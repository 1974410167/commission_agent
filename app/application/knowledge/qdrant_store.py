"""Qdrant 向量存储与检索封装。"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from app.config.settings import Settings, get_settings
from app.domain.knowledge_models import KnowledgeChunk, RetrievedChunk

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qdrant_models
except ImportError:  # pragma: no cover - 依赖未安装时走 local fallback
    QdrantClient = None
    qdrant_models = None


class QdrantKnowledgeStore:
    """把知识块向量存入 Qdrant，并负责向量检索。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.collection_name = self.settings.qdrant_collection
        self.client = self._build_client()

    @property
    def available(self) -> bool:
        """当前是否具备真实 Qdrant 能力。"""
        return self.client is not None and qdrant_models is not None

    def upsert_chunks(self, chunks: list[KnowledgeChunk], vectors: np.ndarray) -> None:
        """把 chunks 和对应向量写入 Qdrant。"""
        if not self.available:
            return
        if len(chunks) == 0 or len(vectors) == 0:
            return
        vector_size = int(vectors.shape[1])
        self._ensure_collection(vector_size)
        points = [
            qdrant_models.PointStruct(
                id=self._point_id(chunk.chunk_id),
                vector=vectors[index].tolist(),
                payload=self._chunk_to_payload(chunk),
            )
            for index, chunk in enumerate(chunks)
        ]
        self.client.upsert(collection_name=self.collection_name, points=points, wait=True)

    def search(
        self,
        *,
        query_vector: np.ndarray,
        top_k: int,
        payload_filter: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """按向量相似度检索知识块。"""
        if not self.available:
            return []
        search_filter = self._build_filter(payload_filter)
        hits = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector.tolist(),
            query_filter=search_filter,
            limit=top_k,
        )
        return [self._hit_to_chunk(hit) for hit in hits]

    def _build_client(self) -> QdrantClient | None:
        if QdrantClient is None or not self.settings.qdrant_enabled:
            return None
        if self.settings.qdrant_path:
            return QdrantClient(path=self.settings.qdrant_path)
        return QdrantClient(url=self.settings.qdrant_url, api_key=self.settings.qdrant_api_key or None, timeout=10.0)

    def _ensure_collection(self, vector_size: int) -> None:
        if not self.available:
            return
        current_size = None
        try:
            info = self.client.get_collection(self.collection_name)
            current_size = getattr(info.config.params.vectors, "size", None)
        except Exception:
            current_size = None
        if current_size == vector_size:
            return
        if current_size is not None:
            self.client.delete_collection(collection_name=self.collection_name)
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=qdrant_models.VectorParams(size=vector_size, distance=qdrant_models.Distance.COSINE),
        )

    @staticmethod
    def _chunk_to_payload(chunk: KnowledgeChunk) -> dict[str, Any]:
        heading_path_text = " / ".join(chunk.heading_path)
        return {
            "chunk_id": chunk.chunk_id,
            "source_file": chunk.source_file,
            "heading_path": chunk.heading_path,
            "heading_path_text": heading_path_text,
            "text": chunk.text,
            "keywords": chunk.keywords,
            "content_summary": QdrantKnowledgeStore._summarize_text(chunk.text),
        }

    @staticmethod
    def _point_id(chunk_id: str) -> int:
        """把业务 chunk_id 映射成 Qdrant 可接受的稳定整数 id。"""
        digest = hashlib.sha1(chunk_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], byteorder="big", signed=False) & 0x7FFF_FFFF_FFFF_FFFF

    @staticmethod
    def _hit_to_chunk(hit: Any) -> RetrievedChunk:
        payload = hit.payload or {}
        return RetrievedChunk(
            chunk_id=str(payload.get("chunk_id", hit.id)),
            source_file=str(payload.get("source_file", "")),
            heading_path=list(payload.get("heading_path", [])),
            text=str(payload.get("text", "")),
            content_summary=str(payload.get("content_summary", "")),
            score=round(float(hit.score), 4),
        )

    @staticmethod
    def _summarize_text(text: str, limit: int = 120) -> str:
        compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
        return compact[:limit] + ("..." if len(compact) > limit else "")

    @staticmethod
    def _build_filter(payload_filter: dict[str, Any] | None) -> Any | None:
        """当前只支持简单的等值 / 多值过滤。"""
        if not payload_filter or qdrant_models is None:
            return None
        conditions: list[Any] = []
        for key, value in payload_filter.items():
            if value is None:
                continue
            if isinstance(value, list):
                conditions.append(
                    qdrant_models.FieldCondition(key=key, match=qdrant_models.MatchAny(any=value))
                )
            else:
                conditions.append(
                    qdrant_models.FieldCondition(key=key, match=qdrant_models.MatchValue(value=value))
                )
        if not conditions:
            return None
        return qdrant_models.Filter(must=conditions)
