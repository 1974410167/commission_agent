"""初始化 ES 索引的脚本。"""

from __future__ import annotations

import argparse

from app.config.settings import get_settings
from app.infrastructure.es.client import create_es_client
from app.infrastructure.es.mappings import COMMISSION_ORDER_MAPPING


def main() -> None:
    """按项目约定 mapping 创建索引。"""
    parser = argparse.ArgumentParser(description="Initialize Elasticsearch index for commission orders.")
    parser.add_argument("--recreate", action="store_true", help="Delete the index first if it already exists.")
    args = parser.parse_args()

    settings = get_settings()
    client = create_es_client(settings)

    if args.recreate and client.indices.exists(index=settings.es_index):
        client.indices.delete(index=settings.es_index)
        print(f"Deleted existing index: {settings.es_index}")

    if client.indices.exists(index=settings.es_index):
        print(f"Index already exists: {settings.es_index}")
        return

    client.indices.create(index=settings.es_index, **COMMISSION_ORDER_MAPPING)
    print(f"Created index: {settings.es_index}")


if __name__ == "__main__":
    main()
