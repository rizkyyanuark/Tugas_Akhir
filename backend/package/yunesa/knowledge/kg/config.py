"""
KG Pipeline Configuration
==========================
Reads all configuration from environment variables, with sensible defaults
matching the original kg.yaml / database.yaml values.

This replaces the old ConfigManager-based approach so the module is
self-contained within the yunesa namespace and has no dependency on
the top-level ``knowledge.utils`` package.
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Base Directory Setup ---
# KG artifacts directory for intermediate pipeline outputs
KG_ARTIFACTS_DIR = Path(os.environ.get("KG_ARTIFACTS_DIR", "/tmp/kg_artifacts"))
KG_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# --- Supabase (data source) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# --- Neo4j ---
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://ta-neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "71509325")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "infokom-unesa")

# --- Milvus ---
MILVUS_HOST = os.environ.get("MILVUS_HOST", "milvus-standalone")
MILVUS_PORT = int(os.environ.get("MILVUS_PORT", "19530"))

# --- LLM (Groq & SiliconFlow) ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY")

# Default LLM settings (Northern Standard: Prefer SiliconFlow if available)
if SILICONFLOW_API_KEY:
    LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-ai/DeepSeek-V3") # SiliconFlow High Performance
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
else:
    LLM_MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")

SILICONFLOW_EMBED_MODEL = os.environ.get("SILICONFLOW_EMBED_MODEL", "BAAI/bge-m3")

# --- NER / Extraction ---
# Using 'tiny' for maximum performance in containerized environment (Northern Standard)
GLINER_MODEL_NAME = os.environ.get("GLINER_MODEL_NAME", "urchade/gliner_tiny_parallel-v2")
GLINER_THRESHOLD = float(os.environ.get("GLINER_THRESHOLD", "0.25"))
SPACY_MODEL_NAME = os.environ.get("SPACY_MODEL_NAME", "en_core_web_sm")

# --- Pipeline Tuning ---
MAX_PAPERS = int(os.environ.get("KG_MAX_PAPERS", "500"))
LLM_BATCH_SIZE = int(os.environ.get("KG_LLM_BATCH_SIZE", "80"))

# --- Diagnostics ---
if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("⚠️ KG Config: SUPABASE_URL or SUPABASE_KEY is missing.")
if not GROQ_API_KEY:
    logger.warning("⚠️ KG Config: GROQ_API_KEY is missing.")
if not SILICONFLOW_API_KEY:
    logger.warning("⚠️ KG Config: SILICONFLOW_API_KEY is missing. 'Northern Standard' embeddings will fail.")
else:
    logger.info(f"✅ KG Config: Northern Standard Ready (Embedder: SiliconFlow, Model: {SILICONFLOW_EMBED_MODEL})")
