"""LangGraph 官方 checkpointer 的统一入口。

这里不再自己维护 ConversationStore，而是直接复用 LangGraph 官方的：
- InMemorySaver
- PostgresSaver

这样 graph state 本身就是唯一真相来源，持久化只是它的自然延伸。
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config.settings import Settings, get_settings
from app.domain.task_state_models import TaskState


_checkpointer: Any | None = None
_checkpointer_backend: str | None = None
_checkpointer_dsn: str | None = None
_postgres_pool: ConnectionPool | None = None
_checkpointer_lock = threading.Lock()


def get_agent_checkpointer(settings: Settings | None = None) -> Any:
    """返回当前进程复用的 LangGraph checkpointer。

    这里要特别注意一件事：
    - PostgreSQL 现在存的是“LangGraph state”
    - 不是我们再额外维护一份自定义业务快照

    也就是说，持久化不是另一套状态源，而只是 graph state 的官方存储后端。
    """

    global _checkpointer, _checkpointer_backend, _checkpointer_dsn, _postgres_pool
    current = settings or get_settings()
    backend = current.conversation_store_backend
    dsn = current.postgres_dsn

    with _checkpointer_lock:
        if _checkpointer is not None and _checkpointer_backend == backend and _checkpointer_dsn == dsn:
            return _checkpointer

        if _postgres_pool is not None:
            _postgres_pool.close()
            _postgres_pool = None

        if backend == "postgres":
            # FastAPI 是并发请求模型，checkpointer 不能长期绑死在单条 psycopg 连接上。
            # 这里改为官方支持的 ConnectionPool 形式，让每次 checkpoint 操作都从池里借连接。
            _postgres_pool = ConnectionPool(
                conninfo=dsn,
                max_size=5,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
            saver = PostgresSaver(_postgres_pool)
            saver.setup()
        else:
            saver = InMemorySaver()

        _checkpointer = saver
        _checkpointer_backend = backend
        _checkpointer_dsn = dsn
        return saver


def get_thread_config(conversation_id: str) -> dict[str, dict[str, str]]:
    """把业务会话 id 映射为 LangGraph thread_id。

    现在 conversation_id 和 thread_id 是同一件事的两种命名：
    - 业务层叫 conversation_id
    - LangGraph 持久化层叫 thread_id
    """

    return {"configurable": {"thread_id": conversation_id}}


def reset_conversation_state(conversation_id: str, settings: Settings | None = None) -> None:
    """删除一个 thread 的全部 checkpoint。

    这相当于把某个会话的持久化状态整体清空。
    之后同一个 conversation_id 再次请求时，会像一条全新会话。
    """

    get_agent_checkpointer(settings).delete_thread(conversation_id)


def dump_conversation_state(workflow: Any, conversation_id: str) -> dict[str, Any]:
    """导出前端调试面板需要的最小持久化状态。

    注意这里不是在“再存一份 snapshot”，而只是把 LangGraph 当前 state
    投影成前端更容易读的结构，方便调试面板展示。
    """

    try:
        snapshot = workflow.get_state(get_thread_config(conversation_id))
        values = snapshot.values or {}
    except Exception:
        values = {}

    task_state = _coerce_task_state(values.get("task_state"))
    payload = {
        "conversation_id": conversation_id,
        "messages": _to_plain(values.get("messages", [])),
        "task_state": _to_plain(task_state),
        "intent": _intent_to_plain(values.get("intent")) or _task_type_to_intent(task_state),
        "normalized_filters": _to_plain(task_state.normalized_filters),
        "missing_slots": _to_plain(task_state.pending_requirements),
        "last_result_summary": _to_plain(task_state.last_result_summary),
        "selected_tool": _to_plain(task_state.selected_tool),
        "action": _to_plain(task_state.action),
        "answer_summary": _to_plain(task_state.answer_summary),
    }
    return payload


def _intent_to_plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _to_plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_plain(item) for key, item in value.items()}
    return value


def _coerce_task_state(value: Any) -> TaskState:
    if isinstance(value, TaskState):
        return value
    if isinstance(value, dict):
        return TaskState(**value)
    return TaskState()


def _task_type_to_intent(task_state: TaskState) -> Any:
    """给调试面板提供一个兼容旧前端字段的意图映射。

    这里是“展示兼容层”，不是新的业务真相来源。
    真正的核心状态仍然是 task_state。
    """

    task_type = task_state.task_type
    if task_type is None:
        return None
    if str(task_type.value) == "CREATOR_COMMISSION":
        return "QUERY_CREATOR_SUMMARY"
    if str(task_type.value) == "MEDIA_COMMISSION_STATUS":
        return "QUERY_MEDIA_COMMISSION_STATUS"
    if str(task_type.value) == "MEDIA_NO_COMMISSION_REASON":
        return "QUERY_MEDIA_NO_COMMISSION_REASON"
    if str(task_type.value) == "ORDER_TRANSFER_STATUS":
        return "QUERY_ORDER_TRANSFER_STATUS"
    if str(task_type.value) == "TERM_EXPLAIN":
        return "EXPLAIN_BUSINESS_TERM"
    return "UNKNOWN"
