"""OpenAI 兼容客户端封装。

当前项目通过这一层统一对接多种 OpenAI 兼容 provider：
- 本地 `llama-server`
- 阿里百炼兼容接口
- 智谱 OpenAI 兼容接口

职责边界：
- chat 用于 NLU 和知识回答润色；
- embeddings 用于 markdown 向量化；
- provider 切换在 `Settings` 中完成，这一层只消费“当前已经选好的配置”。
"""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from app.common.exceptions import LLMServiceError
from app.application.llm.models import ChatCompletionPayload, EmbeddingPayload, LLMMessage
from app.application.llm.provider import ProviderConfig
from app.config.settings import Settings, get_settings


class OpenAICompatibleClient:
    """对 OpenAI SDK 做一层薄封装，并拆分 chat / embedding 配置。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """仅在配置完整时创建对应客户端。"""
        self.settings = settings or get_settings()
        self.provider = ProviderConfig.from_settings(self.settings)
        self.chat_enabled = self.provider.chat_enabled
        self.embedding_enabled = self.provider.embedding_enabled
        self.enabled = bool(self.chat_enabled or self.embedding_enabled)
        self.chat_client = (
            OpenAI(
                api_key=self.provider.chat_api_key,
                base_url=self.provider.chat_base_url,
                timeout=60.0,
                max_retries=0,
            )
            if self.chat_enabled
            else None
        )
        self.embedding_client = (
            OpenAI(
                api_key=self.provider.embedding_api_key,
                base_url=self.provider.embedding_base_url,
                timeout=20.0,
                max_retries=0,
            )
            if self.embedding_enabled
            else None
        )

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 600,
        response_format: dict[str, Any] | None = None,
        raise_on_error: bool = False,
    ) -> ChatCompletionPayload | None:
        """执行 chat 请求。

        默认仍然允许调用方自行决定如何处理失败；
        但 NLU 路径会显式要求 `raise_on_error=True`，避免把失败伪装成业务结果。
        """
        if not self.chat_enabled or self.chat_client is None:
            if raise_on_error:
                raise LLMServiceError("LLM chat client is not configured.")
            return None
        try:
            response = self._create_chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
            content = response.choices[0].message.content or ""
            return ChatCompletionPayload(
                content=content,
                model=self.provider.chat_model,
                raw=response.model_dump(),
            )
        except Exception as exc:
            if raise_on_error:
                raise LLMServiceError(f"LLM chat request failed: {exc.__class__.__name__}: {exc}") from exc
            return None

    def _create_chat_completion(
        self,
        *,
        messages: list[LLMMessage],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None,
    ) -> Any:
        """创建 chat completion，并兼容不支持 `response_format` 的模型。

        例如部分火山引擎模型虽然兼容 OpenAI chat 接口，
        但不支持 `response_format={"type":"json_object"}`。
        这时不应该整条链路失败，而是退回到“仅靠 prompt 约束输出 JSON”。
        """
        request_payload: dict[str, Any] = {
            "model": self.provider.chat_model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            request_payload["response_format"] = response_format
        try:
            return self.chat_client.chat.completions.create(**request_payload)
        except Exception as exc:
            if response_format is not None and self._response_format_unsupported(exc):
                request_payload.pop("response_format", None)
                return self.chat_client.chat.completions.create(**request_payload)
            raise

    @staticmethod
    def _response_format_unsupported(exc: Exception) -> bool:
        """判断异常是否明确表示当前模型不支持 `response_format`。"""
        message = str(exc).lower()
        return "response_format.type" in message and "not supported" in message

    def embeddings(self, texts: list[str]) -> EmbeddingPayload | None:
        """执行一批文本的 embedding 请求。"""
        if not self.embedding_enabled or self.embedding_client is None or not texts:
            return None
        try:
            response = self.embedding_client.embeddings.create(
                model=self.provider.embedding_model,
                input=texts,
            )
            vectors = [item.embedding for item in response.data]
            return EmbeddingPayload(vectors=vectors, model=self.provider.embedding_model)
        except Exception:
            return None
