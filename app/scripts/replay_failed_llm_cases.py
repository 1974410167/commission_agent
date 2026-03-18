"""重放上一轮真实 LLM 回归里失败的 8 个 turn。

这个脚本直接打本地 `/api/chat`，确保每个 case 都经过：
- 真实 LLM 理解
- 真实 LangGraph 状态机
- 真实 ES 查询

当前聚焦两个失败簇：
- MEDIA_COMMISSION_STATUS clarify 链路
- "视频为什么没有分佣" 误分到错误任务
"""

from __future__ import annotations

import json
import sys
import urllib.request
from dataclasses import dataclass
from typing import Any


BASE_URL = "http://127.0.0.1:8002"


@dataclass
class ReplayCase:
    conversation_id: str
    message: str
    user_role: str
    bound_creator_id: int | None
    expected: dict[str, Any]


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def _reset(conversation_id: str) -> None:
    _post_json("/api/chat/reset", {"conversation_id": conversation_id})


def main() -> None:
    cases = [
        ReplayCase(
            conversation_id="retry-status-1",
            message="如何查看我的视频是否可分佣",
            user_role="creator",
            bound_creator_id=88001,
            expected={"action": "clarify", "task_type": "MEDIA_COMMISSION_STATUS"},
        ),
        ReplayCase(
            conversation_id="retry-status-1",
            message="media_id: 990041",
            user_role="creator",
            bound_creator_id=88001,
            expected={
                "action": "answer",
                "intent": "QUERY_MEDIA_COMMISSION_STATUS",
                "task_type": "MEDIA_COMMISSION_STATUS",
                "selected_tool": "get_media_commission_status",
            },
        ),
        ReplayCase(
            conversation_id="retry-status-1",
            message="只看最近7天",
            user_role="creator",
            bound_creator_id=88001,
            expected={
                "action": "answer",
                "intent": "QUERY_MEDIA_COMMISSION_STATUS",
                "task_type": "MEDIA_COMMISSION_STATUS",
                "selected_tool": "get_media_commission_status",
            },
        ),
        ReplayCase(
            conversation_id="retry-status-1",
            message="只看不可分佣订单",
            user_role="creator",
            bound_creator_id=88001,
            expected={
                "action": "answer",
                "intent": "QUERY_MEDIA_COMMISSION_STATUS",
                "task_type": "MEDIA_COMMISSION_STATUS",
                "selected_tool": "get_media_commission_status",
            },
        ),
        ReplayCase(
            conversation_id="retry-status-2",
            message="我的视频能不能分佣",
            user_role="creator",
            bound_creator_id=88001,
            expected={"action": "clarify", "task_type": "MEDIA_COMMISSION_STATUS"},
        ),
        ReplayCase(
            conversation_id="retry-status-3",
            message="怎么看视频是否可分佣",
            user_role="creator",
            bound_creator_id=88001,
            expected={"action": "clarify", "task_type": "MEDIA_COMMISSION_STATUS"},
        ),
        ReplayCase(
            conversation_id="retry-reason-3",
            message="视频为什么没有分佣",
            user_role="operator",
            bound_creator_id=None,
            expected={"action": "clarify", "task_type": "MEDIA_NO_COMMISSION_REASON"},
        ),
        ReplayCase(
            conversation_id="retry-reason-3",
            message="media_id: 990041",
            user_role="operator",
            bound_creator_id=None,
            expected={
                "action": "answer",
                "intent": "QUERY_MEDIA_NO_COMMISSION_REASON",
                "task_type": "MEDIA_NO_COMMISSION_REASON",
                "selected_tool": "get_media_no_commission_breakdown",
            },
        ),
    ]

    for conversation_id in sorted({case.conversation_id for case in cases}):
        _reset(conversation_id)

    failures: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        response = _post_json(
            "/api/chat",
            {
                "conversation_id": case.conversation_id,
                "message": case.message,
                "user_role": case.user_role,
                "bound_creator_id": case.bound_creator_id,
            },
        )
        debug = response.get("debug") or {}
        task_state = debug.get("task_state") or {}
        row = {
            "index": index,
            "conversation_id": case.conversation_id,
            "message": case.message,
            "action": response.get("action"),
            "intent": response.get("intent"),
            "task_type": task_state.get("task_type"),
            "selected_tool": debug.get("selected_tool"),
            "missing_slots": response.get("missing_slots"),
            "answer": response.get("answer"),
            "llm_provider": debug.get("llm_provider"),
            "chat_model": debug.get("chat_model"),
            "llm_call_count": debug.get("llm_call_count"),
        }
        errors: list[str] = []
        for key, expected_value in case.expected.items():
            actual_value = row.get(key)
            if actual_value != expected_value:
                errors.append(f"{key}: expected {expected_value}, got {actual_value}")
        row["status"] = "failed" if errors else "passed"
        if errors:
            row["errors"] = errors
            failures.append(row)
        print(json.dumps(row, ensure_ascii=False))

    summary = {
        "total": len(cases),
        "failed": len(failures),
        "failures": failures,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)
