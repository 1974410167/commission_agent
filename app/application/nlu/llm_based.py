"""LLM 主路径 NLU。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.application.agent.state import AgentState
from app.application.llm.client import OpenAICompatibleClient
from app.application.llm.models import LLMMessage
from app.application.nlu.base import BaseNLU
from app.common.exceptions import LLMServiceError
from app.config.settings import Settings, get_settings
from app.domain.intent_models import CommissionQuerySlots, EntityScope, GoalType, QueryUnderstanding, TimeScope, TurnType
from app.domain.task_state_models import TaskState, TaskType


JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
VALID_TIME_FIELDS = {"order_confirm_time", "order_complete_time"}
VALID_GROUP_BY = {"media_id", "source_type", "none"}


class LLMBasedNLU(BaseNLU):
    """使用一次 LLM 调用完成“单轮动作理解 + 槽位抽取”。

    这里不再让 LLM 直接决定完整业务执行链路，只负责回答两件事：
    - 这一轮用户在干什么（turn_type）
    - 这一轮显式提到了哪些 slots / 倾向的 task_type

    换句话说：
    - LLM 负责“理解”
    - reducer 负责“状态转移”
    - planner 负责“执行计划”

    这就是当前状态机和过去“一个 intent 混管全部语义”的最大区别。
    """

    mode_name = "llm_based"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = OpenAICompatibleClient(self.settings)
        self.available = bool(self.settings.llm_enabled and self.client.chat_enabled)
        self.mode_name = "llm_based" if self.available else "llm_unavailable"
        self._cache_key: tuple[str, str] | None = None
        self._cache_value: QueryUnderstanding | None = None

    def understand_query(self, state: AgentState) -> QueryUnderstanding:
        """基于当前消息和持久化任务态理解本轮输入。

        这里不会把完整历史会话无脑塞给模型，而是只给“必要上下文”：
        - 当前 task_state
        - 最近几轮用户消息
        - 当前用户消息

        原因是：
        - 历史原文只是语义线索，不是业务真相
        - task_state 才是 reducer 后沉淀下来的结构化真相
        """

        if not self.available:
            raise LLMServiceError("LLM NLU is unavailable because chat configuration is incomplete.")

        task_state = self._coerce_task_state(state.get("task_state"))
        current_utc_epoch = int(datetime.now(timezone.utc).timestamp())
        context_payload = {
            # 这些字段不是让模型自己做状态机，而是给它提供必要背景，
            # 帮它理解当前这句话是新问题、改条件还是补 clarify。
            "task_status": self._enum_value(task_state.status),
            "task_type": self._enum_value(task_state.task_type),
            "pending_requirements": task_state.pending_requirements,
            "normalized_filters": task_state.normalized_filters,
            "selected_tool": task_state.selected_tool,
            "answer_summary": task_state.answer_summary,
            "recent_user_messages": self._recent_user_messages(state),
        }
        cache_key = (state["message"], json.dumps(context_payload, ensure_ascii=False, sort_keys=True))
        if self._cache_key == cache_key and self._cache_value is not None:
            return self._cache_value

        response = self.client.chat(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "你是分佣查询 Agent 的 NLU 模块，只负责把当前用户输入转换成结构化理解结果。"
                        "不要回答问题，只输出 JSON，不要输出 markdown、解释或代码块。\n"
                        "业务范围只有四类：达人分佣汇总、视频是否可分佣/为什么不可分佣、订单什么时候到账、术语规则解释。\n"
                        "输出字段只有：turn_type, entity_scope, goal_type, task_type, confidence, slots。"
                        "task_type 可以是 null，最终任务类型由后端 resolver 决定。\n"
                        "不要臆造 slots，没有明确提到就填 null。\n"
                        "turn_type 定义："
                        "NEW_QUERY=新问题；"
                        "MODIFY_FILTERS=修改当前查询条件或展示方式；"
                        "ANSWER_CLARIFY=补充上一轮缺失参数；"
                        "EXPLAIN=解释术语或规则；"
                        "UNSUPPORTED=无法理解。\n"
                        "entity_scope 定义："
                        "CREATOR=达人维度；"
                        "MEDIA=视频维度；"
                        "ORDER=订单维度；"
                        "TERM=术语或规则；"
                        "UNKNOWN=无法判断。\n"
                        "goal_type 定义："
                        "SUMMARY=看汇总；"
                        "STATUS=看状态/是否成立/什么时候发生；"
                        "REASON=看原因；"
                        "COMPARE=看对比；"
                        "EXPLAIN=看解释；"
                        "UNKNOWN=无法判断。\n"
                        "time_scope 定义："
                        "RECENT_7D=最近7天；"
                        "RECENT_30D=最近30天；"
                        "ALL_HISTORY=历史上所有/全部/不限时间/全量。\n"
                        "关键规则："
                        "“是否可分佣”属于 STATUS；"
                        "“为什么不可分佣/为什么没有佣金”属于 REASON；"
                        "“什么时候到账/到账了吗/什么时候打款”属于 ORDER + STATUS；"
                        "“按视频展开”属于 MODIFY_FILTERS，slots.group_by=media_id；"
                        "“对比闭环CPS和开环CPS”属于 MODIFY_FILTERS，entity_scope=CREATOR，goal_type=COMPARE，slots.compare_source_types=[1,2]；"
                        "时间表达统一落到 slots.time_scope："
                        "最近7天/近一周 -> RECENT_7D；"
                        "最近30天/近一个月 -> RECENT_30D；"
                        "历史上所有/全部/不限时间/全量 -> ALL_HISTORY；"
                        "用户问“什么是/解释一下/有什么区别”这类术语问题时，才属于 TERM + EXPLAIN；"
                        "“如何查看/怎么看 + 视频是否可分佣”仍然是视频状态查询，不属于术语解释；"
                        "“我的视频能不能分佣/我的视频是否可分佣”属于 MEDIA + STATUS，不要理解成 CREATOR 汇总；"
                        "当前系统的到账查询只支持订单维度，所以“我的佣金什么时候到账”也应理解成 ORDER + STATUS，"
                        "如果缺订单号则等待后端 clarify，不要改成 CREATOR 汇总；"
                        "“只看最近7天/只看不可分佣订单/按视频展开/对比闭环CPS和开环CPS”通常属于 MODIFY_FILTERS；"
                        "如果当前状态是 clarify，且用户只补一个 id，优先输出 ANSWER_CLARIFY，并继承当前任务语义。\n"
                        "枚举值必须使用数字编码："
                        "is_commission: 1=可分佣, 2=不可分佣；"
                        "source_type: 1=闭环CPS, 2=开环CPS, 3=CPT。\n"
                        "slots 只允许这些字段：creator_id, media_id, shop_order_id, third_party_order_id, "
                        "source_type, is_commission, no_commission_type, transfer_type, region, time_scope, time_field, "
                        "start_time, end_time, compare_source_types, group_by, term。\n"
                        "少量样例：\n"
                        '用户: 帮我查达人88001最近30天分佣情况 -> {"turn_type":"NEW_QUERY","entity_scope":"CREATOR","goal_type":"SUMMARY","task_type":null,"slots":{"creator_id":88001},"confidence":0.96}\n'
                        '用户: 按视频展开 -> {"turn_type":"MODIFY_FILTERS","entity_scope":"CREATOR","goal_type":"SUMMARY","task_type":null,"slots":{"group_by":"media_id"},"confidence":0.95}\n'
                        '用户: 对比闭环CPS和开环CPS -> {"turn_type":"MODIFY_FILTERS","entity_scope":"CREATOR","goal_type":"COMPARE","task_type":null,"slots":{"compare_source_types":[1,2],"group_by":"none"},"confidence":0.95}\n'
                        '用户: 视频990041是否可分佣 -> {"turn_type":"NEW_QUERY","entity_scope":"MEDIA","goal_type":"STATUS","task_type":null,"slots":{"media_id":990041},"confidence":0.96}\n'
                        '用户: 我的视频能不能分佣 -> {"turn_type":"NEW_QUERY","entity_scope":"MEDIA","goal_type":"STATUS","task_type":null,"slots":{},"confidence":0.88}\n'
                        '用户: 怎么看视频是否可分佣 -> {"turn_type":"NEW_QUERY","entity_scope":"MEDIA","goal_type":"STATUS","task_type":null,"slots":{},"confidence":0.88}\n'
                        '用户: 查询这个视频历史上所有的分佣情况 -> {"turn_type":"MODIFY_FILTERS","entity_scope":"MEDIA","goal_type":"STATUS","task_type":null,"slots":{"time_scope":"ALL_HISTORY"},"confidence":0.9}\n'
                        '用户: 视频990041为什么不可分佣 -> {"turn_type":"NEW_QUERY","entity_scope":"MEDIA","goal_type":"REASON","task_type":null,"slots":{"media_id":990041},"confidence":0.97}\n'
                        '用户: 订单SO-20260308-001127什么时候到账 -> {"turn_type":"NEW_QUERY","entity_scope":"ORDER","goal_type":"STATUS","task_type":null,"slots":{"shop_order_id":"SO-20260308-001127"},"confidence":0.98}\n'
                        '用户: 我的佣金什么时候到账 -> {"turn_type":"NEW_QUERY","entity_scope":"ORDER","goal_type":"STATUS","task_type":null,"slots":{},"confidence":0.83}\n'
                        '用户: 解释一下闭环CPS和CPT的区别 -> {"turn_type":"EXPLAIN","entity_scope":"TERM","goal_type":"EXPLAIN","task_type":null,"slots":{"term":"闭环CPS和CPT的区别"},"confidence":0.97}'
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f"当前UTC时间戳：{current_utc_epoch}\n"
                        f"当前任务状态：{json.dumps(context_payload, ensure_ascii=False)}\n"
                        f"当前用户消息：{state['message']}\n"
                        "请返回 JSON，格式为："
                        '{"turn_type":"NEW_QUERY","entity_scope":"CREATOR","goal_type":"SUMMARY","task_type":null,"confidence":0.95,'
                        '"slots":{"creator_id":null,"media_id":null,"shop_order_id":null,'
                        '"third_party_order_id":null,"source_type":null,"is_commission":null,'
                        '"no_commission_type":null,"transfer_type":null,"region":null,"time_scope":null,"time_field":null,'
                        '"start_time":null,"end_time":null,"compare_source_types":null,"group_by":null,"term":null}}'
                    ),
                ),
            ],
            temperature=0.0,
            max_tokens=500,
            response_format={"type": "json_object"},
            raise_on_error=True,
        )

        try:
            parsed = self._parse_json(response.content if response else "")
            understanding = QueryUnderstanding(
                turn_type=TurnType(parsed.get("turn_type", TurnType.UNSUPPORTED.value)),
                entity_scope=self._parse_entity_scope(parsed.get("entity_scope")),
                goal_type=self._parse_goal_type(parsed.get("goal_type")),
                task_type=self._parse_task_type(parsed.get("task_type")),
                confidence=self._coerce_confidence(parsed.get("confidence")),
                slots=CommissionQuerySlots(**self._sanitize_slots_payload(parsed.get("slots", {}))),
            )
        except Exception as exc:
            raise LLMServiceError(f"LLM NLU returned invalid JSON payload: {exc}") from exc

        self._cache_key = cache_key
        self._cache_value = understanding
        return understanding

    @staticmethod
    def _recent_user_messages(state: AgentState) -> list[str]:
        messages = state.get("messages", [])
        return [message.content for message in messages if message.role == "user"][-5:]

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        match = JSON_OBJECT_PATTERN.search(content)
        if not match:
            raise ValueError("no json object found in llm response")
        return json.loads(match.group(0))

    @staticmethod
    def _parse_task_type(value: Any) -> TaskType | None:
        if value in (None, "", "null"):
            return None
        try:
            return TaskType(str(value))
        except ValueError:
            return TaskType.UNKNOWN

    @staticmethod
    def _parse_entity_scope(value: Any) -> EntityScope | None:
        if value in (None, "", "null"):
            return None
        try:
            return EntityScope(str(value))
        except ValueError:
            return EntityScope.UNKNOWN

    @staticmethod
    def _parse_goal_type(value: Any) -> GoalType | None:
        if value in (None, "", "null"):
            return None
        try:
            return GoalType(str(value))
        except ValueError:
            return GoalType.UNKNOWN

    @staticmethod
    def _coerce_confidence(value: Any) -> float | None:
        if value is None:
            return None
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(confidence, 1.0))

    @staticmethod
    def _enum_value(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        return value

    @staticmethod
    def _sanitize_slots_payload(raw_slots: Any) -> dict[str, Any]:
        """只做类型收敛，不再做正则补丁式理解。

        这一层只负责：
        - 把字符串数字转成 int
        - 过滤非法枚举值
        - 统一 list / scalar 的基本类型

        它不再承担过去那种“靠规则强行理解用户输入”的职责。
        """

        if not isinstance(raw_slots, dict):
            return {}

        slots = dict(raw_slots)
        for key in (
            "creator_id",
            "media_id",
            "is_commission",
            "no_commission_type",
            "transfer_type",
            "start_time",
            "end_time",
        ):
            value = slots.get(key)
            if isinstance(value, str):
                stripped = value.strip()
                slots[key] = int(stripped) if stripped.isdigit() else None

        for key in ("shop_order_id", "third_party_order_id", "region", "term"):
            value = slots.get(key)
            if isinstance(value, str):
                slots[key] = value.strip() or None

        time_field = slots.get("time_field")
        slots["time_field"] = time_field if time_field in VALID_TIME_FIELDS else None

        group_by = slots.get("group_by")
        slots["group_by"] = group_by if group_by in VALID_GROUP_BY else None

        time_scope = slots.get("time_scope")
        if time_scope in {scope.value for scope in TimeScope}:
            slots["time_scope"] = time_scope
        else:
            slots["time_scope"] = None

        if slots.get("is_commission") not in (None, 1, 2):
            slots["is_commission"] = None

        for key in ("source_type", "compare_source_types"):
            value = slots.get(key)
            if isinstance(value, list):
                cleaned = []
                for item in value:
                    if isinstance(item, int):
                        cleaned.append(item)
                    elif isinstance(item, str) and item.strip().isdigit():
                        cleaned.append(int(item.strip()))
                slots[key] = cleaned or None
            elif isinstance(value, str):
                stripped = value.strip()
                slots[key] = [int(stripped)] if stripped.isdigit() else None

        return slots

    @staticmethod
    def _coerce_task_state(value: Any) -> TaskState:
        if isinstance(value, TaskState):
            return value
        if isinstance(value, dict):
            return TaskState(**value)
        return TaskState()
