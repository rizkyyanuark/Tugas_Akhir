"""
ETL Configuration Module - Single Source of Truth
===================================================
All runtime configuration is resolved from ENVIRONMENT VARIABLES.
No YAML files, no config_manager, no Airflow Variables inside here.

Level 3 Architecture:
  Airflow DAG injects all secrets/settings as env vars via DockerOperator.
  The worker container reads them here via os.environ.get().

Maintenance Guide:
  ┌──────────────────────────────────────────────────────────────────────┐
  │  To add a new setting:                                               │
  │  1. Add os.environ.get("MY_KEY", "default") here                     │
  │  2. Map it in _worker_env() in the DAG file                          │
  │  3. Create the Airflow Variable in Admin → Variables                  │
  └──────────────────────────────────────────────────────────────────────┘
"""
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── Base Directories ──────────────────────────────────────────────────
# In Docker: /app/data (persistent volume mounted by Airflow)
# Locally:   <project_root>/data (auto-created)

_is_docker = (
    os.environ.get("DOCKER_ENVIRONMENT") == "true"
    or os.environ.get("RUNNING_IN_DOCKER") == "true"
    or Path("/app/data").exists()
)

if _is_docker:
    DATA_DIR = Path(os.environ.get("ETL_DATA_DIR", "/app/data"))
else:
    # Walk up from this file to find the project root (contains 'backend/')
    _current = Path(__file__).resolve().parent
    _project_root = _current
    while _current != _current.parent:
        if (_current / "backend").is_dir():
            _project_root = _current
            break
        _current = _current.parent
    DATA_DIR = Path(os.environ.get("ETL_DATA_DIR", str(_project_root / "data")))

RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ─── Core Infrastructure ──────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ─── Scraping Credentials ─────────────────────────────────────────────
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
SCIVAL_EMAIL = os.environ.get("SCIVAL_EMAIL", "")
SCIVAL_PASS = os.environ.get("SCIVAL_PASS", "")

# ─── BrightData Proxy ─────────────────────────────────────────────────
BD_USER_SERP = os.environ.get("BD_USER_SERP", "")
BD_PASS_SERP = os.environ.get("BD_PASS_SERP", "")

# Web Unlocker Zone
BD_USER_UNLOCKER = os.environ.get("BD_USER_UNLOCKER", "")
BD_PASS_UNLOCKER = os.environ.get("BD_PASS_UNLOCKER", "")

# Host
BRIGHT_DATA_HOST = os.environ.get("BRIGHT_DATA_HOST", "brd.superproxy.io:33335")

# ─── AI / LLM ─────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# ─── Notification ─────────────────────────────────────────────────────
NOTIFICATION_EMAIL = os.environ.get("NOTIFICATION_EMAIL", "")

# ─── Diagnostics ──────────────────────────────────────────────────────
if not SUPABASE_URL:
    logger.warning("⚠️ ETL Config: SUPABASE_URL is missing.")
else:
    logger.info(f"✅ ETL Config: Loaded (Supabase: {SUPABASE_URL[:30]}...)")
