# Commission Agent

本目录已完成四个阶段：

- 第一阶段：Elasticsearch 数据层
- 第二阶段：Agent 核心骨架、LangGraph workflow、FastAPI `/api/chat`
- 第三阶段：OpenAI 兼容 provider 接入、markdown 知识索引、轻量 RAG、LLMBasedNLU
- 第四阶段：Web Chat 页面、调试面板、演示脚本

所有实现都放在 `code/commission_agent` 下，没有污染仓库其他目录。

## 项目目录

```text
code/commission_agent/
├── app/
│   ├── api/
│   ├── application/
│   │   ├── agent/
│   │   ├── knowledge/
│   │   ├── llm/
│   │   ├── nlu/
│   │   └── tools/
│   ├── config/
│   ├── domain/
│   ├── infrastructure/es/
│   └── scripts/
├── docs/
├── knowledge/
├── .env.example
├── docker-compose.yml
└── requirements.txt
```

## conda 环境创建

```bash
conda create -n commission_env python=3.11 -y
conda activate commission_env
```

如果当前机器的 `conda activate` 没有初始化，可以先执行：

```bash
conda init zsh
```

## 依赖安装

```bash
pip install -r requirements.txt
```

当前依赖包括：

- `elasticsearch`
- `fastapi`
- `uvicorn`
- `pydantic`
- `langgraph`
- `langchain-core`
- `httpx`
- `python-dateutil`
- `openai`
- `numpy`

## 当前架构

当前这套 Agent 不是自由循环的 ReAct Agent，而是一个受控状态机。

主链路：

```text
用户消息
-> understand_query
-> reduce_state
-> normalize_and_validate
-> build_query_plan
-> execute_tool
-> compose_answer
```

其中：

- `understand_query`
  - 一次 LLM 调用完成单轮语义理解
  - 输出：
    - `turn_type`
    - `entity_scope`
    - `goal_type`
    - `slots`
- `resolve_task_type`
  - 后端把：
    - `entity_scope + goal_type`
  - 映射成系统支持的 `task_type`
- `reduce_state`
  - 把上一轮 `task_state` 和本轮理解结果合成新的任务态
- `normalize_and_validate`
  - 做时间标准化、权限校验、缺参判断
- `build_query_plan`
  - 把稳定的 `task_state` 翻译成执行计划
- `execute_tool`
  - 查询类走 ES
  - explain 类走 knowledge 检索 + LLM 组织答案

当前状态机是条件路由 graph，而不是线性节点里靠 `if/else` 短路。

### 关键语义层

当前 NLU 不再让 LLM 直接拍板最终任务，而是先输出底层语义维度：

- `turn_type`
  - `NEW_QUERY`
  - `MODIFY_FILTERS`
  - `ANSWER_CLARIFY`
  - `EXPLAIN`
  - `UNSUPPORTED`
- `entity_scope`
  - `CREATOR`
  - `MEDIA`
  - `ORDER`
  - `TERM`
- `goal_type`
  - `SUMMARY`
  - `STATUS`
  - `REASON`
  - `COMPARE`
  - `EXPLAIN`

然后由后端 resolver 做确定性映射，例如：

- `CREATOR + SUMMARY -> CREATOR_COMMISSION`
- `MEDIA + STATUS -> MEDIA_COMMISSION_STATUS`
- `MEDIA + REASON -> MEDIA_NO_COMMISSION_REASON`
- `ORDER + STATUS -> ORDER_TRANSFER_STATUS`
- `TERM + EXPLAIN -> TERM_EXPLAIN`

这样可以显著降低：

- “视频是否可分佣” 和 “视频为什么不可分佣” 混淆
- “按视频展开” 把任务切成新任务
- clarify 补 `media_id / order_id` 时任务类型漂移

### 会话持久化

当前不再使用自定义 `ConversationStore`。

会话状态持久化由 LangGraph 官方 PostgreSQL checkpointer 接管：

- `thread_id = conversation_id`
- 每轮请求都会从 graph 起点重新执行
- 但会先恢复上一轮的 `task_state`

这意味着：

- 系统支持跨请求多轮 follow-up
- clarify 补参可以延续
- 运行时状态只有一份真相：graph state / `task_state`

## 环境变量

复制配置：

```bash
cp .env.example .env
```

推荐配置：

