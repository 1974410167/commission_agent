"""LangGraph 工作流编排入口。

这张图现在是一个“受控状态机”，而不是自由循环的 ReAct Agent。

主链路可以概括成：
1. understand_query: LLM 理解本轮用户输入
2. reduce_state: 把上一轮任务态和本轮理解结果合成新的 task_state
3. normalize_and_validate: 做确定性归一化、权限校验、缺参判断
4. 条件分支：
   - 缺参 -> clarify
   - 不支持 -> compose_answer
   - 可执行 -> build_query_plan -> execute_tool -> compose_answer

这样设计的目的，是把“语义理解”和“状态转移”拆开，避免过去那种：
- 线性流水线
- 节点里到处短路
- 历史快照和当前 state 混着判断
"""

from __future__ import annotations

from functools import lru_cache
from time import perf_counter
from typing import Callable

from langgraph.graph import END, START, StateGraph

from app.application.agent.checkpointer import get_agent_checkpointer
from app.application.agent.nodes import (
    build_query_plan_node,
    clarify_if_needed,
    compose_answer,
    reduce_state,
    execute_tool,
    normalize_and_validate,
    understand_query,
)
from app.application.agent.state import AgentState
from app.common.logging_utils import get_agent_logger


agent_logger = get_agent_logger()


@lru_cache(maxsize=1)
def get_agent_workflow():
    """编译一次 workflow，供 API 和脚本复用。

    这里直接挂 LangGraph 官方 checkpointer，因此：
    - graph state 本身就是唯一持久化真相
    - 不再需要额外的 load/save conversation 节点
    """

    graph = StateGraph(AgentState)
    graph.add_node("understand_query", _instrument_node("understand_query", understand_query))
    graph.add_node("reduce_state", _instrument_node("reduce_state", reduce_state))
    graph.add_node("normalize_and_validate", _instrument_node("normalize_and_validate", normalize_and_validate))
    graph.add_node("clarify_if_needed", _instrument_node("clarify_if_needed", clarify_if_needed))
    graph.add_node("build_query_plan", _instrument_node("build_query_plan", build_query_plan_node))
    graph.add_node("execute_tool", _instrument_node("execute_tool", execute_tool))
    graph.add_node("compose_answer", _instrument_node("compose_answer", compose_answer))

    # 每一轮请求都会从 START 重新执行整张图；
    # 但真正的上下文会由 checkpointer 在 invoke 前自动恢复。
    graph.add_edge(START, "understand_query")
    graph.add_edge("understand_query", "reduce_state")
    graph.add_edge("reduce_state", "normalize_and_validate")
    graph.add_conditional_edges(
        "normalize_and_validate",
        _after_normalize,
        {
            "clarify": "clarify_if_needed",
            "route": "build_query_plan",
            "unsupported": "compose_answer",
        },
    )
    graph.add_edge("clarify_if_needed", END)
    graph.add_conditional_edges(
        "build_query_plan",
        _after_route_tool,
        {
            "execute": "execute_tool",
            "unsupported": "compose_answer",
        },
    )
    graph.add_edge("execute_tool", "compose_answer")
    graph.add_edge("compose_answer", END)
    return graph.compile(checkpointer=get_agent_checkpointer())


def _after_normalize(state: AgentState) -> str:
    """根据校验结果决定走 clarify / route / unsupported 哪条路径。"""

    route_status = state.get("route_status")
    if route_status == "clarify":
        return "clarify"
    if route_status == "unsupported":
        return "unsupported"
    return "route"


def _after_route_tool(state: AgentState) -> str:
    """planner 产出执行计划后，只保留 execute 或 unsupported 两种流向。"""

    return "execute" if state.get("route_status") == "execute" else "unsupported"


def _instrument_node(name: str, fn: Callable[[AgentState], AgentState]) -> Callable[[AgentState], AgentState]:
    """给每个 LangGraph 节点补统一日志和 trace。

    状态机一旦复杂起来，最怕“链路走偏却不知道是哪一层偏了”。
    这里统一记录：
    - 节点名
    - 耗时
    - 关键信息摘要

    这样调试时就能看清：
    - 是 LLM 理解错了
    - 还是 reducer 转错了
    - 或者 planner / tool / compose_answer 出了问题
    """

    def wrapped(state: AgentState) -> AgentState:
        conversation_id = state.get("conversation_id", "-")
        start = perf_counter()
        agent_logger.info("node_start | conversation_id=%s | node=%s", conversation_id, name)
        try:
            updates = fn(state) or {}
        except Exception:
            duration_ms = round((perf_counter() - start) * 1000, 2)
            agent_logger.exception(
                "node_error | conversation_id=%s | node=%s | duration_ms=%s",
                conversation_id,
                name,
                duration_ms,
            )
            raise

        duration_ms = round((perf_counter() - start) * 1000, 2)
        trace_entry = {
            "node": name,
            "status": "ok",
            "duration_ms": duration_ms,
            "summary": _summarize_node_result(name, updates),
        }
        node_logs = [*state.get("node_logs", []), trace_entry]
        agent_logger.info(
            "node_finish | conversation_id=%s | node=%s | duration_ms=%s | summary=%s",
            conversation_id,
            name,
            duration_ms,
            trace_entry["summary"],
        )
        merged_updates = dict(updates)
        merged_updates["node_logs"] = node_logs
        return merged_updates

    return wrapped


def _summarize_node_result(name: str, updates: AgentState) -> str:
    """把节点输出压缩成适合日志和 debug 面板阅读的一句话。"""

    if not updates:
        return "no_state_change"
    if name == "understand_query" and updates.get("understanding") is not None:
        understanding = updates["understanding"]
        slots = understanding.slots.model_dump(exclude_none=True)
        return (
            f"turn_type={understanding.turn_type.value}, "
            f"entity_scope={understanding.entity_scope.value if understanding.entity_scope else None}, "
            f"goal_type={understanding.goal_type.value if understanding.goal_type else None}, "
            f"task_type={understanding.task_type.value if understanding.task_type else None}, "
            f"slots={slots or 'empty'}"
        )
    if name == "reduce_state" and updates.get("task_state") is not None:
        task_state = updates["task_state"]
        task_type = getattr(task_state.task_type, "value", task_state.task_type)
        return (
            f"task_type={task_type}, status={getattr(task_state.status, 'value', task_state.status)}, "
            f"filters={task_state.normalized_filters or {}}"
        )
    if name == "normalize_and_validate":
        normalized = updates.get("normalized_filters")
        missing = updates.get("missing_slots")
        return f"route_status={updates.get('route_status')}, normalized_filters={normalized}, missing_slots={missing or []}"
    if name == "clarify_if_needed":
        return f"clarify_question={updates.get('clarify_question')}"
    if name == "build_query_plan":
        plan = updates.get("query_plan")
        return (
            f"route_status={updates.get('route_status')}, "
            f"selected_tool={updates.get('selected_tool')}, "
            f"response_intent={getattr(plan.response_intent, 'value', None) if plan else None}"
        )
    if name == "execute_tool":
        result = updates.get("tool_result")
        return f"tool_result_type={type(result).__name__}" if result is not None else "tool_result=empty"
    if name == "compose_answer" and updates.get("response") is not None:
        response = updates["response"]
        return f"action={response.action}, evidence_count={len(response.evidence)}"
    return f"updated_keys={sorted(updates.keys())}"
