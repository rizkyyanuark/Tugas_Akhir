import os
import logging
from pathlib import Path
from knowledge.utils.config_manager import load_config

logger = logging.getLogger(__name__)


def _cfg_value(source, path: str, default=None):
    """Safely read dotted-path config values from ConfigDict/dict objects."""
    current = source
    for key in path.split("."):
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
    return default if current is None else current


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool) -> bool:
    return _as_bool(os.environ.get(name), default)


# --- Load Configs ---
config = load_config("kg")
db_config = load_config("database")

# --- Base Directory Setup ---
current_dir = Path(__file__).resolve().parent
BASE_DIR = current_dir.parents[2]  # Fallback to /app or /app/package
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
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY")

_neo4j_default_port = _cfg_value(db_config, "neo4j.default_port", 7687)
NEO4J_URI = os.environ.get("NEO4J_URI") or _cfg_value(
    db_config, "neo4j.uri", f"bolt://ta-neo4j:{_neo4j_default_port}"
)
NEO4J_USER = (
    os.environ.get("NEO4J_USER")
    or os.environ.get("NEO4J_USERNAME")
    or _cfg_value(db_config, "neo4j.user", "neo4j")
)
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD") or _cfg_value(
    db_config, "neo4j.password", "")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE") or _cfg_value(
    db_config, "neo4j.default_db", "neo4j")

MILVUS_HOST = os.environ.get("MILVUS_HOST") or _cfg_value(
    db_config, "milvus.default_host", "milvus-standalone"
)
MILVUS_PORT = int(os.environ.get("MILVUS_PORT") or _cfg_value(
    db_config, "milvus.default_port", 19530))
ENABLE_MILVUS = _env_bool("KG_ENABLE_MILVUS", True)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
LLM_MODEL = os.environ.get("LLM_MODEL") or _cfg_value(
    config, "llm.model", "llama-3.3-70b-versatile")

GLINER_MODEL_NAME = os.environ.get(
    "GLINER_MODEL_NAME", _cfg_value(config, "extraction.gliner_model", "urchade/gliner_small-v2.1"))
GLINER_THRESHOLD = float(os.environ.get(
    "GLINER_THRESHOLD", _cfg_value(config, "extraction.gliner_threshold", 0.15)))
SPACY_MODEL_NAME = _cfg_value(
    config, "extraction.spacy_model", "en_core_web_sm")

MAX_PAPERS = int(os.environ.get(
    "KG_MAX_PAPERS", _cfg_value(config, "pipeline.max_papers_per_run", 500)))
LLM_BATCH_SIZE = int(os.environ.get(
    "KG_LLM_BATCH_SIZE", _cfg_value(config, "llm.batch_size", 80)))

# --- Airflow UI Variables (Highest Priority) ---
try:
    from airflow.models import Variable

    def _av(name, fallback):
        v = Variable.get(name, default_var=None)
        return v if v is not None else fallback

    SUPABASE_URL = _av("SUPABASE_URL", SUPABASE_URL)
    SUPABASE_KEY = _av("SUPABASE_KEY", _av(
        "SUPABASE_SERVICE_ROLE_KEY", SUPABASE_KEY))
    GROQ_API_KEY = _av("GROQ_API_KEY", GROQ_API_KEY)
    NEO4J_URI = _av("NEO4J_URI", NEO4J_URI)
    NEO4J_USER = _av("NEO4J_USER", _av("NEO4J_USERNAME", NEO4J_USER))
    NEO4J_PASSWORD = _av("NEO4J_PASSWORD", NEO4J_PASSWORD)
    NEO4J_DATABASE = _av("NEO4J_DATABASE", NEO4J_DATABASE)
    ENABLE_MILVUS = _as_bool(
        _av("KG_ENABLE_MILVUS", ENABLE_MILVUS), ENABLE_MILVUS)
except ImportError:
    pass

# --- Diagnostics ---
if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("⚠️ KG Config: SUPABASE_URL or SUPABASE_KEY is missing.")
if not GROQ_API_KEY:
    logger.warning("⚠️ KG Config: GROQ_API_KEY is missing.")
else:
    logger.info(f"✅ KG Config loaded (Neo4j: {NEO4J_URI}, Model: {LLM_MODEL})")

if not ENABLE_MILVUS:
    logger.info(
        "ℹ️ KG Config: Milvus ingestion disabled (KG_ENABLE_MILVUS=false).")
