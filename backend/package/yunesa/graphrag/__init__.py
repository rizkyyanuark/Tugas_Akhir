"""GraphRAG retrieval orchestration utilities."""

import asyncio
from typing import Any

from .academic_graphrag import AcademicGraphRAGService
from .base import BaseGraphStorage, BaseKVStorage, BaseVectorStorage
from .query_planner import AcademicKeywordPlan, AcademicQueryParam, AcademicQueryPlanner
from .storage import MilvusVectorStorage, Neo4jGraphStorage
from .heuristics import AcademicHeuristics
from .normalizers import AcademicNormalizers
from .neo4j_queries import AcademicNeo4jQueries
from .evidence import AcademicEvidence


def _run_async(coro):
    """Run an async coroutine synchronously, handling running loop if present."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            try:
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(coro)
            except ImportError:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(lambda: asyncio.run(coro))
                    return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def graphrag_retrieve(
    query: str,
    *,
    mode: str = "hybrid",
    top_k: int = 5,
    graph_name: str = "yunesa_academic_kg",
    param: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Synchronous GraphRAG retrieval delegating to yunesa.graphrag (SSOT)."""
    if param is not None:
        mode = getattr(param, "mode", mode)
        top_k = getattr(param, "top_k", top_k)
        graph_name = getattr(param, "graph_name", graph_name)

    service = AcademicGraphRAGService()

    async def _retrieve():
        return await service.query_academic_indexes(
            query,
            retrieval_mode=mode,
            graph_name=graph_name,
            top_k=top_k,
            **kwargs,
        )

    return _run_async(_retrieve())


def graphrag_answer(
    query: str,
    *,
    mode: str = "hybrid",
    top_k: int = 5,
    graph_name: str = "yunesa_academic_kg",
    model: str = "llama-3.3-70b-versatile",
    retrieval_param: Any = None,
    generation_param: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Synchronous GraphRAG answer generation delegating to yunesa.graphrag (SSOT)."""
    if retrieval_param is not None:
        mode = getattr(retrieval_param, "mode", mode)
        top_k = getattr(retrieval_param, "top_k", top_k)
        graph_name = getattr(retrieval_param, "graph_name", graph_name)
    if generation_param is not None:
        model = getattr(generation_param, "model", model)

    service = AcademicGraphRAGService()

    async def _answer():
        ctx = await service.build_context_package(
            query_text=query,
            chunks=None,
            kb_name="academic_kg",
            retrieval_mode=mode,
            graph_name=graph_name,
        )
        return {
            "query": query,
            "answer": ctx.get("evidence_text", ""),
            "retrieval": ctx.get("academic_retrieval") or ctx,
            "context": ctx.get("evidence_text", ""),
        }

    return _run_async(_answer())


__all__ = [
    "AcademicGraphRAGService",
    "AcademicKeywordPlan",
    "AcademicQueryParam",
    "AcademicQueryPlanner",
    "BaseGraphStorage",
    "BaseKVStorage",
    "BaseVectorStorage",
    "MilvusVectorStorage",
    "Neo4jGraphStorage",
    "AcademicHeuristics",
    "AcademicNormalizers",
    "AcademicNeo4jQueries",
    "AcademicEvidence",
    "graphrag_retrieve",
    "graphrag_answer",
]
