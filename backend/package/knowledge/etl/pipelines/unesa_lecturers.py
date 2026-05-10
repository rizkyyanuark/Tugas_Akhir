"""UNESA lecturers pipeline task handlers for the ETL worker."""

import logging

logger = logging.getLogger("etl-worker")


def _lec_extract_web(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_web_step

    output = run_web_step()
    logger.info("lec_extract_web complete -> %s", output)


def _lec_extract_pddikti(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_pddikti_step

    output = run_pddikti_step()
    logger.info("lec_extract_pddikti complete -> %s", output)


def _lec_merge(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_smart_merge

    output = run_smart_merge()
    logger.info("lec_merge complete -> %s", output)


def _lec_enrich(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_enrichment

    output = run_enrichment(scholar_sample=5 if test_mode else None)
    logger.info("lec_enrich complete -> %s", output)


def _lec_transform(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_post_processing

    output = run_post_processing()
    logger.info("lec_transform complete -> %s", output)


def _lec_load(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_supabase_sync

    synced_count = run_supabase_sync()
    logger.info("lec_load complete -> Synced %s records", synced_count)


LECTURERS_TASKS = {
    "lec_extract_web": _lec_extract_web,
    "lec_extract_pddikti": _lec_extract_pddikti,
    "lec_merge": _lec_merge,
    "lec_enrich": _lec_enrich,
    "lec_transform": _lec_transform,
    "lec_load": _lec_load,
}

TASKS = LECTURERS_TASKS
