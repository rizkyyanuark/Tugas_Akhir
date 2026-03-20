"""
Extract: Semantic Scholar API
=============================
Fetches paper metadata (Abstract, DOI, TLDR) from Semantic Scholar's free API.
"""
import time
import requests
from difflib import SequenceMatcher


def _normalize(text: str) -> str:
    if not text:
        return ""
    return str(text).lower().strip().replace(' ', '')


def extract_s2_metadata(doi: str = None, title: str = None) -> dict:
    """
    Fetch paper details from Semantic Scholar API.
    Tries DOI first, falls back to title search.

    Returns dict with keys: abstract, tldr, externalIds, venue, year,
                            publicationTypes, openAccessPdf, etc.
    Returns None if not found.
    """
    fields = "title,abstract,tldr,externalIds,venue,year,publicationTypes,openAccessPdf"

    # Strategy 1: DOI lookup (most accurate)
    if doi:
        try:
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
            resp = requests.get(url, params={"fields": fields}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('title'):
                    print(f"      ✅ [S2] DOI match: {data['title'][:50]}...")
                    return data
        except Exception as e:
            print(f"      ⚠️ [S2] DOI lookup error: {e}")
        time.sleep(0.5)

    # Strategy 2: Title search
    if title:
        try:
            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            resp = requests.get(
                url,
                params={"query": title[:200], "limit": 3, "fields": fields},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get('data', [])
                for r in results:
                    r_title = r.get('title', '')
                    sim = SequenceMatcher(
                        None, _normalize(title), _normalize(r_title)
                    ).ratio()
                    if sim >= 0.85:
                        print(f"      ✅ [S2] Title match (sim={sim:.2f})")
                        return r

                if results:
                    best = results[0].get('title', '')
                    print(f"      ⚠️ [S2] No strict match. Best: '{best[:50]}...'")
        except Exception as e:
            print(f"      ⚠️ [S2] Title search error: {e}")

    return None
