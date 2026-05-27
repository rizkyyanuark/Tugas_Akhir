"""UNESA papers pipeline task handlers for the ETL worker."""

import logging
from datetime import datetime, timezone

from ..config import ETL_FORCE_EXTRACT, ETL_FRESHNESS_HOURS
from ..utils.logging import log_event, result_fields, timed_event
from ..utils.storage import get_modification_time, path_exists

logger = logging.getLogger("etl-worker")


def _fresh_checkpoint(checkpoints):
    """Return the first checkpoint still inside the extraction freshness window."""
    for checkpoint in checkpoints:
        if not path_exists(checkpoint):
            continue

        modified_at = get_modification_time(checkpoint)
        if not modified_at:
            continue
        if modified_at.tzinfo is None:
            modified_at = modified_at.replace(tzinfo=timezone.utc)

        age_hours = (datetime.now(timezone.utc) - modified_at).total_seconds() / 3600
        if age_hours < ETL_FRESHNESS_HOURS:
            return checkpoint, age_hours

    return None, None


def _should_skip_extract(config, label: str, checkpoints) -> bool:
    """Skip expensive paper extraction when a recent checkpoint is reusable."""
    if config.is_full:
        log_event(logger, "freshness.force", task=label, reason="mode_full")
        return False
    if config.is_sample:
        return False
    if ETL_FORCE_EXTRACT:
        log_event(logger, "freshness.force", task=label, reason="ETL_FORCE_EXTRACT")
        return False

    checkpoint, age_hours = _fresh_checkpoint(checkpoints)
    if checkpoint is None:
        return False

    file_name = checkpoint.name if hasattr(checkpoint, "name") else str(checkpoint).split("/")[-1]
    log_event(
        logger,
        "freshness.skip",
        task=label,
        file=file_name,
        age_hours=f"{age_hours:.1f}",
        threshold_hours=ETL_FRESHNESS_HOURS,
        override="--mode full or ETL_FORCE_EXTRACT=true",
    )
    return True


def _paper_extract_scopus(config):
    """Extract raw papers from Scopus via SciVal/Selenium."""
    from knowledge.etl.services.paper_paths import (
        LEGACY_SCOPUS_CSV,
        LEGACY_SCOPUS_RAW_CSV,
        SCOPUS_CSV,
        SCOPUS_RAW_CSV,
    )
    from knowledge.etl.services.unesa_papers import run_scopus_scraping

    if _should_skip_extract(
        config,
        "paper_extract_scopus",
        (SCOPUS_RAW_CSV, SCOPUS_CSV, LEGACY_SCOPUS_RAW_CSV, LEGACY_SCOPUS_CSV),
    ):
        return

    with timed_event(logger, "paper.extract_scopus", mode=config.mode):
        result = run_scopus_scraping(
            run_mode=config.mode,
            sample_size=config.sample_size if config.is_sample else None,
        )
    log_event(logger, "paper.extract_scopus.result", **result_fields(result))


def _paper_extract_scholar(config):
    """Extract raw papers from one Google Scholar author in sample mode."""
    from knowledge.etl.services.paper_paths import LEGACY_SCHOLAR_CSV, SCHOLAR_CSV
    from knowledge.etl.services.unesa_papers import run_scholar_scraping

    if _should_skip_extract(config, "paper_extract_scholar", (SCHOLAR_CSV, LEGACY_SCHOLAR_CSV)):
        return

    with timed_event(logger, "paper.extract_scholar", mode=config.mode):
        result = run_scholar_scraping(
            run_mode=config.mode,
            sample_size=1 if config.is_sample else None,
            limit_per_author=config.sample_size if config.is_sample else 500,
            paper_limit=config.sample_size if config.is_sample else None,
        )
    log_event(logger, "paper.extract_scholar.result", **result_fields(result))


