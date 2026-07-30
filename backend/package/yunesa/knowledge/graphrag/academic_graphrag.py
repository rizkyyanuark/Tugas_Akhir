"""Academic GraphRAG retrieval package builder.

This module keeps Yunesa's existing Yuxi-style retrieval backbone intact:
Milvus/Zilliz returns semantic text evidence, Neo4j/AuraDB returns structured
academic graph evidence, and the chat agent synthesizes the final answer.
"""

import asyncio
import csv
import hashlib
import io
import os
import re
import time
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

from yunesa.observability import opik_span, set_observation_output
from yunesa.utils import logger

from .base import BaseGraphStorage, BaseVectorStorage
from .query_planner import AcademicQueryParam, AcademicQueryPlanner
from .storage import MilvusVectorStorage, Neo4jGraphStorage, normalize_milvus_uri
from .heuristics import AcademicHeuristics
from .normalizers import AcademicNormalizers, _clip_text, _format_values
from .neo4j_queries import AcademicNeo4jQueries
from .evidence import AcademicEvidence
from .reranker import rerank_documents
from .fusion import (
    reciprocal_rank_fusion,
    degree_rerank_entities,
    degree_rerank_relationships,
    graph_connection_rank,
    match_mentioned_entities,
)

KeywordExtractor = Callable[[str], str | Awaitable[str]]


ACADEMIC_NODE_TYPES = [
    "Lecturer",
    "Publication",
    "Institution",
    "Venue",
    "Year",
    "Keyword",
    "Concept",
]

ACADEMIC_RELATION_TYPES = [
    "HAS_AFFILIATION",
    "PUBLISHES",
    "HAS_AUTHOR",
    "PUBLISHED_IN_VENUE",
    "PUBLISHED_IN_YEAR",
    "HAS_KEYWORD",
    "HAS_TOPIC",
    "SOLVES_PROBLEM",
    "WORKS_ON_TASK",
    "PROPOSES_INNOVATION",
    "USES_METHOD",
    "USES_MODEL",
    "BELONGS_TO_DOMAIN",
    "USES_DATASET",
    "EVALUATED_WITH",
    "HAS_RESULT",
    "COLLABORATES_WITH",
]

ACADEMIC_COLLECTIONS = {
    "paper_chunks": "PaperChunk",
    "entities": "EntityEmbedding",
    "relationships": "RelationshipEmbedding",
    "content_keywords": "ContentKeyword",
}

DEFAULT_ACADEMIC_EMBEDDING_PROVIDER = "siliconflow"
DEFAULT_ACADEMIC_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_MILVUS_DB_NAME = "default"
DEFAULT_MILVUS_TIMEOUT_SECONDS = 12.0
DEFAULT_RETRIEVAL_STAGE_TIMEOUT_SECONDS = 20.0
DEFAULT_STRUCTURED_ENUMERATION_LIMIT = 60


@lru_cache(maxsize=8)
def _cached_milvus_client(uri: str, token: str, db_name: str | None):
    from pymilvus import MilvusClient

    client = MilvusClient(uri=uri, token=token)
    if db_name and hasattr(client, "using_database"):
        client.using_database(db_name)
    return client


