"""
ETL Configuration Module
========================
Loads settings from YAML configs, environment variables, and optionally
Airflow Variables (when running inside Airflow).

Level 3 Architecture Compatible:
  - When run inside Airflow scheduler: reads Airflow Variables as overrides
  - When run inside standalone ETL Worker container: uses pure os.environ
    (Airflow is NOT installed in the worker, so ImportError is expected)
"""
import os
import logging
from pathlib import Path
from knowledge.utils.config_manager import load_config

logger = logging.getLogger(__name__)

# --- Load Configs ---
config = load_config("etl")
db_config = load_config("database")

# --- Base Dirs ---
current_dir = Path(__file__).resolve().parent
BASE_DIR = current_dir.parents[2] # Fallback to /app or /app/package
while current_dir != current_dir.parent:
    if (current_dir / "configs").is_dir():
        BASE_DIR = current_dir
        break
    current_dir = current_dir.parent

# In Level 3 (Docker), we use the /app/data persistent volume
# Logic: If running in docker/airflow, force /app/data, otherwise fallback to local
if os.environ.get("RUNNING_IN_DOCKER") == "true" or os.environ.get("AIRFLOW_CONFIG") or Path("/app/data").exists():
    DATA_DIR = Path(os.environ.get("ETL_DATA_DIR", "/app/data"))
else:
    DATA_DIR = Path(os.environ.get("ETL_DATA_DIR", BASE_DIR / "data"))

RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- Credentials (Priority: ENV > YAML > None) ---
# BUG FIX: Previously SUPABASE_KEY was fetching "SUPABASE_URL" — corrected.
SUPABASE_URL = os.environ.get("SUPABASE_URL", config.supabase.url)
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")  # Secret — env only

# Scraping credentials
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
BD_PASS_SERP = os.environ.get("BD_PASS_SERP")
SCIVAL_EMAIL = os.environ.get("SCIVAL_EMAIL", config.scival.email)
SCIVAL_PASS = os.environ.get("SCIVAL_PASS")

# Database credentials
NEO4J_URI = os.environ.get(
    "NEO4J_URI", db_config.neo4j.uri or f"bolt://localhost:{db_config.neo4j.default_port}")
NEO4J_USER = os.environ.get("NEO4J_USER", db_config.neo4j.user)
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", db_config.neo4j.password)

# --- Airflow UI Variables (Optional Override — only when running inside Airflow) ---
# In Level 3 architecture, the ETL Worker container does NOT have Airflow installed.
# This block will be silently skipped via ImportError, which is expected behavior.
try:
    from airflow.models import Variable

    def _av(name, fallback):
        v = Variable.get(name, default_var=None)
        return v if v is not None else fallback

    SUPABASE_URL = _av('SUPABASE_URL', SUPABASE_URL)
    SUPABASE_KEY = _av('SUPABASE_KEY', SUPABASE_KEY)
    SERPAPI_KEY = _av('SERPAPI_KEY', SERPAPI_KEY)
    NEO4J_URI = _av('NEO4J_URI', NEO4J_URI)
    NEO4J_PASSWORD = _av('NEO4J_PASSWORD', NEO4J_PASSWORD)
except ImportError:
    # Expected when running in standalone ETL Worker (Level 3)
    logger.debug("Airflow not installed — using pure environment variables.")

# --- Diagnostics ---
if not SUPABASE_URL:
    logger.warning("⚠️ ETL Config: SUPABASE_URL is missing.")
else:
    logger.info(f"✅ ETL Config: Loaded (Supabase: {SUPABASE_URL})")
