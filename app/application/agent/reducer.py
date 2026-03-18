"""任务态 reducer。

这层不依赖 ES / RAG / prompt，只做确定性的状态转移：
- 上一轮 task_state 是什么
- 这一轮 LLM 理解结果是什么
- 合并后下一轮 task_state 应该是什么
"""

from __future__ import annotations

from typing import Any

from app.domain.intent_models import CommissionQuerySlots, QueryUnderstanding, TurnType
from app.domain.task_state_models import TaskState, TaskType


def reduce_task_state(previous_task_state: TaskState | None, understanding: QueryUnderstanding) -> TaskState:
    """根据上一轮任务态和本轮理解结果，产出新的任务态。

    reducer 是当前状态机最关键的“状态转移器”：
    - LLM 负责理解这句话在说什么
    - reducer 负责决定会话状态应该怎么变

    这层故意不调 ES / RAG / 任何工具，也不再依赖正则补丁。
    它只做确定性状态转移，保证 follow-up / clarify 的继承逻辑可解释、可调试。
    """

    previous = previous_task_state or TaskState()
    current_slots = _non_empty_slots(understanding.slots)

    if understanding.turn_type == TurnType.EXPLAIN:
        # explain 属于一类独立任务，不应该继承上一轮业务查询 filters，
        # 否则会出现“解释术语却带着 creator_id / media_id”这类状态污染。
        return TaskState(
            task_type=TaskType.TERM_EXPLAIN,
            normalized_filters=current_slots,
        )

    if understanding.turn_type == TurnType.UNSUPPORTED:
        # 当 LLM 无法形成合法理解时，不要凭空造一个新任务。
        # 最稳的做法是保留上一轮任务态，等待用户下一轮重新澄清。
        return TaskState(
            task_type=previous.task_type or TaskType.UNKNOWN,
            status=previous.status,
            normalized_filters=dict(previous.normalized_filters),
            pending_requirements=list(previous.pending_requirements),
            selected_tool=previous.selected_tool,
            action=previous.action,
            last_result_summary=previous.last_result_summary,
            answer_summary=previous.answer_summary,
        )

    if understanding.turn_type == TurnType.NEW_QUERY:
        # 新问题意味着重建任务态。
        # 这里会丢掉上一轮任务 filters，避免老任务上下文污染新问题。
        return TaskState(
            task_type=understanding.task_type,
            normalized_filters=current_slots,
        )

    if understanding.turn_type in {TurnType.MODIFY_FILTERS, TurnType.ANSWER_CLARIFY}:
        # 这两类场景都不应该轻易切换任务大类：
        # - MODIFY_FILTERS: 只是改时间、来源、分佣条件等过滤项
        # - ANSWER_CLARIFY: 只是补上当前任务缺失的关键参数
        #
        # 这里的关键约束是：
        # - 一旦会话已经进入某个明确 task_type，
        #   follow-up 和 clarify 默认都优先继承该 task_type；
        # - 不允许 LLM 因为一条短输入（如 `media_id: 990041` 或 `只看最近7天`）
        #   就把任务从“视频分佣状态”扭到“视频不可分佣原因”或“达人汇总”。
        #
        # 这不是规则 patch，而是状态机本身的稳定性约束：
        # - LLM 负责理解本轮动作和槽位
        # - reducer 负责决定任务是否允许切换
        inherited_task_type = previous.task_type if previous.task_type not in (None, TaskType.UNKNOWN) else understanding.task_type
        return TaskState(
            task_type=inherited_task_type or TaskType.UNKNOWN,
            normalized_filters={**previous.normalized_filters, **current_slots},
            pending_requirements=list(previous.pending_requirements),
            selected_tool=previous.selected_tool,
            action=previous.action,
            last_result_summary=previous.last_result_summary,
            answer_summary=previous.answer_summary,
        )

    # 理论上不应走到这里；保守起见仍保持上一轮任务态，避免状态机抖动。
    return TaskState(
        task_type=previous.task_type or TaskType.UNKNOWN,
        normalized_filters=dict(previous.normalized_filters),
        pending_requirements=list(previous.pending_requirements),
        selected_tool=previous.selected_tool,
        action=previous.action,
        last_result_summary=previous.last_result_summary,
        answer_summary=previous.answer_summary,
    )


def _non_empty_slots(slots: CommissionQuerySlots) -> dict[str, Any]:
    """丢掉 None / 空列表 / 空字典等无效槽位，避免把“没提到”误写成覆盖。"""

    return {
        key: value
        for key, value in slots.model_dump().items()
        if value not in (None, [], {}, "", "none")
    }
