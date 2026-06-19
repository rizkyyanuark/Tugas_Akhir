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
        "academic": "mix",
        "academic_graphrag": "mix",
        "graphrag": "mix",
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

        The public API still exposes the AcademicRAG modes directly. This router
        only intervenes when callers use the broad default (`mix`). Explicit
        modes stay untouched so evaluation scripts can compare modes cleanly.
        """
        normalized_mode = cls.normalize_mode(requested_mode, include_graph=include_graph)
        if normalized_mode not in {"mix"}:
            return {
                "requested_mode": normalized_mode,
                "effective_mode": normalized_mode,
                "auto_routed": False,
                "reason": "explicit_mode",
                "intents": AcademicQueryPlanner.classify_intents(query_text),
            }

        intents = AcademicQueryPlanner.classify_intents(query_text)
        text = str(query_text or "").casefold()
        reasons: list[str] = []
        effective_mode = normalized_mode

        if cls._is_topic_frequency_query(query_text):
            effective_mode = "subgraph"
            reasons.append("topic_frequency_structured_query")
        elif cls._is_collaboration_query(query_text):
            effective_mode = "subgraph"
            reasons.append("collaboration_structured_query")
        elif cls._is_author_publication_query(query_text):
            effective_mode = "subgraph"
            reasons.append("author_publication_structured_query")
        elif cls._has_specific_publication_reference(query_text):
            effective_mode = "subgraph"
            reasons.append("publication_detail_structured_query")
        elif cls._is_lecturer_topic_query(query_text):
            effective_mode = "subgraph"
            reasons.append("lecturer_topic_structured_query")
        elif any(
            marker in text
            for marker in (
                "terhubung",
                "hubungan",
                "relasi",
                "path",
                "jalur",
                "multi-hop",
                "multihop",
                "antara dosen",
                "dosen dan",
            )
        ):
            effective_mode = "hybrid"
            reasons.append("multi_hop_or_relationship_query")

        return {
            "requested_mode": normalized_mode,
            "effective_mode": effective_mode,
            "auto_routed": effective_mode != normalized_mode,
            "reason": ",".join(reasons) if reasons else "default_mix",
            "intents": intents,
        }

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
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        return str(
            node.get("label")
            or node.get("name")
            or node.get("title")
            or props.get("label")
            or props.get("name")
            or props.get("title")
            or ""
        ).strip()

    @classmethod
    def _publication_nodes_from_graph(
        cls,
        graph: dict[str, Any],
        *,
        max_nodes: int = 8,
    ) -> list[dict[str, Any]]:
        publications: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node in graph.get("nodes", []) or []:
            labels = {str(label) for label in (node.get("labels") or [])}
            props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
            node_type = str(node.get("node_type") or props.get("node_type") or node.get("type") or "")
            if "Publication" not in labels and node_type != "Publication":
                continue
            title = str(
                node.get("title")
                or node.get("label")
                or node.get("name")
                or props.get("title")
                or props.get("label")
                or props.get("name")
                or ""
            ).strip()
            key = str(node.get("id") or props.get("id") or props.get("paper_id") or title).casefold()
            if not title or key in seen:
                continue
            seen.add(key)
            publications.append(
                {
                    "title": title,
                    "year": node.get("year") or props.get("year"),
                    "authors": node.get("authors") or props.get("authors"),
                    "doi": node.get("doi") or props.get("doi"),
                    "venue": node.get("venue") or props.get("venue"),
                    "tldr": node.get("tldr") or props.get("tldr"),
                    "abstract": node.get("abstract") or props.get("abstract"),
                    "paper_id": node.get("paper_id") or props.get("paper_id"),
                    "source": "neo4j_graph_publication",
                }
            )
            if len(publications) >= max_nodes:
                break
        return publications

    @classmethod
    def _is_author_publication_query(cls, query_text: str) -> bool:
        terms = set(cls._query_terms(query_text, max_terms=24))
        text = str(query_text or "").casefold()
        query_markers = (
            "paper",
            "papers",
            "penelitian",
            "publikasi",
            "publication",
            "publications",
            "ditulis",
            "menulis",
            "penulis",
            "author",
            "authors",
        )
        has_marker = bool(terms & cls.AUTHOR_PUBLICATION_QUERY_MARKERS) or any(
            marker in text for marker in query_markers
        )
        has_person_hint = bool(
            re.search(r"\b[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)+", query_text or "")
            or cls._extract_author_name_candidates(query_text)
        )
        return has_marker and has_person_hint

    @classmethod
    def _is_author_publication_enumeration_query(cls, query_text: str) -> bool:
        if not cls._is_author_publication_query(query_text):
            return False

        text = re.sub(r"\s+", " ", str(query_text or "").casefold()).strip()
        return any(
            marker in text
            for marker in (
                "apa saja paper",
                "paper apa saja",
                "apa saja publikasi",
                "publikasi apa saja",
                "apa saja penelitian",
                "daftar paper",
                "daftar publikasi",
                "daftar penelitian",
                "list paper",
                "list publikasi",
                "papers by",
                "publications by",
                "papers written by",
                "publications written by",
            )
        )

    @classmethod
    def _extract_author_name_candidates(cls, query_text: str) -> list[str]:
        text = re.sub(r"\s+", " ", str(query_text or "")).strip()
        candidates: list[str] = []
        for match in re.finditer(
            r"\b([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,4})\b",
            text,
        ):
            value = match.group(1).strip()
            if value.casefold() in cls.GRAPH_STOPWORDS:
                continue
            candidates.append(value)

        # Indonesian queries often mention names in lowercase.
        lowered = text.casefold()
        for prefix in ("oleh ", "ditulis oleh ", "paper yang ditulis oleh ", "publikasi "):
            if prefix in lowered:
                raw = text[lowered.index(prefix) + len(prefix) :]
                raw = re.split(
                    r"[?.!,;()]| pada | tahun | dengan | tentang | yang | dkk\b| et al\b",
                    raw,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]
                if raw.strip():
                    candidates.append(raw.strip())

        # Suffix matching for lowercase name before collaboration keywords
        for suffix in (" berkolaborasi", " kolaborasi", " co-author", " coauthor", " kerja sama"):
            if suffix in lowered:
                raw = text[: lowered.index(suffix)]
                words = raw.strip().split()
                if words:
                    # Filter out common English academic terms from being part of name candidates
                    academic_stopwords = {
                        "using", "linear", "regression", "learning", "classification",
                        "clustering", "network", "framework", "analysis", "system",
                        "model", "algorithm", "prediction", "predicting", "performance",
                        "student", "students", "education", "educational", "based",
                        "method", "methods", "data", "mining", "validation", "sampling"
                    }
                    name_words = []
                    for word in reversed(words):
                        if word.lower() in academic_stopwords or word.lower() in cls.GRAPH_STOPWORDS:
                            break
                        name_words.insert(0, word)

                    if name_words:
                        candidates.append(name_words[-1])
                        if len(name_words) >= 2:
                            candidates.append(" ".join(name_words[-2:]))
                        if len(name_words) >= 3:
                            candidates.append(" ".join(name_words[-3:]))

        # Prefix matching for lowercase name after collaboration keywords
        for prefix in ("kolaborasi ", "kolaborator ", "kerja sama "):
            if prefix in lowered:
                raw = text[lowered.index(prefix) + len(prefix) :]
                raw = re.split(
                    r"[?.!,;()]| pada | tahun | dengan | tentang | yang | dkk\b| et al\b",
                    raw,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]
                words = raw.strip().split()
                if words:
                    # Filter out common English academic terms
                    academic_stopwords = {
                        "using", "linear", "regression", "learning", "classification",
                        "clustering", "network", "framework", "analysis", "system",
                        "model", "algorithm", "prediction", "predicting", "performance",
                        "student", "students", "education", "educational", "based",
                        "method", "methods", "data", "mining", "validation", "sampling"
                    }
                    name_words = []
                    for word in words:
                        if word.lower() in academic_stopwords or word.lower() in cls.GRAPH_STOPWORDS:
                            break
                        name_words.append(word)

                    if name_words:
                        candidates.append(name_words[0])
                        if len(name_words) >= 2:
                            candidates.append(" ".join(name_words[:2]))
                        if len(name_words) >= 3:
                            candidates.append(" ".join(name_words[:3]))

        return cls._dedupe_terms(candidates, max_terms=5)

    @classmethod
    def _is_lecturer_topic_query(cls, query_text: str) -> bool:
        text = str(query_text or "").casefold()
        terms = set(cls._query_terms(query_text, max_terms=32))
        has_lecturer_intent = bool(terms & cls.LECTURER_TOPIC_QUERY_MARKERS) or any(
            marker in text
            for marker in (
                "dosen",
                "penulis",
                "siapa",
                "lecturer",
                "author",
                "researcher",
            )
        )
        has_topic_intent = any(
            marker in text
            for marker in (
                "tentang",
                "membahas",
                "topik",
                "topic",
                "using",
                "menggunakan",
                "machine learning",
                "pendidikan",
                "education",
            )
        )
        return has_lecturer_intent and has_topic_intent

    @classmethod
    def _is_topic_frequency_query(cls, query_text: str) -> bool:
        text = str(query_text or "").casefold()
        has_topic = any(
            marker in text
            for marker in ("topik", "topic", "tema", "theme", "research area", "bidang riset")
        )
        has_frequency = any(
            re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text)
            for marker in cls.TOPIC_FREQUENCY_QUERY_MARKERS
        )
        return has_topic and has_frequency

    @classmethod
    def _extract_publication_title_candidates(cls, query_text: str) -> list[str]:
        text = re.sub(r"\s+", " ", str(query_text or "")).strip()
        candidates: list[str] = []
        for match in re.finditer(r"""["“']([^"”']{12,240})["”']""", text):
            candidates.append(match.group(1).strip())

        # Fallback heuristic if no quoted title was found
        if not candidates:
            lowered = text.casefold()
            author_names = cls._extract_author_name_candidates(query_text)
            # Sort author names by length in descending order to avoid partial replacement of names
            sorted_authors = sorted(author_names, key=len, reverse=True)
            for kw in ("paper ", "publikasi ", "penelitian ", "artikel "):
                if kw in lowered:
                    idx = lowered.index(kw)
                    raw = text[idx + len(kw) :]
                    # Split on typical Indonesian/English conjunctions or punctuation
                    title_split_pattern = (
                        r"(?i)\b(?:oleh|ditulis|ditulis oleh|berkolaborasi|dengan|siapa|who|by|written by|"
                        r"published|tahun|year|pada|in|at)\b|[?.!,;()]"
                    )
                    parts = re.split(title_split_pattern, raw, maxsplit=1)
                    title_candidate = parts[0].strip()

                    # Clean title candidate from any extracted author names
                    for author in sorted_authors:
                        pattern = re.compile(rf"\b{re.escape(author)}\b", re.IGNORECASE)
                        title_candidate = pattern.sub("", title_candidate).strip()

                    # Clean trailing/leading connector words that might be left after author cleaning
                    title_candidate = re.sub(r"(?i)\b(?:oleh|ditulis|dan|and)\b", "", title_candidate).strip()
                    title_candidate = re.sub(r"\s+", " ", title_candidate).strip()

                    if len(title_candidate) >= 12:
                        candidates.append(title_candidate)

        return cls._dedupe_terms(candidates, max_terms=4)

    @classmethod
    def _has_specific_publication_reference(cls, query_text: str) -> bool:
        """Detect a concrete publication reference, not a generic paper search."""
        text = re.sub(r"\s+", " ", str(query_text or "")).strip()
        lowered = text.casefold()
        if re.search(r"""["â€œ'][^"â€']{12,240}["â€']""", text):
            return True
        if any(marker in lowered for marker in ("berjudul", "judul ", "entitled", "title ")):
            return bool(cls._extract_publication_title_candidates(query_text))
        if any(
            marker in lowered
            for marker in (
                "paper apa",
                "apa paper",
                "publikasi apa",
                "apa publikasi",
                "penelitian apa",
                "apa penelitian",
                "membahas",
                "tentang",
                "carikan",
                "cari ",
                "find ",
                "which paper",
                "what paper",
            )
        ):
            return False
        return bool(cls._extract_publication_title_candidates(query_text))

    @staticmethod
    def _format_values(value: Any) -> str:
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item) for item in value if item)
        return str(value or "")

    @classmethod
    def _department_terms(cls, query_text: str) -> list[str]:
        text = str(query_text or "").casefold()
        values: list[str] = []
        if "s2 informatika" in text:
            values.extend(["s2 informatika", "informatika"])
        elif "informatika" in text:
            values.append("informatika")
        return cls._dedupe_terms(values, max_terms=4)

    @classmethod
    def _topic_terms_for_neo4j(cls, query_text: str) -> list[str]:
        text = str(query_text or "").casefold()
        ignored = {
            "apa",
            "saja",
            "siapa",
            "mana",
            "dosen",
            "lecturer",
            "lecturers",
            "author",
            "authors",
            "penulis",
            "paper",
            "papers",
            "publikasi",
            "publication",
            "publications",
            "tentang",
            "bidang",
            "menulis",
            "ditulis",
            "s2",
            "informatika",
        }
        terms: list[str] = []
        phrase_map = {
            "machine learning": ["machine learning"],
            "deep learning": ["deep learning"],
            "artificial intelligence": ["artificial intelligence", "ai"],
            " ai ": ["artificial intelligence", "ai"],
            "data mining": ["data mining"],
            "pendidikan": ["education", "educational", "student", "students", "learning"],
            "mahasiswa": ["student", "students", "student performance"],
            "siswa": ["student", "students", "student performance"],
            "education": ["education", "educational", "student", "students"],
        }
        for marker, mapped_terms in phrase_map.items():
            if marker in text:
                terms.extend(mapped_terms)

        for term in cls._query_terms(query_text, max_terms=24):
            if term in ignored or term in cls.GRAPH_STOPWORDS:
                continue
            terms.append(term)

        return cls._dedupe_terms(terms, max_terms=12)

    @classmethod
    def _is_collaboration_query(cls, query_text: str) -> bool:
        text = str(query_text or "").casefold()
        return any(
            marker in text
            for marker in (
                "berkolaborasi",
                "kolaborasi",
                "kolaborator",
                "collaborat",
                "co-author",
                "coauthor",
                "co author",
                "kerja sama",
            )
        )

    @classmethod
    def normalize_author_publication_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        query_text: str = "",
        max_chunks: int = 12,
        max_chars: int = 1800,
    ) -> list[dict[str, Any]]:
        terms = set(cls._query_terms(query_text, max_terms=24))
        year_terms = set(re.findall(r"\b(?:19|20)\d{2}\b", query_text or ""))

        def relevance(row: dict[str, Any]) -> tuple[int, int, str]:
            title = str(row.get("title") or "")
            body = " ".join(
                str(row.get(key) or "")
                for key in ("title", "authors", "venue", "tldr", "abstract", "doi")
            ).casefold()
            overlap = sum(1 for term in terms if term in body)
            year_bonus = 3 if str(row.get("year") or "") in year_terms else 0
            try:
                year = int(row.get("year") or 0)
            except (TypeError, ValueError):
                year = 0
            return overlap + year_bonus, year, title.casefold()

        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        ranked_rows = sorted(
            rows or [],
            key=lambda row: (
                -relevance(row)[0],
                -relevance(row)[1],
                relevance(row)[2],
            ),
        )
        for index, row in enumerate(ranked_rows[:max_chunks], start=1):
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            key = str(row.get("paper_id") or title).casefold()
            if key in seen:
                continue
            seen.add(key)
            parts = [
                f"Title: {title}",
                f"Year: {row.get('year') or 'unknown'}",
                f"Author matched: {row.get('author') or 'unknown'}",
                f"Authors: {cls._format_values(row.get('authors')) or 'unknown'}",
            ]
            if row.get("doi"):
                parts.append(f"DOI: {row.get('doi')}")
            if row.get("venue"):
                parts.append(f"Venue: {row.get('venue')}")
            if row.get("tldr"):
                parts.append(f"TLDR: {row.get('tldr')}")
            if row.get("abstract"):
                parts.append(f"Abstract: {row.get('abstract')}")
            if row.get("link"):
                parts.append(f"Link: {row.get('link')}")
            normalized.append(
                {
                    "rank": index,
                    "content": cls._clip_text("\n".join(parts), max_chars),
                    "score": 1.0,
                    "source": title,
                    "file_id": row.get("paper_id") or title,
                    "chunk_id": f"author-publication:{row.get('paper_id') or title}",
                    "chunk_index": index - 1,
                    "metadata": {
                        "source": title,
                        "title": title,
                        "year": row.get("year"),
                        "authors": row.get("authors"),
                        "doi": row.get("doi"),
                        "venue": row.get("venue"),
                        "paper_id": row.get("paper_id"),
                        "retrieval_source": "neo4j_author_publications",
                    },
                }
            )
        return normalized

    @classmethod
    def normalize_lecturer_topic_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 12,
        max_chars: int = 1800,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, row in enumerate(rows or [], start=1):
            title = str(row.get("title") or "").strip()
            lecturer = str(row.get("lecturer") or "").strip()
            if not title or not lecturer:
                continue
            key = f"{lecturer.casefold()}::{str(row.get('paper_id') or title).casefold()}"
            if key in seen:
                continue
            seen.add(key)
            matched_terms = row.get("matched_terms") or []
            if isinstance(matched_terms, (list, tuple, set)):
                matched_text = ", ".join(str(item) for item in matched_terms if item)
            else:
                matched_text = str(matched_terms or "")
            parts = [
                f"Lecturer: {lecturer}",
                f"Affiliation: {row.get('affiliation') or 'unknown'}",
                f"Title: {title}",
                f"Year: {row.get('year') or 'unknown'}",
                f"Authors: {cls._format_values(row.get('authors')) or 'unknown'}",
                f"Matched terms: {matched_text or 'unknown'}",
            ]
            if row.get("doi"):
                parts.append(f"DOI: {row.get('doi')}")
            if row.get("venue"):
                parts.append(f"Venue: {row.get('venue')}")
            if row.get("tldr"):
                parts.append(f"TLDR: {row.get('tldr')}")
            if row.get("abstract"):
                parts.append(f"Abstract: {row.get('abstract')}")
            normalized.append(
                {
                    "rank": index,
                    "content": cls._clip_text("\n".join(parts), max_chars),
                    "score": row.get("score") or 1.0,
                    "source": title,
                    "file_id": row.get("paper_id") or title,
                    "chunk_id": f"lecturer-topic:{lecturer}:{row.get('paper_id') or title}",
                    "chunk_index": index - 1,
                    "metadata": {
                        "source": title,
                        "title": title,
                        "year": row.get("year"),
                        "authors": row.get("authors"),
                        "doi": row.get("doi"),
                        "venue": row.get("venue"),
                        "paper_id": row.get("paper_id"),
                        "lecturer": lecturer,
                        "affiliation": row.get("affiliation"),
                        "matched_terms": matched_terms,
                        "retrieval_source": "neo4j_lecturer_topic_publications",
                    },
                }
            )
        return normalized[:max_chunks]

    @classmethod
    def normalize_publication_detail_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 8,
        max_chars: int = 2200,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, row in enumerate((rows or [])[:max_chunks], start=1):
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            concepts = row.get("concepts") or []
            concept_text = ", ".join(
                f"{item.get('relation')}: {item.get('value')}"
                for item in concepts
                if isinstance(item, dict) and item.get("value")
            )
            parts = [
                f"Title: {title}",
                f"Year: {row.get('year') or 'unknown'}",
                f"Authors: {cls._format_values(row.get('authors')) or 'unknown'}",
            ]
            if row.get("doi"):
                parts.append(f"DOI: {row.get('doi')}")
            if row.get("venue"):
                parts.append(f"Venue: {row.get('venue')}")
            if row.get("tldr"):
                parts.append(f"TLDR: {row.get('tldr')}")
            if row.get("abstract"):
                parts.append(f"Abstract: {row.get('abstract')}")
            if concept_text:
                parts.append(f"Graph concepts: {concept_text}")
            if row.get("link"):
                parts.append(f"Link: {row.get('link')}")
            normalized.append(
                {
                    "rank": index,
                    "content": cls._clip_text("\n".join(parts), max_chars),
                    "score": 1.0,
                    "source": title,
                    "file_id": row.get("paper_id") or title,
                    "chunk_id": f"publication-detail:{row.get('paper_id') or title}",
                    "chunk_index": index - 1,
                    "metadata": {
                        "source": title,
                        "title": title,
                        "year": row.get("year"),
                        "authors": row.get("authors"),
                        "doi": row.get("doi"),
                        "venue": row.get("venue"),
                        "paper_id": row.get("paper_id"),
                        "retrieval_source": "neo4j_publication_details",
                    },
                }
            )
        return normalized

    @classmethod
    def normalize_topic_frequency_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 15,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, row in enumerate((rows or [])[:max_chunks], start=1):
            topic = str(row.get("topic") or "").strip()
            if not topic:
                continue
            titles = cls._format_values(row.get("sample_titles"))
            content = (
                f"Topic: {topic}\n"
                f"Concept type: {row.get('concept_type') or 'Concept'}\n"
                f"Publication count: {row.get('publication_count') or 0}\n"
                f"Sample publications: {titles or 'unknown'}"
            )
            normalized.append(
                {
                    "rank": index,
                    "content": content,
                    "score": float(row.get("publication_count") or 0),
                    "source": "YUNESA Academic Knowledge Graph topic aggregation",
                    "file_id": f"topic-frequency:{topic}",
                    "chunk_id": f"topic-frequency:{topic}",
                    "chunk_index": index - 1,
                    "metadata": {
                        "topic": topic,
                        "concept_type": row.get("concept_type"),
                        "publication_count": row.get("publication_count"),
                        "sample_titles": row.get("sample_titles"),
                        "retrieval_source": "neo4j_topic_frequency",
                    },
                }
            )
        return normalized

    @classmethod
    def normalize_collaboration_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_chunks: int = 12,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, row in enumerate((rows or [])[:max_chunks], start=1):
            lecturer = str(row.get("lecturer") or "").strip()
            collaborator = str(row.get("collaborator") or "").strip()
            if not lecturer or not collaborator:
                continue
            titles = cls._format_values(row.get("paper_titles"))
            content = (
                f"Lecturer: {lecturer}\n"
                f"Collaborator: {collaborator}\n"
                f"Collaboration paper count: {row.get('paper_count') or 0}\n"
                f"Shared publications: {titles or 'unknown'}"
            )
            normalized.append(
                {
                    "rank": index,
                    "content": content,
                    "score": float(row.get("paper_count") or 0),
                    "source": f"{lecturer} collaborates with {collaborator}",
                    "file_id": f"collaboration:{lecturer}:{collaborator}",
                    "chunk_id": f"collaboration:{lecturer}:{collaborator}",
                    "chunk_index": index - 1,
                    "metadata": {
                        "lecturer": lecturer,
                        "collaborator": collaborator,
                        "paper_count": row.get("paper_count"),
                        "paper_titles": row.get("paper_titles"),
                        "paper_ids": row.get("paper_ids"),
                        "retrieval_source": "neo4j_collaborations",
                    },
                }
            )
        return normalized

    @classmethod
    async def query_collaborations(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        if not cls._is_collaboration_query(query_text):
            return []

        lecturer_candidates = cls._extract_author_name_candidates(query_text)
        if not lecturer_candidates:
            return []

        topic_terms = cls._topic_terms_for_neo4j(query_text)

        try:
            from yunesa import graph_base

            if hasattr(graph_base, "start") and not graph_base.is_running():
                graph_base.start()
            if not graph_base.is_running() or not getattr(graph_base, "driver", None):
                return []

            resolved_graph_name = cls._academic_graph_name(graph_name)
            cypher = """
                UNWIND $lecturer_candidates AS lecturer_name
                MATCH (lecturer:Lecturer)
                WHERE lecturer.graph_name = $graph_name
                  AND (
                    toLower(coalesce(lecturer.label, '')) CONTAINS toLower(lecturer_name)
                    OR toLower(coalesce(lecturer.name, '')) CONTAINS toLower(lecturer_name)
                    OR toLower(coalesce(lecturer.nama_dosen, '')) CONTAINS toLower(lecturer_name)
                    OR toLower(coalesce(lecturer.nama_norm, '')) CONTAINS toLower(lecturer_name)
                  )
                MATCH (lecturer)-[collab_rel:COLLABORATES_WITH]-(collaborator:Lecturer)
                WHERE collaborator.graph_name = $graph_name
                OPTIONAL MATCH (lecturer)-[:PUBLISHES]->(paper:Publication)<-[:PUBLISHES]-(collaborator)
                WHERE paper.graph_name = $graph_name
                WITH DISTINCT lecturer, collaborator, collab_rel, collect(DISTINCT paper) AS papers
                WITH
                  lecturer,
                  collaborator,
                  collab_rel,
                  [
                    paper IN papers |
                    {
                      paper_id: paper.paper_id,
                      title: coalesce(paper.title, paper.label, paper.name),
                      year: paper.year,
                      doi: paper.doi,
                      text: toLower(
                        toString(coalesce(paper.title, '')) + ' ' +
                        toString(coalesce(paper.abstract, '')) + ' ' +
                        toString(coalesce(paper.tldr, '')) + ' ' +
                        toString(coalesce(paper.keywords, ''))
                      )
                    }
                  ] AS paper_items
                WITH
                  lecturer,
                  collaborator,
                  collab_rel,
                  CASE
                    WHEN size($topic_terms) = 0 THEN paper_items
                    ELSE [
                      item IN paper_items
                      WHERE any(term IN $topic_terms WHERE item.text CONTAINS toLower(term))
                    ]
                  END AS matched_papers,
                  paper_items
                WHERE size($topic_terms) = 0 OR size(matched_papers) > 0
                RETURN
                  coalesce(lecturer.label, lecturer.nama_norm, lecturer.nama_dosen, lecturer.name) AS lecturer,
                  coalesce(
                    collaborator.label,
                    collaborator.nama_norm,
                    collaborator.nama_dosen,
                    collaborator.name
                  ) AS collaborator,
                  CASE
                    WHEN size(matched_papers) > 0 THEN size(matched_papers)
                    ELSE coalesce(collab_rel.paper_count, size(paper_items))
                  END AS paper_count,
                  [item IN matched_papers | item.paper_id][0..12] AS paper_ids,
                  [item IN matched_papers | item.title][0..12] AS paper_titles,
                  [item IN matched_papers | item.year][0..12] AS years,
                  [item IN matched_papers | item.doi][0..12] AS dois
                ORDER BY paper_count DESC, toLower(collaborator) ASC
                LIMIT $limit
            """

            def run_query() -> list[dict[str, Any]]:
                with graph_base.driver.session(database=graph_base._neo4j_database()) as session:
                    rows = session.run(
                        cypher,
                        lecturer_candidates=lecturer_candidates,
                        topic_terms=topic_terms,
                        graph_name=resolved_graph_name,
                        limit=limit,
                    )
                    return [dict(row) for row in rows]

            return await asyncio.to_thread(run_query)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Academic GraphRAG collaboration query failed: {type(exc).__name__}: {exc}"
            )
            return []

    @classmethod
    async def query_author_publications(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        if not cls._is_author_publication_query(query_text):
            return []

        author_candidates = cls._extract_author_name_candidates(query_text)
        if not author_candidates:
            return []

        try:
            from yunesa import graph_base

            if hasattr(graph_base, "start") and not graph_base.is_running():
                graph_base.start()
            if not graph_base.is_running() or not getattr(graph_base, "driver", None):
                return []

            resolved_graph_name = cls._academic_graph_name(graph_name)
            cypher = """
                UNWIND $author_candidates AS author_name
                MATCH (lecturer:Lecturer)
                WHERE lecturer.graph_name = $graph_name
                  AND (
                    toLower(coalesce(lecturer.label, '')) CONTAINS toLower(author_name)
                    OR toLower(coalesce(lecturer.name, '')) CONTAINS toLower(author_name)
                    OR toLower(coalesce(lecturer.nama_dosen, '')) CONTAINS toLower(author_name)
                    OR toLower(coalesce(lecturer.nama_norm, '')) CONTAINS toLower(author_name)
                  )
                MATCH (lecturer)-[:PUBLISHES|HAS_AUTHOR]-(paper:Publication)
                WHERE paper.graph_name = $graph_name
                WITH DISTINCT lecturer, paper
                OPTIONAL MATCH (paper)<-[:PUBLISHES]-(coauthor:Lecturer)
                WHERE coauthor.graph_name = $graph_name
                WITH lecturer, paper,
                     collect(DISTINCT coalesce(
                       coauthor.label,
                       coauthor.nama_norm,
                       coauthor.nama_dosen,
                       coauthor.name
                     )) AS connected_authors
                RETURN
                  coalesce(lecturer.label, lecturer.nama_norm, lecturer.nama_dosen, lecturer.name) AS author,
                  paper.paper_id AS paper_id,
                  coalesce(paper.title, paper.label, paper.name) AS title,
                  paper.year AS year,
                  CASE
                    WHEN size(connected_authors) > 0 THEN connected_authors
                    ELSE paper.authors
                  END AS authors,
                  paper.doi AS doi,
                  paper.venue AS venue,
                  paper.tldr AS tldr,
                  paper.abstract AS abstract,
                  paper.link AS link
                ORDER BY toInteger(coalesce(paper.year, '0')) DESC, title ASC
                LIMIT $limit
            """

            def run_query() -> list[dict[str, Any]]:
                with graph_base.driver.session(database=graph_base._neo4j_database()) as session:
                    rows = session.run(
                        cypher,
                        author_candidates=author_candidates,
                        graph_name=resolved_graph_name,
                        limit=limit,
                    )
                    return [dict(row) for row in rows]

            rows = await asyncio.to_thread(run_query)
            return rows
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Academic GraphRAG author publication query failed: {type(exc).__name__}: {exc}"
            )
            return []

    @classmethod
    async def query_publication_details(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        title_candidates = cls._extract_publication_title_candidates(query_text)
        if not title_candidates:
            return []

        try:
            from yunesa import graph_base

            if hasattr(graph_base, "start") and not graph_base.is_running():
                graph_base.start()
            if not graph_base.is_running() or not getattr(graph_base, "driver", None):
                return []

            resolved_graph_name = cls._academic_graph_name(graph_name)
            cypher = """
                UNWIND $title_candidates AS title_candidate
                MATCH (paper:Publication)
                WHERE paper.graph_name = $graph_name
                  AND toLower(coalesce(paper.title, paper.label, paper.name, ''))
                      CONTAINS toLower(title_candidate)
                OPTIONAL MATCH (paper)<-[:PUBLISHES]-(author:Lecturer)
                WHERE author.graph_name = $graph_name
                WITH DISTINCT paper,
                     collect(DISTINCT coalesce(
                       author.label,
                       author.nama_norm,
                       author.nama_dosen,
                       author.name
                     )) AS connected_authors
                OPTIONAL MATCH (paper)-[
                  relation:HAS_KEYWORD|HAS_TOPIC|USES_METHOD|USES_MODEL|
                  USES_DATASET|EVALUATED_WITH|BELONGS_TO_DOMAIN|HAS_RESULT
                ]->(concept)
                WITH paper, connected_authors,
                     collect(DISTINCT {
                       relation: type(relation),
                       value: coalesce(concept.label, concept.name, concept.id)
                     }) AS concepts
                RETURN
                  paper.paper_id AS paper_id,
                  coalesce(paper.title, paper.label, paper.name) AS title,
                  paper.year AS year,
                  CASE
                    WHEN size(connected_authors) > 0 THEN connected_authors
                    ELSE paper.authors
                  END AS authors,
                  paper.doi AS doi,
                  paper.venue AS venue,
                  paper.tldr AS tldr,
                  paper.abstract AS abstract,
                  paper.link AS link,
                  concepts AS concepts
                ORDER BY toInteger(toString(coalesce(paper.year, '0'))) DESC, title ASC
                LIMIT $limit
            """

            def run_query() -> list[dict[str, Any]]:
                with graph_base.driver.session(database=graph_base._neo4j_database()) as session:
                    rows = session.run(
                        cypher,
                        title_candidates=title_candidates,
                        graph_name=resolved_graph_name,
                        limit=limit,
                    )
                    return [dict(row) for row in rows]

            return await asyncio.to_thread(run_query)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Academic GraphRAG publication detail query failed: {type(exc).__name__}: {exc}"
            )
            return []

    @classmethod
    async def query_topic_frequencies(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 15,
    ) -> list[dict[str, Any]]:
        if not cls._is_topic_frequency_query(query_text):
            return []

        try:
            from yunesa import graph_base

            if hasattr(graph_base, "start") and not graph_base.is_running():
                graph_base.start()
            if not graph_base.is_running() or not getattr(graph_base, "driver", None):
                return []

            resolved_graph_name = cls._academic_graph_name(graph_name)
            cypher = """
                MATCH (paper:Publication)-[
                  relation:HAS_TOPIC|HAS_KEYWORD|BELONGS_TO_DOMAIN|
                  USES_METHOD|USES_MODEL|USES_DATASET
                ]->(concept)
                WHERE paper.graph_name = $graph_name
                  AND concept.graph_name = $graph_name
                WITH
                  coalesce(concept.label, concept.name, concept.id) AS topic,
                  coalesce(concept.concept_type, labels(concept)[0], 'Concept') AS concept_type,
                  count(DISTINCT paper) AS publication_count,
                  collect(DISTINCT coalesce(paper.title, paper.label, paper.name))[0..5]
                    AS sample_titles
                WHERE topic IS NOT NULL AND trim(toString(topic)) <> ''
                RETURN topic, concept_type, publication_count, sample_titles
                ORDER BY publication_count DESC, toLower(toString(topic)) ASC
                LIMIT $limit
            """

            def run_query() -> list[dict[str, Any]]:
                with graph_base.driver.session(database=graph_base._neo4j_database()) as session:
                    rows = session.run(
                        cypher,
                        graph_name=resolved_graph_name,
                        limit=limit,
                    )
                    return [dict(row) for row in rows]

            return await asyncio.to_thread(run_query)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Academic GraphRAG topic frequency query failed: {type(exc).__name__}: {exc}"
            )
            return []

    @classmethod
    async def query_lecturer_topic_publications(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        if not cls._is_lecturer_topic_query(query_text):
            return []

        topic_terms = cls._topic_terms_for_neo4j(query_text)
        if not topic_terms:
            return []

        department_terms = cls._department_terms(query_text)
        min_match_count = min(2, len(topic_terms))

        try:
            from yunesa import graph_base

            if hasattr(graph_base, "start") and not graph_base.is_running():
                graph_base.start()
            if not graph_base.is_running() or not getattr(graph_base, "driver", None):
                return []

            resolved_graph_name = cls._academic_graph_name(graph_name)
            cypher = """
                MATCH (lecturer:Lecturer)-[:PUBLISHES]->(paper:Publication)
                WHERE lecturer.graph_name = $graph_name
                  AND paper.graph_name = $graph_name
                OPTIONAL MATCH (lecturer)-[:HAS_AFFILIATION]->(affiliation:Institution)
                WITH lecturer, paper, collect(DISTINCT affiliation) AS affiliations
                OPTIONAL MATCH (paper)-[
                  :HAS_KEYWORD|HAS_TOPIC|USES_METHOD|USES_MODEL|USES_DATASET
                  |EVALUATED_WITH|BELONGS_TO_DOMAIN
                ]->(concept)
                WITH lecturer, paper, affiliations, collect(DISTINCT concept) AS concepts
                WITH
                  lecturer,
                  paper,
                  affiliations,
                  concepts,
                  toLower(
                    toString(coalesce(paper.title, '')) + ' ' +
                    toString(coalesce(paper.label, '')) + ' ' +
                    toString(coalesce(paper.abstract, '')) + ' ' +
                    toString(coalesce(paper.tldr, '')) + ' ' +
                    toString(coalesce(paper.keywords, '')) + ' ' +
                    toString(coalesce(paper.authors, ''))
                  ) AS paper_text,
                  [
                    c IN concepts |
                    toLower(
                      toString(coalesce(c.label, '')) + ' ' +
                      toString(coalesce(c.name, '')) + ' ' +
                      toString(coalesce(c.description, '')) + ' ' +
                      toString(coalesce(c.concept_type, ''))
                    )
                  ] AS concept_texts,
                  [
                    a IN affiliations |
                    coalesce(a.label, a.name, a.id, '')
                  ] AS affiliation_names,
                  toLower(
                    coalesce(lecturer.label, '') + ' ' +
                    coalesce(lecturer.name, '') + ' ' +
                    coalesce(lecturer.nama_dosen, '') + ' ' +
                    coalesce(lecturer.nama_norm, '') + ' ' +
                    reduce(s = '', a IN affiliations | s + ' ' + coalesce(a.label, a.name, a.id, ''))
                  ) AS lecturer_text
                WHERE size($department_terms) = 0
                   OR any(term IN $department_terms WHERE lecturer_text CONTAINS toLower(term))
                WITH
                  lecturer,
                  paper,
                  affiliation_names,
                  [
                    term IN $topic_terms
                    WHERE paper_text CONTAINS toLower(term)
                       OR any(concept_text IN concept_texts WHERE concept_text CONTAINS toLower(term))
                  ] AS matched_terms
                WHERE size(matched_terms) >= $min_match_count
                WITH DISTINCT lecturer, paper, affiliation_names, matched_terms
                OPTIONAL MATCH (paper)<-[:PUBLISHES]-(coauthor:Lecturer)
                WHERE coauthor.graph_name = $graph_name
                WITH lecturer, paper, affiliation_names, matched_terms,
                     collect(DISTINCT coalesce(
                       coauthor.label,
                       coauthor.nama_norm,
                       coauthor.nama_dosen,
                       coauthor.name
                     )) AS connected_authors
                RETURN
                  coalesce(lecturer.label, lecturer.nama_norm, lecturer.nama_dosen, lecturer.name) AS lecturer,
                  affiliation_names AS affiliations,
                  paper.paper_id AS paper_id,
                  coalesce(paper.title, paper.label, paper.name) AS title,
                  paper.year AS year,
                  CASE
                    WHEN size(connected_authors) > 0 THEN connected_authors
                    ELSE paper.authors
                  END AS authors,
                  paper.doi AS doi,
                  paper.venue AS venue,
                  paper.tldr AS tldr,
                  paper.abstract AS abstract,
                  paper.link AS link,
                  matched_terms AS matched_terms,
                  size(matched_terms) AS score
                ORDER BY score DESC, toInteger(toString(coalesce(paper.year, '0'))) DESC, lecturer ASC, title ASC
                LIMIT $limit
            """

            def run_query() -> list[dict[str, Any]]:
                with graph_base.driver.session(database=graph_base._neo4j_database()) as session:
                    rows = session.run(
                        cypher,
                        graph_name=resolved_graph_name,
                        topic_terms=topic_terms,
                        department_terms=department_terms,
                        min_match_count=min_match_count,
                        limit=limit,
                    )
                    normalized_rows: list[dict[str, Any]] = []
                    for row in rows:
                        data = dict(row)
                        affiliations = data.pop("affiliations", []) or []
                        data["affiliation"] = ", ".join(
                            str(item) for item in affiliations if item
                        )
                        normalized_rows.append(data)
                    return normalized_rows

            return await asyncio.to_thread(run_query)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Academic GraphRAG lecturer-topic query failed: {type(exc).__name__}: {exc}"
            )
            return []

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
                        filter=cls._graph_filter(graph_name),
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
        retrieval_mode: str = "mix",
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

        if second_tasks:
            payload.update(
                await cls._gather_search_results(second_labels, second_tasks)
            )

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
        for position, row in enumerate(rows or []):
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
                "_position": position,
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
        normalized = sorted(
            grouped.values(),
            key=lambda item: (
                item.get("score")
                if isinstance(item.get("score"), (int, float))
                else float("inf"),
                item["_position"],
            ),
        )[:max_chunks]
        for index, item in enumerate(normalized, start=1):
            item.pop("_position", None)
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
        edges_by_signature: dict[tuple[str, str, str], dict[str, Any]] = {}

        for graph in results:
            for node in graph.get("nodes", []) or []:
                node_id = str(node.get("id") or "")
                if not node_id:
                    continue
                existing = nodes_by_id.get(node_id)
                node_is_virtual = node.get("graph_type") == "virtual"
                existing_is_virtual = existing and existing.get("graph_type") == "virtual"
                if existing_is_virtual and not node_is_virtual:
                    nodes_by_id[node_id] = node
                elif existing is None and len(nodes_by_id) < max_nodes:
                    nodes_by_id[node_id] = node

        allowed_nodes = set(nodes_by_id)
        for graph in results:
            for edge in graph.get("edges", []) or []:
                source_id = str(edge.get("source_id") or edge.get("source") or "")
                target_id = str(edge.get("target_id") or edge.get("target") or "")
                relation = str(edge.get("type") or "RELATED_TO").upper()
                if source_id not in allowed_nodes or target_id not in allowed_nodes:
                    continue
                signature = (source_id, relation, target_id)
                existing = edges_by_signature.get(signature)
                edge_source = str((edge.get("properties") or {}).get("source") or "")
                existing_source = str(
                    ((existing or {}).get("properties") or {}).get("source") or ""
                )
                if existing_source == "structured_query" and edge_source != "structured_query":
                    edges_by_signature[signature] = edge
                elif existing is None:
                    edges_by_signature[signature] = edge

        return {
            "nodes": list(nodes_by_id.values()),
            "edges": list(edges_by_signature.values()),
        }

    @staticmethod
    def _virtual_id(node_type: str, value: Any) -> str:
        normalized = re.sub(r"\s+", " ", str(value or "").strip()).casefold()
        digest = hashlib.sha1(
            f"{node_type}:{normalized}".encode()
        ).hexdigest()[:16]
        return f"virtual:{node_type.casefold()}:{digest}"

    @staticmethod
    def _structured_node_id(node_type: str, node_id: Any) -> str:
        value = str(node_id or "").strip()
        if (
            node_type == "Publication"
            and re.fullmatch(r"[0-9a-fA-F]{32}", value)
        ):
            return f"paper:{value.lower()}"
        return value

    @classmethod
    def _dedupe_evidence_chunks(
        cls,
        chunks: list[dict[str, Any]],
        *,
        max_chunks: int = 24,
    ) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for chunk in chunks:
            source = re.sub(
                r"\s+",
                " ",
                str(chunk.get("source") or chunk.get("file_id") or "").strip(),
            )
            key = source.casefold()
            if not key:
                key = hashlib.sha1(
                    str(chunk.get("content") or "").encode()
                ).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            item = dict(chunk)
            item["rank"] = len(deduped) + 1
            deduped.append(item)
            if len(deduped) >= max_chunks:
                break
        return deduped

    @classmethod
    def _map_structured_rows_to_graph(
        cls,
        academic: dict[str, Any] | None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Convert structured academic query rows into deterministic graph evidence."""
        academic = academic or {}
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[tuple[str, str, str], dict[str, Any]] = {}

        def add_node(
            node_type: str,
            name: Any,
            *,
            node_id: Any = None,
            properties: dict[str, Any] | None = None,
        ) -> str:
            display_name = str(name or node_id or "").strip()
            if not display_name:
                return ""
            resolved_id = cls._structured_node_id(
                node_type,
                node_id,
            ) or cls._virtual_id(
                node_type,
                display_name,
            )
            node = nodes.setdefault(
                resolved_id,
                {
                    "id": resolved_id,
                    "name": display_name,
                    "type": node_type,
                    "labels": [node_type],
                    "properties": {},
                    "normalized": {
                        "name": display_name,
                        "type": node_type,
                        "source": "structured_query",
                    },
                    "graph_type": "virtual",
                },
            )
            node["properties"].update(
                {
                    key: value
                    for key, value in (properties or {}).items()
                    if value not in (None, "", [], {})
                }
            )
            return resolved_id

        def add_edge(
            source_id: str,
            relation: Any,
            target_id: str,
            *,
            properties: dict[str, Any] | None = None,
        ) -> None:
            relation_name = str(relation or "RELATED_TO").strip().upper()
            if not source_id or not target_id:
                return
            signature = (source_id, relation_name, target_id)
            if signature in edges:
                edges[signature]["properties"].update(properties or {})
                return
            edge_id = cls._virtual_id(
                "edge",
                "|".join(signature),
            )
            edges[signature] = {
                "id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "type": relation_name,
                "properties": {
                    "source": "structured_query",
                    **(properties or {}),
                },
                "normalized": {
                    "type": relation_name,
                    "direction": "directed",
                },
            }

        publication_rows = [
            *(academic.get("author_publications") or []),
            *(academic.get("lecturer_topic_publications") or []),
        ]
        for row in publication_rows:
            lecturer_name = row.get("author") or row.get("lecturer")
            title = row.get("title")
            lecturer_id = add_node(
                "Lecturer",
                lecturer_name,
                properties={"affiliation": row.get("affiliation")},
            )
            publication_id = add_node(
                "Publication",
                title,
                node_id=row.get("paper_id"),
                properties={
                    "title": title,
                    "year": row.get("year"),
                    "authors": row.get("authors"),
                    "doi": row.get("doi"),
                    "tldr": row.get("tldr"),
                    "abstract": row.get("abstract"),
                },
            )
            add_edge(publication_id, "HAS_AUTHOR", lecturer_id)
            affiliation = row.get("affiliation")
            if affiliation:
                institution_id = add_node("Institution", affiliation)
                add_edge(lecturer_id, "HAS_AFFILIATION", institution_id)

        for row in academic.get("publication_details") or []:
            title = row.get("title")
            publication_id = add_node(
                "Publication",
                title,
                node_id=row.get("paper_id"),
                properties={
                    "title": title,
                    "year": row.get("year"),
                    "authors": row.get("authors"),
                    "doi": row.get("doi"),
                    "tldr": row.get("tldr"),
                    "abstract": row.get("abstract"),
                },
            )
            for concept in row.get("concepts") or []:
                if not isinstance(concept, dict):
                    continue
                concept_name = concept.get("value") or concept.get("name")
                concept_type = concept.get("concept_type") or concept.get("type") or "Concept"
                concept_id = add_node(
                    str(concept_type),
                    concept_name,
                    node_id=concept.get("id"),
                )
                add_edge(
                    publication_id,
                    concept.get("relation") or "HAS_TOPIC",
                    concept_id,
                )

        for row in academic.get("collaborations") or []:
            lecturer_id = add_node("Lecturer", row.get("lecturer"))
            collaborator_id = add_node("Lecturer", row.get("collaborator"))
            add_edge(
                lecturer_id,
                "COLLABORATES_WITH",
                collaborator_id,
                properties={
                    "paper_count": row.get("paper_count"),
                    "paper_titles": row.get("paper_titles"),
                },
            )

        for row in academic.get("entities") or []:
            add_node(
                str(row.get("entityType") or "Concept"),
                row.get("entityName"),
                node_id=row.get("nodeId"),
                properties={
                    "description": row.get("description"),
                    "source_id": row.get("sourceId"),
                },
            )

        for row in academic.get("relationships") or []:
            source_id = add_node("Entity", row.get("srcId"), node_id=row.get("srcId"))
            target_id = add_node("Entity", row.get("tgtId"), node_id=row.get("tgtId"))
            add_edge(
                source_id,
                row.get("relType"),
                target_id,
                properties={
                    "description": row.get("description"),
                    "source_id": row.get("sourceId"),
                },
            )

        return {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
        }

    @staticmethod
    def _prune_shortest_path_graph(
        graph: dict[str, Any],
        relationship_rows: list[dict[str, Any]] | None,
        *,
        seed_node_ids: list[str],
    ) -> dict[str, Any]:
        """Keep shortest-path edges supported by relationship vector retrieval."""
        rows = relationship_rows or []
        if not rows:
            return graph

        allowed = {
            (
                frozenset(
                    {
                        str(row.get("srcId") or "").strip(),
                        str(row.get("tgtId") or "").strip(),
                    }
                ),
                str(row.get("relType") or "").strip().upper(),
            )
            for row in rows
            if row.get("srcId") and row.get("tgtId")
        }
        kept_edges = []
        kept_node_ids = {str(node_id) for node_id in seed_node_ids if node_id}
        for edge in graph.get("edges", []) or []:
            source_id = str(edge.get("source_id") or edge.get("source") or "").strip()
            target_id = str(edge.get("target_id") or edge.get("target") or "").strip()
            relation = str(edge.get("type") or "").strip().upper()
            if (frozenset({source_id, target_id}), relation) not in allowed:
                continue
            kept_edges.append(edge)
            kept_node_ids.update({source_id, target_id})

        return {
            "nodes": [
                node
                for node in graph.get("nodes", []) or []
                if str(node.get("id") or "") in kept_node_ids
            ],
            "edges": kept_edges,
        }

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
        seed_ids = cls._dedupe_terms(node_ids, max_terms=8)
        if not seed_ids:
            return {"nodes": [], "edges": [], "status": "skipped"}
        try:
            storage = graph_storage or Neo4jGraphStorage(graph_name=graph_name)
            max_hops = int(
                os.getenv("YUNESA_NEO4J_SHORTEST_PATH_MAX_HOPS", "3")
            )
            graph = await storage.get_shortest_path(
                seed_ids,
                max_hops=max_hops,
                max_nodes=max_nodes,
                graph_name=graph_name,
            )
            graph = cls._prune_shortest_path_graph(
                graph,
                relationship_rows,
                seed_node_ids=seed_ids,
            )
            graph["status"] = "ok" if graph.get("nodes") else "empty"
            graph["seed_node_ids"] = seed_ids
            return graph
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Academic GraphRAG shortest-path retrieval failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return {
                "nodes": [],
                "edges": [],
                "status": "error",
                "seed_node_ids": seed_ids,
                "message": str(exc),
            }

    @staticmethod
    def _encode_string_by_tiktoken(content: str, model_name: str = "gpt-4") -> list[int]:
        import tiktoken
        try:
            encoder = tiktoken.encoding_for_model(model_name)
        except Exception:
            encoder = tiktoken.get_encoding("cl100k_base")
        return encoder.encode(content)

    @classmethod
    def _truncate_list_by_token_size(
        cls,
        list_data: list[Any],
        key: Callable[[Any], str],
        max_token_size: int,
        model_name: str = "gpt-4",
    ) -> list[Any]:
        if max_token_size <= 0:
            return []
        tokens = 0
        for i, data in enumerate(list_data):
            tokens += len(cls._encode_string_by_tiktoken(key(data), model_name=model_name))
            if tokens > max_token_size:
                return list_data[:i]
        return list_data

    @classmethod
    def _compact_evidence_text(
        cls,
        chunks: list[dict[str, Any]],
        graph: dict[str, Any],
        academic: dict[str, Any] | None = None,
        grounding: dict[str, Any] | None = None,
        mode: str = "mix",
    ) -> str:
        del grounding
        # Fetch limits according to original AcademicRAG parameters
        param = AcademicQueryParam.from_runtime(mode)
        is_global = param.resolved_kg_mode() == "global"
        
        # Max tokens from environment or QueryParam defaults
        max_entity_tokens = int(os.getenv("MAX_TOKEN_ENTITY_DESC", str(param.max_token_for_local_context)))
        max_relation_tokens = int(os.getenv("MAX_TOKEN_RELATION_DESC", str(param.max_token_for_global_context if is_global else param.max_token_for_local_context)))
        max_text_tokens = int(os.getenv("MAX_TOKEN_TEXT_CHUNK", str(param.max_token_for_text_unit)))

        combined_graph = cls._merge_graph_results(
            [
                graph or {},
                cls._map_structured_rows_to_graph(academic),
            ],
            max_nodes=80,
        )
        node_names = {
            str(node.get("id") or ""): str(
                node.get("name") or node.get("id") or ""
            )
            for node in combined_graph.get("nodes", [])
        }

        # --- Entities (truncated based on description token size) ---
        nodes = combined_graph.get("nodes", [])
        truncated_nodes = cls._truncate_list_by_token_size(
            nodes,
            key=lambda x: str(x.get("properties", {}).get("description") or x.get("properties", {}).get("abstract") or x.get("name") or x.get("id") or ""),
            max_token_size=max_entity_tokens
        )

        entity_rows: list[list[Any]] = [
            ["id", "entity", "type", "description", "source"]
        ]
        for index, node in enumerate(truncated_nodes, start=1):
            properties = node.get("properties") or {}
            description = (
                properties.get("description")
                or properties.get("tldr")
                or properties.get("abstract")
                or properties.get("title")
                or ""
            )
            entity_rows.append(
                [
                    index,
                    node.get("name") or node.get("id"),
                    node.get("type") or "Node",
                    cls._clip_text(description, 800),
                    (node.get("normalized") or {}).get("source")
                    or node.get("graph_type")
                    or "neo4j",
                ]
            )

        # --- Relationships (truncated based on relationship description/triples token size) ---
        all_relations = []
        for edge in combined_graph.get("edges", []):
            all_relations.append({
                "is_edge": True,
                "data": edge,
                "description": str((edge.get("properties") or {}).get("description") or "")
            })
        for triple in (graph.get("triples", []) or []):
            all_relations.append({
                "is_edge": False,
                "data": triple,
                "description": f"{triple.get('source')} {triple.get('relation')} {triple.get('target')}"
            })
            
        # Deduplicate relationships by source, type, and target
        relationship_signatures: set[tuple[str, str, str]] = set()
        deduped_relations = []
        for r in all_relations:
            if r["is_edge"]:
                source_id = str(r["data"].get("source_id") or r["data"].get("source") or "")
                target_id = str(r["data"].get("target_id") or r["data"].get("target") or "")
                relation = str(r["data"].get("type") or "RELATED_TO")
            else:
                source_id = str(r["data"].get("source") or "")
                relation = str(r["data"].get("relation") or "RELATED_TO")
                target_id = str(r["data"].get("target") or "")
            sig = (source_id, relation, target_id)
            if sig not in relationship_signatures:
                relationship_signatures.add(sig)
                deduped_relations.append(r)

        truncated_relations = cls._truncate_list_by_token_size(
            deduped_relations,
            key=lambda x: x["description"],
            max_token_size=max_relation_tokens
        )

        relationship_rows: list[list[Any]] = [
            ["id", "source", "target", "relation", "description", "source"]
        ]
        for index, r in enumerate(truncated_relations, start=1):
            if r["is_edge"]:
                edge = r["data"]
                properties = edge.get("properties") or {}
                source_id = str(edge.get("source_id") or edge.get("source") or "")
                target_id = str(edge.get("target_id") or edge.get("target") or "")
                relation = str(edge.get("type") or "RELATED_TO")
                relationship_rows.append(
                    [
                        index,
                        node_names.get(source_id, source_id),
                        node_names.get(target_id, target_id),
                        relation,
                        cls._clip_text(properties.get("description") or "", 600),
                        properties.get("source") or "neo4j",
                    ]
                )
            else:
                triple = r["data"]
                source = str(triple.get("source") or "")
                relation = str(triple.get("relation") or "RELATED_TO")
                target = str(triple.get("target") or "")
                relationship_rows.append(
                    [
                        index,
                        source,
                        target,
                        relation,
                        "",
                        "neo4j",
                    ]
                )

        # --- Sources (truncated based on content token size) ---
        truncated_chunks = cls._truncate_list_by_token_size(
            chunks or [],
            key=lambda x: str(x.get("content") or ""),
            max_token_size=max_text_tokens
        )

        source_rows: list[list[Any]] = [["id", "source", "content", "score"]]
        for index, chunk in enumerate(truncated_chunks, start=1):
            source_rows.append(
                [
                    index,
                    chunk.get("source") or "knowledge-base",
                    cls._clip_text(chunk.get("content") or "", 1600),
                    chunk.get("score"),
                ]
            )

        def to_csv(rows: list[list[Any]]) -> str:
            output = io.StringIO(newline="")
            writer = csv.writer(
                output,
                quoting=csv.QUOTE_ALL,
                lineterminator="\n",
            )
            writer.writerows(rows)
            return output.getvalue().strip()

        evidence = (
            "-----Entities-----\n"
            "```csv\n"
            f"{to_csv(entity_rows)}\n"
            "```\n"
            "-----Relationships-----\n"
            "```csv\n"
            f"{to_csv(relationship_rows)}\n"
            "```\n"
            "-----Sources-----\n"
            "```csv\n"
            f"{to_csv(source_rows)}\n"
            "```"
        )
        logger.debug(
            "Academic GraphRAG evidence_text size: %d chars "
            "(entities=%d, relations=%d, sources=%d)",
            len(evidence),
            len(entity_rows) - 1,
            len(relationship_rows) - 1,
            len(source_rows) - 1,
        )
        return evidence

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
        keyword_decomposition = academic.get("keyword_decomposition") or {}
        return {
            "mode": payload.get("mode"),
            "requested_mode": payload.get("requested_mode"),
            "route_decision": payload.get("route_decision"),
            "kb_name": (payload.get("knowledge_base") or {}).get("name"),
            "collection_id": (payload.get("knowledge_base") or {}).get("collection_id"),
            "chunks": len(payload.get("chunks", []) or []),
            "academic_status": academic.get("status"),
            "academicrag_mode": academic.get("academicrag_mode"),
            "kg_mode": academic.get("kg_mode"),
            "academic_paper_chunks": len(academic.get("paper_chunks", []) or []),
            "academic_author_publications": len(academic.get("author_publications", []) or []),
            "academic_publication_details": len(academic.get("publication_details", []) or []),
            "academic_lecturer_topic_publications": len(
                academic.get("lecturer_topic_publications", []) or []
            ),
            "academic_topic_frequencies": len(academic.get("topic_frequencies", []) or []),
            "academic_collaborations": len(academic.get("collaborations", []) or []),
            "academic_keywords": len(academic.get("keywords", []) or []),
            "academic_entities": len(academic.get("entities", []) or []),
            "academic_relationships": len(academic.get("relationships", []) or []),
            "high_level_keywords": keyword_decomposition.get("high_level_keywords", []),
            "low_level_keywords": keyword_decomposition.get("low_level_keywords", []),
            "graph": cls._graph_summary(graph),
            "grounding": payload.get("grounding"),
            "evidence_chars": len(payload.get("evidence_text") or ""),
            "duration_seconds": round(duration_seconds, 3),
        }

    @classmethod
    def _grounding_status(
        cls,
        chunks: list[dict[str, Any]],
        graph: dict[str, Any],
        academic: dict[str, Any],
        query_text: str = "",
    ) -> dict[str, Any]:
        # Extract query terms and filter out generic/question stopwords
        terms = cls._query_terms(query_text, max_terms=24)
        generic_stopwords = {
            # English
            "paper", "papers", "publication", "publications", "article", "articles", "lecturer", "lecturers",
            "researcher", "researchers", "professor", "professors", "author", "authors", "write", "written",
            "topic", "topics", "study", "studies", "research", "researching", "list", "find", "search", "show",
            "get", "about", "using", "use", "used", "method", "methods", "algorithm", "algorithms",
            "dataset", "datasets", "model", "models", "approach", "approaches", "framework", "frameworks",
            "results", "result", "performance", "analysis", "evaluation", "evaluate", "implement", "implementation",
            # Indonesian
            "paper", "publikasi", "artikel", "dosen", "peneliti", "penulis", "tulis", "ditulis",
            "topik", "penelitian", "riset", "daftar", "cari", "carikan", "tunjukkan", "dapatkan",
            "tentang", "menggunakan", "penerapan", "implementasi", "metode", "algoritma", "dataset",
            "model", "pendekatan", "kerangka", "hasil", "performa", "analisa", "analisis", "evaluasi",
            "siapa", "apa", "bagaimana", "dimana", "kapan", "mengapa", "kenapa", "saja", "yang", "dengan",
            "pada", "dan", "untuk", "oleh", "di", "ke", "dari", "adalah", "yaitu", "yakni", "sebagai",
            "dalam", "secara", "bahwa", "ini", "itu", "saya", "kami", "mereka", "kita", "kamu", "dia",
        }
        topic_terms = [t.lower() for t in terms if t.lower() not in generic_stopwords and len(t) >= 3]

        # Check if topic terms are found in retrieved chunks, academic details, or graph nodes/triples
        has_topic_match = True
        if topic_terms:
            content_parts = []
            for chunk in chunks or []:
                content_parts.append(str(chunk.get("content") or ""))
                content_parts.append(str(chunk.get("source") or ""))

            for key in ("publication_details", "author_publications", "lecturer_topic_publications", "topic_frequencies", "collaborations"):
                for item in academic.get(key, []) or []:
                    if isinstance(item, dict):
                        content_parts.extend(str(val) for val in item.values() if val)

            for node in graph.get("nodes", []) or []:
                if isinstance(node, dict):
                    content_parts.append(str(node.get("name") or ""))
                    content_parts.append(str(node.get("label") or ""))

            for triple in graph.get("triples", []) or []:
                if isinstance(triple, dict):
                    content_parts.append(str(triple.get("source") or ""))
                    content_parts.append(str(triple.get("target") or ""))

            search_text = " ".join(content_parts).lower()
            has_topic_match = any(term in search_text for term in topic_terms)

        direct_count = len(chunks) if has_topic_match else 0
        structured_direct_count = sum(
            len(academic.get(key, []) or [])
            for key in (
                "publication_details",
                "author_publications",
                "lecturer_topic_publications",
                "topic_frequencies",
                "collaborations",
            )
        ) if has_topic_match else 0
        direct_count += structured_direct_count
        relation_intent = any(
            marker in str(query_text or "").casefold()
            for marker in (
                "berkolaborasi",
                "collaborat",
                "hubungan",
                "relasi",
                "collaboration",
                "relationship",
                "connected",
                "terhubung",
            )
        )
        graph_direct_count = (
            len(graph.get("triples", []) or [])
            if relation_intent and structured_direct_count == 0 and has_topic_match
            else 0
        )
        direct_count += graph_direct_count
        supporting_count = sum(
            len(academic.get(key, []) or [])
            for key in ("keywords", "entities", "relationships")
        )
        supporting_count += max(0, len(graph.get("triples", []) or []) - graph_direct_count)
        supporting_count += len(cls._publication_nodes_from_graph(graph, max_nodes=12))
        if direct_count:
            status = "grounded"
        elif supporting_count:
            status = "supporting_only"
        else:
            status = "empty"
        return {
            "status": status,
            "answerable": status == "grounded",
            "direct_evidence_count": direct_count,
            "supporting_evidence_count": supporting_count,
            "graph_direct_evidence_count": graph_direct_count,
        }

    async def query_graph(
        self,
        query_text: str,
        *,
        max_depth: int = 2,
        max_nodes: int = 80,
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
        max_depth: int = 2,
        max_nodes: int = 80,
        graph_name: str | None = None,
        seed_terms: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            from yunesa import graph_base

            if hasattr(graph_base, "start") and not graph_base.is_running():
                graph_base.start()
            if not graph_base.is_running():
                return {"nodes": [], "edges": [], "triples": [], "status": "unavailable"}

            terms = self._dedupe_terms(
                list(seed_terms or []),
                max_terms=5,
            )
            if not terms:
                terms = [query_text]

            graph_results = await asyncio.gather(
                *[
                    asyncio.to_thread(
                        graph_base.query_subgraph,
                        keyword=term,
                        max_depth=max_depth,
                        max_nodes=max_nodes,
                        graph_name=graph_name,
                    )
                    for term in terms
                ]
            )
            graph = self._merge_graph_results(graph_results, max_nodes=max_nodes)
            if not graph.get("nodes") and terms != [query_text]:
                graph = await asyncio.to_thread(
                    graph_base.query_subgraph,
                    keyword=query_text,
                    max_depth=max_depth,
                    max_nodes=max_nodes,
                    graph_name=graph_name,
                )
            if not graph.get("nodes"):
                fallback_results = await asyncio.gather(
                    *[
                        asyncio.to_thread(
                            graph_base.query_subgraph,
                            keyword=term,
                            max_depth=max_depth,
                            max_nodes=max_nodes,
                            graph_name=graph_name,
                        )
                        for term in self._fallback_graph_terms(query_text)
                    ]
                )
                graph = self._merge_graph_results(
                    fallback_results,
                    max_nodes=max_nodes,
                )

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
        retrieval_mode: str = "mix",
        include_graph: bool = True,
        graph_max_depth: int = 2,
        graph_max_nodes: int = 80,
        graph_name: str | None = None,
        trace_metadata: dict[str, Any] | None = None,
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
            academic = await self.query_academic_indexes(
                semantic_query,
                retrieval_mode=mode,
                graph_name=resolved_graph_name,
                top_k=int(os.getenv("YUNESA_ACADEMIC_GRAPHRAG_TOP_K", "8")),
                keyword_top_k=int(os.getenv("YUNESA_ACADEMIC_GRAPHRAG_KEYWORD_TOP_K", "8")),
            )
            academic = dict(academic or {})
            academic["route_decision"] = route_decision
            author_publications_raw = await self.query_author_publications(
                intent_query,
                graph_name=resolved_graph_name,
                limit=author_publication_window + 1,
            )
            author_publications_capped = len(author_publications_raw) > author_publication_window
            author_publications = author_publications_raw[:author_publication_window]
            academic["author_publications"] = author_publications
            academic.setdefault("structured_counts", {})["author_publications"] = {
                "returned": len(author_publications),
                "limit": author_publication_window,
                "complete": not author_publications_capped,
                "enumeration_query": author_publication_enumeration_query,
            }
            publication_details = await self.query_publication_details(
                intent_query,
                graph_name=resolved_graph_name,
                limit=int(os.getenv("YUNESA_PUBLICATION_DETAIL_QUERY_LIMIT", "12")),
            )
            academic["publication_details"] = publication_details
            lecturer_topic_publications = await self.query_lecturer_topic_publications(
                intent_query,
                graph_name=resolved_graph_name,
                limit=int(os.getenv("YUNESA_LECTURER_TOPIC_QUERY_LIMIT", "60")),
            )
            academic["lecturer_topic_publications"] = lecturer_topic_publications
            topic_frequencies = await self.query_topic_frequencies(
                intent_query,
                graph_name=resolved_graph_name,
                limit=int(os.getenv("YUNESA_TOPIC_FREQUENCY_QUERY_LIMIT", "15")),
            )
            academic["topic_frequencies"] = topic_frequencies
            collaborations = await self.query_collaborations(
                intent_query,
                graph_name=resolved_graph_name,
                limit=int(os.getenv("YUNESA_COLLABORATION_QUERY_LIMIT", "40")),
            )
            academic["collaborations"] = collaborations
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
            set_observation_output(
                span,
                output=self._context_summary(payload, time.perf_counter() - started_at),
            )
            return payload
