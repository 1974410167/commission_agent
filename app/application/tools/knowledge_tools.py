"""知识工具层。"""

from __future__ import annotations

from typing import Any

from app.application.knowledge.service import KnowledgeService
from app.domain.intent_models import KnowledgeExplainResult


class KnowledgeTools:
    """把知识检索和解释能力封装成 workflow 可直接调用的工具。"""

    def __init__(self) -> None:
        self.service = KnowledgeService()

    def retrieve_term_knowledge(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        """检索术语类知识块。"""
        chunks = self.service.retrieve_term_knowledge(query=query, top_k=top_k)
        return [chunk.model_dump() for chunk in chunks]

    def retrieve_rule_knowledge(self, code_or_query: str, top_k: int = 4) -> list[dict[str, Any]]:
        """检索规则类知识块。"""
        chunks = self.service.retrieve_rule_knowledge(code_or_query=code_or_query, top_k=top_k)
        return [chunk.model_dump() for chunk in chunks]

    def explain_business_term(self, term_or_query: str, context: dict[str, Any] | None = None) -> KnowledgeExplainResult:
        """解释业务术语，例如 CPS / CPT / 闭环 / 开环。"""
        payload = self.service.explain_business_term(term_or_query=term_or_query, context=context)
        return KnowledgeExplainResult(
            query=payload.query,
            answer=payload.answer,
            evidence=payload.evidence,
            matched_chunks=payload.matched_chunks,
            mode=payload.mode,
        )

    def explain_rule_with_context(
        self,
        fact_payload: dict[str, Any],
        query: str | None = None,
    ) -> KnowledgeExplainResult:
        """围绕事实结果补充规则解释，但不改写事实本身。"""
        payload = self.service.explain_rule_with_context(fact_payload=fact_payload, query=query)
        return KnowledgeExplainResult(
            query=payload.query,
            answer=payload.answer,
            evidence=payload.evidence,
            matched_chunks=payload.matched_chunks,
            mode=payload.mode,
        )
