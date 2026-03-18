"""第一阶段 ES 校验脚本。"""

from __future__ import annotations

import json

from app.config.settings import get_settings
from app.infrastructure.es.client import create_es_client
from app.infrastructure.es.repository import CommissionOrderRepository


def _print_block(title: str, payload: dict) -> None:
    """格式化打印一段校验结果。"""
    print(f"=== {title} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    """跑四类基础查询，确保索引和数据可用。"""
    settings = get_settings()
    client = create_es_client(settings)
    repository = CommissionOrderRepository(client, settings.es_index)

    total_docs = repository.count_all()
    if total_docs <= 0:
        raise RuntimeError("index is empty, seed data before validation")

    creator_id = repository.find_recent_creator_id(days=30)
    if creator_id is None:
        raise RuntimeError("could not find a creator with recent orders")
    creator_summary = repository.get_creator_commission_summary(creator_id=creator_id, days=30)
    if creator_summary["order_count"] <= 0:
        raise RuntimeError("creator summary returned no orders")
    _print_block("Query 1: Creator recent 30-day commission summary", creator_summary)

    media_id = repository.find_media_id_with_non_commission()
    if media_id is None:
        raise RuntimeError("could not find a media id with non-commission orders")
    media_summary = repository.get_media_no_commission_distribution(media_id=media_id)
    if media_summary["non_commissionable_order_count"] <= 0:
        raise RuntimeError("media summary returned no non-commission orders")
    _print_block("Query 2: Media non-commission reason distribution", media_summary)

    shop_order_id = repository.find_latest_shop_order_id()
    if shop_order_id is None:
        raise RuntimeError("could not find a shop order id")
    order_status = repository.get_order_transfer_status(shop_order_id=shop_order_id)
    if order_status is None:
        raise RuntimeError("order status lookup returned no result")
    _print_block("Query 3: Order transfer status", order_status)

    comparison_target = repository.find_creator_with_multiple_source_types()
    if comparison_target is None:
        raise RuntimeError("could not find creator with at least two source types")
    comparison_creator_id, (source_type_a, source_type_b) = comparison_target
    comparison_summary = repository.compare_creator_source_types(
        creator_id=comparison_creator_id,
        source_type_a=source_type_a,
        source_type_b=source_type_b,
    )
    if len(comparison_summary["comparison"]) < 2:
        raise RuntimeError("comparison query did not return both source types")
    _print_block("Query 4: Creator comparison across two source types", comparison_summary)

    print(f"Validated {total_docs} indexed documents successfully.")


if __name__ == "__main__":
    main()
