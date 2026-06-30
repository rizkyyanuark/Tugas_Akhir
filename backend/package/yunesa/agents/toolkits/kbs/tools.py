"""Knowledge base toolkit module."""

import inspect
import json
import os
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command
from pydantic import BaseModel, Field

from yunesa import knowledge_base
from yunesa.utils import logger

# ========== Common knowledge base tool functions ==========


class ListKBsInput(BaseModel):
    """Input model for listing user-accessible knowledge bases."""

    # LangChain runtime injection requires at least one parameter.
    dummy: str = Field(
        default="", description="Dummy parameter - ignore")  # Add this


@tool(args_schema=ListKBsInput)
async def list_kbs(dummy: str, runtime: ToolRuntime) -> str:  # Now has 2 params
    """List knowledge bases accessible to the current user.

    Returns a list of knowledge base names that the user can access by permission.
    The list is filtered by user role and department, and excludes knowledge bases
    that are not enabled in the current conversation.

    Returns:
        Accessible knowledge base list.
    """
    # Get user info from runtime.context.
    runtime_context = runtime.context
    user_id = getattr(runtime_context, "user_id", None)
    if not user_id:
        return "Unable to get user information"

    # Log full runtime context for debugging.
    logger.debug(f"Runtime context: {runtime_context.__dict__}")

    # Get knowledge bases enabled in the current conversation.
    enabled_kb_names = getattr(runtime_context, "knowledges", []) or []

    # Get all knowledge bases accessible to user (including name and description).
    try:
        result = await knowledge_base.get_databases_by_raw_id(user_id)
        all_kbs = result.get("databases", [])
    except Exception as e:
        logger.error(f"Failed to get user knowledge base list: {e}")
        return f"Failed to get knowledge base list: {str(e)}"

    all_kb_names = [kb["name"] for kb in all_kbs]

    logger.debug(
        f"Knowledge bases accessible to user {user_id}: {all_kb_names}")
    logger.debug(
        f"Knowledge bases enabled in current conversation for user {user_id}: {enabled_kb_names}")

    # Intersect with enabled knowledge bases.
    available_kbs = [kb for kb in all_kbs if kb["name"] in enabled_kb_names]
    academic_virtual_kb = _academic_virtual_kb_info()
    if not any(_is_academic_virtual_kb(kb.get("name", "")) for kb in available_kbs):
        available_kbs.append(academic_virtual_kb)

    if not available_kbs:
        return "No accessible knowledge base is currently available"

    # Format output (include name and description).
    kb_list = []
    for kb in available_kbs:
        name = kb.get("name", "")
        desc = kb.get("description") or "No description"
        kb_list.append({"name": name, "description": desc})

    return kb_list


class GetMindmapInput(BaseModel):
    """Input model for mindmap retrieval."""

    kb_name: str = Field(
        description="Knowledge base name used to specify which mindmap to retrieve")


@tool(args_schema=GetMindmapInput)
async def get_mindmap(kb_name: str, runtime: ToolRuntime) -> str:
    """Get the mindmap structure of a specific knowledge base.

    Use this tool when the user wants to understand overall structure,
    file categorization, and knowledge architecture.

    Args:
        kb_name: Knowledge base name

    Returns:
        Mindmap hierarchy in text format
    """
    if not kb_name:
        return "Please provide a knowledge base name"

    # Get all retrievers.
    retrievers = knowledge_base.get_retrievers()

    # Find target knowledge base.
    target_db_id = None
    target_info = None
    for db_id, info in retrievers.items():
        if info["name"] == kb_name:
            target_db_id = db_id
            target_info = info
            break

    if not target_db_id:
        return f"knowledge base '{kb_name}' does not exist"

    try:
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        kb = await kb_repo.get_by_id(target_db_id)

        if kb is None:
            return f"knowledge base {target_info['name']} does not exist"

        mindmap_data = kb.mindmap

        if not mindmap_data:
            return f"Knowledge base {target_info['name']} does not have a generated mindmap yet."

        # Convert mindmap JSON data to hierarchical text.
        def mindmap_to_text(node, level=0):
            """Recursively convert mindmap JSON to hierarchical text."""
            indent = "  " * level
            text = f"{indent}- {node.get('content', '')}\n"
            for child in node.get("children", []):
                text += mindmap_to_text(child, level + 1)
            return text

        mindmap_text = f"Mindmap structure for knowledge base {target_info['name']}:\n\n"
        mindmap_text += mindmap_to_text(mindmap_data)

        return mindmap_text

    except Exception as e:
        logger.error(f"Failed to get mindmap: {e}")
        return f"Failed to get mindmap: {str(e)}"


