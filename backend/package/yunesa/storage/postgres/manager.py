"""PostgreSQL database manager - supports knowledge base and business data."""

import json
import os
from contextlib import asynccontextmanager

from psycopg_pool import AsyncConnectionPool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from yunesa.storage.postgres.models_business import Base as BusinessBase
from yunesa.storage.postgres.models_knowledge import Base as KnowledgeBase
from yunesa.utils import logger

from server.utils.singleton import SingletonMeta

# Merge two Base registries.
CombinedBase = declarative_base()

# Inherit all tables.
for module in [KnowledgeBase, BusinessBase]:
    for table_name in dir(module):
        table = getattr(module, table_name)
        if isinstance(table, type) and hasattr(table, "__tablename__"):
            setattr(CombinedBase, table_name, table)


class PostgresManager(metaclass=SingletonMeta):
    """PostgreSQL database manager - supports knowledge base and business data."""

    # Environment variable name for knowledge base PostgreSQL URL.
    KB_DATABASE_URL_ENV = "POSTGRES_URL"

    def __init__(self):
        self.async_engine = None
        self.AsyncSession = None
        self.langgraph_pool = None
        self._initialized = False

    def initialize(self):
        """initializedatabaseconnect"""
        if self._initialized:
            return

        db_url = os.getenv(self.KB_DATABASE_URL_ENV)
        if not db_url:
            logger.error(
                f"Environment variable {self.KB_DATABASE_URL_ENV} is not set; "
                "please configure the PostgreSQL connection string in docker-compose.yml or .env"
            )
            return

        try:
            # Create async SQLAlchemy engine.
            self.async_engine = create_async_engine(
                db_url,
                json_serializer=lambda obj: json.dumps(
                    obj, ensure_ascii=False),
                json_deserializer=json.loads,
                pool_pre_ping=True,
                pool_recycle=1800,
            )

            # Create async session factory.
            self.AsyncSession = async_sessionmaker(
                bind=self.async_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            # ==========================================
            # 2. Initialize a dedicated native psycopg_pool for LangGraph
            # ==========================================
            # NOTE: psycopg does not recognize SQLAlchemy dialect suffixes such as "+asyncpg".
            # If db_url is "postgresql+asyncpg://user:pwd@host/db",
            # convert it to standard "postgresql://user:pwd@host/db".
            langgraph_db_url = db_url.replace(
                "+asyncpg", "").replace("+psycopg", "")

            # Create dedicated LangGraph connection pool.
            self.langgraph_pool = AsyncConnectionPool(
                conninfo=langgraph_db_url,
                # Tune based on agent concurrency; usually 5-10 is enough.
                max_size=10,
                # LangGraph checkpoint strongly depends on autocommit.
                kwargs={"autocommit": True},
            )

            self._initialized = True
            logger.info(
                f"PostgreSQL manager initialized for knowledge base: {db_url.split('@')[0]}://***")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL manager: {e}")
            # Do not raise exception here: allow app startup and fail when DB is actually used.

    def _check_initialized(self):
        """Check whether manager is initialized."""
        if not self._initialized:
            raise RuntimeError(
                "PostgreSQL manager not initialized. Please check configuration.")

    async def create_tables(self):
        """Create all tables (knowledge base + business)."""
        self._check_initialized()
        async with self.async_engine.begin() as conn:
            await conn.run_sync(KnowledgeBase.metadata.create_all)
            await conn.run_sync(BusinessBase.metadata.create_all)
        logger.info("PostgreSQL tables created/checked (knowledge + business)")

    async def create_business_tables(self):
        """Create all business-data tables."""
        self._check_initialized()
        async with self.async_engine.begin() as conn:
            await conn.run_sync(BusinessBase.metadata.create_all)
        logger.info("PostgreSQL business tables created/checked")

    async def drop_tables(self):
        """Drop all tables (use with caution!)."""
        self._check_initialized()
        async with self.async_engine.begin() as conn:
            await conn.run_sync(BusinessBase.metadata.drop_all)
            await conn.run_sync(KnowledgeBase.metadata.drop_all)
        logger.info("PostgreSQL tables dropped")

    async def ensure_knowledge_schema(self):
        """Ensure knowledge base schema includes all required columns."""
        self._check_initialized()
        stmts = [
            "ALTER TABLE IF EXISTS knowledge_bases ADD COLUMN IF NOT EXISTS embed_info JSONB",
            "ALTER TABLE IF EXISTS knowledge_bases ADD COLUMN IF NOT EXISTS llm_info JSONB",
            "ALTER TABLE IF EXISTS knowledge_bases ADD COLUMN IF NOT EXISTS query_params JSONB",
            "ALTER TABLE IF EXISTS knowledge_bases ADD COLUMN IF NOT EXISTS additional_params JSONB",
            "ALTER TABLE IF EXISTS knowledge_bases ADD COLUMN IF NOT EXISTS share_config JSONB",
            "ALTER TABLE IF EXISTS knowledge_bases ADD COLUMN IF NOT EXISTS mindmap JSONB",
            "ALTER TABLE IF EXISTS knowledge_bases ADD COLUMN IF NOT EXISTS sample_questions JSONB",
            "ALTER TABLE IF EXISTS knowledge_bases ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS parent_id VARCHAR(64)",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS original_filename VARCHAR(512)",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS file_type VARCHAR(64)",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS path VARCHAR(1024)",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS minio_url VARCHAR(1024)",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS markdown_file VARCHAR(1024)",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS status VARCHAR(32)",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS content_hash VARCHAR(128)",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS file_size BIGINT",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS content_type VARCHAR(64)",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS processing_params JSONB",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS is_folder BOOLEAN",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS error_message TEXT",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS created_by VARCHAR(64)",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS updated_by VARCHAR(64)",
            "ALTER TABLE IF EXISTS knowledge_files ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ",
            "ALTER TABLE IF EXISTS evaluation_benchmarks ADD COLUMN IF NOT EXISTS data_file_path VARCHAR(1024)",
            "ALTER TABLE IF EXISTS evaluation_benchmarks ADD COLUMN IF NOT EXISTS created_by VARCHAR(64)",
            "ALTER TABLE IF EXISTS evaluation_benchmarks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ",
            "ALTER TABLE IF EXISTS evaluation_results ADD COLUMN IF NOT EXISTS metrics JSONB",
            "ALTER TABLE IF EXISTS evaluation_results ADD COLUMN IF NOT EXISTS overall_score DOUBLE PRECISION",
            "ALTER TABLE IF EXISTS evaluation_results ADD COLUMN IF NOT EXISTS total_questions INTEGER",
            "ALTER TABLE IF EXISTS evaluation_results ADD COLUMN IF NOT EXISTS completed_questions INTEGER",
            "ALTER TABLE IF EXISTS evaluation_results ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ",
            "ALTER TABLE IF EXISTS evaluation_results ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
            "ALTER TABLE IF EXISTS evaluation_results ADD COLUMN IF NOT EXISTS created_by VARCHAR(64)",
            "ALTER TABLE IF EXISTS evaluation_result_details ADD COLUMN IF NOT EXISTS gold_chunk_ids JSONB",
            "ALTER TABLE IF EXISTS evaluation_result_details ADD COLUMN IF NOT EXISTS gold_answer TEXT",
            "ALTER TABLE IF EXISTS evaluation_result_details ADD COLUMN IF NOT EXISTS generated_answer TEXT",
            "ALTER TABLE IF EXISTS evaluation_result_details ADD COLUMN IF NOT EXISTS retrieved_chunks JSONB",
            "ALTER TABLE IF EXISTS evaluation_result_details ADD COLUMN IF NOT EXISTS metrics JSONB",
            # Extend db_id length to support IDs up to 75 chars (kb_private_ + 64-char hash).
            "ALTER TABLE IF EXISTS knowledge_bases ALTER COLUMN db_id TYPE VARCHAR(80)",
            "ALTER TABLE IF EXISTS knowledge_files ALTER COLUMN db_id TYPE VARCHAR(80)",
            "ALTER TABLE IF EXISTS evaluation_benchmarks ALTER COLUMN db_id TYPE VARCHAR(80)",
            "ALTER TABLE IF EXISTS evaluation_results ALTER COLUMN db_id TYPE VARCHAR(80)",
            "CREATE INDEX IF NOT EXISTS idx_kb_type ON knowledge_bases(kb_type)",
            "CREATE INDEX IF NOT EXISTS idx_kb_name ON knowledge_bases(name)",
            "CREATE INDEX IF NOT EXISTS idx_kf_db_id ON knowledge_files(db_id)",
            "CREATE INDEX IF NOT EXISTS idx_kf_parent ON knowledge_files(parent_id)",
            "CREATE INDEX IF NOT EXISTS idx_kf_status ON knowledge_files(status)",
            "CREATE INDEX IF NOT EXISTS idx_kf_hash ON knowledge_files(content_hash)",
            "CREATE INDEX IF NOT EXISTS idx_eb_db_id ON evaluation_benchmarks(db_id)",
            "CREATE INDEX IF NOT EXISTS idx_er_db_id ON evaluation_results(db_id)",
            "CREATE INDEX IF NOT EXISTS idx_er_status ON evaluation_results(status)",
            "CREATE INDEX IF NOT EXISTS idx_er_started ON evaluation_results(started_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_erd_task ON evaluation_result_details(task_id)",
        ]

        async with self.async_engine.begin() as conn:
            for stmt in stmts:
                await conn.execute(text(stmt))

    async def ensure_business_schema(self):
        """Ensure business schema includes newly added fields (compatible with existing tables)."""
        self._check_initialized()
        stmts = [
            "ALTER TABLE IF EXISTS skills ADD COLUMN IF NOT EXISTS tool_dependencies JSONB DEFAULT '[]'::jsonb",
            "ALTER TABLE IF EXISTS skills ADD COLUMN IF NOT EXISTS mcp_dependencies JSONB DEFAULT '[]'::jsonb",
            "ALTER TABLE IF EXISTS skills ADD COLUMN IF NOT EXISTS skill_dependencies JSONB DEFAULT '[]'::jsonb",
            "ALTER TABLE IF EXISTS skills ADD COLUMN IF NOT EXISTS version VARCHAR(64)",
            "ALTER TABLE IF EXISTS skills ADD COLUMN IF NOT EXISTS is_builtin BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE IF EXISTS skills ADD COLUMN IF NOT EXISTS content_hash VARCHAR(128)",
            "ALTER TABLE IF EXISTS subagents ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE IF EXISTS conversations ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE IF EXISTS mcp_servers ADD COLUMN IF NOT EXISTS env JSONB",
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                id VARCHAR(64) PRIMARY KEY,
                thread_id VARCHAR(64) NOT NULL,
                agent_id VARCHAR(64) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                request_id VARCHAR(64) NOT NULL UNIQUE,
                input_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                error_type VARCHAR(64),
                error_message TEXT,
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_agent_runs_user_created ON agent_runs(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_agent_runs_thread_created ON agent_runs(thread_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_agent_runs_status_updated ON agent_runs(status, updated_at)",
            "CREATE INDEX IF NOT EXISTS ix_conversations_is_pinned ON conversations(is_pinned)",
        ]
        async with self.async_engine.begin() as conn:
            for stmt in stmts:
                await conn.execute(text(stmt))

    @property
    def is_postgresql(self) -> bool:
        """Check whether current engine is PostgreSQL."""
        if not self._initialized:
            return False
        return self.async_engine.dialect.name == "postgresql"

    async def get_async_session(self) -> AsyncSession:
        """Get asynchronous database session."""
        self._check_initialized()
        return self.AsyncSession()

    @asynccontextmanager
    async def get_async_session_context(self):
        """Context manager for asynchronous database sessions."""
        self._check_initialized()
        session = self.AsyncSession()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"PostgreSQL async operation failed: {e}")
            raise
        finally:
            await session.close()

    async def close(self):
        """Dispose engine and close pools."""
        if self.async_engine:
            await self.async_engine.dispose()

        if self.langgraph_pool:
            await self.langgraph_pool.close()

    async def async_check_first_run(self):
        """Check first run (async): verify whether users table contains data."""
        from sqlalchemy import func, select

        self._check_initialized()
        async with self.get_async_session_context() as session:
            from yunesa.storage.postgres.models_business import User

            result = await session.execute(select(func.count(User.id)))
            count = result.scalar()
            return count == 0

    async def execute(self, statement):
        """Execute SQL statement directly (for migration scripts)."""
        self._check_initialized()
        async with self.get_async_session_context() as session:
            return await session.execute(statement)

    async def add(self, instance):
        """Add instance to session (for migration scripts)."""
        self._check_initialized()
        async with self.get_async_session_context() as session:
            session.add(instance)

    async def commit(self):
        """Commit current session."""
        self._check_initialized()
        async with self.get_async_session_context():
            pass  # commit is automatic in context manager


# Create global PostgreSQL manager instance.
pg_manager = PostgresManager()
