"""Demo 页面和演示脚本使用的样例数据解析器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config.settings import get_settings
from app.infrastructure.es.client import create_es_client
from app.infrastructure.es.repository import CommissionOrderRepository


def resolve_demo_context() -> dict[str, Any]:
    """从 ES 中挑一批真实可用的样例 id。"""
    settings = get_settings()
    repository = CommissionOrderRepository(create_es_client(settings), settings.es_index)
    creator_id = repository.find_recent_creator_id() or 88016
    media_id = repository.find_media_id_with_non_commission() or 990041
    shop_order_id = repository.find_latest_shop_order_id() or "SO-20260308-001127"
    compare = repository.find_creator_with_multiple_source_types()
    compare_creator_id = compare[0] if compare else creator_id
    compare_source_types = list(compare[1]) if compare else [1, 2]
    return {
        "recent_creator_id": creator_id,
        "bound_creator_id": creator_id,
        "recent_media_id": media_id,
        "latest_shop_order_id": shop_order_id,
        "compare_creator_id": compare_creator_id,
        "compare_source_type_a": compare_source_types[0],
        "compare_source_type_b": compare_source_types[1],
    }


def load_sample_conversations() -> list[dict[str, Any]]:
    """加载样例会话，并把占位符替换成真实 id。"""
    settings = get_settings()
    sample_path = settings.project_root / "demo" / "sample_conversations.json"
    raw_items = json.loads(sample_path.read_text(encoding="utf-8"))
    context = resolve_demo_context()
    resolved: list[dict[str, Any]] = []
    for item in raw_items:
        resolved_item = _replace_placeholders(item, context)
        if isinstance(resolved_item, dict) and str(resolved_item.get("bound_creator_id", "")).isdigit():
            resolved_item["bound_creator_id"] = int(resolved_item["bound_creator_id"])
        resolved.append(resolved_item)
    return resolved


def _replace_placeholders(value: Any, context: dict[str, Any]) -> Any:
    """递归替换 JSON 中的 `{{placeholder}}`。"""
    if isinstance(value, str):
        result = value
        for key, replacement in context.items():
            result = result.replace(f"{{{{{key}}}}}", str(replacement))
        return result
    if isinstance(value, list):
        return [_replace_placeholders(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, context) for key, item in value.items()}
    return value
