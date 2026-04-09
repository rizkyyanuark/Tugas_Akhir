from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from ta_backend_core.assistant.services.task_service import tasker
from ta_backend_core.assistant.services.mcp_service import ensure_builtin_mcp_servers_in_db
from ta_backend_core.assistant.services.subagent_service import init_builtin_subagents
from ta_backend_core.assistant.services.run_queue_service import close_queue_clients, get_redis_client
from ta_backend_core.assistant.storage.postgres.manager import pg_manager
from ta_backend_core.assistant.knowledge import knowledge_base
from ta_backend_core.assistant.utils import logger
from ta_backend_core.assistant.agents.backends.sandbox import init_sandbox_provider, shutdown_sandbox_provider
from ta_backend_core.assistant import get_version


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan事件管理器"""
    # 初始化数据库连接
    try:
        pg_manager.initialize()
        await pg_manager.create_business_tables()
        await pg_manager.ensure_business_schema()
        await pg_manager.ensure_knowledge_schema()
    except Exception as e:
        logger.error(f"Failed to initialize database during startup: {e}")

    # 确保内置 MCP 服务器定义存在于数据库
    try:
        await ensure_builtin_mcp_servers_in_db()
    except Exception as e:
        logger.error(f"Failed to ensure builtin MCP servers during startup: {e}")

    # 初始化内置 SubAgent
    try:
        await init_builtin_subagents()
    except Exception as e:
        logger.error(f"Failed to initialize builtin subagents during startup: {e}")
        raise

    # 初始化知识库管理器
    import os
    if os.environ.get("LITE_MODE", "").lower() in ("true", "1"):
        logger.info("LITE_MODE enabled, skipping knowledge base initialization")
    else:
        try:
            await knowledge_base.initialize()
        except Exception as e:
            logger.error(f"Failed to initialize knowledge base manager: {e}")

    # 预热 Redis（run 队列）
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
    # 2. 核心修复：在这里执行一次 setup()，建完表就拉倒
    # =========================================================
    checkpointer = AsyncPostgresSaver(pg_manager.langgraph_pool)
    await checkpointer.setup()
    print("LangGraph Checkpoint tables verified/created!")

    # =========================================================
    # 3. Strwythura NLP Pre-loading
    # =========================================================
    logger.info("🔄 Pre-loading Strwythura NLP models (SpaCy & GLiNER)...")
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
        app.state.spacy_model = nlp
        logger.info("✅ SpaCy model loaded.")
    except Exception as e:
        logger.warning(f"⚠️ SpaCy model not available: {e}")

    try:
        from ta_backend_core.knowledge.kg.models.gliner_model import GLiNER
        gliner_model = GLiNER.from_pretrained(
            os.environ.get("GLINER_MODEL_NAME", "urchade/gliner_small-v2.1"),
            load_tokenizer=True
        )
        app.state.gliner_model = gliner_model
        logger.info("✅ GLiNER model loaded.")
    except Exception as e:
        logger.warning(f"⚠️ GLiNER model not available: {e}")

    await tasker.start()
    logger.info(f"""

░██     ░██                       ░██
 ░██   ░██
  ░██ ░██   ░██    ░██ ░██    ░██ ░██
   ░████    ░██    ░██  ░██  ░██  ░██
    ░██     ░██    ░██   ░█████   ░██
    ░██     ░██   ░███  ░██  ░██  ░██
    ░██      ░█████░██ ░██    ░██ ░██  v{get_version()}

    """)
    logger.info("Yuxi backend startup complete")
    yield
    await tasker.shutdown()
    shutdown_sandbox_provider()
    await close_queue_clients()
    await pg_manager.close()
