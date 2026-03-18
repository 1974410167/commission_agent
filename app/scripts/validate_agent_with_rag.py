"""第三阶段 Agent + RAG 校验脚本。"""

from __future__ import annotations

import json

from app.application.agent.graph import get_agent_workflow
from app.config.settings import get_settings
from app.domain.agent_models import UserContext
from app.infrastructure.es.client import create_es_client
from app.infrastructure.es.repository import CommissionOrderRepository


def _print_case(title: str, response: dict[str, object]) -> None:
    """打印单个 Agent + RAG 场景结果。"""
    print(f"\n=== {title} ===")
    print(f"query action: {response['action']}")
    print(f"intent: {response['intent']}")
    debug = response.get("debug") or {}
    print(f"nlu mode: {debug.get('nlu_mode')}")
    print(f"selected tool: {debug.get('selected_tool')}")
    print("normalized filters:")
    print(json.dumps(response["normalized_filters"], ensure_ascii=False, indent=2))
    print(f"answer: {response['answer']}")
    print("evidence:")
    print(json.dumps(response["evidence"], ensure_ascii=False, indent=2))


def main() -> None:
    """执行第三阶段定义的 Agent + RAG 场景矩阵。"""
    settings = get_settings()
    client = create_es_client(settings)
    repository = CommissionOrderRepository(client=client, index_name=settings.es_index)
    workflow = get_agent_workflow()

    creator_id = repository.find_recent_creator_id()
    media_id = repository.find_media_id_with_non_commission()
    shop_order_id = repository.find_latest_shop_order_id()
    if creator_id is None or media_id is None or shop_order_id is None:
        raise RuntimeError("seed data not ready for agent validation")

    conversation_id = "validate-agent-rag-1"
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
                "conversation_id": "validate-agent-rag-media",
                "message": f"帮我查视频{media_id}为什么不可分佣",
                "user_context": UserContext(user_role="operator"),
            },
        ),
        (
            "5. 查询某订单什么时候到账",
            {
                "conversation_id": "validate-agent-rag-order",
                "message": f"订单{shop_order_id}什么时候到账",
                "user_context": UserContext(user_role="operator"),
            },
        ),
        (
            "6. 解释闭环cps 和 cpt 的区别",
            {
                "conversation_id": "validate-agent-rag-knowledge",
                "message": "解释闭环cps和cpt有什么区别",
                "user_context": UserContext(user_role="operator"),
            },
        ),
        (
            "7. creator 模式自动绑定 creator_id",
            {
                "conversation_id": "validate-agent-rag-creator",
                "message": "帮我查最近30天分佣情况",
                "user_context": UserContext(user_role="creator", bound_creator_id=creator_id),
            },
        ),
        (
            "8. explain 术语问题",
            {
                "conversation_id": "validate-agent-rag-fallback",
                "message": "解释一下 NO_PRODUCT_COMMISSION",
                "user_context": UserContext(user_role="operator"),
            },
        ),
    ]

    non_empty_answers = 0
    for title, payload in cases:
        result = workflow.invoke(payload)
        response = result["response"].model_dump()
        _print_case(title, response)
        if response["answer"]:
            non_empty_answers += 1

    if non_empty_answers < len(cases):
        raise RuntimeError("agent with rag validation did not produce all expected outputs")


if __name__ == "__main__":
    main()
