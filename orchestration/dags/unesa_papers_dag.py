"""
Airflow DAG: UNESA Papers ETL Pipeline (Level 3 Architecture)
===============================================================
PURE ORCHESTRATOR --- All heavy work delegated to etl-worker containers.

Tasks (via DockerOperator):
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
from airflow.models import Variable
from airflow.providers.ssh.operators.ssh import SSHOperator
from airflow.operators.bash import BashOperator

AIRFLOW_ENV = os.environ.get("AIRFLOW_ENV", "production")

# --- Constants --------------------------------------------------

ETL_WORKER_IMAGE = "rizyyk/unesa-etl:v3"
DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "unesa_etl_network")
HOST_DATA_DIR = os.environ.get("HOST_DATA_DIR", "/home/shared/vols/etl/unesa_research_data")


def _get_docker_bash_cmd(command: str) -> str:
    """
    Constructs a full 'docker run' command string for the SSHOperator.
    Maps all necessary environment variables, network, and volumes.
    """
    return f"""
        docker pull {ETL_WORKER_IMAGE} && \
        docker run --rm \
        --network {DOCKER_NETWORK} \
        --shm-size 2g \
        -v {HOST_DATA_DIR}:/app/data \
        -e SUPABASE_URL="{Variable.get('SUPABASE_URL_SECRET', '')}" \
        -e SUPABASE_KEY="{Variable.get('SUPABASE_KEY_SECRET', '')}" \
        -e ELSEVIER_EMAIL="{Variable.get('SCIVAL_EMAIL_SECRET', '')}" \
        -e ELSEVIER_PASSWORD="{Variable.get('SCIVAL_PASS_SECRET', '')}" \
        -e SCIVAL_EMAIL="{Variable.get('SCIVAL_EMAIL_SECRET', '')}" \
        -e SCIVAL_PASS="{Variable.get('SCIVAL_PASS_SECRET', '')}" \
        -e SERPAPI_KEY="{Variable.get('SERPAPI_KEY_SECRET', '')}" \
        -e BRIGHT_DATA_HOST="{Variable.get('BRIGHT_DATA_HOST', 'brd.superproxy.io:33335')}" \
        -e BD_USER_UNLOCKER="{Variable.get('BD_USER_UNLOCKER_SECRET', '')}" \
        -e BD_PASS_UNLOCKER="{Variable.get('BD_PASS_UNLOCKER_SECRET', '')}" \
        -e BD_USER_SERP="{Variable.get('BD_USER_SERP_SECRET', '')}" \
        -e BD_PASS_SERP="{Variable.get('BD_PASS_SERP_SECRET', '')}" \
        -e GROQ_API_KEY="{Variable.get('GROQ_API_KEY_SECRET', '')}" \
        -e NOTIFICATION_EMAIL="{Variable.get('NOTIFICATION_EMAIL_SECRET', '')}" \
        {ETL_WORKER_IMAGE} {command}
    """


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

def create_operator(task_id: str, command_suffix: str):
    cmd = _get_docker_bash_cmd(command_suffix)
    if AIRFLOW_ENV == "production":
        return SSHOperator(
            task_id=task_id,
            ssh_conn_id="ssh_default",
            command=cmd,
            cmd_timeout=3600,
            dag=dag,
        )
    else:
        # Development environment (Local)
        # Airflow scheduler container has /var/run/docker.sock mounted, run bash natively!
        return BashOperator(
            task_id=task_id,
            bash_command=cmd,
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
