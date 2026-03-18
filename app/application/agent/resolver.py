"""语义维度到 TaskType 的确定性映射。

这里专门解决一个问题：
- LLM 很擅长理解“在问谁、想知道什么”
- 但不适合直接拍板系统内部最终 task_type

因此我们先让模型输出：
- entity_scope
- goal_type

再由后端把它们映射成系统支持的任务类型。
"""

from __future__ import annotations

from app.domain.intent_models import EntityScope, GoalType, QueryUnderstanding, TurnType
from app.domain.task_state_models import TaskType


def resolve_task_type(understanding: QueryUnderstanding) -> TaskType | None:
    """把 LLM 输出的语义维度收敛成系统任务类型。"""

    entity_scope = understanding.entity_scope
    goal_type = understanding.goal_type

    if understanding.turn_type == TurnType.EXPLAIN:
        return TaskType.TERM_EXPLAIN

    if entity_scope == EntityScope.CREATOR and goal_type in {GoalType.SUMMARY, GoalType.COMPARE}:
        return TaskType.CREATOR_COMMISSION

    if entity_scope == EntityScope.MEDIA and goal_type == GoalType.STATUS:
        return TaskType.MEDIA_COMMISSION_STATUS

    if entity_scope == EntityScope.MEDIA and goal_type == GoalType.REASON:
        return TaskType.MEDIA_NO_COMMISSION_REASON

    if entity_scope == EntityScope.ORDER and goal_type == GoalType.STATUS:
        return TaskType.ORDER_TRANSFER_STATUS

    if entity_scope == EntityScope.TERM and goal_type == GoalType.EXPLAIN:
        return TaskType.TERM_EXPLAIN

    return TaskType.UNKNOWN
