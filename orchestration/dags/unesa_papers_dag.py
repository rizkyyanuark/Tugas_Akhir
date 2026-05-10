"""
Airflow DAG: UNESA Papers ETL Pipeline (Level 3 Architecture)
===============================================================
PURE ORCHESTRATOR --- All heavy work delegated to etl-worker containers.

Tasks (via DockerOperator → etl-worker container):
  1. extract_scopus  -> Scrape papers from Scopus via Selenium
  2. extract_scholar -> Scrape papers from Google Scholar via SerpAPI
  3. transform       -> Normalize, deduplicate, and enrich with AI embeddings
  4. load            -> UPSERT to Supabase PostgreSQL
  5. notify          -> Email notification on completion

Schedule: Daily at 03:00 WIB (20:00 UTC previous day)

Maintenance Guide:
    +-----------------------------------------------------------------+
    |  To add a new Airflow Variable for the worker:                  |
    |  1. Create it in Airflow UI -> Admin -> Variables               |
    |  2. Add it to _worker_env() below                               |
    |  3. Reference it in config.py via os.environ.get()              |
    +-----------------------------------------------------------------+
"""

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount

# --- Constants --------------------------------------------------

ETL_WORKER_IMAGE = os.environ.get(
    "ETL_WORKER_IMAGE", "tugas-akhir-etl-worker:prod")
DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "tugas-akhir-network")
HOST_DATA_DIR = os.environ.get(
    "HOST_DATA_DIR", "/home/ubuntu/Tugas_Akhir/data").replace("\\", "/")

DATA_MOUNT = Mount(source=HOST_DATA_DIR, target="/app/data", type="bind")


def _worker_env() -> dict[str, str]:
    # Using Jinja templates {{ var.value.VAR_NAME }} for Airflow compatibility
    return {
        "SUPABASE_URL": "{{ var.value.SUPABASE_URL_SECRET }}",
        "SUPABASE_KEY": "{{ var.value.SUPABASE_KEY_SECRET }}",
        "ELSEVIER_EMAIL": "{{ var.value.SCIVAL_EMAIL_SECRET }}",
        "ELSEVIER_PASSWORD": "{{ var.value.SCIVAL_PASS_SECRET }}",
        "SCIVAL_EMAIL": "{{ var.value.SCIVAL_EMAIL_SECRET }}",
        "SCIVAL_PASS": "{{ var.value.SCIVAL_PASS_SECRET }}",
        "SERPAPI_KEY": "{{ var.value.SERPAPI_KEY_SECRET }}",
        "BRIGHT_DATA_HOST": "{{ var.value.BRIGHT_DATA_HOST }}",
        "BD_USER_UNLOCKER": "{{ var.value.BD_USER_UNLOCKER_SECRET }}",
        "BD_PASS_UNLOCKER": "{{ var.value.BD_PASS_UNLOCKER_SECRET }}",
        "BD_USER_SERP": "{{ var.value.BD_USER_SERP_SECRET }}",
        "BD_PASS_SERP": "{{ var.value.BD_PASS_SERP_SECRET }}",
        "BRIGHTDATA_SERP_TOKEN": "{{ var.value.BRIGHTDATA_SERP_TOKEN_SECRET }}",
        "GROQ_API_KEY": "{{ var.value.GROQ_API_KEY_SECRET }}",
        "NOTIFICATION_EMAIL": "{{ var.value.NOTIFICATION_EMAIL_SECRET }}",
        "DOCKER_ENVIRONMENT": "true",
    }


# --- DAG Configuration ------------------------------------------

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
    description="ETL: Sinkronisasi Publikasi Ilmiah UNESA ke Supabase",
    schedule="0 20 * * *",  # 03:00 WIB = 20:00 UTC
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["unesa", "papers", "etl", "scholar"],
    max_active_runs=1,
)


# --- Task Definitions -------------------------------------------
# Uses DockerOperator to run the etl-worker container on the host's Docker daemon
# via the mounted /var/run/docker.sock. Prerequisites:
#   1. Docker SDK available in the Airflow image
#   2. Scheduler container running as root (user: "0:0")
#   3. /var/run/docker.sock mounted as volume

def create_operator(task_id: str, command_suffix: str):
    return DockerOperator(
        task_id=task_id,
        image=ETL_WORKER_IMAGE,
        command=command_suffix,
        docker_url="unix://var/run/docker.sock",
        network_mode=DOCKER_NETWORK,
        shm_size="2g",
        mounts=[DATA_MOUNT],
        environment=_worker_env(),
        auto_remove="success",
        mount_tmp_dir=False,
        dag=dag,
    )


extract_scopus = create_operator("extract_scopus", "paper_extract_scopus")
extract_scholar = create_operator("extract_scholar", "paper_extract_scholar")
transform_task = create_operator("transform", "paper_transform")
load_task = create_operator("load", "paper_load")
notify_task = create_operator("notify", "paper_notify")


# --- DAG Pipeline Flow ------------------------------------------
[extract_scopus, extract_scholar] >> transform_task
transform_task >> load_task >> notify_task
