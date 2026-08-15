"""SiliconFlow Cross-Encoder Reranker service for GraphRAG context refinement."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Hardcoded defaults as requested by the user
DEFAULT_RERANKER_MODEL = "Qwen/Qwen3-Reranker-8B"
DEFAULT_RERANKER_TOP_N = 25
DEFAULT_RERANKER_TIMEOUT = 30.0
DEFAULT_RERANK_URL = "https://api.siliconflow.com/v1/rerank"


def build_rerank_text(paper_chunk: dict[str, Any]) -> str:
    """Format a paper chunk into a text blob for the Cross-Encoder Reranker."""
    title = paper_chunk.get("title") or paper_chunk.get("paper_title") or ""
    authors = paper_chunk.get("authors") or ""
    content = paper_chunk.get("content") or ""
    return f"Title: {title}\nAuthors: {authors}\nContent: {content}"


def _call_rerank_api(
    query: str,
    documents: list[str],
    api_key: str,
    model_name: str,
    rerank_url: str,
    timeout: float,
) -> dict[str, Any]:
    """Execute a synchronous POST request to the SiliconFlow Rerank API."""
    response = requests.post(
        rerank_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_name,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


async def rerank_documents(
    query: str,
    papers: list[dict[str, Any]],
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """Rerank paper chunks using Qwen3-Reranker-8B via SiliconFlow API.

    Gracefully falls back to original order (sliced to top_k) on API failures.
    """
    if not papers:
        return []

    # Read credentials & configurations from env (only URL, API key, and model can be custom, rest use default)
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        logger.warning("SILICONFLOW_API_KEY is not configured. Skipping reranker.")
        return papers[:top_k]

    rerank_url = os.getenv("SILICONFLOW_RERANK_URL", DEFAULT_RERANK_URL)
    model_name = os.getenv("SILICONFLOW_RERANKER_MODEL", DEFAULT_RERANKER_MODEL)

    # Slice to top_n candidates (default 25)
    candidates = papers[:DEFAULT_RERANKER_TOP_N]
    doc_texts = [build_rerank_text(p) for p in candidates]

    try:
        # Call the API in a thread pool to avoid blocking the async event loop
        result_data = await asyncio.to_thread(
            _call_rerank_api,
            query,
            doc_texts,
            api_key,
            model_name,
            rerank_url,
            DEFAULT_RERANKER_TIMEOUT,
        )

        results = result_data.get("results") or []
        reranked_papers: list[dict[str, Any]] = []
        for item in results:
            idx = item.get("index")
            if idx is not None and 0 <= idx < len(candidates):
                doc = candidates[idx]
                doc["rerank_score"] = float(item.get("relevance_score", 0.0))
                reranked_papers.append(doc)

        # Return the top_k sorted papers
        return reranked_papers[:top_k]

    except Exception as exc:
        logger.warning(
            f"SiliconFlow Cross-Encoder Reranker failed: {type(exc).__name__}: {exc}. "
            "Falling back to original retrieval order."
        )
        return papers[:top_k]
