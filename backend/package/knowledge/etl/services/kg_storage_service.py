"""Independent graph and vector storage stages for KG construction.

Neo4j and Milvus have different failure modes. Keeping them in separate worker
tasks prevents a transient embedding-provider failure from clearing and
rewriting an already-valid graph database.
"""

from __future__ import annotations

import logging
from typing import Any

from networkx.readwrite import json_graph

from knowledge.etl.services import kg_paths
from knowledge.etl.services import kg_service as core
from knowledge.etl.utils.storage import path_exists, read_json_artifact, write_json_artifact


logger = logging.getLogger(__name__)


def _load_quality_checked_graph(*, mode: str, sample_size: int, stage: str) -> tuple[Any, Any, str]:
    kg = core._kg_module()
    mode = core._normal_mode(mode)
    graph_name = core._effective_graph_name(mode)

    if not path_exists(kg_paths.KG_GRAPH_JSON):
        core.run_kg_build(mode=mode, sample_size=sample_size)

    enforce_gates = core._env_bool("YUNESA_ENFORCE_QUALITY_GATES", mode != "sample")
    if enforce_gates and path_exists(kg_paths.KG_SUMMARY_JSON):
        build_summary = read_json_artifact(kg_paths.KG_SUMMARY_JSON)
        gates = (build_summary.get("quality") or {}).get("quality_gates") or {}
        failed_gates = [name for name, passed in gates.items() if not passed]
        if failed_gates:
            logger.error("kg.%s.quality_gate_blocked | failed_gates=%s", stage, failed_gates)
            raise ValueError(
                f"Quality gate check failed before {stage}: {', '.join(failed_gates)}"
            )
        logger.info("kg.%s.quality_gates_passed | gates=%s", stage, list(gates))

    graph_payload = read_json_artifact(kg_paths.KG_GRAPH_JSON)
    graph = json_graph.node_link_graph(graph_payload, directed=True, multigraph=True)
    logger.info(
        "kg.%s.artifact_loaded | graph_name=%s | nodes=%s | edges=%s | artifact=%s",
        stage,
        graph_name,
        graph.number_of_nodes(),
        graph.number_of_edges(),
        kg_paths.KG_GRAPH_JSON,
    )
    return kg, graph, graph_name


def _update_storage_summary(*, mode: str, graph_name: str, section: str, payload: Any) -> None:
    summary: dict[str, Any] = {}
    if path_exists(kg_paths.KG_SUMMARY_JSON):
        summary = read_json_artifact(kg_paths.KG_SUMMARY_JSON)
    storage = summary.setdefault(
        "storage",
        {"mode": mode, "graph_name": graph_name, "neo4j": None, "milvus": None},
    )
    storage["mode"] = mode
    storage["graph_name"] = graph_name
    storage[section] = payload
    write_json_artifact(summary, kg_paths.KG_SUMMARY_JSON)


def run_kg_write_neo4j(*, mode: str = "incremental", sample_size: int = 50) -> dict[str, Any]:
    """Write only AuraDB/Neo4j and persist an auditable stage status."""
    mode = core._normal_mode(mode)
    kg, graph, graph_name = _load_quality_checked_graph(
        mode=mode,
        sample_size=sample_size,
        stage="write_neo4j",
    )
    enabled = core._env_bool("YUNESA_KG_WRITE_NEO4J", mode != "sample")
    clear_existing = core._env_bool("YUNESA_KG_CLEAR_NEO4J", mode == "full")
    report: dict[str, Any] = {
        "enabled": enabled,
        "clear_existing": clear_existing,
        "status": "skipped" if not enabled else "running",
    }
    _update_storage_summary(mode=mode, graph_name=graph_name, section="neo4j", payload=report)

    if not enabled:
        logger.info("kg.write_neo4j.skipped | graph_name=%s | reason=disabled", graph_name)
        return report

    logger.info(
        "kg.write_neo4j.plan | graph_name=%s | nodes=%s | edges=%s | clear_existing=%s",
        graph_name,
        graph.number_of_nodes(),
        graph.number_of_edges(),
        clear_existing,
    )
    try:
        result = kg.write_graph_to_neo4j(
            graph,
            graph_name=graph_name,
            clear_existing=clear_existing,
        )
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        _update_storage_summary(mode=mode, graph_name=graph_name, section="neo4j", payload=report)
        raise

    report.update(status="success", result=result)
    _update_storage_summary(mode=mode, graph_name=graph_name, section="neo4j", payload=report)
    logger.info(
        "kg.write_neo4j.done | graph_name=%s | nodes_written=%s | edges_written=%s",
        graph_name,
        result.get("nodes_written", 0),
        result.get("edges_written", 0),
    )
    return report


def run_kg_write_milvus(*, mode: str = "incremental", sample_size: int = 50) -> dict[str, Any]:
    """Write only Zilliz/Milvus with provider retry and embedding cache support."""
    mode = core._normal_mode(mode)
    kg, graph, graph_name = _load_quality_checked_graph(
        mode=mode,
        sample_size=sample_size,
        stage="write_milvus",
    )
    enabled = core._env_bool("YUNESA_KG_WRITE_MILVUS", mode != "sample")
    clear_existing = core._env_bool("YUNESA_KG_CLEAR_MILVUS", mode == "full")
    report: dict[str, Any] = {
        "enabled": enabled,
        "clear_existing": clear_existing,
        "status": "skipped" if not enabled else "running",
    }
    _update_storage_summary(mode=mode, graph_name=graph_name, section="milvus", payload=report)

    if not enabled:
        logger.info("kg.write_milvus.skipped | graph_name=%s | reason=disabled", graph_name)
        return report

    logger.info(
        "kg.write_milvus.plan | graph_name=%s | nodes=%s | edges=%s | clear_existing=%s",
        graph_name,
        graph.number_of_nodes(),
        graph.number_of_edges(),
        clear_existing,
    )
    try:
        result = kg.write_vector_index_to_milvus(
            graph,
            graph_name=graph_name,
            clear_existing=clear_existing,
        )
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        _update_storage_summary(mode=mode, graph_name=graph_name, section="milvus", payload=report)
        raise

    report.update(status="success", result=result)
    _update_storage_summary(mode=mode, graph_name=graph_name, section="milvus", payload=report)
    collections = result.get("collections", {})
    logger.info(
        "kg.write_milvus.done | graph_name=%s | collections=%s | inserted_rows=%s",
        graph_name,
        len(collections),
        sum(item.get("inserted_rows", 0) for item in collections.values()),
    )
    return report


def run_kg_write_stores(*, mode: str = "incremental", sample_size: int = 50) -> dict[str, Any]:
    """Compatibility entrypoint; production Airflow uses the split stages."""
    neo4j = run_kg_write_neo4j(mode=mode, sample_size=sample_size)
    milvus = run_kg_write_milvus(mode=mode, sample_size=sample_size)
    report = {
        "mode": core._normal_mode(mode),
        "graph_name": core._effective_graph_name(core._normal_mode(mode)),
        "neo4j": neo4j,
        "milvus": milvus,
    }
    logger.info(
        "kg.write_stores.done | mode=%s | graph_name=%s | neo4j_status=%s | milvus_status=%s",
        report["mode"],
        report["graph_name"],
        neo4j.get("status"),
        milvus.get("status"),
    )
    return report
