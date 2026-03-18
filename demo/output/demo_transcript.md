# Demo Transcript

Generated at 2026-03-08 15:49:54 UTC

## summary
- role: `operator`
- conversation_id: `demo-summary-1`
- action: `answer`
- intent: `QUERY_CREATOR_SUMMARY`
- selected_tool: `get_creator_commission_summary`
- nlu_mode: `llm_based`
- query: 帮我查达人88016最近30天分佣情况

### Answer
查询范围为 2026-02-06 ~ 2026-03-08。达人 88016 共有 178 笔订单，可分佣 142 笔，不可分佣 36 笔，总佣金 52592.30。主要来源分布为 闭环CPS 76 笔，开环CPS 62 笔，CPT 40 笔。

### Evidence
- `es_fact` 达人分佣汇总 | commission_orders_v1 | 达人 88016，2026-02-06 ~ 2026-03-08，总订单 178，总佣金 52592.30。
- `es_fact` 来源类型分布 | commission_orders_v1 | 闭环CPS 76 笔，开环CPS 62 笔，CPT 40 笔
- `es_fact` 不可分佣原因分布 | commission_orders_v1 | 非联盟达人/未成为可参与分佣的达人 7 笔，达人包任务不是 CPS/CPX 任务 7 笔，分佣比例为 0 7 笔，无法通过订单 POI 找到店铺 6 笔，履约任务状态无效或已取消 5 笔，商品在投稿/下单时都不处于推广状态 4 笔

## follow_up
- role: `operator`
- conversation_id: `demo-summary-1`
- action: `answer`
- intent: `QUERY_CREATOR_SUMMARY`
- selected_tool: `get_creator_commission_summary`
- nlu_mode: `llm_based`
- query: 只看不可分佣订单

### Answer
查询范围为 2026-02-06 ~ 2026-03-08。达人 88016 共有 36 笔订单，可分佣 0 笔，不可分佣 36 笔，总佣金 0.00。主要来源分布为 开环CPS 15 笔，闭环CPS 11 笔，CPT 10 笔。

### Evidence
- `es_fact` 达人分佣汇总 | commission_orders_v1 | 达人 88016，2026-02-06 ~ 2026-03-08，总订单 36，总佣金 0.00。
- `es_fact` 来源类型分布 | commission_orders_v1 | 开环CPS 15 笔，闭环CPS 11 笔，CPT 10 笔
- `es_fact` 不可分佣原因分布 | commission_orders_v1 | 非联盟达人/未成为可参与分佣的达人 7 笔，达人包任务不是 CPS/CPX 任务 7 笔，分佣比例为 0 7 笔，无法通过订单 POI 找到店铺 6 笔，履约任务状态无效或已取消 5 笔，商品在投稿/下单时都不处于推广状态 4 笔

## follow_up
- role: `operator`
- conversation_id: `demo-summary-1`
- action: `answer`
- intent: `SUMMARIZE_BY_MEDIA`
- selected_tool: `summarize_commission_by_media`
- nlu_mode: `llm_based`
- query: 按视频展开

### Answer
达人 88016 已按视频展开，当前命中 5 个视频。下面 evidence 中列出了订单量最高的前 5 个视频。

### Evidence
- `es_fact` 按视频汇总 | commission_orders_v1 | 达人 88016 当前命中 5 个视频，前 5 个视频已在 evidence 中展开。
- `es_fact` 视频 990075 | commission_orders_v1 | 总订单 10，可分佣 0，不可分佣 10，总佣金 0.00。
- `es_fact` 视频 990079 | commission_orders_v1 | 总订单 8，可分佣 0，不可分佣 8，总佣金 0.00。
- `es_fact` 视频 990076 | commission_orders_v1 | 总订单 7，可分佣 0，不可分佣 7，总佣金 0.00。
- `es_fact` 视频 990078 | commission_orders_v1 | 总订单 6，可分佣 0，不可分佣 6，总佣金 0.00。
- `es_fact` 视频 990077 | commission_orders_v1 | 总订单 5，可分佣 0，不可分佣 5，总佣金 0.00。

## media_reason
- role: `operator`
- conversation_id: `demo-media-1`
- action: `answer`
- intent: `QUERY_MEDIA_NO_COMMISSION_REASON`
- selected_tool: `get_media_no_commission_breakdown`
- nlu_mode: `llm_based`
- query: 查询视频990041为什么不可分佣

### Answer
视频 990041 当前命中的不可分佣订单共有 16 笔。主要原因分布为 履约任务状态无效或已取消 5 笔，商品在投稿/下单时都不处于推广状态 4 笔，无法通过订单 POI 找到店铺 3 笔，非联盟达人/未成为可参与分佣的达人 2 笔，达人包任务不是 CPS/CPX 任务 1 笔，分佣比例为 0 1 笔。 结合规则说明：根据当前不可分佣统计，主要规则解释为：`no_commission_type=1`。商品在投稿和用户下单时都不处于推广状态，因此订单无法进入分佣链路。；`no_commission_type=5`。商品或任务的分佣比例为 0，因此虽然有带货行为，但最终不产生佣金。

