"""验证 Qdrant backend 本身是否可用。"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np

from app.application.knowledge.qdrant_store import QdrantKnowledgeStore
from app.config.settings import get_settings
from app.domain.knowledge_models import KnowledgeChunk


def main() -> None:
    settings = get_settings()
    if not settings.qdrant_path:
        raise SystemExit("Set QDRANT_PATH first so validation runs against embedded Qdrant.")
    qdrant_path = settings.project_root / settings.qdrant_path if not settings.qdrant_path.startswith("/") else None
    storage_path = qdrant_path if qdrant_path is not None else settings.qdrant_path
    storage_path = Path(storage_path)
    if storage_path.exists():
        shutil.rmtree(storage_path)

    store = QdrantKnowledgeStore(settings)
    if not store.available:
        raise SystemExit("Qdrant store is not available. Check qdrant-client install and config.")

    chunks = [
        KnowledgeChunk(
            chunk_id="chunk-cps",
            source_file="knowledge/rag_knowledge.md",
            heading_path=["3.1 CPS"],
            text="CPS 是按成交结果结算的分佣模式。",
            keywords=["cps", "成交", "分佣"],
        ),
        KnowledgeChunk(
            chunk_id="chunk-cpt",
            source_file="knowledge/rag_knowledge.md",
            heading_path=["3.2 CPT"],
            text="CPT 是按任务履约和内容要求结算的固定合作模式。",
            keywords=["cpt", "任务", "固定结算"],
        ),
        KnowledgeChunk(
            chunk_id="chunk-transfer",
            source_file="knowledge/rag_knowledge.md",
            heading_path=["5.1 T+2"],
            text="T+2 表示订单核销后通常两个自然日到账。",
            keywords=["t+2", "到账"],
        ),
    ]
    vectors = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    store.upsert_chunks(chunks, vectors)

    cps_hits = store.search(query_vector=np.array([0.98, 0.01, 0.0], dtype=np.float32), top_k=2)
    transfer_hits = store.search(query_vector=np.array([0.01, 0.05, 0.99], dtype=np.float32), top_k=2)

    print("Qdrant backend validation completed.")
    print(f"collection: {store.collection_name}")
    print(f"qdrant_path: {storage_path}")
    print(f"cps_top_hit: {cps_hits[0].chunk_id if cps_hits else 'none'}")
    print(f"transfer_top_hit: {transfer_hits[0].chunk_id if transfer_hits else 'none'}")
    if not cps_hits or cps_hits[0].chunk_id != "chunk-cps":
        raise SystemExit("Unexpected CPS retrieval result.")
    if not transfer_hits or transfer_hits[0].chunk_id != "chunk-transfer":
        raise SystemExit("Unexpected transfer retrieval result.")


if __name__ == "__main__":
    main()