```env
MODEL_PROVIDER=local
EMBEDDING_PROVIDER=bailian
LLM_ENABLED=true
RAG_ENABLED=true
APP_DEBUG=true
CONVERSATION_STORE_BACKEND=memory
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=commission_agent
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DSN=
POSTGRES_SSLMODE=disable
CHAT_BASE_URL=
CHAT_API_KEY=
CHAT_MODEL=
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
EMBEDDING_MODEL=
BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
BAILIAN_API_KEY=
BAILIAN_CHAT_MODEL=qwen3.5-flash
BAILIAN_EMBEDDING_MODEL=text-embedding-v4
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
ZHIPU_API_KEY=
ZHIPU_CHAT_MODEL=glm-4.7
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
VOLCENGINE_API_KEY=
VOLCENGINE_CHAT_MODEL=DeepSeek-V3.2
LOCAL_CHAT_BASE_URL=http://127.0.0.1:18080/v1
LOCAL_CHAT_API_KEY=local-llm
LOCAL_CHAT_MODEL=qwen-local
ES_HOST=http://127.0.0.1:9200
ES_INDEX=commission_orders_v1
ES_USERNAME=
ES_PASSWORD=
ES_VERIFY_CERTS=false
COMMISSION_SEED=20260308
```

说明：

- `MODEL_PROVIDER` 控制 chat / NLU 当前使用哪个 provider：
  - `local`
  - `bailian`
  - `zhipu`
  - `volcengine`
- `EMBEDDING_PROVIDER` 控制向量构建默认使用哪个 provider，当前推荐保留为 `bailian`
- `CONVERSATION_STORE_BACKEND` 控制会话快照后端：
  - `memory`
  - `postgres`
- 如需切换 provider，优先只改：
  - `MODEL_PROVIDER`
  - `EMBEDDING_PROVIDER`
- 若显式填写 `CHAT_*` / `EMBEDDING_*`，会覆盖 provider 预设
- 当 chat 配置不完整时：
  - `LLMBasedNLU` 不可用
  - `debug.nlu_mode` 会显示 `llm_unavailable`
- 当 embedding 配置不完整时：
  - 已构建好的 RAG 索引仍可读取
  - 只是不能重新生成新的向量文件

### Provider 切换示例

切到本地模型：

```env
MODEL_PROVIDER=local
```

切到阿里百炼：

```env
MODEL_PROVIDER=bailian
```

切到智谱：

```env
MODEL_PROVIDER=zhipu
```

切到火山引擎：

```env
MODEL_PROVIDER=volcengine
```

切换 provider 后需要重启 FastAPI 服务。

如果使用本地模型，先启动本地 `llama-server`：

```bash
/opt/homebrew/bin/llama-server \
  -m /Users/gehaoyuan/code/models/qwen25-single/Qwen2.5-14B-Instruct-Q4_K_M.gguf \
  --host 127.0.0.1 \
  --port 18080 \
  -ngl 999 \
  -t 8
```

## Elasticsearch 启动

优先方案：

```bash
docker compose up -d
```

这条命令现在会同时启动：

- Elasticsearch：`http://127.0.0.1:9200`
- Kibana：`http://127.0.0.1:5601`

当前机器实际验证用的是本地 ES 归档包启动，命令如下：

```bash
ES_JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home \
ES_JAVA_OPTS="-Xms512m -Xmx512m -Dos.name=BSD -Dorg.fusesource.jansi.Ansi.disable=true" \
./.elasticsearch/elasticsearch-8.17.2/bin/elasticsearch \
  -Ecluster.name=commission-agent-local \
  -Enode.name=commission-agent-node-1 \
  -Ediscovery.type=single-node \
  -Expack.security.enabled=false \
  -Expack.ml.enabled=false \
  -Eingest.geoip.downloader.enabled=false \
  -Enetwork.host=127.0.0.1 \
  -Ehttp.port=9200 \
  -Epath.data=$PWD/.elasticsearch/data \
  -Epath.logs=$PWD/.elasticsearch/logs
```

## Kibana 启动

如果你想直接在页面里查看 ES 数据，可以启动本地 Kibana。

优先推荐直接使用 docker compose，一次把 ES 和 Kibana 都起起来：

```bash
cd /Users/gehaoyuan/code/commission_agent
docker compose up -d
```

