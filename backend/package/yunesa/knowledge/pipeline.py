"""
pipeline.py — End-to-End Academic Knowledge Graph Pipeline Runner
==================================================================
Pipeline runner functions: build_academic_kg_from_supabase, run_local_kg_pipeline, write_run_manifest.
"""

from __future__ import annotations

import time
import json
import logging
from pathlib import Path
from typing import Any

from yunesa.knowledge.config import (
    KGConfig,
    AcademicExtractionConfig,
    load_project_env,
    supabase_credential_status,
    milvus_credential_status,
)
from yunesa.knowledge.utils.text_processing import normalize_text
from yunesa.knowledge.parser.data_loader import (
    fetch_supabase_sample,
    fetch_postgres_sample,
    load_local_csv_sample,
)
from yunesa.knowledge.utils.ieee_semantic import IeeeSemanticIndex
from yunesa.knowledge.utils.concept_resolver import AcademicConceptResolver
from yunesa.knowledge.parser.ner_extraction import (
    extract_academic_elements_with_gliner_glirel,
    summarize_extracted_elements,
)
from yunesa.knowledge.graphs.builder import (
    AcademicKGBuilder,
    export_graph_artifacts,
)
from yunesa.knowledge.graphs.storage_neo4j import (
    write_graph_to_neo4j,
    inspect_neo4j_graph,
    neo4j_credential_status,
)
from yunesa.knowledge.implementations.milvus import (
    write_vector_index_to_milvus,
    inspect_milvus_collections,
)
from yunesa.knowledge.eval.quality_gates import graph_quality_report

logger = logging.getLogger(__name__)


def build_academic_kg_from_supabase(sample_size: int = 50) -> dict[str, Any]:
    config = KGConfig.default(sample_size=sample_size)
    load_project_env(config.project_root)

    papers_df, lecturers_df, links_df = fetch_supabase_sample(sample_size=sample_size)
    ieee_index = IeeeSemanticIndex.from_files(
        config.thesaurus_path,
        config.taxonomy_path,
        max_terms=config.max_ieee_terms,
    )

    concept_resolver = AcademicConceptResolver.from_path(config.concept_aliases_path)
    builder = AcademicKGBuilder(ieee_index, concept_resolver=concept_resolver, graph_name="yunesa_academic_kg")
    graph = builder.build(
        papers_df=papers_df,
        lecturers_df=lecturers_df,
        links_df=links_df,
        max_concepts_per_paper=config.max_concepts_per_paper,
    )
    artifacts = export_graph_artifacts(graph, config.output_dir)

    return {
        "config": config,
        "papers_df": papers_df,
        "lecturers_df": lecturers_df,
        "links_df": links_df,
        "ieee_summary": ieee_index.summary(),
        "entity_resolution": concept_resolver.summary(),
        "graph": graph,
        "validation": builder.validate(),
        "artifacts": artifacts,
    }


