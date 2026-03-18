"""把任务态翻译成执行计划。

planner 这层专门回答一个问题：
“当前任务态已经明确后，这一轮到底该怎么执行？”

它的存在是为了把两件事彻底拆开：
- reducer 决定当前任务是什么
- planner 决定这一轮怎么查
"""

from __future__ import annotations

from app.domain.intent_models import AgentIntent
from app.domain.query_plan_models import QueryPlan, QueryPlanMode
from app.domain.task_state_models import TaskState, TaskType


def build_query_plan(task_state: TaskState) -> QueryPlan:
    """根据任务态生成这一轮的稳定执行计划。

    这里不应该再做语义理解；所有语义理解都已经在 `understand_query`
    和 `reduce_state` 结束。planner 只看结构化后的 task_state。
    """

    filters = dict(task_state.normalized_filters)

    if task_state.task_type == TaskType.CREATOR_COMMISSION:
        # 达人分佣任务下，可能有三种 常见执行形态：
        # 1. 普通汇总
        # 2. 按视频展开
        # 3. 对比两类 source_type
        #
        # 它们仍属于同一个 task_type，只是 query_plan 不同。
        compare_types = filters.get("compare_source_types") or []
        if len(compare_types) >= 2:
            return QueryPlan(
                mode=QueryPlanMode.ES_ONLY,
                tool_name="compare_source_type_commission",
                response_intent=AgentIntent.COMPARE_SOURCE_TYPE,
                filters=filters,
            )
        if filters.get("group_by") == "media_id":
            return QueryPlan(
                mode=QueryPlanMode.ES_ONLY,
                tool_name="summarize_commission_by_media",
                response_intent=AgentIntent.SUMMARIZE_BY_MEDIA,
                filters=filters,
            )
        # 默认走达人维度汇总。
        return QueryPlan(
            mode=QueryPlanMode.ES_ONLY,
            tool_name="get_creator_commission_summary",
            response_intent=AgentIntent.QUERY_CREATOR_SUMMARY,
            filters=filters,
        )

    if task_state.task_type == TaskType.MEDIA_COMMISSION_STATUS:
        return QueryPlan(
            mode=QueryPlanMode.ES_ONLY,
            tool_name="get_media_commission_status",
            response_intent=AgentIntent.QUERY_MEDIA_COMMISSION_STATUS,
            filters=filters,
        )

    if task_state.task_type == TaskType.MEDIA_NO_COMMISSION_REASON:
        # 这类问题既要查事实（视频下有哪些不可分佣订单），
        # 又可能要补充原因解释，因此走 hybrid。
        return QueryPlan(
            mode=QueryPlanMode.HYBRID,
            tool_name="get_media_no_commission_breakdown",
            response_intent=AgentIntent.QUERY_MEDIA_NO_COMMISSION_REASON,
            filters=filters,
            needs_rule_explanation=True,
        )

    if task_state.task_type == TaskType.ORDER_TRANSFER_STATUS:
        # 订单到账状态同样是“事实 + 规则解释”的混合型场景。
        return QueryPlan(
            mode=QueryPlanMode.HYBRID,
            tool_name="get_order_transfer_status",
            response_intent=AgentIntent.QUERY_ORDER_TRANSFER_STATUS,
            filters=filters,
            needs_rule_explanation=True,
        )

    if task_state.task_type == TaskType.TERM_EXPLAIN:
        # 术语解释只需要知识检索，不需要 ES 事实查询。
        return QueryPlan(
            mode=QueryPlanMode.KNOWLEDGE_ONLY,
            tool_name="explain_business_term",
            response_intent=AgentIntent.EXPLAIN_BUSINESS_TERM,
            filters=filters,
        )

    return QueryPlan(mode=QueryPlanMode.UNSUPPORTED, response_intent=AgentIntent.UNKNOWN, filters=filters)
