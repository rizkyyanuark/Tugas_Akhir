from __future__ import annotations

import logging
from typing import Any

from ..clients.semantic_client import fetch_s2_details

logger = logging.getLogger(__name__)


def extract_s2_metadata(doi: str | None = None, title: str | None = None) -> dict[str, Any] | None:
    """
    Fetch paper details from Semantic Scholar API.
    Tries DOI first, falls back to title search.
    """
    logger.info(f"Fetching Semantic Scholar metadata for DOI={doi}, Title={title[:50] if title else None}")
    
    data = fetch_s2_details(doi=doi, title=title)
    
    if not data:
        logger.debug("No metadata found in Semantic Scholar.")
        return None
        
    return data

