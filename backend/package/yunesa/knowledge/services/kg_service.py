"""Service wrappers for production Knowledge Graph construction tasks."""

from __future__ import annotations

import importlib
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from networkx.readwrite import json_graph

from yunesa.knowledge.services import kg_paths
from yunesa.etl.utils.storage import (
    path_exists,
    read_dataframe_artifact,
    read_json_artifact,
    write_dataframe_artifact,
    write_json_artifact,
)

logger = logging.getLogger(__name__)


DEFAULT_GRAPH_NAME = "yunesa_academic_kg"
SAMPLE_GRAPH_NAME = "yunesa_academic_kg_sample"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("kg.config.invalid_int | name=%s | value=%r | default=%s", name, value, default)
        return default


def _normal_mode(mode: str | None) -> str:
    mode = (mode or os.getenv("ETL_RUN_MODE") or "incremental").strip().lower()
    return mode if mode in {"sample", "incremental", "full"} else "incremental"


def _effective_graph_name(mode: str) -> str:
    configured = os.getenv("YUNESA_KG_GRAPH_NAME", "").strip()
    if configured:
        return configured
    return DEFAULT_GRAPH_NAME


def _kg_module() -> Any:
    """Import the canonical KG engine from yunesa.knowledge (preferred)
    with fallback to legacy notebook paths for backward compatibility."""
    import yunesa.knowledge as knowledge_pkg
    return knowledge_pkg

    # Legacy fallback: search filesystem paths
    candidates: list[Path] = []
    configured = os.getenv("YUNESA_KG_SRC_DIR", "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            Path("/app/kg-src"),
            Path.cwd() / "notebooks" / "build-graph" / "src",
            Path(__file__).resolve().parents[5] / "notebooks" / "build-graph" / "src",
        ]
    )
    for candidate in candidates:
        if (candidate / "yunesa_academic_kg.py").exists():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return importlib.import_module("yunesa_academic_kg")
    raise ImportError(
        "Cannot locate academic KG package. Install yunesa.knowledge or set YUNESA_KG_SRC_DIR."
    )


