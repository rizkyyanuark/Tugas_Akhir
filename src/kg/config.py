"""
Config: KG Pipeline Configuration
==================================
Centralised configuration for the Knowledge Graph construction pipeline.
Follows the same 3-layer priority cascade as src/etl/config.py:
  Layer 1: .env file              ← Lowest priority
  Layer 2: credentials_new.json   ← Fills gaps only
  Layer 3: Airflow UI Variables   ← HIGHEST priority (always wins)
"""

import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── Base Directory Setup ──
# Resolves to project root: Tugas_Akhir/
BASE_DIR = Path(__file__).resolve().parent.parent.parent
dotenv_path = BASE_DIR / ".env"
load_dotenv(dotenv_path)

# ── Data Directories ──
DATA_DIR = BASE_DIR / "data"
KG_ARTIFACTS_DIR = DATA_DIR / "kg_artifacts"
KG_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# LAYER 1: OS Environment Variables (.env file)
# ══════════════════════════════════════════════════════════════

# Supabase (Source of Truth)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Neo4j (Graph Database)
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "rizkyyk123")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "Infokom_unesa")

# Weaviate (Vector Database)
WEAVIATE_HOST = os.environ.get("WEAVIATE_HOST", "localhost")
WEAVIATE_PORT = int(os.environ.get("WEAVIATE_PORT", "8081"))

# Groq LLM
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")

# NER Configuration
# We use gliner_large-v2.1 which is highly robust for English NER tasks like those found in English TLDRs
GLINER_MODEL_NAME = os.environ.get("GLINER_MODEL_NAME", "urchade/gliner_large-v2.1")
GLINER_THRESHOLD = float(os.environ.get("GLINER_THRESHOLD", "0.15"))
SPACY_MODEL_NAME = "en_core_web_sm"

# Pipeline Defaults
MAX_PAPERS = int(os.environ.get("KG_MAX_PAPERS", "500"))
LLM_BATCH_SIZE = int(os.environ.get("KG_LLM_BATCH_SIZE", "80"))

# ══════════════════════════════════════════════════════════════
# LAYER 2: credentials_new.json fallback (fills MISSING only)
# ══════════════════════════════════════════════════════════════
try:
    creds_path = BASE_DIR / "notebooks" / "scraping" / "credentials_new.json"
    if creds_path.exists():
        with open(creds_path, "r") as f:
            creds = json.load(f)
        if not SUPABASE_URL:
            SUPABASE_URL = creds.get("supabase", {}).get("url") or creds.get("SUPABASE_URL")
        if not SUPABASE_KEY:
            SUPABASE_KEY = creds.get("supabase", {}).get("key") or creds.get("SUPABASE_KEY")
except Exception as e:
    logger.warning(f"Warning loading credentials JSON: {e}")

# ══════════════════════════════════════════════════════════════
# LAYER 3: Airflow UI Variables (HIGHEST PRIORITY)
# ══════════════════════════════════════════════════════════════
try:
    from airflow.models import Variable

    def _av(name, fallback):
        v = Variable.get(name, default_var=None)
        return v if v is not None else fallback

    SUPABASE_URL = _av("SUPABASE_URL", SUPABASE_URL)
    SUPABASE_KEY = _av("SUPABASE_KEY", SUPABASE_KEY)
    GROQ_API_KEY = _av("GROQ_API_KEY", GROQ_API_KEY)
    NEO4J_URI = _av("NEO4J_URI", NEO4J_URI)
    NEO4J_USER = _av("NEO4J_USER", NEO4J_USER)
    NEO4J_PASSWORD = _av("NEO4J_PASSWORD", NEO4J_PASSWORD)
    NEO4J_DATABASE = _av("NEO4J_DATABASE", NEO4J_DATABASE)
except ImportError:
    pass  # Not running in Airflow environment

# ── Diagnostics ──
if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("⚠️ KG Config: SUPABASE_URL or SUPABASE_KEY is missing.")
if not GROQ_API_KEY:
    logger.warning("⚠️ KG Config: GROQ_API_KEY is missing. LLM curation will fail.")
else:
    logger.info(f"✅ KG Config loaded (Neo4j: {NEO4J_URI}, DB: {NEO4J_DATABASE}, Weaviate: {WEAVIATE_HOST}:{WEAVIATE_PORT})")