### Evidence
- `es_fact` 视频不可分佣统计 | commission_orders_v1 | 视频 990041 不可分佣订单 16 笔；履约任务状态无效或已取消 5 笔，商品在投稿/下单时都不处于推广状态 4 笔，无法通过订单 POI 找到店铺 3 笔，非联盟达人/未成为可参与分佣的达人 2 笔，达人包任务不是 CPS/CPX 任务 1 笔，分佣比例为 0 1 笔。
- `knowledge_chunk` 达人联盟分佣业务 / 不可分佣原因说明 / NO_PRODUCT_COMMISSION | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `no_commission_type=1`。商品在投稿和用户下单时都不处于推广状态，因此订单无法进入分佣链路。
- `knowledge_chunk` 达人联盟分佣业务 / 不可分佣原因说明 / COMMISSION_RATE_ZERO | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `no_commission_type=5`。商品或任务的分佣比例为 0，因此虽然有带货行为，但最终不产生佣金。
- `knowledge_chunk` 达人联盟分佣业务 / 不可分佣原因说明 / FULFILMENT_TASK_INVALID_STATUS | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `no_commission_type=3`。履约任务状态异常、无效或已经取消，导致订单不能分佣。
- `knowledge_chunk` 达人联盟分佣业务 / 不可分佣原因说明 / NO_EXIST_SHOP_FROM_ORDER_POI | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `no_commission_type=6`。系统无法根据订单 POI 找到店铺信息，无法完成店铺与任务的归因。

## order_transfer
- role: `operator`
- conversation_id: `demo-order-1`
- action: `answer`
- intent: `QUERY_ORDER_TRANSFER_STATUS`
- selected_tool: `get_order_transfer_status`
- nlu_mode: `llm_based`
- query: 查询订单 SO-20260308-001127 什么时候到账

### Answer
订单 SO-20260308-001127 当前状态为已到账，到账时间为 2026-03-17 02:25:54 UTC。 规则说明：- `order_confirm_time` 表示用户下单确认时间。 - `order_complete_time` 表示订单完成核销时间。 - `transfer_time` 表示实际到账时间。 - 当 `transfer_type=2`...；`transfer_type=2`。订单已经满足结算前提，处于待打款或打款处理中，通常按 T+2 预计到账。

### Evidence
- `es_fact` 订单到账事实 | commission_orders_v1 | 订单 SO-20260308-001127，状态 已到账，source_type 开环CPS，佣金 722.76。
- `knowledge_chunk` 达人联盟分佣业务 / T+2 到账规则 | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | - `order_confirm_time` 表示用户下单确认时间。 - `order_complete_time` 表示订单完成核销时间。 - `transfer_time` 表示实际到账时间。 - 当 `transfer_type=2`...
- `knowledge_chunk` 达人联盟分佣业务 / 转账状态说明 / 在路上 | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `transfer_type=2`。订单已经满足结算前提，处于待打款或打款处理中，通常按 T+2 预计到账。
- `knowledge_chunk` 达人联盟分佣业务 / 转账状态说明 / 不可转账 | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `transfer_type=1`。当前订单还不满足打款条件，需要结合 `no_transfer_reason` 理解具体原因。
- `knowledge_chunk` 达人联盟分佣业务 / 不可转账原因说明 / 订单未完成 | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `no_transfer_reason=2`。订单尚未完成核销，结算链路还未开始。

## term_explain
- role: `operator`
- conversation_id: `demo-knowledge-1`
- action: `answer`
- intent: `EXPLAIN_BUSINESS_TERM`
- selected_tool: `explain_business_term`
- nlu_mode: `llm_based`
- query: 解释一下闭环cps和cpt的区别

### Answer
闭环cps和cpt 的相关规则如下：1. 开环 CPS：为商品设置开环通用计划，达人投稿携带商品后，用户下单即可获取开环 CPS 佣金。 2. 闭环 CPS：为商品设置闭环通用计划，达人投稿携带商品后，用户在站内下单即可获取闭环 CPS 佣金。 3. 达人包 CPS：商家发布...；`source_type=1`。用户浏览内容、下单和支付都在平台内完成，平台掌握更完整的成交和归因链路。；订单核销后，才会开始结算。CPS 和 CPT 都按照 T+2 结算。