class QueryKBInput(BaseModel):
    """Input model for knowledge base retrieval."""

    kb_name: str = Field(description="Knowledge base name to query. For academic, lecturer, or publication questions, always query using 'yunesa_academic_kg'.")
    query_text: str = Field(
        description=(
            "Keywords for retrieval. Prefer focused keywords that help answer the question "
            "instead of directly using the user's raw input."
        )
    )
    file_name: str | None = Field(
        default=None,
        description=(
            "(Optional, leave empty unless needed) After reading the mindmap, you may provide a file keyword "
            "for fuzzy matching.\nUse only when retrieval results are too broad and need narrowing."
        ),
    )
    include_graph: bool = Field(
        default=False,
        description="Whether to include graph entities and relationships in the result for visualization.",
    )
    retrieval_mode: str = Field(
        default="hybrid",
        description=(
            "Retrieval mode: vector, keyword, subgraph, global, graph, or hybrid. "
            "Use hybrid for Academic GraphRAG because it combines Zilliz/Milvus vector evidence "
            "and Neo4j/AuraDB academic graph evidence."
        ),
    )


async def _resolve_visible_knowledge_bases_for_query(runtime: ToolRuntime | None) -> list[dict[str, Any]]:
    if runtime is None:
        return []

    context = getattr(runtime, "context", None)
    if context is None:
        return []

    visible_kbs = getattr(context, "_visible_knowledge_bases", None)
    if isinstance(visible_kbs, list):
        return visible_kbs

    try:
        from yunesa.agents.backends.knowledge_base_backend import resolve_visible_knowledge_bases_for_context

        return await resolve_visible_knowledge_bases_for_context(context)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"Failed to parse session-visible knowledge bases, skip filepath injection: {exc}")
        return []


