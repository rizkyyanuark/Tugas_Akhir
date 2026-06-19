"""Airflow task handlers for Academic Knowledge Graph construction."""

from __future__ import annotations

import logging

from knowledge.etl.utils.logging import log_event, result_fields, timed_event

logger = logging.getLogger("etl-worker")


def _kg_load_data(config):
    """Fetch graph-ready source rows from Supabase into shared KG artifacts."""
    from knowledge.etl.services.kg_service import run_kg_data_load

    with timed_event(logger, "kg.load_data", mode=config.mode):
        result = run_kg_data_load(
            mode=config.mode,
            sample_size=config.sample_size,
        )
    log_event(logger, "kg.load_data.result", **result_fields(result))


def _kg_extract_entities(config):
    """Optionally run GLiNER extraction over publication text."""
    from knowledge.etl.services.kg_service import run_kg_entity_extraction

    with timed_event(logger, "kg.extract_entities", mode=config.mode):
        result = run_kg_entity_extraction(
            mode=config.mode,
            sample_size=config.sample_size,
        )
    log_event(logger, "kg.extract_entities.result", **result_fields(result))


def _kg_build_graph(config):
    """Build the NetworkX property graph and export KG artifacts."""
    from knowledge.etl.services.kg_service import run_kg_build

    with timed_event(logger, "kg.build_graph", mode=config.mode):
        result = run_kg_build(
            mode=config.mode,
            sample_size=config.sample_size,
        )
    log_event(logger, "kg.build_graph.result", **result_fields(result))


def _kg_write_stores(config):
    """Write the built graph into Neo4j AuraDB and/or Zilliz/Milvus."""
    from knowledge.etl.services.kg_service import run_kg_write_stores

    with timed_event(logger, "kg.write_stores", mode=config.mode):
        result = run_kg_write_stores(
            mode=config.mode,
            sample_size=config.sample_size,
        )
    log_event(logger, "kg.write_stores.result", **result_fields(result))


KG_TASKS = {
    "kg_load_data": _kg_load_data,
    "kg_extract_entities": _kg_extract_entities,
    "kg_build_graph": _kg_build_graph,
    "kg_write_stores": _kg_write_stores,
}

TASKS = KG_TASKS
