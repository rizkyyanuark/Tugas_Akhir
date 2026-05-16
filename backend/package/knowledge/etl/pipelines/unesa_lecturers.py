"""UNESA lecturers pipeline task handlers for the ETL worker."""

import logging
from datetime import datetime, timezone

from ..config import ETL_FORCE_EXTRACT, ETL_FRESHNESS_HOURS, ID_COLUMN_TYPES
from ..services.lecturer_paths import (
    FINAL_CSV,
    MERGED_CSV,
    SCRAPE_PDDIKTI_PATH,
    SCRAPE_SIAKADU_PATH,
    SCRAPE_WEB_PATH,
)
from ..utils.storage import path_exists, get_modification_time, read_dataframe_csv

logger = logging.getLogger("etl-worker")

# Backward-compatible task-level names.
RAW_WEB_CSV = SCRAPE_WEB_PATH
PDDIKTI_CSV = SCRAPE_PDDIKTI_PATH
SIAKADU_CSV = SCRAPE_SIAKADU_PATH


def _is_data_fresh(file_path, max_age_hours: int) -> bool:
    """Check if a file was modified within the freshness window."""
    if not path_exists(file_path):
        return False

    mtime = get_modification_time(file_path)
    if not mtime:
        return False

    # Ensure mtime is timezone-aware for comparison
    if mtime.tzinfo is None:
        mtime = mtime.replace(tzinfo=timezone.utc)

    age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
    return age_hours < max_age_hours


def _should_skip_extract(config, label: str, file_path) -> bool:
    """
    Determine if extraction should be skipped based on run mode + freshness.

    Args:
        config:    RunConfig from run_worker.
        label:     Human-readable task label for logging.
        file_path: Path to the OUTPUT file of this step.
                   Freshness is checked against this file.
    """
    # full mode → always run
    if config.is_full:
        logger.info("%s: Mode=full - forcing extraction", label)
        return False

    # sample mode → always run (quick test)
    if config.is_sample:
        return False

    # explicit force flag → always run
    if ETL_FORCE_EXTRACT:
        logger.info("%s: ETL_FORCE_EXTRACT=true - forcing extraction", label)
        return False

    # incremental mode → skip if output file is fresh enough
    if _is_data_fresh(file_path, ETL_FRESHNESS_HOURS):
        mtime = get_modification_time(file_path)
        if mtime.tzinfo is None:
            mtime = mtime.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600

        # Get display name for the file
        fname = file_path.name if hasattr(file_path, 'name') else str(file_path).split("/")[-1]
        logger.info(
            "Skip %s: %s is fresh (%.1fh old, threshold: %sh). "
            "Use --mode full or ETL_FORCE_EXTRACT=true to override.",
            label, fname, age_hours, ETL_FRESHNESS_HOURS
        )
        return True

    return False


# TASK HANDLERS
# Each handler checks data freshness against its own specific output file.

def _lec_extract_web(config):
    """Scrape lecturer data from prodi websites."""
    if _should_skip_extract(config, "lec_extract_web", RAW_WEB_CSV):
        return

    from knowledge.etl.services.unesa_lecturers import scrape_university_websites

    output = scrape_university_websites(prodi_filter=config.prodi_filter)
    logger.info("lec_extract_web complete: %s", output)


def _lec_extract_pddikti(config):
    """Fetch lecturer data from PDDIKTI API."""
    if _should_skip_extract(config, "lec_extract_pddikti", PDDIKTI_CSV):
        return

    from knowledge.etl.services.unesa_lecturers import fetch_pddikti_data

    output = fetch_pddikti_data(prodi_filter=config.prodi_filter)
    logger.info("lec_extract_pddikti complete: %s", output)


def _lec_extract_siakadu(config):
    """Fetch lecturer NIP/NIDN identities from SIAKADU."""
    if _should_skip_extract(config, "lec_extract_siakadu", SIAKADU_CSV):
        return

    from knowledge.etl.services.siakadu_identity import fetch_siakadu_data

    output = fetch_siakadu_data(prodi_filter=config.prodi_filter)
    logger.info("lec_extract_siakadu complete: %s", output)


def _read_checkpoint(file_path, label: str, prodi_filter: str | None = None):
    df = read_dataframe_csv(file_path, dtype=ID_COLUMN_TYPES)
    if prodi_filter and "prodi_code" in df.columns:
        df = df[df["prodi_code"].astype(str) == str(prodi_filter)]
    logger.info("Loaded %s checkpoint from %s (%s records)", label, file_path, len(df))
    return df


def _load_or_extract_web(config):
    from knowledge.etl.services.unesa_lecturers import scrape_university_websites

    if path_exists(RAW_WEB_CSV):
        df = _read_checkpoint(RAW_WEB_CSV, "web", config.prodi_filter)
        if not df.empty:
            return df

    logger.info("Web checkpoint missing or empty. Running web extraction before merge.")
    return scrape_university_websites(prodi_filter=config.prodi_filter)


def _load_or_extract_pddikti(config):
    from knowledge.etl.services.unesa_lecturers import fetch_pddikti_data

    if path_exists(PDDIKTI_CSV):
        df = _read_checkpoint(PDDIKTI_CSV, "PDDIKTI", config.prodi_filter)
        if not df.empty:
            return df

    logger.info("PDDIKTI checkpoint missing or empty. Running PDDIKTI extraction before merge.")
    return fetch_pddikti_data(prodi_filter=config.prodi_filter)


def _lec_merge(config):
    """Merge web + PDDIKTI data into a single dataset."""
    from knowledge.etl.services.unesa_lecturers import run_smart_merge

    df_web = _load_or_extract_web(config)
    df_pddikti = _load_or_extract_pddikti(config)
    
    output = run_smart_merge(df_web, df_pddikti)
    logger.info("lec_merge complete: %s", output)


def _lec_enrich(config):
    """API enrichment (SimCV, Sinta, SciVal, Scholar)."""
    from knowledge.etl.services.unesa_lecturers import run_enrichment

    # In sample mode, limit Scholar API calls to sample_size
    scholar_sample = config.sample_size if config.is_sample else None
    output = run_enrichment(scholar_sample=scholar_sample)
    logger.info("lec_enrich complete: %s", output)


def _lec_transform(config):
    """Final post-processing and cleaning."""
    from knowledge.etl.services.unesa_lecturers import run_post_processing

    output = run_post_processing()
    logger.info("lec_transform complete: %s", output)


def _lec_load(config):
    """UPSERT to Supabase PostgreSQL."""
    from knowledge.etl.services.unesa_lecturers import run_supabase_sync

    synced_count = run_supabase_sync()
    logger.info("lec_load complete: Synced %s records", synced_count)


LECTURERS_TASKS = {
    "lec_extract_web": _lec_extract_web,
    "lec_extract_pddikti": _lec_extract_pddikti,
    "lec_extract_siakadu": _lec_extract_siakadu,
    "lec_merge": _lec_merge,
    "lec_enrich": _lec_enrich,
    "lec_transform": _lec_transform,
    "lec_load": _lec_load,
}

TASKS = LECTURERS_TASKS
