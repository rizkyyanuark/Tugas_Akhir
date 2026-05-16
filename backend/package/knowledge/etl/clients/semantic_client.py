from __future__ import annotations

import logging
import re
import time
from difflib import SequenceMatcher
from typing import Any, Dict, Optional

import requests

from ..config import SAVE_DIR

logger = logging.getLogger(__name__)

try:
    from knowledge.etl.transform import cleaner
except ImportError:
    logger.warning("Could not import ETL cleaner. Using fallback cleaning.")
    cleaner = None

# Free API key (or None)
API_KEY = "ZWTWpCL5EUX02DYSdts74tkVSEyToXQ6T5Vyak00"
BASE_URL = "https://api.semanticscholar.org/graph/v1"


def _deep_clean_abstract(text: str | None) -> str:
    """Cleans abstract from common noise prefixes and suffixes."""
    if not text:
        return ""
    
    cleaned = str(text).strip()
    # Remove noise prefixes like "Abstrak ", "Abstract:"
    cleaned = re.sub(r"^\s*(?i:abstract|abstrak)[\s\- :.]+[\s]*", "", cleaned)
    # Remove "Kata Kunci - ..." blocks at the end
    cleaned = re.sub(
        r"(?i)\s*(?:kata\s+kunci|keywords?|key\s+words?|subject\s+terms?|index\s+terms?)[\s:\- \.].*$",
        "",
        cleaned,
        flags=re.DOTALL,
    )
    
    return cleaner.clean_text(cleaned) if cleaner else cleaned.strip()


def _normalize_text(text: str | None) -> str:
    """Normalizes text for comparison by removing non-alphanumeric characters and lowering case."""
    if not text or not isinstance(text, str):
        return ""
    return re.sub(r"[^a-z0-9]", "", text.lower())


class SemanticScholarClient:
    """Client for interacting with the Semantic Scholar API."""

    def __init__(self, api_key: str | None = API_KEY):
        self.base_url = BASE_URL
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.timeout = 15

    def search_paper_id(self, title: str) -> str | None:
        """
        Search for a paper by title and return the first result's paperId if it matches closely.
        """
        if not title or len(str(title)) < 5:
            return None

        url = f"{self.base_url}/paper/search"
        params = {
            "query": title[:200],
            "limit": 3,
            "fields": "paperId,title",
        }

        try:
            response = requests.get(
                url, headers=self.headers, params=params, timeout=self.timeout
            )
            if response.status_code == 200:
                data = response.json().get("data", [])
                for item in data:
                    returned_title = item.get("title", "")
                    if returned_title:
                        similarity = SequenceMatcher(
                            None, _normalize_text(title), _normalize_text(returned_title)
                        ).ratio()
                        if similarity >= 0.85:
                            return item["paperId"]
                
                if data:
                    logger.debug(
                        f"No strict match found in S2. Best: '{data[0].get('title', '')[:50]}...'"
                    )
            elif response.status_code == 429:
                logger.warning("S2 Rate Limit (429). Sleeping 5s...")
                time.sleep(5)
            else:
                logger.error(f"S2 API error {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"S2 Search Error: {e}")
        
        return None

    def get_paper_details(self, paper_id: str) -> dict[str, Any] | None:
        """
        Get details (tldr, abstract, externalIds, url, publicationTypes) for a given paperId.
        """
        if not paper_id:
            return None

        url = f"{self.base_url}/paper/{paper_id}"
        params = {
            "fields": "title,tldr,abstract,externalIds,url,openAccessPdf,publicationTypes,year,venue"
        }

        try:
            response = requests.get(
                url, headers=self.headers, params=params, timeout=self.timeout
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("abstract"):
                    data["abstract"] = _deep_clean_abstract(data["abstract"])
                return data
            elif response.status_code == 429:
                logger.warning("S2 Rate Limit (429). Retrying after 5s...")
                time.sleep(5)
                response = requests.get(
                    url, headers=self.headers, params=params, timeout=self.timeout
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("abstract"):
                        data["abstract"] = _deep_clean_abstract(data["abstract"])
                    return data
        except Exception as e:
            logger.error(f"S2 Details Error for {paper_id}: {e}")
            
        return None


def fetch_s2_details(doi: str | None = None, title: str | None = None) -> dict[str, Any] | None:
    """Convenience function to fetch Semantic Scholar details by DOI or Title."""
    client = SemanticScholarClient()
    paper_id = None

    if doi:
        url = f"{BASE_URL}/paper/DOI:{doi}"
        try:
            resp = requests.get(url, headers=client.headers, params={"fields": "paperId"}, timeout=10)
            if resp.status_code == 200:
                paper_id = resp.json().get("paperId")
        except Exception as e:
            logger.debug(f"S2 DOI lookup failed for {doi}: {e}")

    if not paper_id and title:
        paper_id = client.search_paper_id(title)

    if paper_id:
        return client.get_paper_details(paper_id)

    return None


def fetch_tldr(doi: str | None = None, title: str | None = None) -> str | None:
    """Legacy wrapper specifically for fetching TLDR text."""
    details = fetch_s2_details(doi=doi, title=title)
    if details and details.get("tldr"):
        return details["tldr"].get("text")
    return None


