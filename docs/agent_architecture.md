# Agent Architecture

当前版本的核心变化有两点：

- graph 已切到 LangGraph 官方 checkpointer
- 自定义 `ConversationStore` 与手写 `load/save` 节点已经删除
- 状态机开始收敛为 `turn_understanding -> task_state -> query_plan`

## 工作流

当前工作流节点顺序如下：

1. `understand_query`
2. `reduce_state`
3. `normalize_and_validate`
4. 条件分支：
   - clarify -> `clarify_if_needed`
   - unsupported -> `compose_answer`
   - route -> `build_query_plan`
5. `build_query_plan`
6. 条件分支：
   - execute -> `execute_tool`
   - unsupported -> `compose_answer`
7. `execute_tool`
8. `compose_answer`

说明：

- graph state 由官方 checkpointer 自动持久化
- follow-up 查询先经过 `state_reducer`，再继承 `task_state.normalized_filters`
- creator 权限校验在 `normalize_and_validate`
- 缺参时直接返回 `clarify`
- tool 路由先走 `query_plan`，不再直接 `intent -> tool`
- tool 节点只调用封装好的应用层工具，不拼 ES DSL

## 目录结构

```text
code/commission_agent/
├── app/
│   ├── api/
│   ├── application/
│   │   ├── agent/
│   │   ├── nlu/
│   │   └── tools/
│   ├── domain/
│   ├── infrastructure/es/
│   └── scripts/
└── docs/
```

## 会话上下文

当前版本使用 LangGraph 官方 checkpointer：

- `thread_id = conversation_id`
- PostgreSQL backend 下由 `PostgresSaver` 持久化
- memory backend 下由 `InMemorySaver` 持久化

业务上真正依赖的任务态字段是：

- `messages`
- `task_state.task_type`
- `task_state.status`
- `task_state.normalized_filters`
- `task_state.pending_requirements`
- `task_state.selected_tool`
- `task_state.action`
- `task_state.last_result_summary`
- `task_state.answer_summary`

执行层会再从 `task_state` 生成 `query_plan`：

- `mode`
- `tool_name`
- `response_intent`
- `filters`

## NLU 策略

- 当前项目使用 `LLMBasedNLU`
- graph 中只做一次 `understand_query`
- 输出：
  - `turn_type`
  - `task_type`
  - `slots`
  - `confidence`
- 当模型配置可用时，NLU 走当前 `MODEL_PROVIDER` 对应的 chat provider
- 当模型不可用时，NLU 会直接报错，不再伪装成业务上的 `UNKNOWN`

## Chat API

启动：

```bash
conda activate commission_env
uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

示例请求：

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id": "demo-1",
    "message": "帮我查达人88016最近30天分佣情况",
    "user_role": "operator",
    "bound_creator_id": null
  }'
```

响应结构包含：

- `action`
- `answer`
- `intent`
- `normalized_filters`
- `evidence`
- `next_suggestions`
- `missing_slots`

## Workflow 验证

```bash
python -m app.scripts.validate_agent_workflow
```

脚本至少覆盖：

- operator 查询达人汇总
- follow-up 只看不可分佣
- follow-up 按视频展开
- 查询视频不可分佣原因
- 查询订单到账状态
- 解释闭环CPS 和 CPT 的区别

## 下一阶段接入 markdown RAG

当前术语解释由 `StaticKnowledgeTool` 提供。下一阶段可以平滑替换为：

1. markdown 文档切片器
2. 本地检索接口
3. 保持 `explain_business_term()` 工具接口不变，仅替换内部实现