查看状态：

```bash
docker compose ps
```

关闭：

```bash
docker compose down
```

当前项目已经把 Kibana 归档包和本地配置放在：

- [kibana-8.17.2-darwin-aarch64.tar.gz](/Users/gehaoyuan/code/commission_agent/.kibana/kibana-8.17.2-darwin-aarch64.tar.gz)
- [kibana.local.yml](/Users/gehaoyuan/code/commission_agent/.kibana/kibana.local.yml)

首次使用如果还没解压：

```bash
cd /Users/gehaoyuan/code/commission_agent
tar -xzf ./.kibana/kibana-8.17.2-darwin-aarch64.tar.gz -C ./.kibana
```

启动命令：

```bash
cd /Users/gehaoyuan/code/commission_agent
./.kibana/kibana-8.17.2/bin/kibana --config ./.kibana/kibana.local.yml
```

启动后访问：

- [http://127.0.0.1:5601](http://127.0.0.1:5601)

说明：

- 这个 Kibana 配置默认连接本地 ES：`http://127.0.0.1:9200`
- 端口默认是 `5601`
- 关闭方式：在启动 Kibana 的终端里按 `Ctrl+C`

首次进入后建议这样查看数据：

1. 进入 `Stack Management` -> `Data Views`
2. 创建 Data View：`commission_orders_v1`
3. 打开 `Discover`
4. 按字段筛选，例如：
   - `creator_id: 88016`
   - `media_id: 990041`
   - `shop_order_id: "SO-20260308-001127"`
   - `is_commission: 2`

## 第一阶段命令

初始化索引：

```bash
python -m app.scripts.init_es --recreate
```

写入 mock 数据：

```bash
python -m app.scripts.seed_es --count 3000
```

基础校验：

```bash
python -m app.scripts.validate_es
```

## 第三阶段：知识索引与 RAG

知识 markdown 标准位置：

- [knowledge/rag_knowledge.md](/Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md)

构建知识索引：

```bash
python -m app.scripts.build_knowledge_index
```

构建产物：

- [knowledge/chunks.jsonl](/Users/gehaoyuan/code/commission_agent/knowledge/chunks.jsonl)
- [knowledge/index.json](/Users/gehaoyuan/code/commission_agent/knowledge/index.json)
- 如果 embedding 可用，还会额外生成 `knowledge/index.npy`

本地实际构建结果：

- source file: `knowledge/rag_knowledge.md`
- chunk count: `27`
- index mode: `embedding`
- embedding model: `text-embedding-v4`

说明：

- chat 和 embedding 现在支持分离配置
- 当前本地实际验证：
  - chat 可在 `local / bailian / zhipu` 之间切换
  - embedding 默认继续使用百炼兼容地址
  - `text-embedding-v4` 已成功返回 1024 维向量

验证 RAG：

```bash
python -m app.scripts.validate_rag
```

验证 LLM NLU：

```bash
python -m app.scripts.validate_llm_nlu
```

验证 Agent + RAG：

```bash
python -m app.scripts.validate_agent_with_rag
```

## FastAPI

启动：

```bash
uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

如果 `8000` 端口被占用，可以切到其他端口，例如：

```bash
uvicorn app.api.main:app --host 127.0.0.1 --port 8001
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

`/api/chat` 示例：

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id": "demo-rag-1",
    "message": "帮我查视频990041为什么不可分佣",
    "user_role": "operator",
    "bound_creator_id": null
  }'
```

creator 模式示例：

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id": "demo-rag-2",
    "message": "帮我查最近30天分佣情况",
    "user_role": "creator",
    "bound_creator_id": 88016
  }'
```

## 当前支持的问题类型

- 查某达人最近 30 天分佣情况
- 只看不可分佣订单
- 按视频展开
- 对比闭环 CPS 和开环 CPS
- 查询某视频是否可分佣
- 查询某视频为什么不可分佣
- 查询订单什么时候到账
- 解释 CPS / CPT / 闭环 / 开环 / NO_PRODUCT_COMMISSION 等术语或规则

说明：

- 订单到账状态当前只支持订单维度
- 像“我的佣金什么时候到账”这类问句会被收敛成：
  - `ORDER + STATUS`
  - 缺订单号时进入 clarify

响应字段：

