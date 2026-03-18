"""LangGraph 节点之间共享的状态定义。

这里把状态分成两类：

1. 持久化任务态
   这部分会跟随 LangGraph checkpointer 一起跨请求保存，
   表示“当前会话正在处理什么任务、已经积累了哪些上下文”。

2. 单轮执行态
   这部分只服务当前一次 `/api/chat` 调用，用来承接 NLU、路由、
   tool 结果、调试 trace 等临时信息。

这样做的目的，是避免把“上一轮回答内容”误当成“下一轮业务判断依据”，
同时也不再依赖额外的 ConversationStore / history snapshot。
"""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict

from app.domain.agent_models import ConversationMessage, UserContext
from app.domain.intent_models import AgentIntent, ChatResponse, CommissionQuerySlots, QueryUnderstanding
from app.domain.query_plan_models import QueryPlan
from app.domain.task_state_models import TaskState


class AgentState(TypedDict, total=False):
    """workflow 节点间传递的状态容器。

    这里有意保持“宽松但可读”：
    - 便于逐节点增量写入字段；
    - 避免过早做过重抽象；
    - 同时给每个状态字段一个明确语义。
    """

    # 当前请求的基础输入。
    conversation_id: str
    message: str
    user_context: UserContext

    # 持久化任务态：由 checkpointer 自动跨请求保存。
    # 这部分是“跨轮可继承的业务真相”，下一轮会从 PostgreSQL 恢复。
    messages: list[ConversationMessage]
    task_state: TaskState

    # 单轮执行态：仅服务本轮图执行。
    # 它们不应被下一轮直接拿来做主判断，因此每次新请求都会被主动清空或覆盖。
    understanding: QueryUnderstanding
    intent: AgentIntent
    nlu_mode: str
    slots: CommissionQuerySlots
    llm_call_count: int
    normalized_filters: dict[str, Any]
    missing_slots: list[str]
    clarify_question: str
    selected_tool: str | None
    query_plan: QueryPlan
    route_status: str
    error_message: str
    node_logs: list[dict[str, Any]]
    tool_result: Any
    rule_explanation: Any
    evidence: list[Any]
    action: str
    answer: str
    answer_summary: str
    last_result_summary: str
    next_suggestions: list[str]
    debug: dict[str, Any]
    response: ChatResponse


PERSISTED_STATE_KEYS = ("conversation_id", "messages", "task_state")


def build_turn_input(conversation_id: str, message: str, user_context: UserContext) -> AgentState:
    """构造新一轮 invoke 的输入，并主动清空会被上一轮污染的临时字段。

    checkpointer 会恢复上一轮完整 state，所以每次新请求都要显式覆盖这些
    “只属于单轮执行”的字段，否则旧的 tool_result / node_logs / answer
    可能泄漏到本轮判断中。

    这里的设计重点是：
    - 不去手工 load/save 会话快照
    - 只告诉 graph“新一轮输入是什么”
    - 其余可持久化字段交给 checkpointer 自动恢复
    """

    return {
        "conversation_id": conversation_id,
        "message": message,
        "user_context": user_context,
        "node_logs": [],
        "llm_call_count": 0,
        "route_status": "",
        "clarify_question": "",
        "tool_result": None,
        "rule_explanation": None,
        "evidence": [],
        "answer": "",
        "selected_tool": None,
        "query_plan": None,
        "next_suggestions": [],
    }