def _find_query_target(
    *,
    kb_name: str,
    retrievers: dict[str, Any],
    visible_kbs: list[dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    if visible_kbs:
        matched_kbs = [db for db in visible_kbs if str(
            db.get("name") or "").strip() == kb_name]
        if not matched_kbs:
            return None, None, f"Knowledge base '{kb_name}' does not exist or is not enabled in current session"
        if len(matched_kbs) > 1:
            return None, None, f"Knowledge base '{kb_name}' has duplicate names; rename and retry"

        target_db_id = str(matched_kbs[0].get("db_id") or "")
        target_info = retrievers.get(target_db_id)
        if target_info is None:
            return None, None, f"knowledge base '{kb_name}' does not exist"
        return target_db_id, target_info, None

    for db_id, info in retrievers.items():
        if info["name"] == kb_name:
            return str(db_id), info, None

    return None, None, f"knowledge base '{kb_name}' does not exist"


def _is_academic_virtual_kb(kb_name: str) -> bool:
    normalized = str(kb_name or "").strip().lower().replace("-", "_").replace(" ", "_")
    allowed = {
        "yunesa",
        "academic_kg",
        "yunesa_academic_kg",
        "yunesa_academic_graphrag",
        str(os.getenv("YUNESA_ACADEMIC_KB_NAME") or "").strip().lower().replace("-", "_").replace(" ", "_"),
    }
    allowed.discard("")
    return normalized in allowed


def _academic_virtual_kb_info() -> dict[str, str]:
    return {
        "name": os.getenv("YUNESA_ACADEMIC_KB_NAME") or "yunesa_academic_kg",
        "description": "Curated YUNESA academic knowledge graph stored in Neo4j and Zilliz.",
    }


def _message_text(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return " ".join(parts).strip()
    return str(content or "").strip()


def _original_user_query(runtime: ToolRuntime | None, fallback: str) -> str:
    state = getattr(runtime, "state", None) if runtime is not None else None
    messages = state.get("messages", []) if isinstance(state, dict) else []
    for message in reversed(messages or []):
        message_type = (
            message.get("type") if isinstance(message, dict) else getattr(message, "type", None)
        )
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        if message_type == "human" or role == "user":
            text = _message_text(message)
            if text:
                return text
    return str(fallback or "").strip()


def _runtime_trace_metadata(runtime: ToolRuntime | None, tool_call_id: str | None) -> dict[str, Any]:
    if runtime is None:
        return {}
    config = getattr(runtime, "config", None)
    metadata = config.get("metadata", {}) if isinstance(config, dict) else {}
    context = getattr(runtime, "context", None)
    result = {
        key: value
        for key, value in dict(metadata or {}).items()
        if key in {"request_id", "thread_id", "user_id", "agent_id", "agent_config_id", "operation"}
    }
    for key in ("thread_id", "user_id"):
        value = getattr(context, key, None)
        if value and key not in result:
            result[key] = value
    if tool_call_id:
        result["tool_call_id"] = tool_call_id
    return result


def _format_author_publication_answer_hint(
    rows: list[dict[str, Any]],
    *,
    limit: int,
) -> str:
    """Format author publications as a Markdown table for the LLM answer hint."""
    table_rows: list[str] = []
    for index, row in enumerate(rows[:limit], start=1):
        title = str(row.get("title") or "").strip()
        if not title:
            continue

        year = str(row.get("year") or "").strip() or "-"

        venue = str(row.get("venue") or "").strip()
        doi = str(row.get("doi") or "").strip()
        venue_doi = venue or (f"doi:{doi}" if doi else "-")

        # Escape pipe characters in title to avoid breaking the table
        title_safe = title.replace("|", "\\|")
        venue_safe = venue_doi.replace("|", "\\|")
        table_rows.append(f"| {index} | {title_safe} | {year} | {venue_safe} |")

    if not table_rows:
        return ""

    header = "| No | Judul | Tahun | Venue/DOI |"
    separator = "|---|---|---|---|"
    return "\n".join([header, separator] + table_rows)


def _format_academic_rows_table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    *,
    limit: int = 12,
) -> str:
    """Format structured academic rows into a compact Markdown table."""
    table_rows: list[str] = []

    def cell_value(value: Any) -> str:
        if isinstance(value, (list, tuple, set)):
            text = ", ".join(str(item) for item in value if item)
        else:
            text = str(value or "")
        text = text.strip() or "-"
        return text.replace("|", "\\|")

    for index, row in enumerate(rows[:limit], start=1):
        cells = [str(index)]
        for _, key in columns:
            cells.append(cell_value(row.get(key)))
        table_rows.append("| " + " | ".join(cells) + " |")

    if not table_rows:
        return ""

    header = "| No | " + " | ".join(label for label, _ in columns) + " |"
    separator = "|" + "---|" * (len(columns) + 1)
    return "\n".join([header, separator] + table_rows)


def _build_ui_graph(graph_context: dict[str, Any]) -> dict[str, Any]:
    """Create a readable graph payload without exposing internal database identifiers."""
    raw_nodes = list(graph_context.get("nodes", []) or [])[:32]
    raw_edges = list(graph_context.get("edges", []) or [])[:48]
    node_id_map: dict[str, str] = {}
    display_name_map: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []

    for index, node in enumerate(raw_nodes, start=1):
        if not isinstance(node, dict):
            continue
        original_id = str(node.get("id") or "").strip()
        if not original_id:
            continue

        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        name = str(
            node.get("name")
            or node.get("title")
            or properties.get("name")
            or properties.get("title")
            or f"Entity {index}"
        ).strip()
        node_type = str(
            node.get("type")
            or properties.get("node_type")
            or properties.get("concept_type")
            or "Entity"
        ).strip()
        public_id = f"node-{index}"
        node_id_map[original_id] = public_id
        display_name_map[original_id] = name

        safe_properties = {
            key: properties.get(key)
            for key in (
                "year",
                "venue",
                "doi",
                "url",
                "affiliation",
                "program_studi",
                "concept_type",
            )
            if properties.get(key) not in (None, "")
        }
        nodes.append(
            {
                "id": public_id,
                "name": name,
                "type": node_type,
                "properties": safe_properties,
            }
        )

    edges: list[dict[str, Any]] = []
    triples: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for index, edge in enumerate(raw_edges, start=1):
        if not isinstance(edge, dict):
            continue
        source_raw = str(
            edge.get("source_id") or edge.get("source") or edge.get("sourceId") or ""
        ).strip()
        target_raw = str(
            edge.get("target_id") or edge.get("target") or edge.get("targetId") or ""
        ).strip()
        source_id = node_id_map.get(source_raw)
        target_id = node_id_map.get(target_raw)
        if not source_id or not target_id:
            continue

        relation = str(edge.get("type") or edge.get("relation") or "RELATED_TO").strip()
        signature = (source_id, target_id, relation)
        if signature in seen_edges:
            continue
        seen_edges.add(signature)
        edges.append(
            {
                "id": f"edge-{index}",
                "source_id": source_id,
                "target_id": target_id,
                "type": relation,
            }
        )
        if len(triples) < 32:
            triples.append(
                {
                    "source": display_name_map[source_raw],
                    "relation": relation,
                    "target": display_name_map[target_raw],
                }
            )

    return {
        "status": graph_context.get("status"),
        "nodes": nodes,
        "edges": edges,
        "triples": triples,
    }



def _academic_tool_response(
    *,
    payload: dict[str, Any],
    query_text: str,
    kb_name: str,
    retrieval_mode: str,
    tool_call_id: str | None,
) -> Any:
    if not tool_call_id:
        return payload

    graph_context = payload.get("graph", {})
    academic = payload.get("academic_retrieval", {}) or {}
    keyword_decomposition = dict(academic.get("keyword_decomposition", {}) or {})
    keyword_decomposition.pop("prompt", None)
    citations = {
        "entities": graph_context.get("nodes", []),
        "relationships": graph_context.get("edges", []),
        "chunks": payload.get("chunks", []),
        "academic_retrieval": {**academic, "keyword_decomposition": keyword_decomposition},
        "query": query_text,
        "kb_name": kb_name,
        "retrieval_mode": retrieval_mode,
        "storage_layer": payload.get("storage_layer", {}),
        "grounding": payload.get("grounding", {}),
    }
    author_publication_meta = (
        academic.get("structured_counts", {}).get("author_publications", {})
        if isinstance(academic.get("structured_counts"), dict)
        else {}
    )
    author_publication_payload_limit = (
        60 if author_publication_meta.get("enumeration_query") else 12
    )
    author_publication_rows = academic.get("author_publications", [])[
        :author_publication_payload_limit
    ]
    answer_hints: dict[str, Any] = {}
    if author_publication_meta.get("enumeration_query") and author_publication_rows:
        answer_hints["author_publications_markdown"] = (
            _format_author_publication_answer_hint(
                author_publication_rows,
                limit=author_publication_payload_limit,
            )
        )
        answer_hints["author_publications_instruction"] = (
            "For this publication-list query, answer from this exact list. "
            "Do not rename titles, do not invent titles, and do not summarize as "
            "'notable publications' unless the user explicitly asks for a summary."
        )

    lecturer_topic_rows = academic.get("lecturer_topic_publications", [])[:20]
    if lecturer_topic_rows:
        answer_hints["lecturer_topic_publications_markdown"] = _format_academic_rows_table(
            lecturer_topic_rows,
            [
                ("Dosen", "lecturer"),
                ("Judul", "title"),
                ("Tahun", "year"),
                ("Kecocokan", "matched_terms"),
            ],
            limit=20,
        )
        answer_hints["lecturer_topic_publications_instruction"] = (
            "For lecturer-topic questions, answer from this exact table. "
            "Do not say author names are unavailable when lecturer rows are present."
        )

    publication_detail_rows = academic.get("publication_details", [])[:12]
    if publication_detail_rows:
        answer_hints["publication_details_markdown"] = _format_academic_rows_table(
            publication_detail_rows,
            [
                ("Judul", "title"),
                ("Tahun", "year"),
                ("Authors", "authors"),
                ("Venue", "venue"),
                ("DOI", "doi"),
            ],
            limit=12,
        )
        answer_hints["publication_details_instruction"] = (
            "For exact publication questions, treat this table as authoritative. "
            "Use the authors and metadata exactly as retrieved."
        )

    collaboration_rows = academic.get("collaborations", [])[:20]
    if collaboration_rows:
        answer_hints["collaborations_markdown"] = _format_academic_rows_table(
            collaboration_rows,
            [
                ("Dosen", "lecturer"),
                ("Kolaborator", "collaborator"),
                ("Jumlah Paper", "paper_count"),
                ("Contoh Paper", "paper_titles"),
            ],
            limit=20,
        )
        answer_hints["collaborations_instruction"] = (
            "For collaboration questions, answer from this exact table. "
            "Do not infer collaborators from unrelated publications."
        )

    topic_frequency_rows = academic.get("topic_frequencies", [])[:15]
    if topic_frequency_rows:
        answer_hints["topic_frequencies_markdown"] = _format_academic_rows_table(
            topic_frequency_rows,
            [
                ("Topik", "topic"),
                ("Jenis", "concept_type"),
                ("Jumlah Publikasi", "publication_count"),
                ("Contoh Paper", "sample_titles"),
            ],
            limit=15,
        )
        answer_hints["topic_frequencies_instruction"] = (
            "For most-frequent or top-topic questions, answer only from this frequency table."
        )

    # Helper functions to prune publication items and remove verbose fields like abstract and tldr to save context tokens.
    def _prune_pub(pub):
        if not isinstance(pub, dict):
            return pub
        return {
            k: v for k, v in {
                "title": pub.get("title"),
                "year": pub.get("year"),
                "authors": pub.get("authors"),
                "doi": pub.get("doi"),
                "venue": pub.get("venue"),
                "paper_id": pub.get("paper_id"),
            }.items() if v is not None
        }

    def _prune_pub_detail(pub):
        if not isinstance(pub, dict):
            return pub
        return {
            k: v for k, v in {
                "title": pub.get("title"),
                "year": pub.get("year"),
                "authors": pub.get("authors"),
                "doi": pub.get("doi"),
                "venue": pub.get("venue"),
                "concepts": pub.get("concepts"),
                "paper_id": pub.get("paper_id"),
            }.items() if v is not None
        }

    def _prune_lecturer_topic(pub):
        if not isinstance(pub, dict):
            return pub
        return {
            k: v for k, v in {
                "lecturer": pub.get("lecturer"),
                "affiliation": pub.get("affiliation"),
                "matched_terms": pub.get("matched_terms"),
                "title": pub.get("title"),
                "year": pub.get("year"),
                "authors": pub.get("authors"),
                "doi": pub.get("doi"),
                "paper_id": pub.get("paper_id"),
            }.items() if v is not None
        }

    # Build a heavily pruned payload specifically for the LLM's context.
    # Exclude verbose raw subgraphs and chunks since the formatted CSV representation
    # is already provided in the `summary` field, and full metadata is preserved in `citations`
    # for frontend rendering/observability.
    llm_academic_retrieval = {
        "status": academic.get("status"),
        "mode": academic.get("mode"),
        "academicrag_mode": academic.get("academicrag_mode"),
        "kg_mode": academic.get("kg_mode"),
        "route_decision": academic.get("route_decision"),
        "author_publications": [_prune_pub(p) for p in author_publication_rows],
        "publication_details": [_prune_pub_detail(p) for p in academic.get("publication_details", []) or []],
        "lecturer_topic_publications": [_prune_lecturer_topic(p) for p in academic.get("lecturer_topic_publications", []) or []],
        "topic_frequencies": academic.get("topic_frequencies", [])[:15] if academic.get("topic_frequencies") else [],
        "collaborations": academic.get("collaborations", [])[:24] if academic.get("collaborations") else [],
        "structured_counts": academic.get("structured_counts", {}),
    }
    ui_graph = _build_ui_graph(graph_context)

    tool_payload = {
        "type": "academic_graphrag_result",
        "query": query_text,
        "kb_name": kb_name,
        "retrieval_mode": retrieval_mode,
        "summary": payload.get("evidence_text") or "",
        "answer_hints": answer_hints,
        "grounding": payload.get("grounding", {}),
        "academic_retrieval": llm_academic_retrieval,
        # Retained for the frontend visualizer. Raw IDs/provenance remain in citations.
        "graph": ui_graph,
        "answer_policy": (
            "Use only retrieved evidence. If grounding.status is empty or supporting_only, "
            "state that the requested academic data was not found and do not answer from prior knowledge. "
            "Prioritize synthesising context from the structured RAG chunks and triples. "
            "Clearly respond in the same language as the user's question (e.g. if the user asks in Indonesian, answer in Indonesian; if in English, answer in English). "
            "For lecturer publication list questions, enumerate author_publications rows returned by "
            "the tool and state the returned count. If structured_counts.author_publications.complete "
            "is false, say that the list is capped by the retrieval limit. For exact publication "
            "author/collaboration questions, prioritize publication_details over general collaborations. "
            "When answer_hints.author_publications_markdown is present, use that exact list and do "
            "not rename, paraphrase, or invent publication titles. "
            "When answer_hints.lecturer_topic_publications_markdown, "
            "answer_hints.publication_details_markdown, answer_hints.collaborations_markdown, "
            "or answer_hints.topic_frequencies_markdown are present, use those exact tables as the "
            "primary answer basis before summarising. "
            "FORMATTING: Always present publication lists as a numbered Markdown table with columns "
            "No | Judul | Tahun | Venue/DOI. Open with a brief one-sentence contextual summary before "
            "the table. Close with a concise paragraph noting the total count and any retrieval cap. "
            "Use bold (**text**) for key terms. Never output a plain bullet list for publication "
            "queries; always use the numbered table format. The graph field is UI diagnostic data, "
            "not an answer outline. Never dump entity IDs, concept/node IDs, keyword inventories, "
            "relationship codes (such as SKOS_RELATED, SKOS_BROADER, or other Neo4j relationship types), "
            "or raw triples in the response text unless the user explicitly asks to inspect graph internals. "
            "Deduplicate publication titles case-insensitively. Answer the requested intent directly and "
            "do not repeat the same evidence under expertise, publications, keywords, entities, "
            "relationships, and triples sections."
        ),
    }

    return Command(
        update={
            "citations": [citations],
            "messages": [
                ToolMessage(
                    content=json.dumps(tool_payload, ensure_ascii=False, default=str),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


async def _build_academic_graphrag_context(
    *,
    query_text: str,
    original_query_text: str,
    chunks: list[dict[str, Any]],
    kb_name: str,
    collection_id: str | None,
    retrieval_mode: str,
    include_graph: bool,
    kwargs: dict[str, Any],
    trace_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retrieve AcademicRAG-style context from Milvus/Zilliz and Neo4j/AuraDB."""
    from yunesa.knowledge.graphrag import AcademicGraphRAGService

    service = AcademicGraphRAGService()
    return await service.build_context_package(
        query_text=query_text,
        original_query_text=original_query_text,
        chunks=chunks,
        kb_name=kb_name,
        collection_id=collection_id,
        retrieval_mode=retrieval_mode,
        include_graph=include_graph,
        graph_max_depth=int(kwargs.get("graph_max_depth", kwargs.get("graph_hops", 2))),
        graph_max_nodes=int(kwargs.get("graph_max_nodes", 80)),
        graph_name=kwargs.get("graph_name"),
        trace_metadata=trace_metadata,
    )


@tool(args_schema=QueryKBInput)
async def query_kb(
    kb_name: str,
    query_text: str,
    file_name: str | None = None,
    include_graph: bool = False,
    retrieval_mode: str = "hybrid",
    runtime: ToolRuntime = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Any:
    """Retrieve content from a specified knowledge base.

    Use this tool when the user needs specific content retrieval. It retrieves
    related document chunks from the target knowledge base by keywords.

    Args:
        kb_name: Knowledge base name. For academic, lecturer, or publication questions, always use 'yunesa_academic_kg'.
        query_text: Retrieval keywords
        file_name: Optional filename filter

    Returns:
        Retrieval result
    """
    if not kb_name:
        return "Please provide a knowledge base name"
    if not query_text:
        return "Please provide query text"

    original_query_text = _original_user_query(runtime, query_text)
    trace_metadata = _runtime_trace_metadata(runtime, tool_call_id)

    # Get all retrievers.
    retrievers = knowledge_base.get_retrievers()

    visible_kbs = await _resolve_visible_knowledge_bases_for_query(runtime)

    target_db_id, target_info, target_error = _find_query_target(
        kb_name=kb_name,
        retrievers=retrievers,
        visible_kbs=visible_kbs,
    )
    if target_error:
        if not _is_academic_virtual_kb(kb_name):
            return target_error

        from yunesa.knowledge.graphrag import AcademicGraphRAGService

        resolved_retrieval_mode = AcademicGraphRAGService.normalize_mode(
            retrieval_mode,
            include_graph=include_graph,
        )
        payload = await _build_academic_graphrag_context(
            query_text=query_text,
            original_query_text=original_query_text,
            chunks=[],
            kb_name=kb_name,
            collection_id=None,
            retrieval_mode=resolved_retrieval_mode,
            include_graph=AcademicGraphRAGService.uses_graph(
                resolved_retrieval_mode,
                include_graph=include_graph,
            ),
            kwargs={},
            trace_metadata=trace_metadata,
        )
        return _academic_tool_response(
            payload=payload,
            query_text=query_text,
            kb_name=kb_name,
            retrieval_mode=resolved_retrieval_mode,
            tool_call_id=tool_call_id,
        )

    metadata = target_info.get("metadata") if isinstance(
        target_info, dict) else None
    kb_type = str((metadata or {}).get("kb_type") or "").strip().lower()

    try:
        retriever = target_info["retriever"]
        kwargs = {}
        if file_name:
            kwargs["file_name"] = file_name

        from yunesa.knowledge.graphrag import AcademicGraphRAGService

        resolved_retrieval_mode = AcademicGraphRAGService.normalize_mode(
            retrieval_mode,
            include_graph=include_graph,
        )
        if kb_type == "milvus":
            kwargs["search_mode"] = AcademicGraphRAGService.milvus_search_mode(
                resolved_retrieval_mode
            )

        if inspect.iscoroutinefunction(retriever):
            result = await retriever(query_text, **kwargs)
        else:
            result = retriever(query_text, **kwargs)

        if kb_type != "milvus":
            return result

        if not isinstance(result, list):
            return f"Knowledge base '{kb_name}' returned a non-Milvus chunk list; filepath injection is unavailable"

        from yunesa.agents.backends.knowledge_base_backend import inject_filepaths_into_retrieval_result

        # Only Milvus result file_ids map to local filesystem paths and can be enriched.
        enriched_result = await inject_filepaths_into_retrieval_result(
            retrieval_chunks=result,
            visible_kbs=visible_kbs,
            target_db_id=target_db_id,
            target_kb_name=kb_name,
        )

        if _is_academic_virtual_kb(kb_name) or AcademicGraphRAGService.uses_graph(
            resolved_retrieval_mode,
            include_graph=include_graph,
        ):
            payload = await _build_academic_graphrag_context(
                query_text=query_text,
                original_query_text=original_query_text,
                chunks=enriched_result,
                kb_name=kb_name,
                collection_id=target_db_id,
                retrieval_mode=resolved_retrieval_mode,
                include_graph=AcademicGraphRAGService.uses_graph(
                    resolved_retrieval_mode,
                    include_graph=include_graph,
                ),
                kwargs=kwargs,
                trace_metadata=trace_metadata,
            )
            return _academic_tool_response(
                payload=payload,
                query_text=query_text,
                kb_name=kb_name,
                retrieval_mode=resolved_retrieval_mode,
                tool_call_id=tool_call_id,
            )

        return enriched_result

    except Exception as e:
        logger.error(f"retrievalfailed: {e}")
        return f"retrievalfailed: {str(e)}"


def get_common_kb_tools() -> list:
    """Get common knowledge base tool list.

    Returns three common tools:
    - list_kbs: list user-accessible knowledge bases
    - get_mindmap: get mindmap for a specified knowledge base
    - query_kb: retrieve from a specified knowledge base
    """
    return [list_kbs, get_mindmap, query_kb]
