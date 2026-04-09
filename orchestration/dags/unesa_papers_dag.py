"""
Airflow DAG: UNESA Papers ETL Pipeline (Level 3 Architecture)
==============================================================
PURE ORCHESTRATOR — Airflow does NOT run any ETL code directly.
All heavy work is delegated to isolated etl-worker containers
via DockerOperator (Docker-outside-of-Docker).

Pipeline:
  Task 1A: Extract papers from Google Scholar (SerpAPI)
  Task 1B: Extract papers from Scopus (SciVal)
  Task 2:  Merge & Deduplicate papers cross-source
  Task 3:  Enrich papers with Semantic Scholar & OpenAlex metadata
  Task 4:  Transform & Clean noisy data
  Task 5:  Load enriched papers to Supabase & Link to Lecturers
  Task 6:  Trigger KG Construction Webhook

Schedule: Daily at 01:00 WIB (UTC+7)
"""
import os
import uuid
from datetime import datetime, timedelta

from airflow import DAG
from airflow.models import Variable
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.decorators import task
from docker.types import Mount

# ─── Constants ──────────────────────────────────────────────────
ETL_WORKER_IMAGE = "tugas-akhir/etl-worker:latest"
DOCKER_NETWORK = "tugas_akhir_default"
DATA_VOLUME = "tugas_akhir_etl_data"  # Named volume shared with Airflow

# Environment variables to inject into worker containers.
# Secrets are pulled from Airflow Variables (set via UI) and forwarded
# as plain env vars to the worker — the worker has NO Airflow installed.
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
    }


# ─── DAG Configuration ──────────────────────────────────────────

default_args = {
    "owner": "rizky",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="unesa_papers_etl",
    default_args=default_args,
    description="Level 3 ETL: Scopus & Scholar Papers → Supabase (DockerOperator)",
    schedule_interval="0 18 * * *",  # 01:00 WIB = 18:00 UTC previous day
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["etl", "scholar", "scopus", "unesa", "level3"],
    max_active_runs=1,
)

# ─── Shared DockerOperator Config ────────────────────────────────
# All tasks share these base settings for DRY configuration.
docker_defaults = {
    "image": ETL_WORKER_IMAGE,
    "docker_url": "unix://var/run/docker.sock",
    "network_mode": DOCKER_NETWORK,
    "auto_remove": "success",  # Clean up containers after success
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

# ─── Task 1A: Extract Scholar ───────────────────────────────────

extract_scholar = DockerOperator(
    task_id="extract_scholar",
    command="extract_scholar --test-mode",
    environment=_worker_env(),
    **docker_defaults,
)

# ─── Task 1B: Extract Scopus ────────────────────────────────────

extract_scopus = DockerOperator(
    task_id="extract_scopus",
    command="extract_scopus",
    environment=_worker_env(),
    **docker_defaults,
)

# ─── Task 2: Merge (Cross-Source Deduplication) ──────────────────

merge_task = DockerOperator(
    task_id="merge",
    command="merge",
    environment=_worker_env(),
    **docker_defaults,
)

# ─── Task 3: Enrich ─────────────────────────────────────────────

enrich_task = DockerOperator(
    task_id="enrich",
    command="enrich --test-mode",
    environment=_worker_env(),
    **docker_defaults,
)

# ─── Task 4: Transform (Clean Data) ─────────────────────────────

transform_task = DockerOperator(
    task_id="transform",
    command="transform",
    environment=_worker_env(),
    **docker_defaults,
)

# ─── Task 5: Load ───────────────────────────────────────────────

load_task = DockerOperator(
    task_id="load",
    command="load",
    environment=_worker_env(),
    **docker_defaults,
)

# ─── Task 6: Trigger KG Construction ────────────────────────────

@task(dag=dag, retries=1, retry_delay=timedelta(minutes=2))
def trigger_kg_construction():
    """POST to KG Backend webhook to start Knowledge Graph construction.

    This is the event-driven bridge between ETL (Fase 1) and KG (Fase 2).
    Soft-fail: if the KG backend is not reachable, the ETL pipeline
    still succeeds — KG can be triggered manually later.
    """
    import requests

    kg_url = os.environ.get("KG_BACKEND_URL", "http://api:8000")
    endpoint = f"{kg_url}/webhook/trigger"

    payload = {
        "source": "airflow",
        "trigger_id": str(uuid.uuid4()),
        "test_mode": False,
    }

    try:
        resp = requests.post(endpoint, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        print(f"✅ KG Pipeline triggered successfully: {result}")
        return result
    except requests.exceptions.ConnectionError:
        print(
            "⚠️ KG Backend not reachable at "
            f"{endpoint}. Skipping KG trigger — run manually later."
        )
    except Exception as e:
        print(f"⚠️ KG trigger failed (non-fatal): {type(e).__name__}: {e}")


kg_trigger = trigger_kg_construction()

# ─── DAG Pipeline (Execution Flow) ──────────────────────────────
# Step 1: Parallel extraction
[extract_scholar, extract_scopus] >> merge_task

# Step 2-5: Sequential processing → Step 6: KG Trigger
merge_task >> enrich_task >> transform_task >> load_task >> kg_trigger
