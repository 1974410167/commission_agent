"""任务态模型。

这里把“当前会话正在处理什么任务”单独抽出来，避免继续把：
- 单轮用户输入理解
- 会话级任务状态
- 工具执行计划

混在同一批零散字段里。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    """会话当前正在处理的任务类型。

    注意这里不是“单轮输入动作类型”，也不是最终路由后的 tool 名。
    它描述的是：当前会话到底在查哪一类业务问题。

    可以把它理解成“任务的大类”：
    - `CREATOR_COMMISSION` 表示“达人分佣任务”
    - 但这个任务后续既可能走“普通汇总”，也可能走“按视频展开”
    - 这些执行差异不应该再污染 task_type，而应该交给 planner 决定

    这样做的核心目的是把：
    - 用户这句话说了什么
    - 当前会话正在处理什么任务
    - 这一轮到底怎么执行
    拆成三个层次，避免一个 intent 混管全部语义。
    """

    CREATOR_COMMISSION = "CREATOR_COMMISSION"
    MEDIA_COMMISSION_STATUS = "MEDIA_COMMISSION_STATUS"
    MEDIA_NO_COMMISSION_REASON = "MEDIA_NO_COMMISSION_REASON"
    ORDER_TRANSFER_STATUS = "ORDER_TRANSFER_STATUS"
    TERM_EXPLAIN = "TERM_EXPLAIN"
    UNKNOWN = "UNKNOWN"


class TaskStatus(str, Enum):
    """任务态当前所处的状态。

    这里刻意只保留很少的几个状态，避免把状态机做成难维护的大泥球：
    - READY: 任务信息已齐，可以进入 planner / tool 执行
    - CLARIFYING: 当前任务明确，但缺关键参数，需要继续追问
    - UNSUPPORTED: 当前输入无法形成系统支持的合法任务
    """

    READY = "READY"
    CLARIFYING = "CLARIFYING"
    UNSUPPORTED = "UNSUPPORTED"


class TaskState(BaseModel):
    """当前会话的唯一业务真相。

    这是现在整套 Agent 最重要的对象。理解它时可以记住一句话：
    “用户历史原文是线索，TaskState 才是业务真相。”

    也就是说：
    - 历史消息可以帮助 LLM 理解语义
    - 但真正决定下一轮如何继承、如何路由、如何追问的，不再是历史原文
    - 而是这里这份结构化任务态
    """

    task_type: TaskType | None = None
    status: TaskStatus = TaskStatus.READY
    # 这是当前任务已经沉淀下来的过滤条件。
    # 它不是“本轮临时抽出来的 slots”，而是跨轮保留下来的任务上下文。
    normalized_filters: dict[str, Any] = Field(default_factory=dict)
    # 当前任务还缺哪些关键字段，例如 media_id / shop_order_id。
    # 当这里非空时，状态机会进入 CLARIFYING，而不是直接执行工具。
    pending_requirements: list[str] = Field(default_factory=list)
    # selected_tool 表示上一轮 planner 产出的工具决策，用于 debug 和上下文说明。
    # 它不应反向决定 task_type，避免再形成“工具决定任务”的倒挂关系。
    selected_tool: str | None = None
    # action / last_result_summary / answer_summary 都属于“上一轮结果摘要”。
    # 它们可以帮助调试和后续表达，但不应该成为业务判断的主依据。
    action: str | None = None
    last_result_summary: str | None = None
    answer_summary: str | None = None
