"""意图、槽位、工具结果和最终响应模型。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.knowledge_models import EvidenceItem, RetrievedChunk
from app.domain.task_state_models import TaskType


class AgentIntent(str, Enum):
    """当前阶段支持的全部意图。"""

    QUERY_CREATOR_SUMMARY = "QUERY_CREATOR_SUMMARY"
    QUERY_MEDIA_COMMISSION_STATUS = "QUERY_MEDIA_COMMISSION_STATUS"
    QUERY_MEDIA_NO_COMMISSION_REASON = "QUERY_MEDIA_NO_COMMISSION_REASON"
    QUERY_ORDER_TRANSFER_STATUS = "QUERY_ORDER_TRANSFER_STATUS"
    EXPLAIN_BUSINESS_TERM = "EXPLAIN_BUSINESS_TERM"
    SUMMARIZE_BY_MEDIA = "SUMMARIZE_BY_MEDIA"
    COMPARE_SOURCE_TYPE = "COMPARE_SOURCE_TYPE"
    FOLLOW_UP_REFINE = "FOLLOW_UP_REFINE"
    UNKNOWN = "UNKNOWN"


class TurnType(str, Enum):
    """单轮用户输入的动作类型。

    这里描述的是“这句话在干嘛”，而不是“最终怎么路由工具”。
    例如：
    - `MODIFY_FILTERS` 说明用户只是在改条件
    - 但它并不意味着当前任务就从达人汇总切换成了别的任务
    """

    NEW_QUERY = "NEW_QUERY"
    MODIFY_FILTERS = "MODIFY_FILTERS"
    ANSWER_CLARIFY = "ANSWER_CLARIFY"
    EXPLAIN = "EXPLAIN"
    UNSUPPORTED = "UNSUPPORTED"


class EntityScope(str, Enum):
    """当前这句话涉及的业务主体。

    它回答的是“用户这句话主要在问谁”：
    - 达人
    - 视频
    - 订单
    - 术语/规则

    这是比 task_type 更底层的语义维度，适合由 LLM 先判断出来，
    再交给后端 resolver 映射成系统支持的任务类型。
    """

    CREATOR = "CREATOR"
    MEDIA = "MEDIA"
    ORDER = "ORDER"
    TERM = "TERM"
    UNKNOWN = "UNKNOWN"


class GoalType(str, Enum):
    """当前这句话想达成的目标。

    它回答的是“用户到底想知道什么”：
    - summary: 总览/汇总
    - status: 状态/是否可分佣/是否到账
    - reason: 原因/为什么不可分佣
    - compare: 对比
    - explain: 解释术语或规则
    """

    SUMMARY = "SUMMARY"
    STATUS = "STATUS"
    REASON = "REASON"
    COMPARE = "COMPARE"
    EXPLAIN = "EXPLAIN"
    UNKNOWN = "UNKNOWN"


class TimeScope(str, Enum):
    """时间范围语义。

    这层不是最终 ES DSL，而是用户时间表达的轻量语义抽象：
    - RECENT_7D
    - RECENT_30D
    - ALL_HISTORY

    这样可以避免把“最近7天/最近30天/历史上所有”都写成零散 case。
    """

    RECENT_7D = "RECENT_7D"
    RECENT_30D = "RECENT_30D"
    ALL_HISTORY = "ALL_HISTORY"


class CommissionQuerySlots(BaseModel):
    """NLU 抽取出来的原始槽位。

    这些值可能还不完整，也可能还没做统一格式处理，
    后续还要进入 normalize / validate 阶段。
    """

    creator_id: int | None = None
    media_id: int | None = None
    shop_order_id: str | None = None
    third_party_order_id: str | None = None
    source_type: int | list[int] | None = None
    is_commission: int | None = None
    no_commission_type: int | None = None
    transfer_type: int | None = None
    region: str | None = None
    time_scope: TimeScope | None = None
    time_field: Literal["order_confirm_time", "order_complete_time"] | None = None
    start_time: int | None = None
    end_time: int | None = None
    compare_source_types: list[int] | None = None
    group_by: Literal["media_id", "source_type", "none"] | None = None
    term: str | None = None


class QueryUnderstanding(BaseModel):
    """单次 LLM 理解结果。

    graph 现在只做一次 NLU chat 调用，但它不再直接承担“最终任务拍板”。

    LLM 主要输出三层语义：
    - turn_type: 这一轮在干什么
    - entity_scope: 这一轮主要在问谁
    - goal_type: 这一轮想知道什么

    然后再由后端 resolver 把：
    - entity_scope + goal_type
    映射成系统支持的 task_type。

    这样做的原因是：
    - 直接让 LLM 猜 task_type 太容易把相近任务混掉
    - 尤其是“视频是否可分佣” vs “视频为什么不可分佣”这类边界问题
    """

    turn_type: TurnType
    entity_scope: EntityScope | None = None
    goal_type: GoalType | None = None
    task_type: TaskType | None = None
    slots: CommissionQuerySlots = Field(default_factory=CommissionQuerySlots)
    confidence: float | None = None


class NormalizedFilters(BaseModel):
    """归一化后的过滤条件。

    这一层的目标是让下游 tool / repository 可以直接消费，
    不再关心“单值还是数组”“时间默认值是否补齐”之类的问题。
    """

    creator_id: int | None = None
    media_id: int | None = None
    shop_order_id: str | None = None
    third_party_order_id: str | None = None
    source_type: list[int] | None = None
    is_commission: int | None = None
    no_commission_type: int | None = None
    transfer_type: int | None = None
    region: str | None = None
    time_scope: TimeScope | None = None
    time_field: Literal["order_confirm_time", "order_complete_time"] | None = None
    start_time: int | None = None
    end_time: int | None = None
    compare_source_types: list[int] | None = None
    group_by: Literal["media_id", "source_type", "none"] = "none"
    term: str | None = None

    def to_query_filters(self) -> dict[str, Any]:
        """导出给 repository 使用的过滤字典，并清理空值。"""
        data = self.model_dump()
        if data["compare_source_types"]:
            data["source_type"] = data["compare_source_types"]
        return {key: value for key, value in data.items() if value not in (None, [], {}, "", "none")}


class ClarifyResponse(BaseModel):
    """缺参追问结果。"""

    missing_slots: list[str] = Field(default_factory=list)
    question: str


class CreatorSummaryResult(BaseModel):
    """达人汇总查询结果。"""

    creator_id: int | None = None
    total_orders: int
    commissionable_orders: int
    non_commissionable_orders: int
    total_commission_amount: float
    source_type_distribution: dict[str, int]
    no_commission_type_distribution: dict[str, int]


class MediaNoCommissionBreakdownResult(BaseModel):
    """视频不可分佣原因统计结果。"""

    media_id: int | None = None
    non_commissionable_orders: int
    no_commission_type_distribution: dict[str, int]


class MediaCommissionStatusResult(BaseModel):
    """视频维度分佣状态汇总结果。

    这个结果回答的是“视频是否可分佣 / 可分佣占比如何”，
    和“视频为什么不可分佣”不是同一类问题。
    """

    media_id: int | None = None
    total_orders: int
    commissionable_orders: int
    non_commissionable_orders: int
    total_commission_amount: float
    source_type_distribution: dict[str, int]
    no_commission_type_distribution: dict[str, int]


class OrderTransferStatusResult(BaseModel):
    """单笔订单到账状态结果。"""

    creator_id: int | None = None
    media_id: int | None = None
    shop_order_id: str
    third_party_order_id: str | None = None
    source_type: int
    is_commission: int
    transfer_type: int
    transfer_time: int | None = None
    no_transfer_reason: int | None = None
    order_complete_time: int | None = None
    commission_amount: float


class MediaSummaryItem(BaseModel):
    """按视频汇总时的一条聚合项。"""

    media_id: int
    total_orders: int
    commissionable_orders: int
    non_commissionable_orders: int
    total_commission_amount: float


class MediaCommissionSummaryResult(BaseModel):
    """按视频展开后的结果。"""

    creator_id: int | None = None
    items: list[MediaSummaryItem]


class SourceTypeComparisonItem(BaseModel):
    """source_type 对比结果中的一项。"""

    source_type: int
    total_orders: int
    commissionable_orders: int
    non_commissionable_orders: int
    total_commission_amount: float


class SourceTypeComparisonResult(BaseModel):
    """同一达人在多个 source_type 下的对比结果。"""

    creator_id: int | None = None
    compare_source_types: list[int] = Field(default_factory=list)
    items: list[SourceTypeComparisonItem]


class KnowledgeExplainResult(BaseModel):
    """知识层返回的解释结果。"""

    query: str
    answer: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    matched_chunks: list[RetrievedChunk] = Field(default_factory=list)
    mode: str = "static"


class ChatResponse(BaseModel):
    """对 API 和 Web Demo 统一暴露的最终响应结构。"""

    action: Literal["answer", "clarify"]
    answer: str
    normalized_filters: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    next_suggestions: list[str] = Field(default_factory=list)
    missing_slots: list[str] | None = None
    intent: str
    debug: dict[str, Any] | None = None
