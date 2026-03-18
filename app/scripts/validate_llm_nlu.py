"""NLU 选择和抽取结果校验脚本。"""

from __future__ import annotations

import json

from app.application.agent.state import build_turn_input
from app.application.nlu.factory import NLUFactory
from app.config.settings import get_settings
from app.domain.agent_models import ConversationMessage, UserContext


def main() -> None:
    """用几组代表性 query 验证 intent 和 slot 抽取。"""
    settings = get_settings()
    nlu = NLUFactory.create()
    queries = [
        "帮我查达人88016最近30天分佣情况",
        "只看最近7天",
        "帮我查询视频990000是否可分佣",
        "帮我查视频990041为什么不可分佣",
        "订单SO-20260308-001127什么时候到账",
        "解释闭环cps和cpt有什么区别",
        "对比闭环cps和开环cps",
    ]

    print(f"chat provider: {settings.model_provider}")
    print(f"chat model: {settings.chat_model}")

    if not settings.chat_enabled:
        print("llm nlu unavailable")
    else:
        print("llm mode enabled")

    messages: list[ConversationMessage] = []
    for index, query in enumerate(queries, start=1):
        understanding = nlu.understand_query(
            {
                **build_turn_input(
                    conversation_id=f"validate-llm-{index}",
                    message=query,
                    user_context=UserContext(user_role="operator", bound_creator_id=None),
                ),
                "messages": messages,
            }
        )
        print(f"\nquery: {query}")
        print(f"turn_type: {understanding.turn_type.value}")
        print(f"entity_scope: {understanding.entity_scope.value if understanding.entity_scope else None}")
        print(f"goal_type: {understanding.goal_type.value if understanding.goal_type else None}")
        print(f"task_type: {understanding.task_type.value if understanding.task_type else None}")
        print(f"confidence: {understanding.confidence}")
        print(json.dumps(understanding.slots.model_dump(), ensure_ascii=False, indent=2))
        messages.extend(
            [
                ConversationMessage(role="user", content=query),
                ConversationMessage(role="assistant", content="校验占位回答"),
            ]
        )
        messages = messages[-10:]


if __name__ == "__main__":
    main()
