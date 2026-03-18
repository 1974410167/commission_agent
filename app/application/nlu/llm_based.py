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
from app.domain.intent_models import CommissionQuerySlots, EntityScope, GoalType, QueryUnderstanding, TurnType
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
                        "你是分佣查询 Agent 的 NLU 模块。"
                        "你只负责理解当前这一轮用户输入，并返回一个 JSON 对象。"
                        "只能输出 JSON，不要输出解释、markdown、代码块。"
                        "不要臆造参数，不确定就填 null。\n"
                        "turn_type 只能是：NEW_QUERY, MODIFY_FILTERS, ANSWER_CLARIFY, EXPLAIN, UNSUPPORTED。\n"
                        "entity_scope 只能是：CREATOR, MEDIA, ORDER, TERM, UNKNOWN 或 null。\n"
                        "goal_type 只能是：SUMMARY, STATUS, REASON, COMPARE, EXPLAIN, UNKNOWN 或 null。\n"
                        "task_type 可以留空或填 null，最终任务类型由后端 resolver 决定。\n"
                        "如果用户是在当前任务基础上改条件，如“只看最近7天”“只看不可分佣订单”“按视频展开”，"
                        "turn_type 应是 MODIFY_FILTERS，只返回本轮新增或修改的 slots，"
                        "并尽量保持 entity_scope / goal_type 与当前任务一致。\n"
                        "枚举值必须使用数字编码："
                        "is_commission: 1=可分佣, 2=不可分佣；"
                        "source_type: 1=闭环CPS, 2=开环CPS, 3=CPT。\n"
                        "如果历史状态显示上一轮在 clarify，当前消息是在补 creator_id / media_id / shop_order_id 等参数，"
                        "turn_type 应是 ANSWER_CLARIFY，并优先继承当前任务状态中的 entity_scope / goal_type 语义，"
                        "不要因为补一个 id 就改成别的任务。\n"
                        "如果用户是在解释术语或规则含义，turn_type 应是 EXPLAIN，entity_scope 应是 TERM，goal_type 应是 EXPLAIN。\n"
                        "关键示例：\n"
                        "1. 如果当前任务是达人分佣汇总，用户说“只看不可分佣订单”，"
                        '返回 {"turn_type":"MODIFY_FILTERS","entity_scope":"CREATOR","goal_type":"SUMMARY","slots":{"is_commission":2}}。\n'
                        "2. 如果当前任务是达人分佣汇总，用户说“按视频展开”，"
                        '返回 {"turn_type":"MODIFY_FILTERS","entity_scope":"CREATOR","goal_type":"SUMMARY","slots":{"group_by":"media_id"}}。\n'
                        "3. 如果当前任务是达人分佣汇总，用户说“对比闭环CPS和开环CPS”，"
                        '返回 {"turn_type":"MODIFY_FILTERS","entity_scope":"CREATOR","goal_type":"COMPARE","slots":{"compare_source_types":[1,2],"group_by":"none"}}。\n'
                        "4. 如果用户说“帮我查询视频990000是否可分佣”，"
                        '返回 {"turn_type":"NEW_QUERY","entity_scope":"MEDIA","goal_type":"STATUS","slots":{"media_id":990000}}。\n'
                        "5. 如果当前任务是视频分佣状态查询，历史状态处于 clarify 且缺 media_id，用户说“media_id: 990041”，"
                        '返回 {"turn_type":"ANSWER_CLARIFY","entity_scope":"MEDIA","goal_type":"STATUS","slots":{"media_id":990041}}。\n'
                        "6. 如果当前任务是视频不可分佣原因查询，历史状态处于 clarify 且缺 media_id，用户说“media_id: 990041”，"
                        '返回 {"turn_type":"ANSWER_CLARIFY","entity_scope":"MEDIA","goal_type":"REASON","slots":{"media_id":990041}}。\n'
                        "7. 如果用户说“只看最近7天”，应把 start_time 和 end_time 计算成 epoch_second，"
                        "end_time 使用当前 UTC 时间，start_time 为 end_time 往前 7 天。\n"
                        "8. 如果用户在解释术语，如“闭环CPS和CPT的区别”，"
                        '返回 {"turn_type":"EXPLAIN","entity_scope":"TERM","goal_type":"EXPLAIN","slots":{"term":"闭环CPS和CPT的区别"}}。\n'
                        "9. 如果用户说“如何查看我的视频是否可分佣”，说明他在问视频维度的分佣状态问题；"
                        '若没有给 media_id，返回 {"turn_type":"NEW_QUERY","entity_scope":"MEDIA","goal_type":"STATUS","slots":{}}。\n'
                        "10. 如果用户说“我的视频能不能分佣”，这仍然是视频分佣状态问题；"
                        '若没有 media_id，返回 {"turn_type":"NEW_QUERY","entity_scope":"MEDIA","goal_type":"STATUS","slots":{}}。\n'
                        "11. 如果用户说“视频990041为什么不可分佣”，这是视频原因查询，"
                        '返回 {"turn_type":"NEW_QUERY","entity_scope":"MEDIA","goal_type":"REASON","slots":{"media_id":990041}}。\n'
                        "12. 如果用户说“视频为什么没有分佣”或“我的视频为什么没有分佣”，"
                        '这属于视频不可分佣原因问题；若没有 media_id，返回 {"turn_type":"NEW_QUERY","entity_scope":"MEDIA","goal_type":"REASON","slots":{}}。\n'
                        "slots 只允许这些字段：creator_id, media_id, shop_order_id, third_party_order_id, "
                        "source_type, is_commission, no_commission_type, transfer_type, region, time_field, "
                        "start_time, end_time, compare_source_types, group_by, term。"
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
                        '"no_commission_type":null,"transfer_type":null,"region":null,"time_field":null,'
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
