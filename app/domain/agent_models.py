"""Agent 会话相关模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator


class UserContext(BaseModel):
    """调用方身份信息。

    这里不做真实登录，但通过 `user_role + bound_creator_id`
    来模拟后端权限边界。
    """

    user_role: Literal["creator", "operator"]
    bound_creator_id: int | None = None

    @model_validator(mode="after")
    def validate_creator_binding(self) -> "UserContext":
        """creator 模式必须绑定 creator_id，否则后续权限判断没有锚点。"""
        if self.user_role == "creator" and self.bound_creator_id is None:
            raise ValueError("bound_creator_id is required when user_role=creator")
        return self


class ConversationMessage(BaseModel):
    """会话中的一条消息。"""

    role: Literal["user", "assistant"]
    content: str
