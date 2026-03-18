"""embedding 生成器。"""

from __future__ import annotations

import numpy as np

from app.application.llm.client import OpenAICompatibleClient
from app.config.settings import Settings, get_settings


class KnowledgeEmbeddingService:
    """为知识块和用户 query 生成向量。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = OpenAICompatibleClient(self.settings)
        self.batch_size = 8

    @property
    def enabled(self) -> bool:
        """当前 embedding 能力是否可用。"""
        return bool(self.settings.rag_enabled and self.client.enabled)

    def embed_texts(self, texts: list[str]) -> np.ndarray | None:
        """分批生成向量，避免一次请求过大导致 provider 失败。"""
        if not self.enabled:
            return None
        vectors: list[list[float]] = []
        # 分批请求是必要的：
        # embedding 接口虽然支持批量，但一次塞太多文本更容易失败。
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            payload = self.client.embeddings(batch)
            if payload is None:
                return None
            vectors.extend(payload.vectors)
        return np.array(vectors, dtype=np.float32)
