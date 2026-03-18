"""NLU 抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.application.agent.state import AgentState
from app.domain.intent_models import QueryUnderstanding


class BaseNLU(ABC):
    """workflow 依赖的最小 NLU 接口。"""

    mode_name = "llm_based"

    @abstractmethod
    def understand_query(self, state: AgentState) -> QueryUnderstanding:
        """一次性完成 turn_type / task_type / slots 理解。"""
        raise NotImplementedError
