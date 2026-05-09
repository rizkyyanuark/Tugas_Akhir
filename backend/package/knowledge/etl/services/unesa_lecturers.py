"""Services: UNESA Lecturers ETL domain logic."""

import logging

logger = logging.getLogger(__name__)


def run_extract_web() -> str:
    """Scrape lecturer data from prodi websites."""
    from knowledge.etl.scraping import pipeline

    return pipeline.run_web_step()


def run_extract_pddikti() -> str:
    """Fetch lecturer data from the PDDIKTI API."""
    from knowledge.etl.scraping import pipeline

    return pipeline.run_pddikti_step()


def run_merge() -> str:
    """Merge web and PDDIKTI data."""
    from knowledge.etl.scraping import pipeline

    return pipeline.run_smart_merge()


def run_enrich(test_mode: bool = False) -> str:
    """Enrich lecturers with external data sources."""
    from knowledge.etl.scraping import pipeline

    sample_limit = 5 if test_mode else None
    return pipeline.run_enrichment(scholar_sample=sample_limit)


def run_transform() -> str:
    """Run final post-processing for lecturer data."""
    from knowledge.etl.scraping import pipeline

    return pipeline.run_post_processing()


def run_load() -> int:
    """Sync lecturer data to Supabase."""
    from knowledge.etl.scraping import pipeline

    return pipeline.run_supabase_sync()
