"""业务枚举及其中英文标签映射。"""

from __future__ import annotations

from enum import IntEnum


class IsCommission(IntEnum):
    """订单是否可分佣。"""

    COMMISSIONABLE = 1
    NOT_COMMISSIONABLE = 2


class SourceType(IntEnum):
    """分佣来源类型。"""

    CLOSED_LOOP_CPS = 1
    OPEN_LOOP_CPS = 2
    CPT = 3


class NoCommissionType(IntEnum):
    """不可分佣原因。"""

    NO_PRODUCT_COMMISSION = 1
    NOT_ALLIANCE_CREATOR = 2
    FULFILMENT_TASK_INVALID_STATUS = 3
    CREATOR_PACKAGE_TASK_NOT_CPS_TASK = 4
    COMMISSION_RATE_ZERO = 5
    NO_EXIST_SHOP_FROM_ORDER_POI = 6


class TransferType(IntEnum):
    """结算转账状态。"""

    NOT_TRANSFERABLE = 1
    IN_TRANSIT = 2
    ARRIVED = 3


class NoTransferReason(IntEnum):
    """不可转账原因。"""

    ORDER_NOT_ATTRIBUTABLE = 1
    ORDER_NOT_COMPLETED = 2
    ORDER_CLOSED = 3
    KYC_NOT_OPENED = 4
    PIPO_NOT_OPENED = 5


IS_COMMISSION_LABELS = {
    IsCommission.COMMISSIONABLE: {"code": "COMMISSIONABLE", "zh_cn": "可分佣"},
    IsCommission.NOT_COMMISSIONABLE: {"code": "NOT_COMMISSIONABLE", "zh_cn": "不可分佣"},
}

SOURCE_TYPE_LABELS = {
    SourceType.CLOSED_LOOP_CPS: {"code": "CLOSED_LOOP_CPS", "zh_cn": "闭环CPS"},
    SourceType.OPEN_LOOP_CPS: {"code": "OPEN_LOOP_CPS", "zh_cn": "开环CPS"},
    SourceType.CPT: {"code": "CPT", "zh_cn": "CPT"},
}

NO_COMMISSION_TYPE_LABELS = {
    NoCommissionType.NO_PRODUCT_COMMISSION: {
        "code": "NO_PRODUCT_COMMISSION",
        "zh_cn": "商品在投稿/下单时都不处于推广状态",
    },
    NoCommissionType.NOT_ALLIANCE_CREATOR: {
        "code": "NOT_ALLIANCE_CREATOR",
        "zh_cn": "非联盟达人/未成为可参与分佣的达人",
    },
    NoCommissionType.FULFILMENT_TASK_INVALID_STATUS: {
        "code": "FULFILMENT_TASK_INVALID_STATUS",
        "zh_cn": "履约任务状态无效或已取消",
    },
    NoCommissionType.CREATOR_PACKAGE_TASK_NOT_CPS_TASK: {
        "code": "CREATOR_PACKAGE_TASK_NOT_CPS_TASK",
        "zh_cn": "达人包任务不是 CPS/CPX 任务",
    },
    NoCommissionType.COMMISSION_RATE_ZERO: {
        "code": "COMMISSION_RATE_ZERO",
        "zh_cn": "分佣比例为 0",
    },
    NoCommissionType.NO_EXIST_SHOP_FROM_ORDER_POI: {
        "code": "NO_EXIST_SHOP_FROM_ORDER_POI",
        "zh_cn": "无法通过订单 POI 找到店铺",
    },
}

TRANSFER_TYPE_LABELS = {
    TransferType.NOT_TRANSFERABLE: {"code": "NOT_TRANSFERABLE", "zh_cn": "不可转账"},
    TransferType.IN_TRANSIT: {"code": "IN_TRANSIT", "zh_cn": "在路上"},
    TransferType.ARRIVED: {"code": "ARRIVED", "zh_cn": "已到账"},
}

NO_TRANSFER_REASON_LABELS = {
    NoTransferReason.ORDER_NOT_ATTRIBUTABLE: {
        "code": "ORDER_NOT_ATTRIBUTABLE",
        "zh_cn": "订单不可归因",
    },
    NoTransferReason.ORDER_NOT_COMPLETED: {
        "code": "ORDER_NOT_COMPLETED",
        "zh_cn": "订单未完成",
    },
    NoTransferReason.ORDER_CLOSED: {
        "code": "ORDER_CLOSED",
        "zh_cn": "订单已关闭",
    },
    NoTransferReason.KYC_NOT_OPENED: {
        "code": "KYC_NOT_OPENED",
        "zh_cn": "KYC未开户",
    },
    NoTransferReason.PIPO_NOT_OPENED: {
        "code": "PIPO_NOT_OPENED",
        "zh_cn": "PIPO未开户",
    },
}


ENUM_ZH_MAPPINGS = {
    "is_commission": {int(key): value for key, value in IS_COMMISSION_LABELS.items()},
    "source_type": {int(key): value for key, value in SOURCE_TYPE_LABELS.items()},
    "no_commission_type": {int(key): value for key, value in NO_COMMISSION_TYPE_LABELS.items()},
    "transfer_type": {int(key): value for key, value in TRANSFER_TYPE_LABELS.items()},
    "no_transfer_reason": {int(key): value for key, value in NO_TRANSFER_REASON_LABELS.items()},
}
