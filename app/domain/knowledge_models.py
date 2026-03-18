"""markdown 知识库、检索和 evidence 相关模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeChunk(BaseModel):
    """从 markdown 中切出来的一个知识块。"""

    chunk_id: str
    source_file: str
    heading_path: list[str] = Field(default_factory=list)
    text: str
    keywords: list[str] = Field(default_factory=list)
    start_line: int | None = None
    end_line: int | None = None


class RetrievedChunk(BaseModel):
    """带检索分数的知识块。"""

    chunk_id: str
    source_file: str
    heading_path: list[str] = Field(default_factory=list)
    text: str
    content_summary: str
    score: float


class EvidenceItem(BaseModel):
    """统一证据结构。

    这样前端和回答生成层不用区分 evidence 到底来自 ES 还是知识库，
    只需要看 `type` 即可。
    """

    type: Literal["es_fact", "knowledge_chunk"]
    title: str
    content_summary: str
    source: str
    score: float | None = None


class KnowledgeExplainPayload(BaseModel):
    """知识服务层生成的结构化解释结果。"""

    query: str
    answer: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    matched_chunks: list[RetrievedChunk] = Field(default_factory=list)
    mode: Literal["keyword", "embedding", "static"] = "static"


class KnowledgeBuildResult(BaseModel):
    """构建知识索引后的摘要结果。"""

    source_file: str
    chunk_count: int
    index_mode: Literal["keyword", "embedding"]
    embedding_model: str | None = None
