"""知识 markdown 兜底加载器。"""

from __future__ import annotations

from pathlib import Path

from app.config.settings import Settings, get_settings


DEFAULT_KNOWLEDGE_APPENDIX = """

# 分佣规则补充

## T+2 到账规则
订单完成核销后，进入结算链路。当前分佣数据层里默认按照 T+2 理解预计到账时间：

- `order_complete_time` 表示订单核销时间
- `transfer_time` 表示实际到账时间
- 当 `transfer_type=2` 时表示“在路上”，通常可按 `order_complete_time + 2 天` 理解预计到账
- 当 `transfer_type=3` 时表示“已到账”，以实际 `transfer_time` 为准

## 不可分佣原因说明

### NO_PRODUCT_COMMISSION
`no_commission_type=1`。商品在投稿和用户下单时都不处于推广状态，因此订单无法进入分佣链路。

### NOT_ALLIANCE_CREATOR
`no_commission_type=2`。达人不是联盟达人，或尚未满足参与分佣的资格。

### FULFILMENT_TASK_INVALID_STATUS
`no_commission_type=3`。履约任务状态异常、无效或已经取消，导致订单不能分佣。

### CREATOR_PACKAGE_TASK_NOT_CPS_TASK
`no_commission_type=4`。达人包任务不是 CPS/CPX 类型，订单不应走 CPS 分佣逻辑。

### COMMISSION_RATE_ZERO
`no_commission_type=5`。商品或任务的分佣比例为 0，因此虽然有带货行为，但最终不产生佣金。

### NO_EXIST_SHOP_FROM_ORDER_POI
`no_commission_type=6`。系统无法根据订单 POI 找到店铺信息，无法完成店铺与任务的归因。

## 转账状态说明

### transfer_type = 1 不可转账
表示当前订单还不满足打款条件，通常需要结合 `no_transfer_reason` 一起理解原因。

### transfer_type = 2 在路上
表示订单已经满足结算前提，处于待打款或打款处理中，常按 T+2 预计到账。

### transfer_type = 3 已到账
表示佣金已完成打款，以 `transfer_time` 为准。

## 不可转账原因说明

### 订单不可归因
`no_transfer_reason=1`。订单和达人/任务/商品之间没有形成有效归因关系，因此无法转账。

### 订单未完成
`no_transfer_reason=2`。订单尚未完成核销，结算链路还未开始。

### 订单已关闭
`no_transfer_reason=3`。订单关闭后不再继续结算。

### KYC未开户
`no_transfer_reason=4`。收款主体未完成 KYC 开户，平台不能执行打款。

### PIPO未开户
`no_transfer_reason=5`。PIPO 收款账户未开通，导致打款链路中断。
"""


def ensure_knowledge_markdown(settings: Settings | None = None) -> Path:
    """确保项目内始终有一份可运行的 markdown 知识源。"""
    current = settings or get_settings()
    current.knowledge_dir.mkdir(parents=True, exist_ok=True)

    if current.knowledge_markdown_path.exists():
        return current.knowledge_markdown_path

    root_markdown = current.project_root / "rag_knowledge.md"
    base_text = ""
    if root_markdown.exists():
        base_text = root_markdown.read_text(encoding="utf-8").strip()
    else:
        base_text = "# 分佣知识库\n\n当前知识库由项目自动生成，用于解释分佣概念、状态和规则。"

    merged = base_text + DEFAULT_KNOWLEDGE_APPENDIX
    current.knowledge_markdown_path.write_text(merged.strip() + "\n", encoding="utf-8")
    return current.knowledge_markdown_path