class AcademicGraphRAGService:
    """Build an AcademicRAG-style context package from vector and graph stores."""

    VALID_MODES = {
        "vector",
        "keyword",
        "subgraph",
        "global",
        "graph",
        "hybrid",
        "mix",
    }
    MODE_ALIASES = {
        "naive": "vector",
        "bm25": "keyword",
        "local": "subgraph",
        "academic": "hybrid",
        "academic_graphrag": "hybrid",
        "graphrag": "hybrid",
        "mix": "hybrid",
    }
    # AcademicRAG-style query planning lives in query_planner.py. These aliases
    # keep existing tests and callers stable while making the upstream-inspired
    # routing layer explicit and reusable.
    GRAPH_STOPWORDS = AcademicQueryPlanner.GRAPH_STOPWORDS
    AUTHOR_PUBLICATION_QUERY_MARKERS = AcademicQueryPlanner.AUTHOR_PUBLICATION_QUERY_MARKERS
    LECTURER_TOPIC_QUERY_MARKERS = AcademicQueryPlanner.LECTURER_TOPIC_QUERY_MARKERS
    TOPIC_FREQUENCY_QUERY_MARKERS = AcademicQueryPlanner.TOPIC_FREQUENCY_QUERY_MARKERS

    @classmethod
    def normalize_mode(cls, mode: str | None, include_graph: bool = False) -> str:
        return AcademicQueryParam.normalize_runtime_mode(mode, include_graph=include_graph)

    @classmethod
    def milvus_search_mode(cls, mode: str) -> str:
        if mode == "keyword":
            return "keyword"
        if mode in {"subgraph", "global", "graph", "hybrid", "mix"}:
            return "hybrid"
        return "vector"

    @classmethod
    def uses_graph(cls, mode: str, include_graph: bool = False) -> bool:
        return mode in {"subgraph", "graph", "hybrid", "mix"}

    @classmethod
    def route_retrieval_mode(
        cls,
        query_text: str,
        *,
        requested_mode: str | None = None,
        include_graph: bool = False,
    ) -> dict[str, Any]:
        """Choose an effective retrieval mode for default academic UI queries.

        LLM router is active, so we disable heuristic overrides.
        """
        normalized_mode = cls.normalize_mode(requested_mode, include_graph=include_graph)
        return {
            "requested_mode": normalized_mode,
            "effective_mode": normalized_mode,
            "auto_routed": False,
            "reason": "llm_router_active",
            "intents": AcademicQueryPlanner.classify_intents(query_text),
        }


    @staticmethod
    def storage_layer() -> dict[str, Any]:
        return {
            "metadata": {
                "backend": "postgres_self_hosted",
                "stores": ["papers", "lecturers"],
            },
            "vector": {
                "backend": "milvus_self_hosted",
                "purpose": "semantic, BM25, and hybrid retrieval over text chunks",
                "fields": [
                    "content",
                    "embedding",
                    "content_sparse",
                    "source",
                    "file_id",
                    "chunk_id",
                    "chunk_index",
                ],
            },
            "graph": {
                "backend": "neo4j_self_hosted",
                "purpose": "structured academic ontology traversal",
                "node_types": ACADEMIC_NODE_TYPES,
                "relation_types": ACADEMIC_RELATION_TYPES,
            },
        }

    @staticmethod
    def _clip_text(value: str, max_chars: int) -> str:
        text = str(value or "").strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    @staticmethod
    def _academic_graph_name(graph_name: str | None = None) -> str:
        return (
            str(graph_name or "").strip()
            or os.getenv("YUNESA_NEO4J_GRAPH_NAME")
            or os.getenv("YUNESA_GRAPH_NAME")
            or "yunesa_academic_kg"
        )

    @staticmethod
    def _academic_milvus_enabled() -> bool:
        value = os.getenv("YUNESA_USE_CANONICAL_GRAPHRAG", "1").strip().lower()
        return value not in {"0", "false", "no", "off"}

    @staticmethod
    def _milvus_credentials() -> tuple[str, str, str | None]:
        uri = os.getenv("MILVUS_URI") or os.getenv("ZILLIZ_URI") or ""
        token = os.getenv("MILVUS_TOKEN") or os.getenv("ZILLIZ_TOKEN") or ""
        db_name = os.getenv("MILVUS_DB_NAME") or os.getenv("ZILLIZ_DB_NAME") or None
        if db_name and db_name.strip().lower() in {"default", "none", "null"}:
            db_name = None
        return (
            normalize_milvus_uri(uri),
            token.strip(),
            str(db_name).strip() if db_name else None,
        )

    @staticmethod
    def _milvus_db_candidates(db_name: str | None) -> list[str | None]:
        """Try the configured database first, then the Milvus/Zilliz default.

        This keeps explicit deployments working while protecting production from
        stale `MILVUS_DB_NAME` values that point to a database without AcademicRAG
        collections.
        """
        candidates: list[str | None] = []
        configured = str(db_name or "").strip()
        if configured and configured.lower() not in {"none", "null"}:
            # Zilliz serverless tokens can already be scoped to their database.
            # Calling using_database("default") then requires DescribeDatabase,
            # which scoped tokens may intentionally not have. Prefer the implicit
            # connection for "default", while preserving explicit named DBs.
            if configured.lower() == DEFAULT_MILVUS_DB_NAME:
                candidates.extend([None, configured])
            else:
                candidates.extend([configured, None])
        else:
            candidates.append(None)
        return candidates

    @staticmethod
    def _is_milvus_transport_failure(exc: Exception) -> bool:
        message = f"{type(exc).__name__}: {exc}".casefold()
        return any(
            marker in message
            for marker in (
                "deadline_exceeded",
                "timed out",
                "timeout",
                "connection refused",
                "connection reset",
                "failed to connect",
                "name resolution",
                "unavailable",
            )
        )

    @classmethod
    async def _gather_search_results(
        cls,
        labels: list[str],
        tasks: list[Any],
    ) -> dict[str, list[dict[str, Any]]]:
        async def run_one(label: str, task: Any) -> tuple[str, list[dict[str, Any]]]:
            try:
                rows = await asyncio.wait_for(
                    task,
                    timeout=DEFAULT_RETRIEVAL_STAGE_TIMEOUT_SECONDS,
                )
                return label, rows
            except TimeoutError:
                logger.warning(
                    f"Academic GraphRAG retrieval timed out for {label} after "
                    f"{DEFAULT_RETRIEVAL_STAGE_TIMEOUT_SECONDS:.0f}s"
                )
                return label, []
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"Academic GraphRAG retrieval failed for {label}: "
                    f"{type(exc).__name__}: {exc}"
                )
                return label, []

        results = await asyncio.gather(
            *(run_one(label, task) for label, task in zip(labels, tasks, strict=False))
        )
        return dict(results)

    @staticmethod
    def _graph_filter(graph_name: str) -> str:
        safe_graph_name = str(graph_name or "").replace("\\", "\\\\").replace('"', '\\"')
        return f'graphName == "{safe_graph_name}"' if safe_graph_name else ""

    @classmethod
    def _query_terms(cls, query_text: str, *, max_terms: int = 8) -> list[str]:
        return AcademicQueryPlanner.query_terms(query_text, max_terms=max_terms)

    @staticmethod
    def _dedupe_terms(values: list[Any], *, max_terms: int = 8) -> list[str]:
        return AcademicQueryPlanner.dedupe_terms(values, max_terms=max_terms)

    @staticmethod
    def _node_label(node: dict[str, Any]) -> str:
        return AcademicNormalizers._node_label(node)

    @classmethod
    def _publication_nodes_from_graph(
        cls,
        graph: dict[str, Any],
        *,
        max_nodes: int = 8,
    ) -> list[dict[str, Any]]:
        return AcademicNormalizers._publication_nodes_from_graph(graph, max_nodes=max_nodes)

    @classmethod
    def _is_author_publication_query(cls, query_text: str) -> bool:
        return AcademicHeuristics._is_author_publication_query(query_text)

    @classmethod
    def _is_author_publication_enumeration_query(cls, query_text: str) -> bool:
        return AcademicHeuristics._is_author_publication_enumeration_query(query_text)

    @classmethod
    def _extract_author_name_candidates(cls, query_text: str) -> list[str]:
        return AcademicHeuristics._extract_author_name_candidates(query_text)

    @classmethod
    def _is_lecturer_topic_query(cls, query_text: str) -> bool:
        return AcademicHeuristics._is_lecturer_topic_query(query_text)

    @classmethod
    def _is_topic_frequency_query(cls, query_text: str) -> bool:
        return AcademicHeuristics._is_topic_frequency_query(query_text)

    @classmethod
    def _extract_publication_title_candidates(cls, query_text: str) -> list[str]:
        return AcademicHeuristics._extract_publication_title_candidates(query_text)

    @classmethod
    def _has_specific_publication_reference(cls, query_text: str) -> bool:
        return AcademicHeuristics._has_specific_publication_reference(query_text)

    @staticmethod
    def _format_values(value: Any) -> str:
        return _format_values(value)

    @classmethod
    def _department_terms(cls, query_text: str) -> list[str]:
        return AcademicHeuristics._department_terms(query_text)

    @classmethod
    def _topic_terms_for_neo4j(cls, query_text: str) -> list[str]:
        return AcademicHeuristics._topic_terms_for_neo4j(query_text)

    @classmethod
    def _is_collaboration_query(cls, query_text: str) -> bool:
        return AcademicHeuristics._is_collaboration_query(query_text)

    @classmethod
    def normalize_author_publication_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        query_text: str = "",
        max_chunks: int = 12,
        max_chars: int = 1800,
    ) -> list[dict[str, Any]]:
        return AcademicNormalizers.normalize_author_publication_chunks(
            rows, query_text=query_text, max_chunks=max_chunks, max_chars=max_chars
        )

    @classmethod
    def normalize_lecturer_topic_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 12,
        max_chars: int = 1800,
    ) -> list[dict[str, Any]]:
        return AcademicNormalizers.normalize_lecturer_topic_chunks(
            rows, max_chunks=max_chunks, max_chars=max_chars
        )

    @classmethod
    def normalize_publication_detail_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 8,
        max_chars: int = 2200,
    ) -> list[dict[str, Any]]:
        return AcademicNormalizers.normalize_publication_detail_chunks(
            rows, max_chunks=max_chunks, max_chars=max_chars
        )

    @classmethod
    def normalize_topic_frequency_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 15,
    ) -> list[dict[str, Any]]:
        return AcademicNormalizers.normalize_topic_frequency_chunks(rows, max_chunks=max_chunks)

    @classmethod
    def normalize_collaboration_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 12,
    ) -> list[dict[str, Any]]:
        return AcademicNormalizers.normalize_collaboration_chunks(rows, max_chunks=max_chunks)

    @classmethod
    async def query_collaborations(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 40,
        skip_intent_check: bool = False,
        extracted_entities: dict[str, Any] | None = None,
        sub_intents: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return await AcademicNeo4jQueries.query_collaborations(
            query_text,
            graph_name=graph_name,
            limit=limit,
            skip_intent_check=skip_intent_check,
            extracted_entities=extracted_entities,
            sub_intents=sub_intents,
        )

    @classmethod
    async def query_author_publications(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 60,
        skip_intent_check: bool = False,
        extracted_entities: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return await AcademicNeo4jQueries.query_author_publications(
            query_text,
            graph_name=graph_name,
            limit=limit,
            skip_intent_check=skip_intent_check,
            extracted_entities=extracted_entities,
            **kwargs,
        )

    @classmethod
    async def query_publication_details(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 12,
        extracted_entities: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return await AcademicNeo4jQueries.query_publication_details(
            query_text,
            graph_name=graph_name,
            limit=limit,
            extracted_entities=extracted_entities,
            **kwargs,
        )

    @classmethod
    async def query_topic_frequencies(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 15,
        skip_intent_check: bool = False,
        extracted_entities: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return await AcademicNeo4jQueries.query_topic_frequencies(
            query_text,
            graph_name=graph_name,
            limit=limit,
            skip_intent_check=skip_intent_check,
            extracted_entities=extracted_entities,
            **kwargs,
        )

    @classmethod
    async def query_lecturer_topic_publications(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 40,
        skip_intent_check: bool = False,
        extracted_entities: dict[str, Any] | None = None,
        sub_intents: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return await AcademicNeo4jQueries.query_lecturer_topic_publications(
            query_text,
            graph_name=graph_name,
            limit=limit,
            skip_intent_check=skip_intent_check,
            extracted_entities=extracted_entities,
            sub_intents=sub_intents,
        )

    @classmethod
    async def query_papers_by_topic(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 40,
        start_year: int | None = None,
        end_year: int | None = None,
        skip_intent_check: bool = False,
    ) -> list[dict[str, Any]]:
        return await AcademicNeo4jQueries.query_papers_by_topic(
            query_text,
            graph_name=graph_name,
            limit=limit,
            start_year=start_year,
            end_year=end_year,
            skip_intent_check=skip_intent_check,
        )

    @classmethod
    def _content_keyword_terms(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_terms: int = 16,
    ) -> list[str]:
        return AcademicQueryPlanner.content_keyword_terms(rows, max_terms=max_terms)

    @classmethod
    def decompose_query_keywords(
        cls,
        query_text: str,
        keyword_rows: list[dict[str, Any]] | None,
        *,
        max_terms: int = 8,
    ) -> dict[str, Any]:
        """Build AcademicRAG-style high/low keyword clues for local/global retrieval."""
        return AcademicQueryPlanner.decompose_keywords(
            query_text,
            keyword_rows,
            max_terms=max_terms,
        ).as_dict()

    @staticmethod
    def _use_llm_keyword_extraction() -> bool:
        mode = os.getenv("YUNESA_ACADEMIC_KEYWORD_EXTRACTION_MODE", "llm")
        return mode.strip().lower() in {"llm", "model", "academicrag"}

    @staticmethod
    async def _default_keyword_extractor(prompt: str) -> str:
        from yunesa.models import select_model

        model = select_model()
        response = await model.call(prompt, stream=False)
        return str(getattr(response, "content", response) or "")

    @classmethod
    async def extract_keywords_with_keyword_clues(
        cls,
        query_text: str,
        keyword_rows: list[dict[str, Any]] | None,
        *,
        max_terms: int = 8,
        history: str = "",
        keyword_extractor: KeywordExtractor | None = None,
    ) -> dict[str, Any]:
        """Extract high/low keywords with the AcademicRAG prompt contract.

        The reference AcademicRAG implementation uses the keywords vector index
        as clues, prompts the LLM, parses JSON, and falls back by switching KG
        modes when one side is empty. This service keeps the same prompt/JSON
        contract while allowing a deterministic fallback for production latency
        or provider failures.
        """
        fallback = AcademicQueryPlanner.decompose_keywords(
            query_text,
            keyword_rows,
            max_terms=max_terms,
            history=history,
        )
        extractor = keyword_extractor
        if extractor is None and cls._use_llm_keyword_extraction():
            extractor = cls._default_keyword_extractor
        if extractor is None:
            return fallback.as_dict()

        try:
            raw_response = extractor(fallback.prompt)
            if asyncio.iscoroutine(raw_response):
                raw_response = await raw_response
            llm_plan = AcademicQueryPlanner.plan_from_model_response(
                query_text=query_text,
                keyword_rows=keyword_rows,
                raw_response=str(raw_response or ""),
                max_terms=max_terms,
                history=history,
            )
            if llm_plan is not None:
                return llm_plan.as_dict()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "AcademicRAG keyword extraction fell back to heuristic: "
                f"{type(exc).__name__}: {exc}"
            )
        return fallback.as_dict()

    @classmethod
    def _keyword_query(cls, keywords: list[Any], fallback: str) -> str:
        terms = cls._dedupe_terms(keywords, max_terms=16)
        return ", ".join(terms) if terms else fallback

    @staticmethod
    def _milvus_literal(value: str) -> str:
        return str(value or "").replace("\\", "\\\\").replace('"', '\\"')

    @classmethod
    def _lexical_filter(cls, *, query_text: str, graph_name: str, text_fields: list[str]) -> str:
        graph_filter = cls._graph_filter(graph_name)
        terms = cls._query_terms(query_text)
        if not terms or not text_fields:
            return graph_filter

        term_clauses: list[str] = []
        for term in terms:
            safe_term = cls._milvus_literal(term)
            field_clauses = [f'{field} like "%{safe_term}%"' for field in text_fields]
            term_clauses.append("(" + " || ".join(field_clauses) + ")")
        text_filter = "(" + " || ".join(term_clauses) + ")"
        return f"{graph_filter} && {text_filter}" if graph_filter else text_filter

    @classmethod
    def _rank_rows_by_terms(
        cls,
        rows: list[dict[str, Any]],
        *,
        query_text: str,
        text_fields: list[str],
        top_k: int,
    ) -> list[dict[str, Any]]:
        terms = cls._query_terms(query_text)
        if not terms:
            return rows[:top_k]

        ranked: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            haystack = " ".join(str(row.get(field) or "") for field in text_fields).lower()
            score = sum(1 for term in terms if term in haystack)
            if score > 0:
                ranked.append((score, row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in ranked[:top_k]]

    @staticmethod
    def _hit_to_row(hit: Any) -> dict[str, Any]:
        if isinstance(hit, dict):
            row = dict(hit.get("entity") or hit)
            if "distance" in hit:
                row["distance"] = hit["distance"]
            elif "score" in hit:
                row["distance"] = hit["score"]
            return row
        entity = getattr(hit, "entity", None)
        row = dict(entity or {})
        distance = getattr(hit, "distance", None)
        if distance is not None:
            row["distance"] = distance
        return row

    @classmethod
    def _embed_queries(cls, query_texts: list[str]) -> dict[str, list[float]]:
        provider = DEFAULT_ACADEMIC_EMBEDDING_PROVIDER.strip().lower().replace("-", "_")
        if provider in {"lexical", "none", "disabled"}:
            raise RuntimeError("Dense embedding is disabled by Academic GraphRAG configuration.")
        if provider not in {"siliconflow", "silicon_flow"}:
            raise RuntimeError(f"Unsupported backend embedding provider: {provider}")

        api_key = os.getenv("SILICONFLOW_API_KEY")
        if not api_key:
            raise RuntimeError("SILICONFLOW_API_KEY is not configured.")

        texts: list[str] = []
        seen: set[str] = set()
        for query_text in query_texts:
            text = re.sub(r"\s+", " ", str(query_text or "")).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            texts.append(text)
        if not texts:
            return {}

        import requests

        response = requests.post(
            os.getenv("SILICONFLOW_EMBEDDING_URL", "https://api.siliconflow.com/v1/embeddings"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEFAULT_ACADEMIC_EMBEDDING_MODEL,
                "input": texts,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        response_rows = response.json().get("data") or []
        vectors: dict[str, list[float]] = {}
        for position, row in enumerate(response_rows):
            index = int(row.get("index", position))
            if index >= len(texts):
                continue
            vector = row.get("embedding")
            if vector:
                vectors[texts[index]] = [float(value) for value in vector]
        if len(vectors) != len(texts):
            raise RuntimeError("SiliconFlow embedding response is empty.")
        return vectors

    @classmethod
    def _embed_query(cls, query_text: str) -> list[float]:
        text = str(query_text or "").strip()
        return cls._embed_queries([text])[text]

    @classmethod
    async def _search_academic_collection(
        cls,
        *,
        query_text: str,
        collection_name: str,
        output_fields: list[str],
        text_fields: list[str],
        top_k: int,
        graph_name: str,
        query_vector: list[float] | None = None,
        embed_if_missing: bool = True,
    ) -> list[dict[str, Any]]:
        if not cls._academic_milvus_enabled():
            return []
        uri, token, db_name = cls._milvus_credentials()
        if not uri or not token:
            return []

        try:
            vector = query_vector
            if vector is None and embed_if_missing:
                vector = await asyncio.to_thread(cls._embed_query, query_text)
            if vector is None:
                raise RuntimeError("Dense query vector is unavailable.")
            for candidate_db in cls._milvus_db_candidates(db_name):
                try:
                    client = await asyncio.to_thread(
                        _cached_milvus_client,
                        uri,
                        token,
                        candidate_db,
                    )
                    raw_hits = await asyncio.to_thread(
                        client.search,
                        collection_name=collection_name,
                        data=[vector],
                        anns_field="embedding",
                        limit=top_k,
                        output_fields=output_fields,
                        search_params={"metric_type": os.getenv("YUNESA_MILVUS_METRIC_TYPE", "L2")},
                        filter=cls._graph_filter(graph_name) if collection_name != "community_summaries" else None,
                        timeout=DEFAULT_MILVUS_TIMEOUT_SECONDS,
                    )
                    if candidate_db != db_name:
                        logger.info(
                            f"Academic GraphRAG dense search used Milvus database "
                            f"{candidate_db or '<implicit>'} for {collection_name}"
                        )
                    return [cls._hit_to_row(hit) for hit in (raw_hits[0] if raw_hits else [])]
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        f"Academic GraphRAG dense search failed for {collection_name} "
                        f"on Milvus database {candidate_db or '<implicit>'}: {type(exc).__name__}: {exc}"
                    )
                    if cls._is_milvus_transport_failure(exc):
                        return []
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                f"Academic GraphRAG dense search skipped for {collection_name}; "
                f"falling back to lexical query: {type(exc).__name__}: {exc}"
            )

        for candidate_db in cls._milvus_db_candidates(db_name):
            try:
                client = await asyncio.to_thread(
                    _cached_milvus_client,
                    uri,
                    token,
                    candidate_db,
                )
                rows = await asyncio.to_thread(
                    client.query,
                    collection_name=collection_name,
                    filter=cls._lexical_filter(
                        query_text=query_text,
                        graph_name=graph_name,
                        text_fields=text_fields,
                    ),
                    output_fields=output_fields,
                    limit=top_k,
                    timeout=DEFAULT_MILVUS_TIMEOUT_SECONDS,
                )
                if candidate_db != db_name:
                    logger.info(
                        f"Academic GraphRAG lexical query used Milvus database "
                        f"{candidate_db or '<implicit>'} for {collection_name}"
                    )
                return [dict(row) for row in rows or []]
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    f"Academic GraphRAG lexical query failed for {collection_name} "
                    f"on Milvus database {candidate_db or '<implicit>'}: {exc}"
                )
                if cls._is_milvus_transport_failure(exc):
                    return []

        for candidate_db in cls._milvus_db_candidates(db_name):
            try:
                client = await asyncio.to_thread(
                    _cached_milvus_client,
                    uri,
                    token,
                    candidate_db,
                )
                rows = await asyncio.to_thread(
                    client.query,
                    collection_name=collection_name,
                    filter=cls._graph_filter(graph_name),
                    output_fields=output_fields,
                    limit=max(top_k * 20, 100),
                    timeout=DEFAULT_MILVUS_TIMEOUT_SECONDS,
                )
                if candidate_db != db_name:
                    logger.info(
                        f"Academic GraphRAG graph-filter fallback used Milvus database "
                        f"{candidate_db or '<implicit>'} for {collection_name}"
                    )
                return cls._rank_rows_by_terms(
                    [dict(row) for row in rows or []],
                    query_text=query_text,
                    text_fields=text_fields,
                    top_k=top_k,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    f"Academic GraphRAG fallback query failed for {collection_name} "
                    f"on Milvus database {candidate_db or '<implicit>'}: {exc}"
                )
                if cls._is_milvus_transport_failure(exc):
                    return []
        logger.warning(f"Academic GraphRAG vector retrieval returned no rows for {collection_name}")
        return []

    @classmethod
    async def query_academic_indexes(
        cls,
        query_text: str,
        *,
        retrieval_mode: str = "hybrid",
        graph_name: str | None = None,
        top_k: int = 8,
        keyword_top_k: int = 8,
        keyword_extractor: KeywordExtractor | None = None,
        vector_storage: BaseVectorStorage | None = None,
        graph_storage: BaseGraphStorage | None = None,
    ) -> dict[str, Any]:
        """Retrieve from canonical AcademicRAG indexes produced by the notebook pipeline."""
        started_at = time.perf_counter()
        query_param = AcademicQueryParam.from_runtime(
            retrieval_mode,
            top_k=top_k,
            keyword_top_k=keyword_top_k,
        )
        mode = query_param.runtime_mode
        resolved_graph_name = cls._academic_graph_name(graph_name)
        payload: dict[str, Any] = {
            "status": "skipped",
            "mode": mode,
            "academicrag_mode": query_param.mode,
            "kg_mode": query_param.resolved_kg_mode(),
            "graph_name": resolved_graph_name,
            "milvus_database": (cls._milvus_credentials()[2] or DEFAULT_MILVUS_DB_NAME),
            "paper_chunks": [],
            "keywords": [],
            "entities": [],
            "relationships": [],
            "subgraph": {"nodes": [], "edges": [], "status": "skipped"},
            "keyword_decomposition": {},
            "local_query": query_text,
            "global_query": query_text,
            "route_plan": query_param.route_plan(),
            "diagnostics": {
                "embedding_batches": 0,
                "dense_embedding_status": "not_requested",
            },
        }
        if not cls._academic_milvus_enabled():
            payload["status"] = "disabled"
            return payload

        vector_store = vector_storage or MilvusVectorStorage(
            cls._search_academic_collection
        )
        first_layers = query_param.route_plan()["layers"]
        needs_clues = first_layers["clues"]
        needs_raw_papers = first_layers["raw_vector"]

        query_vectors: dict[str, list[float]] = {}
        try:
            query_vectors = await asyncio.to_thread(cls._embed_queries, [query_text])
            payload["diagnostics"]["embedding_batches"] += 1
            payload["diagnostics"]["dense_embedding_status"] = "ready"
        except Exception as exc:  # noqa: BLE001
            payload["diagnostics"]["dense_embedding_status"] = "lexical_fallback"
            payload["diagnostics"]["embedding_error_type"] = type(exc).__name__

        first_tasks = []
        first_labels = []
        if needs_raw_papers:
            first_labels.append("paper_chunks")
            first_tasks.append(
                vector_store.query(
                    query_text=query_text,
                    collection_name=ACADEMIC_COLLECTIONS["paper_chunks"],
                    output_fields=["graphName", "title", "content", "year", "paperUrl", "authors"],
                    text_fields=["title", "content", "authors"],
                    top_k=top_k,
                    graph_name=resolved_graph_name,
                    query_vector=query_vectors.get(query_text),
                    embed_if_missing=False,
                )
            )
        if needs_clues:
            first_labels.append("keywords")
            first_tasks.append(
                vector_store.query(
                    query_text=query_text,
                    collection_name=ACADEMIC_COLLECTIONS["content_keywords"],
                    output_fields=["graphName", "keywords", "sourcePaper"],
                    text_fields=["keywords", "sourcePaper"],
                    top_k=keyword_top_k,
                    graph_name=resolved_graph_name,
                    query_vector=query_vectors.get(query_text),
                    embed_if_missing=False,
                )
            )

        if first_tasks:
            payload.update(
                await cls._gather_search_results(first_labels, first_tasks)
            )

        if needs_clues:
            decomposition = await cls.extract_keywords_with_keyword_clues(
                query_text,
                payload["keywords"],
                max_terms=max(keyword_top_k, 1),
                keyword_extractor=keyword_extractor,
            )
            payload["keyword_decomposition"] = decomposition
            query_param.with_keywords(
                high_level_keywords=decomposition.get("high_level_keywords"),
                low_level_keywords=decomposition.get("low_level_keywords"),
            )
            payload["kg_mode"] = query_param.resolved_kg_mode()
            payload["route_plan"] = query_param.route_plan()
            payload["local_query"] = cls._keyword_query(
                decomposition["low_level_keywords"],
                query_text,
            )
            payload["global_query"] = cls._keyword_query(
                decomposition["high_level_keywords"],
                query_text,
            )

        second_layers = query_param.route_plan()["layers"]
        needs_fused_papers = second_layers["fused_vector"]
        needs_local = second_layers["local"]
        needs_global = second_layers["global"]
        fused_query = cls._keyword_query(
            [
                *(payload["keyword_decomposition"].get("low_level_keywords") or []),
                *(payload["keyword_decomposition"].get("high_level_keywords") or []),
            ],
            query_text,
        )
        secondary_queries: list[str] = []
        if needs_fused_papers:
            secondary_queries.append(fused_query)
        if needs_local:
            secondary_queries.append(payload["local_query"])
        if needs_global:
            secondary_queries.append(payload["global_query"])

        missing_queries = [query for query in secondary_queries if query not in query_vectors]
        if missing_queries and payload["diagnostics"]["dense_embedding_status"] == "ready":
            try:
                query_vectors.update(
                    await asyncio.to_thread(cls._embed_queries, missing_queries)
                )
                payload["diagnostics"]["embedding_batches"] += 1
            except Exception as exc:  # noqa: BLE001
                payload["diagnostics"]["dense_embedding_status"] = "partial_lexical_fallback"
                payload["diagnostics"]["secondary_embedding_error_type"] = type(exc).__name__

        second_tasks = []
        second_labels = []
        if needs_fused_papers:
            second_labels.append("paper_chunks")
            second_tasks.append(
                vector_store.query(
                    query_text=fused_query,
                    collection_name=ACADEMIC_COLLECTIONS["paper_chunks"],
                    output_fields=["graphName", "title", "content", "year", "paperUrl", "authors"],
                    text_fields=["title", "content", "authors"],
                    top_k=top_k,
                    graph_name=resolved_graph_name,
                    query_vector=query_vectors.get(fused_query),
                    embed_if_missing=False,
                )
            )
        if needs_local:
            second_labels.append("entities")
            second_tasks.append(
                vector_store.query(
                    query_text=payload["local_query"],
                    collection_name=ACADEMIC_COLLECTIONS["entities"],
                    output_fields=["graphName", "entityName", "entityType", "description", "nodeId", "sourceId"],
                    text_fields=["entityName", "entityType", "description"],
                    top_k=top_k,
                    graph_name=resolved_graph_name,
                    query_vector=query_vectors.get(payload["local_query"]),
                    embed_if_missing=False,
                )
            )
        if needs_global:
            second_labels.append("relationships")
            second_tasks.append(
                vector_store.query(
                    query_text=payload["global_query"],
                    collection_name=ACADEMIC_COLLECTIONS["relationships"],
                    output_fields=["graphName", "srcId", "tgtId", "relType", "description", "sourceId"],
                    text_fields=["srcId", "tgtId", "relType", "description"],
                    top_k=top_k,
                    graph_name=resolved_graph_name,
                    query_vector=query_vectors.get(payload["global_query"]),
                    embed_if_missing=False,
                )
            )
            second_labels.append("community_summaries")
            second_tasks.append(
                vector_store.query(
                    query_text=payload["global_query"],
                    collection_name="community_summaries",
                    output_fields=["id", "community_id", "content"],
                    text_fields=["content"],
                    top_k=int(os.getenv("YUNESA_COMMUNITY_TOP_K", "3")),
                    graph_name=resolved_graph_name,
                    query_vector=query_vectors.get(payload["global_query"]),
                    embed_if_missing=False,
                )
            )

        if second_tasks:
            payload.update(
                await cls._gather_search_results(second_labels, second_tasks)
            )

        # Mentioned entity matching (Neo4j lookup)
        mentioned_entities = await match_mentioned_entities(
            query_text, graph_storage, resolved_graph_name
        )
        existing_entities = payload.get("entities", []) or []
        seen_node_ids = {m.get("nodeId") for m in mentioned_entities if m.get("nodeId")}
        merged_entities = list(mentioned_entities)
        for ent in existing_entities:
            nid = ent.get("nodeId")
            if nid and nid not in seen_node_ids:
                seen_node_ids.add(nid)
                merged_entities.append(ent)
        
        # Degree reranking for entities
        if merged_entities:
            merged_entities = await degree_rerank_entities(
                merged_entities, graph_storage, resolved_graph_name
            )
        payload["entities"] = merged_entities[:top_k]

        # Degree reranking for relationships
        relationships = payload.get("relationships", []) or []
        if relationships:
            relationships = await degree_rerank_relationships(
                relationships, graph_storage, resolved_graph_name
            )
        payload["relationships"] = relationships[:top_k]

        # Reciprocal Rank Fusion (RRF) for paper chunks
        paper_chunks = payload.get("paper_chunks", []) or []
        entity_ids = [row.get("nodeId") for row in payload.get("entities", []) if row.get("nodeId")]
        if paper_chunks and entity_ids:
            graph_ranks = await graph_connection_rank(
                paper_chunks, entity_ids, graph_storage, resolved_graph_name
            )
            paper_chunks = reciprocal_rank_fusion(paper_chunks, graph_ranks)
        
        # Cross-Encoder Reranker for paper chunks
        if paper_chunks:
            paper_chunks = await rerank_documents(query_text, paper_chunks, top_k=top_k)
        payload["paper_chunks"] = paper_chunks

        node_ids = cls._dedupe_terms(
            [
                row.get("nodeId")
                for row in payload.get("entities", [])
                if row.get("nodeId")
            ],
            max_terms=8,
        )
        payload["subgraph"] = (
            await cls._query_shortest_path_subgraph(
                node_ids,
                graph_name=resolved_graph_name,
                relationship_rows=payload.get("relationships"),
                graph_storage=graph_storage,
                max_nodes=80,
            )
            if needs_local and node_ids
            else {"nodes": [], "edges": [], "status": "skipped"}
        )
        payload["status"] = (
            "ok"
            if any(
                payload.get(key)
                for key in ("paper_chunks", "keywords", "entities", "relationships")
            )
            else "empty"
        )
        payload["diagnostics"]["duration_seconds"] = round(
            time.perf_counter() - started_at,
            3,
        )
        return payload

    @classmethod
    def normalize_chunks(
        cls,
        chunks: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 8,
        max_chars: int = 1200,
    ) -> list[dict[str, Any]]:
        return AcademicNormalizers.normalize_chunks(
            chunks, max_chunks=max_chunks, max_chars=max_chars
        )

    @classmethod
    def normalize_academic_paper_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 8,
        max_chars: int = 1200,
    ) -> list[dict[str, Any]]:
        return AcademicNormalizers.normalize_academic_paper_chunks(
            rows, max_chunks=max_chunks, max_chars=max_chars
        )

    @staticmethod
    def _triples_from_graph(graph: dict[str, Any]) -> list[dict[str, str]]:
        return AcademicEvidence._triples_from_graph(graph)

    @classmethod
    def _fallback_graph_terms(cls, query_text: str, max_terms: int = 6) -> list[str]:
        return AcademicEvidence._fallback_graph_terms(query_text, max_terms=max_terms)

    @staticmethod
    def _merge_graph_results(results: list[dict[str, Any]], max_nodes: int) -> dict[str, Any]:
        return AcademicEvidence._merge_graph_results(results, max_nodes=max_nodes)

    @staticmethod
    def _virtual_id(node_type: str, value: Any) -> str:
        return AcademicEvidence._virtual_id(node_type, value)

    @staticmethod
    def _structured_node_id(node_type: str, node_id: Any) -> str:
        return AcademicEvidence._structured_node_id(node_type, node_id)

    @classmethod
    def _dedupe_evidence_chunks(
        cls,
        chunks: list[dict[str, Any]],
        *,
        max_chunks: int = 24,
    ) -> list[dict[str, Any]]:
        return AcademicEvidence._dedupe_evidence_chunks(chunks, max_chunks=max_chunks)

    @classmethod
    def _map_structured_rows_to_graph(
        cls,
        academic: dict[str, Any] | None,
    ) -> dict[str, list[dict[str, Any]]]:
        return AcademicEvidence._map_structured_rows_to_graph(academic)

    @staticmethod
    def _prune_shortest_path_graph(
        graph: dict[str, Any],
        relationship_rows: list[dict[str, Any]] | None,
        *,
        seed_node_ids: list[str],
    ) -> dict[str, Any]:
        return AcademicEvidence._prune_shortest_path_graph(
            graph, relationship_rows, seed_node_ids=seed_node_ids
        )

    @classmethod
    async def _query_shortest_path_subgraph(
        cls,
        node_ids: list[str],
        *,
        graph_name: str,
        relationship_rows: list[dict[str, Any]] | None,
        graph_storage: BaseGraphStorage | None = None,
        max_nodes: int = 80,
    ) -> dict[str, Any]:
        return await AcademicEvidence._query_shortest_path_subgraph(
            node_ids,
            graph_name=graph_name,
            relationship_rows=relationship_rows,
            graph_storage=graph_storage,
            max_nodes=max_nodes,
        )

    @staticmethod
    def _encode_string_by_tiktoken(content: str, model_name: str = "gpt-4") -> list[int]:
        return AcademicEvidence._encode_string_by_tiktoken(content, model_name=model_name)

    @classmethod
    def _truncate_list_by_token_size(
        cls,
        list_data: list[Any],
        key: Callable[[Any], str],
        max_token_size: int,
        model_name: str = "gpt-4",
    ) -> list[Any]:
        return AcademicEvidence._truncate_list_by_token_size(
            list_data, key=key, max_token_size=max_token_size, model_name=model_name
        )

    @classmethod
    def _compact_evidence_text(
        cls,
        chunks: list[dict[str, Any]],
        graph: dict[str, Any],
        academic: dict[str, Any] | None = None,
        grounding: dict[str, Any] | None = None,
        mode: str = "hybrid",
    ) -> str:
        return AcademicEvidence._compact_evidence_text(
            chunks, graph, academic=academic, grounding=grounding, mode=mode
        )

    @staticmethod
    def _graph_summary(graph: dict[str, Any]) -> dict[str, Any]:
        return AcademicEvidence._graph_summary(graph)

    @classmethod
    def _context_summary(cls, payload: dict[str, Any], duration_seconds: float) -> dict[str, Any]:
        return AcademicEvidence._context_summary(payload, duration_seconds=duration_seconds)

    @classmethod
    def _grounding_status(
        cls,
        chunks: list[dict[str, Any]],
        graph: dict[str, Any],
        academic: dict[str, Any],
        query_text: str = "",
    ) -> dict[str, Any]:
        return AcademicEvidence._grounding_status(
            chunks, graph, academic, query_text=query_text
        )

    async def query_graph(
        self,
        query_text: str,
        *,
        max_depth: int = 1,
        max_nodes: int = 30,
        graph_name: str | None = None,
        seed_terms: list[str] | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        with opik_span(
            "academic_graphrag.graph_retrieval",
            type="tool",
            input={
                "query": query_text,
                "max_depth": max_depth,
                "max_nodes": max_nodes,
                "graph_name": graph_name,
                "seed_terms": seed_terms or [],
            },
            metadata={"storage": "neo4j_aura"},
            tags=["graph-retrieval", "neo4j"],
        ) as span:
            graph = await self._query_graph_impl(
                query_text,
                max_depth=max_depth,
                max_nodes=max_nodes,
                graph_name=graph_name,
                seed_terms=seed_terms,
            )
            set_observation_output(
                span,
                output=self._graph_summary(graph),
                metadata={"duration_seconds": round(time.perf_counter() - started_at, 3)},
            )
            return graph

    async def _query_graph_impl(
        self,
        query_text: str,
        *,
        max_depth: int = 1,
        max_nodes: int = 30,
        graph_name: str | None = None,
        seed_terms: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            from yunesa import graph_base

            if hasattr(graph_base, "start") and not graph_base.is_running():
                graph_base.start()
            if not graph_base.is_running():
                return {"nodes": [], "edges": [], "triples": [], "status": "unavailable"}

            from yunesa.knowledge.graphrag.query_planner import GRAPH_STOPWORDS
            terms = self._dedupe_terms(
                [
                    term
                    for term in (seed_terms or [])
                    if str(term).strip().lower() not in GRAPH_STOPWORDS
                ],
                max_terms=3,
            )
            if not terms:
                # Filter query_text too if it's just a stopword
                clean_query = query_text
                if str(query_text).strip().lower() in GRAPH_STOPWORDS:
                    clean_query = ""
                terms = [clean_query] if clean_query else []

            async def _query_with_timeout(term: str) -> dict[str, Any]:
                try:
                    return await asyncio.wait_for(
                        asyncio.to_thread(
                            graph_base.query_subgraph,
                            keyword=term,
                            max_depth=max_depth,
                            max_nodes=max_nodes,
                            graph_name=graph_name,
                        ),
                        timeout=15.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Neo4j query timeout for term '{term}' (15s)")
                    return {"nodes": [], "edges": []}
                except Exception as e:
                    logger.warning(f"Neo4j query failed for term '{term}': {e}")
                    raise

            try:
                graph_results = await asyncio.gather(
                    *[_query_with_timeout(term) for term in terms],
                    return_exceptions=False
                )
            except Exception as e:
                logger.error(f"Circuit breaker triggered: Neo4j failure in batch query: {e}")
                return {"nodes": [], "edges": [], "triples": [], "status": "error"}

            graph = self._merge_graph_results(graph_results, max_nodes=max_nodes)
            if not graph.get("nodes") and terms != [query_text]:
                try:
                    graph = await _query_with_timeout(query_text)
                except Exception as e:
                    logger.error(f"Circuit breaker triggered on fallback query: {e}")
                    return {"nodes": [], "edges": [], "triples": [], "status": "error"}

            if not graph.get("nodes"):
                fallback_terms = self._fallback_graph_terms(query_text)
                if fallback_terms:
                    try:
                        fallback_results = await asyncio.gather(
                            *[_query_with_timeout(term) for term in fallback_terms],
                            return_exceptions=False
                        )
                        graph = self._merge_graph_results(
                            fallback_results,
                            max_nodes=max_nodes,
                        )
                    except Exception as e:
                        logger.error(f"Circuit breaker triggered on fallback terms: {e}")
                        return {"nodes": [], "edges": [], "triples": [], "status": "error"}

            graph["triples"] = self._triples_from_graph(graph)
            graph["status"] = "ok"
            return graph
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Academic GraphRAG graph retrieval failed: {exc}")
            return {
                "nodes": [],
                "edges": [],
                "triples": [],
                "status": "error",
                "message": str(exc),
            }

    async def build_context_package(
        self,
        *,
        query_text: str,
        original_query_text: str | None = None,
        chunks: list[dict[str, Any]] | None,
        kb_name: str,
        collection_id: str | None = None,
        retrieval_mode: str = "hybrid",
        include_graph: bool = True,
        graph_max_depth: int = 2,
        graph_max_nodes: int = 80,
        graph_name: str | None = None,
        trace_metadata: dict[str, Any] | None = None,
        routing_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        intent_query = str(original_query_text or query_text).strip()
        semantic_query = intent_query or query_text
        with opik_span(
            "academic_graphrag.build_context_package",
            type="tool",
            input={
                "query": query_text,
                "original_query": intent_query,
                "kb_name": kb_name,
                "collection_id": collection_id,
                "retrieval_mode": retrieval_mode,
                "include_graph": include_graph,
                "graph_max_depth": graph_max_depth,
                "graph_max_nodes": graph_max_nodes,
                "graph_name": graph_name,
                "input_chunks": len(chunks or []),
            },
            metadata={
                "storage": "milvus+neo4j",
                "service": "query_kb",
                **(trace_metadata or {}),
            },
            tags=["context-assembly", "hybrid-retrieval"],
        ) as span:
            requested_mode = self.normalize_mode(retrieval_mode, include_graph=include_graph)
            route_decision = self.route_retrieval_mode(
                intent_query,
                requested_mode=requested_mode,
                include_graph=include_graph,
            )
            mode = str(route_decision["effective_mode"])
            resolved_graph_name = self._academic_graph_name(graph_name)
            # Extract entities and sub-intents from routing_metadata
            routing_metadata = routing_metadata or {}
            extracted_entities = routing_metadata.get("entities")
            sub_intents = routing_metadata.get("sub_intents") or []

            if extracted_entities is not None:
                author_publication_enumeration_query = "author_publications" in sub_intents and any(
                    marker in intent_query.lower() for marker in ("daftar", "list", "apa saja", "show")
                )
            else:
                author_publication_enumeration_query = (
                    self._is_author_publication_enumeration_query(intent_query)
                )
            author_publication_context_limit = int(
                os.getenv("YUNESA_AUTHOR_PUBLICATION_CONTEXT_LIMIT", "12")
            )
            author_publication_limit = int(
                os.getenv(
                    "YUNESA_AUTHOR_PUBLICATION_QUERY_LIMIT",
                    str(DEFAULT_STRUCTURED_ENUMERATION_LIMIT),
                )
            )
            author_publication_window = (
                author_publication_limit
                if author_publication_enumeration_query
                else author_publication_context_limit
            )

            # Graceful fallback: skip structured queries if intent is vector_search
            # or if routing_metadata is empty/lacks valid entities.
            skip_structured_queries = False
            if routing_metadata:
                detected_intent = routing_metadata.get("detected_intent", "hybrid_search")
                if detected_intent == "vector_search":
                    skip_structured_queries = True
                elif not extracted_entities or (
                    not extracted_entities.get("author_names") and
                    not extracted_entities.get("topics") and
                    not extracted_entities.get("publication_title")
                ):
                    skip_structured_queries = True

            if skip_structured_queries:
                mode = "vector"

            if not skip_structured_queries:
                # Run all queries in parallel using asyncio.gather to reduce latency
                (
                    academic_raw,
                    author_publications_raw,
                    publication_details,
                    lecturer_topic_publications,
                    topic_frequencies,
                    collaborations,
                ) = await asyncio.gather(
                    self.query_academic_indexes(
                        semantic_query,
                        retrieval_mode=mode,
                        graph_name=resolved_graph_name,
                        top_k=int(os.getenv("YUNESA_ACADEMIC_GRAPHRAG_TOP_K", "8")),
                        keyword_top_k=int(os.getenv("YUNESA_ACADEMIC_GRAPHRAG_KEYWORD_TOP_K", "8")),
                    ),
                    self.query_author_publications(
                        intent_query,
                        graph_name=resolved_graph_name,
                        limit=author_publication_window + 1,
                        extracted_entities=extracted_entities,
                        sub_intents=sub_intents,
                    ),
                    self.query_publication_details(
                        intent_query,
                        graph_name=resolved_graph_name,
                        limit=int(os.getenv("YUNESA_PUBLICATION_DETAIL_QUERY_LIMIT", "12")),
                        extracted_entities=extracted_entities,
                        sub_intents=sub_intents,
                    ),
                    self.query_lecturer_topic_publications(
                        intent_query,
                        graph_name=resolved_graph_name,
                        limit=int(os.getenv("YUNESA_LECTURER_TOP_QUERY_LIMIT", "60")),
                        extracted_entities=extracted_entities,
                        sub_intents=sub_intents,
                    ),
                    self.query_topic_frequencies(
                        intent_query,
                        graph_name=resolved_graph_name,
                        limit=int(os.getenv("YUNESA_TOPIC_FREQUENCY_QUERY_LIMIT", "15")),
                        extracted_entities=extracted_entities,
                        sub_intents=sub_intents,
                    ),
                    self.query_collaborations(
                        intent_query,
                        graph_name=resolved_graph_name,
                        limit=int(os.getenv("YUNESA_COLLABORATION_QUERY_LIMIT", "40")),
                        extracted_entities=extracted_entities,
                        sub_intents=sub_intents,
                    ),
                )
                academic = dict(academic_raw or {})
                academic["route_decision"] = route_decision
                author_publications_capped = len(author_publications_raw) > author_publication_window
                author_publications = author_publications_raw[:author_publication_window]
                academic["author_publications"] = author_publications
                academic.setdefault("structured_counts", {})["author_publications"] = {
                    "returned": len(author_publications),
                    "limit": author_publication_window,
                    "complete": not author_publications_capped,
                    "enumeration_query": author_publication_enumeration_query,
                }
            else:
                academic = {
                    "paper_chunks": [],
                    "entities": [],
                    "keyword_decomposition": {},
                    "route_decision": route_decision,
                }
                # Even if structured queries are skipped, we still need to run vector search for vector mode!
                if mode == "vector":
                    academic_raw = await self.query_academic_indexes(
                        semantic_query,
                        retrieval_mode=mode,
                        graph_name=resolved_graph_name,
                        top_k=int(os.getenv("YUNESA_ACADEMIC_GRAPHRAG_TOP_K", "8")),
                        keyword_top_k=int(os.getenv("YUNESA_ACADEMIC_GRAPHRAG_KEYWORD_TOP_K", "8")),
                    )
                    academic = dict(academic_raw or {})
                    academic["route_decision"] = route_decision
                author_publications_raw = []
                author_publications_capped = False
                author_publications = []
                academic["author_publications"] = []
                academic.setdefault("structured_counts", {})["author_publications"] = {
                    "returned": 0,
                    "limit": author_publication_window,
                    "complete": True,
                    "enumeration_query": author_publication_enumeration_query,
                }
                publication_details = []
                lecturer_topic_publications = []
                topic_frequencies = []
                collaborations = []
            # Only clear individual publication evidence for general collaboration queries.
            # If the query is about a specific publication (title candidate extracted),
            # we must keep the publication details to allow the LLM to verify sole-authorship.
            has_specific_pub = self._has_specific_publication_reference(intent_query)
            if publication_details and has_specific_pub:
                collaborations = []
                academic["collaborations"] = []
            elif collaborations:
                author_publications = []
                lecturer_topic_publications = []
                academic["author_publications"] = []
                academic["lecturer_topic_publications"] = []
            author_chunks = self.normalize_author_publication_chunks(
                author_publications,
                query_text=intent_query,
                max_chunks=int(
                    os.getenv(
                        "YUNESA_AUTHOR_PUBLICATION_CHUNKS",
                        str(DEFAULT_STRUCTURED_ENUMERATION_LIMIT),
                    )
                ),
            )
            publication_detail_chunks = self.normalize_publication_detail_chunks(
                publication_details,
                max_chunks=int(os.getenv("YUNESA_PUBLICATION_DETAIL_CHUNKS", "8")),
            )
            lecturer_topic_chunks = self.normalize_lecturer_topic_chunks(
                lecturer_topic_publications,
                max_chunks=int(os.getenv("YUNESA_LECTURER_TOPIC_CHUNKS", "12")),
            )
            topic_frequency_chunks = self.normalize_topic_frequency_chunks(
                topic_frequencies,
                max_chunks=int(os.getenv("YUNESA_TOPIC_FREQUENCY_CHUNKS", "15")),
            )
            collaboration_chunks = self.normalize_collaboration_chunks(
                collaborations,
                max_chunks=int(os.getenv("YUNESA_COLLABORATION_CHUNKS", "12")),
            )
            academic_chunks = self.normalize_academic_paper_chunks(academic.get("paper_chunks"))
            if collaboration_chunks:
                direct_chunks = [*collaboration_chunks]
            else:
                direct_chunks = [
                    *publication_detail_chunks,
                    *lecturer_topic_chunks,
                    *author_chunks,
                    *topic_frequency_chunks,
                ]
            if direct_chunks:
                academic_sources = {str(item.get("source") or "").casefold() for item in direct_chunks}
                supplemental_chunks = [
                    item
                    for item in academic_chunks
                    if str(item.get("source") or "").casefold() not in academic_sources
                ][:4]
                normalized_chunks = self._dedupe_evidence_chunks(
                    direct_chunks + supplemental_chunks,
                )
            else:
                normalized_chunks = self._dedupe_evidence_chunks(
                    academic_chunks or self.normalize_chunks(chunks),
                )
            graph_terms = [
                str(row.get("entityName") or "").strip()
                for row in (academic.get("entities") or [])[:5]
                if str(row.get("entityName") or "").strip()
            ]
            if extracted_entities:
                graph_terms.extend(extracted_entities.get("author_names") or [])
            else:
                graph_terms.extend(self._extract_author_name_candidates(intent_query))
            keyword_decomposition = academic.get("keyword_decomposition") or {}
            graph_terms.extend(keyword_decomposition.get("low_level_keywords") or [])
            graph_terms = self._dedupe_terms(graph_terms, max_terms=5)
            graph = (
                await self.query_graph(
                    academic.get("local_query") or semantic_query,
                    max_depth=graph_max_depth,
                    max_nodes=graph_max_nodes,
                    graph_name=resolved_graph_name,
                    seed_terms=graph_terms,
                )
                if self.uses_graph(mode, include_graph=include_graph)
                else {"nodes": [], "edges": [], "triples": [], "status": "skipped"}
            )
            if self.uses_graph(mode, include_graph=include_graph):
                graph = self._merge_graph_results(
                    [
                        academic.get("subgraph") or {},
                        self._map_structured_rows_to_graph(academic),
                        graph,
                    ],
                    max_nodes=graph_max_nodes,
                )
                graph["triples"] = self._triples_from_graph(graph)
                graph["status"] = "ok" if graph["nodes"] else "empty"

            payload = {
                "mode": mode,
                "requested_mode": requested_mode,
                "route_decision": route_decision,
                "query": query_text,
                "original_query": intent_query,
                "knowledge_base": {"name": kb_name, "collection_id": collection_id},
                "storage_layer": self.storage_layer(),
                "chunks": normalized_chunks,
                "academic_retrieval": academic,
                "graph": graph,
            }
            payload["grounding"] = self._grounding_status(
                normalized_chunks,
                graph,
                academic,
                query_text=intent_query,
            )
            payload["evidence_text"] = self._compact_evidence_text(
                normalized_chunks,
                graph,
                academic=academic,
                grounding=payload["grounding"],
                mode=academic.get("academicrag_mode") or academic.get("mode") or mode,
            )

            # Sub-intent context injection and logging for unknown intents
            known_intents = {
                "collaboration",
                "lecturer_topic",
                "author_publications",
                "topic_frequency",
                "publication_details",
            }
            unknown_intents = [intent for intent in sub_intents if intent not in known_intents]
            if unknown_intents:
                logger.info(f"Unknown sub-intents detected: {unknown_intents}")
                unknown_str = ", ".join(unknown_intents)
                prefix = (
                    f"[UNKNOWN SUB-INTENTS DETECTED]\n"
                    f"- The user query suggests specialized intents: {unknown_str}.\n"
                    f"- If appropriate, handle these intents in your response.\n\n"
                )
                payload["evidence_text"] = prefix + (payload["evidence_text"] or "")
            set_observation_output(
                span,
                output=self._context_summary(payload, time.perf_counter() - started_at),
            )
            return payload
