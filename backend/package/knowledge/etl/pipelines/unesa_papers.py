"""UNESA papers pipeline task handlers for the ETL worker."""

import logging
import os

logger = logging.getLogger("etl-worker")


def _paper_extract_scopus(test_mode: bool):
    """Extract raw papers from Scopus via SciVal/Selenium."""
    from knowledge.etl.services.unesa_papers import run_scopus_extraction

    result = run_scopus_extraction()
    logger.info("paper_extract_scopus complete -> %s", result)


def _paper_extract_scholar(test_mode: bool):
    """Extract raw papers from Google Scholar via SerpAPI."""
    from knowledge.etl.services.unesa_papers import run_scholars_extraction

    result = run_scholars_extraction(test_mode=test_mode)
    logger.info("paper_extract_scholar complete -> %s", result)


def _paper_transform(test_mode: bool):
    """Full post-extraction pipeline: Merge → Enrich → Clean."""
    from knowledge.etl.services.unesa_papers import run_merge, run_enrichment, run_transform
    from knowledge.etl.config import RAW_DATA_DIR

    # Step 1: Merge (deduplicate across Scopus + Scholar)
    scholar_path = str(RAW_DATA_DIR / "scholar_papers_raw.csv")
    scopus_path = str(RAW_DATA_DIR / "dosen_papers_scopus_raw.csv")
    merged_path = run_merge(scholar_path, scopus_path)
    logger.info("Merge complete -> %s", merged_path)

    # Step 2: Enrich (Semantic Scholar + OpenAlex + TLDR)
    enriched_path = run_enrichment(merged_path, test_mode=test_mode)
    logger.info("Enrich complete -> %s", enriched_path)

    # Step 3: Clean (HTML scrubbing, Unicode normalization)
    cleaned_path = run_transform(enriched_path)
    logger.info("paper_transform complete -> %s", cleaned_path)


def _paper_load(test_mode: bool):
    """UPSERT cleaned papers to Supabase PostgreSQL."""
    from knowledge.etl.services.unesa_papers import run_database_commit
    from knowledge.etl.config import PROCESSED_DATA_DIR

    cleaned_path = str(PROCESSED_DATA_DIR / "unesa_papers_cleaned.csv")
    run_database_commit(cleaned_path)
    logger.info("paper_load complete")


def _paper_notify(test_mode: bool):
    """Send completion notification (log-based for now)."""
    email = os.environ.get("NOTIFICATION_EMAIL", "")
    logger.info("=" * 60)
    logger.info("PAPERS ETL PIPELINE - COMPLETE")
    logger.info("=" * 60)

    if email:
        logger.info("Notification target: %s", email)
    else:
        logger.info("No NOTIFICATION_EMAIL set - skipping email.")

    logger.info("All papers pipeline tasks finished successfully.")


PAPERS_TASKS = {
    "paper_extract_scopus": _paper_extract_scopus,
    "paper_extract_scholar": _paper_extract_scholar,
    "paper_transform": _paper_transform,
    "paper_load": _paper_load,
    "paper_notify": _paper_notify,
}

TASKS = PAPERS_TASKS
