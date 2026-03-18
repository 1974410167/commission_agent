"""本地文件向量存储。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.domain.knowledge_models import KnowledgeChunk


class LocalKnowledgeVectorStore:
    """在本地文件中持久化 chunks、meta 和向量。"""

    def save(
        self,
        *,
        chunks_path: Path,
        index_meta_path: Path,
        index_vector_path: Path,
        chunks: list[KnowledgeChunk],
        mode: str,
        embedding_model: str | None,
        vectors: np.ndarray | None,
    ) -> None:
        """把知识块、索引元信息和可选向量写到本地。"""
        chunks_path.parent.mkdir(parents=True, exist_ok=True)
        with chunks_path.open("w", encoding="utf-8") as file:
            for chunk in chunks:
                file.write(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n")

        meta = {
            "mode": mode,
            "embedding_model": embedding_model,
            "chunk_count": len(chunks),
        }
        index_meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if vectors is not None:
            np.save(index_vector_path, vectors)

    def load(
        self,
        *,
        chunks_path: Path,
        index_meta_path: Path,
        index_vector_path: Path,
    ) -> tuple[list[KnowledgeChunk], dict, np.ndarray | None]:
        """从本地文件加载全部知识索引产物。"""
        chunks = [
            KnowledgeChunk(**json.loads(line))
            for line in chunks_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        meta = json.loads(index_meta_path.read_text(encoding="utf-8"))
        vectors = None
        if index_vector_path.exists():
            vectors = np.load(index_vector_path)
        return chunks, meta, vectors
