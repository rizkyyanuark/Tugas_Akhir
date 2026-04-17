"""
Airflow DAG: UNESA Lecturers ETL Pipeline (Level 3 Architecture)
=================================================================
PURE ORCHESTRATOR --- All heavy work delegated to etl-worker containers.

Tasks (via DockerOperator):
  1. extract_web      -> Scrape lecturer data from prodi websites
  2. extract_pddikti  -> Fetch lecturer data from PDDIKTI API
  3. merge            -> Web-First Smart Merge
  4. enrich           -> API Enrichment (SimCV, Sinta, SciVal, Scholar)
  5. transform        -> Final Post-Processing
  6. load             -> UPSERT to Supabase PostgreSQL

Schedule: Weekly (Sunday 02:00 WIB = Saturday 19:00 UTC)

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


# --- Constants --------------------------------------------------

ETL_WORKER_IMAGE = "rizyyk/unesa-etl:v2"
DOCKER_NETWORK = "unesa_etl_network"
# Path fisik di server host (sesuai init_server.sh)
HOST_DATA_DIR = "/home/shared/vols/etl/unesa_research_data"


def _get_docker_bash_cmd(command):
    return f"""
    docker run --rm \
    --network {DOCKER_NETWORK} \
    -v {HOST_DATA_DIR}:/app/data \
    -e SUPABASE_URL="{Variable.get('SUPABASE_URL_SECRET', '')}" \
    -e SUPABASE_KEY="{Variable.get('SUPABASE_KEY_SECRET', '')}" \
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
    dag_id="unesa_lecturers_etl",
    default_args=default_args,
    description="ETL: Sinkronisasi Profil Dosen UNESA ke Supabase",
    schedule="0 19 * * 6",  # Sunday 02:00 WIB = Saturday 19:00 UTC
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["unesa", "lecturers", "etl", "pddikti"],
    max_active_runs=1,
)


# --- Task Definitions -------------------------------------------

extract_web = SSHOperator(
    task_id="extract_web",
    ssh_conn_id="ssh_default",
    command=_get_docker_bash_cmd("lec_extract_web"),
    cmd_timeout=3600,
    dag=dag,
)

extract_pddikti = SSHOperator(
    task_id="extract_pddikti",
    ssh_conn_id="ssh_default",
    command=_get_docker_bash_cmd("lec_extract_pddikti"),
    cmd_timeout=3600,
    dag=dag,
)

merge_task = SSHOperator(
    task_id="merge",
    ssh_conn_id="ssh_default",
    command=_get_docker_bash_cmd("lec_merge"),
    cmd_timeout=3600,
    dag=dag,
)

enrich_task = SSHOperator(
    task_id="enrich",
    ssh_conn_id="ssh_default",
    command=_get_docker_bash_cmd("lec_enrich"),
    cmd_timeout=3600,
    dag=dag,
)

transform_task = SSHOperator(
    task_id="transform",
    ssh_conn_id="ssh_default",
    command=_get_docker_bash_cmd("lec_transform"),
    cmd_timeout=3600,
    dag=dag,
)

load_task = SSHOperator(
    task_id="load",
    ssh_conn_id="ssh_default",
    command=_get_docker_bash_cmd("lec_load"),
    cmd_timeout=3600,
    dag=dag,
)


# --- DAG Pipeline Flow ------------------------------------------
[extract_web, extract_pddikti] >> merge_task
merge_task >> enrich_task >> transform_task >> load_task
