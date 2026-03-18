"""NLU 工厂。"""

from __future__ import annotations

from app.application.nlu.base import BaseNLU
from app.application.nlu.llm_based import LLMBasedNLU
from app.config.settings import Settings, get_settings


class NLUFactory:
    """始终返回 LLM NLU。

    当前项目只保留一套 NLU 实现，这里不再做多实现切换。
    """

    @staticmethod
    def create(settings: Settings | None = None) -> BaseNLU:
        """返回 LLM NLU 实例。"""
        current = settings or get_settings()
        return LLMBasedNLU(settings=current)
