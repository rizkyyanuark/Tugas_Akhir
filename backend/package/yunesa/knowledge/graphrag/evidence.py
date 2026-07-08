import csv
import hashlib
import io
import os
import re
from typing import Any, Callable
from yunesa.utils import logger
from .query_planner import AcademicQueryPlanner, AcademicQueryParam
from .base import BaseGraphStorage
from .storage import Neo4jGraphStorage

def _clip_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."

def _format_values(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if item)
    return str(value or "")

class AcademicEvidence:
    """Methods to assemble, compact, and ground retrieved knowledge graph and vector context."""

    @classmethod
    def _dedupe_terms(cls, values: list[Any], *, max_terms: int = 8) -> list[str]:
        return AcademicQueryPlanner.dedupe_terms(values, max_terms=max_terms)

    @classmethod
    def _query_terms(cls, query_text: str, *, max_terms: int = 8) -> list[str]:
        return AcademicQueryPlanner.query_terms(query_text, max_terms=max_terms)

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
            if normalized in AcademicQueryPlanner.GRAPH_STOPWORDS:
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
        except Exception as exc:
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
        mode: str = "hybrid",
    ) -> str:
        del grounding
        param = AcademicQueryParam.from_runtime(mode)
        is_global = param.resolved_kg_mode() == "global"
        
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
                    _clip_text(description, 800),
                    (node.get("normalized") or {}).get("source")
                    or node.get("graph_type")
                    or "neo4j",
                ]
            )

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
                        _clip_text(properties.get("description") or "", 600),
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
                    _clip_text(chunk.get("content") or "", 1600),
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

        community_summaries = (academic or {}).get("community_summaries") or []
        community_rows: list[list[Any]] = [["id", "community_id", "summary"]]
        for index, comm in enumerate(community_summaries, start=1):
            community_rows.append([
                index,
                comm.get("community_id") or comm.get("id"),
                _clip_text(comm.get("content") or "", 1200)
            ])

        evidence_parts = []
        if len(community_rows) > 1:
            evidence_parts.append(
                "-----Community Summaries-----\n"
                "```csv\n"
                f"{to_csv(community_rows)}\n"
                "```"
            )
        evidence_parts.append(
            "-----Entities-----\n"
            "```csv\n"
            f"{to_csv(entity_rows)}\n"
            "```"
        )
        evidence_parts.append(
            "-----Relationships-----\n"
            "```csv\n"
            f"{to_csv(relationship_rows)}\n"
            "```"
        )
        evidence_parts.append(
            "-----Sources-----\n"
            "```csv\n"
            f"{to_csv(source_rows)}\n"
            "```"
        )
        evidence = "\n".join(evidence_parts)
        logger.debug(
            "Academic GraphRAG evidence_text size: %d chars "
            "(communities=%d, entities=%d, relations=%d, sources=%d)",
            len(evidence),
            len(community_rows) - 1,
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
        terms = cls._query_terms(query_text, max_terms=24)
        generic_stopwords = {
            "paper", "papers", "publication", "publications", "article", "articles", "lecturer", "lecturers",
            "researcher", "researchers", "professor", "professors", "author", "authors", "write", "written",
            "topic", "topics", "study", "studies", "research", "researching", "list", "find", "search", "show",
            "get", "about", "using", "use", "used", "method", "methods", "algorithm", "algorithms",
            "dataset", "datasets", "model", "models", "approach", "approaches", "framework", "frameworks",
            "results", "result", "performance", "analysis", "evaluation", "evaluate", "implement", "implementation",
            "paper", "publikasi", "artikel", "dosen", "peneliti", "penulis", "tulis", "ditulis",
            "topik", "penelitian", "riset", "daftar", "cari", "carikan", "tunjukkan", "dapatkan",
            "tentang", "menggunakan", "penerapan", "implementasi", "metode", "algoritma", "dataset",
            "model", "pendekatan", "kerangka", "hasil", "performa", "analisa", "analisis", "evaluasi",
            "siapa", "apa", "bagaimana", "dimana", "kapan", "mengapa", "kenapa", "saja", "yang", "dengan",
            "pada", "dan", "untuk", "oleh", "di", "ke", "dari", "adalah", "yaitu", "yakni", "sebagai",
            "dalam", "secara", "bahwa", "ini", "itu", "saya", "kami", "mereka", "kita", "kamu", "dia",
        }
        topic_terms = [t.lower() for t in terms if t.lower() not in generic_stopwords and len(t) >= 3]

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
                "berkolaborasi", "collaborat", "hubungan", "relasi",
                "collaboration", "relationship", "connected", "terhubung",
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
        
        # Avoid direct circular dependency by using standard normalizer logic here
        from .normalizers import AcademicNormalizers
        supporting_count += len(AcademicNormalizers._publication_nodes_from_graph(graph, max_nodes=12))
        
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
