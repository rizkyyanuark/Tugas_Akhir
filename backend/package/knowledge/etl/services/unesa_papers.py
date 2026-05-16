import logging
import re
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd

from knowledge.etl.clients.supabase_client import SupabaseClient
from knowledge.etl.config import (
    SCIVAL_EMAIL, 
    SCIVAL_PASS, 
    BRIGHTDATA_SERP_TOKEN
)
from knowledge.etl.services.paper_paths import (
    SCHOLAR_CSV,
    SCHOLAR_TEMP_CSV,
    SCOPUS_CSV,
    SCOPUS_RAW_CSV,
)
from knowledge.etl.utils.storage import (
    path_name,
    read_dataframe_csv,
    smart_exists,
    smart_unlink,
    write_dataframe_csv,
)
from knowledge.etl.transform.enricher import resolve_academic_authors, enrich_paper_batch

logger = logging.getLogger(__name__)


def _get_target_ids(df_lecturers: pd.DataFrame, col_name: str) -> List[str]:
    """Extract clean IDs from lecturer DataFrame."""
    if df_lecturers.empty:
        return []
    ids = df_lecturers[col_name].dropna().unique().tolist()
    return [str(x).strip().replace('.0', '') for x in ids if x and str(x).strip().lower() not in ('nan', 'none', '')]


def _load_lecturers_from_supabase() -> pd.DataFrame:
    """Standardized loader for lecturer data from Supabase."""
    try:
        client = SupabaseClient()
        df = client.get_lecturers_df()
        if df.empty:
            logger.warning("No lecturer data found in Supabase.")
        return df
    except Exception as e:
        logger.error(f"Failed to load lecturers from Supabase. Error: {e}")
        return pd.DataFrame()


# ================================================================
# STEP 1: SCOPUS SCRAPING
# ================================================================
def run_scopus_scraping(df_lecturers: Optional[pd.DataFrame] = None, email: Optional[str] = None, password: Optional[str] = None) -> pd.DataFrame:
    """Scrape papers from Scopus for all lecturers."""
    email = email or SCIVAL_EMAIL
    password = password or SCIVAL_PASS
    from knowledge.etl.clients.scopus_client import ScopusPaperClient

    logger.info("Starting STEP 1: SCOPUS SCRAPING")

    if df_lecturers is None:
        df_lecturers = _load_lecturers_from_supabase()

    target_ids = _get_target_ids(df_lecturers, 'scopus_id')
    logger.info(f"Found {len(target_ids)} Scopus IDs to scrape.")

    if not target_ids:
        logger.warning("No valid Scopus IDs found. Skipping scraping process.")
        return pd.DataFrame()

    client = ScopusPaperClient(email, password)
    papers = client.run_scraper(target_ids)

    df_new = pd.DataFrame(papers) if papers else pd.DataFrame()
    write_dataframe_csv(df_new, SCOPUS_RAW_CSV, index=False)
    logger.info(f"Checkpoint saved: {len(df_new)} papers to {SCOPUS_RAW_CSV}")

    return df_new


# ================================================================
# STEP 2: SCOPUS PROCESSING (Clean + Dedup + TLDR Enrichment)
# ================================================================
def run_scopus_processing(input_raw_path: Optional[Path] = None, output_master_path: Optional[Path] = None) -> pd.DataFrame:
    """Process Scopus data: Clean, Deduplicate, and Enrich."""
    from knowledge.etl.clients.scopus_client import process_scopus_data

    logger.info("Starting STEP 2: SCOPUS PROCESSING")

    raw_path = input_raw_path or SCOPUS_RAW_CSV
    master_path = output_master_path or SCOPUS_CSV

    if not smart_exists(raw_path):
        logger.info(f"Raw data not found at: {raw_path}. Skipping.")
        return pd.DataFrame()
    
    df_raw = read_dataframe_csv(raw_path, dtype=str).fillna("")

    df_master = pd.DataFrame()
    if smart_exists(master_path):
        logger.info(f"Loading Master Database: {master_path}")
        df_master = read_dataframe_csv(master_path, dtype=str).fillna("")
    else:
        logger.info("No Master Database found. Starting fresh.")

    logger.info(f"Merging: New ({len(df_raw)}) + Master ({len(df_master)})")
    df_combined = pd.concat([df_master, df_raw], ignore_index=True)

    if df_combined.empty:
        logger.warning("No paper data available to process.")
        return pd.DataFrame()

    df_processed = process_scopus_data(df_combined)

    write_dataframe_csv(df_processed, master_path, index=False)
    logger.info(f"Saved {len(df_processed)} papers to {master_path}")
    
    smart_unlink(raw_path)
    return df_processed


