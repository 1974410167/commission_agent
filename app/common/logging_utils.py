"""项目统一日志配置。

目标很明确：
1. FastAPI / uvicorn 日志落到 `logs/api.log`
2. Agent workflow 节点日志落到 `logs/agent.log`
3. 控制台仍保留输出，方便本地直接看进程日志
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config.settings import get_settings


_CONFIGURED = False


def configure_project_logging() -> None:
    """初始化项目日志。

    这里不直接改 root logger，避免把第三方库的所有日志都拉进来。
    我们只关心三类输出：
    - `commission_agent.api`
    - `commission_agent.agent`
    - `uvicorn.error` / `uvicorn.access`
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    api_file_handler = RotatingFileHandler(
        settings.api_log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    api_file_handler.setFormatter(formatter)

    agent_file_handler = RotatingFileHandler(
        settings.agent_log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    agent_file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    _bind_handlers("commission_agent.api", [console_handler, api_file_handler])
    _bind_handlers("commission_agent.agent", [console_handler, agent_file_handler])
    _bind_handlers("uvicorn.error", [console_handler, api_file_handler])
    _bind_handlers("uvicorn.access", [console_handler, api_file_handler])

    _CONFIGURED = True


def get_api_logger() -> logging.Logger:
    """返回 API 层 logger。"""
    configure_project_logging()
    return logging.getLogger("commission_agent.api")


def get_agent_logger() -> logging.Logger:
    """返回 Agent workflow logger。"""
    configure_project_logging()
    return logging.getLogger("commission_agent.agent")


def _bind_handlers(logger_name: str, handlers: list[logging.Handler]) -> None:
    """把 handler 绑定到指定 logger，并避免重复绑定。"""
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()
    for handler in handlers:
        logger.addHandler(handler)
