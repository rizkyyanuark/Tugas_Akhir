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
from yunesa.services.kg_service import get_kg_service
from yunesa import get_version


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
    import os
    if os.environ.get("LITE_MODE", "").lower() in ("true", "1"):
        logger.info("LITE_MODE enabled, skipping knowledge base initialization")
    else:
        try:
            await knowledge_base.initialize()
        except Exception as e:
            logger.error(f"Failed to initialize knowledge base manager: {e}")

    # Warm up Redis (run queue)
    try:
        redis = await get_redis_client()
        await redis.ping()
    except Exception as e:
        logger.warning(f"Run queue redis unavailable on startup: {e}")

    try:
        init_sandbox_provider()
    except Exception as e:
        logger.error(f"Failed to initialize sandbox provider during startup: {e}")

    # =========================================================
    # LangGraph Checkpointer Setup
    # =========================================================
    checkpointer = AsyncPostgresSaver(pg_manager.langgraph_pool)
    await checkpointer.setup()
    print("LangGraph Checkpoint tables verified/created!")

    # Initialize KG Service and attach to app state
    app.state.kg_service = get_kg_service(config)

    await tasker.start()
    logger.info(f"""

░██     ░██
 ░██   ░██
  ░██ ░██   ░██    ░██ ░█████░██  ░█████    ░█████    ░█████
   ░████    ░██    ░██ ░██   ░██ ░██   ░██ ░██             ░██
    ░██     ░██    ░██ ░██   ░██ ░███████   ░█████    ░██████
    ░██     ░██   ░███ ░██   ░██ ░██             ░██ ░██   ░██
    ░██      ░█████░██ ░██   ░██  ░█████   ░█████     ░████░██  v{get_version()}

    """)
    logger.info("AgenticRAG backend startup complete")
    yield
    await tasker.shutdown()
    shutdown_sandbox_provider()
    await close_queue_clients()
    await pg_manager.close()
