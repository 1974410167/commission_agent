"""验证 LangGraph 官方 checkpointer 的线程持久化。"""

from __future__ import annotations

import json

from app.application.agent.checkpointer import dump_conversation_state, get_thread_config, reset_conversation_state
from app.application.agent.graph import get_agent_workflow
from app.application.agent.state import build_turn_input
from app.config.settings import get_settings
from app.domain.agent_models import UserContext


def main() -> None:
    settings = get_settings()
    workflow = get_agent_workflow()
    conversation_id = "checkpointer-validate-1"
    user_context = UserContext(user_role="operator", bound_creator_id=None)

    print(f"backend: {settings.conversation_store_backend}")
    print(f"conversation_id: {conversation_id}")

    reset_conversation_state(conversation_id, settings)
    empty_snapshot = dump_conversation_state(workflow, conversation_id)
    assert empty_snapshot["messages"] == []
    print("empty_state:")
    print(json.dumps(empty_snapshot, ensure_ascii=False, indent=2))

    first = workflow.invoke(
        build_turn_input(conversation_id=conversation_id, message="帮我查达人88016最近30天分佣情况", user_context=user_context),
        config=get_thread_config(conversation_id),
    )
    first_snapshot = dump_conversation_state(workflow, conversation_id)
    assert first_snapshot["intent"] == "QUERY_CREATOR_SUMMARY"
    assert len(first_snapshot["messages"]) == 2
    print("after_first_turn:")
    print(json.dumps(first_snapshot, ensure_ascii=False, indent=2))

    second = workflow.invoke(
        build_turn_input(conversation_id=conversation_id, message="只看不可分佣订单", user_context=user_context),
        config=get_thread_config(conversation_id),
    )
    second_snapshot = dump_conversation_state(workflow, conversation_id)
    assert len(second_snapshot["messages"]) == 4
    print("after_second_turn:")
    print(json.dumps(second_snapshot, ensure_ascii=False, indent=2))

    for index in range(3, 8):
        workflow.invoke(
            build_turn_input(conversation_id=conversation_id, message=f"第{index}轮补充问题", user_context=user_context),
            config=get_thread_config(conversation_id),
        )

    final_snapshot = dump_conversation_state(workflow, conversation_id)
    assert len(final_snapshot["messages"]) == 10
    print("after_truncation:")
    print(json.dumps(final_snapshot, ensure_ascii=False, indent=2))

    reset_conversation_state(conversation_id, settings)
    reset_snapshot = dump_conversation_state(workflow, conversation_id)
    assert reset_snapshot["messages"] == []
    print("after_reset:")
    print(json.dumps(reset_snapshot, ensure_ascii=False, indent=2))

    # 避免变量未使用。
    _ = first, second


if __name__ == "__main__":
    main()