- `action`
- `answer`
- `intent`
- `normalized_filters`
- `evidence`
- `next_suggestions`
- `missing_slots`
- `debug`

## evidence 结构

`evidence` 统一包含：

- `type`: `es_fact` 或 `knowledge_chunk`
- `title`
- `content_summary`
- `source`
- `score`

示例：

```json
[
  {
    "type": "es_fact",
    "title": "视频不可分佣统计",
    "content_summary": "视频 990041 不可分佣订单 16 笔...",
    "source": "commission_orders_v1",
    "score": null
  },
  {
    "type": "knowledge_chunk",
    "title": "达人联盟分佣业务 / 不可分佣原因说明 / NO_PRODUCT_COMMISSION",
    "content_summary": "`no_commission_type=1`。商品在投稿和用户下单时都不处于推广状态...",
    "source": "/Users/gehaoyuan/code/commission_agent/knowledge/rag_knowledge.md",
    "score": 0.5
  }
]
```

`debug` 在开发环境默认开启，包含：

- `nlu_mode`: `llm_based` 或 `llm_unavailable`
- `retrieved_chunks`
- `selected_tool`
- `workflow_trace`
- `timing`

## 运行日志

FastAPI 和 Agent workflow 现在都会把日志落到本地文件。

日志目录：

- [api.log](/Users/gehaoyuan/code/commission_agent/logs/api.log)
- [agent.log](/Users/gehaoyuan/code/commission_agent/logs/agent.log)

说明：

- `api.log`
  - 记录页面访问、健康检查、`/api/chat` 请求和响应摘要
  - 也会包含 `uvicorn.error` 和 `uvicorn.access` 日志
- `agent.log`
  - 记录每个 LangGraph 节点的开始、结束、耗时和摘要
  - 例如 `classify_intent`、`normalize_and_validate`、`execute_tool`

实时查看：

```bash
tail -f /Users/gehaoyuan/code/commission_agent/logs/api.log
tail -f /Users/gehaoyuan/code/commission_agent/logs/agent.log
```

## PostgreSQL Checkpointer 持久化

持久化说明见 [docs/postgres_persistence.md](/Users/gehaoyuan/code/commission_agent/docs/postgres_persistence.md)。

如果本机已有 PostgreSQL，可直接配置：

```env
CONVERSATION_STORE_BACKEND=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=commission_agent
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_SSLMODE=disable
```

初始化 LangGraph checkpointer 表：

```bash
python -m app.scripts.init_postgres
```

验证官方 checkpointer：

```bash
CONVERSATION_STORE_BACKEND=postgres python -m app.scripts.validate_checkpointer
```

验证 Agent 多轮：

```bash
CONVERSATION_STORE_BACKEND=postgres python -m app.scripts.validate_agent_postgres
```

## 第四阶段：Web Demo

页面文档见 [docs/web_demo.md](/Users/gehaoyuan/code/commission_agent/docs/web_demo.md)。

启动服务：

```bash
cd /Users/gehaoyuan/code/commission_agent
conda activate commission_env
uvicorn app.api.main:app --host 127.0.0.1 --port 8001
```

打开页面：

