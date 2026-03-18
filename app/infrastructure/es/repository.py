"""ES Repository。

这里集中放所有 Elasticsearch DSL，目的是：
- 不让 workflow 节点直接拼 DSL；
- 不让 tool 层感知 ES 细节；
- 让查询能力集中、可测试、可替换。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from elasticsearch import Elasticsearch

from app.domain.enums import IsCommission


def _epoch_days_ago(days: int) -> int:
    """把“几天前”转换成 epoch 秒。"""
    return int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())


def _epoch_second_range(*, gte: int | None = None, lte: int | None = None) -> dict[str, Any]:
    """统一生成 ES date range，并显式声明 epoch_second。

    当前索引 mapping 里几个时间字段都配置成了 `format=epoch_second`。
    如果 query 里不显式带 `format`，ES 对纯数字 range 的解析可能按默认毫秒处理，
    最终就会出现“索引里明明有数据，但最近 30 天全部命中 0”的假象。
    """
    body: dict[str, Any] = {"format": "epoch_second"}
    if gte is not None:
        body["gte"] = gte
    if lte is not None:
        body["lte"] = lte
    return body


def _distribution(buckets: Iterable[dict[str, Any]]) -> dict[str, int]:
    """把 ES 聚合 buckets 转成普通字典。"""
    return {str(bucket["key"]): bucket["doc_count"] for bucket in buckets}


class CommissionOrderRepository:
    """项目里唯一负责构造分佣查询 DSL 的地方。"""

    def __init__(self, client: Elasticsearch, index_name: str) -> None:
        self.client = client
        self.index_name = index_name

    def count_all(self) -> int:
        """返回索引中的总文档数。"""
        response = self.client.count(index=self.index_name)
        return int(response["count"])

    @staticmethod
    def _compact_filters(filters: dict[str, Any]) -> dict[str, Any]:
        """先剔除空过滤条件，避免拼出无效 DSL。"""
        return {key: value for key, value in filters.items() if value not in (None, [], {}, "")}

    def _build_filter_clauses(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """把归一化后的过滤条件翻译成 ES filter clauses。"""
        normalized = self._compact_filters(filters)
        clauses: list[dict[str, Any]] = []

        # 这些字段都走 keyword / numeric 精确匹配，不走全文检索。
        term_fields = {
            "creator_id",
            "media_id",
            "shop_order_id",
            "third_party_order_id",
            "source_type",
            "is_commission",
            "no_commission_type",
            "transfer_type",
            "region",
            "merchant_id",
        }

        for field in term_fields:
            value = normalized.get(field)
            if value is None:
                continue
            # list -> `terms`
            # scalar -> `term`
            # 这样上游无论传单值还是数组，都能统一处理。
            if isinstance(value, list):
                clauses.append({"terms": {field: value}})
            else:
                clauses.append({"term": {field: value}})

        # compare_source_types 是对比查询特有字段，最终也落成 source_type 的 terms 过滤。
        if normalized.get("compare_source_types"):
            clauses.append({"terms": {"source_type": normalized["compare_source_types"]}})

        start_time = normalized.get("start_time")
        end_time = normalized.get("end_time")
        time_field = normalized.get("time_field")
        if time_field and (start_time is not None or end_time is not None):
            range_body = _epoch_second_range(gte=start_time, lte=end_time)
            # 时间过滤字段不是固定死的：
            # 某些问题会按下单时间查，某些问题会按核销时间查。
            clauses.append({"range": {time_field: range_body}})

        return clauses

    def _base_query(self, filters: dict[str, Any]) -> dict[str, Any]:
        """构造多数查询共用的 bool/filter 基础查询。"""
        return {"bool": {"filter": self._build_filter_clauses(filters)}}

    def get_creator_commission_summary(self, creator_id: int, days: int = 30) -> dict[str, Any]:
        """用于基础校验脚本的达人近 N 天汇总查询。"""
        response = self.client.search(
            index=self.index_name,
            size=0,
            query={
                "bool": {
                    "filter": [
                        {"term": {"creator_id": creator_id}},
                        {"range": {"order_confirm_time": _epoch_second_range(gte=_epoch_days_ago(days))}},
                    ]
                }
            },
            aggs={
                "commissionable_count": {"filter": {"term": {"is_commission": int(IsCommission.COMMISSIONABLE)}}},
                "non_commissionable_count": {"filter": {"term": {"is_commission": int(IsCommission.NOT_COMMISSIONABLE)}}},
                "total_commission_amount": {"sum": {"field": "commission_amount"}},
                "source_type_distribution": {"terms": {"field": "source_type", "size": 10}},
                "no_commission_type_distribution": {
                    "filter": {"term": {"is_commission": int(IsCommission.NOT_COMMISSIONABLE)}},
                    "aggs": {"types": {"terms": {"field": "no_commission_type", "size": 10}}},
                },
            },
        )
        return {
            "creator_id": creator_id,
            "days": days,
            "order_count": response["hits"]["total"]["value"],
            "commissionable_count": response["aggregations"]["commissionable_count"]["doc_count"],
            "non_commissionable_count": response["aggregations"]["non_commissionable_count"]["doc_count"],
            "total_commission_amount": round(
                float(response["aggregations"]["total_commission_amount"]["value"] or 0.0), 2
            ),
            "source_type_distribution": _distribution(
                response["aggregations"]["source_type_distribution"]["buckets"]
            ),
            "no_commission_type_distribution": _distribution(
                response["aggregations"]["no_commission_type_distribution"]["types"]["buckets"]
            ),
        }

    def get_media_no_commission_distribution(self, media_id: int) -> dict[str, Any]:
        """用于基础校验脚本的视频不可分佣原因查询。"""
        response = self.client.search(
            index=self.index_name,
            size=0,
            query={
                "bool": {
                    "filter": [
                        {"term": {"media_id": media_id}},
                        {"term": {"is_commission": int(IsCommission.NOT_COMMISSIONABLE)}},
                    ]
                }
            },
            aggs={"no_commission_type_distribution": {"terms": {"field": "no_commission_type", "size": 10}}},
        )
        return {
            "media_id": media_id,
            "non_commissionable_order_count": response["hits"]["total"]["value"],
            "no_commission_type_distribution": _distribution(
                response["aggregations"]["no_commission_type_distribution"]["buckets"]
            ),
        }

    def get_order_transfer_status(self, shop_order_id: str) -> dict[str, Any] | None:
        """用于基础校验脚本的单订单到账状态查询。"""
        response = self.client.search(
            index=self.index_name,
            size=1,
            query={"term": {"shop_order_id": shop_order_id}},
            _source=[
                "shop_order_id",
                "source_type",
                "is_commission",
                "transfer_type",
                "transfer_time",
                "no_transfer_reason",
                "order_complete_time",
            ],
        )
        hits = response["hits"]["hits"]
        if not hits:
            return None
        return hits[0]["_source"]

    def compare_creator_source_types(self, creator_id: int, source_type_a: int, source_type_b: int) -> dict[str, Any]:
        """用于基础校验脚本的来源类型对比查询。"""
        response = self.client.search(
            index=self.index_name,
            size=0,
            query={
                "bool": {
                    "filter": [
                        {"term": {"creator_id": creator_id}},
                        {"terms": {"source_type": [source_type_a, source_type_b]}},
                    ]
                }
            },
            aggs={
                "by_source_type": {
                    "terms": {"field": "source_type", "size": 10},
                    "aggs": {
                        "commissionable_count": {
                            "filter": {"term": {"is_commission": int(IsCommission.COMMISSIONABLE)}}
                        },
                        "non_commissionable_count": {
                            "filter": {"term": {"is_commission": int(IsCommission.NOT_COMMISSIONABLE)}}
                        },
                        "total_commission_amount": {"sum": {"field": "commission_amount"}},
                    },
                }
            },
        )
        comparison: dict[str, dict[str, Any]] = {}
        for bucket in response["aggregations"]["by_source_type"]["buckets"]:
            comparison[str(bucket["key"])] = {
                "order_count": bucket["doc_count"],
                "commissionable_count": bucket["commissionable_count"]["doc_count"],
                "non_commissionable_count": bucket["non_commissionable_count"]["doc_count"],
                "total_commission_amount": round(float(bucket["total_commission_amount"]["value"] or 0.0), 2),
            }
        return {
            "creator_id": creator_id,
            "source_type_a": source_type_a,
            "source_type_b": source_type_b,
            "comparison": comparison,
        }

    def get_creator_commission_summary_with_filters(self, filters: dict[str, Any]) -> dict[str, Any]:
        """Agent 主流程使用的达人汇总查询。"""
        # 这个聚合是整个项目里使用频率最高的一类查询：
        # - total orders
        # - commissionable / non-commissionable
        # - total commission amount
        # - source_type 分布
        # - no_commission_type 分布
        # 后面的回答生成基本都围绕这些聚合结果组织。
        response = self.client.search(
            index=self.index_name,
            size=0,
            query=self._base_query(filters),
            aggs={
                "commissionable_count": {"filter": {"term": {"is_commission": int(IsCommission.COMMISSIONABLE)}}},
                "non_commissionable_count": {"filter": {"term": {"is_commission": int(IsCommission.NOT_COMMISSIONABLE)}}},
                "total_commission_amount": {"sum": {"field": "commission_amount"}},
                "source_type_distribution": {"terms": {"field": "source_type", "size": 10}},
                "no_commission_type_distribution": {
                    "filter": {"term": {"is_commission": int(IsCommission.NOT_COMMISSIONABLE)}},
                    "aggs": {"types": {"terms": {"field": "no_commission_type", "size": 10}}},
                },
            },
        )
        return {
            "creator_id": filters.get("creator_id"),
            "total_orders": response["hits"]["total"]["value"],
            "commissionable_orders": response["aggregations"]["commissionable_count"]["doc_count"],
            "non_commissionable_orders": response["aggregations"]["non_commissionable_count"]["doc_count"],
            "total_commission_amount": round(
                float(response["aggregations"]["total_commission_amount"]["value"] or 0.0), 2
            ),
            "source_type_distribution": _distribution(
                response["aggregations"]["source_type_distribution"]["buckets"]
            ),
            "no_commission_type_distribution": _distribution(
                response["aggregations"]["no_commission_type_distribution"]["types"]["buckets"]
            ),
        }

    def get_media_no_commission_breakdown(self, filters: dict[str, Any]) -> dict[str, Any]:
        """Agent 主流程使用的视频不可分佣原因分布查询。"""
        # 这里不做更复杂的统计，只聚焦“这个视频为什么不可分佣”，
        # 后续再由知识层解释这些 no_commission_type code 的业务含义。
        response = self.client.search(
            index=self.index_name,
            size=0,
            query=self._base_query(filters),
            aggs={"no_commission_type_distribution": {"terms": {"field": "no_commission_type", "size": 10}}},
        )
        return {
            "media_id": filters.get("media_id"),
            "non_commissionable_orders": response["hits"]["total"]["value"],
            "no_commission_type_distribution": _distribution(
                response["aggregations"]["no_commission_type_distribution"]["buckets"]
            ),
        }

    def get_media_commission_status(self, filters: dict[str, Any]) -> dict[str, Any]:
        """按视频维度汇总整体分佣状态。

        这个查询回答的是：
        - 当前视频命中了多少订单
        - 其中多少可分佣 / 不可分佣
        - 总佣金多少
        - 主要来源类型分布
        - 如果存在不可分佣，再补原因分布
        """
        response = self.client.search(
            index=self.index_name,
            size=0,
            query=self._base_query(filters),
            aggs={
                "commissionable_count": {"filter": {"term": {"is_commission": int(IsCommission.COMMISSIONABLE)}}},
                "non_commissionable_count": {"filter": {"term": {"is_commission": int(IsCommission.NOT_COMMISSIONABLE)}}},
                "total_commission_amount": {"sum": {"field": "commission_amount"}},
                "source_type_distribution": {"terms": {"field": "source_type", "size": 10}},
                "no_commission_type_distribution": {
                    "filter": {"term": {"is_commission": int(IsCommission.NOT_COMMISSIONABLE)}},
                    "aggs": {"types": {"terms": {"field": "no_commission_type", "size": 10}}},
                },
            },
        )
        return {
            "media_id": filters.get("media_id"),
            "total_orders": response["hits"]["total"]["value"],
            "commissionable_orders": response["aggregations"]["commissionable_count"]["doc_count"],
            "non_commissionable_orders": response["aggregations"]["non_commissionable_count"]["doc_count"],
            "total_commission_amount": round(
                float(response["aggregations"]["total_commission_amount"]["value"] or 0.0), 2
            ),
            "source_type_distribution": _distribution(
                response["aggregations"]["source_type_distribution"]["buckets"]
            ),
            "no_commission_type_distribution": _distribution(
                response["aggregations"]["no_commission_type_distribution"]["types"]["buckets"]
            ),
        }

    def get_order_transfer_status_with_filters(self, filters: dict[str, Any]) -> dict[str, Any] | None:
        """Agent 主流程使用的单订单到账状态查询。"""
        # 单订单查询只取 size=1，并按最近 order_confirm_time 倒序，
        # 这样即便过滤条件不够精确，也尽量返回最相关的一条。
        response = self.client.search(
            index=self.index_name,
            size=1,
            query=self._base_query(filters),
            sort=[{"order_confirm_time": {"order": "desc"}}],
            _source=[
                "creator_id",
                "media_id",
                "shop_order_id",
                "third_party_order_id",
                "source_type",
                "is_commission",
                "transfer_type",
                "transfer_time",
                "no_transfer_reason",
                "order_complete_time",
                "commission_amount",
            ],
        )
        hits = response["hits"]["hits"]
        if not hits:
            return None
        return hits[0]["_source"]

    def summarize_commission_by_media(self, filters: dict[str, Any]) -> dict[str, Any]:
        """按视频维度聚合达人查询结果。"""
        # `size=200` 是当前 demo 足够用的上限：
        # - 能覆盖“一个达人下多个视频”的展示；
        # - 又不会把 response 做得过重。
        response = self.client.search(
            index=self.index_name,
            size=0,
            query=self._base_query(filters),
            aggs={
                "by_media": {
                    "terms": {"field": "media_id", "size": 200, "order": {"_count": "desc"}},
                    "aggs": {
                        "commissionable_count": {
                            "filter": {"term": {"is_commission": int(IsCommission.COMMISSIONABLE)}}
                        },
                        "non_commissionable_count": {
                            "filter": {"term": {"is_commission": int(IsCommission.NOT_COMMISSIONABLE)}}
                        },
                        "total_commission_amount": {"sum": {"field": "commission_amount"}},
                    },
                }
            },
        )
        items: list[dict[str, Any]] = []
        for bucket in response["aggregations"]["by_media"]["buckets"]:
            # 这里返回的是已经拉平的聚合项，而不是原始 ES bucket，
            # 这样 tool 层和回答层不需要再感知 ES bucket 结构。
            items.append(
                {
                    "media_id": int(bucket["key"]),
                    "total_orders": bucket["doc_count"],
                    "commissionable_orders": bucket["commissionable_count"]["doc_count"],
                    "non_commissionable_orders": bucket["non_commissionable_count"]["doc_count"],
                    "total_commission_amount": round(float(bucket["total_commission_amount"]["value"] or 0.0), 2),
                }
            )
        return {"creator_id": filters.get("creator_id"), "items": items}

    def compare_source_type_commission(self, filters: dict[str, Any]) -> dict[str, Any]:
        """按 source_type 聚合同一达人结果，用于对比查询。"""
        # compare_source_types 最终会落到 `_base_query(filters)` 里，
        # 这里再按 source_type 聚合一次，是为了拿到每种类型自己的订单量和佣金。
        response = self.client.search(
            index=self.index_name,
            size=0,
            query=self._base_query(filters),
            aggs={
                "by_source_type": {
                    "terms": {"field": "source_type", "size": 10},
                    "aggs": {
                        "commissionable_count": {
                            "filter": {"term": {"is_commission": int(IsCommission.COMMISSIONABLE)}}
                        },
                        "non_commissionable_count": {
                            "filter": {"term": {"is_commission": int(IsCommission.NOT_COMMISSIONABLE)}}
                        },
                        "total_commission_amount": {"sum": {"field": "commission_amount"}},
                    },
                }
            },
        )
        items: list[dict[str, Any]] = []
        for bucket in response["aggregations"]["by_source_type"]["buckets"]:
            items.append(
                {
                    "source_type": int(bucket["key"]),
                    "total_orders": bucket["doc_count"],
                    "commissionable_orders": bucket["commissionable_count"]["doc_count"],
                    "non_commissionable_orders": bucket["non_commissionable_count"]["doc_count"],
                    "total_commission_amount": round(float(bucket["total_commission_amount"]["value"] or 0.0), 2),
                }
            )
        return {
            "creator_id": filters.get("creator_id"),
            "compare_source_types": filters.get("compare_source_types") or filters.get("source_type"),
            "items": items,
        }

    def find_recent_creator_id(self, days: int = 30) -> int | None:
        """挑一个最近有订单的 creator_id，供校验和 Demo 使用。"""
        response = self.client.search(
            index=self.index_name,
            size=0,
            query={"range": {"order_confirm_time": _epoch_second_range(gte=_epoch_days_ago(days))}},
            aggs={"creators": {"terms": {"field": "creator_id", "size": 1, "order": {"_count": "desc"}}}},
        )
        buckets = response["aggregations"]["creators"]["buckets"]
        return int(buckets[0]["key"]) if buckets else None

    def find_media_id_with_non_commission(self) -> int | None:
        """挑一个一定存在不可分佣订单的视频 id。"""
        response = self.client.search(
            index=self.index_name,
            size=0,
            query={"term": {"is_commission": int(IsCommission.NOT_COMMISSIONABLE)}},
            aggs={"media_ids": {"terms": {"field": "media_id", "size": 1, "order": {"_count": "desc"}}}},
        )
        buckets = response["aggregations"]["media_ids"]["buckets"]
        return int(buckets[0]["key"]) if buckets else None

    def find_recent_media_id(self, days: int = 30) -> int | None:
        """挑一个最近有订单的视频 id，供视频维度验证脚本使用。"""
        response = self.client.search(
            index=self.index_name,
            size=0,
            query={"range": {"order_confirm_time": _epoch_second_range(gte=_epoch_days_ago(days))}},
            aggs={"media_ids": {"terms": {"field": "media_id", "size": 1, "order": {"_count": "desc"}}}},
        )
        buckets = response["aggregations"]["media_ids"]["buckets"]
        return int(buckets[0]["key"]) if buckets else None

    def find_latest_shop_order_id(self) -> str | None:
        """挑一个最近订单 id，供脚本和前端快捷问题使用。"""
        response = self.client.search(
            index=self.index_name,
            size=1,
            sort=[{"order_confirm_time": {"order": "desc"}}],
            _source=["shop_order_id"],
        )
        hits = response["hits"]["hits"]
        return hits[0]["_source"]["shop_order_id"] if hits else None

    def find_creator_with_multiple_source_types(self) -> tuple[int, tuple[int, int]] | None:
        """挑一个同时覆盖至少两种 source_type 的达人。"""
        # 这个方法主要服务于 demo / validate，不是面向真实业务查询。
        # 目的只是从现有 seeded 数据里找一个稳定可展示的样例。
        response = self.client.search(
            index=self.index_name,
            size=0,
            aggs={
                "creators": {
                    "terms": {"field": "creator_id", "size": 50, "order": {"_count": "desc"}},
                    "aggs": {"source_types": {"terms": {"field": "source_type", "size": 10}}},
                }
            },
        )
        for bucket in response["aggregations"]["creators"]["buckets"]:
            source_buckets = bucket["source_types"]["buckets"]
            if len(source_buckets) >= 2:
                pair = (int(source_buckets[0]["key"]), int(source_buckets[1]["key"]))
                return int(bucket["key"]), pair
        return None
