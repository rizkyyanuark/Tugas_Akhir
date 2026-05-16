from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

from ..config import RAW_DATA_DIR, SERPAPI_KEY
from ..utils.storage import read_dataframe_csv, write_dataframe_csv

logger = logging.getLogger(__name__)


def _serpapi_fetch_author(
    api_key: str,
    scholar_id: str,
    start: int = 0,
    num: int = 100,
    max_retries: int = 2
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Fetch one page of Google Scholar Author articles via SerpAPI.
    
    Returns:
        A tuple of (articles_list, has_next_page).
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
            # If failing with sort, try without sort as a fallback
            if attempt == max_retries and "sort" in current_params:
                current_params.pop("sort")

            resp = requests.get(
                "https://serpapi.com/search.json",
                params=current_params,
                timeout=30
            )
            
            if resp.status_code == 200:
                data = resp.json()
                articles = data.get("articles", [])
                has_next = "next" in data.get("serpapi_pagination", {})

                if articles or attempt == max_retries:
                    return articles, has_next

                logger.warning(f"SerpAPI returned empty (attempt {attempt + 1}), retrying...")
                time.sleep(3)
            else:
                error_msg = resp.json().get("error", resp.text[:200])
                logger.warning(f"SerpAPI HTTP {resp.status_code}: {error_msg}")
                if attempt < max_retries:
                    time.sleep(3)
                else:
                    return [], False
        except Exception as e:
            logger.error(f"SerpAPI Error: {e}")
            if attempt < max_retries:
                time.sleep(3)
            else:
                return [], False

    return [], False


def extract_scholar_papers(
    targets: List[Dict[str, str]],
    api_key: Optional[str] = None,
    limit_per_author: int = 500,
    resume_from_temp: bool = True,
) -> pd.DataFrame:
    """
    Extract papers from Google Scholar for a list of lecturer targets via SerpAPI.

    Args:
        targets: List of dicts with 'id' (scholar_id) and 'name'.
        api_key: SerpAPI Key. Falls back to config SERPAPI_KEY.
        limit_per_author: Max papers per author profile.
        resume_from_temp: Whether to resume from a temp checkpoint file.

    Returns:
        DataFrame with raw scholar paper data.
    """
    token = api_key or SERPAPI_KEY
    if not token:
        logger.error("SERPAPI_KEY not found in arguments or config.")
        raise ValueError("SERPAPI_KEY not configured!")

    logger.info(f"Extracting Google Scholar papers via SerpAPI for {len(targets)} authors.")

    temp_csv = RAW_DATA_DIR / "scholar_extract_temp.csv"
    scraped_ids: Set[str] = set()
    all_raw: List[Dict[str, Any]] = []

    # Resume support
    if resume_from_temp and temp_csv.exists():
        try:
            df_temp = read_dataframe_csv(temp_csv, dtype=str).fillna("")
            all_raw = df_temp.to_dict("records")
            scraped_ids = set(df_temp["scholar_id"].unique())
            logger.info(f"Resuming from checkpoint: {len(all_raw)} papers for {len(scraped_ids)} authors.")
        except Exception as e:
            logger.warning(f"Failed to load checkpoint from {temp_csv}: {e}")

    for i, target in enumerate(targets):
        scholar_id = target.get("id")
        name = target.get("name", "Unknown")

        if not scholar_id:
            logger.warning(f"Skipping target {name}: No scholar ID provided.")
            continue

        if scholar_id in scraped_ids:
            logger.debug(f"[{i+1}/{len(targets)}] {name} already processed. Skipping.")
            continue

        logger.info(f"[{i+1}/{len(targets)}] Processing {name} ({scholar_id})...")
        start = 0
        author_count = 0

        while author_count < limit_per_author:
            articles, has_next = _serpapi_fetch_author(
                token, scholar_id, start=start, num=100
            )
            
            if not articles:
                break

            for art in articles:
                all_raw.append({
                    "Title": art.get("title", ""),
                    "Year": str(art.get("year", "")),
                    "Journal": art.get("publication", ""),
                    "Link": art.get("link", ""),
                    "Authors": art.get("authors", ""),
                    "Author IDs": scholar_id,
                    "citation_id": art.get("citation_id", ""),
                    "scholar_id": scholar_id,
                    "dosen": name,
                })
                author_count += 1

            if not has_next or len(articles) < 100:
                break
            
            start += 100
            time.sleep(0.3)

        logger.info(f"      Extracted {author_count} papers for {name}.")
        scraped_ids.add(scholar_id)

        # Auto-save checkpoint
        try:
            write_dataframe_csv(pd.DataFrame(all_raw), temp_csv, index=False)
        except Exception as e:
            logger.error(f"Failed to save checkpoint to {temp_csv}: {e}")
            
        time.sleep(1)

    if not all_raw:
        logger.warning("No papers were extracted.")
        return pd.DataFrame()

    df = pd.DataFrame(all_raw)

    # Save final raw output
    output_path = RAW_DATA_DIR / "scholar_papers_raw.csv"
    try:
        write_dataframe_csv(df, output_path, index=False)
        logger.info(f"Extraction complete. Total: {len(df)} papers. Saved to {output_path}")
    except Exception as e:
        logger.error(f"Failed to save final output to {output_path}: {e}")

    # Clean up temp
    if temp_csv.exists():
        temp_csv.unlink(missing_ok=True)

    return df
