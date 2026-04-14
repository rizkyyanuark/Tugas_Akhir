"""
Airflow DAG: UNESA Lecturers ETL Pipeline (Level 3 Architecture)
=================================================================
PURE ORCHESTRATOR — All heavy work delegated to etl-worker containers.
Exactly mirrors 'scraping_dosen_infokom_v4.ipynb' notebook logic.

Tasks (via DockerOperator):
  1. extract_web      → Scrape lecturer data from prodi websites
  2. extract_pddikti  → Fetch lecturer data from PDDIKTI API
  3. merge            → Web-First Smart Merge
  4. enrich           → API Enrichment (SimCV, Sinta, SciVal, Scholar)
  5. transform        → Final Post-Processing
  6. load             → UPSERT to Supabase PostgreSQL

Schedule: Weekly (Sunday 02:00 WIB = Saturday 19:00 UTC)
"""
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.models import Variable
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount

# ─── Constants ──────────────────────────────────────────────────
ETL_WORKER_IMAGE = "tugas-akhir/etl-worker:latest"
DOCKER_NETWORK = "yuxi-know_app-network"
DATA_VOLUME = "tugas_akhir_etl_data"  # Shared volume with Airflow/Worker

def _worker_env():
    """Build environment dict for ETL Worker containers."""
    return {
        "SUPABASE_URL": Variable.get("SUPABASE_URL", default_var=os.environ.get("SUPABASE_URL", "")),
        "SUPABASE_KEY": Variable.get("SUPABASE_KEY", default_var=os.environ.get("SUPABASE_KEY", "")),
        "SERPAPI_KEY": Variable.get("SERPAPI_KEY", default_var=os.environ.get("SERPAPI_KEY", "")),
        "SCIVAL_EMAIL": os.environ.get("SCIVAL_EMAIL", ""),
        "SCIVAL_PASS": os.environ.get("SCIVAL_PASS", ""),
        "BD_PASS_SERP": os.environ.get("BD_PASS_SERP", ""),
        "BD_USER_SERP": os.environ.get("BD_USER_SERP", ""),
        "NEO4J_URI": os.environ.get("NEO4J_URI", ""),
        "NEO4J_USER": os.environ.get("NEO4J_USER", ""),
        "NEO4J_PASSWORD": os.environ.get("NEO4J_PASSWORD", ""),
        "GROQ_API_KEY": Variable.get("GROQ_API_KEY", default_var=os.environ.get("GROQ_API_KEY", "")),
        "KG_BACKEND_URL": os.environ.get("KG_BACKEND_URL", "http://api:8000"),
        "KG_WEBHOOK_URL": f"{os.environ.get('KG_BACKEND_URL', 'http://api:8000')}/webhook/trigger",
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
        Mount(
            source=DATA_VOLUME,
            target="/app/data",
            type="volume",
        ),
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

# Step 3, 4, 5, 6: Sequential processing
merge_task >> enrich_task >> transform_task >> load_task
