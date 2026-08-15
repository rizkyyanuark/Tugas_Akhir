"""Academic knowledge graph specialized tools for Agent Sayha."""

import io
import csv
from typing import Annotated, Any
from langchain_core.tools import InjectedToolCallId
from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import BaseModel, Field

from yunesa import knowledge_base
from yunesa.utils import logger
from yunesa.agents.toolkits.registry import tool
from .tools import (
    _resolve_visible_knowledge_bases_for_query,
    _find_query_target,
    _academic_tool_response,
)
from yunesa.graphrag import AcademicGraphRAGService


async def _run_specialized_academic_retrieval(
    *,
    kb_name: str,
    query_text: str,
    retrieval_key: str,
    query_func: Any,
    runtime: ToolRuntime | None,
    tool_call_id: str | None,
    limit: int,
    additional_kwargs: dict[str, Any] = None,
) -> Any:
    # 1. Resolve permissions
    visible_kbs = await _resolve_visible_knowledge_bases_for_query(runtime)
    retrievers = knowledge_base.get_retrievers()
    target_db_id, target_info, target_error = _find_query_target(
        kb_name=kb_name,
        retrievers=retrievers,
        visible_kbs=visible_kbs,
    )
    if target_error:
        return target_error

    # 2. Setup service and graph name
    service = AcademicGraphRAGService()
    resolved_graph_name = service._academic_graph_name(None)

    # 3. Call the Cypher query method with skip_intent_check=True
    kwargs = {"graph_name": resolved_graph_name, "limit": limit, "skip_intent_check": True}
    if additional_kwargs:
        kwargs.update(additional_kwargs)

    rows = await query_func(query_text, **kwargs)

    # 4. Construct academic dictionary
    academic = {
        "status": "ok",
        "mode": "subgraph",
        "academicrag_mode": "subgraph",
        "kg_mode": "local",
        "route_decision": {
            "requested_mode": "subgraph",
            "effective_mode": "subgraph",
            "auto_routed": True,
            "reason": "specialized_tool",
            "intents": {retrieval_key: True},
        },
        "author_publications": [],
        "publication_details": [],
        "lecturer_topic_publications": [],
        "topic_frequencies": [],
        "collaborations": [],
        "structured_counts": {},
    }
    academic[retrieval_key] = rows

    # Special handling for structured counts
    if retrieval_key == "author_publications":
        academic["structured_counts"]["author_publications"] = {
            "returned": len(rows),
            "limit": limit,
            "complete": len(rows) <= limit,
            "enumeration_query": True,
        }

    # 5. Map rows to graph
    graph = service._map_structured_rows_to_graph(academic)
    graph["triples"] = service._triples_from_graph(graph)
    graph["status"] = "ok" if graph["nodes"] else "empty"

    # 6. Build final payload
    payload = {
        "mode": "subgraph",
        "requested_mode": "subgraph",
        "route_decision": academic["route_decision"],
        "query": query_text,
        "original_query": query_text,
        "knowledge_base": {"name": kb_name, "collection_id": target_db_id},
        "storage_layer": service.storage_layer(),
        "chunks": [],
        "academic_retrieval": academic,
        "graph": graph,
    }

    # 7. Generate grounding and evidence_text
    payload["grounding"] = service._grounding_status(
        [],
        graph,
        academic,
        query_text=query_text,
    )
    payload["evidence_text"] = service._compact_evidence_text(
        [],
        graph,
        academic=academic,
        grounding=payload["grounding"],
        mode="subgraph",
    )

    # 8. Return formatted tool response
    return _academic_tool_response(
        payload=payload,
        query_text=query_text,
        kb_name=kb_name,
        retrieval_mode="subgraph",
        tool_call_id=tool_call_id,
    )


# 1. Search Lecturer Publications
class SearchLecturerPublicationsInput(BaseModel):
    author_name: str = Field(
        description="The name of the lecturer/author to search publications for (e.g. 'Nurhayati' or 'Farid Baskoro')."
    )
    kb_name: str = Field(
        default="yunesa_academic_kg",
        description="Knowledge base name (default: yunesa_academic_kg)."
    )
    limit: int = Field(
        default=60,
        description="The maximum number of publication records to return."
    )


