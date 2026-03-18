"""在 postgres checkpointer backend 下验证 Agent 多轮会话。"""

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
    creator_id = repository.find_recent_creator_id() or 88016
    recent_media_id = repository.find_recent_media_id() or 990041
    media_id = repository.find_media_id_with_non_commission()
    shop_order_id = repository.find_latest_shop_order_id()

    summary_conversation_id = "agent-postgres-validate-summary"
    clarify_conversation_id = "agent-postgres-validate-clarify"
    media_status_conversation_id = "agent-postgres-validate-media-status"
    order_conversation_id = "agent-postgres-validate-order"
    explain_conversation_id = "agent-postgres-validate-explain"
    reset_conversation_state(summary_conversation_id, settings)
    reset_conversation_state(clarify_conversation_id, settings)
    reset_conversation_state(media_status_conversation_id, settings)
    reset_conversation_state(order_conversation_id, settings)
    reset_conversation_state(explain_conversation_id, settings)

    turns = [
        (
            "operator",
            f"帮我查达人{creator_id}最近30天分佣情况",
            UserContext(user_role="operator", bound_creator_id=None),
            summary_conversation_id,
        ),
        (
            "follow_up",
            "只看不可分佣订单",
            UserContext(user_role="operator", bound_creator_id=None),
            summary_conversation_id,
        ),
        (
            "follow_up",
            "按视频展开",
            UserContext(user_role="operator", bound_creator_id=None),
            summary_conversation_id,
        ),
        (
            "clarify_question",
            "我的视频为什么不可分佣",
            UserContext(user_role="operator", bound_creator_id=None),
            clarify_conversation_id,
        ),
        (
            "clarify_follow_up",
            f"media_id: {media_id}",
            UserContext(user_role="operator", bound_creator_id=None),
            clarify_conversation_id,
        ),
        (
            "media_status",
            f"帮我查询视频{recent_media_id}是否可分佣",
            UserContext(user_role="operator", bound_creator_id=None),
            media_status_conversation_id,
        ),
        (
            "order_status",
            f"订单{shop_order_id}什么时候到账",
            UserContext(user_role="operator", bound_creator_id=None),
            order_conversation_id,
        ),
        (
            "explain",
            "解释一下闭环cps和cpt的区别",
            UserContext(user_role="operator", bound_creator_id=None),
            explain_conversation_id,
        ),
    ]

    print(f"backend: {settings.conversation_store_backend}")
    assert settings.conversation_store_backend == "postgres"
    assert media_id is not None
    assert recent_media_id is not None
    assert shop_order_id is not None
    for label, message, user_context, conversation_id in turns:
        result = workflow.invoke(
            build_turn_input(
                conversation_id=conversation_id,
                message=message,
                user_context=user_context,
            ),
            config=get_thread_config(conversation_id),
        )
        response = result["response"].model_dump()
        snapshot = dump_conversation_state(workflow, conversation_id)
        assert snapshot["conversation_id"] == conversation_id
        assert snapshot["intent"] == response["intent"]
        assert len(snapshot["messages"]) >= 2
        if label == "clarify_question":
            assert response["action"] == "clarify"
            assert response["missing_slots"] == ["media_id"]
        if label == "clarify_follow_up":
            assert response["action"] == "answer"
            assert response["intent"] == "QUERY_MEDIA_NO_COMMISSION_REASON"
            assert response["normalized_filters"]["media_id"] == media_id
        if label == "media_status":
            assert response["action"] == "answer"
            assert response["intent"] == "QUERY_MEDIA_COMMISSION_STATUS"
            assert response["normalized_filters"]["media_id"] == recent_media_id
            assert (response.get("debug") or {}).get("selected_tool") == "get_media_commission_status"
        if label == "follow_up" and message == "只看不可分佣订单":
            assert response["normalized_filters"]["is_commission"] == 2
            assert (response.get("debug") or {}).get("selected_tool") == "get_creator_commission_summary"
        if label == "follow_up" and message == "按视频展开":
            assert response["intent"] == "SUMMARIZE_BY_MEDIA"
            assert response["normalized_filters"]["group_by"] == "media_id"
            assert (response.get("debug") or {}).get("selected_tool") == "summarize_commission_by_media"
        print("\nturn:")
        print(
            json.dumps(
                {
                    "label": label,
                    "message": message,
                    "conversation_id": conversation_id,
                    "intent": response["intent"],
                    "action": response["action"],
                    "normalized_filters": response["normalized_filters"],
                    "selected_tool": (response.get("debug") or {}).get("selected_tool"),
                    "llm_call_count": (response.get("debug") or {}).get("llm_call_count"),
                    "snapshot_summary": {
                        "action": snapshot.get("action"),
                        "intent": snapshot.get("intent"),
                        "normalized_filters": snapshot.get("normalized_filters"),
                        "selected_tool": snapshot.get("selected_tool"),
                        "missing_slots": snapshot.get("missing_slots"),
                        "message_count": len(snapshot.get("messages", [])),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
