"""
Extract: Google Scholar Papers via SerpAPI
==========================================
Fetches paper metadata from Google Scholar Author profiles.
Designed for Airflow micro-batch execution.
"""
import time
import logging
import requests
import pandas as pd
from pathlib import Path

logger = logging.getLogger(__name__)

from ..config import SERPAPI_KEY, RAW_DATA_DIR


def _serpapi_fetch_author(api_key: str, scholar_id: str, start: int = 0,
                          num: int = 100, max_retries: int = 2):
    """
    Fetch one page of Google Scholar Author articles via SerpAPI.
    Returns (articles_list, has_next_page).
    """
    params = {
        "engine": "google_scholar_author",
        "author_id": scholar_id,
        "api_key": api_key,
        "hl": "en",
        "start": start,
        "num": num,
        "sort": "pubdate",
    }

    for attempt in range(max_retries + 1):
        try:
            current_params = dict(params)
            if attempt == max_retries and "sort" in current_params:
                current_params.pop("sort")

            resp = requests.get(
                "https://serpapi.com/search.json",
                params=current_params, timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                articles = data.get("articles", [])
                has_next = "next" in data.get("serpapi_pagination", {})

                if articles or attempt == max_retries:
                    return articles, has_next

                logger.warning(f"      ⚠️ SerpAPI empty (attempt {attempt+1}), retry 3s...")
                time.sleep(3)
            else:
                error = resp.json().get("error", resp.text[:200])
                logger.warning(f"      ⚠️ SerpAPI HTTP {resp.status_code}: {error}")
                if attempt < max_retries:
                    time.sleep(3)
                else:
                    return [], False
        except Exception as e:
            logger.error(f"      ⚠️ SerpAPI Error: {e}")
            if attempt < max_retries:
                time.sleep(3)
            else:
                return [], False

    return [], False



def extract_scholar_papers(
    targets: list,
    api_key: str = None,
    limit_per_author: int = 500,
    resume_from_temp: bool = True,
) -> pd.DataFrame:
    """
    Extract papers from Google Scholar for a list of lecturer targets.

    Args:
        targets: List of dicts with keys 'id' (scholar_id) and 'name'.
        api_key: SerpAPI Key. Falls back to config SERPAPI_KEY.
        limit_per_author: Max papers per author profile.
        resume_from_temp: Whether to resume from a temp checkpoint file.

    Returns:
        DataFrame with raw scholar paper data.
    """
    from ..config import SERPAPI_KEY
    token = api_key or SERPAPI_KEY
    if not token:
        raise ValueError("❌ SERPAPI_KEY not configured!")

    logger.info(f"\n📡 EXTRACT: Google Scholar via SerpAPI ({len(targets)} authors)")
    logger.info("=" * 60)

    TEMP_CSV = RAW_DATA_DIR / "scholar_extract_temp.csv"

    scraped_ids = set()
    all_raw = []

    # Resume support
    if resume_from_temp and TEMP_CSV.exists():
        try:
            df_temp = pd.read_csv(TEMP_CSV, dtype=str).fillna("")
            all_raw = df_temp.to_dict('records')
            scraped_ids = set(df_temp['scholar_id'].unique())
            logger.info(f"   🔄 [RESUME] {len(all_raw)} papers from checkpoint.")
        except Exception:
            pass

    for i, t in enumerate(targets):
        if t['id'] in scraped_ids:
            logger.info(f"[{i+1}/{len(targets)}] {t['name']}... ⏭️ [Resume]")
            continue

        logger.info(f"[{i+1}/{len(targets)}] {t['name']} ({t['id']})...")
        start = 0
        author_count = 0

        while author_count < limit_per_author:
            articles, has_next = _serpapi_fetch_author(
                token, t["id"], start=start, num=100
            )
            if not articles:
                break

            for art in articles:
                all_raw.append({
                    "Title": art.get('title', ''),
                    "Year": str(art.get("year", "")),
                    "Journal": art.get("publication", ""),
                    "Link": art.get("link", ""),
                    "Authors": art.get("authors", ""),
                    "Author IDs": t["id"],
                    "citation_id": art.get("citation_id", ""),
                    "scholar_id": t["id"],
                    "dosen": t["name"],
                })
                author_count += 1

            if not has_next or len(articles) < 100:
                break
            start += 100
            time.sleep(0.3)

        logger.info(f"      📄 {author_count} papers fetched.")

        # Auto-save checkpoint
        pd.DataFrame(all_raw).to_csv(TEMP_CSV, index=False)
        time.sleep(1)

    if not all_raw:
        logger.warning("   ⚠️ No papers extracted.")
        return pd.DataFrame()

    df = pd.DataFrame(all_raw)

    # Save final raw output
    output_path = RAW_DATA_DIR / "scholar_papers_raw.csv"
    df.to_csv(output_path, index=False)
    logger.info(f"\n   ✅ Extracted {len(df)} papers -> {output_path}")

    # Clean up temp
    if TEMP_CSV.exists():
        TEMP_CSV.unlink(missing_ok=True)

    return df
