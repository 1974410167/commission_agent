"""Commission Agent 的工作流节点实现。

这份文件是当前状态机最核心的执行层。

可以把它按职责分成 5 段来看：
1. `understand_query`
   - 只负责“理解本轮输入”
   - 不直接决定最终工具路由
2. `reduce_state`
   - 真正的状态转移层
   - 把上一轮任务态和本轮理解结果合成新的 task_state
3. `normalize_and_validate`
   - 纯后端确定性层
   - 只做标准化、权限校验、缺参判断
4. `build_query_plan_node` / `execute_tool`
   - 把稳定的任务态翻译成可执行计划并执行
5. `compose_answer`
   - 用结构化结果组织最终回答

也就是说，这里已经不是“模型直接决定一切”的黑盒，而是一套分层状态机。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.application.agent.planner import build_query_plan
from app.application.agent.prompts import DEFAULT_SUGGESTIONS, UNKNOWN_CAPABILITY_HINT
from app.application.agent.reducer import reduce_task_state
from app.application.agent.resolver import resolve_task_type
from app.application.agent.state import AgentState
from app.application.nlu.factory import NLUFactory
from app.application.tools.commission_tools import CommissionTools
from app.application.tools.knowledge_tools import KnowledgeTools
from app.config.settings import get_settings
from app.domain.agent_models import ConversationMessage
from app.domain.enums import ENUM_ZH_MAPPINGS, TransferType
from app.domain.intent_models import (
    AgentIntent,
    ChatResponse,
    CommissionQuerySlots,
    NormalizedFilters,
    TurnType,
)
from app.domain.knowledge_models import EvidenceItem
from app.domain.query_plan_models import QueryPlan, QueryPlanMode
from app.domain.task_state_models import TaskState, TaskStatus, TaskType


settings = get_settings()
commission_tools = CommissionTools()
knowledge_tools = KnowledgeTools()


def understand_query(state: AgentState) -> AgentState:
    """一次 LLM 调用完成本轮动作理解和槽位抽取。

    这里的输出是 `QueryUnderstanding`，重点回答：
    - 这句话是在新开任务、改条件、补 clarify，还是做 explain
    - 当前提到了哪些 slots
    - 倾向于哪一类 task_type

    这里故意不直接产出最终工具路由，避免让一轮 LLM 理解结果直接主宰整条链路。
    """

    nlu = NLUFactory.create()
    understanding = nlu.understand_query(state)
    return {
        "nlu_mode": getattr(nlu, "mode_name", "llm_based"),
        "understanding": understanding,
        "slots": understanding.slots,
        "llm_call_count": state.get("llm_call_count", 0) + 1,
    }


def reduce_state(state: AgentState) -> AgentState:
    """把单轮理解结果收敛为新的任务态。

    这里不再做“按历史快照打补丁”的思路，而是统一走 reducer：
    - 上一轮 task_state
    - 当前轮 turn_understanding
    -> 下一轮 task_state

    你可以把它理解成整个状态机的“扭转器/状态转移器”：
    - 不是简单 merge 历史
    - 而是明确决定当前会话任务应该如何演化
    """

    understanding = state["understanding"]
    resolved_task_type = resolve_task_type(understanding)
    resolved_understanding = understanding.model_copy(update={"task_type": resolved_task_type})
    previous_task_state = _coerce_task_state(state.get("task_state"))
    next_task_state = reduce_task_state(previous_task_state, resolved_understanding)
    return {
        "understanding": resolved_understanding,
        "task_state": next_task_state,
        "slots": CommissionQuerySlots(**next_task_state.normalized_filters),
        "intent": _task_state_to_base_intent(next_task_state),
    }


def normalize_and_validate(state: AgentState) -> AgentState:
    """归一化槽位、补默认值、做权限和缺参校验。

    这一层非常重要，因为它和 LLM 理解职责是刻意分开的：
    - LLM 负责理解“用户在说什么”
    - 这里负责把结果变成“系统可执行、可校验、可审计”的结构化条件

    所以这里只允许保留确定性逻辑，例如：
    - 时间标准化
    - source_type 归一化
    - creator 权限校验
    - 缺参检测

    而不再承担正则打补丁式的语义理解职责。
    """

    user_context = state["user_context"]
    task_state = _coerce_task_state(state.get("task_state"))
    slots = CommissionQuerySlots(**task_state.normalized_filters)
    data = slots.model_dump()
    now = datetime.now(timezone.utc)
    normalized: dict[str, Any] = {
        "creator_id": data.get("creator_id"),
        "media_id": data.get("media_id"),
        "shop_order_id": data.get("shop_order_id"),
        "third_party_order_id": data.get("third_party_order_id"),
        "source_type": _normalize_source_type(data.get("source_type")),
        "is_commission": data.get("is_commission"),
        "no_commission_type": data.get("no_commission_type"),
        "transfer_type": data.get("transfer_type"),
        "region": data.get("region"),
        "time_field": data.get("time_field"),
        "start_time": data.get("start_time"),
        "end_time": data.get("end_time"),
        "compare_source_types": data.get("compare_source_types"),
        "group_by": data.get("group_by") or "none",
        "term": data.get("term"),
    }
    _apply_relative_time_standardization(state.get("message", ""), normalized, now)

    if user_context.user_role == "creator":
        # 权限校验始终必须在后端完成，不能依赖 prompt 约束。
        # creator 只能查自己的 creator_id，这是高优先级硬规则。
        bound_creator_id = user_context.bound_creator_id
        requested_creator_id = normalized.get("creator_id")
        understanding = state.get("understanding")
        explicit_creator_in_turn = False
        if understanding is not None:
            explicit_creator_in_turn = understanding.slots.creator_id is not None

        # 如果这一轮只是 follow-up/改条件，没有显式再次指定 creator_id，
        # 那么即便上一轮 task_state 中残留了别人的 creator_id，也应该回归当前登录 creator。
        if requested_creator_id is None or (
            not explicit_creator_in_turn
            and understanding is not None
            and understanding.turn_type == TurnType.MODIFY_FILTERS
        ):
            normalized["creator_id"] = bound_creator_id
        elif requested_creator_id != bound_creator_id:
            denial_answer = (
                f"creator 角色只能查询绑定达人 {bound_creator_id} 的数据，"
                f"当前请求的 creator_id={requested_creator_id} 无权限访问。"
            )
            denied_task_state = task_state.model_copy(
                update={
                    "normalized_filters": NormalizedFilters(**normalized).model_dump(),
                    "pending_requirements": [],
                    "status": TaskStatus.UNSUPPORTED,
                    "action": "answer",
                    "last_result_summary": denial_answer,
                    "answer_summary": denial_answer,
                }
            )
            return {
                "task_state": denied_task_state,
                "normalized_filters": NormalizedFilters(**normalized).model_dump(),
                "route_status": "unsupported",
                "action": "answer",
                "answer": denial_answer,
                "answer_summary": denial_answer,
                "last_result_summary": denial_answer,
                "missing_slots": [],
                "evidence": [],
                "next_suggestions": ["查询我最近 30 天分佣情况", "按视频展开我的最近 7 天不可分佣订单"],
            }

    if task_state.task_type == TaskType.CREATOR_COMMISSION and (
        normalized["start_time"] is None or normalized["end_time"] is None
    ):
        # 达人分佣查询如果用户没明确说时间范围，则默认补最近 30 天。
        # 这是“默认值补齐”，不是语义猜测。
        normalized["time_field"] = normalized["time_field"] or "order_confirm_time"
        normalized["end_time"] = int(now.timestamp())
        normalized["start_time"] = int((now - timedelta(days=30)).timestamp())

    if task_state.task_type == TaskType.MEDIA_COMMISSION_STATUS and (
        normalized["start_time"] is None or normalized["end_time"] is None
    ):
        normalized["time_field"] = normalized["time_field"] or "order_confirm_time"
        normalized["end_time"] = int(now.timestamp())
        normalized["start_time"] = int((now - timedelta(days=30)).timestamp())

    missing_slots: list[str] = []
    # 缺参判断跟 task_type 强相关：
    # - 达人查询缺 creator_id
    # - 视频原因查询缺 media_id
    # - 订单状态缺 order_id
    # 这也是为什么 task_state 必须先于 route_tool 稳定下来。
    if task_state.task_type == TaskType.CREATOR_COMMISSION and normalized.get("creator_id") is None:
        missing_slots.append("creator_id")
    if task_state.task_type == TaskType.MEDIA_COMMISSION_STATUS and normalized.get("media_id") is None:
        missing_slots.append("media_id")
    if task_state.task_type == TaskType.MEDIA_NO_COMMISSION_REASON and normalized.get("media_id") is None:
        missing_slots.append("media_id")
    if task_state.task_type == TaskType.ORDER_TRANSFER_STATUS and not (
        normalized.get("shop_order_id") or normalized.get("third_party_order_id")
    ):
        missing_slots.append("shop_order_id")
    if task_state.task_type == TaskType.TERM_EXPLAIN and not normalized.get("term"):
        missing_slots.append("term")
    if task_state.task_type == TaskType.CREATOR_COMMISSION and len(normalized.get("compare_source_types") or []) == 1:
        missing_slots.append("compare_source_types")

    route_status = "route"
    if missing_slots:
        route_status = "clarify"
    elif task_state.task_type in {None, TaskType.UNKNOWN}:
        route_status = "unsupported"

    # normalize 后会把最新的 normalized_filters 和 pending_requirements 写回 task_state，
    # 从这一步开始，后续 planner / answer 统一读取这份任务态。
    next_task_state = task_state.model_copy(
        update={
            "normalized_filters": NormalizedFilters(**normalized).model_dump(),
            "pending_requirements": missing_slots,
            "status": TaskStatus.CLARIFYING if missing_slots else (
                TaskStatus.UNSUPPORTED if route_status == "unsupported" else TaskStatus.READY
            ),
        }
    )
    return {
        "task_state": next_task_state,
        "intent": _task_state_to_base_intent(next_task_state),
        "normalized_filters": NormalizedFilters(**normalized).model_dump(),
        "missing_slots": missing_slots,
        "route_status": route_status,
    }


def clarify_if_needed(state: AgentState) -> AgentState:
    """生成 clarify 响应，并把当前任务态直接写回 state。

    clarify 不再只是“一句追问文案”，而是状态机中的正式状态：
    - task_state.status = CLARIFYING
    - pending_requirements 明确记录还缺什么

    下一轮用户补充信息时，LLM 会在当前 task_state 背景下重新理解，
    而不是再走过去那种重 regex patch 的修补思路。
    """

    missing_slots = state.get("missing_slots", [])
    question = _clarify_question(_coerce_task_state(state.get("task_state")), missing_slots)
    response = ChatResponse(
        action="clarify",
        answer=question,
        normalized_filters=state.get("normalized_filters", {}),
        evidence=[],
        next_suggestions=DEFAULT_SUGGESTIONS,
        missing_slots=missing_slots,
        intent=_intent_for_response(state).value,
        debug=_build_debug(
            {
                **state,
                "action": "clarify",
                "answer": question,
                "answer_summary": question,
                "last_result_summary": question,
                "evidence": [],
                "next_suggestions": DEFAULT_SUGGESTIONS,
            }
        ),
    )
    updated_messages = _append_turn_messages(state, question)
    next_task_state = _coerce_task_state(state.get("task_state")).model_copy(
        update={
            "status": TaskStatus.CLARIFYING,
            "pending_requirements": missing_slots,
            "normalized_filters": state.get("normalized_filters", {}),
            "selected_tool": None,
            "action": "clarify",
            "last_result_summary": question,
            "answer_summary": question,
        }
    )
    return {
        "action": "clarify",
        "clarify_question": question,
        "answer": question,
        "answer_summary": question,
        "last_result_summary": question,
        "evidence": [],
        "next_suggestions": DEFAULT_SUGGESTIONS,
        "messages": updated_messages,
        "task_state": next_task_state,
        "response": response,
    }


def build_query_plan_node(state: AgentState) -> AgentState:
    """根据任务态生成执行计划。

    这一层开始，系统已经不再问“用户在说什么”，而只问：
    - 当前 task_state 是否足够稳定
    - 这一轮应该按什么模式执行

    这也是 `task_state -> query_plan -> tool` 这条链成立的关键。
    """

    task_state = _coerce_task_state(state.get("task_state")).model_copy(
        update={"normalized_filters": state.get("normalized_filters", {})}
    )
    plan = build_query_plan(task_state)
    if plan.mode == QueryPlanMode.UNSUPPORTED or not plan.tool_name:
        unsupported_answer = f"{UNKNOWN_CAPABILITY_HINT} 你可以直接给我达人、视频或订单编号。"
        return {
            "route_status": "unsupported",
            "selected_tool": None,
            "query_plan": plan,
            "intent": AgentIntent.UNKNOWN,
            "action": "answer",
            "answer": unsupported_answer,
            "answer_summary": unsupported_answer,
            "last_result_summary": unsupported_answer,
            "evidence": [],
            "next_suggestions": DEFAULT_SUGGESTIONS,
        }
    return {
        "query_plan": plan,
        "selected_tool": plan.tool_name,
        "intent": plan.response_intent,
        "route_status": "execute",
    }


def execute_tool(state: AgentState) -> AgentState:
    """执行工具，并在需要时追加规则解释。

    这里的原则是：
    - 事实来自 ES
    - 规则解释来自知识库
    - explain 类问题可以在工具层内部再做一次 LLM 组织答案

    也就是说，并不是所有问题都会在 compose_answer 时再次调用 LLM。
    查询类问题尽量保持模板化，避免事实被二次改写。
    """

    plan = _coerce_query_plan(state.get("query_plan"))
    filters = NormalizedFilters(**(plan.filters or state["normalized_filters"]))
    tool_name = plan.tool_name or state["selected_tool"]
    result = None
    rule_explanation = None
    llm_calls = state.get("llm_call_count", 0)

    if tool_name == "get_creator_commission_summary":
        result = commission_tools.get_creator_commission_summary(filters)
    elif tool_name == "get_media_commission_status":
        result = commission_tools.get_media_commission_status(filters)
    elif tool_name == "get_media_no_commission_breakdown":
        result = commission_tools.get_media_no_commission_breakdown(filters)
        # 视频不可分佣原因只在“确实有不可分佣订单”时再补知识解释。
        # 否则用户问“为什么不可分佣”，而事实结果是 0 笔不可分佣，
        # 再去检索知识库只会把无关规则（如 T+2）拼进回答。
        if (
            result is not None
            and result.non_commissionable_orders > 0
            and bool(result.no_commission_type_distribution)
        ):
            rule_explanation = knowledge_tools.explain_rule_with_context(
                fact_payload=result.model_dump(),
                query=None,
            )
    elif tool_name == "get_order_transfer_status":
        result = commission_tools.get_order_transfer_status(filters)
        if result is not None:
            rule_explanation = knowledge_tools.explain_rule_with_context(
                fact_payload=result.model_dump(),
                query=state["message"],
            )
    elif tool_name == "summarize_commission_by_media":
        result = commission_tools.summarize_commission_by_media(filters)
    elif tool_name == "compare_source_type_commission":
        result = commission_tools.compare_source_type_commission(filters)
    elif tool_name == "explain_business_term":
        # explain 是少数允许“检索后再调用 LLM 统一组织答案”的场景。
        # 查询类问题则尽量避免在最终回答阶段再调 LLM，以保持事实稳定。
        result = knowledge_tools.explain_business_term(
            filters.term or state["message"],
            context={
                "history": _recent_user_messages(state)[-3:],
                "previous_intent": _task_state_to_base_intent(_coerce_task_state(state.get("task_state"))).value,
                "previous_answer_summary": _coerce_task_state(state.get("task_state")).answer_summary,
            },
        )
        llm_calls += 1

    if result is None:
        empty_answer = "没有查到匹配结果，请确认编号或筛选条件。"
        return {
            "tool_result": None,
            "rule_explanation": rule_explanation,
            "action": "answer",
            "answer": empty_answer,
            "answer_summary": empty_answer,
            "last_result_summary": empty_answer,
            "evidence": [],
            "next_suggestions": DEFAULT_SUGGESTIONS,
            "llm_call_count": llm_calls,
        }

    if state["user_context"].user_role == "creator":
        result_creator_id = getattr(result, "creator_id", None)
        if result_creator_id is not None and result_creator_id != state["user_context"].bound_creator_id:
            denied_answer = "当前登录身份无权限查看这条结果。"
            return {
                "tool_result": None,
                "rule_explanation": rule_explanation,
                "action": "answer",
                "answer": denied_answer,
                "answer_summary": denied_answer,
                "last_result_summary": denied_answer,
                "evidence": [],
                "next_suggestions": ["查询我最近 30 天分佣情况"],
                "llm_call_count": llm_calls,
            }

    return {"tool_result": result, "rule_explanation": rule_explanation, "llm_call_count": llm_calls}


def compose_answer(state: AgentState) -> AgentState:
    """把结构化结果和错误态统一组装成最终响应。

    这里有一个重要设计取舍：
    - 查询类回答尽量走模板化组织
    - explain 类允许工具层先检索知识，再让 LLM 组织文本

    这样可以兼顾：
    - 查询类的稳定、可控、可追溯
    - explain 类的自然表达能力
    """

    if state.get("tool_result") is None:
        # unsupported / 没查到结果 / clarify 等“无结构化结果”的场景都从这里统一出响应。
        answer = state.get("answer") or f"{UNKNOWN_CAPABILITY_HINT} 你可以直接给我达人、视频或订单编号。"
        response = ChatResponse(
            action=state.get("action", "answer"),
            answer=answer,
            normalized_filters=state.get("normalized_filters", {}),
            evidence=state.get("evidence", []),
            next_suggestions=state.get("next_suggestions", DEFAULT_SUGGESTIONS),
            missing_slots=state.get("missing_slots") if state.get("action") == "clarify" else None,
            intent=_intent_for_response(state).value,
            debug=_build_debug(state),
        )
        updated_messages = _append_turn_messages(state, answer)
        last_summary = state.get("last_result_summary") or answer
        next_task_state = _coerce_task_state(state.get("task_state")).model_copy(
            update={
                "normalized_filters": state.get("normalized_filters", {}),
                "pending_requirements": state.get("missing_slots", []),
                "selected_tool": state.get("selected_tool"),
                "status": TaskStatus.CLARIFYING if state.get("action") == "clarify" else TaskStatus.UNSUPPORTED,
                "action": state.get("action", "answer"),
                "last_result_summary": last_summary,
                "answer_summary": answer,
            }
        )
        return {
            "messages": updated_messages,
            "task_state": next_task_state,
            "response": response,
        }

    intent = state["intent"]
    filters = state["normalized_filters"]
    result = state["tool_result"]
    rule_explanation = state.get("rule_explanation")
    answer = ""
    last_result_summary = ""
    evidence: list[EvidenceItem] = []

    if intent == AgentIntent.QUERY_CREATOR_SUMMARY:
        # 达人汇总属于典型“结构化查询回答”，适合模板化输出。
        source_distribution = _translate_distribution("source_type", result.source_type_distribution)
        no_commission_distribution = _translate_distribution(
            "no_commission_type", result.no_commission_type_distribution
        )
        answer = (
            f"查询范围为 {_format_time_range(filters)}。达人 {result.creator_id} 共有 {result.total_orders} 笔订单，"
            f"可分佣 {result.commissionable_orders} 笔，不可分佣 {result.non_commissionable_orders} 笔，"
            f"总佣金 {result.total_commission_amount:.2f}。主要来源分布为 {_distribution_sentence(source_distribution)}。"
        )
        last_result_summary = (
            f"达人 {result.creator_id}，{_format_time_range(filters)}，"
            f"{result.total_orders} 单，佣金 {result.total_commission_amount:.2f}。"
        )
        evidence = [
            _es_fact_evidence(
                "达人分佣汇总",
                f"达人 {result.creator_id}，{_format_time_range(filters)}，总订单 {result.total_orders}，总佣金 {result.total_commission_amount:.2f}。",
            ),
            _es_fact_evidence("来源类型分布", _distribution_sentence(source_distribution)),
            _es_fact_evidence("不可分佣原因分布", _distribution_sentence(no_commission_distribution)),
        ]
    elif intent == AgentIntent.QUERY_MEDIA_COMMISSION_STATUS:
        source_distribution = _translate_distribution("source_type", result.source_type_distribution)
        no_commission_distribution = _translate_distribution(
            "no_commission_type", result.no_commission_type_distribution
        )
        if result.total_orders == 0:
            answer = f"查询范围为 {_format_time_range(filters)}。视频 {result.media_id} 当前没有命中订单，暂时无法判断是否可分佣。"
        elif result.non_commissionable_orders == 0:
            answer = (
                f"查询范围为 {_format_time_range(filters)}。视频 {result.media_id} 当前命中 {result.total_orders} 笔订单，"
                f"全部可分佣，总佣金 {result.total_commission_amount:.2f}。主要来源分布为 {_distribution_sentence(source_distribution)}。"
            )
        elif result.commissionable_orders == 0:
            answer = (
                f"查询范围为 {_format_time_range(filters)}。视频 {result.media_id} 当前命中 {result.total_orders} 笔订单，"
                f"全部不可分佣。主要不可分佣原因分布为 {_distribution_sentence(no_commission_distribution)}。"
            )
        else:
            answer = (
                f"查询范围为 {_format_time_range(filters)}。视频 {result.media_id} 当前命中 {result.total_orders} 笔订单，"
                f"可分佣 {result.commissionable_orders} 笔，不可分佣 {result.non_commissionable_orders} 笔，"
                f"总佣金 {result.total_commission_amount:.2f}。主要来源分布为 {_distribution_sentence(source_distribution)}。"
            )
        last_result_summary = (
            f"视频 {result.media_id}，{_format_time_range(filters)}，"
            f"总订单 {result.total_orders}，可分佣 {result.commissionable_orders}，"
            f"不可分佣 {result.non_commissionable_orders}。"
        )
        evidence = [
            _es_fact_evidence("视频分佣状态", last_result_summary),
            _es_fact_evidence("来源类型分布", _distribution_sentence(source_distribution)),
            _es_fact_evidence("不可分佣原因分布", _distribution_sentence(no_commission_distribution)),
        ]
    elif intent == AgentIntent.QUERY_MEDIA_NO_COMMISSION_REASON:
        # 视频不可分佣原因是 hybrid 场景：
        # - ES 提供事实统计
        # - knowledge 提供规则解释
        reason_distribution = _translate_distribution("no_commission_type", result.no_commission_type_distribution)
        answer = (
            f"视频 {result.media_id} 当前命中的不可分佣订单共有 {result.non_commissionable_orders} 笔。"
            f"主要原因分布为 {_distribution_sentence(reason_distribution)}。"
        )
        if (
            result.non_commissionable_orders > 0
            and rule_explanation is not None
            and rule_explanation.answer.strip()
        ):
            answer += f" 结合规则说明：{rule_explanation.answer}"
        last_result_summary = (
            f"视频 {result.media_id} 不可分佣 {result.non_commissionable_orders} 笔；"
            f"{_distribution_sentence(reason_distribution)}。"
        )
        evidence = [
            _es_fact_evidence(
                "视频不可分佣统计",
                last_result_summary,
            ),
        ]
        if result.non_commissionable_orders > 0 and rule_explanation is not None and rule_explanation.evidence:
            evidence.extend(rule_explanation.evidence)
    elif intent == AgentIntent.QUERY_ORDER_TRANSFER_STATUS:
        # 订单状态回答以事实为主；只有知识解释足够相关时才追加规则说明。
        answer = _compose_order_status_answer(result, rule_explanation)
        last_result_summary = (
            f"订单 {result.shop_order_id}，状态 {_enum_label('transfer_type', result.transfer_type)}，"
            f"佣金 {result.commission_amount:.2f}。"
        )
        evidence = [
            _es_fact_evidence(
                "订单到账事实",
                last_result_summary,
            ),
        ]
        if rule_explanation is not None and rule_explanation.evidence:
            evidence.extend(rule_explanation.evidence)
    elif intent == AgentIntent.SUMMARIZE_BY_MEDIA:
        # “按视频展开”不是新任务，只是同一达人分佣任务的另一种展示计划。
        top_items = [item.model_dump() for item in result.items[:5]]
        answer = (
            f"达人 {result.creator_id} 已按视频展开，当前命中 {len(result.items)} 个视频。"
            "下面 evidence 中列出了订单量最高的前 5 个视频。"
        )
        last_result_summary = f"达人 {result.creator_id} 按视频展开，命中 {len(result.items)} 个视频。"
        evidence = [
            _es_fact_evidence(
                "按视频汇总",
                f"达人 {result.creator_id} 当前命中 {len(result.items)} 个视频，前 5 个视频已在 evidence 中展开。",
            )
        ]
        evidence.extend(
            _es_fact_evidence(
                f"视频 {item['media_id']}",
                (
                    f"总订单 {item['total_orders']}，可分佣 {item['commissionable_orders']}，"
                    f"不可分佣 {item['non_commissionable_orders']}，总佣金 {item['total_commission_amount']:.2f}。"
                ),
            )
            for item in top_items
        )
    elif intent == AgentIntent.COMPARE_SOURCE_TYPE:
        # 同理，“来源类型对比”也是同一任务下的另一种 plan。
        lines = [
            (
                f"{_enum_label('source_type', item.source_type)}: {item.total_orders} 单，可分佣 {item.commissionable_orders}，"
                f"不可分佣 {item.non_commissionable_orders}，佣金 {item.total_commission_amount:.2f}"
            )
            for item in result.items
        ]
        answer = f"达人 {result.creator_id} 的来源类型对比结果如下：" + "；".join(lines)
        last_result_summary = f"达人 {result.creator_id} 的来源类型对比结果：" + "；".join(lines)
        evidence = [_es_fact_evidence("来源类型对比", line) for line in lines]
    elif intent == AgentIntent.EXPLAIN_BUSINESS_TERM:
        # explain 类回答由 knowledge tool 负责组织好主答案，这里只做透传。
        answer = result.answer
        last_result_summary = result.answer
        evidence = result.evidence

    response_intent = _intent_for_response(state)
    response = ChatResponse(
        action="answer",
        answer=answer,
        normalized_filters=filters,
        evidence=evidence,
        next_suggestions=DEFAULT_SUGGESTIONS,
        missing_slots=None,
        intent=response_intent.value,
        debug=_build_debug(state, rule_explanation=rule_explanation, tool_result=result),
    )
    updated_messages = _append_turn_messages(state, answer)
    next_task_state = _coerce_task_state(state.get("task_state")).model_copy(
        update={
            "normalized_filters": filters,
            "pending_requirements": [],
            "selected_tool": state.get("selected_tool"),
            "status": TaskStatus.READY,
            "action": "answer",
            "last_result_summary": last_result_summary or answer,
            "answer_summary": answer,
        }
    )
    return {
        "action": "answer",
        "answer": answer,
        "answer_summary": answer,
        "last_result_summary": last_result_summary or answer,
        "evidence": evidence,
        "next_suggestions": DEFAULT_SUGGESTIONS,
        "messages": updated_messages,
        "task_state": next_task_state,
        "response": response,
    }


def _coerce_intent(value: Any) -> AgentIntent | None:
    if value is None:
        return None
    if isinstance(value, AgentIntent):
        return value
    return AgentIntent(str(value))


def _intent_value(value: Any) -> str | None:
    intent = _coerce_intent(value)
    return intent.value if intent is not None else None


def _coerce_task_state(value: Any) -> TaskState:
    if isinstance(value, TaskState):
        return value
    if isinstance(value, dict):
        return TaskState(**value)
    return TaskState()


def _coerce_query_plan(value: Any) -> QueryPlan:
    if isinstance(value, QueryPlan):
        return value
    if isinstance(value, dict):
        return QueryPlan(**value)
    return QueryPlan(mode=QueryPlanMode.UNSUPPORTED)


def _task_state_to_base_intent(task_state: TaskState) -> AgentIntent:
    if task_state.task_type == TaskType.CREATOR_COMMISSION:
        return AgentIntent.QUERY_CREATOR_SUMMARY
    if task_state.task_type == TaskType.MEDIA_COMMISSION_STATUS:
        return AgentIntent.QUERY_MEDIA_COMMISSION_STATUS
    if task_state.task_type == TaskType.MEDIA_NO_COMMISSION_REASON:
        return AgentIntent.QUERY_MEDIA_NO_COMMISSION_REASON
    if task_state.task_type == TaskType.ORDER_TRANSFER_STATUS:
        return AgentIntent.QUERY_ORDER_TRANSFER_STATUS
    if task_state.task_type == TaskType.TERM_EXPLAIN:
        return AgentIntent.EXPLAIN_BUSINESS_TERM
    return AgentIntent.UNKNOWN


def _intent_for_response(state: AgentState) -> AgentIntent:
    """决定响应里暴露给前端的 intent。

    顺序上优先：
    1. 当前节点已经明确写入的 intent
    2. planner 产出的 response_intent
    3. 从 task_state 映射出来的基础 intent

    这样做是为了把“内部任务态”和“外部展示意图”分开。
    """

    intent = state.get("intent")
    if isinstance(intent, AgentIntent):
        return intent
    plan = state.get("query_plan")
    if plan:
        return _coerce_query_plan(plan).response_intent
    return _task_state_to_base_intent(_coerce_task_state(state.get("task_state")))


def _recent_user_messages(state: AgentState) -> list[str]:
    """只提取最近用户消息，供 explain 场景做轻量上下文补充。"""

    messages = state.get("messages", [])
    return [message.content for message in messages if message.role == "user"]


def _append_turn_messages(state: AgentState, assistant_answer: str) -> list[ConversationMessage]:
    """把当前轮 user/assistant 消息附加回 state，并截断到最近 10 条。"""

    messages = [
        *state.get("messages", []),
        ConversationMessage(role="user", content=state["message"]),
        ConversationMessage(role="assistant", content=assistant_answer),
    ]
    return messages[-10:]


def _normalize_source_type(source_type: int | list[int] | None) -> list[int] | None:
    """统一把 source_type 收敛成 list，方便后续 planner / repository 处理。"""

    if source_type is None:
        return None
    if isinstance(source_type, list):
        return source_type
    return [source_type]


def _clarify_question(task_state: TaskState, missing_slots: list[str]) -> str:
    """把缺失字段转换成面向用户的追问文案。

    追问文案不能只看槽位名，还要看当前任务类型。否则：
    - `MEDIA_COMMISSION_STATUS`
    - `MEDIA_NO_COMMISSION_REASON`
    都缺 `media_id` 时，会共用同一句错误提示。
    """

    media_question = "需要先提供 media_id。"
    if task_state.task_type == TaskType.MEDIA_COMMISSION_STATUS:
        media_question = "需要先提供 media_id，才能继续判断视频是否可分佣。"
    elif task_state.task_type == TaskType.MEDIA_NO_COMMISSION_REASON:
        media_question = "需要先提供 media_id，才能继续查视频不可分佣原因。"

    mapping = {
        "creator_id": "需要先提供 creator_id，或者在 creator 模式下传 bound_creator_id。",
        "media_id": media_question,
        "shop_order_id": "需要先提供 shop_order_id 或 third_party_order_id。",
        "compare_source_types": "需要明确两种 source_type，例如闭环CPS和开环CPS。",
        "term": "需要明确要解释的术语，例如 CPS、CPT、闭环、开环或 NO_PRODUCT_COMMISSION。",
    }
    return "；".join(mapping.get(item, item) for item in missing_slots)


def _apply_relative_time_standardization(message: str, normalized: dict[str, Any], now: datetime) -> None:
    """把“最近7天/最近30天”这类相对时间统一标准化。

    这层属于允许保留的确定性时间标准化，不承担主路径意图理解职责。
    目标是避免 LLM 在相对时间换算上偶发漂移，导致 follow-up 查错时间窗。
    """

    compact = message.replace(" ", "")
    if any(token in compact for token in ("最近7天", "近7天", "最近一周", "近一周")):
        normalized["end_time"] = int(now.timestamp())
        normalized["start_time"] = int((now - timedelta(days=7)).timestamp())
        normalized["time_field"] = normalized.get("time_field") or "order_confirm_time"
        return
    if any(token in compact for token in ("最近30天", "近30天", "最近一个月", "近一个月", "近1个月")):
        normalized["end_time"] = int(now.timestamp())
        normalized["start_time"] = int((now - timedelta(days=30)).timestamp())
        normalized["time_field"] = normalized.get("time_field") or "order_confirm_time"


def _format_time_range(filters: dict[str, Any]) -> str:
    start_time = filters.get("start_time")
    end_time = filters.get("end_time")
    if not start_time or not end_time:
        return "未限定时间"
    start = datetime.fromtimestamp(start_time, tz=timezone.utc).strftime("%Y-%m-%d")
    end = datetime.fromtimestamp(end_time, tz=timezone.utc).strftime("%Y-%m-%d")
    return f"{start} ~ {end}"


def _enum_label(enum_name: str, value: int | None) -> str | None:
    if value is None:
        return None
    mapping = ENUM_ZH_MAPPINGS.get(enum_name, {})
    item = mapping.get(int(value))
    return item["zh_cn"] if item else str(value)


def _translate_distribution(enum_name: str, distribution: dict[str, int]) -> dict[str, int]:
    translated: dict[str, int] = {}
    for key, count in distribution.items():
        translated[_enum_label(enum_name, int(key)) or key] = count
    return translated


def _distribution_sentence(distribution: dict[str, int]) -> str:
    if not distribution:
        return "暂无分布数据"
    return "，".join(f"{key} {value} 笔" for key, value in distribution.items())


def _compose_order_status_answer(result: Any, rule_explanation: Any | None) -> str:
    transfer_type = int(result.transfer_type)
    if transfer_type == int(TransferType.ARRIVED):
        base = f"订单 {result.shop_order_id} 当前状态为已到账，到账时间为 {_format_epoch(result.transfer_time)}。"
    elif transfer_type == int(TransferType.IN_TRANSIT):
        completed = _format_epoch(result.order_complete_time)
        eta = _format_epoch(result.order_complete_time + 2 * 24 * 3600) if result.order_complete_time else "未知"
        base = f"订单 {result.shop_order_id} 当前在路上，核销时间 {completed}，按 T+2 预计到账时间 {eta}。"
    else:
        reason = _enum_label("no_transfer_reason", result.no_transfer_reason)
        base = f"订单 {result.shop_order_id} 当前不可转账，原因是 {reason}。"
    if rule_explanation is not None and rule_explanation.answer.strip():
        base += f" 规则说明：{rule_explanation.answer}"
    return base


def _format_epoch(value: int | None) -> str:
    if value is None:
        return "未知"
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _es_fact_evidence(title: str, summary: str) -> EvidenceItem:
    return EvidenceItem(type="es_fact", title=title, content_summary=summary, source=settings.es_index)


def _build_debug(
    state: AgentState,
    *,
    rule_explanation: Any | None = None,
    tool_result: Any | None = None,
) -> dict[str, Any] | None:
    """构造前端调试面板所需的开发态信息。"""

    if not settings.app_debug:
        return None
    explanation = rule_explanation
    if explanation is None and tool_result is not None and hasattr(tool_result, "matched_chunks"):
        explanation = tool_result
    retrieved_chunks = []
    if explanation is not None and hasattr(explanation, "matched_chunks"):
        retrieved_chunks = [
            {
                "chunk_id": chunk.chunk_id,
                "heading_path": chunk.heading_path,
                "score": chunk.score,
            }
            for chunk in explanation.matched_chunks
        ]
    return {
        "nlu_mode": state.get("nlu_mode", "llm_based"),
        "llm_provider": settings.model_provider,
        "chat_model": settings.chat_model,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model or None,
        "llm_call_count": state.get("llm_call_count", 0),
        "task_state": _to_plain_task_state(state.get("task_state")),
        "retrieved_chunks": retrieved_chunks,
        "selected_tool": state.get("selected_tool"),
        "workflow_trace": state.get("node_logs", []),
    }


def _to_plain_task_state(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return _coerce_task_state(value).model_dump()
