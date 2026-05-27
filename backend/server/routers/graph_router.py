import asyncio
import traceback

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

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
    # Check graph database service status.
    if not graph_base.is_running():
        # First detect graph type; allow it if the type does not require graph_base.
        graph_type = await GraphAdapterFactory.detect_graph_type(db_id, knowledge_base)
        if graph_type == "core":
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

        # 1. Get default Neo4j graph info (Core type).
        neo4j_info = graph_base.get_graph_info()
        if neo4j_info:
            # Use default metadata from Core adapter.
            from yunesa.knowledge.graphs.adapters.core import CoreGraphAdapter

            capabilities = _get_capabilities_from_metadata(
                CoreGraphAdapter._get_metadata(None))

            graphs.append(
                {
                    "id": "neo4j",
                    "name": "Core Citation Graph",
                    "type": "core",
                    "description": "Main graph database for real-time citations and entity relationships",
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
                    "status": "active",
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
                    "entity_types": [{"type": label, "count": "N/A"} for label in info.get("labels", [])],
                },
            }

    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get stats: {str(e)}")


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

