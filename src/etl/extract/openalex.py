"""
Extract: OpenAlex API
=====================
Fetches paper metadata from the free OpenAlex API.
"""
import time
import requests
from difflib import SequenceMatcher


def _normalize(text: str) -> str:
    if not text:
        return ""
    return str(text).lower().strip().replace(' ', '')


def extract_openalex_metadata(doi: str | None = None, title: str | None = None) -> dict | None:
    """
    Look up a paper in OpenAlex by DOI or title.

    Returns dict with keys: keywords, author_names, doc_type,
                            publication_year, doi, abstract,
                            oa_pdf_url, oa_landing_url, host_venue
    Returns None if not found.
    """
    headers = {"User-Agent": "mailto:rizky.yanuar@unesa.ac.id"}
    base = "https://api.openalex.org/works"

    work = None

    # Strategy 1: DOI lookup
    if doi:
        try:
            url = f"{base}/doi:{doi}"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                work = resp.json()
        except Exception as e:
            print(f"      ⚠️ [OpenAlex] DOI error: {e}")
        time.sleep(0.3)

    # Strategy 2: Title search
    if not work and title:
        try:
            resp = requests.get(
                base,
                params={"search": title[:200], "per_page": 3},
                headers=headers, timeout=15
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                for r in results:
                    r_title = r.get("title", "")
                    sim = SequenceMatcher(
                        None, _normalize(title), _normalize(r_title)
                    ).ratio()
                    if sim >= 0.85:
                        work = r
                        break

                if not work and results:
                    best = results[0]
                    sim = SequenceMatcher(
                        None, _normalize(title), _normalize(best.get("title", ""))
                    ).ratio()
                    print(f"      ⚠️ [OpenAlex] Best match sim={sim:.2f}. Skip.")
        except Exception as e:
            print(f"      ⚠️ [OpenAlex] Title error: {e}")

    if not work:
        return None

    # Parse result
    result = {}

    # Keywords (from concepts)
    concepts = work.get("concepts", [])
    if concepts:
        kw_list = [c["display_name"] for c in concepts if c.get("score", 0) > 0.3]
        result["keywords"] = ", ".join(kw_list) if kw_list else ""

    # Author names
    authorships = work.get("authorships", [])
    result["author_names"] = [
        a.get("author", {}).get("display_name", "")
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
