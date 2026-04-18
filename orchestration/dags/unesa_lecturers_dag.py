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
from airflow.providers.standard.operators.bash import BashOperator

AIRFLOW_ENV = os.environ.get("AIRFLOW_ENV", "production")

# --- Constants --------------------------------------------------

ETL_WORKER_IMAGE = os.environ.get("ETL_WORKER_IMAGE", "tugas-akhir-etl-worker:latest")
DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "tugas-akhir-network")
HOST_DATA_DIR = os.environ.get("HOST_DATA_DIR", "./data")


def _get_docker_bash_cmd(command):
    # Using Jinja templates {{ var.value.VAR_NAME }} for Airflow compatibility
    return f"""
docker run --rm \
--network {DOCKER_NETWORK} \
-v {HOST_DATA_DIR}:/app/data \
-e SUPABASE_URL="{{{{ var.value.SUPABASE_URL_SECRET }}}}" \
-e SUPABASE_KEY="{{{{ var.value.SUPABASE_KEY_SECRET }}}}" \
-e SCIVAL_EMAIL="{{{{ var.value.SCIVAL_EMAIL_SECRET }}}}" \
-e SCIVAL_PASS="{{{{ var.value.SCIVAL_PASS_SECRET }}}}" \
-e SERPAPI_KEY="{{{{ var.value.SERPAPI_KEY_SECRET }}}}" \
-e BRIGHT_DATA_HOST="{{{{ var.value.BRIGHT_DATA_HOST }}}}" \
-e BD_USER_UNLOCKER="{{{{ var.value.BD_USER_UNLOCKER_SECRET }}}}" \
-e BD_PASS_UNLOCKER="{{{{ var.value.BD_PASS_UNLOCKER_SECRET }}}}" \
-e BD_USER_SERP="{{{{ var.value.BD_USER_SERP_SECRET }}}}" \
-e BD_PASS_SERP="{{{{ var.value.BD_PASS_SERP_SECRET }}}}" \
-e GROQ_API_KEY="{{{{ var.value.GROQ_API_KEY_SECRET }}}}" \
-e NOTIFICATION_EMAIL="{{{{ var.value.NOTIFICATION_EMAIL_SECRET }}}}" \
{ETL_WORKER_IMAGE} {command}
""".strip()


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

extract_web = create_operator("extract_web", "lec_extract_web")
extract_pddikti = create_operator("extract_pddikti", "lec_extract_pddikti")
merge_task = create_operator("merge", "lec_merge")
enrich_task = create_operator("enrich", "lec_enrich")
transform_task = create_operator("transform", "lec_transform")
load_task = create_operator("load", "lec_load")


# --- DAG Pipeline Flow ------------------------------------------
[extract_web, extract_pddikti] >> merge_task
merge_task >> enrich_task >> transform_task >> load_task
