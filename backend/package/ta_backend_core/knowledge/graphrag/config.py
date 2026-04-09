"""
GraphRAG Config: Centralised Configuration
============================================
Configuration for the GraphRAG retrieval & generation pipeline.
Extends src/kg/config.py for graph/vector DB connections and adds
OpenRouter LLM + Opik observability settings.
"""

import os
import logging
from pathlib import Path
from ta_backend_core.knowledge.utils.config_manager import load_config

logger = logging.getLogger(__name__)

# --- Load Configs ---
config = load_config("graphrag")
db_config = load_config("database")

# --- Base Directory ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
KG_ARTIFACTS_DIR = DATA_DIR / "kg_artifacts"
TEXT_CHUNKS_PATH = KG_ARTIFACTS_DIR / "text_chunks.json"

# --- Aliases (Backward Compatibility) ---
NEO4J_URI = os.environ.get("NEO4J_URI", db_config.neo4j.uri or f"bolt://localhost:{db_config.neo4j.default_port}")
NEO4J_USER = os.environ.get("NEO4J_USER", db_config.neo4j.user)
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", db_config.neo4j.password)
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", db_config.neo4j.default_db)

MILVUS_HOST = os.environ.get("MILVUS_HOST", db_config.milvus.default_host or "milvus-standalone")
MILVUS_PORT = int(os.environ.get("MILVUS_PORT", db_config.milvus.default_port or 19530))

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", config.llm.openrouter.base_url)
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", config.llm.openrouter.model)

OPIK_URL = os.environ.get("OPIK_URL", config.observability.opik.url)
OPIK_WORKSPACE = os.environ.get("OPIK_WORKSPACE", config.observability.opik.workspace)
OPIK_PROJECT = os.environ.get("OPIK_PROJECT", config.observability.opik.project_name)

KEYWORD_TOP_K = int(os.environ.get("GRAPHRAG_KEYWORD_TOP_K", config.retrieval.keyword_top_k))
ENTITY_TOP_K = int(os.environ.get("GRAPHRAG_ENTITY_TOP_K", config.retrieval.entity_top_k))
RELATIONSHIP_TOP_K = int(os.environ.get("GRAPHRAG_REL_TOP_K", config.retrieval.rel_top_k))
CHUNK_TOP_K = int(os.environ.get("GRAPHRAG_CHUNK_TOP_K", config.retrieval.chunk_top_k))
BFS_MAX_DEPTH = int(os.environ.get("GRAPHRAG_BFS_MAX_DEPTH", config.retrieval.bfs_max_depth))

LLM_MAX_TOKENS = int(os.environ.get("GRAPHRAG_LLM_MAX_TOKENS", config.llm.openrouter.max_tokens))
LLM_TEMPERATURE = float(os.environ.get("GRAPHRAG_LLM_TEMPERATURE", config.llm.openrouter.temperature))

# ── Airflow override layer ──
try:
    from airflow.models import Variable

    def _av(name, fallback):
        v = Variable.get(name, default_var=None)
        return v if v is not None else fallback

    NEO4J_URI = _av("NEO4J_URI", NEO4J_URI)
    NEO4J_PASSWORD = _av("NEO4J_PASSWORD", NEO4J_PASSWORD)
    OPENROUTER_API_KEY = _av("OPENROUTER_API_KEY", OPENROUTER_API_KEY)
except ImportError:
    pass

# ── Diagnostics ──
if not OPENROUTER_API_KEY:
    logger.warning("⚠️ GraphRAG Config: OPENROUTER_API_KEY is missing.")
else:
    logger.info(
        f"✅ GraphRAG Config loaded (LLM: {OPENROUTER_MODEL}, "
        f"Neo4j: {NEO4J_URI}, Milvus: {MILVUS_HOST}:{MILVUS_PORT})"
    )
