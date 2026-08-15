from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from yunesa.services.task_service import tasker
from yunesa.services.mcp_service import ensure_builtin_mcp_servers_in_db
from yunesa.services.subagent_service import init_builtin_subagents
from yunesa.services.run_queue_service import close_queue_clients, get_redis_client
from yunesa.storage.postgres.manager import pg_manager
from yunesa.knowledge import knowledge_base
from yunesa.utils import logger
from yunesa.agents.backends.sandbox import init_sandbox_provider, shutdown_sandbox_provider
from yunesa.config.app import config
from server.app_metadata import get_yunesa_banner


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan event manager"""
    # Initialize database connections
    try:
        pg_manager.initialize()
        await pg_manager.create_business_tables()
        await pg_manager.ensure_business_schema()
        await pg_manager.ensure_knowledge_schema()
    except Exception as e:
        logger.error(f"Failed to initialize database during startup: {e}")

    # Ensure builtin MCP server definitions exist in the database
    try:
        await ensure_builtin_mcp_servers_in_db()
    except Exception as e:
        logger.error(f"Failed to ensure builtin MCP servers during startup: {e}")

    # Initialize builtin SubAgents
    try:
        await init_builtin_subagents()
    except Exception as e:
        logger.error(f"Failed to initialize builtin subagents during startup: {e}")
        raise

    # Initialize Knowledge Base manager
    import asyncio
    import os
    if os.environ.get("LITE_MODE", "").lower() in ("true", "1"):
        logger.info("LITE_MODE enabled, skipping knowledge base initialization")
    else:
        try:
            await knowledge_base.initialize()
        except Exception as e:
            logger.error(f"Failed to initialize knowledge base manager: {e}")

    # Pre-warm Neo4j & Milvus connection pools in background (non-blocking).
    # Cold-start of the Neo4j AuraDB driver takes up to ~140 s on first query.
    # Firing a lightweight ping here eliminates that latency for real user queries.
    async def _prewarm_neo4j():
        try:
            from yunesa import graph_base
            if hasattr(graph_base, "start") and not graph_base.is_running():
                await asyncio.to_thread(graph_base.start)
            if graph_base.is_running() and getattr(graph_base, "driver", None):
                def _ping():
                    with graph_base.driver.session() as session:
                        session.run("RETURN 1")
                await asyncio.to_thread(_ping)
                logger.info("Neo4j connection pool pre-warmed successfully")
        except Exception as exc:
            logger.warning(f"Neo4j pre-warm skipped (will connect on first query): {exc}")

    async def _prewarm_milvus():
        try:
            milvus_uri = os.getenv("MILVUS_URI") or os.getenv("ZILLIZ_URI", "")
            milvus_token = os.getenv("MILVUS_TOKEN") or os.getenv("ZILLIZ_TOKEN", "")
            if not milvus_uri or not milvus_token:
                return
            from yunesa.graphrag.storage import normalize_milvus_uri
            from pymilvus import MilvusClient
            def _ping():
                client = MilvusClient(uri=normalize_milvus_uri(milvus_uri), token=milvus_token)
                client.list_collections()
            await asyncio.to_thread(_ping)
            logger.info("Milvus/Zilliz connection pool pre-warmed successfully")
        except Exception as exc:
            logger.warning(f"Milvus pre-warm skipped (will connect on first query): {exc}")

    asyncio.create_task(_prewarm_neo4j())
    asyncio.create_task(_prewarm_milvus())

    # Warm up Redis (run queue)
    try:
        redis = await get_redis_client()
        await redis.ping()
    except Exception as e:
        logger.warning(f"Run queue redis unavailable on startup: {e}")

    sandbox_enabled = os.environ.get("SANDBOX_ENABLED", "").lower() in ("true", "1", "yes")
    if sandbox_enabled:
        try:
            init_sandbox_provider()
        except Exception as e:
            logger.error(f"Failed to initialize sandbox provider during startup: {e}")
    else:
        logger.info("SANDBOX_ENABLED is false; skipping sandbox provider startup")

    # =========================================================
    # LangGraph Checkpointer Setup
    # =========================================================
    checkpointer = AsyncPostgresSaver(pg_manager.langgraph_pool)
    await checkpointer.setup()
    print("LangGraph Checkpoint tables verified/created!")

    await tasker.start()
    logger.info("\n%s", get_yunesa_banner())
    logger.info("AgenticRAG backend startup complete")
    yield
    await tasker.shutdown()
    if sandbox_enabled:
        shutdown_sandbox_provider()
    await close_queue_clients()
    await pg_manager.close()
