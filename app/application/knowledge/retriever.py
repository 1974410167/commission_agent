"""轻量混合检索器。

策略很简单：
- 有向量时：向量分数为主，关键词分数为辅；
- 没向量时：退化成纯关键词检索；
- 不引入外部向量数据库，全部走本地文件。
"""

from __future__ import annotations

import math
import re

import numpy as np

from app.application.knowledge.embeddings import KnowledgeEmbeddingService
from app.domain.knowledge_models import KnowledgeChunk, RetrievedChunk


BUSINESS_TERMS = [
    "闭环cps",
    "开环cps",
    "cps",
    "cpt",
    "闭环",
    "开环",
    "t+2",
    "no_product_commission",
    "not_alliance_creator",
    "fulfilment_task_invalid_status",
    "creator_package_task_not_cps_task",
    "commission_rate_zero",
    "no_exist_shop_from_order_poi",
    "transfer_type",
    "no_transfer_reason",
    "订单不可归因",
    "订单未完成",
    "订单已关闭",
    "kyc未开户",
    "pipo未开户",
]

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+\-]{2,}|[\u4e00-\u9fff]{2,}")


class KnowledgeRetriever:
    """对知识块做向量 + 关键词混合排序。"""

    def __init__(self, embedding_service: KnowledgeEmbeddingService) -> None:
        self.embedding_service = embedding_service

    def retrieve(
        self,
        query: str,
        *,
        chunks: list[KnowledgeChunk],
        vectors: np.ndarray | None,
        top_k: int = 4,
    ) -> list[RetrievedChunk]:
        """检索 top_k 知识块。"""
        # 两路分数并行算：
        # - keyword 更可解释；
        # - embedding 更鲁棒。
        keyword_scores = [self._keyword_score(query, chunk) for chunk in chunks]
        embedding_scores = self._embedding_scores(query, vectors) if vectors is not None else [0.0] * len(chunks)

        scored: list[RetrievedChunk] = []
        for index, chunk in enumerate(chunks):
            score = (embedding_scores[index] * 0.8) + (keyword_scores[index] * 0.2) if vectors is not None else keyword_scores[index]
            if score <= 0:
                continue
            scored.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    source_file=chunk.source_file,
                    heading_path=chunk.heading_path,
                    text=chunk.text,
                    content_summary=self._summarize_text(chunk.text),
                    score=round(float(score), 4),
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]

    def _embedding_scores(self, query: str, vectors: np.ndarray | None) -> list[float]:
        """计算 query 向量与知识块向量的余弦相似度。"""
        if vectors is None:
            return []
        query_vectors = self.embedding_service.embed_texts([query])
        if query_vectors is None or len(query_vectors) == 0:
            return [0.0] * len(vectors)
        query_vector = query_vectors[0]
        query_norm = np.linalg.norm(query_vector)
        if query_norm == 0:
            return [0.0] * len(vectors)
        vector_norms = np.linalg.norm(vectors, axis=1)
        scores = np.dot(vectors, query_vector) / np.maximum(vector_norms * query_norm, 1e-8)
        return scores.astype(float).tolist()

    def _keyword_score(self, query: str, chunk: KnowledgeChunk) -> float:
        """计算简单关键词命中分。"""
        haystack = (" ".join(chunk.heading_path) + "\n" + chunk.text).lower()
        terms = self._extract_terms(query)
        if not terms:
            return 0.0
        hit_count = 0.0
        for term in terms:
            if term in haystack:
                hit_count += 1.0
            elif any(term in keyword for keyword in chunk.keywords):
                hit_count += 0.6
        return hit_count / max(len(terms), 1)

    @staticmethod
    def _extract_terms(query: str) -> list[str]:
        """提取 query 中更偏业务域的关键词集合。"""
        normalized = query.lower().replace(" ", "")
        terms = [term for term in BUSINESS_TERMS if term in normalized]
        terms.extend(match.group(0).lower() for match in TOKEN_PATTERN.finditer(query))
        deduped: list[str] = []
        for term in terms:
            if term not in deduped:
                deduped.append(term)
        return deduped

    @staticmethod
    def _summarize_text(text: str, limit: int = 120) -> str:
        """把多行 markdown 文本压成短摘要。"""
        compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
        return compact[:limit] + ("..." if len(compact) > limit else "")
