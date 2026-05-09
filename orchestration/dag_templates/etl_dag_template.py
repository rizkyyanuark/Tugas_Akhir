"""
Template: ETL DAG using DockerOperator
=====================================
Copy this file into orchestration/dags/ and update:
- dag_id, schedule, tags
- ETL_WORKER_IMAGE if needed
- task list and command suffixes
- required Airflow Variables
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
        "NOTIFICATION_EMAIL": "{{ var.value.NOTIFICATION_EMAIL_SECRET }}",
        "DOCKER_ENVIRONMENT": "true",
    }


# --- DAG Configuration ------------------------------------------

default_args = {
    "owner": "team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="template_etl_job",
    default_args=default_args,
    description="ETL template using DockerOperator",
    schedule="0 1 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["etl", "template"],
    max_active_runs=1,
)


# --- Task Definitions -------------------------------------------
# Runs the etl-worker container on the host's Docker daemon via /var/run/docker.sock.

def create_operator(task_id: str, command_suffix: str):
    return DockerOperator(
        task_id=task_id,
        image=ETL_WORKER_IMAGE,
        command=command_suffix,
        docker_url="unix://var/run/docker.sock",
        network_mode=DOCKER_NETWORK,
        mounts=[DATA_MOUNT],
        environment=_worker_env(),
        auto_remove="success",
        dag=dag,
    )


extract_task = create_operator("extract", "etl_extract")
transform_task = create_operator("transform", "etl_transform")
load_task = create_operator("load", "etl_load")


# --- DAG Pipeline Flow ------------------------------------------
extract_task >> transform_task >> load_task
