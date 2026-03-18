"""项目统一配置入口。

所有 ES / LLM / RAG / Web Demo 的运行参数都从这里读取。
这层现在额外承担一件事：把“多 provider 切换”收口在一个地方。

当前支持：
- `MODEL_PROVIDER=local`
- `MODEL_PROVIDER=bailian`
- `MODEL_PROVIDER=zhipu`
- `MODEL_PROVIDER=volcengine`

设计原则：
- chat provider 由 `MODEL_PROVIDER` 决定；
- embedding provider 由 `EMBEDDING_PROVIDER` 决定；
- 若显式设置 `CHAT_*` / `EMBEDDING_*`，则优先使用显式覆盖值；
- 这样切 provider 时通常只需要改 provider 名，不需要手改整套 URL / key / model。
- 会话存储 backend 也在这里统一收口，避免节点层自己拼 DSN。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    """把环境变量里的字符串解析成布尔值。"""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """运行期解析后的不可变配置对象。"""

    model_provider: str = os.getenv("MODEL_PROVIDER", "local").strip().lower()
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "bailian").strip().lower()

    # 兼容前面阶段已经使用过的旧变量名。若新变量未配置，会退回这组默认值。
    openai_compatible_base_url: str = os.getenv(
        "OPENAI_COMPATIBLE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    openai_compatible_api_key: str = os.getenv("OPENAI_COMPATIBLE_API_KEY", "")

    # 通用覆盖项：只有显式填写时才会覆盖 provider 预设。
    chat_base_url_override: str = os.getenv("CHAT_BASE_URL", "")
    chat_api_key_override: str = os.getenv("CHAT_API_KEY", "")
    chat_model_override: str = os.getenv("CHAT_MODEL", "")
    embedding_base_url_override: str = os.getenv("EMBEDDING_BASE_URL", "")
    embedding_api_key_override: str = os.getenv("EMBEDDING_API_KEY", "")
    embedding_model_override: str = os.getenv("EMBEDDING_MODEL", "")

    # Bailian 预设
    bailian_base_url: str = os.getenv(
        "BAILIAN_BASE_URL",
        os.getenv("OPENAI_COMPATIBLE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    bailian_api_key: str = os.getenv("BAILIAN_API_KEY", os.getenv("OPENAI_COMPATIBLE_API_KEY", ""))
    bailian_chat_model: str = os.getenv("BAILIAN_CHAT_MODEL", "qwen3.5-flash")
    bailian_embedding_model: str = os.getenv("BAILIAN_EMBEDDING_MODEL", "text-embedding-v4")

    # Zhipu 预设
    zhipu_base_url: str = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    zhipu_api_key: str = os.getenv("ZHIPU_API_KEY", "")
    zhipu_chat_model: str = os.getenv("ZHIPU_CHAT_MODEL", "glm-4.7")
    zhipu_embedding_base_url: str = os.getenv("ZHIPU_EMBEDDING_BASE_URL", os.getenv("ZHIPU_BASE_URL", ""))
    zhipu_embedding_api_key: str = os.getenv("ZHIPU_EMBEDDING_API_KEY", os.getenv("ZHIPU_API_KEY", ""))
    zhipu_embedding_model: str = os.getenv("ZHIPU_EMBEDDING_MODEL", "")

    # Volcano Engine / Ark 预设
    volcengine_base_url: str = os.getenv("VOLCENGINE_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
    volcengine_api_key: str = os.getenv("VOLCENGINE_API_KEY", "")
    volcengine_chat_model: str = os.getenv("VOLCENGINE_CHAT_MODEL", "DeepSeek-V3.2")
    volcengine_embedding_base_url: str = os.getenv("VOLCENGINE_EMBEDDING_BASE_URL", "")
    volcengine_embedding_api_key: str = os.getenv("VOLCENGINE_EMBEDDING_API_KEY", "")
    volcengine_embedding_model: str = os.getenv("VOLCENGINE_EMBEDDING_MODEL", "")

    # 本地 llama.cpp server 预设
    local_chat_base_url: str = os.getenv("LOCAL_CHAT_BASE_URL", "http://127.0.0.1:18080/v1")
    local_chat_api_key: str = os.getenv("LOCAL_CHAT_API_KEY", "local-llm")
    local_chat_model: str = os.getenv("LOCAL_CHAT_MODEL", "qwen-local")

    llm_enabled: bool = _get_bool("LLM_ENABLED", True)
    rag_enabled: bool = _get_bool("RAG_ENABLED", True)
    app_debug: bool = _get_bool("APP_DEBUG", True)
    conversation_store_backend: str = os.getenv("CONVERSATION_STORE_BACKEND", "memory").strip().lower()
    postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_db: str = os.getenv("POSTGRES_DB", "commission_agent")
    postgres_user: str = os.getenv("POSTGRES_USER", "postgres")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    postgres_dsn_override: str = os.getenv("POSTGRES_DSN", "")
    postgres_sslmode: str = os.getenv("POSTGRES_SSLMODE", "disable")
    es_url: str = os.getenv("ES_HOST", os.getenv("COMMISSION_ES_URL", "http://127.0.0.1:9200"))
    es_username: str = os.getenv("ES_USERNAME", os.getenv("COMMISSION_ES_USERNAME", ""))
    es_password: str = os.getenv("ES_PASSWORD", os.getenv("COMMISSION_ES_PASSWORD", ""))
    es_index: str = os.getenv("ES_INDEX", os.getenv("COMMISSION_ES_INDEX", "commission_orders_v1"))
    es_verify_certs: bool = _get_bool("ES_VERIFY_CERTS", _get_bool("COMMISSION_ES_VERIFY_CERTS", False))
    seed: int = int(os.getenv("COMMISSION_SEED", "20260308"))
    project_root: Path = Path(__file__).resolve().parents[2]
    logs_dir: Path = Path(__file__).resolve().parents[2] / "logs"
    api_log_path: Path = Path(__file__).resolve().parents[2] / "logs" / "api.log"
    agent_log_path: Path = Path(__file__).resolve().parents[2] / "logs" / "agent.log"
    knowledge_dir: Path = Path(__file__).resolve().parents[2] / "knowledge"
    knowledge_markdown_path: Path = Path(__file__).resolve().parents[2] / "knowledge" / "rag_knowledge.md"
    knowledge_chunks_path: Path = Path(__file__).resolve().parents[2] / "knowledge" / "chunks.jsonl"
    knowledge_index_meta_path: Path = Path(__file__).resolve().parents[2] / "knowledge" / "index.json"
    knowledge_index_vector_path: Path = Path(__file__).resolve().parents[2] / "knowledge" / "index.npy"

    @property
    def chat_base_url(self) -> str:
        """当前 chat 实际生效的 base URL。"""
        if self.chat_base_url_override:
            return self.chat_base_url_override
        return self._provider_chat_defaults()["base_url"]

    @property
    def chat_api_key(self) -> str:
        """当前 chat 实际生效的 API key。"""
        if self.chat_api_key_override:
            return self.chat_api_key_override
        return self._provider_chat_defaults()["api_key"]

    @property
    def chat_model(self) -> str:
        """当前 chat 实际生效的模型名。"""
        if self.chat_model_override:
            return self.chat_model_override
        return self._provider_chat_defaults()["model"]

    @property
    def embedding_base_url(self) -> str:
        """当前 embedding 实际生效的 base URL。"""
        if self.embedding_base_url_override:
            return self.embedding_base_url_override
        return self._provider_embedding_defaults()["base_url"]

    @property
    def embedding_api_key(self) -> str:
        """当前 embedding 实际生效的 API key。"""
        if self.embedding_api_key_override:
            return self.embedding_api_key_override
        return self._provider_embedding_defaults()["api_key"]

    @property
    def embedding_model(self) -> str:
        """当前 embedding 实际生效的模型名。"""
        if self.embedding_model_override:
            return self.embedding_model_override
        return self._provider_embedding_defaults()["model"]

    @property
    def openai_compatible_enabled(self) -> bool:
        """兼容旧脚本的总开关，本质上等价于当前 chat 是否可用。"""
        return self.chat_enabled

    @property
    def chat_enabled(self) -> bool:
        """当前 chat 配置是否足够完整，可以真正发起对话请求。"""
        return bool(self.llm_enabled and self.chat_api_key and self.chat_base_url and self.chat_model)

    @property
    def embedding_enabled(self) -> bool:
        """当前 embedding 配置是否足够完整，可以真正生成向量。"""
        return bool(self.rag_enabled and self.embedding_api_key and self.embedding_base_url and self.embedding_model)

    @property
    def postgres_dsn(self) -> str:
        """优先用显式 DSN，否则由基础参数组装。"""
        if self.postgres_dsn_override:
            return self.postgres_dsn_override
        return (
            f"host={self.postgres_host} "
            f"port={self.postgres_port} "
            f"dbname={self.postgres_db} "
            f"user={self.postgres_user} "
            f"password={self.postgres_password} "
            f"sslmode={self.postgres_sslmode}"
        )

    def _provider_chat_defaults(self) -> dict[str, str]:
        """根据 `MODEL_PROVIDER` 返回 chat 侧的默认配置。"""
        provider = self.model_provider
        if provider == "local":
            return {
                "base_url": self.local_chat_base_url,
                "api_key": self.local_chat_api_key,
                "model": self.local_chat_model,
            }
        if provider == "zhipu":
            return {
                "base_url": self.zhipu_base_url,
                "api_key": self.zhipu_api_key,
                "model": self.zhipu_chat_model,
            }
        if provider == "volcengine":
            return {
                "base_url": self.volcengine_base_url,
                "api_key": self.volcengine_api_key,
                "model": self.volcengine_chat_model,
            }
        return {
            "base_url": self.bailian_base_url,
            "api_key": self.bailian_api_key,
            "model": self.bailian_chat_model,
        }

    def _provider_embedding_defaults(self) -> dict[str, str]:
        """根据 `EMBEDDING_PROVIDER` 返回 embedding 侧的默认配置。"""
        provider = self.embedding_provider
        if provider == "zhipu":
            return {
                "base_url": self.zhipu_embedding_base_url,
                "api_key": self.zhipu_embedding_api_key,
                "model": self.zhipu_embedding_model,
            }
        if provider == "volcengine":
            return {
                "base_url": self.volcengine_embedding_base_url,
                "api_key": self.volcengine_embedding_api_key,
                "model": self.volcengine_embedding_model,
            }
        if provider == "local":
            return {
                "base_url": "",
                "api_key": "",
                "model": "",
            }
        return {
            "base_url": self.bailian_base_url,
            "api_key": self.bailian_api_key,
            "model": self.bailian_embedding_model,
        }


def get_settings() -> Settings:
    """按需构建配置对象。"""
    return Settings()
