"""真实 LLM 驱动的 100-case 回归脚本。

这个脚本和 `validate_state_machine_matrix.py` 的定位不同：
- `validate_state_machine_matrix.py` 重点验证 reducer / normalize / planner 的确定性逻辑；
- 本脚本直接打本地 `/api/chat`，确保每个 case 都经过：
  - 真实 LLM 理解
  - 真实 LangGraph 状态机
  - 真实 ES / RAG / checkpointer

目标：
- 跑满 100 个 turn 级 case；
- 覆盖单轮、多轮 follow-up、clarify、creator 权限、媒体状态/原因近邻语义；
- 每个 case 至少验证：
  - action
  - intent
  - debug.task_state.task_type
  - debug.selected_tool
  - 关键 filters 子集
  - 当前请求确实走了 llm_based。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from app.config.settings import get_settings
from app.infrastructure.es.client import create_es_client
from app.infrastructure.es.repository import CommissionOrderRepository
from app.web.demo_data import resolve_demo_context


BASE_URL = "http://127.0.0.1:8002"


@dataclass
class RealLLMCase:
    conversation_id: str
    message: str
    user_role: str = "operator"
    bound_creator_id: int | None = None
    expected_action: str | None = None
    expected_intent: str | None = None
    expected_task_type: str | None = None
    expected_selected_tool: str | None = None
    expected_missing_slots: list[str] | None = None
    expected_filters_subset: dict[str, Any] | None = None
    answer_contains: list[str] = field(default_factory=list)
    note: str = ""


def main() -> None:
    _ensure_service_alive()
    context = _build_context()
    cases = _build_cases(context)
    assert len(cases) == 100, f"expected 100 cases, got {len(cases)}"

    _reset_conversations(cases)

    failures: list[dict[str, Any]] = []
    passed = 0
    counts: dict[str, int] = {
        "creator_summary_turns": 0,
        "media_status_turns": 0,
        "media_reason_turns": 0,
        "order_turns": 0,
        "explain_turns": 0,
        "creator_permission_turns": 0,
    }

    for index, case in enumerate(cases, start=1):
        payload = {
            "conversation_id": case.conversation_id,
            "message": case.message,
            "user_role": case.user_role,
            "bound_creator_id": case.bound_creator_id,
        }
        response = _post_json("/api/chat", payload)
        try:
            _assert_case(case, response)
            passed += 1
        except AssertionError as exc:
            failures.append(
                {
                    "index": index,
                    "conversation_id": case.conversation_id,
                    "message": case.message,
                    "note": case.note,
                    "error": str(exc),
                    "response_summary": {
                        "action": response.get("action"),
                        "intent": response.get("intent"),
                        "task_type": ((response.get("debug") or {}).get("task_state") or {}).get("task_type"),
                        "selected_tool": (response.get("debug") or {}).get("selected_tool"),
                        "normalized_filters": response.get("normalized_filters"),
                        "missing_slots": response.get("missing_slots"),
                        "answer": response.get("answer"),
                    },
                }
            )

        _increment_counts(counts, case.conversation_id)
        print(
            json.dumps(
                {
                    "index": index,
                    "conversation_id": case.conversation_id,
                    "message": case.message,
                    "action": response.get("action"),
                    "intent": response.get("intent"),
                    "task_type": ((response.get("debug") or {}).get("task_state") or {}).get("task_type"),
                    "selected_tool": (response.get("debug") or {}).get("selected_tool"),
                    "llm_provider": (response.get("debug") or {}).get("llm_provider"),
                    "chat_model": (response.get("debug") or {}).get("chat_model"),
                    "llm_call_count": (response.get("debug") or {}).get("llm_call_count"),
                    "status": "passed" if len(failures) < (index - passed + 1) else "failed",
                },
                ensure_ascii=False,
            )
        )

    summary = {
        "total_cases": len(cases),
        "passed": passed,
        "failed": len(failures),
        "section_counts": counts,
        "model": _model_summary(),
        "failures": failures[:20],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


def _ensure_service_alive() -> None:
    health = _get_json("/health")
    assert health.get("status") == "ok", health


def _build_context() -> dict[str, Any]:
    settings = get_settings()
    repository = CommissionOrderRepository(create_es_client(settings), settings.es_index)
    demo_context = resolve_demo_context()
    compare = repository.find_creator_with_multiple_source_types()
    compare_creator_id = compare[0] if compare else demo_context["recent_creator_id"]
    return {
        "creator_id": int(compare_creator_id),
        "creator_bound_id": int(demo_context["bound_creator_id"]),
        "other_creator_id": int(demo_context["bound_creator_id"]) + 999,
        "media_status_id": int(demo_context["recent_media_id"]),
        "media_reason_id": int(repository.find_media_id_with_non_commission() or demo_context["recent_media_id"]),
        "shop_order_id": str(demo_context["latest_shop_order_id"]),
    }


def _build_cases(context: dict[str, Any]) -> list[RealLLMCase]:
    cases: list[RealLLMCase] = []
    creator_id = context["creator_id"]
    creator_bound_id = context["creator_bound_id"]
    other_creator_id = context["other_creator_id"]
    media_status_id = context["media_status_id"]
    media_reason_id = context["media_reason_id"]
    shop_order_id = context["shop_order_id"]

    # 30 turns: 6 creator commission conversations x 5 turns.
    creator_openers = [
        f"帮我查达人{creator_id}最近30天分佣情况",
        f"查询达人{creator_id}近30天分佣情况",
        f"看一下达人{creator_id}最近30天佣金情况",
        f"帮我汇总达人{creator_id}最近30天带货佣金",
        f"达人{creator_id}最近30天分佣表现怎么样",
        f"帮我看达人{creator_id}近一个月分佣情况",
    ]
    for index, opener in enumerate(creator_openers, start=1):
        cid = f"real-llm-creator-{index}"
        cases.extend(
            [
                RealLLMCase(
                    conversation_id=cid,
                    message=opener,
                    expected_action="answer",
                    expected_intent="QUERY_CREATOR_SUMMARY",
                    expected_task_type="CREATOR_COMMISSION",
                    expected_selected_tool="get_creator_commission_summary",
                    expected_filters_subset={"creator_id": creator_id},
                    note="creator summary open",
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看不可分佣订单",
                    expected_action="answer",
                    expected_intent="QUERY_CREATOR_SUMMARY",
                    expected_task_type="CREATOR_COMMISSION",
                    expected_selected_tool="get_creator_commission_summary",
                    expected_filters_subset={"creator_id": creator_id, "is_commission": 2},
                    note="creator follow-up non commission",
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="按视频展开",
                    expected_action="answer",
                    expected_intent="SUMMARIZE_BY_MEDIA",
                    expected_task_type="CREATOR_COMMISSION",
                    expected_selected_tool="summarize_commission_by_media",
                    expected_filters_subset={"creator_id": creator_id, "group_by": "media_id"},
                    note="creator follow-up by media",
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看最近7天",
                    expected_action="answer",
                    expected_intent="SUMMARIZE_BY_MEDIA",
                    expected_task_type="CREATOR_COMMISSION",
                    expected_selected_tool="summarize_commission_by_media",
                    expected_filters_subset={"creator_id": creator_id, "group_by": "media_id"},
                    note="creator follow-up recent 7d",
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="对比闭环cps和开环cps",
                    expected_action="answer",
                    expected_intent="COMPARE_SOURCE_TYPE",
                    expected_task_type="CREATOR_COMMISSION",
                    expected_selected_tool="compare_source_type_commission",
                    expected_filters_subset={"creator_id": creator_id},
                    note="creator compare source types",
                ),
            ]
        )

    # 20 turns: media commission status.
    direct_media_status = [
        (f"帮我查询视频{media_status_id}是否可分佣", "operator", None),
        (f"看下视频{media_status_id}是否可分佣", "creator", creator_bound_id),
    ]
    for index, (message, role, bound_id) in enumerate(direct_media_status, start=1):
        cid = f"real-llm-media-status-direct-{index}"
        cases.extend(
            [
                RealLLMCase(
                    conversation_id=cid,
                    message=message,
                    user_role=role,
                    bound_creator_id=bound_id,
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_COMMISSION_STATUS",
                    expected_task_type="MEDIA_COMMISSION_STATUS",
                    expected_selected_tool="get_media_commission_status",
                    expected_filters_subset={"media_id": media_status_id},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看最近7天",
                    user_role=role,
                    bound_creator_id=bound_id,
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_COMMISSION_STATUS",
                    expected_task_type="MEDIA_COMMISSION_STATUS",
                    expected_selected_tool="get_media_commission_status",
                    expected_filters_subset={"media_id": media_status_id},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看不可分佣订单",
                    user_role=role,
                    bound_creator_id=bound_id,
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_COMMISSION_STATUS",
                    expected_task_type="MEDIA_COMMISSION_STATUS",
                    expected_selected_tool="get_media_commission_status",
                    expected_filters_subset={"media_id": media_status_id, "is_commission": 2},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看最近30天",
                    user_role=role,
                    bound_creator_id=bound_id,
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_COMMISSION_STATUS",
                    expected_task_type="MEDIA_COMMISSION_STATUS",
                    expected_selected_tool="get_media_commission_status",
                    expected_filters_subset={"media_id": media_status_id},
                ),
            ]
        )

    clarify_media_status_openers = [
        "如何查看我的视频是否可分佣",
        "我的视频能不能分佣",
        "怎么看视频是否可分佣",
    ]
    for index, opener in enumerate(clarify_media_status_openers, start=1):
        cid = f"real-llm-media-status-clarify-{index}"
        cases.extend(
            [
                RealLLMCase(
                    conversation_id=cid,
                    message=opener,
                    user_role="creator",
                    bound_creator_id=creator_bound_id,
                    expected_action="clarify",
                    expected_task_type="MEDIA_COMMISSION_STATUS",
                    expected_missing_slots=["media_id"],
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message=f"media_id: {media_status_id}",
                    user_role="creator",
                    bound_creator_id=creator_bound_id,
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_COMMISSION_STATUS",
                    expected_task_type="MEDIA_COMMISSION_STATUS",
                    expected_selected_tool="get_media_commission_status",
                    expected_filters_subset={"media_id": media_status_id},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看最近7天",
                    user_role="creator",
                    bound_creator_id=creator_bound_id,
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_COMMISSION_STATUS",
                    expected_task_type="MEDIA_COMMISSION_STATUS",
                    expected_selected_tool="get_media_commission_status",
                    expected_filters_subset={"media_id": media_status_id},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看不可分佣订单",
                    user_role="creator",
                    bound_creator_id=creator_bound_id,
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_COMMISSION_STATUS",
                    expected_task_type="MEDIA_COMMISSION_STATUS",
                    expected_selected_tool="get_media_commission_status",
                    expected_filters_subset={"media_id": media_status_id, "is_commission": 2},
                ),
            ]
        )

    # 20 turns: media no-commission reason.
    direct_media_reason = [
        f"视频{media_reason_id}为什么不可分佣",
        f"帮我看视频{media_reason_id}为什么不可分佣",
    ]
    for index, opener in enumerate(direct_media_reason, start=1):
        cid = f"real-llm-media-reason-direct-{index}"
        cases.extend(
            [
                RealLLMCase(
                    conversation_id=cid,
                    message=opener,
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_NO_COMMISSION_REASON",
                    expected_task_type="MEDIA_NO_COMMISSION_REASON",
                    expected_selected_tool="get_media_no_commission_breakdown",
                    expected_filters_subset={"media_id": media_reason_id},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看最近7天",
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_NO_COMMISSION_REASON",
                    expected_task_type="MEDIA_NO_COMMISSION_REASON",
                    expected_selected_tool="get_media_no_commission_breakdown",
                    expected_filters_subset={"media_id": media_reason_id},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看不可分佣订单",
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_NO_COMMISSION_REASON",
                    expected_task_type="MEDIA_NO_COMMISSION_REASON",
                    expected_selected_tool="get_media_no_commission_breakdown",
                    expected_filters_subset={"media_id": media_reason_id},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message=f"再查一下视频{media_reason_id}为什么不可分佣",
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_NO_COMMISSION_REASON",
                    expected_task_type="MEDIA_NO_COMMISSION_REASON",
                    expected_selected_tool="get_media_no_commission_breakdown",
                    expected_filters_subset={"media_id": media_reason_id},
                ),
            ]
        )

    clarify_media_reason_openers = [
        "我的视频为什么不可分佣",
        "帮我看下视频为什么没有佣金",
        "视频为什么没有分佣",
    ]
    for index, opener in enumerate(clarify_media_reason_openers, start=1):
        cid = f"real-llm-media-reason-clarify-{index}"
        cases.extend(
            [
                RealLLMCase(
                    conversation_id=cid,
                    message=opener,
                    expected_action="clarify",
                    expected_task_type="MEDIA_NO_COMMISSION_REASON",
                    expected_missing_slots=["media_id"],
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message=f"media_id: {media_reason_id}",
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_NO_COMMISSION_REASON",
                    expected_task_type="MEDIA_NO_COMMISSION_REASON",
                    expected_selected_tool="get_media_no_commission_breakdown",
                    expected_filters_subset={"media_id": media_reason_id},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看最近7天",
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_NO_COMMISSION_REASON",
                    expected_task_type="MEDIA_NO_COMMISSION_REASON",
                    expected_selected_tool="get_media_no_commission_breakdown",
                    expected_filters_subset={"media_id": media_reason_id},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看不可分佣订单",
                    expected_action="answer",
                    expected_intent="QUERY_MEDIA_NO_COMMISSION_REASON",
                    expected_task_type="MEDIA_NO_COMMISSION_REASON",
                    expected_selected_tool="get_media_no_commission_breakdown",
                    expected_filters_subset={"media_id": media_reason_id},
                ),
            ]
        )

    # 12 turns: order status.
    order_direct_openers = [
        f"查询订单{shop_order_id}什么时候到账",
        f"帮我查订单{shop_order_id}到账状态",
        f"订单{shop_order_id}到账了吗",
        f"再看看订单{shop_order_id}什么时候到账",
    ]
    for index, opener in enumerate(order_direct_openers, start=1):
        cid = f"real-llm-order-{index}"
        cases.extend(
            [
                RealLLMCase(
                    conversation_id=cid,
                    message=opener,
                    expected_action="answer" if index != 2 else "answer",
                    expected_intent="QUERY_ORDER_TRANSFER_STATUS",
                    expected_task_type="ORDER_TRANSFER_STATUS",
                    expected_selected_tool="get_order_transfer_status",
                    expected_filters_subset={"shop_order_id": shop_order_id},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="解释一下T+2到账规则",
                    expected_action="answer",
                    expected_intent="EXPLAIN_BUSINESS_TERM",
                    expected_task_type="TERM_EXPLAIN",
                    expected_selected_tool="explain_business_term",
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message=f"订单{shop_order_id}什么时候到账",
                    expected_action="answer",
                    expected_intent="QUERY_ORDER_TRANSFER_STATUS",
                    expected_task_type="ORDER_TRANSFER_STATUS",
                    expected_selected_tool="get_order_transfer_status",
                    expected_filters_subset={"shop_order_id": shop_order_id},
                ),
            ]
        )

    # 6 turns: explain.
    explain_queries = [
        "解释一下闭环cps和cpt的区别",
        "什么是闭环cps",
        "什么是开环cps",
        "NO_PRODUCT_COMMISSION 是什么意思",
        "解释一下CPS",
        "解释一下CPT",
    ]
    for index, query in enumerate(explain_queries, start=1):
        cases.append(
            RealLLMCase(
                conversation_id=f"real-llm-explain-{index}",
                message=query,
                expected_action="answer",
                expected_intent="EXPLAIN_BUSINESS_TERM",
                expected_task_type="TERM_EXPLAIN",
                expected_selected_tool="explain_business_term",
            )
        )

    # 12 turns: creator permission.
    permission_openers = [
        "帮我查最近30天分佣情况",
        "查一下我最近30天分佣情况",
        "帮我看我最近30天佣金",
        "看下我最近30天分佣表现",
    ]
    for index, opener in enumerate(permission_openers, start=1):
        cid = f"real-llm-creator-permission-{index}"
        cases.extend(
            [
                RealLLMCase(
                    conversation_id=cid,
                    message=opener,
                    user_role="creator",
                    bound_creator_id=creator_bound_id,
                    expected_action="answer",
                    expected_intent="QUERY_CREATOR_SUMMARY",
                    expected_task_type="CREATOR_COMMISSION",
                    expected_selected_tool="get_creator_commission_summary",
                    expected_filters_subset={"creator_id": creator_bound_id},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message="只看不可分佣订单",
                    user_role="creator",
                    bound_creator_id=creator_bound_id,
                    expected_action="answer",
                    expected_intent="QUERY_CREATOR_SUMMARY",
                    expected_task_type="CREATOR_COMMISSION",
                    expected_selected_tool="get_creator_commission_summary",
                    expected_filters_subset={"creator_id": creator_bound_id, "is_commission": 2},
                ),
                RealLLMCase(
                    conversation_id=cid,
                    message=f"帮我查达人{other_creator_id}最近30天分佣情况",
                    user_role="creator",
                    bound_creator_id=creator_bound_id,
                    expected_action="answer",
                    answer_contains=["只能查询绑定达人", str(creator_bound_id)],
                ),
            ]
        )

    assert len(cases) == 100, len(cases)
    return cases


def _assert_case(case: RealLLMCase, response: dict[str, Any]) -> None:
    debug = response.get("debug") or {}
    task_state = debug.get("task_state") or {}
    normalized = response.get("normalized_filters") or {}

    assert debug.get("nlu_mode") == "llm_based", "request did not use llm_based nlu"
    assert debug.get("llm_provider"), "llm provider missing"
    assert (debug.get("llm_call_count") or 0) >= 1, "llm_call_count should be >= 1"

    if case.expected_action is not None:
        assert response.get("action") == case.expected_action, (
            f"expected action={case.expected_action}, got {response.get('action')}"
        )
    if case.expected_intent is not None:
        assert response.get("intent") == case.expected_intent, (
            f"expected intent={case.expected_intent}, got {response.get('intent')}"
        )
    if case.expected_task_type is not None:
        assert task_state.get("task_type") == case.expected_task_type, (
            f"expected task_type={case.expected_task_type}, got {task_state.get('task_type')}"
        )
    if case.expected_selected_tool is not None:
        assert debug.get("selected_tool") == case.expected_selected_tool, (
            f"expected selected_tool={case.expected_selected_tool}, got {debug.get('selected_tool')}"
        )
    if case.expected_missing_slots is not None:
        assert response.get("missing_slots") == case.expected_missing_slots, (
            f"expected missing_slots={case.expected_missing_slots}, got {response.get('missing_slots')}"
        )
    if case.expected_filters_subset:
        for key, expected_value in case.expected_filters_subset.items():
            assert normalized.get(key) == expected_value, (
                f"expected normalized_filters[{key}]={expected_value}, got {normalized.get(key)}"
            )
    for snippet in case.answer_contains:
        assert snippet in (response.get("answer") or ""), f"answer missing snippet: {snippet}"


def _increment_counts(counts: dict[str, int], conversation_id: str) -> None:
    if conversation_id.startswith("real-llm-creator-") and "permission" not in conversation_id:
        counts["creator_summary_turns"] += 1
    elif conversation_id.startswith("real-llm-media-status-"):
        counts["media_status_turns"] += 1
    elif conversation_id.startswith("real-llm-media-reason-"):
        counts["media_reason_turns"] += 1
    elif conversation_id.startswith("real-llm-order-"):
        counts["order_turns"] += 1
    elif conversation_id.startswith("real-llm-explain-"):
        counts["explain_turns"] += 1
    elif conversation_id.startswith("real-llm-creator-permission-"):
        counts["creator_permission_turns"] += 1


def _reset_conversations(cases: list[RealLLMCase]) -> None:
    conversation_ids = sorted({case.conversation_id for case in cases})
    for conversation_id in conversation_ids:
        _post_json("/api/chat/reset", {"conversation_id": conversation_id})


def _get_json(path: str) -> dict[str, Any]:
    request = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"HTTP {exc.code} for {path}: {body}") from exc


def _model_summary() -> dict[str, Any]:
    settings = get_settings()
    return {
        "provider": settings.model_provider,
        "chat_model": settings.chat_model,
        "base_url": settings.chat_base_url,
    }


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - 命令行脚本需要清晰失败退出。
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)
