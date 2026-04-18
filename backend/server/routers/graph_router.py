import asyncio
import traceback

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from server.utils.auth_middleware import get_admin_user, get_superadmin_user
from yunesa import graph_base, knowledge_base
from yunesa.knowledge.graphs.adapters.base import GraphAdapter
from yunesa.knowledge.graphs.adapters.factory import GraphAdapterFactory
from yunesa.services.task_service import TaskContext, tasker
from yunesa.storage.postgres.models_business import User
from yunesa.storage.minio.client import StorageError
from yunesa.utils.logging_config import logger

graph = APIRouter(prefix="/graph", tags=["graph"])


# =============================================================================
# === Unified Graph Interface (Unified Graph API) ===
# =============================================================================


async def _get_graph_adapter(db_id: str) -> GraphAdapter:
    """
    Get the corresponding graph adapter by database ID.

    Args:
        db_id: Database ID.

    Returns:
        GraphAdapter: Matching graph adapter instance.
    """
    # Check graph database service status (required only for Upload type).
    if not graph_base.is_running():
        # First detect graph type; allow it if the type does not require graph_base.
        graph_type = await GraphAdapterFactory.detect_graph_type(db_id, knowledge_base)
        if graph_type == "upload":
            raise HTTPException(
                status_code=503, detail="Graph database service is not running")

    # Auto-create adapter via factory method.
    return await GraphAdapterFactory.create_adapter_by_db_id(
        db_id=db_id, knowledge_base_manager=knowledge_base, graph_db_instance=graph_base
    )


def _get_capabilities_from_metadata(metadata) -> dict:
    """Extract capabilities dictionary from a GraphMetadata object."""
    return {
        "supports_embedding": metadata.supports_embedding,
        "supports_threshold": metadata.supports_threshold,
    }


@graph.get("/list")
async def get_graphs(current_user: User = Depends(get_admin_user)):
    """
    Get all available knowledge graphs.

    Returns:
        A list containing all graph info (including Neo4j and LightRAG),
        plus capability metadata for each type.
    """
    try:
        graphs = []

        # 1. Get default Neo4j graph info (Upload type).
        neo4j_info = graph_base.get_graph_info()
        if neo4j_info:
            # Use default metadata from Upload adapter.
            from yunesa.knowledge.graphs.adapters.upload import UploadGraphAdapter

            capabilities = _get_capabilities_from_metadata(
                UploadGraphAdapter._get_metadata(None))

            graphs.append(
                {
                    "id": "neo4j",
                    "name": "default graph",
                    "type": "upload",
                    "description": "Default graph database for uploaded documents",
                    "status": neo4j_info.get("status", "unknown"),
                    "created_at": neo4j_info.get("last_updated"),
                    "node_count": neo4j_info.get("entity_count", 0),
                    "edge_count": neo4j_info.get("relationship_count", 0),
                    "capabilities": capabilities,
                }
            )

        # 2. Get LightRAG database info.
        lightrag_dbs = await knowledge_base.get_lightrag_databases()
        # Use default metadata from LightRAG adapter.
        from yunesa.knowledge.graphs.adapters.lightrag import LightRAGGraphAdapter

        capabilities = _get_capabilities_from_metadata(
            LightRAGGraphAdapter._get_metadata(None))

        for db in lightrag_dbs:
            db_id = db.get("db_id")

            graphs.append(
                {
                    "id": db_id,
                    "name": db.get("name"),
                    "type": "lightrag",
                    "description": db.get("description"),
                    "status": "active",  # LightRAG DBs are usually active if listed
                    "created_at": db.get("created_at"),
                    "metadata": db,
                    "capabilities": capabilities,
                }
            )

        return {"success": True, "data": graphs}

    except Exception as e:
        logger.error(f"Failed to list graphs: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to list graphs: {str(e)}")


