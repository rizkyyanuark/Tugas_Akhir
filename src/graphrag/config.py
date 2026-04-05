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
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── Base Directory ──
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

# ── Data Paths ──
DATA_DIR = BASE_DIR / "data"
KG_ARTIFACTS_DIR = DATA_DIR / "kg_artifacts"
TEXT_CHUNKS_PATH = KG_ARTIFACTS_DIR / "text_chunks.json"

# ── Neo4j (reuse from kg config) ──
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "infokom-unesa")

# ── Weaviate ──
WEAVIATE_HOST = os.environ.get("WEAVIATE_HOST", "weaviate")
WEAVIATE_PORT = int(os.environ.get("WEAVIATE_PORT", "8080"))

# ── OpenRouter LLM ──
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "qwen/qwen3.6-plus:free")

# ── Opik Observability ──
OPIK_URL = os.environ.get("OPIK_URL", "http://opik-backend:8080")
OPIK_WORKSPACE = os.environ.get("OPIK_WORKSPACE", "default")
OPIK_PROJECT = os.environ.get("OPIK_PROJECT", "academic-graphrag")

# ── Retrieval Hyperparameters ──
KEYWORD_TOP_K = int(os.environ.get("GRAPHRAG_KEYWORD_TOP_K", "10"))
ENTITY_TOP_K = int(os.environ.get("GRAPHRAG_ENTITY_TOP_K", "20"))
RELATIONSHIP_TOP_K = int(os.environ.get("GRAPHRAG_REL_TOP_K", "30"))
CHUNK_TOP_K = int(os.environ.get("GRAPHRAG_CHUNK_TOP_K", "10"))
BFS_MAX_DEPTH = int(os.environ.get("GRAPHRAG_BFS_MAX_DEPTH", "3"))

# ── Generation ──
LLM_MAX_TOKENS = int(os.environ.get("GRAPHRAG_LLM_MAX_TOKENS", "4096"))
LLM_TEMPERATURE = float(os.environ.get("GRAPHRAG_LLM_TEMPERATURE", "0.7"))

# ── Airflow override layer ──
try:
    from airflow.models import Variable

    def _av(name, fallback):
        v = Variable.get(name, default_var=None)
        return v if v is not None else fallback

    OPENROUTER_API_KEY = _av("OPENROUTER_API_KEY", OPENROUTER_API_KEY)
except ImportError:
    pass

# ── Diagnostics ──
if not OPENROUTER_API_KEY:
    logger.warning("⚠️ GraphRAG Config: OPENROUTER_API_KEY is missing.")
else:
    logger.info(
        f"✅ GraphRAG Config loaded (LLM: {OPENROUTER_MODEL}, "
        f"Neo4j: {NEO4J_URI}, Weaviate: {WEAVIATE_HOST}:{WEAVIATE_PORT})"
    )
