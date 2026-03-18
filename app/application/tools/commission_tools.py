"""分佣查询工具层。

这一层的职责很简单：
- 吃 `NormalizedFilters`；
- 调 repository；
- 返回强类型结果。

这样 workflow 节点就不用知道 ES DSL 细节。
"""

from __future__ import annotations

from app.config.settings import get_settings
from app.domain.intent_models import (
    CreatorSummaryResult,
    MediaCommissionStatusResult,
    MediaCommissionSummaryResult,
    MediaNoCommissionBreakdownResult,
    NormalizedFilters,
    OrderTransferStatusResult,
    SourceTypeComparisonResult,
)
from app.infrastructure.es.client import create_es_client
from app.infrastructure.es.repository import CommissionOrderRepository


class CommissionTools:
    """workflow 使用的分佣工具门面。"""

    def __init__(self) -> None:
        settings = get_settings()
        client = create_es_client(settings)
        self.repository = CommissionOrderRepository(client=client, index_name=settings.es_index)

    def get_creator_commission_summary(self, filters: NormalizedFilters) -> CreatorSummaryResult:
        """查询达人维度分佣汇总。"""
        data = self.repository.get_creator_commission_summary_with_filters(filters.to_query_filters())
        return CreatorSummaryResult(**data)

    def get_media_no_commission_breakdown(self, filters: NormalizedFilters) -> MediaNoCommissionBreakdownResult:
        """查询某个视频的不可分佣原因分布。"""
        data = self.repository.get_media_no_commission_breakdown(filters.to_query_filters())
        return MediaNoCommissionBreakdownResult(**data)

    def get_media_commission_status(self, filters: NormalizedFilters) -> MediaCommissionStatusResult:
        """查询某个视频整体是否可分佣，以及可/不可分佣订单分布。"""
        data = self.repository.get_media_commission_status(filters.to_query_filters())
        return MediaCommissionStatusResult(**data)

    def get_order_transfer_status(self, filters: NormalizedFilters) -> OrderTransferStatusResult | None:
        """查询某笔订单的到账状态。"""
        data = self.repository.get_order_transfer_status_with_filters(filters.to_query_filters())
        return OrderTransferStatusResult(**data) if data else None

    def summarize_commission_by_media(self, filters: NormalizedFilters) -> MediaCommissionSummaryResult:
        """按视频维度展开达人查询结果。"""
        data = self.repository.summarize_commission_by_media(filters.to_query_filters())
        return MediaCommissionSummaryResult(**data)

    def compare_source_type_commission(self, filters: NormalizedFilters) -> SourceTypeComparisonResult:
        """对比同一达人在多个 source_type 下的分佣表现。"""
        data = self.repository.compare_source_type_commission(filters.to_query_filters())
        return SourceTypeComparisonResult(**data)
