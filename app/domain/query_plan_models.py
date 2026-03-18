"""执行计划模型。

QueryPlan 负责把任务态翻译成“这一轮应该调用什么工具、按什么模式执行”，
从而避免继续让 graph 直接用 intent 硬路由工具。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.domain.intent_models import AgentIntent


class QueryPlanMode(str, Enum):
    """执行计划类型。

    注意这层已经不是“任务是什么”，而是“这一轮怎么执行”：
    - `ES_ONLY` 只查结构化事实
    - `KNOWLEDGE_ONLY` 只做知识解释
    - `HYBRID` 先拿事实，再补规则说明
    - `UNSUPPORTED` 说明当前任务态还无法生成合法执行计划
    """

    ES_ONLY = "es_only"
    KNOWLEDGE_ONLY = "knowledge_only"
    HYBRID = "hybrid"
    UNSUPPORTED = "unsupported"


class QueryPlan(BaseModel):
    """当前轮的执行计划。

    这层专门回答“怎么查”，而不是“查什么”。

    举个例子：
    - `task_type = CREATOR_COMMISSION` 只是说明当前任务属于达人分佣查询
    - 但这一轮到底是普通汇总、按视频展开，还是来源类型对比
    - 需要由 QueryPlan 决定

    这也是把状态机做稳的关键：
    - TaskState 保持稳定
    - QueryPlan 允许灵活变化
    """

    mode: QueryPlanMode
    tool_name: str | None = None
    # response_intent 仍然保留，是为了兼容现有响应协议和前端展示。
    # 它更接近“对外呈现意图”，而不是状态机内部的任务大类。
    response_intent: AgentIntent = AgentIntent.UNKNOWN
    filters: dict[str, Any] = Field(default_factory=dict)
    needs_rule_explanation: bool = False
    response_style: str | None = None
