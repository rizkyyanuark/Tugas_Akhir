"""
Keyword Extractor: Clue-Guided Keyword Extraction
===================================================
Implements Step ① of AcademicRAG (Chen, 2025):
  Query → ContentKeyword VDB → clues → LLM → (high_level, low_level) keywords
"""

import logging
from typing import Dict, List, Tuple

from .llm_adapter import LLMAdapter
from .storage.milvus_adapter import MilvusVectorStorage
from .prompts import KEYWORDS_EXTRACTION_CLUES
from .config import KEYWORD_TOP_K

logger = logging.getLogger(__name__)


async def extract_keywords_with_clues(
    query: str,
    milvus_storage: MilvusVectorStorage,
    llm: LLMAdapter,
    top_k: int = KEYWORD_TOP_K,
) -> Tuple[List[str], List[str]]:
    """Clue-guided keyword extraction (Eq. 3.1-3.2 Proposal).

    1. Query → ContentKeyword VDB → top-k keyword clues
    2. Clues + Query → LLM → structured (high_level, low_level) keywords

    Args:
        query: User query string.
        milvus_storage: Milvus vector storage adapter.
        llm: LLM adapter instance.
        top_k: Number of keyword clues to retrieve.

    Returns:
        Tuple of (high_level_keywords, low_level_keywords).
    """
    # Step 1: Get keyword clues from Milvus ContentKeyword collection
    clue_results = milvus_storage.query_keywords(query, top_k=top_k)
    clues_text = "; ".join([r.get("keywords", "") for r in clue_results if r.get("keywords")])

    if not clues_text:
        clues_text = "Tidak ada clues ditemukan."

    logger.info(f"Keyword clues retrieved: {len(clue_results)} results")

    # Step 2: LLM extraction with clues
    prompt = KEYWORDS_EXTRACTION_CLUES.format(
        clues=clues_text,
        query=query,
    )

    result = await llm.extract_json(
        user_prompt=prompt,
        system_prompt="Anda adalah keyword extractor. Output HANYA dalam format JSON.",
    )

    high_level = result.get("high_level", [])
    low_level = result.get("low_level", [])

    # Ensure they are lists of strings
    if not isinstance(high_level, list):
        high_level = [str(high_level)] if high_level else []
    if not isinstance(low_level, list):
        low_level = [str(low_level)] if low_level else []

    logger.info(f"Keywords extracted — HL: {high_level}, LL: {low_level}")
    return high_level, low_level