### Evidence
- `knowledge_chunk` 达人联盟分佣业务 / 分佣类型 / CPS | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | 1. 开环 CPS：为商品设置开环通用计划，达人投稿携带商品后，用户下单即可获取开环 CPS 佣金。 2. 闭环 CPS：为商品设置闭环通用计划，达人投稿携带商品后，用户在站内下单即可获取闭环 CPS 佣金。 3. 达人包 CPS：商家发布...
- `knowledge_chunk` 达人联盟分佣业务 / source_type 说明 / 闭环CPS | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `source_type=1`。用户浏览内容、下单和支付都在平台内完成，平台掌握更完整的成交和归因链路。
- `knowledge_chunk` 达人联盟分佣业务 / 结算时机 | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | 订单核销后，才会开始结算。CPS 和 CPT 都按照 T+2 结算。
- `knowledge_chunk` 达人联盟分佣业务 / 分佣类型 / CPT | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | 只有达人包任务类型会出现 CPT。达人包任务创建时会设置一个固定佣金值，比如 100。 - 达人发布投稿并审核通过，可先获得 30% 佣金。 - 视频公开状态达到七天后，可获取另外 70% 佣金。

## compare
- role: `operator`
- conversation_id: `demo-summary-1`
- action: `answer`
- intent: `COMPARE_SOURCE_TYPE`
- selected_tool: `compare_source_type_commission`
- nlu_mode: `llm_based`
- query: 对比闭环cps和开环cps

### Answer
达人 88016 的来源类型对比结果如下：开环CPS: 15 单，可分佣 0，不可分佣 15，佣金 0.00；闭环CPS: 11 单，可分佣 0，不可分佣 11，佣金 0.00

### Evidence
- `es_fact` 来源类型对比 | commission_orders_v1 | 开环CPS: 15 单，可分佣 0，不可分佣 15，佣金 0.00
- `es_fact` 来源类型对比 | commission_orders_v1 | 闭环CPS: 11 单，可分佣 0，不可分佣 11，佣金 0.00

## creator_self
- role: `creator`
- conversation_id: `demo-creator-1`
- action: `answer`
- intent: `QUERY_CREATOR_SUMMARY`
- selected_tool: `get_creator_commission_summary`
- nlu_mode: `llm_based`
- query: 帮我查最近30天分佣情况

### Answer
查询范围为 2026-02-06 ~ 2026-03-08。达人 88016 共有 178 笔订单，可分佣 142 笔，不可分佣 36 笔，总佣金 52592.30。主要来源分布为 闭环CPS 76 笔，开环CPS 62 笔，CPT 40 笔。

### Evidence
- `es_fact` 达人分佣汇总 | commission_orders_v1 | 达人 88016，2026-02-06 ~ 2026-03-08，总订单 178，总佣金 52592.30。
- `es_fact` 来源类型分布 | commission_orders_v1 | 闭环CPS 76 笔，开环CPS 62 笔，CPT 40 笔
- `es_fact` 不可分佣原因分布 | commission_orders_v1 | 非联盟达人/未成为可参与分佣的达人 7 笔，达人包任务不是 CPS/CPX 任务 7 笔，分佣比例为 0 7 笔，无法通过订单 POI 找到店铺 6 笔，履约任务状态无效或已取消 5 笔，商品在投稿/下单时都不处于推广状态 4 笔

## permission_check
- role: `creator`
- conversation_id: `demo-creator-2`
- action: `answer`
- intent: `QUERY_CREATOR_SUMMARY`
- selected_tool: `None`
- nlu_mode: `llm_based`
- query: 帮我查达人99999最近30天分佣情况

### Answer
creator 角色只能查询绑定达人 88016 的数据，当前请求的 creator_id=99999 无权限访问。

### Evidence

## term_explain
- role: `operator`
- conversation_id: `demo-fallback-1`
- action: `answer`
- intent: `EXPLAIN_BUSINESS_TERM`
- selected_tool: `explain_business_term`
- nlu_mode: `llm_based`
- query: 解释一下 NO_PRODUCT_COMMISSION

### Answer
no_product_commission 的相关规则如下：`no_commission_type=1`。商品在投稿和用户下单时都不处于推广状态，因此订单无法进入分佣链路。；`no_commission_type=5`。商品或任务的分佣比例为 0，因此虽然有带货行为，但最终不产生佣金。；`no_commission_type=3`。履约任务状态异常、无效或已经取消，导致订单不能分佣。

### Evidence
- `knowledge_chunk` 达人联盟分佣业务 / 不可分佣原因说明 / NO_PRODUCT_COMMISSION | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `no_commission_type=1`。商品在投稿和用户下单时都不处于推广状态，因此订单无法进入分佣链路。
- `knowledge_chunk` 达人联盟分佣业务 / 不可分佣原因说明 / COMMISSION_RATE_ZERO | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `no_commission_type=5`。商品或任务的分佣比例为 0，因此虽然有带货行为，但最终不产生佣金。
- `knowledge_chunk` 达人联盟分佣业务 / 不可分佣原因说明 / FULFILMENT_TASK_INVALID_STATUS | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `no_commission_type=3`。履约任务状态异常、无效或已经取消，导致订单不能分佣。
- `knowledge_chunk` 达人联盟分佣业务 / 不可分佣原因说明 / NOT_ALLIANCE_CREATOR | /Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md | `no_commission_type=2`。达人不是联盟达人，或尚未满足参与分佣的资格。