def _resource_path(filename: str, env_name: str) -> Path:
    configured = os.getenv(env_name, "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            Path("/app/package/yunesa/etl/resources") / filename,
            Path.cwd() / "notebooks" / "build-graph" / filename,
            Path.cwd() / "notebooks" / "build-graph" / "config" / filename,
            Path(__file__).resolve().parents[5] / "notebooks" / "build-graph" / filename,
            Path(__file__).resolve().parents[5] / "notebooks" / "build-graph" / "config" / filename,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else Path(filename)


def _concept_aliases_path() -> Path:
    configured = os.getenv("YUNESA_CONCEPT_ALIASES_PATH", "").strip()
    if configured:
        return Path(configured)

    approved = _resource_path("concept_aliases.approved.yml", "YUNESA_APPROVED_CONCEPT_ALIASES_PATH")
    if approved.exists():
        return approved
    return _resource_path("concept_aliases.yml", "YUNESA_BASE_CONCEPT_ALIASES_PATH")


def _archive_artifact(source: Path, history_dir: Path, run_id: str) -> Path | None:
    """Copy an artifact into the history directory with a run-ID suffix."""
    if not isinstance(source, Path) or not source.exists():
        return None
    safe_id = run_id.replace(":", "_").replace("/", "_").replace(" ", "_")[:120]
    dest = history_dir / f"{source.stem}_{safe_id}{source.suffix}"
    history_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    logger.info("kg.archive | %s -> %s", source.name, dest)
    return dest


def _try_generate_llm_suggestions(
    report_path: Path,
    output_path: Path,
    kg: Any,
) -> dict[str, Any] | None:
    """Attempt to generate LLM-assisted alias suggestions, returning None on skip."""
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        logger.info("kg.llm_suggestions.skipped | reason=no_GROQ_API_KEY")
        return None
    if not isinstance(report_path, Path) or not report_path.exists():
        logger.warning("kg.llm_suggestions.skipped | reason=missing_report | path=%s", report_path)
        return None
    try:
        config = kg.LLMAliasSuggestionConfig.from_env()
        result = kg.write_llm_alias_suggestions(report_path, output_path, config=config)
        logger.info(
            "kg.llm_suggestions.done | candidates=%s | suggestions=%s | errors=%s | output=%s",
            result.get("candidate_count", 0),
            result.get("suggestion_count", 0),
            len(result.get("errors", [])),
            output_path,
        )
        return result
    except Exception:
        logger.exception("kg.llm_suggestions.failed")
        return None


def _fetch_supabase_rows(
    client: Any,
    table: str,
    columns: str,
    *,
    order_by: str | None = None,
    desc: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_size = min(1000, limit or 1000)
    start = 0

    while True:
        end = start + page_size - 1
        if limit is not None:
            end = min(end, limit - 1)

        query = client.table(table).select(columns)
        if order_by:
            query = query.order(order_by, desc=desc)
        response = query.range(start, end).execute()
        batch = response.data or []
        rows.extend(batch)

        if len(batch) < page_size or (limit is not None and len(rows) >= limit):
            break
        start += page_size

    return rows[:limit] if limit is not None else rows


def _load_supabase_frames(mode: str, sample_size: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    try:
        from supabase import create_client
    except ImportError as exc:
        raise ImportError("supabase package is required for KG data loading.") from exc

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY first.")

    client = create_client(url, key)
    paper_cols = ",".join(
        [
            "paper_id",
            "title",
            "abstract",
            "tldr",
            "keywords",
            "year",
            "journal",
            "document_type",
            "authors",
            "author_ids",
            "doi",
            "link",
        ]
    )
    lecturer_cols = "nip,nama_dosen,nama_norm,nidn,prodi,scopus_id,scholar_id,sinta_id"

    paper_limit = max(sample_size * 3, sample_size) if mode == "sample" else None
    paper_rows = _fetch_supabase_rows(
        client,
        "papers",
        paper_cols,
        order_by="year",
        desc=True,
        limit=paper_limit,
    )
    papers_df = pd.DataFrame(paper_rows)
    if not papers_df.empty:
        title_mask = papers_df["title"].fillna("").astype(str).str.strip() != ""
        abstract_mask = papers_df["abstract"].fillna("").astype(str).str.len() > 20
        tldr_mask = papers_df["tldr"].fillna("").astype(str).str.len() > 20
        papers_df = papers_df[title_mask & (abstract_mask | tldr_mask)].copy()
        if mode == "sample":
            papers_df = papers_df.head(sample_size).copy()

    lecturers_df = pd.DataFrame(_fetch_supabase_rows(client, "lecturers", lecturer_cols))
    links_df = pd.DataFrame(_fetch_supabase_rows(client, "paper_lecturers", "paper_id,nip"))
    if not papers_df.empty and not links_df.empty:
        paper_ids = set(papers_df["paper_id"].fillna("").astype(str))
        links_df = links_df[links_df["paper_id"].fillna("").astype(str).isin(paper_ids)].copy()

    return papers_df.reset_index(drop=True), lecturers_df.reset_index(drop=True), links_df.reset_index(drop=True)


def _load_postgres_frames(mode: str, sample_size: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    try:
        from yunesa.etl.clients.postgres_client import PostgresClient
        pg_client = PostgresClient()
        with pg_client._get_connection() as conn:
            with conn.cursor() as cur:
                limit_clause = f" LIMIT {max(sample_size * 3, sample_size)}" if mode == "sample" else ""
                cur.execute(f"SELECT paper_id, title, abstract, tldr, keywords, year, journal, document_type, authors, author_ids, doi, link FROM papers ORDER BY year DESC NULLS LAST{limit_clause};")
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description]
                papers_df = pd.DataFrame(rows, columns=cols)

                cur.execute("SELECT nip, nama_dosen, nama_norm, nidn, prodi, scopus_id, scholar_id, sinta_id FROM lecturers;")
                l_rows = cur.fetchall()
                l_cols = [desc[0] for desc in cur.description]
                lecturers_df = pd.DataFrame(l_rows, columns=l_cols)

        if not papers_df.empty:
            title_mask = papers_df["title"].fillna("").astype(str).str.strip() != ""
            abstract_mask = papers_df["abstract"].fillna("").astype(str).str.len() > 20
            tldr_mask = papers_df["tldr"].fillna("").astype(str).str.len() > 20
            papers_df = papers_df[title_mask & (abstract_mask | tldr_mask)].copy()
            if mode == "sample":
                papers_df = papers_df.head(sample_size).copy()

        links = []
        if not papers_df.empty:
            for _, row in papers_df.iterrows():
                pid = row.get("paper_id")
                a_ids = str(row.get("author_ids") or "")
                if pid and a_ids:
                    for aid in a_ids.replace(";", ",").split(","):
                        aid_clean = aid.strip()
                        if aid_clean:
                            links.append({"paper_id": pid, "nip": aid_clean})
        links_df = pd.DataFrame(links)
        return papers_df.reset_index(drop=True), lecturers_df.reset_index(drop=True), links_df.reset_index(drop=True)
    except Exception as exc:
        logger.warning(f"kg_service.postgres_failed | {exc} | Falling back to Supabase...")
        return _load_supabase_frames(mode, sample_size)


def run_kg_data_load(*, mode: str = "incremental", sample_size: int = 50) -> dict[str, Any]:
    """Fetch KG source tables from Self-Hosted PostgreSQL (with Supabase fallback) and persist task artifacts."""
    mode = _normal_mode(mode)
    sample_size = max(1, int(sample_size))
    papers_df, lecturers_df, links_df = _load_postgres_frames(mode, sample_size)

    write_dataframe_artifact(papers_df, kg_paths.KG_PAPERS_PARQUET)
    write_dataframe_artifact(lecturers_df, kg_paths.KG_LECTURERS_PARQUET)
    write_dataframe_artifact(links_df, kg_paths.KG_LINKS_PARQUET)

    result = {
        "mode": mode,
        "sample_size": sample_size if mode == "sample" else None,
        "artifacts": {
            "papers": str(kg_paths.KG_PAPERS_PARQUET),
            "lecturers": str(kg_paths.KG_LECTURERS_PARQUET),
            "links": str(kg_paths.KG_LINKS_PARQUET),
        },
        "rows": {
            "papers": len(papers_df),
            "lecturers": len(lecturers_df),
            "links": len(links_df),
        },
    }
    logger.info("kg.load_data.done | %s", json.dumps(result, sort_keys=True))
    return result


def run_kg_entity_extraction(*, mode: str = "incremental", sample_size: int = 50) -> dict[str, Any]:
    """Run optional GLiNER extraction and persist extracted entities JSON."""
    kg = _kg_module()
    mode = _normal_mode(mode)
    use_gliner = _env_bool("YUNESA_USE_GLINER", False)
    use_glirel = _env_bool("YUNESA_USE_GLIREL", False) and use_gliner

    if not path_exists(kg_paths.KG_PAPERS_PARQUET):
        run_kg_data_load(mode=mode, sample_size=sample_size)

    papers_df = read_dataframe_artifact(kg_paths.KG_PAPERS_PARQUET).fillna("")
    if not use_gliner:
        extracted: dict[str, Any] = {}
        write_json_artifact(extracted, kg_paths.KG_ENTITIES_JSON)
        result = {
            "mode": mode,
            "use_gliner": False,
            "use_glirel": False,
            "documents": 0,
            "entities": 0,
            "relationships": 0,
            "artifacts": {"entities": str(kg_paths.KG_ENTITIES_JSON)},
        }
        logger.info("kg.extract_entities.skipped | %s", json.dumps(result, sort_keys=True))
        return result

    extraction_config = kg.AcademicExtractionConfig(
        use_gliner=True,
        use_glirel=use_glirel,
        gliner_model=os.getenv("YUNESA_GLINER_MODEL", kg.DEFAULT_GLINER_MODEL),
        glirel_model=os.getenv("YUNESA_GLIREL_MODEL", kg.DEFAULT_GLIREL_MODEL),
        entity_threshold=float(os.getenv("YUNESA_GLINER_THRESHOLD", "0.50")),
        relation_threshold=float(os.getenv("YUNESA_GLIREL_THRESHOLD", "0.30")),
        max_text_chars=_env_int("YUNESA_EXTRACTION_MAX_TEXT_CHARS", 3500),
        max_entities_per_paper=_env_int("YUNESA_MAX_ENTITIES_PER_PAPER", 20),
        max_relations_per_paper=_env_int("YUNESA_MAX_RELATIONS_PER_PAPER", 20),
    )
    extracted = kg.extract_academic_elements_with_gliner_glirel(papers_df, extraction_config)
    write_json_artifact(extracted, kg_paths.KG_ENTITIES_JSON)
    summary = kg.summarize_extracted_elements(extracted)
    result = {
        "mode": mode,
        "use_gliner": True,
        "use_glirel": use_glirel,
        **summary,
        "artifacts": {"entities": str(kg_paths.KG_ENTITIES_JSON)},
    }
    logger.info("kg.extract_entities.done | %s", json.dumps(result, sort_keys=True))
    return result


def run_kg_build(*, mode: str = "incremental", sample_size: int = 50) -> dict[str, Any]:
    """Build the NetworkX academic KG and persist graph artifacts."""
    kg = _kg_module()
    mode = _normal_mode(mode)
    graph_name = _effective_graph_name(mode)

    if not path_exists(kg_paths.KG_PAPERS_PARQUET):
        run_kg_data_load(mode=mode, sample_size=sample_size)
    if not path_exists(kg_paths.KG_ENTITIES_JSON):
        run_kg_entity_extraction(mode=mode, sample_size=sample_size)

    papers_df = read_dataframe_artifact(kg_paths.KG_PAPERS_PARQUET).fillna("")
    lecturers_df = read_dataframe_artifact(kg_paths.KG_LECTURERS_PARQUET).fillna("")
    links_df = read_dataframe_artifact(kg_paths.KG_LINKS_PARQUET).fillna("")
    extracted = read_json_artifact(kg_paths.KG_ENTITIES_JSON)

    thesaurus_path = _resource_path("ieee-thesaurus.ttl", "YUNESA_IEEE_THESAURUS_PATH")
    taxonomy_path = _resource_path("ieee-taxonomy.ttl", "YUNESA_IEEE_TAXONOMY_PATH")
    aliases_path = _concept_aliases_path()
    ieee_index = kg.IeeeSemanticIndex.from_files(
        thesaurus_path,
        taxonomy_path,
        max_terms=None,
    )
    concept_resolver = kg.AcademicConceptResolver.from_path(aliases_path)
    builder = kg.AcademicKGBuilder(
        ieee_index,
        concept_resolver=concept_resolver,
        extracted_elements=extracted,
        graph_name=graph_name,
    )
    graph = builder.build(
        papers_df=papers_df,
        lecturers_df=lecturers_df,
        links_df=links_df,
        max_concepts_per_paper=_env_int("YUNESA_MAX_CONCEPTS_PER_PAPER", 14),
    )

    nodes_df, edges_df = kg.graph_to_frames(graph)
    write_dataframe_artifact(nodes_df, kg_paths.KG_NODES_PARQUET)
    write_dataframe_artifact(edges_df, kg_paths.KG_EDGES_PARQUET)

    serialisable = kg.serialisable_graph_copy(graph)
    write_json_artifact(json_graph.node_link_data(serialisable), kg_paths.KG_GRAPH_JSON)

    validation = builder.validate()
    quality = kg.graph_quality_report(graph)
    entity_resolution = kg.entity_resolution_report(graph)
    write_json_artifact(entity_resolution, kg_paths.KG_ENTITY_RESOLUTION_JSON)
    summary = {
        "mode": mode,
        "graph_name": graph_name,
        "input_rows": {
            "papers": len(papers_df),
            "lecturers": len(lecturers_df),
            "links": len(links_df),
        },
        "ieee_summary": ieee_index.summary(),
        "entity_resolution": {
            "resolver": concept_resolver.summary(),
            "report": entity_resolution,
        },
        "extraction": kg.summarize_extracted_elements(extracted),
        "validation": validation,
        "quality": quality,
        "artifacts": {
            "graph": str(kg_paths.KG_GRAPH_JSON),
            "nodes": str(kg_paths.KG_NODES_PARQUET),
            "edges": str(kg_paths.KG_EDGES_PARQUET),
            "entity_resolution": str(kg_paths.KG_ENTITY_RESOLUTION_JSON),
        },
    }
    write_json_artifact(summary, kg_paths.KG_SUMMARY_JSON)

    # ── Auto-generate LLM alias suggestions ──────────────────────────
    er_report_path = (
        Path(kg_paths.KG_ENTITY_RESOLUTION_JSON)
        if isinstance(kg_paths.KG_ENTITY_RESOLUTION_JSON, (str, Path))
        else None
    )
    er_suggestions_dir = Path(os.getenv(
        "YUNESA_ALIAS_SUGGESTIONS_PATH",
        "/app/data/kg/entity_resolution/concept_alias_suggestions.json",
    ))
    llm_result = _try_generate_llm_suggestions(er_report_path, er_suggestions_dir, kg)
    if llm_result is not None:
        summary["llm_suggestions"] = {
            "candidate_count": llm_result.get("candidate_count", 0),
            "suggestion_count": llm_result.get("suggestion_count", 0),
            "error_count": len(llm_result.get("errors", [])),
            "output_path": str(er_suggestions_dir),
        }
        write_json_artifact(summary, kg_paths.KG_SUMMARY_JSON)

    # ── Archive historical copies of reports ──────────────────────────
    run_id = os.getenv("YUNESA_RUN_ID", "").strip()
    if run_id:
        history_dir = (
            Path("/app/data/kg/output/history")
            if Path("/app/data").is_dir()
            else Path("data/kg/output/history")
        )
        _archive_artifact(er_report_path, history_dir, run_id)
        summary_path = (
            Path(kg_paths.KG_SUMMARY_JSON)
            if isinstance(kg_paths.KG_SUMMARY_JSON, (str, Path))
            else None
        )
        _archive_artifact(summary_path, history_dir, run_id)

    logger.info(
        "kg.build.done | nodes=%s | edges=%s | graph_name=%s",
        graph.number_of_nodes(),
        graph.number_of_edges(),
        graph_name,
    )
    return summary


def _run_kg_write_stores_legacy(*, mode: str = "incremental", sample_size: int = 50) -> dict[str, Any]:
    """Legacy combined implementation retained for compatibility audits."""
    kg = _kg_module()
    mode = _normal_mode(mode)
    graph_name = _effective_graph_name(mode)

    if not path_exists(kg_paths.KG_GRAPH_JSON):
        run_kg_build(mode=mode, sample_size=sample_size)

    # ── Quality gate enforcement ─────────────────────────────────────
    enforce_gates = _env_bool("YUNESA_ENFORCE_QUALITY_GATES", mode != "sample")
    if enforce_gates and path_exists(kg_paths.KG_SUMMARY_JSON):
        build_summary = read_json_artifact(kg_paths.KG_SUMMARY_JSON)
        gates = (build_summary.get("quality") or {}).get("quality_gates") or {}
        failed_gates = [name for name, passed in gates.items() if not passed]
        if failed_gates:
            msg = (
                f"Quality gate check FAILED — refusing to write stores. "
                f"Failed gates: {', '.join(failed_gates)}. "
                f"Set YUNESA_ENFORCE_QUALITY_GATES=false to override."
            )
            logger.error("kg.write_stores.quality_gate_blocked | %s", msg)
            raise ValueError(msg)
        logger.info("kg.write_stores.quality_gates_passed | gates=%s", list(gates.keys()))

    graph_payload = read_json_artifact(kg_paths.KG_GRAPH_JSON)
    graph = json_graph.node_link_graph(graph_payload, directed=True, multigraph=True)

    default_write = mode != "sample"
    default_clear = mode == "full"
    write_neo4j = _env_bool("YUNESA_KG_WRITE_NEO4J", default_write)
    write_milvus = _env_bool("YUNESA_KG_WRITE_MILVUS", default_write)
    clear_neo4j = _env_bool("YUNESA_KG_CLEAR_NEO4J", default_clear)
    clear_milvus = _env_bool("YUNESA_KG_CLEAR_MILVUS", default_clear)

    report: dict[str, Any] = {
        "mode": mode,
        "graph_name": graph_name,
        "write_neo4j": write_neo4j,
        "write_milvus": write_milvus,
        "clear_neo4j": clear_neo4j,
        "clear_milvus": clear_milvus,
        "neo4j": None,
        "milvus": None,
    }
    if write_neo4j:
        report["neo4j"] = kg.write_graph_to_neo4j(
            graph,
            graph_name=graph_name,
            clear_existing=clear_neo4j,
        )
    if write_milvus:
        report["milvus"] = kg.write_vector_index_to_milvus(
            graph,
            graph_name=graph_name,
            clear_existing=clear_milvus,
        )

    summary: dict[str, Any] = {}
    if path_exists(kg_paths.KG_SUMMARY_JSON):
        summary = read_json_artifact(kg_paths.KG_SUMMARY_JSON)
    summary["storage"] = report
    write_json_artifact(summary, kg_paths.KG_SUMMARY_JSON)
    logger.info(
        "kg.write_stores.done | %s",
        json.dumps(
            {key: value for key, value in report.items() if key not in {"neo4j", "milvus"}},
            sort_keys=True,
        ),
    )
    return report


def run_kg_write_stores(*, mode: str = "incremental", sample_size: int = 50) -> dict[str, Any]:
    """Compatibility wrapper around independently retryable storage stages."""
    from yunesa.etl.services.kg_storage_service import run_kg_write_stores as run_split_stores

    return run_split_stores(mode=mode, sample_size=sample_size)
