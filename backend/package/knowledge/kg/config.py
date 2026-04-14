import os
import logging
from pathlib import Path
from knowledge.utils.config_manager import load_config

logger = logging.getLogger(__name__)

# --- Load Configs ---
config = load_config("kg")
db_config = load_config("database")

# --- Base Directory Setup ---
current_dir = Path(__file__).resolve().parent
BASE_DIR = current_dir.parents[2] # Fallback to /app or /app/package
while current_dir != current_dir.parent:
    if (current_dir / "configs").is_dir():
        BASE_DIR = current_dir
        break
    current_dir = current_dir.parent

# Universal DATA_DIR handling (Level 3 optimization)
if os.environ.get("RUNNING_IN_DOCKER") == "true" or os.environ.get("AIRFLOW_CONFIG") or Path("/app/data").exists():
    DATA_DIR = Path(os.environ.get("KG_DATA_DIR", "/app/data"))
else:
    DATA_DIR = BASE_DIR / "data"

KG_ARTIFACTS_DIR = DATA_DIR / "kg_artifacts"
KG_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# --- Aliases (Backward Compatibility) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

NEO4J_URI = os.environ.get(
    "NEO4J_URI", db_config.neo4j.uri or f"bolt://ta-neo4j:{db_config.neo4j.default_port}")
NEO4J_USER = os.environ.get("NEO4J_USER", db_config.neo4j.user)
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", db_config.neo4j.password)
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", db_config.neo4j.default_db)

MILVUS_HOST = os.environ.get(
    "MILVUS_HOST", db_config.milvus.default_host or "milvus-standalone")
MILVUS_PORT = int(os.environ.get(
    "MILVUS_PORT", db_config.milvus.default_port or 19530))

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
LLM_MODEL = os.environ.get("LLM_MODEL", config.llm.model)

GLINER_MODEL_NAME = os.environ.get(
    "GLINER_MODEL_NAME", config.extraction.gliner_model)
GLINER_THRESHOLD = float(os.environ.get(
    "GLINER_THRESHOLD", config.extraction.gliner_threshold))
SPACY_MODEL_NAME = config.extraction.spacy_model

MAX_PAPERS = int(os.environ.get(
    "KG_MAX_PAPERS", config.pipeline.max_papers_per_run))
LLM_BATCH_SIZE = int(os.environ.get(
    "KG_LLM_BATCH_SIZE", config.llm.batch_size))

# --- Airflow UI Variables (Highest Priority) ---
try:
    from airflow.models import Variable

    def _av(name, fallback):
        v = Variable.get(name, default_var=None)
        return v if v is not None else fallback

    SUPABASE_URL = _av("SUPABASE_URL", SUPABASE_URL)
    SUPABASE_KEY = _av("SUPABASE_KEY", SUPABASE_KEY)
    GROQ_API_KEY = _av("GROQ_API_KEY", GROQ_API_KEY)
    NEO4J_URI = _av("NEO4J_URI", NEO4J_URI)
    NEO4J_PASSWORD = _av("NEO4J_PASSWORD", NEO4J_PASSWORD)
except ImportError:
    pass

# --- Diagnostics ---
if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("⚠️ KG Config: SUPABASE_URL or SUPABASE_KEY is missing.")
if not GROQ_API_KEY:
    logger.warning("⚠️ KG Config: GROQ_API_KEY is missing.")
else:
    logger.info(f"✅ KG Config loaded (Neo4j: {NEO4J_URI}, Model: {LLM_MODEL})")
