"""知识服务主入口。

这层把知识库相关的几个步骤串起来：
- 确保 markdown 存在；
- 按标题切块；
- 构建本地索引；
- 按 query 检索；
- 生成 explain 类回答；
- 在缺少 embedding 或 LLM 时自动 fallback。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.application.knowledge.chunker import chunk_markdown
from app.application.knowledge.embeddings import KnowledgeEmbeddingService
from app.application.knowledge.loader import ensure_knowledge_markdown
from app.application.knowledge.qdrant_store import QdrantKnowledgeStore
from app.application.knowledge.retriever import KnowledgeRetriever
from app.application.knowledge.vector_store import LocalKnowledgeVectorStore
from app.application.llm.client import OpenAICompatibleClient
from app.application.llm.models import LLMMessage
from app.config.settings import Settings, get_settings
from app.domain.enums import ENUM_ZH_MAPPINGS
from app.domain.knowledge_models import EvidenceItem, KnowledgeBuildResult, KnowledgeExplainPayload, RetrievedChunk

MIN_RAG_RELEVANCE_SCORE = 0.45


class KnowledgeService:
    """负责知识索引构建、检索和解释的总服务。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        # knowledge 层自己持有 embedding / retriever / vector store / llm client，
        # 这样上层 tools 不需要知道它内部到底是 keyword 还是 embedding。
        self.embedding_service = KnowledgeEmbeddingService(self.settings)
        self.local_retriever = KnowledgeRetriever(self.embedding_service)
        self.local_vector_store = LocalKnowledgeVectorStore()
        self.qdrant_store = QdrantKnowledgeStore(self.settings)
        self.llm_client = OpenAICompatibleClient(self.settings)

    def build_index(self) -> KnowledgeBuildResult:
        """构建本地知识索引。

        如果 embedding 可用，就写入向量文件；
        否则仍然会产出 chunks 和 meta，供 keyword fallback 使用。
        """
        markdown_path = ensure_knowledge_markdown(self.settings)
        chunks = chunk_markdown(markdown_path)
        # embedding 文本刻意把 heading_path 拼进去，避免只向量化正文导致语义丢失。
        embedding_texts = [self._chunk_to_embedding_text(chunk) for chunk in chunks]
        vectors = self.embedding_service.embed_texts(embedding_texts)
        mode = "embedding" if vectors is not None else "keyword"
        # 即使 embedding 失败，这里也仍然把 chunks 和 meta 写出来，
        # 确保系统最差还能走 keyword fallback。
        self.local_vector_store.save(
            chunks_path=self.settings.knowledge_chunks_path,
            index_meta_path=self.settings.knowledge_index_meta_path,
            index_vector_path=self.settings.knowledge_index_vector_path,
            chunks=chunks,
            mode=mode,
            embedding_model=self.settings.embedding_model if vectors is not None else None,
            vectors=vectors,
            backend=self.settings.knowledge_backend,
        )
        # Qdrant 是“索引后端”，不是新的知识源。
        # 所以仍然保留本地 chunks/meta 文件，便于调试与 fallback；
        # 只是额外把 embedding 向量同步到 Qdrant collection。
        if vectors is not None and self.settings.knowledge_backend == "qdrant":
            self.qdrant_store.upsert_chunks(chunks, vectors)
        return KnowledgeBuildResult(
            source_file=str(markdown_path),
            chunk_count=len(chunks),
            index_mode=mode,
            embedding_model=self.settings.embedding_model if vectors is not None else None,
        )

    def retrieve_term_knowledge(self, query: str, top_k: int = 4) -> list[RetrievedChunk]:
        """检索术语解释类问题对应的知识块。"""
        chunks, _, vectors = self._ensure_index_loaded()
        normalized_query, canonical_term = self._normalize_term_query(query)
        retrieved = self._retrieve_chunks(normalized_query, chunks=chunks, vectors=vectors, top_k=max(top_k, 8))
        reranked = self._rerank_term_chunks(retrieved, canonical_term)
        return self._filter_relevant_chunks(reranked)[:top_k]

    def retrieve_rule_knowledge(self, code_or_query: str, top_k: int = 4) -> list[RetrievedChunk]:
        """检索规则/状态/原因码相关的知识块。"""
        chunks, _, vectors = self._ensure_index_loaded()
        # 规则码经常很短，比如 NO_PRODUCT_COMMISSION。
        # 先扩写成更长、更贴业务语义的 query，检索会稳定很多。
        normalized_query = self._normalize_rule_query(code_or_query)
        retrieved = self._retrieve_chunks(normalized_query, chunks=chunks, vectors=vectors, top_k=max(top_k, 8))
        return self._filter_relevant_chunks(retrieved)[:top_k]

    def explain_business_term(self, term_or_query: str, context: dict[str, Any] | None = None) -> KnowledgeExplainPayload:
        """解释业务术语类问题。"""
        matched_chunks = self.retrieve_term_knowledge(term_or_query, top_k=4)
        # 若一个 chunk 都没命中，就直接走静态兜底，避免 explain 类问题无响应。
        if not matched_chunks:
            return self._static_fallback(term_or_query)
        concise_fallback = self._compose_term_answer(term_or_query, matched_chunks)
        answer = self._synthesize_answer(
            query=term_or_query,
            matched_chunks=matched_chunks,
            context=context,
            fallback_answer=concise_fallback,
        )
        # mode 字段反映的是当前知识回答实际走的底层索引形态，
        # 而不是“项目理论上支持什么”。
        return KnowledgeExplainPayload(
            query=term_or_query,
            answer=answer,
            evidence=[self._to_evidence(chunk) for chunk in matched_chunks],
            matched_chunks=matched_chunks,
            mode="embedding" if self.embedding_service.enabled else "keyword",
        )

    def explain_rule_with_context(
        self,
        fact_payload: dict[str, Any],
        query: str | None = None,
    ) -> KnowledgeExplainPayload:
        """在 ES 事实之外，补上规则层解释。"""
        # 如果 ES 事实已经足够直接回答，就不要为了“看起来像 RAG”而强行补知识说明。
        # 这能避免：
        # - 已到账订单被误拼上无关的原因码解释；
        # - 低相关 chunk 污染最终回答。
        if self._fact_is_self_explanatory(fact_payload):
            return KnowledgeExplainPayload(
                query=query or "",
                answer="",
                evidence=[],
                matched_chunks=[],
                mode="static",
            )

        knowledge_query = query or self._build_rule_query(fact_payload)
        matched_chunks = self.retrieve_rule_knowledge(knowledge_query, top_k=4)
        # 对“为什么不可分佣 / 为什么还没到账”这类问题，
        # 事实来自 ES，解释来自知识库。两者缺一不可。
        if not matched_chunks:
            # 规则解释缺失时不要硬兜一个可能偏题的静态解释；
            # 这类场景宁可只回答 ES 事实，也不要输出错误规则。
            return KnowledgeExplainPayload(
                query=knowledge_query,
                answer="",
                evidence=[],
                matched_chunks=[],
                mode="static",
            )
        # explain_rule_with_context 不让 LLM 重新发挥长文总结，
        # 而是优先用规则化拼接，确保“解释围绕事实结果展开”，不偏题。
        answer = self._compose_rule_answer(fact_payload, matched_chunks)
        return KnowledgeExplainPayload(
            query=knowledge_query,
            answer=answer,
            evidence=[self._to_evidence(chunk) for chunk in matched_chunks],
            matched_chunks=matched_chunks,
            mode="embedding" if self.embedding_service.enabled else "keyword",
        )

    def _ensure_index_loaded(self) -> tuple[list, dict, np.ndarray | None]:
        """首次使用时按需构建索引，否则直接从本地文件加载。"""
        if not self.settings.knowledge_chunks_path.exists() or not self.settings.knowledge_index_meta_path.exists():
            self.build_index()
        return self.local_vector_store.load(
            chunks_path=self.settings.knowledge_chunks_path,
            index_meta_path=self.settings.knowledge_index_meta_path,
            index_vector_path=self.settings.knowledge_index_vector_path,
        )

    def _retrieve_chunks(
        self,
        query: str,
        *,
        chunks: list,
        vectors: np.ndarray | None,
        top_k: int,
    ) -> list[RetrievedChunk]:
        """根据配置在 local / qdrant 检索后端之间切换。"""
        if self.settings.knowledge_backend == "qdrant" and vectors is not None:
            query_vectors = self.embedding_service.embed_texts([query])
            if query_vectors is not None and len(query_vectors) > 0:
                retrieved = self.qdrant_store.search(query_vector=query_vectors[0], top_k=top_k)
                if retrieved:
                    return retrieved
        return self.local_retriever.retrieve(query, chunks=chunks, vectors=vectors, top_k=top_k)

    @staticmethod
    def _chunk_to_embedding_text(chunk) -> str:
        """把标题路径和正文拼起来，作为最终向量化文本。"""
        return " / ".join(chunk.heading_path) + "\n" + chunk.text

    def _synthesize_answer(
        self,
        *,
        query: str,
        matched_chunks: list[RetrievedChunk],
        context: dict[str, Any] | None,
        fallback_answer: str,
    ) -> str:
        """让 LLM 负责“表达更自然”，但不负责“编造新知识”。"""
        # 没有 LLM 时，直接用规则拼接答案，不影响 explain 能力可用性。
        if not self.llm_client.enabled:
            return fallback_answer
        # 这里不给模型原始 query 之外的自由空间：
        # 只喂命中的 chunks，并明确要求“只能依据提供的知识片段回答”。
        prompt = "\n\n".join(
            f"[{chunk.chunk_id}] {' / '.join(chunk.heading_path)}\n{chunk.text}"
            for chunk in matched_chunks
        )
        context_text = f"\n补充上下文：{context}" if context else ""
        response = self.llm_client.chat(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "你是分佣知识助手。只能依据提供的知识片段回答，禁止编造未提供的规则。"
                        "回答要尽量简单清晰，适合直接展示给业务用户。"
                        "输出格式要求："
                        "1. 先给一句话定义；"
                        "2. 再给 2 到 3 条关键点；"
                        "3. 如果有必要，最后补一条一句话对比；"
                        "4. 不要大段照抄原文；"
                        "5. 不要输出 markdown 标题；"
                        "6. 不要把多个相近概念混在一起讲，除非用户明确要求比较。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f"问题：{query}{context_text}\n\n"
                        f"知识片段：\n{prompt}\n\n"
                        "请按要求给出简洁中文解释。"
                    ),
                ),
            ],
            temperature=0.1,
            max_tokens=300,
        )
        return response.content.strip() if response and response.content.strip() else fallback_answer

    def _compose_term_answer(self, query: str, matched_chunks: list[RetrievedChunk]) -> str:
        """无 LLM 时的规则化术语回答拼接逻辑。"""
        canonical_term = self._detect_canonical_term(query)
        if canonical_term == "cps":
            return "\n".join(
                [
                    "CPS 是按成交结果结算的分佣模式。",
                    "",
                    "- 重点看用户是否下单、订单是否核销、订单是否可归因。",
                    "- 只要成交链路不成立，最终就可能没有佣金。",
                    "- 在本业务里，CPS 包括开环 CPS、闭环 CPS、达人包 CPS。",
                ]
            )
        if canonical_term == "cpt":
            return "\n".join(
                [
                    "CPT 是按任务履约和内容要求结算的固定合作模式。",
                    "",
                    "- 更看任务是否完成，不是单纯看订单成交结果。",
                    "- 在本业务里，CPT 只出现在达人包任务中。",
                    "- 佣金通常是固定金额，而不是纯按订单比例浮动。",
                ]
            )
        if canonical_term == "闭环cps":
            return "\n".join(
                [
                    "闭环 CPS 指用户在 TikTok 平台内完成浏览、下单和支付的 CPS 模式。",
                    "",
                    "- 交易全程发生在平台内。",
                    "- 平台掌握更完整的成交和归因链路。",
                    "- 系统中对应 `source_type=1`。",
                ]
            )
        if canonical_term == "开环cps":
            return "\n".join(
                [
                    "开环 CPS 指用户从平台内容跳转到第三方平台完成交易的 CPS 模式。",
                    "",
                    "- 用户先在平台看到内容，再跳转到第三方平台下单。",
                    "- 订单结果更依赖第三方平台回传。",
                    "- 系统中对应 `source_type=2`。",
                ]
            )
        if canonical_term == "cps_vs_cpt":
            return "\n".join(
                [
                    "CPS 和 CPT 的核心区别是：结算依据不同。",
                    "",
                    "- CPS 看成交结果。",
                    "- CPT 看任务完成情况。",
                    "- 简单理解：CPS 更像带货成交分佣，CPT 更像固定合作任务结算。",
                ]
            )
        if canonical_term == "开环_vs_闭环":
            return "\n".join(
                [
                    "开环和闭环的核心区别是：交易发生在哪里。",
                    "",
                    "- 开环：用户跳转到第三方平台完成交易。",
                    "- 闭环：用户在 TikTok 平台内完成交易。",
                    "- 简单理解：开环是平台外成交，闭环是平台内成交。",
                ]
            )

        cleaned_snippets = [self._clean_chunk_summary(chunk.content_summary) for chunk in matched_chunks[:2]]
        if len(cleaned_snippets) == 1:
            return cleaned_snippets[0]
        return "\n".join([f"{query} 的相关说明如下：", "", *[f"- {item}" for item in cleaned_snippets]])

    def _compose_rule_answer(self, fact_payload: dict[str, Any], matched_chunks: list[RetrievedChunk]) -> str:
        """只围绕当前事实结果拼出必要规则解释。"""
        rule_snippet = "；".join(chunk.content_summary for chunk in matched_chunks[:2])
        # 这里按 fact_payload 的形状区分场景，而不是额外传一个 mode 参数：
        # - 有 no_transfer_reason -> 订单到账解释
        # - 有 no_commission_type_distribution -> 不可分佣解释
        # 这样上层调用更简单。
        if fact_payload.get("no_transfer_reason") is not None:
            return f"根据当前订单事实，规则解释为：{rule_snippet}"
        if fact_payload.get("no_commission_type_distribution"):
            return f"根据当前不可分佣统计，主要规则解释为：{rule_snippet}"
        return rule_snippet

    @staticmethod
    def _filter_relevant_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """过滤低相关 chunk。

        当前阈值先固定为 0.45：
        - >= 0.45：认为足够相关，可进入最终回答；
        - < 0.45：留在调试阶段也意义不大，直接丢弃，避免污染 answer/evidence。
        """
        return [chunk for chunk in chunks if chunk.score >= MIN_RAG_RELEVANCE_SCORE]

    @staticmethod
    def _fact_is_self_explanatory(fact_payload: dict[str, Any]) -> bool:
        """判断 ES 事实是否已经足够完整，不需要再补规则解释。

        这里不按 intent 硬编码，而是看事实本身是否已经闭环：
        - 如果订单已经到账且到账时间明确，业务问题“什么时候到账”已经有直接答案；
        - 这时再走 RAG 只会增加噪声，不会增加信息增益。
        """
        transfer_type = fact_payload.get("transfer_type")
        transfer_time = fact_payload.get("transfer_time")
        if transfer_type == 3 and transfer_time is not None:
            return True
        return False

    def _static_fallback(self, query: str) -> KnowledgeExplainPayload:
        """当 markdown 检索失败时，用静态映射做最终兜底。"""
        normalized = query.strip().lower()
        # 优先尝试把 query 映射到现有枚举 code / 中文标签，
        # 这样至少能给出一条准确但简短的解释。
        for enum_name, mappings in ENUM_ZH_MAPPINGS.items():
            for _, value in mappings.items():
                if value["code"].lower() in normalized or value["zh_cn"] in query:
                    answer = f"{value['code']} 表示：{value['zh_cn']}。"
                    evidence = [
                        EvidenceItem(
                            type="knowledge_chunk",
                            title=f"{enum_name} 静态解释",
                            content_summary=answer,
                            source="static-mapping",
                        )
                    ]
                    return KnowledgeExplainPayload(
                        query=query,
                        answer=answer,
                        evidence=evidence,
                        matched_chunks=[],
                        mode="static",
                    )
        answer = "当前命中了静态知识兜底解释，但没有找到更具体的 markdown 片段。"
        return KnowledgeExplainPayload(
            query=query,
            answer=answer,
            evidence=[
                EvidenceItem(
                    type="knowledge_chunk",
                    title="静态知识兜底",
                    content_summary=answer,
                    source="static-fallback",
                )
            ],
            matched_chunks=[],
            mode="static",
        )

    @staticmethod
    def _build_rule_query(fact_payload: dict[str, Any]) -> str:
        """把 ES 事实结果转换成更适合检索的规则 query。"""
        if fact_payload.get("no_transfer_reason") is not None:
            # 订单到账类解释同时带上 transfer_type、no_transfer_reason 和 T+2，
            # 能显著提高命中“到账链路 + 原因解释”相关 chunk 的概率。
            reason_code = int(fact_payload.get("no_transfer_reason"))
            reason_label = ENUM_ZH_MAPPINGS["no_transfer_reason"].get(reason_code, {}).get("code", str(reason_code))
            transfer_code = int(fact_payload.get("transfer_type"))
            transfer_label = ENUM_ZH_MAPPINGS["transfer_type"].get(transfer_code, {}).get("zh_cn", str(transfer_code))
            return f"{transfer_label} {reason_label} T+2"
        if fact_payload.get("no_commission_type_distribution"):
            # 媒体不可分佣类解释只需要把出现过的 reason code 拼出来即可。
            codes = [
                ENUM_ZH_MAPPINGS["no_commission_type"].get(int(code), {}).get("code", str(code))
                for code in fact_payload["no_commission_type_distribution"].keys()
            ]
            return " ".join(codes)
        return "T+2 规则"

    @staticmethod
    def _normalize_rule_query(query: str) -> str:
        """把紧凑的 code 扩写成更好检索的 query。"""
        query_upper = query.upper()
        replacements = {
            "NO_PRODUCT_COMMISSION": "NO_PRODUCT_COMMISSION 商品在投稿和下单时都不处于推广状态",
            "NOT_ALLIANCE_CREATOR": "NOT_ALLIANCE_CREATOR 非联盟达人",
            "FULFILMENT_TASK_INVALID_STATUS": "FULFILMENT_TASK_INVALID_STATUS 履约任务状态无效",
            "CREATOR_PACKAGE_TASK_NOT_CPS_TASK": "CREATOR_PACKAGE_TASK_NOT_CPS_TASK 达人包任务不是 CPS",
            "COMMISSION_RATE_ZERO": "COMMISSION_RATE_ZERO 分佣比例为 0",
            "NO_EXIST_SHOP_FROM_ORDER_POI": "NO_EXIST_SHOP_FROM_ORDER_POI 无法通过订单 POI 找到店铺",
        }
        for code, expanded in replacements.items():
            if code in query_upper:
                return expanded
        return query

    @staticmethod
    def _normalize_term_query(query: str) -> tuple[str, str | None]:
        canonical_term = KnowledgeService._detect_canonical_term(query)
        expansions = {
            "cps": "CPS 是什么 Cost Per Sale 按成交结果结算 分佣模式",
            "cpt": "CPT 是什么 固定结算 任务履约 达人包",
            "闭环cps": "闭环 CPS 是什么 source_type=1 平台内成交",
            "开环cps": "开环 CPS 是什么 source_type=2 第三方平台成交",
            "cps_vs_cpt": "CPS 和 CPT 的区别 结算依据不同",
            "开环_vs_闭环": "开环 和 闭环 的区别 交易发生在哪里",
        }
        return expansions.get(canonical_term, query), canonical_term

    @staticmethod
    def _detect_canonical_term(query: str) -> str | None:
        normalized = query.lower().replace(" ", "")
        if "cps和cpt" in normalized or ("cps" in normalized and "cpt" in normalized and "区别" in normalized):
            return "cps_vs_cpt"
        if ("开环" in normalized and "闭环" in normalized and "区别" in normalized) or "开环和闭环" in normalized:
            return "开环_vs_闭环"
        if "闭环cps" in normalized:
            return "闭环cps"
        if "开环cps" in normalized:
            return "开环cps"
        if "cpt" in normalized and "cps" not in normalized:
            return "cpt"
        if "cps" in normalized and "开环" not in normalized and "闭环" not in normalized:
            return "cps"
        return None

    @staticmethod
    def _rerank_term_chunks(chunks: list[RetrievedChunk], canonical_term: str | None) -> list[RetrievedChunk]:
        if canonical_term is None:
            return chunks

        def bonus(chunk: RetrievedChunk) -> float:
            heading = " / ".join(chunk.heading_path).lower().replace(" ", "")
            if canonical_term == "cps":
                if "3.1cps是什么" in heading or "问：cps是什么" in heading:
                    return 0.22
                if "开环cps" in heading or "闭环cps" in heading:
                    return -0.08
            if canonical_term == "cpt":
                if "3.2cpt是什么" in heading or "问：cpt是什么" in heading:
                    return 0.22
            if canonical_term == "闭环cps" and ("3.4闭环cps是什么" in heading or "问：闭环cps是什么" in heading):
                return 0.22
            if canonical_term == "开环cps" and ("3.3开环cps是什么" in heading or "问：开环cps是什么" in heading):
                return 0.22
            if canonical_term == "cps_vs_cpt" and ("3.6cps和cpt的区别" in heading or "问：cps和cpt有什么区别" in heading):
                return 0.22
            if canonical_term == "开环_vs_闭环" and ("3.7开环和闭环的区别" in heading):
                return 0.22
            return 0.0

        reranked = sorted(chunks, key=lambda item: item.score + bonus(item), reverse=True)
        return reranked

    @staticmethod
    def _clean_chunk_summary(text: str) -> str:
        cleaned = (
            text.replace("**", "")
            .replace("`", "")
            .replace("> ", "")
            .replace(" - ", "；")
            .replace("---", "")
            .strip()
        )
        return " ".join(cleaned.split())

    @staticmethod
    def _to_evidence(chunk: RetrievedChunk) -> EvidenceItem:
        """把检索结果转成 API 对外统一 evidence 结构。"""
        return EvidenceItem(
            type="knowledge_chunk",
            title=" / ".join(chunk.heading_path),
            content_summary=chunk.content_summary,
            source=chunk.source_file,
            score=chunk.score,
        )