- [http://127.0.0.1:8001](http://127.0.0.1:8001)

页面主要区域：

- 标题区
- 会话控制区
- Demo Guide
- 快捷问题区
- 聊天区
- 调试面板

调试面板现在额外展示：

- `workflow_trace`
- 每个节点的 `status / duration_ms / summary`
- 本轮总请求耗时和 workflow 耗时

如果没有 API key：

- 页面仍可用
- 运行模式会显示 `LLM Unavailable`

如果当前 provider 配置可用：

- 页面会显示 `LLM + RAG`
- `debug.nlu_mode` 会显示 `llm_based`

运行 demo 脚本：

```bash
python -m app.scripts.run_demo_chat
```

生成产物：

- [demo/output/demo_transcript.md](/Users/gehaoyuan/code/commission_agent/demo/output/demo_transcript.md)
- [demo/output/demo_transcript.json](/Users/gehaoyuan/code/commission_agent/demo/output/demo_transcript.json)

## NLU 选择逻辑

- 当前项目只使用 `LLMBasedNLU`
- 当当前 chat provider 配置可用时，`debug.nlu_mode=llm_based`
- 当 LLM 不可用时，`debug.nlu_mode=llm_unavailable`
- 前端不再提供模型切换开关，NLU 固定走 `LLMBasedNLU`

## 真实 LLM 回归

当前项目维护了一套真实 LLM 驱动的回归脚本：

- [/Users/gehaoyuan/code/commission_agent/app/scripts/validate_real_llm_matrix.py](/Users/gehaoyuan/code/commission_agent/app/scripts/validate_real_llm_matrix.py)

这套脚本不是纯本地单测，而是直接调用：

- 本地 `/api/chat`
- 真实 LLM
- 真实 LangGraph 状态机
- 真实 ES / RAG / PostgreSQL checkpointer

运行命令：

```bash
cd /Users/gehaoyuan/code/commission_agent
CONVERSATION_STORE_BACKEND=postgres \
POSTGRES_DSN='dbname=commission_agent user=gehaoyuan' \
python -m app.scripts.validate_real_llm_matrix
```

当前覆盖共 `100` 个 turn 级 case，包含：

- creator summary
- media commission status
- media no-commission reason
- order transfer status
- explain
- creator permission

同时覆盖多轮 follow-up 和 clarify，例如：

- `只看最近7天`
- `按视频展开`
- `media_id: 990041`
- `我的佣金什么时候到账`
- `我的佣金到账了吗`

最新一次真实回归结果：

- `total_cases = 100`
- `passed = 100`
- `failed = 0`

日志输出：

- [/Users/gehaoyuan/code/commission_agent/demo/output/validate_real_llm_matrix.log](/Users/gehaoyuan/code/commission_agent/demo/output/validate_real_llm_matrix.log)
- 查某视频为什么不可分佣
- 查某订单什么时候到账
- 解释 `cps / cpt / 开环 / 闭环`
- 解释 `NO_PRODUCT_COMMISSION / transfer_type / no_transfer_reason / T+2`
- 汇总某达人按视频维度的分佣情况
- 对比两类 `source_type` 的分佣情况
- follow-up：
  - `只看最近 7 天`
  - `只看不可分佣订单`
  - `按视频展开`
  - `对比闭环CPS和开环CPS`

## 字段与枚举说明

完整字段说明、业务规则和中英文枚举映射见：

- [docs/es_design.md](/Users/gehaoyuan/code/commission_agent/docs/es_design.md)
- [docs/agent_architecture.md](/Users/gehaoyuan/code/commission_agent/docs/agent_architecture.md)
- [docs/rag_design.md](/Users/gehaoyuan/code/commission_agent/docs/rag_design.md)
- [docs/llm_integration.md](/Users/gehaoyuan/code/commission_agent/docs/llm_integration.md)

## 验证摘要

第一阶段：

- 索引创建成功：`commission_orders_v1`
- 写入成功：`3000` 条 mock 数据
- `validate_es` 已跑通

第二阶段：

- `validate_agent_workflow` 已跑通
- 多轮上下文继承已验证
- FastAPI `/health` 和 `/api/chat` 已验证

第三阶段：

- `build_knowledge_index` 已跑通，生成 `27` 个 chunk
- 当前配置下 embedding 已可用，索引已切换为 `embedding`
- `validate_rag` 已跑通：
  - `什么是闭环cps`
  - `cpt和cps有什么区别`
  - `NO_PRODUCT_COMMISSION 是什么意思`
- `validate_llm_nlu` 已跑通，当前环境已验证 `LLMBasedNLU`
- `validate_agent_with_rag` 已跑通，覆盖：
  - operator 查询达人汇总
  - follow-up 只看不可分佣
  - follow-up 按视频展开
  - 视频不可分佣原因 + 规则解释
  - 订单到账状态 + T+2 说明
  - explain term
  - creator 自动绑定 creator_id
  - 无 key explain 静态知识路径
- FastAPI 实测返回：
  - `GET /health -> {"status":"ok"}`
  - `POST /api/chat` 返回 `answer + evidence + debug`
  - `debug.nlu_mode=llm_based`

第四阶段：

- `GET /` 提供可用的 Web Chat 页面
- 页面支持多轮对话、角色切换、调试面板、evidence 展示
- `run_demo_chat` 可生成 transcript 文件

## 下一阶段

下一阶段最适合衔接：

- markdown RAG 质量优化
- 更强的多轮会话 memory
- 正式业务化前端
