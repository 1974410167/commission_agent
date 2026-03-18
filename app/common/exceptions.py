"""项目内统一异常定义。"""

from __future__ import annotations


class LLMServiceError(RuntimeError):
    """表示 LLM 相关调用失败，应该直接暴露给上层。"""

    pass
