"""状态机矩阵验证。

目标不是验证某条具体回答文案，而是用大量 deterministic case 覆盖：
- reducer 是否稳定地维持 task_type
- normalize 是否正确做缺参、时间、权限、默认值处理
- planner 是否把同一个任务映射成正确的执行计划
- 多轮 follow-up / clarify 是否按预期转移

这类脚本的价值在于：
- 不把 100 个 case 都压到真实 LLM 上，避免把状态机问题和模型波动混在一起
- 重点检验我们自己控制的确定性逻辑是否健壮
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.application.agent.nodes import build_query_plan_node, normalize_and_validate, reduce_state
from app.application.agent.state import AgentState
from app.domain.agent_models import UserContext
from app.domain.intent_models import CommissionQuerySlots, EntityScope, GoalType, QueryUnderstanding, TurnType
from app.domain.query_plan_models import QueryPlanMode
from app.domain.task_state_models import TaskState, TaskStatus, TaskType


OPERATOR = UserContext(user_role="operator", bound_creator_id=None)
CREATOR = UserContext(user_role="creator", bound_creator_id=88001)


@dataclass
class TurnCase:
    message: str
    understanding: QueryUnderstanding
    user_context: UserContext = field(default_factory=lambda: OPERATOR)
    expected_task_type: TaskType | None = None
    expected_route_status: str | None = None
    expected_tool: str | None = None
    expected_status: TaskStatus | None = None
    expected_missing_slots: list[str] | None = None
    expected_filters_subset: dict[str, Any] | None = None


def main() -> None:
    section_counts: dict[str, int] = {}

    section_counts["reducer"] = _run_reducer_cases()
    section_counts["normalize"] = _run_normalize_cases()
    section_counts["planner"] = _run_planner_cases()
    section_counts["conversation_flows"] = _run_conversation_cases()

    total = sum(section_counts.values())
    assert total == 100, f"expected 100 cases, got {total}"

    print(
        json.dumps(
            {
                "total_cases": total,
                "section_counts": section_counts,
                "status": "passed",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _run_reducer_cases() -> int:
    cases: list[tuple[str, TaskState | None, QueryUnderstanding, TaskType | None, dict[str, Any]]] = [
        (
            "new_creator_query",
            None,
            _u(TurnType.NEW_QUERY, TaskType.CREATOR_COMMISSION, creator_id=88001),
            TaskType.CREATOR_COMMISSION,
            {"creator_id": 88001},
        ),
        (
            "new_media_status_query",
            None,
            _u(TurnType.NEW_QUERY, TaskType.MEDIA_COMMISSION_STATUS, media_id=990000),
            TaskType.MEDIA_COMMISSION_STATUS,
            {"media_id": 990000},
        ),
        (
            "new_media_reason_query",
            None,
            _u(TurnType.NEW_QUERY, TaskType.MEDIA_NO_COMMISSION_REASON, media_id=990041),
            TaskType.MEDIA_NO_COMMISSION_REASON,
            {"media_id": 990041},
        ),
        (
            "new_order_query",
            None,
            _u(TurnType.NEW_QUERY, TaskType.ORDER_TRANSFER_STATUS, shop_order_id="SO-1"),
            TaskType.ORDER_TRANSFER_STATUS,
            {"shop_order_id": "SO-1"},
        ),
        (
            "explain_resets_filters",
            TaskState(task_type=TaskType.CREATOR_COMMISSION, normalized_filters={"creator_id": 88001}),
            _u(TurnType.EXPLAIN, TaskType.TERM_EXPLAIN, term="cps"),
            TaskType.TERM_EXPLAIN,
            {"term": "cps"},
        ),
        (
            "unsupported_preserves_creator_task",
            TaskState(
                task_type=TaskType.CREATOR_COMMISSION,
                normalized_filters={"creator_id": 88001},
                status=TaskStatus.READY,
            ),
            _u(TurnType.UNSUPPORTED, TaskType.UNKNOWN),
            TaskType.CREATOR_COMMISSION,
            {"creator_id": 88001},
        ),
    ]

    creator_previous = TaskState(
        task_type=TaskType.CREATOR_COMMISSION,
        normalized_filters={"creator_id": 88001, "start_time": 100, "end_time": 200, "group_by": "none"},
        pending_requirements=[],
        status=TaskStatus.READY,
    )
    for index, payload in enumerate(
        [
            {"is_commission": 2},
            {"group_by": "media_id"},
            {"compare_source_types": [1, 2]},
            {"source_type": [1]},
            {"time_field": "order_complete_time"},
            {"region": "US"},
            {"no_commission_type": 1},
            {"transfer_type": 2},
        ],
        start=1,
    ):
        cases.append(
            (
                f"creator_modify_{index}",
                creator_previous,
                _u(TurnType.MODIFY_FILTERS, TaskType.CREATOR_COMMISSION, **payload),
                TaskType.CREATOR_COMMISSION,
                payload,
            )
        )

    media_status_previous = TaskState(
        task_type=TaskType.MEDIA_COMMISSION_STATUS,
        normalized_filters={"media_id": 990000, "group_by": "none"},
        pending_requirements=[],
        status=TaskStatus.READY,
    )
    for index, payload in enumerate(
        [
            {"is_commission": 2},
            {"start_time": 1000, "end_time": 2000},
            {"source_type": [1]},
            {"region": "SG"},
            {"time_field": "order_complete_time"},
            {"creator_id": 88001},
        ],
        start=1,
    ):
        cases.append(
            (
                f"media_status_modify_{index}",
                media_status_previous,
                _u(TurnType.MODIFY_FILTERS, TaskType.MEDIA_COMMISSION_STATUS, **payload),
                TaskType.MEDIA_COMMISSION_STATUS,
                payload,
            )
        )

    clarify_previous_media = TaskState(
        task_type=TaskType.MEDIA_NO_COMMISSION_REASON,
        normalized_filters={},
        pending_requirements=["media_id"],
        status=TaskStatus.CLARIFYING,
    )
    for media_id in [990041, 990042, 990043, 990044]:
        cases.append(
            (
                f"clarify_media_{media_id}",
                clarify_previous_media,
                _u(TurnType.ANSWER_CLARIFY, TaskType.MEDIA_NO_COMMISSION_REASON, media_id=media_id),
                TaskType.MEDIA_NO_COMMISSION_REASON,
                {"media_id": media_id},
            )
        )

    clarify_previous_order = TaskState(
        task_type=TaskType.ORDER_TRANSFER_STATUS,
        normalized_filters={},
        pending_requirements=["shop_order_id"],
        status=TaskStatus.CLARIFYING,
    )
    for shop_order_id in ["SO-1", "SO-2", "SO-3", "SO-4"]:
        cases.append(
            (
                f"clarify_order_{shop_order_id}",
                clarify_previous_order,
                _u(TurnType.ANSWER_CLARIFY, TaskType.ORDER_TRANSFER_STATUS, shop_order_id=shop_order_id),
                TaskType.ORDER_TRANSFER_STATUS,
                {"shop_order_id": shop_order_id},
            )
        )

    explain_previous = TaskState(
        task_type=TaskType.MEDIA_COMMISSION_STATUS,
        normalized_filters={"media_id": 990000, "creator_id": 88001},
        status=TaskStatus.READY,
    )
    for term in ["cps", "NO_PRODUCT_COMMISSION"]:
        cases.append(
            (
                f"explain_term_{term}",
                explain_previous,
                _u(TurnType.EXPLAIN, TaskType.TERM_EXPLAIN, term=term),
                TaskType.TERM_EXPLAIN,
                {"term": term},
            )
        )

    assert len(cases) == 30, len(cases)
    for name, previous, understanding, expected_task_type, expected_subset in cases:
        state = reduce_state({"task_state": previous or TaskState(), "understanding": understanding})
        task_state = state["task_state"]
        assert task_state.task_type == expected_task_type, name
        _assert_subset(task_state.normalized_filters, expected_subset, name)
    return len(cases)


def _run_normalize_cases() -> int:
    cases: list[tuple[str, AgentState, dict[str, Any]]] = []

    creator_base = TaskState(task_type=TaskType.CREATOR_COMMISSION, normalized_filters={"creator_id": 88001})
    media_status_base = TaskState(task_type=TaskType.MEDIA_COMMISSION_STATUS, normalized_filters={"media_id": 990000})
    media_reason_base = TaskState(task_type=TaskType.MEDIA_NO_COMMISSION_REASON, normalized_filters={})
    order_base = TaskState(task_type=TaskType.ORDER_TRANSFER_STATUS, normalized_filters={})
    explain_base = TaskState(task_type=TaskType.TERM_EXPLAIN, normalized_filters={})

    cases.extend(
        [
            (
                "creator_default_30d",
                _state("帮我查达人", creator_base, OPERATOR),
                {"route_status": "route", "require_keys": ["start_time", "end_time"], "task_type": TaskType.CREATOR_COMMISSION},
            ),
            (
                "creator_recent_7d",
                _state("只看最近7天", creator_base, OPERATOR),
                {"route_status": "route", "range_days": 7},
            ),
            (
                "creator_recent_30d",
                _state("最近30天", creator_base, OPERATOR),
                {"route_status": "route", "range_days": 30},
            ),
            (
                "creator_bound_creator_id",
                _state("查最近30天分佣", TaskState(task_type=TaskType.CREATOR_COMMISSION, normalized_filters={}), CREATOR),
                {"route_status": "route", "creator_id": 88001},
            ),
            (
                "creator_forbidden_other_creator",
                _state(
                    "查达人99000最近30天分佣",
                    TaskState(task_type=TaskType.CREATOR_COMMISSION, normalized_filters={"creator_id": 99000}),
                    CREATOR,
                ),
                {"route_status": "unsupported", "creator_id": 99000},
            ),
            (
                "creator_missing_creator",
                _state("查达人分佣", TaskState(task_type=TaskType.CREATOR_COMMISSION, normalized_filters={}), OPERATOR),
                {"route_status": "clarify", "missing_slots": ["creator_id"]},
            ),
            (
                "creator_single_compare_type",
                _state(
                    "对比闭环cps",
                    TaskState(
                        task_type=TaskType.CREATOR_COMMISSION,
                        normalized_filters={"creator_id": 88001, "compare_source_types": [1]},
                    ),
                    OPERATOR,
                ),
                {"route_status": "clarify", "missing_slots": ["compare_source_types"]},
            ),
            (
                "media_status_default_30d",
                _state("查询视频是否可分佣", media_status_base, OPERATOR),
                {"route_status": "route", "range_days": 30},
            ),
            (
                "media_status_recent_7d",
                _state("只看最近7天", media_status_base, OPERATOR),
                {"route_status": "route", "range_days": 7},
            ),
            (
                "media_status_missing_media",
                _state("我的视频是否可分佣", TaskState(task_type=TaskType.MEDIA_COMMISSION_STATUS, normalized_filters={}), OPERATOR),
                {"route_status": "clarify", "missing_slots": ["media_id"]},
            ),
            (
                "media_reason_missing_media",
                _state("视频不可分佣", media_reason_base, OPERATOR),
                {"route_status": "clarify", "missing_slots": ["media_id"]},
            ),
            (
                "order_missing_id",
                _state("订单什么时候到账", order_base, OPERATOR),
                {"route_status": "clarify", "missing_slots": ["shop_order_id"]},
            ),
            (
                "term_missing_term",
                _state("解释一下", explain_base, OPERATOR),
                {"route_status": "clarify", "missing_slots": ["term"]},
            ),
            (
                "unknown_task_unsupported",
                _state("随便聊聊", TaskState(task_type=TaskType.UNKNOWN, normalized_filters={}), OPERATOR),
                {"route_status": "unsupported"},
            ),
        ]
    )

    # 补足到 25 个 normalize case：围绕时间、权限、media task 的常见变体。
    for idx, message in enumerate(
        [
            "近7天",
            "最近一周",
            "近一个月",
            "最近30天",
            "近30天",
            "最近7天",
        ],
        start=1,
    ):
        cases.append(
            (
                f"media_status_time_variant_{idx}",
                _state(message, media_status_base, OPERATOR),
                {"route_status": "route", "expect_time_field": "order_confirm_time"},
            )
        )

    for idx, filters in enumerate(
        [
            {"media_id": 990000, "creator_id": 88001},
            {"media_id": 990000, "is_commission": 2},
            {"media_id": 990000, "source_type": [1]},
            {"media_id": 990000, "region": "US"},
            {"media_id": 990000, "time_field": "order_complete_time"},
        ],
        start=1,
    ):
        cases.append(
            (
                f"media_status_filter_variant_{idx}",
                _state("查询视频分佣情况", TaskState(task_type=TaskType.MEDIA_COMMISSION_STATUS, normalized_filters=filters), OPERATOR),
                {"route_status": "route", "subset": filters},
            )
        )

    assert len(cases) == 25, len(cases)
    for name, state, expected in cases:
        result = normalize_and_validate(state)
        assert result["route_status"] == expected["route_status"], name
        task_state = result["task_state"]
        if "task_type" in expected:
            assert task_state.task_type == expected["task_type"], name
        if "creator_id" in expected:
            assert result["normalized_filters"]["creator_id"] == expected["creator_id"], name
        if "missing_slots" in expected:
            assert result["missing_slots"] == expected["missing_slots"], name
        if "require_keys" in expected:
            for key in expected["require_keys"]:
                assert result["normalized_filters"].get(key) is not None, f"{name}:{key}"
        if "range_days" in expected:
            _assert_range_days(result["normalized_filters"], expected["range_days"], name)
        if "expect_time_field" in expected:
            assert result["normalized_filters"]["time_field"] == expected["expect_time_field"], name
        if "subset" in expected:
            _assert_subset(result["normalized_filters"], expected["subset"], name)
    return len(cases)


def _run_planner_cases() -> int:
    cases: list[tuple[str, TaskState, str | None, str | None, QueryPlanMode]] = [
        (
            "creator_summary_base",
            TaskState(task_type=TaskType.CREATOR_COMMISSION, normalized_filters={"creator_id": 88001}),
            "get_creator_commission_summary",
            "QUERY_CREATOR_SUMMARY",
            QueryPlanMode.ES_ONLY,
        ),
        (
            "creator_summary_by_media",
            TaskState(
                task_type=TaskType.CREATOR_COMMISSION,
                normalized_filters={"creator_id": 88001, "group_by": "media_id"},
            ),
            "summarize_commission_by_media",
            "SUMMARIZE_BY_MEDIA",
            QueryPlanMode.ES_ONLY,
        ),
        (
            "creator_summary_compare",
            TaskState(
                task_type=TaskType.CREATOR_COMMISSION,
                normalized_filters={"creator_id": 88001, "compare_source_types": [1, 2]},
            ),
            "compare_source_type_commission",
            "COMPARE_SOURCE_TYPE",
            QueryPlanMode.ES_ONLY,
        ),
        (
            "media_status_plan",
            TaskState(task_type=TaskType.MEDIA_COMMISSION_STATUS, normalized_filters={"media_id": 990000}),
            "get_media_commission_status",
            "QUERY_MEDIA_COMMISSION_STATUS",
            QueryPlanMode.ES_ONLY,
        ),
        (
            "media_reason_plan",
            TaskState(task_type=TaskType.MEDIA_NO_COMMISSION_REASON, normalized_filters={"media_id": 990041}),
            "get_media_no_commission_breakdown",
            "QUERY_MEDIA_NO_COMMISSION_REASON",
            QueryPlanMode.HYBRID,
        ),
        (
            "order_plan",
            TaskState(task_type=TaskType.ORDER_TRANSFER_STATUS, normalized_filters={"shop_order_id": "SO-1"}),
            "get_order_transfer_status",
            "QUERY_ORDER_TRANSFER_STATUS",
            QueryPlanMode.HYBRID,
        ),
        (
            "explain_plan",
            TaskState(task_type=TaskType.TERM_EXPLAIN, normalized_filters={"term": "cps"}),
            "explain_business_term",
            "EXPLAIN_BUSINESS_TERM",
            QueryPlanMode.KNOWLEDGE_ONLY,
        ),
        (
            "unknown_plan",
            TaskState(task_type=TaskType.UNKNOWN, normalized_filters={}),
            None,
            "UNKNOWN",
            QueryPlanMode.UNSUPPORTED,
        ),
    ]

    # 补 12 个 creator 变体，确保 plan 对无关 filter 保持稳定。
    creator_variants = [
        {"creator_id": 88001, "is_commission": 2},
        {"creator_id": 88001, "source_type": [1]},
        {"creator_id": 88001, "region": "US"},
        {"creator_id": 88001, "time_field": "order_complete_time"},
        {"creator_id": 88001, "group_by": "none"},
        {"creator_id": 88001, "is_commission": 1},
        {"creator_id": 88001, "start_time": 1, "end_time": 2},
        {"creator_id": 88001, "no_commission_type": 1},
        {"creator_id": 88001, "transfer_type": 2},
        {"creator_id": 88001, "source_type": [2]},
        {"creator_id": 88001, "source_type": [3]},
        {"creator_id": 88001, "group_by": "source_type"},
    ]
    for idx, filters in enumerate(creator_variants, start=1):
        cases.append(
            (
                f"creator_variant_{idx}",
                TaskState(task_type=TaskType.CREATOR_COMMISSION, normalized_filters=filters),
                "get_creator_commission_summary",
                "QUERY_CREATOR_SUMMARY",
                QueryPlanMode.ES_ONLY,
            )
        )

    assert len(cases) == 20, len(cases)
    for name, task_state, tool_name, intent, mode in cases:
        result = build_query_plan_node({"task_state": task_state, "normalized_filters": task_state.normalized_filters})
        plan = result.get("query_plan")
        assert result["route_status"] in {"execute", "unsupported"}, name
        if mode == QueryPlanMode.UNSUPPORTED:
            assert result["route_status"] == "unsupported", name
            continue
        assert result["selected_tool"] == tool_name, name
        assert plan is not None and plan.mode == mode, name
        assert plan.response_intent.value == intent, name
    return len(cases)


def _run_conversation_cases() -> int:
    flows: list[tuple[str, list[TurnCase]]] = [
        (
            "creator_summary_flow",
            [
                TurnCase(
                    message="帮我查达人88001最近30天分佣情况",
                    understanding=_u(TurnType.NEW_QUERY, TaskType.CREATOR_COMMISSION, creator_id=88001),
                    expected_task_type=TaskType.CREATOR_COMMISSION,
                    expected_route_status="route",
                    expected_tool="get_creator_commission_summary",
                    expected_status=TaskStatus.READY,
                ),
                TurnCase(
                    message="只看最近7天",
                    understanding=_u(TurnType.MODIFY_FILTERS, TaskType.CREATOR_COMMISSION),
                    expected_task_type=TaskType.CREATOR_COMMISSION,
                    expected_route_status="route",
                    expected_tool="get_creator_commission_summary",
                    expected_status=TaskStatus.READY,
                ),
                TurnCase(
                    message="只看不可分佣订单",
                    understanding=_u(TurnType.MODIFY_FILTERS, TaskType.CREATOR_COMMISSION, is_commission=2),
                    expected_task_type=TaskType.CREATOR_COMMISSION,
                    expected_route_status="route",
                    expected_tool="get_creator_commission_summary",
                    expected_status=TaskStatus.READY,
                    expected_filters_subset={"is_commission": 2},
                ),
                TurnCase(
                    message="按视频展开",
                    understanding=_u(TurnType.MODIFY_FILTERS, TaskType.CREATOR_COMMISSION, group_by="media_id"),
                    expected_task_type=TaskType.CREATOR_COMMISSION,
                    expected_route_status="route",
                    expected_tool="summarize_commission_by_media",
                    expected_status=TaskStatus.READY,
                    expected_filters_subset={"group_by": "media_id"},
                ),
            ],
        ),
        (
            "media_status_direct_flow",
            [
                TurnCase(
                    message="帮我查询视频990000是否可分佣",
                    understanding=_u(TurnType.NEW_QUERY, TaskType.MEDIA_COMMISSION_STATUS, media_id=990000),
                    expected_task_type=TaskType.MEDIA_COMMISSION_STATUS,
                    expected_route_status="route",
                    expected_tool="get_media_commission_status",
                    expected_status=TaskStatus.READY,
                ),
                TurnCase(
                    message="只看最近7天",
                    understanding=_u(TurnType.MODIFY_FILTERS, TaskType.MEDIA_COMMISSION_STATUS),
                    expected_task_type=TaskType.MEDIA_COMMISSION_STATUS,
                    expected_route_status="route",
                    expected_tool="get_media_commission_status",
                    expected_status=TaskStatus.READY,
                ),
                TurnCase(
                    message="只看不可分佣订单",
                    understanding=_u(TurnType.MODIFY_FILTERS, TaskType.MEDIA_COMMISSION_STATUS, is_commission=2),
                    expected_task_type=TaskType.MEDIA_COMMISSION_STATUS,
                    expected_route_status="route",
                    expected_tool="get_media_commission_status",
                    expected_status=TaskStatus.READY,
                    expected_filters_subset={"is_commission": 2},
                ),
            ],
        ),
        (
            "media_status_clarify_flow",
            [
                TurnCase(
                    message="如何查看我的视频是否可分佣",
                    understanding=_u(TurnType.NEW_QUERY, TaskType.MEDIA_COMMISSION_STATUS),
                    expected_task_type=TaskType.MEDIA_COMMISSION_STATUS,
                    expected_route_status="clarify",
                    expected_status=TaskStatus.CLARIFYING,
                    expected_missing_slots=["media_id"],
                ),
                TurnCase(
                    message="media_id: 990000",
                    understanding=_u(TurnType.ANSWER_CLARIFY, TaskType.MEDIA_COMMISSION_STATUS, media_id=990000),
                    expected_task_type=TaskType.MEDIA_COMMISSION_STATUS,
                    expected_route_status="route",
                    expected_tool="get_media_commission_status",
                    expected_status=TaskStatus.READY,
                    expected_filters_subset={"media_id": 990000},
                ),
                TurnCase(
                    message="只看最近7天",
                    understanding=_u(TurnType.MODIFY_FILTERS, TaskType.MEDIA_COMMISSION_STATUS),
                    expected_task_type=TaskType.MEDIA_COMMISSION_STATUS,
                    expected_route_status="route",
                    expected_tool="get_media_commission_status",
                    expected_status=TaskStatus.READY,
                ),
            ],
        ),
        (
            "media_reason_clarify_flow",
            [
                TurnCase(
                    message="我的视频为什么不可分佣",
                    understanding=_u(TurnType.NEW_QUERY, TaskType.MEDIA_NO_COMMISSION_REASON),
                    expected_task_type=TaskType.MEDIA_NO_COMMISSION_REASON,
                    expected_route_status="clarify",
                    expected_status=TaskStatus.CLARIFYING,
                    expected_missing_slots=["media_id"],
                ),
                TurnCase(
                    message="990041",
                    understanding=_u(TurnType.ANSWER_CLARIFY, TaskType.MEDIA_NO_COMMISSION_REASON, media_id=990041),
                    expected_task_type=TaskType.MEDIA_NO_COMMISSION_REASON,
                    expected_route_status="route",
                    expected_tool="get_media_no_commission_breakdown",
                    expected_status=TaskStatus.READY,
                ),
                TurnCase(
                    message="只看最近7天",
                    understanding=_u(TurnType.MODIFY_FILTERS, TaskType.MEDIA_NO_COMMISSION_REASON),
                    expected_task_type=TaskType.MEDIA_NO_COMMISSION_REASON,
                    expected_route_status="route",
                    expected_tool="get_media_no_commission_breakdown",
                    expected_status=TaskStatus.READY,
                ),
            ],
        ),
        (
            "order_clarify_flow",
            [
                TurnCase(
                    message="我的佣金什么时候到账",
                    understanding=_u(TurnType.NEW_QUERY, TaskType.ORDER_TRANSFER_STATUS),
                    expected_task_type=TaskType.ORDER_TRANSFER_STATUS,
                    expected_route_status="clarify",
                    expected_status=TaskStatus.CLARIFYING,
                    expected_missing_slots=["shop_order_id"],
                ),
                TurnCase(
                    message="shop_order_id: SO-20260309-001127",
                    understanding=_u(
                        TurnType.ANSWER_CLARIFY,
                        TaskType.ORDER_TRANSFER_STATUS,
                        shop_order_id="SO-20260309-001127",
                    ),
                    expected_task_type=TaskType.ORDER_TRANSFER_STATUS,
                    expected_route_status="route",
                    expected_tool="get_order_transfer_status",
                    expected_status=TaskStatus.READY,
                ),
                TurnCase(
                    message="只看最近7天",
                    understanding=_u(TurnType.MODIFY_FILTERS, TaskType.ORDER_TRANSFER_STATUS),
                    expected_task_type=TaskType.ORDER_TRANSFER_STATUS,
                    expected_route_status="route",
                    expected_tool="get_order_transfer_status",
                    expected_status=TaskStatus.READY,
                ),
            ],
        ),
        (
            "creator_to_explain_flow",
            [
                TurnCase(
                    message="帮我查达人88001最近30天分佣情况",
                    understanding=_u(TurnType.NEW_QUERY, TaskType.CREATOR_COMMISSION, creator_id=88001),
                    expected_task_type=TaskType.CREATOR_COMMISSION,
                    expected_route_status="route",
                    expected_tool="get_creator_commission_summary",
                    expected_status=TaskStatus.READY,
                ),
                TurnCase(
                    message="解释一下闭环cps和cpt的区别",
                    understanding=_u(TurnType.EXPLAIN, TaskType.TERM_EXPLAIN, term="闭环cps和cpt的区别"),
                    expected_task_type=TaskType.TERM_EXPLAIN,
                    expected_route_status="route",
                    expected_tool="explain_business_term",
                    expected_status=TaskStatus.READY,
                    expected_filters_subset={"term": "闭环cps和cpt的区别"},
                ),
                TurnCase(
                    message="再解释一下NO_PRODUCT_COMMISSION",
                    understanding=_u(TurnType.EXPLAIN, TaskType.TERM_EXPLAIN, term="NO_PRODUCT_COMMISSION"),
                    expected_task_type=TaskType.TERM_EXPLAIN,
                    expected_route_status="route",
                    expected_tool="explain_business_term",
                    expected_status=TaskStatus.READY,
                ),
            ],
        ),
        (
            "creator_permission_flow",
            [
                TurnCase(
                    message="查最近30天分佣",
                    understanding=_u(TurnType.NEW_QUERY, TaskType.CREATOR_COMMISSION),
                    user_context=CREATOR,
                    expected_task_type=TaskType.CREATOR_COMMISSION,
                    expected_route_status="route",
                    expected_tool="get_creator_commission_summary",
                    expected_status=TaskStatus.READY,
                    expected_filters_subset={"creator_id": 88001},
                ),
                TurnCase(
                    message="只看不可分佣订单",
                    understanding=_u(TurnType.MODIFY_FILTERS, TaskType.CREATOR_COMMISSION, is_commission=2),
                    user_context=CREATOR,
                    expected_task_type=TaskType.CREATOR_COMMISSION,
                    expected_route_status="route",
                    expected_tool="get_creator_commission_summary",
                    expected_status=TaskStatus.READY,
                    expected_filters_subset={"creator_id": 88001, "is_commission": 2},
                ),
                TurnCase(
                    message="查达人99000最近30天分佣",
                    understanding=_u(TurnType.NEW_QUERY, TaskType.CREATOR_COMMISSION, creator_id=99000),
                    user_context=CREATOR,
                    expected_task_type=TaskType.CREATOR_COMMISSION,
                    expected_route_status="unsupported",
                    expected_status=TaskStatus.UNSUPPORTED,
                ),
                TurnCase(
                    message="查最近7天分佣",
                    understanding=_u(TurnType.MODIFY_FILTERS, TaskType.CREATOR_COMMISSION),
                    user_context=CREATOR,
                    expected_task_type=TaskType.CREATOR_COMMISSION,
                    expected_route_status="route",
                    expected_tool="get_creator_commission_summary",
                    expected_status=TaskStatus.READY,
                    expected_filters_subset={"creator_id": 88001},
                ),
            ],
        ),
        (
            "unsupported_recovery_flow",
            [
                TurnCase(
                    message="随便说点没法执行的话",
                    understanding=_u(TurnType.UNSUPPORTED, TaskType.UNKNOWN),
                    expected_task_type=TaskType.UNKNOWN,
                    expected_route_status="unsupported",
                    expected_status=TaskStatus.UNSUPPORTED,
                ),
                TurnCase(
                    message="帮我查询视频990000是否可分佣",
                    understanding=_u(TurnType.NEW_QUERY, TaskType.MEDIA_COMMISSION_STATUS, media_id=990000),
                    expected_task_type=TaskType.MEDIA_COMMISSION_STATUS,
                    expected_route_status="route",
                    expected_tool="get_media_commission_status",
                    expected_status=TaskStatus.READY,
                ),
            ],
        ),
    ]

    total_turns = sum(len(turns) for _, turns in flows)
    assert total_turns == 25, total_turns

    for flow_name, turns in flows:
        task_state = TaskState()
        messages: list[Any] = []
        for index, turn in enumerate(turns, start=1):
            state: AgentState = {
                "conversation_id": f"matrix-{flow_name}",
                "message": turn.message,
                "user_context": turn.user_context,
                "task_state": task_state,
                "messages": messages,
                "understanding": turn.understanding,
            }
            reduced = reduce_state(state)
            state.update(reduced)
            normalized = normalize_and_validate(state)
            state.update(normalized)

            assert state["task_state"].task_type == turn.expected_task_type, f"{flow_name}:{index}:task"
            assert state["route_status"] == turn.expected_route_status, f"{flow_name}:{index}:route"
            if turn.expected_status is not None:
                assert state["task_state"].status == turn.expected_status, f"{flow_name}:{index}:status"
            if turn.expected_missing_slots is not None:
                assert state["missing_slots"] == turn.expected_missing_slots, f"{flow_name}:{index}:missing"
            if turn.expected_filters_subset:
                _assert_subset(state["normalized_filters"], turn.expected_filters_subset, f"{flow_name}:{index}:filters")

            if state["route_status"] == "route":
                planned = build_query_plan_node(state)
                state.update(planned)
                if turn.expected_tool is not None:
                    assert state["selected_tool"] == turn.expected_tool, f"{flow_name}:{index}:tool"

            task_state = state["task_state"]
            messages = state.get("messages", [])

    return total_turns


def _u(turn_type: TurnType, task_type: TaskType | None, **slots: Any) -> QueryUnderstanding:
    entity_scope = EntityScope.UNKNOWN
    goal_type = GoalType.UNKNOWN

    if task_type == TaskType.CREATOR_COMMISSION:
        entity_scope = EntityScope.CREATOR
        goal_type = GoalType.COMPARE if slots.get("compare_source_types") else GoalType.SUMMARY
    elif task_type == TaskType.MEDIA_COMMISSION_STATUS:
        entity_scope = EntityScope.MEDIA
        goal_type = GoalType.STATUS
    elif task_type == TaskType.MEDIA_NO_COMMISSION_REASON:
        entity_scope = EntityScope.MEDIA
        goal_type = GoalType.REASON
    elif task_type == TaskType.ORDER_TRANSFER_STATUS:
        entity_scope = EntityScope.ORDER
        goal_type = GoalType.STATUS
    elif task_type == TaskType.TERM_EXPLAIN:
        entity_scope = EntityScope.TERM
        goal_type = GoalType.EXPLAIN

    return QueryUnderstanding(
        turn_type=turn_type,
        entity_scope=entity_scope,
        goal_type=goal_type,
        task_type=task_type,
        slots=CommissionQuerySlots(**slots),
    )


def _state(message: str, task_state: TaskState, user_context: UserContext) -> AgentState:
    return {
        "conversation_id": "matrix-normalize",
        "message": message,
        "user_context": user_context,
        "task_state": task_state,
        "messages": [],
    }


def _assert_subset(actual: dict[str, Any], expected_subset: dict[str, Any], name: str) -> None:
    for key, value in expected_subset.items():
        assert actual.get(key) == value, f"{name}:{key} expected {value}, got {actual.get(key)}"


def _assert_range_days(filters: dict[str, Any], days: int, name: str) -> None:
    start_time = filters.get("start_time")
    end_time = filters.get("end_time")
    assert start_time is not None and end_time is not None, f"{name}:missing_range"
    actual_days = round((end_time - start_time) / 86400)
    assert actual_days == days, f"{name}:expected {days}d, got {actual_days}d"


if __name__ == "__main__":
    main()
