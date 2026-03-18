"""佣金订单索引 mapping 定义。"""

from __future__ import annotations


COMMISSION_ORDER_MAPPING = {
    "mappings": {
        "dynamic": False,
        "properties": {
            "commission_amount": {"type": "scaled_float", "scaling_factor": 100},
            "creator_id": {"type": "long"},
            "currency": {"type": "keyword"},
            "is_commission": {"type": "integer"},
            "no_commission_type": {"type": "integer"},
            "media_id": {"type": "long"},
            "order_complete_time": {"type": "date", "format": "epoch_second"},
            "order_confirm_time": {"type": "date", "format": "epoch_second"},
            "transfer_time": {"type": "date", "format": "epoch_second"},
            "transfer_type": {"type": "integer"},
            "no_transfer_reason": {"type": "integer"},
            "region": {"type": "keyword"},
            "shop_order_id": {"type": "keyword"},
            "third_party_order_id": {"type": "keyword"},
            "source_type": {"type": "integer"},
            "source_id": {"type": "keyword"},
            "merchant_id": {"type": "keyword"},
        },
    }
}
