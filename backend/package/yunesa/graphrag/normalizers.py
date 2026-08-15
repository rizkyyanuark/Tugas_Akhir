import re
from typing import Any
from .query_planner import AcademicQueryPlanner

def _clip_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."

def _format_values(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if item)
    return str(value or "")

class AcademicNormalizers:
    """Methods to normalize Neo4j and Milvus outputs into grounding chunks."""

    @classmethod
    def _node_label(cls, node: dict[str, Any]) -> str:
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
    def normalize_author_publication_chunks(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        query_text: str = "",
        max_chunks: int = 12,
        max_chars: int = 1800,
    ) -> list[dict[str, Any]]:
        terms = set(AcademicQueryPlanner.query_terms(query_text, max_terms=24))
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
                f"Authors: {_format_values(row.get('authors')) or 'unknown'}",
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
                    "content": _clip_text("\n".join(parts), max_chars),
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
                f"Authors: {_format_values(row.get('authors')) or 'unknown'}",
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
                    "content": _clip_text("\n".join(parts), max_chars),
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
                f"Authors: {_format_values(row.get('authors')) or 'unknown'}",
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
                    "content": _clip_text("\n".join(parts), max_chars),
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
            titles = _format_values(row.get("sample_titles"))
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
            titles = _format_values(row.get("paper_titles"))
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
                    "content": _clip_text(chunk.get("content", ""), max_chars),
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
                    current["content"] = _clip_text(f"{current['content']}\n{content}", max_chars)
                if isinstance(distance, (int, float)) and (
                    not isinstance(current.get("score"), (int, float)) or distance < current["score"]
                ):
                    current["score"] = distance
                continue
            grouped[key] = {
                "rank": 0,
                "content": _clip_text(content, max_chars),
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
            key=lambda row: (
                0 if isinstance(row.get("score"), (int, float)) else 1,
                row.get("score") or 0.0,
                row.get("_position"),
            ),
        )
        for index, item in enumerate(normalized[:max_chunks], start=1):
            item["rank"] = index
            item.pop("_position", None)
        return normalized
