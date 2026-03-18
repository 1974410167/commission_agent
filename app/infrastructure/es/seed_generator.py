"""Mock 数据生成器。

目标不是随便造数据，而是尽量满足真实业务约束：
- 可分佣 / 不可分佣逻辑一致；
- 到账状态与时间字段一致；
- 各类枚举值都有覆盖；
- 同一个 creator 下有多个 media；
- 同一个 media 下有多笔订单。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.enums import (
    IsCommission,
    NoCommissionType,
    NoTransferReason,
    SourceType,
    TransferType,
)
from app.domain.models import CommissionOrder


REGION_TO_CURRENCIES = {
    "US": "USD",
    "SG": "SGD",
    "GB": "GBP",
    "JP": "JPY",
}


@dataclass(frozen=True)
class MediaProfile:
    """媒体级固定属性。"""

    creator_id: int
    media_id: int
    merchant_id: str
    region: str
    currency: str


class MockCommissionOrderGenerator:
    """生成覆盖完整、业务一致的 mock 分佣订单。"""

    def __init__(self, seed: int = 20260308) -> None:
        self.random = random.Random(seed)
        self.creator_ids = [88_000 + index for index in range(1, 21)]
        self.media_profiles = self._build_media_profiles()
        self.order_sequence = 1

    def _build_media_profiles(self) -> list[MediaProfile]:
        """先构造稳定的 creator -> media 拓扑。"""
        profiles: list[MediaProfile] = []
        media_id = 990_000
        for creator_id in self.creator_ids:
            media_count = 5
            for slot in range(media_count):
                region = self.random.choice(list(REGION_TO_CURRENCIES.keys()))
                profiles.append(
                    MediaProfile(
                        creator_id=creator_id,
                        media_id=media_id,
                        merchant_id=f"MERCHANT-{creator_id % 100:02d}-{slot + 1:02d}",
                        region=region,
                        currency=REGION_TO_CURRENCIES[region],
                    )
                )
                media_id += 1
        return profiles

    def generate(self, count: int) -> list[CommissionOrder]:
        """先保证覆盖样本，再补齐随机样本。"""
        if count < 32:
            raise ValueError("count must be >= 32 so all enum values can be covered")

        orders: list[CommissionOrder] = []
        orders.extend(self._build_coverage_orders())
        while len(orders) < count:
            orders.append(self._build_random_order())
        return orders[:count]

    def _build_coverage_orders(self) -> list[CommissionOrder]:
        """强制让所有关键枚举值至少出现一次。"""
        orders: list[CommissionOrder] = []
        source_types = list(SourceType)
        media_cycle = iter(self.media_profiles)

        for index, no_commission_type in enumerate(NoCommissionType, start=1):
            media = next(media_cycle)
            orders.append(
                self._build_order(
                    media=media,
                    is_commission=IsCommission.NOT_COMMISSIONABLE,
                    source_type=source_types[index % len(source_types)],
                    transfer_type=TransferType.NOT_TRANSFERABLE,
                    no_commission_type=no_commission_type,
                    no_transfer_reason=list(NoTransferReason)[(index - 1) % len(NoTransferReason)],
                )
            )

        for index, no_transfer_reason in enumerate(NoTransferReason, start=1):
            media = next(media_cycle)
            orders.append(
                self._build_order(
                    media=media,
                    is_commission=IsCommission.NOT_COMMISSIONABLE,
                    source_type=source_types[(index + 1) % len(source_types)],
                    transfer_type=TransferType.NOT_TRANSFERABLE,
                    no_commission_type=list(NoCommissionType)[(index + 1) % len(NoCommissionType)],
                    no_transfer_reason=no_transfer_reason,
                )
            )

        for source_type in SourceType:
            media = next(media_cycle)
            orders.append(
                self._build_order(
                    media=media,
                    is_commission=IsCommission.COMMISSIONABLE,
                    source_type=source_type,
                    transfer_type=TransferType.IN_TRANSIT,
                )
            )
            media = next(media_cycle)
            orders.append(
                self._build_order(
                    media=media,
                    is_commission=IsCommission.COMMISSIONABLE,
                    source_type=source_type,
                    transfer_type=TransferType.ARRIVED,
                )
            )

        return orders

    def _build_random_order(self) -> CommissionOrder:
        """按概率生成更像真实业务分布的订单。"""
        media = self.random.choice(self.media_profiles)
        source_type = self.random.choices(
            population=list(SourceType),
            weights=[0.45, 0.35, 0.20],
            k=1,
        )[0]

        if source_type == SourceType.CPT:
            is_commission = self.random.choices(
                population=[IsCommission.COMMISSIONABLE, IsCommission.NOT_COMMISSIONABLE],
                weights=[0.65, 0.35],
                k=1,
            )[0]
            transfer_type = (
                self.random.choices([TransferType.IN_TRANSIT, TransferType.ARRIVED], weights=[0.4, 0.6], k=1)[0]
                if is_commission == IsCommission.COMMISSIONABLE
                else TransferType.NOT_TRANSFERABLE
            )
        else:
            is_commission = self.random.choices(
                population=[IsCommission.COMMISSIONABLE, IsCommission.NOT_COMMISSIONABLE],
                weights=[0.72, 0.28],
                k=1,
            )[0]
            if is_commission == IsCommission.COMMISSIONABLE:
                transfer_type = self.random.choices(
                    population=[TransferType.IN_TRANSIT, TransferType.ARRIVED, TransferType.NOT_TRANSFERABLE],
                    weights=[0.28, 0.62, 0.10],
                    k=1,
                )[0]
            else:
                transfer_type = self.random.choices(
                    population=[TransferType.NOT_TRANSFERABLE, TransferType.IN_TRANSIT],
                    weights=[0.88, 0.12],
                    k=1,
                )[0]

        no_commission_type = None
        if is_commission == IsCommission.NOT_COMMISSIONABLE:
            no_commission_type = self.random.choice(list(NoCommissionType))

        no_transfer_reason = None
        if transfer_type == TransferType.NOT_TRANSFERABLE:
            no_transfer_reason = self.random.choice(list(NoTransferReason))

        return self._build_order(
            media=media,
            is_commission=is_commission,
            source_type=source_type,
            transfer_type=transfer_type,
            no_commission_type=no_commission_type,
            no_transfer_reason=no_transfer_reason,
        )

    def _build_order(
        self,
        media: MediaProfile,
        is_commission: IsCommission,
        source_type: SourceType,
        transfer_type: TransferType,
        no_commission_type: NoCommissionType | None = None,
        no_transfer_reason: NoTransferReason | None = None,
    ) -> CommissionOrder:
        """拼装一笔订单，并在返回前做业务约束校验。"""
        confirm_dt = self._random_confirm_datetime()
        complete_dt = None
        transfer_dt = None

        # 在路上/已到账的订单，一定先发生过核销完成。
        if transfer_type in {TransferType.IN_TRANSIT, TransferType.ARRIVED}:
            complete_dt = confirm_dt + timedelta(days=self.random.randint(1, 10), hours=self.random.randint(1, 18))

        # 已到账订单，到账时间必须晚于核销时间。
        if transfer_type == TransferType.ARRIVED and complete_dt is not None:
            transfer_dt = complete_dt + timedelta(days=self.random.randint(2, 5), hours=self.random.randint(0, 6))

        # 有些“不可转账”订单并不代表没核销，只是后续打款条件不满足。
        # 这样生成的数据更适合展示复杂真实场景。
        if transfer_type == TransferType.NOT_TRANSFERABLE and no_transfer_reason not in {
            NoTransferReason.ORDER_NOT_COMPLETED,
            NoTransferReason.ORDER_CLOSED,
        }:
            complete_dt = confirm_dt + timedelta(days=self.random.randint(1, 6), hours=self.random.randint(2, 12))

        commission_amount = 0.0
        if is_commission == IsCommission.COMMISSIONABLE:
            base_amount = self.random.uniform(5, 800)
            if source_type == SourceType.CPT:
                base_amount = self.random.uniform(20, 300)
            commission_amount = round(base_amount, 2)

        order_number = self.order_sequence
        self.order_sequence += 1
        order = CommissionOrder(
            commission_amount=commission_amount,
            creator_id=media.creator_id,
            currency=media.currency,
            is_commission=int(is_commission),
            no_commission_type=int(no_commission_type) if no_commission_type is not None else None,
            media_id=media.media_id,
            order_complete_time=self._to_epoch(complete_dt),
            order_confirm_time=self._to_epoch(confirm_dt),
            transfer_time=self._to_epoch(transfer_dt),
            transfer_type=int(transfer_type),
            no_transfer_reason=int(no_transfer_reason) if no_transfer_reason is not None else None,
            region=media.region,
            shop_order_id=f"SO-{confirm_dt:%Y%m%d}-{order_number:06d}",
            third_party_order_id=f"TP-{int(source_type)}-{order_number:08d}",
            source_type=int(source_type),
            source_id=f"SRC-{int(source_type)}-{media.media_id}-{order_number:06d}",
            merchant_id=media.merchant_id,
        )
        order.validate()
        return order

    def _random_confirm_datetime(self) -> datetime:
        """把订单确认时间打散到最近 120 天窗口中。"""
        now = datetime.now(timezone.utc)
        day_offset = self.random.randint(0, 119)
        minute_offset = self.random.randint(0, 23 * 60 + 59)
        return now - timedelta(days=day_offset, minutes=minute_offset)

    @staticmethod
    def _to_epoch(value: datetime | None) -> int | None:
        """把 datetime 转成 ES mapping 需要的 epoch_second。"""
        return int(value.timestamp()) if value is not None else None
