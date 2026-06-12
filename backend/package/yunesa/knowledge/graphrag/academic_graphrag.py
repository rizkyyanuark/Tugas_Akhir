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
    GRAPH_STOPWORDS = {
        "about",
        "after",
        "again",
        "against",
        "antara",
        "apakah",
        "apa",
        "based",
        "before",
        "berikan",
        "dari",
        "dalam",
        "dan",
        "dengan",
        "dosen",
        "ditulis",
        "from",
        "gimana",
        "hasil",
        "membahas",
        "menggunakan",
        "oleh",
        "pada",
        "paper",
        "penelitian",
        "penulis",
        "siapa",
        "show",
        "saja",
        "system",
        "that",
        "tahun",
        "this",
        "untuk",
        "using",
        "what",
        "yang",
    }
    AUTHOR_PUBLICATION_QUERY_MARKERS = {
        "author",
        "authors",
        "paper",
        "papers",
        "penelitian",
        "publikasi",
        "publication",
        "publications",
        "ditulis",
        "menulis",
        "penulis",
        "wrote",
        "written",
    }
    LECTURER_TOPIC_QUERY_MARKERS = {
        "author",
        "authors",
        "dosen",
        "lecturer",
        "lecturers",
        "penulis",
        "researcher",
        "researchers",
        "siapa",
    }
    TOPIC_FREQUENCY_QUERY_MARKERS = {
        "frequent",
        "frequently",
        "most",
        "paling",
        "sering",
        "terbanyak",
        "top",
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
        if mode in {"subgraph", "global", "graph", "hybrid", "mix"}:
            return "hybrid"
        return "vector"

    @classmethod
    def uses_graph(cls, mode: str, include_graph: bool = False) -> bool:
        return mode in {"subgraph", "graph", "hybrid", "mix"}

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
    def _dedupe_terms(values: list[Any], *, max_terms: int = 8) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,;|[]'\"")
            normalized = text.casefold()
            if not text or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(text)
            if len(terms) >= max_terms:
                break
        return terms

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
        return cls._dedupe_terms(candidates, max_terms=4)

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
                  coalesce(collaborator.label, collaborator.nama_norm, collaborator.nama_dosen, collaborator.name) AS collaborator,
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
                OPTIONAL MATCH (paper)-[:HAS_KEYWORD|HAS_TOPIC|USES_METHOD|USES_MODEL|USES_DATASET|EVALUATED_WITH|BELONGS_TO_DOMAIN]->(concept)
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
        values: list[str] = []
        for row in rows or []:
            raw = row.get("keywords")
            if isinstance(raw, (list, tuple, set)):
                values.extend(str(item) for item in raw)
            else:
                values.extend(re.split(r"[,;|\n]", str(raw or "").strip("[]")))
        return cls._dedupe_terms(values, max_terms=max_terms)

    @classmethod
    def decompose_query_keywords(
        cls,
        query_text: str,
        keyword_rows: list[dict[str, Any]] | None,
        *,
        max_terms: int = 8,
    ) -> dict[str, Any]:
        """Build AcademicRAG-style local and global clues without another LLM call."""
        query_terms = cls._query_terms(query_text, max_terms=max_terms)
        query_tokens = set(query_terms)
        clue_terms = cls._content_keyword_terms(keyword_rows, max_terms=max_terms * 2)
        low_level: list[str] = []
        high_level: list[str] = []

        for clue in clue_terms:
            clue_tokens = set(cls._query_terms(clue, max_terms=max_terms))
            overlap = len(query_tokens & clue_tokens) / max(len(clue_tokens), 1)
            if clue.casefold() in query_text.casefold() or overlap >= 0.5:
                low_level.append(clue)
            else:
                high_level.append(clue)

        low_level = cls._dedupe_terms(
            [*low_level, *query_terms] or [query_text],
            max_terms=max_terms,
        )
        high_level = cls._dedupe_terms(
            high_level or clue_terms or low_level,
            max_terms=max_terms,
        )
        return {
            "provider": "heuristic",
            "high_level_keywords": high_level,
            "low_level_keywords": low_level,
            "content_keyword_clues": clue_terms[:max_terms],
        }

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
    ) -> dict[str, Any]:
        """Retrieve from canonical AcademicRAG indexes produced by the notebook pipeline."""
        started_at = time.perf_counter()
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
            "keyword_decomposition": {},
            "local_query": query_text,
            "global_query": query_text,
            "diagnostics": {
                "embedding_batches": 0,
                "dense_embedding_status": "not_requested",
            },
        }
        if not cls._academic_milvus_enabled():
            payload["status"] = "disabled"
            return payload

        needs_clues = mode in {"keyword", "subgraph", "global", "graph", "hybrid", "mix"}
        needs_local = mode in {"subgraph", "graph", "hybrid", "mix"}
        needs_global = mode in {"global", "graph", "hybrid", "mix"}
        needs_raw_papers = mode in {"vector", "mix"}
        needs_fused_papers = mode in {"keyword", "subgraph", "global", "graph", "hybrid"}

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
                cls._search_academic_collection(
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
                cls._search_academic_collection(
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
            decomposition = cls.decompose_query_keywords(
                query_text,
                payload["keywords"],
                max_terms=max(keyword_top_k, 1),
            )
            payload["keyword_decomposition"] = decomposition
            payload["local_query"] = cls._keyword_query(
                decomposition["low_level_keywords"],
                query_text,
            )
            payload["global_query"] = cls._keyword_query(
                decomposition["high_level_keywords"],
                query_text,
            )

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
                cls._search_academic_collection(
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
                cls._search_academic_collection(
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
                cls._search_academic_collection(
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
        grounding: dict[str, Any] | None = None,
    ) -> str:
        lines = ["Academic GraphRAG evidence:"]
        grounding = grounding or {}
        lines.append(
            "Grounding status: "
            f"{grounding.get('status', 'unknown')} "
            f"(direct={grounding.get('direct_evidence_count', 0)}, "
            f"supporting={grounding.get('supporting_evidence_count', 0)})"
        )
        if chunks:
            lines.append("Vector evidence:")
            for chunk in chunks:
                source = chunk.get("source") or "knowledge-base"
                score = chunk.get("score")
                score_text = f", score={score:.4f}" if isinstance(score, (int, float)) else ""
                lines.append(f"- [{chunk['rank']}] source={source}{score_text}: {chunk['content']}")

        academic = academic or {}
        author_publications = academic.get("author_publications") or []
        if author_publications:
            lines.append("Author publication evidence:")
            for row in author_publications[:12]:
                lines.append(
                    "- "
                    f"title={row.get('title') or 'unknown'} | "
                    f"year={row.get('year') or 'unknown'} | "
                    f"authors={cls._clip_text(cls._format_values(row.get('authors')), 240)} | "
                    f"doi={row.get('doi') or '-'} | "
                    f"tldr={cls._clip_text(row.get('tldr', ''), 500)} | "
                    f"abstract={cls._clip_text(row.get('abstract', ''), 800)}"
                )

        publication_details = academic.get("publication_details") or []
        if publication_details:
            lines.append("Exact publication metadata evidence:")
            for row in publication_details[:8]:
                concepts = row.get("concepts") or []
                concept_text = ", ".join(
                    f"{item.get('relation')}: {item.get('value')}"
                    for item in concepts
                    if isinstance(item, dict) and item.get("value")
                )
                lines.append(
                    "- "
                    f"title={row.get('title') or 'unknown'} | "
                    f"year={row.get('year') or 'unknown'} | "
                    f"authors={cls._clip_text(cls._format_values(row.get('authors')), 320)} | "
                    f"doi={row.get('doi') or '-'} | "
                    f"concepts={cls._clip_text(concept_text, 500)} | "
                    f"tldr={cls._clip_text(row.get('tldr', ''), 500)} | "
                    f"abstract={cls._clip_text(row.get('abstract', ''), 1000)}"
                )

        lecturer_topic_publications = academic.get("lecturer_topic_publications") or []
        if lecturer_topic_publications:
            lines.append("Lecturer-topic publication evidence:")
            for row in lecturer_topic_publications[:12]:
                matched_terms = row.get("matched_terms") or []
                if isinstance(matched_terms, (list, tuple, set)):
                    matched_text = ", ".join(str(item) for item in matched_terms if item)
                else:
                    matched_text = str(matched_terms or "")
                lines.append(
                    "- "
                    f"lecturer={row.get('lecturer') or 'unknown'} | "
                    f"affiliation={row.get('affiliation') or 'unknown'} | "
                    f"title={row.get('title') or 'unknown'} | "
                    f"year={row.get('year') or 'unknown'} | "
                    f"authors={cls._clip_text(cls._format_values(row.get('authors')), 240)} | "
                    f"matched_terms={matched_text or '-'} | "
                    f"doi={row.get('doi') or '-'} | "
                    f"tldr={cls._clip_text(row.get('tldr', ''), 500)} | "
                    f"abstract={cls._clip_text(row.get('abstract', ''), 800)}"
                )

        topic_frequencies = academic.get("topic_frequencies") or []
        if topic_frequencies:
            lines.append("Topic frequency evidence:")
            for row in topic_frequencies[:15]:
                lines.append(
                    "- "
                    f"topic={row.get('topic') or 'unknown'} | "
                    f"concept_type={row.get('concept_type') or 'Concept'} | "
                    f"publication_count={row.get('publication_count') or 0} | "
                    f"sample_titles={cls._clip_text(cls._format_values(row.get('sample_titles')), 600)}"
                )

        collaborations = academic.get("collaborations") or []
        if collaborations:
            lines.append("Lecturer collaboration evidence:")
            for row in collaborations[:12]:
                lines.append(
                    "- "
                    f"lecturer={row.get('lecturer') or 'unknown'} | "
                    f"collaborator={row.get('collaborator') or 'unknown'} | "
                    f"paper_count={row.get('paper_count') or 0} | "
                    f"shared_publications={cls._clip_text(cls._format_values(row.get('paper_titles')), 800)}"
                )

        graph_publications = cls._publication_nodes_from_graph(graph, max_nodes=10)
        if graph_publications:
            lines.append("Graph publication node evidence:")
            for row in graph_publications[:10]:
                lines.append(
                    "- "
                    f"title={row.get('title') or 'unknown'} | "
                    f"year={row.get('year') or 'unknown'} | "
                    f"authors={cls._clip_text(row.get('authors', ''), 240)} | "
                    f"doi={row.get('doi') or '-'} | "
                    f"tldr={cls._clip_text(row.get('tldr', ''), 500)} | "
                    f"abstract={cls._clip_text(row.get('abstract', ''), 800)}"
                )

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

        if grounding.get("status") == "empty":
            lines.append(
                "No relevant evidence was found. Answer that the academic data was not found; "
                "do not use model memory to fill the gap."
            )

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
        keyword_decomposition = academic.get("keyword_decomposition") or {}
        return {
            "mode": payload.get("mode"),
            "kb_name": (payload.get("knowledge_base") or {}).get("name"),
            "collection_id": (payload.get("knowledge_base") or {}).get("collection_id"),
            "chunks": len(payload.get("chunks", []) or []),
            "academic_status": academic.get("status"),
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
        direct_count = len(chunks)
        structured_direct_count = sum(
            len(academic.get(key, []) or [])
            for key in (
                "publication_details",
                "author_publications",
                "lecturer_topic_publications",
                "topic_frequencies",
                "collaborations",
            )
        )
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
            if relation_intent and structured_direct_count == 0
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
            mode = self.normalize_mode(retrieval_mode, include_graph=include_graph)
            resolved_graph_name = self._academic_graph_name(graph_name)
            academic = await self.query_academic_indexes(
                semantic_query,
                retrieval_mode=mode,
                graph_name=resolved_graph_name,
                top_k=int(os.getenv("YUNESA_ACADEMIC_GRAPHRAG_TOP_K", "8")),
                keyword_top_k=int(os.getenv("YUNESA_ACADEMIC_GRAPHRAG_KEYWORD_TOP_K", "8")),
            )
            academic = dict(academic or {})
            author_publications = await self.query_author_publications(
                intent_query,
                graph_name=resolved_graph_name,
                limit=int(os.getenv("YUNESA_AUTHOR_PUBLICATION_QUERY_LIMIT", "60")),
            )
            academic["author_publications"] = author_publications
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
            if collaborations:
                author_publications = []
                lecturer_topic_publications = []
                academic["author_publications"] = []
                academic["lecturer_topic_publications"] = []
            author_chunks = self.normalize_author_publication_chunks(
                author_publications,
                query_text=intent_query,
                max_chunks=int(os.getenv("YUNESA_AUTHOR_PUBLICATION_CHUNKS", "12")),
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
                normalized_chunks = direct_chunks + supplemental_chunks
                for index, item in enumerate(normalized_chunks, start=1):
                    item["rank"] = index
            else:
                normalized_chunks = academic_chunks or self.normalize_chunks(chunks)
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

            payload = {
                "mode": mode,
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
            )
            set_observation_output(
                span,
                output=self._context_summary(payload, time.perf_counter() - started_at),
            )
            return payload
