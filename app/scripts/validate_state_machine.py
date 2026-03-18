"""状态机专项验证。

这个脚本不盯具体回答文案，而是盯状态转移是否符合预期：
- follow-up 只改 filters / plan，不随意切任务
- clarify 进入 CLARIFYING，再通过补参回到 READY
- explain 不继承业务查询 filters
"""

from __future__ import annotations

import json

from app.application.agent.checkpointer import dump_conversation_state, get_thread_config, reset_conversation_state
from app.application.agent.graph import get_agent_workflow
from app.application.agent.state import build_turn_input
from app.config.settings import get_settings
from app.domain.agent_models import UserContext
from app.infrastructure.es.client import create_es_client
from app.infrastructure.es.repository import CommissionOrderRepository


def main() -> None:
    settings = get_settings()
    workflow = get_agent_workflow()
    repository = CommissionOrderRepository(create_es_client(settings), index_name=settings.es_index)
    conversation_id = "state-machine-validate-1"
    clarify_id = "state-machine-validate-clarify"
    media_status_id = "state-machine-validate-media-status"
    media_status_clarify_id = "state-machine-validate-media-status-clarify"
    explain_id = "state-machine-validate-explain"
    reset_conversation_state(conversation_id, settings)
    reset_conversation_state(clarify_id, settings)
    reset_conversation_state(media_status_id, settings)
    reset_conversation_state(media_status_clarify_id, settings)
    reset_conversation_state(explain_id, settings)

    user = UserContext(user_role="operator", bound_creator_id=None)
    media_id = repository.find_recent_media_id() or 990041

    summary = _invoke(workflow, conversation_id, "帮我查达人88001最近30天分佣情况", user)
    assert summary["intent"] == "QUERY_CREATOR_SUMMARY"
    assert summary["debug"]["task_state"]["task_type"] == "CREATOR_COMMISSION"

    recent = _invoke(workflow, conversation_id, "只看最近7天", user)
    assert recent["debug"]["task_state"]["task_type"] == "CREATOR_COMMISSION"

    non_commission = _invoke(workflow, conversation_id, "只看不可分佣订单", user)
    assert non_commission["normalized_filters"]["is_commission"] == 2
    assert non_commission["debug"]["task_state"]["task_type"] == "CREATOR_COMMISSION"

    by_media = _invoke(workflow, conversation_id, "按视频展开", user)
    assert by_media["intent"] == "SUMMARIZE_BY_MEDIA"
    assert by_media["debug"]["selected_tool"] == "summarize_commission_by_media"
    assert by_media["debug"]["task_state"]["task_type"] == "CREATOR_COMMISSION"

    clarify = _invoke(workflow, clarify_id, "我的视频为什么不可分佣", user)
    assert clarify["action"] == "clarify"
    assert clarify["debug"]["task_state"]["status"] == "CLARIFYING"
    assert clarify["missing_slots"] == ["media_id"]

    clarify_answer = _invoke(workflow, clarify_id, "media_id: 990041", user)
    assert clarify_answer["action"] == "answer"
    assert clarify_answer["debug"]["task_state"]["status"] == "READY"
    assert clarify_answer["normalized_filters"]["media_id"] == 990041

    media_status = _invoke(workflow, media_status_id, f"帮我查询视频{media_id}是否可分佣", user)
    assert media_status["intent"] == "QUERY_MEDIA_COMMISSION_STATUS"
    assert media_status["debug"]["task_state"]["task_type"] == "MEDIA_COMMISSION_STATUS"
    assert media_status["normalized_filters"]["media_id"] == media_id

    media_status_clarify = _invoke(workflow, media_status_clarify_id, "如何查看我的视频是否可分佣", user)
    assert media_status_clarify["action"] == "clarify"
    assert media_status_clarify["debug"]["task_state"]["task_type"] == "MEDIA_COMMISSION_STATUS"
    assert media_status_clarify["missing_slots"] == ["media_id"]

    explain = _invoke(workflow, explain_id, "解释一下闭环cps和cpt的区别", user)
    assert explain["intent"] == "EXPLAIN_BUSINESS_TERM"
    assert explain["debug"]["task_state"]["task_type"] == "TERM_EXPLAIN"
    assert explain["normalized_filters"]["creator_id"] is None

    print(
        json.dumps(
            {
                "summary_task_type": summary["debug"]["task_state"]["task_type"],
                "recent_filters": recent["normalized_filters"],
                "non_commission_filters": non_commission["normalized_filters"],
                "by_media_tool": by_media["debug"]["selected_tool"],
                "clarify_status": clarify["debug"]["task_state"]["status"],
                "clarify_answer_media_id": clarify_answer["normalized_filters"]["media_id"],
                "media_status_intent": media_status["intent"],
                "media_status_task_type": media_status["debug"]["task_state"]["task_type"],
                "media_status_clarify_action": media_status_clarify["action"],
                "explain_task_type": explain["debug"]["task_state"]["task_type"],
                "snapshot": dump_conversation_state(workflow, conversation_id),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _invoke(workflow, conversation_id: str, message: str, user_context: UserContext) -> dict:
    result = workflow.invoke(
        build_turn_input(
            conversation_id=conversation_id,
            message=message,
            user_context=user_context,
        ),
        config=get_thread_config(conversation_id),
    )
    return result["response"].model_dump()


if __name__ == "__main__":
    main()
