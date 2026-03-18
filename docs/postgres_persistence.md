# PostgreSQL Checkpointer Persistence

这次改造把会话持久化切到了 LangGraph 官方 checkpointer。

目标是：

- `AgentState` 作为唯一运行时真相
- PostgreSQL 只负责持久化整份 graph state
- 不再维护自定义 `ConversationStore`
- 不再手写 `load_conversation_context()` / `save_conversation_context()`

## 当前结构

- `app/application/agent/checkpointer.py`
  - 统一封装官方：
    - `InMemorySaver`
    - `PostgresSaver`
- `app/application/agent/graph.py`
  - `graph.compile(checkpointer=...)`
- `app/application/agent/state.py`
  - 定义持久化任务态和单轮执行态
- `app/api/main.py`
  - 每次调用时传 `thread_id=conversation_id`
  - `reset` 直接删官方 checkpoint thread

## 环境变量

```env
CONVERSATION_STORE_BACKEND=memory
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=commission_agent
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DSN=
POSTGRES_SSLMODE=disable
```

优先级：

1. `POSTGRES_DSN`
2. `POSTGRES_HOST / PORT / DB / USER / PASSWORD / SSLMODE`

## 持久化字段

LangGraph 会保存完整 state，但业务上真正作为“会话任务态”的字段收敛为：

- `conversation_id`
- `messages`
- `task_state.task_type`
- `task_state.status`
- `task_state.normalized_filters`
- `task_state.pending_requirements`
- `task_state.selected_tool`
- `task_state.action`
- `task_state.last_result_summary`
- `task_state.answer_summary`

前端调试面板展示的是这份最小快照：

- `conversation_id`
- `messages`
- `task_state`
- `intent`
- `normalized_filters`
- `missing_slots`
- `last_result_summary`
- `selected_tool`
- `action`
- `answer_summary`

## 初始化

```bash
CONVERSATION_STORE_BACKEND=postgres python -m app.scripts.init_postgres
```

这个脚本会调用官方 `PostgresSaver.setup()` 创建所需表结构。

## 验证

验证 checkpointer 自身：

```bash
CONVERSATION_STORE_BACKEND=postgres python -m app.scripts.validate_checkpointer
```

验证 Agent 多轮：

```bash
CONVERSATION_STORE_BACKEND=postgres python -m app.scripts.validate_agent_postgres
```

## API 行为

- `/api/chat`
  - 使用 `thread_id=conversation_id`
  - 每轮只注入当前用户输入和清空后的瞬时字段
  - 历史任务态由 checkpointer 自动恢复

- `/api/chat/reset`
  - 直接调用官方 `delete_thread(thread_id)`

## 为什么删除自定义 store

如果同时保留：

- LangGraph checkpointer
- 自定义 `ConversationStore`

就会再次出现“双真相”：

- graph 运行态一份
- 自定义快照一份

这正是当前架构要避免的。
