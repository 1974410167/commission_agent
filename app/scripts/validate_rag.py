"""知识检索与解释能力校验脚本。"""

from __future__ import annotations

import json

from app.application.tools.knowledge_tools import KnowledgeTools


def _print_chunks(chunks: list[dict]) -> None:
    """打印检索到的核心 chunk 信息。"""
    for chunk in chunks:
        print(
            json.dumps(
                {
                    "chunk_id": chunk["chunk_id"],
                    "heading_path": chunk["heading_path"],
                    "score": chunk["score"],
                    "content_summary": chunk["content_summary"],
                },
                ensure_ascii=False,
            )
        )


def main() -> None:
    """跑几组 explain 查询，验证知识层可用性。"""
    tools = KnowledgeTools()
    cases = [
        "什么是闭环cps",
        "cpt和cps有什么区别",
        "NO_PRODUCT_COMMISSION 是什么意思",
    ]

    for query in cases:
        print(f"\n=== query: {query} ===")
        if "NO_PRODUCT_COMMISSION" in query:
            chunks = tools.retrieve_rule_knowledge(query)
            answer = tools.explain_rule_with_context({"no_commission_type_distribution": {"1": 10}}, query=query)
        else:
            chunks = tools.retrieve_term_knowledge(query)
            answer = tools.explain_business_term(query)
        print("top chunks:")
        _print_chunks(chunks)
        print("evidence:")
        print(json.dumps([item.model_dump() for item in answer.evidence], ensure_ascii=False, indent=2))
        print(f"answer: {answer.answer}")


if __name__ == "__main__":
    main()