def _paper_transform(config):
    """Clean, normalize, and merge paper data without external enrichment."""
    from knowledge.etl.services.paper_paths import (
        PAPER_MERGED_CSV,
        PAPER_SAMPLE_TRANSFORMED_CSV,
        SCHOLAR_CSV,
        SCHOLAR_SAMPLE_CSV,
        SCOPUS_CSV,
        SCOPUS_SAMPLE_CSV,
        SCOPUS_SAMPLE_RAW_CSV,
    )
    from knowledge.etl.services.unesa_papers import (
        run_paper_transform,
        run_scopus_processing,
    )

    if config.is_sample:
        with timed_event(logger, "paper.transform.scopus_sample"):
            result = run_scopus_processing(
                input_raw_path=SCOPUS_SAMPLE_RAW_CSV,
                output_master_path=SCOPUS_SAMPLE_CSV,
            )
        log_event(logger, "paper.transform.scopus_sample.result", **result_fields(result))

        with timed_event(logger, "paper.transform.merge_sample", sample_size=config.sample_size):
            result = run_paper_transform(
                source_paths=[(SCOPUS_SAMPLE_CSV, "scopus"), (SCHOLAR_SAMPLE_CSV, "scholar")],
                output_csv=PAPER_SAMPLE_TRANSFORMED_CSV,
                sample_limit=config.sample_size,
            )
        log_event(logger, "paper.transform.merge_sample.result", **result_fields(result))
        return

    with timed_event(logger, "paper.transform.scopus"):
        result = run_scopus_processing()
    log_event(logger, "paper.transform.scopus.result", **result_fields(result))

    with timed_event(logger, "paper.transform.merge"):
        result = run_paper_transform(
            source_paths=[(SCOPUS_CSV, "scopus"), (SCHOLAR_CSV, "scholar")],
            output_csv=PAPER_MERGED_CSV,
        )
    log_event(logger, "paper.transform.merge.result", **result_fields(result))


def _paper_enrich(config):
    """Enrich transformed paper data with external metadata and KG TLDR."""
    from knowledge.etl.services.paper_paths import (
        PAPER_ENRICHED_CSV,
        PAPER_MERGED_CSV,
        PAPER_SAMPLE_MERGED_CSV,
        PAPER_SAMPLE_TRANSFORMED_CSV,
    )
    from knowledge.etl.services.unesa_papers import run_paper_enrichment

    if config.is_sample:
        with timed_event(logger, "paper.enrich", mode=config.mode, sample_size=config.sample_size):
            result = run_paper_enrichment(
                input_csv=PAPER_SAMPLE_TRANSFORMED_CSV,
                output_csv=PAPER_SAMPLE_MERGED_CSV,
                sample_limit=config.sample_size,
                allow_paid_proxy=True,
            )
    else:
        with timed_event(logger, "paper.enrich", mode=config.mode):
            result = run_paper_enrichment(
                input_csv=PAPER_MERGED_CSV,
                output_csv=PAPER_ENRICHED_CSV,
                allow_paid_proxy=True,
            )

    log_event(logger, "paper.enrich.result", **result_fields(result))


def _paper_load(config):
    """UPSERT cleaned papers to Supabase PostgreSQL."""
    from knowledge.etl.services.paper_paths import PAPER_ENRICHED_CSV, PAPER_SAMPLE_MERGED_CSV
    from knowledge.etl.services.unesa_papers import run_supabase_insert

    if config.is_sample:
        with timed_event(logger, "paper.load", mode=config.mode, sample_size=config.sample_size):
            result = run_supabase_insert(
                input_master_path=PAPER_SAMPLE_MERGED_CSV,
                sample_limit=config.sample_size,
            )
    else:
        with timed_event(logger, "paper.load", mode=config.mode):
            result = run_supabase_insert(input_master_path=PAPER_ENRICHED_CSV)

    log_event(logger, "paper.load.result", **result_fields(result))


PAPERS_TASKS = {
    "paper_extract_scopus": _paper_extract_scopus,
    "paper_extract_scholar": _paper_extract_scholar,
    "paper_transform": _paper_transform,
    "paper_enrich": _paper_enrich,
    "paper_load": _paper_load,
}

TASKS = PAPERS_TASKS
