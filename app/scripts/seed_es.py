"""生成并写入 mock 分佣订单数据的脚本。"""

from __future__ import annotations

import argparse

from elasticsearch.helpers import bulk

from app.config.settings import get_settings
from app.infrastructure.es.client import create_es_client
from app.infrastructure.es.seed_generator import MockCommissionOrderGenerator


def main() -> None:
    """生成业务一致的 mock 数据，并 bulk 写入 ES。"""
    parser = argparse.ArgumentParser(description="Generate and bulk load mock commission order data.")
    parser.add_argument("--count", type=int, default=3000, help="Number of mock orders to generate.")
    args = parser.parse_args()

    settings = get_settings()
    client = create_es_client(settings)
    generator = MockCommissionOrderGenerator(seed=settings.seed)
    orders = generator.generate(args.count)
    actions = [
        {
            "_index": settings.es_index,
            "_id": order.shop_order_id,
            "_source": order.to_document(),
        }
        for order in orders
    ]
    success, _ = bulk(client, actions=actions, refresh="wait_for")
    print(f"Indexed documents: {success}")


if __name__ == "__main__":
    main()
