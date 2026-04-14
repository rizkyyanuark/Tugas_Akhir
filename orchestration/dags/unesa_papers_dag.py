"""
Airflow DAG: UNESA Papers ETL Pipeline (Level 3 Architecture)
===============================================================
PURE ORCHESTRATOR — All heavy work delegated to etl-worker containers.

Tasks (via DockerOperator):
  1. extract_scopus  → Scrape papers from Scopus via Selenium
  2. extract_scholar → Scrape papers from Google Scholar via SerpAPI
  3. transform       → Normalize, deduplicate, and enrich with AI embeddings
  4. load            → UPSERT to Supabase PostgreSQL
  5. notify          → Email notification on completion

Schedule: Daily at 03:00 WIB (20:00 UTC previous day)

Maintenance Guide:
    ┌─────────────────────────────────────────────────────────────────┐
    │  To add a new Airflow Variable for the worker:                  │
    │  1. Create it in Airflow UI → Admin → Variables                 │
    │  2. Add it to _worker_env() below                               │
    │  3. Reference it in config.py via os.environ.get()              │
    └─────────────────────────────────────────────────────────────────┘
"""

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.models import Variable
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount


# ─── Constants ──────────────────────────────────────────────────

ETL_WORKER_IMAGE = "rizyyk/unesa-etl:v2"
DOCKER_NETWORK = "yuxi-know_app-network"
DATA_VOLUME = "tugas_akhir_etl_data"


def _get_var(key: str, default: str = "") -> str:
    """Fetch from Airflow Variable first, then fall back to OS env."""
    return Variable.get(key, default_var=os.environ.get(key, default))


def _worker_env() -> dict[str, str]:
    """
    Build the complete environment dict for ETL Worker containers.

    Every key that config.py reads via os.environ.get() must be listed here.
    This is the ONLY bridge between Airflow secrets and the worker container.
    """
    return {
        # ── Core Infrastructure ──
        "SUPABASE_URL":       _get_var("SUPABASE_URL"),
        "SUPABASE_KEY":       _get_var("SUPABASE_KEY"),

        # ── SciVal / Scopus (Elsevier) ──
        "SCIVAL_EMAIL":       _get_var("SCIVAL_EMAIL"),
        "SCIVAL_PASS":        _get_var("SCIVAL_PASS"),

        # ── Google Scholar (SerpAPI) ──
        "SERPAPI_KEY":        _get_var("SERPAPI_KEY"),

        # ── BrightData Proxy ──
        "BRIGHT_DATA_HOST":   _get_var("BRIGHT_DATA_HOST", "brd.superproxy.io:33335"),
        "BD_USER_UNLOCKER":   _get_var("BD_USER_UNLOCKER"),
        "BD_PASS_UNLOCKER":   _get_var("BD_PASS_UNLOCKER"),
        "BD_USER_SERP":       _get_var("BD_USER_SERP"),
        "BD_PASS_SERP":       _get_var("BD_PASS_SERP"),
        "GROQ_API_KEY":       _get_var("GROQ_API_KEY"),
        "NOTIFICATION_EMAIL": _get_var("NOTIFICATION_EMAIL"),
    }


# ─── DAG Configuration ──────────────────────────────────────────

default_args = {
    "owner": "rizky",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="unesa_papers_etl",
    default_args=default_args,
    description="ETL Pipeline: Academic Papers → Supabase (Level 3 DockerOperator)",
    schedule_interval="0 20 * * *",  # 03:00 WIB = 20:00 UTC
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["papers", "daily", "scopus", "scholar", "unesa", "level3"],
    max_active_runs=1,
)


# ─── Shared DockerOperator Config ────────────────────────────────

docker_defaults = {
    "image": ETL_WORKER_IMAGE,
    "docker_url": "unix://var/run/docker.sock",
    "network_mode": DOCKER_NETWORK,
    "auto_remove": "success",
    "mount_tmp_dir": False,
    "mounts": [
        Mount(source=DATA_VOLUME, target="/app/data", type="volume"),
    ],
    "dag": dag,
}


# ─── Task Definitions ───────────────────────────────────────────

extract_scopus = DockerOperator(
    task_id="extract_scopus",
    command="paper_extract_scopus",
    environment=_worker_env(),
    **docker_defaults,
)

extract_scholar = DockerOperator(
    task_id="extract_scholar",
    command="paper_extract_scholar",
    environment=_worker_env(),
    **docker_defaults,
)

transform_task = DockerOperator(
    task_id="transform",
    command="paper_transform",
    environment=_worker_env(),
    **docker_defaults,
)

load_task = DockerOperator(
    task_id="load",
    command="paper_load",
    environment=_worker_env(),
    **docker_defaults,
)

notify_task = DockerOperator(
    task_id="notify",
    command="paper_notify",
    environment=_worker_env(),
    **docker_defaults,
)


# ─── DAG Pipeline Flow ──────────────────────────────────────────
# Step 1: Parallel extraction from two sources
[extract_scopus, extract_scholar] >> transform_task

# Step 2 → 4: Sequential post-processing
transform_task >> load_task >> notify_task