# ================================================================
# STEP 3: SUPABASE INSERT (Upsert + Link to Lecturers)
# ================================================================
def run_supabase_insert(input_master_path: Optional[Path] = None) -> None:
    """Upsert papers and link them to lecturers in Supabase."""
    logger.info("Starting STEP 3: SUPABASE INSERTION")

    csv_path = input_master_path or SCOPUS_CSV
    if not smart_exists(csv_path):
        logger.error(f"Master data not found at: {csv_path}")
        return

    logger.info(f"Loading Cleaned Papers: {csv_path}")
    df_master = read_dataframe_csv(csv_path, dtype=str)
    logger.info(f"Total Rows to Sync: {len(df_master)}")

    try:
        client = SupabaseClient()
        logger.info("Syncing papers to 'papers' table...")
        client.upsert_papers(df_master)

        logger.info("Linking papers to authors...")
        client.link_papers_to_lecturers(df_master)

        logger.info("Database sync completed successfully.")

    except Exception as e:
        logger.error(f"Database Operation Failed: {e}")


# ================================================================
# STEP 4: GOOGLE SCHOLAR SCRAPING (via SerpAPI)
# ================================================================

def _brightdata_fetch_author(api_token: str, scholar_id: str, start: int = 0, num: int = 100) -> tuple[list, bool]:
    """Fetch author papers via BrightData SERP API."""
    import requests
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse, parse_qs
    from knowledge.etl.config import BRIGHTDATA_SERP_ZONE

    url_submit = "https://api.brightdata.com/serp/req"
    target_url = f"https://scholar.google.com/citations?user={scholar_id}&hl=en&cstart={start}&pagesize={num}"
    
    payload = {"zone": BRIGHTDATA_SERP_ZONE, "url": target_url}
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}

    try:
        response = requests.post(url_submit, json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if "response_id" in data:
                res_id = data["response_id"]
                url_res = f"https://api.brightdata.com/serp/get_result?response_id={res_id}"
                
                for _ in range(10):
                    res = requests.get(url_res, headers=headers, timeout=30)
                    if res.status_code == 200:
                        soup = BeautifulSoup(res.text, "html.parser")
                        rows = soup.find_all("tr", class_="gsc_a_tr")
                        articles = []
                        for row in rows:
                            title_tag = row.find("a", class_="gsc_a_at")
                            href = title_tag['href'] if title_tag and 'href' in title_tag.attrs else ""
                            
                            cid = ""
                            if href:
                                qs = parse_qs(urlparse(href).query)
                                if 'citation_for_view' in qs: cid = qs['citation_for_view'][0]

                            gray = row.find_all("div", class_="gs_gray")
                            year_tag = row.find("span", class_="gsc_a_h gsc_a_hc gs_ibl")
                            
                            articles.append({
                                "title": title_tag.text.strip() if title_tag else "",
                                "year": year_tag.text.strip() if year_tag else "",
                                "publication": gray[1].text.strip() if len(gray) > 1 else "",
                                "link": "https://scholar.google.com" + href if href else "",
                                "authors": gray[0].text.strip() if len(gray) > 0 else "",
                                "citation_id": cid
                            })
                        return articles, len(articles) == num
                    elif res.status_code == 202:
                        time.sleep(5)
                    else:
                        break
    except Exception as e:
        logger.error(f"Scholar Fetch Error: {e}")
    return [], False


def run_scholar_scraping(
    api_token: Optional[str] = None, 
    limit_per_author: int = 500, 
    test_target_id: Optional[str] = None,
    run_mode: str = "incremental", 
    sample_size: Optional[int] = None
) -> Optional[pd.DataFrame]:
    """
    Scrape papers from Google Scholar via Bright Data SERP API.

    3-Phase Architecture:
        Phase 1: Pure Scrape - Fetch all papers from SERP API, no filtering.
        Phase 2: Batch Dedup - Remove duplicates vs Scopus + cross-lecturer.
        Phase 3: Batch Author Match - Match author names to lecturer database.

    Run Modes:
        full        -> Scrape ALL lecturers from scratch.
        incremental -> Skip lecturers already present in scholar CSV.
        sample      -> Process only `sample_size` lecturers.
    """
    api_token = api_token or BRIGHTDATA_SERP_TOKEN
    if not api_token:
        logger.error("BRIGHTDATA_SERP_TOKEN not configured! Please check your environment.")
        return None

    logger.info(f"Starting STEP 4: GOOGLE SCHOLAR SCRAPING [Mode: {run_mode.upper()}]")

    from difflib import SequenceMatcher

    # --- Load Lecturer Data from Supabase ---
    df_lecturers = _load_lecturers_from_supabase()
    if df_lecturers.empty:
        logger.error("No lecturer data available from Supabase. Aborting.")
        return None

    targets = []
    for _, row in df_lecturers.iterrows():
        sid = str(row.get("scholar_id", "")).strip().replace('.0', '')
        if sid and sid.lower() not in ("", "nan", "none"):
            targets.append({"id": sid, "name": row["nama_dosen"]})

    # Incremental logic: Skip already-scraped authors
    already_scraped_ids = set()
    if run_mode == "incremental" and smart_exists(SCHOLAR_CSV):
        try:
            df_existing = read_dataframe_csv(SCHOLAR_CSV, usecols=['scholar_id'])
            already_scraped_ids = set(df_existing['scholar_id'].unique().astype(str))
            logger.info(f"Found {len(already_scraped_ids)} already-scraped author IDs in {path_name(SCHOLAR_CSV)}")
        except Exception as e:
            logger.warning(f"Could not read existing CSV for incremental check: {e}")

    if test_target_id:
        targets = [t for t in targets if t['id'] == test_target_id]
        logger.info(f"TEST MODE: Processing single ID: {test_target_id}")
    elif run_mode == "incremental" and already_scraped_ids:
        total_before = len(targets)
        targets = [t for t in targets if t["id"] not in already_scraped_ids]
        skipped = total_before - len(targets)
        logger.info(f"Incremental mode: Skipping {skipped} authors. {len(targets)} to process.")
        if not targets:
            logger.info("All authors already scraped. Use 'full' mode to re-scrape.")
            return None
    elif run_mode == "sample" and sample_size:
        targets = targets[:sample_size]
        logger.info(f"Sample mode: Processing {len(targets)} authors.")

    # ------------------------------------------------------------------
    # PHASE 1: PURE SCRAPE (No Filter, Auto-Save)
    # ------------------------------------------------------------------
    logger.info("PHASE 1: PURE SCRAPE")
    scraped_ids = set()
    all_raw_papers = []
    if smart_exists(SCHOLAR_TEMP_CSV) and not test_target_id:
        try:
            df_temp = read_dataframe_csv(SCHOLAR_TEMP_CSV, dtype=str).fillna("")
            all_raw_papers = df_temp.to_dict('records')
            scraped_ids = set(df_temp['scholar_id'].unique())
            logger.info(f"Resume: Loaded {len(all_raw_papers)} papers from temp file.")
        except Exception:
            pass

    total_api_calls = 0
    newly_scraped = 0

    for i, target in enumerate(targets):
        if target['id'] in scraped_ids:
            logger.info(f"[{i+1}/{len(targets)}] {target['name']} ({target['id']}) - Already processed.")
            continue

        logger.info(f"[{i+1}/{len(targets)}] Scraping: {target['name']} ({target['id']})")
        start = 0
        author_count = 0

        while author_count < limit_per_author:
            articles, has_next = _brightdata_fetch_author(api_token, target["id"], start=start, num=100)
            total_api_calls += 1

            if not articles:
                break

            for art in articles:
                all_raw_papers.append({
                    "Title": art.get('title', ''),
                    "Year": str(art.get("year", "")),
                    "Journal": art.get("publication", ""),
                    "Link": art.get("link", ""),
                    "Authors_raw": art.get("authors", ""),
                    "citation_id": art.get("citation_id", ""),
                    "scholar_id": target["id"],
                    "lecturer_name": target["name"],
                    "source": "scholar",
                })
                author_count += 1

            if not has_next or len(articles) < 100:
                break 
            start += 100
            time.sleep(0.3)

        logger.info(f"Fetched {author_count} papers.")
        newly_scraped += 1

        if not test_target_id and newly_scraped % 5 == 0:
            write_dataframe_csv(pd.DataFrame(all_raw_papers), SCHOLAR_TEMP_CSV, index=False)
            logger.info(f"Auto-save checkpoint: {len(all_raw_papers)} papers saved to temporary file.")

        time.sleep(0.5)

    if not all_raw_papers:
        logger.warning("No papers found for the selected targets.")
        return None

    df_raw = pd.DataFrame(all_raw_papers)

    # ------------------------------------------------------------------
    # PHASE 2: BATCH DEDUP
    # ------------------------------------------------------------------
    logger.info("PHASE 2: BATCH DEDUPLICATION")

    def _normalize_title(text):
        if pd.isna(text): return ""
        return re.sub(r'[^a-z0-9]', '', str(text).lower())

    # Load Scopus for cross-source dedup
    scopus_titles = set()
    if smart_exists(SCOPUS_CSV):
        try:
            df_scopus = read_dataframe_csv(SCOPUS_CSV)
            scopus_titles = set(df_scopus['Title'].apply(_normalize_title))
            logger.info(f"Loaded {len(scopus_titles)} Scopus titles for deduplication.")
        except Exception:
            pass

    df_raw['_norm_title'] = df_raw['Title'].apply(_normalize_title)
    
    # Remove Scopus duplicates
    before = len(df_raw)
    df_raw = df_raw[~df_raw['_norm_title'].isin(scopus_titles)]
    logger.info(f"Removed {before - len(df_raw)} papers already present in Scopus.")

    # Remove cross-lecturer duplicates
    before = len(df_raw)
    df_raw = df_raw.drop_duplicates(subset='_norm_title', keep='first')
    logger.info(f"Removed {before - len(df_raw)} duplicate papers across lecturers.")

    # ------------------------------------------------------------------
    # PHASE 3: AUTHOR RESOLUTION
    # ------------------------------------------------------------------
    logger.info("PHASE 3: AUTHOR RESOLUTION & MATCHING")
    
    authors_resolved = []
    ids_resolved = []
    
    for idx, row in df_raw.iterrows():
        raw_authors = str(row.get("Authors_raw", ""))
        paper_sid = str(row.get("scholar_id", ""))
        
        # Use centralized logic from enricher
        final_names, final_ids = resolve_academic_authors(
            authors_str=raw_authors,
            paper_scholar_id=paper_sid
        )
        authors_resolved.append(final_names)
        ids_resolved.append(final_ids)

    df_raw['Authors'] = authors_resolved
    df_raw['Author IDs'] = ids_resolved
    
    # Cleanup and schema finalization
    df_final = df_raw.drop(columns=['_norm_title'])
    cols_to_add = ["Abstract", "Keywords", "Document Type", "DOI", "TLDR"]
    for col in cols_to_add:
        if col not in df_final.columns:
            df_final[col] = ""

    # Reorder columns
    ordered_cols = [
        "Authors", "Author IDs", "Title", "Year", "Journal", "Link",
        "Abstract", "Keywords", "Document Type", "DOI", "TLDR",
        "citation_id", "scholar_id", "lecturer_name", "source"
    ]
    df_final = df_final[[c for c in ordered_cols if c in df_final.columns]]

    # ------------------------------------------------------------------
    # SAVE & OUTPUT
    # ------------------------------------------------------------------
    if test_target_id:
        logger.info("Test Mode: Results not saved to main CSV.")
        return df_final

    if run_mode == "incremental" and smart_exists(SCHOLAR_CSV):
        try:
            df_existing = read_dataframe_csv(SCHOLAR_CSV)
            df_combined = pd.concat([df_existing, df_final], ignore_index=True)
            df_combined = df_combined.drop_duplicates(subset='Title', keep='first') # Basic dedup on merge
            write_dataframe_csv(df_combined, SCHOLAR_CSV, index=False)
            logger.info(f"Incremental update: {len(df_combined)} total papers saved.")
        except Exception as e:
            logger.error(f"Failed to merge with existing CSV: {e}")
            write_dataframe_csv(df_final, SCHOLAR_CSV, index=False)
    else:
        write_dataframe_csv(df_final, SCHOLAR_CSV, index=False)
        logger.info(f"Saved {len(df_final)} papers to {SCHOLAR_CSV}")

    smart_unlink(SCHOLAR_TEMP_CSV)
    return df_final




# ================================================================
# STEP 5: SCHOLAR ENRICHMENT (Keywords, Abstract, DOI, TLDR)
# ================================================================

def run_scholar_enrichment(
    input_csv: Optional[Path] = None, 
    output_csv: Optional[Path] = None, 
    test_limit: Optional[int] = None
) -> pd.DataFrame:
    """
    Enrich papers with Keywords, Abstract, DOI, TLDR, and Author IDs.
    Uses the centralized enrich_paper_batch service for multi-source enrichment.
    
    Args:
        input_csv: Path to input CSV (default: SCHOLAR_CSV)
        output_csv: Path to output CSV (default: SCHOLAR_CSV)
        test_limit: Max number of papers to enrich in this run.
    """
    logger.info("Starting STEP 5: SCHOLAR ENRICHMENT")
    
    input_file = input_csv or SCHOLAR_CSV
    output_file = output_csv or SCHOLAR_CSV

    if not smart_exists(input_file):
        logger.error(f"Input file not found: {input_file}. Run Scholar Scraping first.")
        return pd.DataFrame()

    try:
        df = read_dataframe_csv(input_file, dtype=str).fillna("")
    except Exception as e:
        logger.error(f"Failed to read input file {input_file}: {e}")
        return pd.DataFrame()

    # Migration: Handle legacy 'Scraped_By_Pipeline' flag
    if 'Scraped_By_Pipeline' in df.columns and 'enriched' not in df.columns:
        df = df.rename(columns={'Scraped_By_Pipeline': 'enriched'})
        logger.info("Migrated legacy 'Scraped_By_Pipeline' column to 'enriched'")

    total_papers = len(df)
    already_enriched = len(df[df.get("enriched", "").astype(str).lower() == "true"])
    remaining = total_papers - already_enriched

    logger.info(f"Pipeline Status: {already_enriched}/{total_papers} enriched, {remaining} remaining.")
    
    if remaining == 0:
        logger.info("All papers already enriched. Skipping.")
        return df

    # We process in batches of 50 for resilience and checkpointing
    # If test_limit is provided, we respect it.
    target_process_count = test_limit if test_limit else remaining
    processed_so_far = 0
    
    logger.info(f"Targeting {target_process_count} papers for enrichment.")

    while processed_so_far < target_process_count:
        batch_size = min(50, target_process_count - processed_so_far)
        
        # enrich_paper_batch handles internal skipping of already enriched rows
        # based on the 'enriched' column.
        df = enrich_paper_batch(df, batch_size=batch_size, allow_paid_proxy=True)
        
        # Incremental save
        try:
            write_dataframe_csv(df, output_file, index=False)
            logger.info(f"Checkpoint saved to {path_name(output_file)}")
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")

        # Check how many were actually added/updated in this loop
        current_enriched = len(df[df.get("enriched", "").astype(str).lower() == "true"])
        newly_done = current_enriched - already_enriched
        
        if newly_done >= target_process_count:
            break
            
        processed_so_far = newly_done
        
        # Stop if no more papers can be enriched (remaining count doesn't move)
        if remaining == (total_papers - current_enriched):
            logger.warning("No progress made in last batch. Potential API limits or no matches found.")
            break
        remaining = total_papers - current_enriched
        if remaining <= 0:
            break

    logger.info(f"ENRICHMENT COMPLETED: {len(df[df.get('enriched', '').astype(str).lower() == 'true'])}/{total_papers} total enriched.")

    return df



