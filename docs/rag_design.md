# RAG Design

第三阶段的 RAG 目标是：让 explain 类问题和“事实 + 规则解释”类问题能够基于 markdown 知识库返回可追溯证据，并支持在本地文件检索与 Qdrant 向量数据库之间切换。

## 设计原则

1. 事实来自 ES
2. 规则来自知识库
3. 无 API key 时仍可运行
4. evidence 必须可追溯到 chunk

## 知识输入

标准知识文件：

- [knowledge/rag_knowledge.md](/Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md)

内容覆盖：

- CPS / CPT
- 开环 / 闭环
- T+2 到账规则
- `no_commission_type`
- `transfer_type`
- `no_transfer_reason`

## 切块策略

采用 heading-aware chunking：

- 按 markdown 标题层级切块
- 每个 chunk 保留：
  - `chunk_id`
  - `source_file`
  - `heading_path`
  - `text`
  - `keywords`
  - `start_line`
  - `end_line`

当前实际构建结果：

- chunk 数量：`27`

## 索引策略

当前支持两种索引后端：

1. `local`
   - [knowledge/chunks.jsonl](/Users/gehaoyuan/code/commission_agent/knowledge/chunks.jsonl)
   - [knowledge/index.json](/Users/gehaoyuan/code/commission_agent/knowledge/index.json)
   - 有 embedding 时追加 `knowledge/index.npy`

2. `qdrant`
   - 本地文件仍然保留，便于调试和 fallback
   - chunk 向量额外同步到 Qdrant collection：`commission_knowledge`

索引模式：

- 有百炼 key：`embedding`
- 无百炼 key：`keyword`
- 如果 embedding 接口配置存在但调用失败：自动降级为 `keyword`

## 检索策略

检索路径支持两种后端：

1. local embedding 检索
   - 通过百炼 OpenAI 兼容 Embedding 接口生成向量
   - 本地 `numpy + cosine similarity`

2. qdrant embedding 检索
   - query 先做 embedding
   - Qdrant collection 做 top-k 向量检索
   - collection 同时保存 chunk payload，便于 evidence 返回

3. keyword fallback
   - 面向业务术语和 code 的关键词命中
   - 不依赖外部 API

## 服务层

`KnowledgeService` 对外提供：

- `build_index`
- `retrieve_term_knowledge`
- `retrieve_rule_knowledge`
- `explain_business_term`
- `explain_rule_with_context`

其中：

- explain term：直接检索知识 chunk
- explain rule with context：先接收 ES 事实，再用事实构造规则查询

## evidence 输出

统一输出：

- `type`
- `title`
- `content_summary`
- `source`
- `score`

这样 API 可以同时返回：

- `es_fact`
- `knowledge_chunk`

## fallback

当没有 API key 时：

- build 仍可成功
- 索引模式切到 `keyword`
- explain 类问题仍能命中 markdown chunk
- 若 markdown 未命中，再回退到静态映射解释
