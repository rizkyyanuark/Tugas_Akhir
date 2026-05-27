from __future__ import annotations

import logging
from typing import Any

from ..clients.semantic_client import fetch_s2_details
from ..utils.logging import log_event

logger = logging.getLogger(__name__)


def extract_s2_metadata(doi: str | None = None, title: str | None = None) -> dict[str, Any] | None:
    """
    Fetch paper details from Semantic Scholar API.
    Tries DOI first, falls back to title search.
    """
    log_event(
        logger,
        "s2.lookup.start",
        has_doi=bool(doi),
        title=title[:80] if title else None,
    )
    
    data = fetch_s2_details(doi=doi, title=title)
    
    if not data:
        logger.debug("s2.lookup.no_match | title=%s", title[:80] if title else "")
        return None
        
    return data

