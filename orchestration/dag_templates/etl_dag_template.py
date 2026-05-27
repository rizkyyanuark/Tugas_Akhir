"""
Template: ETL DAG using DockerOperator
=====================================
Copy this file into orchestration/dags/ and update:
- dag_id, schedule, tags
- task list
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from etl_common import DOCKER_NETWORK, ETL_WORKER_IMAGE, worker_command, worker_env, worker_mounts


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
        mounts=worker_mounts(),
        environment=worker_env(),
        auto_remove="success",
        dag=dag,
    )


extract_task = create_operator("extract", worker_command("etl_extract"))
transform_task = create_operator("transform", worker_command("etl_transform"))
load_task = create_operator("load", worker_command("etl_load"))


# --- DAG Pipeline Flow ------------------------------------------
extract_task >> transform_task >> load_task