@graph.get("/subgraph")
async def get_subgraph(
    db_id: str = Query(..., description="knowledge graphID"),
    node_label: str = Query("*", description="Node label or query keyword"),
    max_depth: int = Query(2, description="Maximum depth", ge=1, le=5),
    max_nodes: int = Query(
        100, description="Maximum node count", ge=1, le=1000),
    current_user: User = Depends(get_admin_user),
):
    """
    Unified subgraph query endpoint.

    Args:
        db_id: Graph ID (LightRAG DB ID or "neo4j").
        node_label: Query keyword or label.
        max_depth: Traversal depth.
        max_nodes: Maximum number of returned nodes.
    """
    try:
        logger.info(f"Querying subgraph - db_id: {db_id}, label: {node_label}")

        adapter = await _get_graph_adapter(db_id)

        # Unified query parameters; adapter handles its own processing logic.
        query_kwargs = {
            "keyword": node_label,
            "max_depth": max_depth,
            "max_nodes": max_nodes,
        }

        result_data = await adapter.query_nodes(**query_kwargs)

        return {
            "success": True,
            "data": result_data,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get subgraph: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get subgraph: {str(e)}")


@graph.get("/labels")
async def get_graph_labels(
    db_id: str = Query(..., description="knowledge graphID"), current_user: User = Depends(get_admin_user)
):
    """
    Get all labels for the graph.
    """
    try:
        # Use unified adapter label retrieval.
        adapter = await _get_graph_adapter(db_id)
        labels = await adapter.get_labels()
        return {"success": True, "data": {"labels": labels}}

    except Exception as e:
        logger.error(f"Failed to get labels: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get labels: {str(e)}")


@graph.get("/stats")
async def get_graph_stats(
    db_id: str = Query(..., description="knowledge graphID"), current_user: User = Depends(get_admin_user)
):
    """
    Get graph statistics.
    """
    try:
        # Use adapter statistics (for kb_* and LightRAG databases).
        if db_id.startswith("kb_") or knowledge_base.is_lightrag_database(db_id):
            adapter = await _get_graph_adapter(db_id)
            stats_data = await adapter.get_stats()
            return {"success": True, "data": stats_data}
        else:
            # Neo4j stats (directly managed graph).
            info = graph_base.get_graph_info(graph_name=db_id)
            if not info:
                raise HTTPException(
                    status_code=404, detail="Graph info not found")

            return {
                "success": True,
                "data": {
                    "total_nodes": info.get("entity_count", 0),
                    "total_edges": info.get("relationship_count", 0),
                    # Neo4j info currently returns 'labels' list, not counts per label.
                    # Improving this would require updating GraphDatabase.get_graph_info
                    "entity_types": [{"type": label, "count": "N/A"} for label in info.get("labels", [])],
                },
            }

    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get stats: {str(e)}")


@graph.get("/neo4j/nodes")
async def get_neo4j_nodes(
    kgdb_name: str = Query(..., description="knowledge graphdatabasename"),
    num: int = Query(100, description="nodecount", ge=1, le=1000),
    current_user: User = Depends(get_admin_user),
):
    """(Deprecated) Use /graph/subgraph instead"""
    response = await get_subgraph(db_id=kgdb_name, node_label="*", max_nodes=num, current_user=current_user)
    return {"success": True, "result": response["data"], "message": "success"}


@graph.get("/neo4j/node")
async def get_neo4j_node(
    entity_name: str = Query(..., description="entityname"), current_user: User = Depends(get_admin_user)
):
    """(Deprecated) Use /graph/subgraph instead"""
    # neo4j/node uses query_nodes(keyword=entity_name)
    response = await get_subgraph(db_id="neo4j", node_label=entity_name, current_user=current_user)
    return {"success": True, "result": response["data"], "message": "success"}


@graph.get("/neo4j/info")
async def get_neo4j_info(current_user: User = Depends(get_admin_user)):
    """Get Neo4j graph database information."""
    try:
        graph_info = graph_base.get_graph_info()
        if graph_info is None:
            raise HTTPException(
                status_code=400, detail="Failed to get graph database info")
        return {"success": True, "data": graph_info}
    except Exception as e:
        logger.error(f"Failed to get graph database info: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get graph database info: {str(e)}")


@graph.post("/neo4j/index-entities")
async def index_neo4j_entities(data: dict = Body(default={}), current_user: User = Depends(get_admin_user)):
    """Add embedding vector indexes to Neo4j graph nodes."""
    try:
        if not graph_base.is_running():
            raise HTTPException(
                status_code=400, detail="Graph database is not started")

        kgdb_name = data.get("kgdb_name", "neo4j")
        count = await graph_base.add_embedding_to_nodes(kgdb_name=kgdb_name)

        return {
            "success": True,
            "status": "success",
            "message": f"Successfully added embedding vectors for {count} nodes",
            "indexed_count": count,
        }
    except Exception as e:
        logger.error(f"Failed to index nodes: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to index nodes: {str(e)}")


@graph.post("/neo4j/add-entities")
async def add_neo4j_entities(
    file_path: str = Body(...),
    kgdb_name: str | None = Body(None),
    embed_model_name: str | None = Body(None),
    batch_size: int | None = Body(None),
    current_user: User = Depends(get_admin_user),
):
    """Add graph entities to Neo4j from a JSONL file (MinIO URL only)."""
    try:
        # Service layer validates URL and downloads file from MinIO.
        await graph_base.jsonl_file_add_entity(file_path, kgdb_name, embed_model_name, batch_size)
        return {"success": True, "message": "Entities added successfully", "status": "success"}
    except StorageError as e:
        # MinIO validation or download error.
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        # Local path rejected.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to add entities: {e}, {traceback.format_exc()}")
        return {"success": False, "message": f"Failed to add entities: {e}", "status": "failed"}


# =============================================================================
# === KG Construction Pipeline (Superadmin Only) ===
# =============================================================================


@graph.post("/kg/build")
async def build_knowledge_graph(
    data: dict = Body(default={}),
    _current_user: User = Depends(get_superadmin_user),
):
    """Trigger the full KG construction pipeline as a background task.

    This endpoint is restricted to superadmin users. It enqueues the
    Knowledge Graph construction pipeline (source loading → backbone →
    NER → entity resolution → LLM curation → DB ingestion) as a
    background task and returns a task_id for progress tracking.

    Body params (all optional):
        test_mode (bool): Limit to 5 papers for quick iteration.  Default: False.
        max_papers (int): Maximum papers to process.  Default: config value.
        clear_db (bool): Clear Neo4j/Milvus before ingestion.  Default: True.
    """

    test_mode: bool = data.get("test_mode", False)
    max_papers: int | None = data.get("max_papers")
    clear_db: bool = data.get("clear_db", True)

    async def run_kg_build(context: TaskContext):
        """Wrapper that runs the synchronous KG pipeline in a thread."""
        await context.set_progress(5.0, "Initializing KG construction pipeline…")

        from yunesa.knowledge.kg.services.kg_pipeline import KGPipeline

        pipeline = KGPipeline(
            test_mode=test_mode,
            max_papers=max_papers,
            clear_db=clear_db,
        )

        mode_label = "TEST" if test_mode else "PRODUCTION"
        await context.set_progress(
            10.0,
            f"Pipeline created ({mode_label} mode, max_papers={pipeline.max_papers}). "
            "Running in background thread…",
        )

        # KGPipeline.run() is synchronous → offload to thread pool
        summary = await asyncio.to_thread(pipeline.run)

        await context.set_result(summary)
        await context.set_progress(100.0, "KG construction completed successfully")
        return summary

    try:
        task = await tasker.enqueue(
            name="KG Construction Pipeline",
            task_type="kg_build",
            payload={
                "test_mode": test_mode,
                "max_papers": max_papers,
                "clear_db": clear_db,
            },
            coroutine=run_kg_build,
        )
        return {
            "message": "KG build task submitted. Track progress in Task Center.",
            "status": "queued",
            "task_id": task.id,
        }
    except Exception as e:
        logger.error(
            f"Failed to enqueue KG build: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to enqueue KG build: {e}")


@graph.get("/kg/status")
async def get_kg_build_status(
    _current_user: User = Depends(get_superadmin_user),
):
    """List recent KG build tasks with their status.

    Returns the latest kg_build tasks so the admin can monitor progress
    without knowing individual task IDs.
    """
    try:
        all_tasks = await tasker.list_tasks(limit=50)
        kg_tasks = [
            t for t in all_tasks.get("tasks", []) if t.get("type") == "kg_build"
        ]
        return {"success": True, "data": kg_tasks}
    except Exception as e:
        logger.error(f"Failed to list KG build tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))
