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

    kb_name: str = Field(description="Knowledge base name to query")
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
        default="mix",
        description=(
            "Retrieval mode: vector, keyword, subgraph, global, graph, hybrid, or mix. "
            "Use mix for Academic GraphRAG because it combines Zilliz/Milvus vector evidence "
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
    citations = {
        "entities": graph_context.get("nodes", []),
        "relationships": graph_context.get("edges", []),
        "chunks": payload.get("chunks", []),
        "academic_retrieval": academic,
        "query": query_text,
        "kb_name": kb_name,
        "retrieval_mode": retrieval_mode,
        "storage_layer": payload.get("storage_layer", {}),
        "grounding": payload.get("grounding", {}),
    }
    tool_payload = {
        "type": "academic_graphrag_result",
        "query": query_text,
        "kb_name": kb_name,
        "retrieval_mode": retrieval_mode,
        "summary": payload.get("evidence_text") or "",
        "grounding": payload.get("grounding", {}),
        "chunks": payload.get("chunks", []),
        "academic_retrieval": {
            "status": academic.get("status"),
            "mode": academic.get("mode"),
            "graph_name": academic.get("graph_name"),
            "milvus_database": academic.get("milvus_database"),
            "paper_chunks": academic.get("paper_chunks", [])[:8],
            "author_publications": academic.get("author_publications", [])[:24],
            "lecturer_topic_publications": academic.get("lecturer_topic_publications", [])[:24],
            "keywords": academic.get("keywords", [])[:8],
            "entities": academic.get("entities", [])[:12],
            "relationships": academic.get("relationships", [])[:12],
            "keyword_decomposition": academic.get("keyword_decomposition", {}),
            "local_query": academic.get("local_query"),
            "global_query": academic.get("global_query"),
            "diagnostics": academic.get("diagnostics", {}),
        },
        "graph": {
            "status": graph_context.get("status"),
            "nodes": graph_context.get("nodes", [])[:24],
            "edges": graph_context.get("edges", [])[:32],
            "triples": graph_context.get("triples", [])[:32],
        },
        "answer_policy": (
            "Use only retrieved evidence. If grounding.status is empty or supporting_only, "
            "state that the requested academic data was not found and do not answer from prior knowledge."
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
    chunks: list[dict[str, Any]],
    kb_name: str,
    collection_id: str | None,
    retrieval_mode: str,
    include_graph: bool,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Retrieve AcademicRAG-style context from Milvus/Zilliz and Neo4j/AuraDB."""
    from yunesa.knowledge.graphrag import AcademicGraphRAGService

    service = AcademicGraphRAGService()
    return await service.build_context_package(
        query_text=query_text,
        chunks=chunks,
        kb_name=kb_name,
        collection_id=collection_id,
        retrieval_mode=retrieval_mode,
        include_graph=include_graph,
        graph_max_depth=int(kwargs.get("graph_max_depth", kwargs.get("graph_hops", 2))),
        graph_max_nodes=int(kwargs.get("graph_max_nodes", 80)),
        graph_name=kwargs.get("graph_name"),
    )


@tool(args_schema=QueryKBInput)
async def query_kb(
    kb_name: str,
    query_text: str,
    file_name: str | None = None,
    include_graph: bool = False,
    retrieval_mode: str = "mix",
    runtime: ToolRuntime = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Any:
    """Retrieve content from a specified knowledge base.

    Use this tool when the user needs specific content retrieval. It retrieves
    related document chunks from the target knowledge base by keywords.

    Args:
        kb_name: Knowledge base name
        query_text: Retrieval keywords
        file_name: Optional filename filter

    Returns:
        Retrieval result
    """
    if not kb_name:
        return "Please provide a knowledge base name"
    if not query_text:
        return "Please provide query text"

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
            chunks=[],
            kb_name=kb_name,
            collection_id=None,
            retrieval_mode=resolved_retrieval_mode,
            include_graph=AcademicGraphRAGService.uses_graph(
                resolved_retrieval_mode,
                include_graph=include_graph,
            ),
            kwargs={},
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
                chunks=enriched_result,
                kb_name=kb_name,
                collection_id=target_db_id,
                retrieval_mode=resolved_retrieval_mode,
                include_graph=AcademicGraphRAGService.uses_graph(
                    resolved_retrieval_mode,
                    include_graph=include_graph,
                ),
                kwargs=kwargs,
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