def write_run_manifest(
    *,
    output_dir: Path,
    config: KGConfig,
    validation: dict[str, Any],
    quality: dict[str, Any],
    storage_reports: dict[str, Any] | None = None,
    artifacts: dict[str, Path] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "config": {
            "project_root": str(config.project_root),
            "build_graph_dir": str(config.build_graph_dir),
            "output_dir": str(config.output_dir),
            "sample_size": config.sample_size,
            "max_concepts_per_paper": config.max_concepts_per_paper,
        },
        "credential_status": {
            "supabase": supabase_credential_status(),
            "neo4j": neo4j_credential_status(),
            "milvus": milvus_credential_status(),
        },
        "validation": validation,
        "quality": quality,
        "storage_reports": storage_reports or {},
        "artifacts": {key: str(value) for key, value in (artifacts or {}).items()},
    }
    path = output_dir / "run_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def run_local_kg_pipeline(
    *,
    sample_size: int = 50,
    source: str = "postgres",
    graph_name: str = "yunesa_academic_kg_local",
    write_neo4j: bool = False,
    write_milvus: bool = False,
    clear_neo4j: bool = False,
    clear_milvus: bool = False,
    use_extraction: bool | None = None,
    use_gliner: bool | None = None,
    use_glirel: bool | None = None,
) -> dict[str, Any]:
    """Build and optionally write the KG locally for repeatable debugging."""
    config = KGConfig.default(sample_size=sample_size)
    load_project_env(config.project_root)

    source = normalize_text(source) or "postgres"
    try:
        if source == "local_csv":
            raise RuntimeError("forced local CSV source")
        elif source == "supabase":
            papers_df, lecturers_df, links_df = fetch_supabase_sample(sample_size=sample_size)
            data_source = "supabase"
        else:
            papers_df, lecturers_df, links_df = fetch_postgres_sample(sample_size=sample_size)
            data_source = "postgres"
    except Exception as exc:
        logger.warning("kg.load_failed | source=%s | error=%s | fallback=local_csv", source, exc)
        papers_df, lecturers_df, links_df = load_local_csv_sample(config.project_root / "notebooks", sample_size=sample_size)
        data_source = "local_csv"

    extraction_config = AcademicExtractionConfig.from_env()
    gliner_enabled = extraction_config.use_gliner
    glirel_enabled = extraction_config.use_glirel
    if use_extraction is not None:
        gliner_enabled = use_extraction
        if not use_extraction:
            glirel_enabled = False
    if use_gliner is not None:
        gliner_enabled = use_gliner
    if use_glirel is not None:
        glirel_enabled = use_glirel
    if not gliner_enabled:
        glirel_enabled = False
    extraction_config = AcademicExtractionConfig(
        use_gliner=gliner_enabled,
        use_glirel=glirel_enabled,
        gliner_model=extraction_config.gliner_model,
        glirel_model=extraction_config.glirel_model,
        entity_threshold=extraction_config.entity_threshold,
        relation_threshold=extraction_config.relation_threshold,
        max_text_chars=extraction_config.max_text_chars,
        max_entities_per_paper=extraction_config.max_entities_per_paper,
        max_relations_per_paper=extraction_config.max_relations_per_paper,
    )
    extracted_elements = extract_academic_elements_with_gliner_glirel(papers_df, extraction_config)

    ieee_index = IeeeSemanticIndex.from_files(
        config.thesaurus_path,
        config.taxonomy_path,
        max_terms=config.max_ieee_terms,
    )
    concept_resolver = AcademicConceptResolver.from_path(config.concept_aliases_path)
    builder = AcademicKGBuilder(
        ieee_index,
        concept_resolver=concept_resolver,
        extracted_elements=extracted_elements,
        graph_name=graph_name,
    )
    graph = builder.build(
        papers_df=papers_df,
        lecturers_df=lecturers_df,
        links_df=links_df,
        max_concepts_per_paper=config.max_concepts_per_paper,
    )
    artifacts = export_graph_artifacts(graph, config.output_dir)
    validation = builder.validate()
    quality = graph_quality_report(graph)

    storage_reports: dict[str, Any] = {
        "data_source": data_source,
        "input_rows": {
            "papers": len(papers_df),
            "lecturers": len(lecturers_df),
            "links": len(links_df),
        },
        "extraction": summarize_extracted_elements(extracted_elements),
        "entity_resolution": concept_resolver.summary(),
    }
    if write_neo4j:
        storage_reports["neo4j_write"] = write_graph_to_neo4j(
            graph,
            graph_name=graph_name,
            clear_existing=clear_neo4j,
        )
        storage_reports["neo4j_inspect"] = inspect_neo4j_graph(graph_name=graph_name)
    if write_milvus:
        storage_reports["milvus_write"] = write_vector_index_to_milvus(
            graph,
            clear_existing=clear_milvus,
            graph_name=graph_name,
        )
        storage_reports["milvus_inspect"] = inspect_milvus_collections()

    manifest_path = write_run_manifest(
        output_dir=config.output_dir,
        config=config,
        validation=validation,
        quality=quality,
        storage_reports=storage_reports,
        artifacts=artifacts,
    )

    return {
        "config": config,
        "graph": graph,
        "validation": validation,
        "quality": quality,
        "storage_reports": storage_reports,
        "artifacts": artifacts,
        "manifest_path": manifest_path,
    }
