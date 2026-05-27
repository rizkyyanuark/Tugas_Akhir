from __future__ import annotations

import logging
from typing import Any

from ..clients.openalex_client import OpenAlexClient

logger = logging.getLogger(__name__)


def extract_openalex_metadata(doi: str | None = None, title: str | None = None) -> dict[str, Any] | None:
    """
    Look up a paper in OpenAlex by DOI or title and return standardized metadata.
    """
    client = OpenAlexClient()
    work = None

    # Strategy 1: DOI lookup
    if doi:
        logger.info(f"Looking up OpenAlex metadata for DOI: {doi}")
        work = client.get_by_doi(doi)

    # Strategy 2: Title search
    if not work and title:
        logger.info(f"Searching OpenAlex for title: {title[:50]}...")
        work = client.search_by_title(title)

    if not work:
        logger.debug(f"OpenAlex: No match found for DOI={doi}, title={title[:30] if title else None}")
        return None

    return client.parse_work(work)

