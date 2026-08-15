"""FastAPI router for Knowledge Graph Construction (conskg)."""

from __future__ import annotations

import logging
from typing import Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from yunesa.services.task_service import TaskContext, tasker
from yunesa.knowledge.services import kg_service, kg_storage_service, kg_paths
from yunesa.etl.utils.storage import path_exists, read_json_artifact

logger = logging.getLogger(__name__)

conskg_router = APIRouter(prefix="/conskg", tags=["conskg"])


class KGBuildRequest(BaseModel):
    mode: str = Field(default="incremental", description="Run mode: sample, incremental, full")
    sample_size: int = Field(default=50, ge=1, description="Sample size if mode is sample")
    graph_name: str = Field(default="yunesa_academic_kg", description="Target graph name")
    use_gliner: bool = Field(default=True, description="Enable GLiNER entity extraction")


class KGWriteRequest(BaseModel):
    mode: str = Field(default="incremental", description="Run mode: sample, incremental, full")
    sample_size: int = Field(default=50, ge=1, description="Sample size if mode is sample")
    graph_name: str = Field(default="yunesa_academic_kg", description="Target graph name")
    clear_existing: bool = Field(default=False, description="Clear existing database contents before writing")


@conskg_router.post("/build")
async def build_knowledge_graph(request: KGBuildRequest):
    """Trigger end-to-end Knowledge Graph building as a background task."""
    async def _run_build(context: TaskContext):
        await context.set_progress(10.0, "Loading KG source data...")
        load_result = kg_service.run_kg_data_load(mode=request.mode, sample_size=request.sample_size)
        
        if request.use_gliner:
            await context.set_progress(40.0, "Running GLiNER entity extraction...")
            kg_service.run_kg_entity_extraction(mode=request.mode, sample_size=request.sample_size)
            
        await context.set_progress(70.0, "Building graph & canonicalizing entities...")
        build_result = kg_service.run_kg_build(mode=request.mode, sample_size=request.sample_size)
        
        await context.set_progress(100.0, "Knowledge Graph construction completed")
        return build_result

    task = await tasker.enqueue(
        name=f"Build Knowledge Graph ({request.graph_name})",
        task_type="kg_build",
        payload=request.model_dump(),
        coroutine=_run_build,
    )
    return {"message": "KG build task queued", "task_id": task["id"], "status": "queued"}


@conskg_router.post("/write/neo4j")
async def write_to_neo4j(request: KGWriteRequest):
    """Write built Knowledge Graph to Neo4j database."""
    async def _run_write_neo4j(context: TaskContext):
        await context.set_progress(20.0, "Writing graph to Neo4j...")
        result = kg_storage_service.run_kg_write_neo4j(mode=request.mode, sample_size=request.sample_size)
        await context.set_progress(100.0, "Neo4j write completed")
        return result

    task = await tasker.enqueue(
        name=f"Write KG to Neo4j ({request.graph_name})",
        task_type="kg_write_neo4j",
        payload=request.model_dump(),
        coroutine=_run_write_neo4j,
    )
    return {"message": "Neo4j write task queued", "task_id": task["id"], "status": "queued"}


@conskg_router.post("/write/milvus")
async def write_to_milvus(request: KGWriteRequest):
    """Write Knowledge Graph vector indices to Milvus."""
    async def _run_write_milvus(context: TaskContext):
        await context.set_progress(20.0, "Writing vector indices to Milvus...")
        result = kg_storage_service.run_kg_write_milvus(mode=request.mode, sample_size=request.sample_size)
        await context.set_progress(100.0, "Milvus write completed")
        return result

    task = await tasker.enqueue(
        name=f"Write KG to Milvus ({request.graph_name})",
        task_type="kg_write_milvus",
        payload=request.model_dump(),
        coroutine=_run_write_milvus,
    )
    return {"message": "Milvus write task queued", "task_id": task["id"], "status": "queued"}


@conskg_router.post("/write/all")
async def write_to_all_stores(request: KGWriteRequest):
    """Write Knowledge Graph to both Neo4j and Milvus."""
    async def _run_write_all(context: TaskContext):
        await context.set_progress(20.0, "Writing graph to Neo4j...")
        neo4j_res = kg_storage_service.run_kg_write_neo4j(mode=request.mode, sample_size=request.sample_size)
        await context.set_progress(60.0, "Writing vector indices to Milvus...")
        milvus_res = kg_storage_service.run_kg_write_milvus(mode=request.mode, sample_size=request.sample_size)
        await context.set_progress(100.0, "All store writes completed")
        return {"neo4j": neo4j_res, "milvus": milvus_res}

    task = await tasker.enqueue(
        name=f"Write KG to Neo4j & Milvus ({request.graph_name})",
        task_type="kg_write_all",
        payload=request.model_dump(),
        coroutine=_run_write_all,
    )
    return {"message": "Store write task queued", "task_id": task["id"], "status": "queued"}


@conskg_router.get("/artifacts")
async def get_kg_artifacts_status():
    """Retrieve availability and metadata of KG artifacts on disk."""
    summary = {}
    if path_exists(kg_paths.KG_SUMMARY_JSON):
        try:
            summary = read_json_artifact(kg_paths.KG_SUMMARY_JSON)
        except Exception as err:
            logger.warning("Could not read KG summary JSON: %s", err)

    return {
        "artifacts": {
            "papers_parquet": path_exists(kg_paths.KG_PAPERS_PARQUET),
            "lecturers_parquet": path_exists(kg_paths.KG_LECTURERS_PARQUET),
            "links_parquet": path_exists(kg_paths.KG_LINKS_PARQUET),
            "entities_json": path_exists(kg_paths.KG_ENTITIES_JSON),
            "graph_json": path_exists(kg_paths.KG_GRAPH_JSON),
            "summary_json": path_exists(kg_paths.KG_SUMMARY_JSON),
            "entity_resolution_json": path_exists(kg_paths.KG_ENTITY_RESOLUTION_JSON),
        },
        "latest_summary": summary,
    }
