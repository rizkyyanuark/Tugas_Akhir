"""Airflow DAG: UNESA Papers ETL Pipeline.

The Airflow scheduler only orchestrates. Each heavy ETL step runs in the
etl-worker image through DockerOperator on the same Compose network.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from etl_common import (
    DOCKER_NETWORK,
    ETL_RUN_MODE,
    ETL_WORKER_IMAGE,
    worker_command,
    worker_env,
    worker_mounts,
)


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
    description=f"ETL: Sinkronisasi publikasi UNESA ke Supabase ({ETL_RUN_MODE} mode)",
    schedule="0 20 * * 6",  # Sunday 03:00 WIB = Saturday 20:00 UTC
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["unesa", "papers", "etl", "supabase", f"mode:{ETL_RUN_MODE}"],
    max_active_runs=1,
)


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


extract_scopus = create_operator("extract_scopus", worker_command("paper_extract_scopus"))
extract_scholar = create_operator("extract_scholar", worker_command("paper_extract_scholar"))
transform = create_operator("transform", worker_command("paper_transform"))
enrich = create_operator("enrich", worker_command("paper_enrich"))
load = create_operator("load", worker_command("paper_load"))

[extract_scopus, extract_scholar] >> transform >> enrich >> load