@tool(
    category="buildin",
    tags=["graph"],
    display_name="Search Lecturer Publications",
    args_schema=SearchLecturerPublicationsInput,
)
async def search_lecturer_publications(
    author_name: str,
    kb_name: str = "yunesa_academic_kg",
    limit: int = 60,
    runtime: ToolRuntime = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Any:
    """Retrieve publications or papers written by a specific lecturer or author from the academic knowledge graph."""
    logger.info(f"Tool search_lecturer_publications called with author_name: {author_name}")
    service = AcademicGraphRAGService()
    return await _run_specialized_academic_retrieval(
        kb_name=kb_name,
        query_text=author_name,
        retrieval_key="author_publications",
        query_func=service.query_author_publications,
        runtime=runtime,
        tool_call_id=tool_call_id,
        limit=limit,
    )


# 2. Search Lecturers by Topic
class SearchLecturersByTopicInput(BaseModel):
    topic: str = Field(
        description="The research topic or keyword to search for (e.g. 'machine learning', 'data mining', 'IoT')."
    )
    department: str | None = Field(
        default=None,
        description="Optional department or study program name filter (e.g. 'Infokom', 'Teknik Informatika')."
    )
    kb_name: str = Field(
        default="yunesa_academic_kg",
        description="Knowledge base name (default: yunesa_academic_kg)."
    )
    limit: int = Field(
        default=40,
        description="The maximum number of publication/lecturer records to return."
    )


@tool(
    category="buildin",
    tags=["graph"],
    display_name="Search Lecturers by Topic",
    args_schema=SearchLecturersByTopicInput,
)
async def search_lecturers_by_topic(
    topic: str,
    department: str | None = None,
    kb_name: str = "yunesa_academic_kg",
    limit: int = 40,
    runtime: ToolRuntime = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Any:
    """Find lecturers who have published research on a specific topic, optionally filtered by department."""
    combined_query = f"{topic} {department or ''}".strip()
    logger.info(f"Tool search_lecturers_by_topic called with combined query: {combined_query}")
    service = AcademicGraphRAGService()
    return await _run_specialized_academic_retrieval(
        kb_name=kb_name,
        query_text=combined_query,
        retrieval_key="lecturer_topic_publications",
        query_func=service.query_lecturer_topic_publications,
        runtime=runtime,
        tool_call_id=tool_call_id,
        limit=limit,
    )


# 3. Search Topic Statistics
class SearchTopicStatisticsInput(BaseModel):
    kb_name: str = Field(
        default="yunesa_academic_kg",
        description="Knowledge base name (default: yunesa_academic_kg)."
    )
    limit: int = Field(
        default=15,
        description="The maximum number of topic frequency records to return."
    )


@tool(
    category="buildin",
    tags=["graph"],
    display_name="Search Topic Statistics",
    args_schema=SearchTopicStatisticsInput,
)
async def search_topic_statistics(
    kb_name: str = "yunesa_academic_kg",
    limit: int = 15,
    runtime: ToolRuntime = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Any:
    """Retrieve statistical metadata on the most frequently studied research topics and concepts."""
    logger.info("Tool search_topic_statistics called")
    service = AcademicGraphRAGService()
    return await _run_specialized_academic_retrieval(
        kb_name=kb_name,
        query_text="topic statistics",
        retrieval_key="topic_frequencies",
        query_func=service.query_topic_frequencies,
        runtime=runtime,
        tool_call_id=tool_call_id,
        limit=limit,
    )


# 4. Search Collaboration Network
class SearchCollaborationNetworkInput(BaseModel):
    lecturer_name: str = Field(
        description="The name of the lecturer to search co-authors and collaborations for (e.g. 'Farid Baskoro')."
    )
    kb_name: str = Field(
        default="yunesa_academic_kg",
        description="Knowledge base name (default: yunesa_academic_kg)."
    )
    limit: int = Field(
        default=40,
        description="The maximum number of collaboration records to return."
    )


@tool(
    category="buildin",
    tags=["graph"],
    display_name="Search Collaboration Network",
    args_schema=SearchCollaborationNetworkInput,
)
async def search_collaboration_network(
    lecturer_name: str,
    kb_name: str = "yunesa_academic_kg",
    limit: int = 40,
    runtime: ToolRuntime = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Any:
    """Retrieve the research collaboration network and co-authors of a specific lecturer."""
    logger.info(f"Tool search_collaboration_network called with lecturer_name: {lecturer_name}")
    service = AcademicGraphRAGService()
    return await _run_specialized_academic_retrieval(
        kb_name=kb_name,
        query_text=lecturer_name,
        retrieval_key="collaborations",
        query_func=service.query_collaborations,
        runtime=runtime,
        tool_call_id=tool_call_id,
        limit=limit,
    )


# 5. Search Papers by Topic
class SearchPapersByTopicInput(BaseModel):
    topic: str = Field(
        description="The research topic or keyword to search papers/publications for (e.g. 'vision transformer', 'deep learning')."
    )
    start_year: int | None = Field(
        default=None,
        description="Optional start year to filter papers (inclusive, e.g. 2023)."
    )
    end_year: int | None = Field(
        default=None,
        description="Optional end year to filter papers (inclusive, e.g. 2024)."
    )
    kb_name: str = Field(
        default="yunesa_academic_kg",
        description="Knowledge base name (default: yunesa_academic_kg)."
    )
    limit: int = Field(
        default=40,
        description="The maximum number of publication records to return."
    )


@tool(
    category="buildin",
    tags=["graph"],
    display_name="Search Papers by Topic",
    args_schema=SearchPapersByTopicInput,
)
async def search_papers_by_topic(
    topic: str,
    start_year: int | None = None,
    end_year: int | None = None,
    kb_name: str = "yunesa_academic_kg",
    limit: int = 40,
    runtime: ToolRuntime = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Any:
    """Find research papers or publications matching a specific topic, keyword, or concept, with optional year range filtering."""
    logger.info(f"Tool search_papers_by_topic called with topic: {topic}, years: {start_year}-{end_year}")
    service = AcademicGraphRAGService()
    return await _run_specialized_academic_retrieval(
        kb_name=kb_name,
        query_text=topic,
        retrieval_key="papers_by_topic",
        query_func=service.query_papers_by_topic,
        runtime=runtime,
        tool_call_id=tool_call_id,
        limit=limit,
        additional_kwargs={
            "start_year": start_year,
            "end_year": end_year,
        }
    )

