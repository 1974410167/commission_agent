"""模型提供商配置对象。

这里不直接做环境变量解析，而是消费 `Settings` 已经计算好的“当前生效配置”。
这样 provider 层不需要知道：
- 当前是 local / bailian / zhipu 的哪一种；
- 是否用了 `CHAT_*` / `EMBEDDING_*` 的显式覆盖；
- 是否沿用了前面阶段的旧变量名。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings, get_settings


@dataclass(frozen=True)
class ProviderConfig:
    """把全局 Settings 收敛成 provider 侧更好消费的配置结构。"""

    provider: str
    embedding_provider: str
    chat_base_url: str
    chat_api_key: str
    chat_model: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    chat_enabled: bool
    embedding_enabled: bool

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "ProviderConfig":
        """从全局配置构造 provider 配置。"""
        current = settings or get_settings()
        return cls(
            provider=current.model_provider,
            embedding_provider=current.embedding_provider,
            chat_base_url=current.chat_base_url,
            chat_api_key=current.chat_api_key,
            chat_model=current.chat_model,
            embedding_base_url=current.embedding_base_url,
            embedding_api_key=current.embedding_api_key,
            embedding_model=current.embedding_model,
            chat_enabled=current.chat_enabled,
            embedding_enabled=current.embedding_enabled,
        )
