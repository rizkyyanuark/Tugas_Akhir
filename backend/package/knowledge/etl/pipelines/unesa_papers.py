"""UNESA papers pipeline task handlers for the ETL worker."""

import logging
import os

logger = logging.getLogger("etl-worker")


def _paper_extract_scopus(test_mode: bool):
    """Extract raw papers from Scopus via SciVal/Selenium."""
    from knowledge.etl.services.unesa_papers import run_scopus_scraping

    result = run_scopus_scraping()
    logger.info("paper_extract_scopus complete -> %s", result)


def _paper_extract_scholar(test_mode: bool):
    """Extract raw papers from Google Scholar via SerpAPI."""
    from knowledge.etl.services.unesa_papers import run_scholar_scraping

    result = run_scholar_scraping(test_target_id="test" if test_mode else None)
    logger.info("paper_extract_scholar complete -> %s", result)


def _paper_transform(test_mode: bool):
    """Full post-extraction pipeline: Merge → Enrich → Clean."""
    from knowledge.etl.services.unesa_papers import run_scopus_processing, run_scholar_enrichment

    # Step 1: Scopus Processing (Clean + Dedup)
    run_scopus_processing()
    logger.info("Scopus Processing complete")

    # Step 2: Scholar Enrichment (Keywords, TLDR, etc)
    run_scholar_enrichment(test_limit=5 if test_mode else None)
    logger.info("Scholar Enrichment complete")


def _paper_load(test_mode: bool):
    """UPSERT cleaned papers to Supabase PostgreSQL."""
    from knowledge.etl.services.unesa_papers import run_supabase_insert

    run_supabase_insert()
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
