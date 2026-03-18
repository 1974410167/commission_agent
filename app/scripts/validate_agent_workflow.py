"""第二阶段 Agent workflow 校验脚本。"""

from __future__ import annotations

import json

from app.application.agent.graph import get_agent_workflow
from app.config.settings import get_settings
from app.domain.agent_models import UserContext
from app.infrastructure.es.client import create_es_client
from app.infrastructure.es.repository import CommissionOrderRepository


def _print_case(title: str, response: dict[str, object]) -> None:
    """打印单个 workflow 校验案例。"""
    print(f"\n=== {title} ===")
    print(f"intent: {response['intent']}")
    print(f"action: {response['action']}")
    print("normalized_filters:")
    print(json.dumps(response["normalized_filters"], ensure_ascii=False, indent=2))
    print(f"answer: {response['answer']}")
    print("evidence:")
    print(json.dumps(response["evidence"], ensure_ascii=False, indent=2))


def main() -> None:
    """执行第二阶段定义的多轮 workflow 校验场景。"""
    settings = get_settings()
    client = create_es_client(settings)
    repository = CommissionOrderRepository(client=client, index_name=settings.es_index)
    workflow = get_agent_workflow()

    creator_id = repository.find_recent_creator_id()
    media_id = repository.find_media_id_with_non_commission()
    shop_order_id = repository.find_latest_shop_order_id()
    compare_pair = repository.find_creator_with_multiple_source_types()
    if creator_id is None or media_id is None or shop_order_id is None or compare_pair is None:
        raise RuntimeError("seed data not ready for agent validation")

    compare_creator_id, source_types = compare_pair
    creator_id = creator_id or compare_creator_id

    conversation_id = "validate-operator-summary"
    cases = [
        (
            "1. operator 查询某达人最近30天分佣情况",
            {
                "conversation_id": conversation_id,
                "message": f"帮我查达人{creator_id}最近30天分佣情况",
                "user_context": UserContext(user_role="operator"),
            },
        ),
        (
            "2. follow-up 只看不可分佣订单",
            {
                "conversation_id": conversation_id,
                "message": "只看不可分佣订单",
                "user_context": UserContext(user_role="operator"),
            },
        ),
        (
            "3. follow-up 按视频展开",
            {
                "conversation_id": conversation_id,
                "message": "按视频展开",
                "user_context": UserContext(user_role="operator"),
            },
        ),
        (
            "4. 查询某视频为什么不可分佣",
            {
                "conversation_id": "validate-media-breakdown",
                "message": f"帮我查视频{media_id}为什么不可分佣",
                "user_context": UserContext(user_role="operator"),
            },
        ),
        (
            "5. 查询某订单什么时候到账",
            {
                "conversation_id": "validate-order-status",
                "message": f"订单{shop_order_id}什么时候到账",
                "user_context": UserContext(user_role="operator"),
            },
        ),
        (
            "6. 解释闭环cps和cpt有什么区别",
            {
                "conversation_id": "validate-knowledge",
                "message": "解释闭环cps和cpt有什么区别",
                "user_context": UserContext(user_role="operator"),
            },
        ),
        (
            "7. follow-up 对比闭环cps和开环cps",
            {
                "conversation_id": conversation_id,
                "message": "对比闭环cps和开环cps",
                "user_context": UserContext(user_role="operator"),
            },
        ),
    ]

    non_empty_answers = 0
    for title, payload in cases:
        result = workflow.invoke(payload)
        response = result["response"].model_dump()
        _print_case(title, response)
        if response["action"] in {"answer", "clarify"} and response["answer"]:
            non_empty_answers += 1

    if non_empty_answers < 7:
        raise RuntimeError("agent workflow validation did not produce all expected outputs")


if __name__ == "__main__":
    main()
