from __future__ import annotations

import logging
import re
import time
from difflib import SequenceMatcher
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _normalize(text: str | None) -> str:
    """Normalizes text for comparison."""
    if not text:
        return ""
    return str(text).lower().strip().replace(" ", "")


class OpenAlexClient:
    """Client for interacting with the OpenAlex API."""

    def __init__(self, email: str = "rizky.yanuar@unesa.ac.id"):
        self.base_url = "https://api.openalex.org/works"
        self.headers = {"User-Agent": f"mailto:{email}"}
        self.timeout = 15

    def get_by_doi(self, doi: str) -> dict[str, Any] | None:
        """Fetch a work by its DOI."""
        if not doi:
            return None
        
        try:
            url = f"{self.base_url}/doi:{doi}"
            resp = requests.get(url, headers=self.headers, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"OpenAlex DOI error for {doi}: {e}")
        
        return None

    def search_by_title(self, title: str) -> dict[str, Any] | None:
        """Search for a work by title and return the best match if it's close enough."""
        if not title:
            return None
            
        try:
            params = {"search": title[:200], "per_page": 3}
            resp = requests.get(
                self.base_url, params=params, headers=self.headers, timeout=self.timeout
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                for r in results:
                    r_title = r.get("title", "")
                    sim = SequenceMatcher(
                        None, _normalize(title), _normalize(r_title)
                    ).ratio()
                    if sim >= 0.85:
                        return r

                if results:
                    best = results[0]
                    sim = SequenceMatcher(
                        None, _normalize(title), _normalize(best.get("title", ""))
                    ).ratio()
                    logger.debug(f"OpenAlex: Best match sim={sim:.2f}. Skip.")
        except Exception as e:
            logger.error(f"OpenAlex title search error for {title}: {e}")
            
        return None

    def parse_work(self, work: dict[str, Any]) -> dict[str, Any]:
        """Parses a raw OpenAlex work object into a standardized format."""
        result = {}

        # Keywords (from concepts)
        concepts = work.get("concepts", [])
        if concepts:
            kw_list = [c["display_name"] for c in concepts if c.get("score", 0) > 0.3]
            result["keywords"] = ", ".join(kw_list) if kw_list else ""

        # Author names + structured IDs
        authorships = work.get("authorships", [])
        result["author_names"] = [
            a.get("author", {}).get("display_name", "")
            for a in authorships if a.get("author")
        ]
        
        # OpenAlex structured author IDs
        result["author_ids_openalex"] = [
            a.get("author", {}).get("id", "")
            for a in authorships if a.get("author", {}).get("id")
        ]
        
        # ORCID
        result["author_orcids"] = [
            (a.get("author", {}).get("orcid") or "")
            for a in authorships if a.get("author")
        ]

        # Document type
        result["doc_type"] = work.get("type_crossref", work.get("type", ""))

        # Other metadata
        result["publication_year"] = work.get("publication_year")
        oa_doi = work.get("doi", "")
        if oa_doi and oa_doi.startswith("https://doi.org/"):
            oa_doi = oa_doi.replace("https://doi.org/", "")
        result["doi"] = oa_doi

        # Abstract (from inverted index)
        inv_abs = work.get("abstract_inverted_index")
        if inv_abs:
            try:
                max_pos = max(pos for positions in inv_abs.values() for pos in positions)
                words = [""] * (max_pos + 1)
                for word, positions in inv_abs.items():
                    for pos in positions:
                        words[pos] = word
                result["abstract"] = " ".join(words)
            except Exception:
                result["abstract"] = ""
        else:
            result["abstract"] = ""

        # Open Access links
        best_oa = work.get("best_oa_location") or {}
        result["oa_pdf_url"] = best_oa.get("pdf_url", "")
        result["oa_landing_url"] = best_oa.get("landing_page_url", "")

        # Host venue
        result["primary_location"] = work.get("primary_location", {})

        return result
