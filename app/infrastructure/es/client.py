"""Elasticsearch 客户端创建入口。"""

from __future__ import annotations

from elasticsearch import Elasticsearch

from app.config.settings import Settings


def create_es_client(settings: Settings) -> Elasticsearch:
    """根据环境配置创建 ES 客户端。"""
    kwargs: dict[str, object] = {
        "hosts": [settings.es_url],
        "verify_certs": settings.es_verify_certs,
        "request_timeout": 30,
    }
    if settings.es_username:
        kwargs["basic_auth"] = (settings.es_username, settings.es_password)
    return Elasticsearch(**kwargs)
