"""
Services: UNESA Papers ETL Domain Logic
=======================================
Pure Python orchestrators decoupled from Airflow context.
This isolates testing and execution, keeping Airflow DAG files lightweight.
"""
import pandas as pd
import os
import logging
from pathlib import Path

from ..config import RAW_DATA_DIR, PROCESSED_DATA_DIR

# Hardcoded fallback until we formally inject this path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

logger = logging.getLogger(__name__)


def run_scholars_extraction(test_mode: bool = False) -> str:
    """Extract raw papers from Google Scholar via SerpAPI."""
    from ..extract.scholar import extract_scholar_papers

    # [LEVEL 3 ARCHITECTURE] Read targets directly from Supabase Database
    # This removes the hard dependency on CSV files passing across decoupled containers.
    from ..load.supabase_loader import SupabaseLoader
    loader = SupabaseLoader()
    
    response = loader.client.table("lecturers").select("nama_dosen, scholar_id", "nama_norm", "scopus_id").execute()
    
    targets = []
    for r in response.data:
        sid = str(r.get("scholar_id", "")).strip().replace('.0', '')
        if sid and sid.lower() not in ("nan", "none", "null"):
            targets.append({"id": sid, "name": r.get("nama_norm", "")})

    if test_mode:
        logger.info("🧪 TEST MODE: Limiting to 1 author.")
        targets = targets[:1]

    df = extract_scholar_papers(
        targets, limit_per_author=5 if test_mode else 100)
    output_path = str(RAW_DATA_DIR / "scholar_papers_raw.csv")
    return output_path


def run_scopus_extraction() -> str:
    """Extract raw papers from Scopus via SciVal/Selenium."""
    from ..extract.scopus import extract_scopus_papers

    # Run the full scraper for all Scopus IDs
    papers = extract_scopus_papers()

    output_path = str(RAW_DATA_DIR / "dosen_papers_scopus_raw.csv")
    return output_path


def run_merge(scholar_path: str, scopus_path: str) -> str:
    """Merge and remove duplicate papers across isolated sources."""
    from ..transform.deduplicator import deduplicate_papers

    df_combined = pd.DataFrame()

    for path, source_name in [(scholar_path, "Scholar"), (scopus_path, "Scopus")]:
        if path and os.path.exists(path):
            try:
                df = pd.read_csv(path, dtype=str).fillna("")
                df_combined = pd.concat([df_combined, df], ignore_index=True)
            except pd.errors.EmptyDataError:
                logger.warning(
                    f"⚠️ Warning: {source_name} file is empty ({path})")
        else:
            logger.warning(
                f"⚠️ Warning: {source_name} path is None or missing.")

    if df_combined.empty:
        logger.warning("⚠️ Both sources are empty. Returning empty output.")
        df_clean = pd.DataFrame()
    else:
        df_clean = deduplicate_papers(df_combined)

    output_path = str(PROCESSED_DATA_DIR / "unesa_papers_deduped.csv")
    df_clean.to_csv(output_path, index=False)
    logger.info(
        f"✅ Saved {len(df_clean)} deduplicated cross-source papers -> {output_path}")
    return output_path


def run_enrichment(merged_csv_path: str, test_mode: bool = False) -> str:
    """Enrich papers with Semantic Scholar + OpenAlex metadata."""
    from ..transform.enricher import enrich_paper_batch

    df = pd.read_csv(merged_csv_path, dtype=str).fillna("")

    if test_mode and len(df) > 5:
        logger.info(
            f"🧪 TEST MODE: Limiting enrichment from {len(df)} to 5 papers.")
        df = df.head(5)
    else:
        logger.info(f"📊 Enriching {len(df)} papers...")

    BATCH_SIZE = 200
    for start in range(0, len(df), BATCH_SIZE):
        df = enrich_paper_batch(df, batch_size=BATCH_SIZE,
                                start_idx=start, allow_paid_proxy=True)

    output_path = str(PROCESSED_DATA_DIR / "unesa_papers_enriched.csv")
    df.to_csv(output_path, index=False)
    logger.info(f"✅ Saved {len(df)} enriched papers -> {output_path}")
    return output_path


def run_transform(enriched_csv_path: str) -> str:
    """Scrub HTML, whitespace, and Unicode artifacts."""
    from ..transform.cleaner import clean_papers_batch

    df = pd.read_csv(enriched_csv_path, dtype=str).fillna("")
    df_clean = clean_papers_batch(df)

    output_path = str(PROCESSED_DATA_DIR / "unesa_papers_cleaned.csv")
    df_clean.to_csv(output_path, index=False)
    logger.info(f"✅ Saved {len(df_clean)} cleaned papers -> {output_path}")
    return output_path


def run_database_commit(cleaned_csv_path: str):
    """UPSERT papers securely to Supabase (PostgreSQL)."""
    from ..load.supabase_loader import SupabaseLoader

    df = pd.read_csv(cleaned_csv_path, dtype=str).fillna("")

    # 1. UPSERT to PostgreSQL (Master Ledger)
    postgres_loader = SupabaseLoader()
    papers_count = postgres_loader.upsert_papers(df)
    links_count = postgres_loader.link_papers_to_lecturers(df)

    logger.info(
        f"✅ [PostgreSQL] Loaded {papers_count} papers and {links_count} links.")

    # 2. Trigger KG Webhook directly from the worker (User Request)
    import requests
    import uuid
    kg_url = os.environ.get("KG_BACKEND_URL", "http://ta-kg-backend:8000")
    batch_id = f"batch_{uuid.uuid4().hex[:8]}"

    payload = {
        "task_name": "unesa_papers_etl",
        "batch_id": batch_id,
        "status": "ETL_SUCCESS"
    }

    try:
        res = requests.post(f"{kg_url}/api/v1/kg/trigger", json=payload, timeout=10)
        res.raise_for_status()
        logger.info(f"✅ KG Backend Construction Triggered! Batch ID: {batch_id}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to trigger KG webhook: {e}")
