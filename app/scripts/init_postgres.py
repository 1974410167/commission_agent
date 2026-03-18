"""初始化 LangGraph PostgreSQL checkpointer 所需的表结构。"""

from __future__ import annotations

from app.application.agent.checkpointer import get_agent_checkpointer
from app.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    checkpointer = get_agent_checkpointer(settings)
    print("PostgreSQL initialized.")
    print(f"backend: {settings.conversation_store_backend}")
    print(f"dsn: {settings.postgres_dsn}")
    print(f"checkpointer: {type(checkpointer).__name__}")


if __name__ == "__main__":
    main()
