"""Academic GraphRAG retrieval package builder.

This module keeps Yunesa's existing Yuxi-style retrieval backbone intact:
Milvus/Zilliz returns semantic text evidence, Neo4j/AuraDB returns structured
academic graph evidence, and the chat agent synthesizes the final answer.
"""

import asyncio
import os
import re
import time
from functools import lru_cache
from typing import Any

from yunesa.observability import opik_span, set_observation_output
from yunesa.utils import logger


ACADEMIC_NODE_TYPES = [
    "Lecturer",
    "Publication",
    "Venue",
    "Year",
    "Keyword",
    "Concept",
]

ACADEMIC_RELATION_TYPES = [
    "PUBLISHES",
    "HAS_AUTHOR",
    "PUBLISHED_IN_VENUE",
    "PUBLISHED_IN_YEAR",
    "HAS_KEYWORD",
    "HAS_TOPIC",
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


@lru_cache(maxsize=8)
def _cached_milvus_client(uri: str, token: str, db_name: str | None):
    from pymilvus import MilvusClient

    client = MilvusClient(uri=uri, token=token)
    if db_name and hasattr(client, "using_database"):
        client.using_database(db_name)
    return client


class AcademicGraphRAGService:
    """Build an AcademicRAG-style context package from vector and graph stores."""

    VALID_MODES = {"vector", "keyword", "graph", "hybrid", "mix"}
    MODE_ALIASES = {
        "naive": "vector",
        "bm25": "keyword",
        "subgraph": "graph",
        "local": "graph",
        "global": "graph",
        "academic": "mix",
        "academic_graphrag": "mix",
        "graphrag": "mix",
    }
    GRAPH_STOPWORDS = {
        "about",
        "after",
        "again",
        "against",
        "antara",
        "apakah",
        "based",
        "before",
        "berikan",
        "dalam",
        "dengan",
        "from",
        "gimana",
        "hasil",
        "pada",
        "show",
        "system",
        "that",
        "this",
        "untuk",
        "using",
        "what",
        "yang",
    }

    @classmethod
    def normalize_mode(cls, mode: str | None, include_graph: bool = False) -> str:
        normalized = str(mode or "").strip().lower() or "mix"
        normalized = cls.MODE_ALIASES.get(normalized, normalized)
        if normalized not in cls.VALID_MODES:
            normalized = "mix"
        if include_graph and normalized in {"vector", "keyword"}:
            return "mix"
        return normalized

    @classmethod
    def milvus_search_mode(cls, mode: str) -> str:
        if mode == "keyword":
            return "keyword"
        if mode in {"hybrid", "mix", "graph"}:
            return "hybrid"
        return "vector"

    @classmethod
    def uses_graph(cls, mode: str, include_graph: bool = False) -> bool:
        return include_graph or mode in {"graph", "hybrid", "mix"}

    @staticmethod
    def storage_layer() -> dict[str, Any]:
        return {
            "metadata": {
                "backend": "supabase",
                "stores": ["papers", "lecturers", "paper_lecturers"],
            },
            "vector": {
                "backend": "zilliz_milvus",
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
                "backend": "neo4j_aura",
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
        return uri.strip(), token.strip(), str(db_name).strip() if db_name else None

    @staticmethod
    def _milvus_db_candidates(db_name: str | None) -> list[str | None]:
        """Try the configured database first, then the Milvus/Zilliz default.

        This keeps explicit deployments working while protecting production from
        stale `MILVUS_DB_NAME` values that point to a database without AcademicRAG
        collections.
        """
        candidates: list[str | None] = []
        configured = str(db_name or "").strip()
        if configured and configured.lower() not in {"none", "null", DEFAULT_MILVUS_DB_NAME}:
            candidates.append(configured)
        candidates.append(None)
        if DEFAULT_MILVUS_DB_NAME not in candidates:
            candidates.append(DEFAULT_MILVUS_DB_NAME)
        return candidates

    @staticmethod
    def _graph_filter(graph_name: str) -> str:
        safe_graph_name = str(graph_name or "").replace("\\", "\\\\").replace('"', '\\"')
        return f'graphName == "{safe_graph_name}"' if safe_graph_name else ""

    @classmethod
    def _query_terms(cls, query_text: str, *, max_terms: int = 8) -> list[str]:
        terms: list[str] = []
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_+.-]{2,}", query_text or ""):
            normalized = token.strip().lower()
            if normalized in cls.GRAPH_STOPWORDS:
                continue
            if normalized not in terms:
                terms.append(normalized)
            if len(terms) >= max_terms:
                break
        return terms

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
    def _embed_query(cls, query_text: str) -> list[float]:
        provider = DEFAULT_ACADEMIC_EMBEDDING_PROVIDER.strip().lower().replace("-", "_")
        if provider in {"lexical", "none", "disabled"}:
            raise RuntimeError("Dense embedding is disabled by Academic GraphRAG configuration.")
        if provider not in {"siliconflow", "silicon_flow"}:
            raise RuntimeError(f"Unsupported backend embedding provider: {provider}")

        api_key = os.getenv("SILICONFLOW_API_KEY")
        if not api_key:
            raise RuntimeError("SILICONFLOW_API_KEY is not configured.")

        import requests

        response = requests.post(
            os.getenv("SILICONFLOW_EMBEDDING_URL", "https://api.siliconflow.com/v1/embeddings"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEFAULT_ACADEMIC_EMBEDDING_MODEL,
                "input": [str(query_text or "")],
            },
            timeout=float(os.getenv("SILICONFLOW_EMBEDDING_TIMEOUT", "30")),
        )
        response.raise_for_status()
        data = (response.json().get("data") or [{}])[0]
        vector = data.get("embedding")
        if not vector:
            raise RuntimeError("SiliconFlow embedding response is empty.")
        return [float(value) for value in vector]

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
    ) -> list[dict[str, Any]]:
        if not cls._academic_milvus_enabled():
            return []
        uri, token, db_name = cls._milvus_credentials()
        if not uri or not token:
            return []

        try:
            vector = await asyncio.to_thread(cls._embed_query, query_text)
            for candidate_db in cls._milvus_db_candidates(db_name):
                try:
                    client = _cached_milvus_client(uri, token, candidate_db)
                    raw_hits = await asyncio.to_thread(
                        client.search,
                        collection_name=collection_name,
                        data=[vector],
                        anns_field="embedding",
                        limit=top_k,
                        output_fields=output_fields,
                        search_params={"metric_type": os.getenv("YUNESA_MILVUS_METRIC_TYPE", "L2")},
                        filter=cls._graph_filter(graph_name),
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
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                f"Academic GraphRAG dense search skipped for {collection_name}; "
                f"falling back to lexical query: {type(exc).__name__}: {exc}"
            )

        for candidate_db in cls._milvus_db_candidates(db_name):
            try:
                client = _cached_milvus_client(uri, token, candidate_db)
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

        for candidate_db in cls._milvus_db_candidates(db_name):
            try:
                client = _cached_milvus_client(uri, token, candidate_db)
                rows = await asyncio.to_thread(
                    client.query,
                    collection_name=collection_name,
                    filter=cls._graph_filter(graph_name),
                    output_fields=output_fields,
                    limit=max(top_k * 20, 100),
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
        logger.warning(f"Academic GraphRAG vector retrieval returned no rows for {collection_name}")
        return []

    @classmethod
    async def query_academic_indexes(
        cls,
        query_text: str,
        *,
        retrieval_mode: str = "mix",
        graph_name: str | None = None,
        top_k: int = 8,
        keyword_top_k: int = 8,
    ) -> dict[str, Any]:
        """Retrieve from canonical AcademicRAG indexes produced by the notebook pipeline."""
        mode = cls.normalize_mode(retrieval_mode)
        resolved_graph_name = cls._academic_graph_name(graph_name)
        payload: dict[str, Any] = {
            "status": "skipped",
            "mode": mode,
            "graph_name": resolved_graph_name,
            "milvus_database": (cls._milvus_credentials()[2] or DEFAULT_MILVUS_DB_NAME),
            "paper_chunks": [],
            "keywords": [],
            "entities": [],
            "relationships": [],
        }
        if not cls._academic_milvus_enabled():
            payload["status"] = "disabled"
            return payload

        tasks = []
        labels = []
        if mode in {"vector", "hybrid", "mix"}:
            labels.append("paper_chunks")
            tasks.append(
                cls._search_academic_collection(
                    query_text=query_text,
                    collection_name=ACADEMIC_COLLECTIONS["paper_chunks"],
                    output_fields=["graphName", "title", "content", "year", "paperUrl", "authors"],
                    text_fields=["title", "content", "authors"],
                    top_k=top_k,
                    graph_name=resolved_graph_name,
                )
            )
        if mode in {"keyword", "hybrid", "mix"}:
            labels.append("keywords")
            tasks.append(
                cls._search_academic_collection(
                    query_text=query_text,
                    collection_name=ACADEMIC_COLLECTIONS["content_keywords"],
                    output_fields=["graphName", "keywords", "sourcePaper"],
                    text_fields=["keywords", "sourcePaper"],
                    top_k=keyword_top_k,
                    graph_name=resolved_graph_name,
                )
            )
        if mode in {"graph", "hybrid", "mix"}:
            labels.extend(["entities", "relationships"])
            tasks.extend(
                [
                    cls._search_academic_collection(
                        query_text=query_text,
                        collection_name=ACADEMIC_COLLECTIONS["entities"],
                        output_fields=["graphName", "entityName", "entityType", "description", "nodeId", "sourceId"],
                        text_fields=["entityName", "entityType", "description"],
                        top_k=top_k,
                        graph_name=resolved_graph_name,
                    ),
                    cls._search_academic_collection(
                        query_text=query_text,
                        collection_name=ACADEMIC_COLLECTIONS["relationships"],
                        output_fields=["graphName", "srcId", "tgtId", "relType", "description", "sourceId"],
                        text_fields=["srcId", "tgtId", "relType", "description"],
                        top_k=top_k,
                        graph_name=resolved_graph_name,
                    ),
                ]
            )

        if tasks:
            results = await asyncio.gather(*tasks)
            for label, rows in zip(labels, results, strict=False):
                payload[label] = rows

        payload["status"] = "ok" if any(payload.get(key) for key in ("paper_chunks", "keywords", "entities", "relationships")) else "empty"
        return payload

    @classmethod
    def normalize_chunks(
        cls,
        chunks: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 8,
        max_chars: int = 1200,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, chunk in enumerate((chunks or [])[:max_chunks], start=1):
            metadata = dict(chunk.get("metadata") or {})
            normalized.append(
                {
                    "rank": index,
                    "content": cls._clip_text(chunk.get("content", ""), max_chars),
                    "score": chunk.get("score"),
                    "source": metadata.get("source") or chunk.get("source"),
                    "file_id": metadata.get("file_id"),
                    "chunk_id": metadata.get("chunk_id"),
                    "chunk_index": metadata.get("chunk_index"),
                }
            )
        return normalized

    @classmethod
    def normalize_academic_paper_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 8,
        max_chars: int = 1200,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows or []:
            source = row.get("title") or row.get("paperUrl") or "PaperChunk"
            key = str(source).strip().lower()
            content = str(row.get("content") or "").strip()
            distance = row.get("distance")
            if key in grouped:
                current = grouped[key]
                if content and content not in current["content"]:
                    current["content"] = cls._clip_text(f"{current['content']}\n{content}", max_chars)
                if isinstance(distance, (int, float)) and (
                    not isinstance(current.get("score"), (int, float)) or distance < current["score"]
                ):
                    current["score"] = distance
                continue
            grouped[key] = {
                "rank": 0,
                "content": cls._clip_text(content, max_chars),
                "score": distance,
                "source": source,
                "file_id": row.get("paperUrl") or row.get("title"),
                "chunk_id": row.get("title"),
                "chunk_index": len(grouped),
                "metadata": {
                    "title": row.get("title"),
                    "year": row.get("year"),
                    "authors": row.get("authors"),
                    "paperUrl": row.get("paperUrl"),
                    "graphName": row.get("graphName"),
                },
            }
            if len(grouped) >= max_chunks:
                break
        normalized = list(grouped.values())
        for index, item in enumerate(normalized, start=1):
            item["rank"] = index
        return normalized

    @staticmethod
    def _triples_from_graph(graph: dict[str, Any]) -> list[dict[str, str]]:
        node_names = {
            str(node.get("id")): str(node.get("name") or node.get("id"))
            for node in graph.get("nodes", [])
        }
        triples = []
        for edge in graph.get("edges", []):
            source_id = str(edge.get("source_id") or edge.get("source") or "")
            target_id = str(edge.get("target_id") or edge.get("target") or "")
            if not source_id or not target_id:
                continue
            triples.append(
                {
                    "source": node_names.get(source_id, source_id),
                    "relation": str(edge.get("type") or "RELATED_TO"),
                    "target": node_names.get(target_id, target_id),
                }
            )
        return triples

    @classmethod
    def _fallback_graph_terms(cls, query_text: str, max_terms: int = 6) -> list[str]:
        terms: list[str] = []
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_+.-]{2,}", query_text or ""):
            normalized = token.strip().lower()
            if normalized in cls.GRAPH_STOPWORDS:
                continue
            if normalized not in terms:
                terms.append(normalized)
            if len(terms) >= max_terms:
                break
        return terms

    @staticmethod
    def _merge_graph_results(results: list[dict[str, Any]], max_nodes: int) -> dict[str, Any]:
        nodes_by_id: dict[str, dict[str, Any]] = {}
        edges_by_id: dict[str, dict[str, Any]] = {}

        for graph in results:
            for node in graph.get("nodes", []) or []:
                node_id = str(node.get("id") or "")
                if node_id and node_id not in nodes_by_id and len(nodes_by_id) < max_nodes:
                    nodes_by_id[node_id] = node

            allowed_nodes = set(nodes_by_id)
            for edge in graph.get("edges", []) or []:
                edge_id = str(edge.get("id") or "")
                source_id = str(edge.get("source_id") or edge.get("source") or "")
                target_id = str(edge.get("target_id") or edge.get("target") or "")
                if edge_id and source_id in allowed_nodes and target_id in allowed_nodes:
                    edges_by_id.setdefault(edge_id, edge)

        return {
            "nodes": list(nodes_by_id.values()),
            "edges": list(edges_by_id.values()),
        }

    @classmethod
    def _compact_evidence_text(
        cls,
        chunks: list[dict[str, Any]],
        graph: dict[str, Any],
        academic: dict[str, Any] | None = None,
    ) -> str:
        lines = ["Academic GraphRAG evidence:"]
        if chunks:
            lines.append("Vector evidence:")
            for chunk in chunks:
                source = chunk.get("source") or "knowledge-base"
                score = chunk.get("score")
                score_text = f", score={score:.4f}" if isinstance(score, (int, float)) else ""
                lines.append(f"- [{chunk['rank']}] source={source}{score_text}: {chunk['content']}")

        academic = academic or {}
        keywords = academic.get("keywords") or []
        if keywords:
            lines.append("Controlled keyword evidence:")
            for row in keywords[:8]:
                lines.append(
                    "- "
                    f"paper={row.get('sourcePaper') or 'unknown'} | "
                    f"keywords={cls._clip_text(row.get('keywords', ''), 500)}"
                )

        entities = academic.get("entities") or []
        if entities:
            lines.append("Entity evidence:")
            for row in entities[:8]:
                lines.append(
                    "- "
                    f"{row.get('entityName')} ({row.get('entityType')}) | "
                    f"{cls._clip_text(row.get('description', ''), 420)}"
                )

        relationships = academic.get("relationships") or []
        if relationships:
            lines.append("Relationship evidence:")
            for row in relationships[:8]:
                lines.append(
                    "- "
                    f"{row.get('srcId')} -[{row.get('relType')}]-> {row.get('tgtId')} | "
                    f"{cls._clip_text(row.get('description', ''), 420)}"
                )

        triples = graph.get("triples") or []
        if triples:
            lines.append("Graph evidence:")
            for triple in triples[:24]:
                lines.append(f"- {triple['source']} -[{triple['relation']}]-> {triple['target']}")
        elif graph.get("status") not in {"ok", None}:
            lines.append(f"Graph evidence unavailable: {graph.get('status')}")

        return "\n".join(lines)

    @staticmethod
    def _graph_summary(graph: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": graph.get("status"),
            "nodes": len(graph.get("nodes", []) or []),
            "edges": len(graph.get("edges", []) or []),
            "triples": len(graph.get("triples", []) or []),
        }

    @classmethod
    def _context_summary(cls, payload: dict[str, Any], duration_seconds: float) -> dict[str, Any]:
        graph = payload.get("graph") or {}
        academic = payload.get("academic_retrieval") or {}
        return {
            "mode": payload.get("mode"),
            "kb_name": (payload.get("knowledge_base") or {}).get("name"),
            "collection_id": (payload.get("knowledge_base") or {}).get("collection_id"),
            "chunks": len(payload.get("chunks", []) or []),
            "academic_status": academic.get("status"),
            "academic_paper_chunks": len(academic.get("paper_chunks", []) or []),
            "academic_keywords": len(academic.get("keywords", []) or []),
            "academic_entities": len(academic.get("entities", []) or []),
            "academic_relationships": len(academic.get("relationships", []) or []),
            "graph": cls._graph_summary(graph),
            "evidence_chars": len(payload.get("evidence_text") or ""),
            "duration_seconds": round(duration_seconds, 3),
        }

    async def query_graph(
        self,
        query_text: str,
        *,
        max_depth: int = 2,
        max_nodes: int = 80,
        graph_name: str | None = None,
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
            },
            metadata={"storage": "neo4j_aura"},
            tags=["graph-retrieval", "neo4j"],
        ) as span:
            graph = await self._query_graph_impl(
                query_text,
                max_depth=max_depth,
                max_nodes=max_nodes,
                graph_name=graph_name,
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
        max_depth: int = 2,
        max_nodes: int = 80,
        graph_name: str | None = None,
    ) -> dict[str, Any]:
        try:
            from yunesa import graph_base

            if hasattr(graph_base, "start") and not graph_base.is_running():
                graph_base.start()
            if not graph_base.is_running():
                return {"nodes": [], "edges": [], "triples": [], "status": "unavailable"}

            graph = await asyncio.to_thread(
                graph_base.query_subgraph,
                keyword=query_text,
                max_depth=max_depth,
                max_nodes=max_nodes,
                graph_name=graph_name,
            )
            if not graph.get("nodes"):
                fallback_results = []
                for term in self._fallback_graph_terms(query_text):
                    fallback_results.append(
                        await asyncio.to_thread(
                            graph_base.query_subgraph,
                            keyword=term,
                            max_depth=max_depth,
                            max_nodes=max_nodes,
                            graph_name=graph_name,
                        )
                    )
                if fallback_results:
                    graph = self._merge_graph_results(fallback_results, max_nodes=max_nodes)

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
        chunks: list[dict[str, Any]] | None,
        kb_name: str,
        collection_id: str | None = None,
        retrieval_mode: str = "mix",
        include_graph: bool = True,
        graph_max_depth: int = 2,
        graph_max_nodes: int = 80,
        graph_name: str | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        with opik_span(
            "academic_graphrag.build_context_package",
            type="tool",
            input={
                "query": query_text,
                "kb_name": kb_name,
                "collection_id": collection_id,
                "retrieval_mode": retrieval_mode,
                "include_graph": include_graph,
                "graph_max_depth": graph_max_depth,
                "graph_max_nodes": graph_max_nodes,
                "graph_name": graph_name,
                "input_chunks": len(chunks or []),
            },
            metadata={"storage": "milvus+neo4j", "service": "query_kb"},
            tags=["context-assembly", "hybrid-retrieval"],
        ) as span:
            mode = self.normalize_mode(retrieval_mode, include_graph=include_graph)
            resolved_graph_name = self._academic_graph_name(graph_name)
            academic = await self.query_academic_indexes(
                query_text,
                retrieval_mode=mode,
                graph_name=resolved_graph_name,
                top_k=int(os.getenv("YUNESA_ACADEMIC_GRAPHRAG_TOP_K", "8")),
                keyword_top_k=int(os.getenv("YUNESA_ACADEMIC_GRAPHRAG_KEYWORD_TOP_K", "8")),
            )
            academic_chunks = self.normalize_academic_paper_chunks(academic.get("paper_chunks"))
            normalized_chunks = academic_chunks or self.normalize_chunks(chunks)
            graph_terms = [
                str(row.get("entityName") or "").strip()
                for row in (academic.get("entities") or [])[:5]
                if str(row.get("entityName") or "").strip()
            ]
            graph_query_text = query_text
            if graph_terms:
                graph_query_text = f"{query_text} {' '.join(graph_terms)}"
            graph = (
                await self.query_graph(
                    graph_query_text,
                    max_depth=graph_max_depth,
                    max_nodes=graph_max_nodes,
                    graph_name=resolved_graph_name,
                )
                if self.uses_graph(mode, include_graph=include_graph)
                else {"nodes": [], "edges": [], "triples": [], "status": "skipped"}
            )

            payload = {
                "mode": mode,
                "query": query_text,
                "knowledge_base": {"name": kb_name, "collection_id": collection_id},
                "storage_layer": self.storage_layer(),
                "chunks": normalized_chunks,
                "academic_retrieval": academic,
                "graph": graph,
            }
            payload["evidence_text"] = self._compact_evidence_text(normalized_chunks, graph, academic=academic)
            set_observation_output(
                span,
                output=self._context_summary(payload, time.perf_counter() - started_at),
            )
            return payload
