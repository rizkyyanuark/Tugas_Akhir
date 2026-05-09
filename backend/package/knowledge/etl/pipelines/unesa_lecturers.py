"""UNESA lecturers pipeline task handlers for the ETL worker."""

import logging

logger = logging.getLogger("etl-worker")


def _lec_extract_web(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_extract_web

    output = run_extract_web()
    logger.info("lec_extract_web complete -> %s", output)


def _lec_extract_pddikti(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_extract_pddikti

    output = run_extract_pddikti()
    logger.info("lec_extract_pddikti complete -> %s", output)


def _lec_merge(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_merge

    output = run_merge()
    logger.info("lec_merge complete -> %s", output)


def _lec_enrich(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_enrich

    output = run_enrich(test_mode=test_mode)
    logger.info("lec_enrich complete -> %s", output)


def _lec_transform(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_transform

    output = run_transform()
    logger.info("lec_transform complete -> %s", output)


def _lec_load(test_mode: bool):
    from knowledge.etl.services.unesa_lecturers import run_load

    synced_count = run_load()
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
