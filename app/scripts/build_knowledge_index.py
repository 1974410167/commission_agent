"""构建本地 markdown 知识索引的脚本。"""

from __future__ import annotations

from app.application.knowledge.service import KnowledgeService


def main() -> None:
    """生成 chunks、meta 和可选向量文件。"""
    service = KnowledgeService()
    result = service.build_index()
    print("Knowledge index build completed.")
    print(f"source_file: {result.source_file}")
    print(f"chunk_count: {result.chunk_count}")
    print(f"index_mode: {result.index_mode}")
    print(f"embedding_model: {result.embedding_model}")
    print(f"knowledge_backend: {service.settings.knowledge_backend}")


if __name__ == "__main__":
    main()
