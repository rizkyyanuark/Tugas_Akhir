"""
Airflow DAG: UNESA Lecturers ETL Pipeline (Level 3 Architecture)
=================================================================
PURE ORCHESTRATOR --- All heavy work delegated to etl-worker containers.

Tasks (via DockerOperator → etl-worker container):
  1. extract_web      -> Scrape lecturer data from prodi websites
  2. extract_pddikti  -> Fetch lecturer data from PDDIKTI API
  3. extract_siakadu  -> Fetch lecturer NIP/NIDN identities from SIAKADU
  4. merge            -> Web-First Smart Merge
  5. enrich           -> API Enrichment (SIAKADU, SimCV, Sinta, SciVal, Scholar)
  6. transform        -> Final Post-Processing
  7. load             -> UPSERT to Supabase PostgreSQL

Schedule: Weekly (Sunday 02:00 WIB = Saturday 19:00 UTC)

Maintenance Guide:
    +-----------------------------------------------------------------+
    |  To add a new Airflow Variable for the worker:                  |
    |  1. Create it in Airflow UI -> Admin -> Variables               |
    |  2. Add it to _worker_env() below                               |
    |  3. Reference it in config.py via os.environ.get()              |
    +-----------------------------------------------------------------+
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from etl_common import DOCKER_NETWORK, ETL_WORKER_IMAGE, worker_env, worker_mounts

# --- Constants --------------------------------------------------

RUN_MODE_TEMPLATE = "{{ dag_run.conf.get('mode', 'incremental') if dag_run else 'incremental' }}"


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
    tags=["unesa", "lecturers", "etl", "pddikti", "siakadu"],
    max_active_runs=1,
)


# --- Task Definitions -------------------------------------------
# Uses DockerOperator to run the etl-worker container on the host's Docker daemon
# via the mounted /var/run/docker.sock. Prerequisites:
#   1. Docker SDK available in the Airflow image
#   2. Scheduler container running as root (user: "0:0")
#   3. /var/run/docker.sock mounted as volume

# --- Task Definitions -------------------------------------------
def create_operator(task_id: str, command_suffix: str):
    return DockerOperator(
        task_id=task_id,
        image=ETL_WORKER_IMAGE,
        command=command_suffix,
        docker_url="unix://var/run/docker.sock",
        network_mode=DOCKER_NETWORK,
        mounts=worker_mounts(),
        environment=worker_env(),
        auto_remove="success",
        mount_tmp_dir=False,
        dag=dag,
    )


def worker_command(task_name: str) -> str:
    return f"{task_name} --mode {RUN_MODE_TEMPLATE}"


extract_web_univ = create_operator("extract_web_univ", worker_command("lec_extract_web"))
extract_pddikti = create_operator("extract_pddikti", worker_command("lec_extract_pddikti"))
merge_task = create_operator("merge", worker_command("lec_merge"))
enrich_task = create_operator("enrich", worker_command("lec_enrich"))
transform_task = create_operator("transform", worker_command("lec_transform"))
load_task = create_operator("load", worker_command("lec_load"))


# --- DAG Pipeline Flow ------------------------------------------
# 2 Parallel Extraction Sources (Internal UNESA + External PDDIKTI)
[extract_web_univ, extract_pddikti] >> merge_task >> enrich_task >> transform_task >> load_task


