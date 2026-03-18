"""LLM 客户端使用的输入输出模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """一条 OpenAI 兼容格式的消息。"""

    role: str
    content: str


class ChatCompletionPayload(BaseModel):
    """标准化后的 chat 返回结果。"""

    content: str
    model: str
    raw: dict = Field(default_factory=dict)


class EmbeddingPayload(BaseModel):
    """标准化后的 embedding 返回结果。"""

    vectors: list[list[float]]
    model: str
