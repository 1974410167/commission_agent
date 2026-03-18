"""FastAPI 层使用的请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.domain.intent_models import ChatResponse


class ChatRequest(BaseModel):
    """`/api/chat` 的请求体。"""

    conversation_id: str
    message: str
    user_role: Literal["creator", "operator"]
    bound_creator_id: int | None = None


class HealthResponse(BaseModel):
    """健康检查接口响应。"""

    status: str


class ChatAPIResponse(ChatResponse):
    """聊天接口最终响应模型。"""

    pass


class ResetChatRequest(BaseModel):
    """重置会话接口的请求体。"""

    conversation_id: str


class ResetChatResponse(BaseModel):
    """重置会话后的简单确认响应。"""

    status: str
