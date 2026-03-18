"""佣金订单核心数据结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.domain.enums import IsCommission, TransferType


@dataclass(frozen=True)
class CommissionOrder:
    """一笔佣金订单在 Python 内存中的表示。"""

    commission_amount: float
    creator_id: int
    currency: str
    is_commission: int
    no_commission_type: int | None
    media_id: int
    order_complete_time: int | None
    order_confirm_time: int
    transfer_time: int | None
    transfer_type: int
    no_transfer_reason: int | None
    region: str
    shop_order_id: str
    third_party_order_id: str
    source_type: int
    source_id: str
    merchant_id: str

    def validate(self) -> None:
        """校验订单是否满足业务一致性约束。"""
        if self.is_commission == IsCommission.COMMISSIONABLE:
            if self.no_commission_type is not None:
                raise ValueError("no_commission_type must be empty when order is commissionable")
            if self.commission_amount < 0:
                raise ValueError("commission_amount must be >= 0")
        if self.is_commission == IsCommission.NOT_COMMISSIONABLE and self.no_commission_type is None:
            raise ValueError("no_commission_type is required when order is not commissionable")

        if self.transfer_type == TransferType.ARRIVED:
            if self.transfer_time is None or self.order_complete_time is None:
                raise ValueError("arrived orders require transfer_time and order_complete_time")
            if self.transfer_time < self.order_complete_time:
                raise ValueError("transfer_time must be >= order_complete_time")

        if self.transfer_type == TransferType.IN_TRANSIT and self.order_complete_time is None:
            raise ValueError("in-transit orders require order_complete_time")

        if self.transfer_type == TransferType.NOT_TRANSFERABLE:
            if self.no_transfer_reason is None:
                raise ValueError("not-transferable orders require no_transfer_reason")
            if self.transfer_time is not None:
                raise ValueError("not-transferable orders must not have transfer_time")

    def to_document(self) -> dict[str, Any]:
        """输出可直接写入 ES 的文档结构。"""
        self.validate()
        return asdict(self)
