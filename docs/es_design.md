# Elasticsearch 数据层设计

## 目标

第一阶段只实现 `commission_orders_v1` 的 Elasticsearch 数据层，为后续 Agent 查询、LangGraph 编排和前端展示提供稳定数据接口。

## 索引说明

- 索引名：`commission_orders_v1`
- `dynamic` 在实际 API 中使用 JSON 布尔值 `false`，与需求里的 `"false"` 语义一致。

## 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `commission_amount` | `scaled_float` | 佣金金额，按 2 位精度存储 |
| `creator_id` | `long` | 达人 ID |
| `currency` | `keyword` | 币种 |
| `is_commission` | `integer` | 是否可分佣 |
| `no_commission_type` | `integer` | 不可分佣原因 |
| `media_id` | `long` | 视频/内容 ID |
| `order_complete_time` | `date(epoch_second)` | 订单核销时间 |
| `order_confirm_time` | `date(epoch_second)` | 用户下单时间 / 订单确认时间 |
| `transfer_time` | `date(epoch_second)` | 实际到账时间，仅已到账订单有值 |
| `transfer_type` | `integer` | 到账状态 |
| `no_transfer_reason` | `integer` | 不可转账原因 |
| `region` | `keyword` | 区域/国家 |
| `shop_order_id` | `keyword` | 平台订单号 |
| `third_party_order_id` | `keyword` | 第三方订单号 |
| `source_type` | `integer` | 业务来源类型 |
| `source_id` | `keyword` | 来源链路 ID |
| `merchant_id` | `keyword` | 商家 ID |

## 枚举设计

### is_commission

- `1 / COMMISSIONABLE / 可分佣`
- `2 / NOT_COMMISSIONABLE / 不可分佣`

### source_type

- `1 / CLOSED_LOOP_CPS / 闭环CPS`
- `2 / OPEN_LOOP_CPS / 开环CPS`
- `3 / CPT / CPT`

### no_commission_type

- `1 / NO_PRODUCT_COMMISSION / 商品在投稿/下单时都不处于推广状态`
- `2 / NOT_ALLIANCE_CREATOR / 非联盟达人/未成为可参与分佣的达人`
- `3 / FULFILMENT_TASK_INVALID_STATUS / 履约任务状态无效或已取消`
- `4 / CREATOR_PACKAGE_TASK_NOT_CPS_TASK / 达人包任务不是 CPS/CPX 任务`
- `5 / COMMISSION_RATE_ZERO / 分佣比例为 0`
- `6 / NO_EXIST_SHOP_FROM_ORDER_POI / 无法通过订单 POI 找到店铺`

### transfer_type

- `1 / NOT_TRANSFERABLE / 不可转账`
- `2 / IN_TRANSIT / 在路上`
- `3 / ARRIVED / 已到账`

### no_transfer_reason

- `1 / ORDER_NOT_ATTRIBUTABLE / 订单不可归因`
- `2 / ORDER_NOT_COMPLETED / 订单未完成`
- `3 / ORDER_CLOSED / 订单已关闭`
- `4 / KYC_NOT_OPENED / KYC未开户`
- `5 / PIPO_NOT_OPENED / PIPO未开户`

## 业务规则

- `order_confirm_time` 表示用户下单时间，也是订单确认时间。
- `order_complete_time` 表示核销时间。
- 结算链路按 `T+2` 设计。
- `transfer_time` 仅保存实际到账时间。
- 对于 `transfer_type=2` 的订单，预计到账时间可通过 `order_complete_time + 2 天` 推导，当前阶段仅在查询层或文档层说明，不单独入 ES。
- `is_commission=1` 时，`no_commission_type` 必须为空。
- `is_commission=2` 时，`no_commission_type` 必填。
- `transfer_type=3` 时，`transfer_time` 与 `order_complete_time` 必填，且 `transfer_time >= order_complete_time`。
- `transfer_type=2` 时，`order_complete_time` 必填，`transfer_time` 为空。
- `transfer_type=1` 时，`no_transfer_reason` 必填，`transfer_time` 为空。

## Mock 数据设计

- 20 个达人，100 个媒体内容。
- 默认生成 3000 笔订单，时间分布在最近 120 天。
- 覆盖全部枚举值。
- 同一达人下有多个媒体，同一媒体下有多笔订单。
- 区域覆盖 `US`、`SG`、`GB`、`JP`，币种覆盖 `USD`、`SGD`、`GBP`、`JPY`。
- CPT 场景按简化链路生成：不可分佣通常不可转账，可分佣通常为在路上或已到账。

## 查询能力

`CommissionOrderRepository` 当前提供：

- 达人最近 N 天分佣摘要查询
- 媒体不可分佣原因分布查询
- 单笔订单到账状态查询
- 同一达人不同 source_type 对比查询
- 校验脚本所需的样本筛选方法
