"""
Airflow DAG: UNESA Lecturers ETL Pipeline (Level 3 Architecture)
=================================================================
PURE ORCHESTRATOR — All heavy work delegated to etl-worker containers.

Tasks (via DockerOperator):
  1. extract_web      → Scrape lecturer data from prodi websites
  2. extract_pddikti  → Fetch lecturer data from PDDIKTI API
  3. merge            → Web-First Smart Merge
  4. enrich           → API Enrichment (SimCV, Sinta, SciVal, Scholar)
  5. transform        → Final Post-Processing
  6. load             → UPSERT to Supabase PostgreSQL

Schedule: Weekly (Sunday 02:00 WIB = Saturday 19:00 UTC)

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
    dag_id="unesa_lecturers_etl",
    default_args=default_args,
    description="ETL Pipeline: V4 Lecturer Profiles → Supabase (Level 3 DockerOperator)",
    schedule_interval="0 19 * * 6",  # Sunday 02:00 WIB = Saturday 19:00 UTC
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["dosen", "weekly", "pddikti", "sinta", "unesa", "level3"],
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

extract_web = DockerOperator(
    task_id="extract_web",
    command="lec_extract_web",
    environment=_worker_env(),
    **docker_defaults,
)

extract_pddikti = DockerOperator(
    task_id="extract_pddikti",
    command="lec_extract_pddikti",
    environment=_worker_env(),
    **docker_defaults,
)

merge_task = DockerOperator(
    task_id="merge",
    command="lec_merge",
    environment=_worker_env(),
    **docker_defaults,
)

enrich_task = DockerOperator(
    task_id="enrich",
    command="lec_enrich --test-mode",
    environment=_worker_env(),
    **docker_defaults,
)

transform_task = DockerOperator(
    task_id="transform",
    command="lec_transform",
    environment=_worker_env(),
    **docker_defaults,
)

load_task = DockerOperator(
    task_id="load",
    command="lec_load",
    environment=_worker_env(),
    **docker_defaults,
)


# ─── DAG Pipeline Flow ──────────────────────────────────────────
# Step 1 & 2: Parallel extraction
[extract_web, extract_pddikti] >> merge_task

# Step 3 → 6: Sequential processing
merge_task >> enrich_task >> transform_task >> load_task
