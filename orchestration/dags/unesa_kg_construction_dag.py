"""Airflow DAG: UNESA Academic Knowledge Graph construction.

This DAG is intentionally separate from lecturer/paper ETL. It reads the
already-enriched Supabase tables, builds the thesis Knowledge Graph, and writes
to Neo4j/Zilliz only when explicitly configured by mode or DAG parameters.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator

from etl_common import (
    DOCKER_NETWORK,
    ETL_SAMPLE_SIZE,
    ETL_WORKER_IMAGE,
    worker_env,
    worker_mounts,
)


MODE_TEMPLATE = "{{ dag_run.conf.get('mode', params.default_mode) if dag_run else params.default_mode }}"
SAMPLE_SIZE_TEMPLATE = "{{ dag_run.conf.get('sample_size', params.default_sample_size) if dag_run else params.default_sample_size }}"
GRAPH_NAME_TEMPLATE = (
    "{{ dag_run.conf.get('graph_name', params.default_graph_name) if dag_run else params.default_graph_name }}"
)
USE_GLINER_TEMPLATE = "{{ '1' if (dag_run.conf.get('use_gliner', params.default_use_gliner) if dag_run else params.default_use_gliner) else '0' }}"
WRITE_NEO4J_TEMPLATE = (
    "{% set resolved_mode = dag_run.conf.get('mode', params.default_mode) if dag_run else params.default_mode %}"
    "{{ '1' if (dag_run.conf.get('write_neo4j', resolved_mode != 'sample') if dag_run else params.default_write_stores) else '0' }}"
)
WRITE_MILVUS_TEMPLATE = (
    "{% set resolved_mode = dag_run.conf.get('mode', params.default_mode) if dag_run else params.default_mode %}"
    "{{ '1' if (dag_run.conf.get('write_milvus', resolved_mode != 'sample') if dag_run else params.default_write_stores) else '0' }}"
)
CLEAR_NEO4J_TEMPLATE = (
    "{% set resolved_mode = dag_run.conf.get('mode', params.default_mode) if dag_run else params.default_mode %}"
    "{{ '1' if (dag_run.conf.get('clear_neo4j', resolved_mode == 'full') if dag_run else params.default_clear_stores) else '0' }}"
)
CLEAR_MILVUS_TEMPLATE = (
    "{% set resolved_mode = dag_run.conf.get('mode', params.default_mode) if dag_run else params.default_mode %}"
    "{{ '1' if (dag_run.conf.get('clear_milvus', resolved_mode == 'full') if dag_run else params.default_clear_stores) else '0' }}"
)


default_args = {
    "owner": "rizky",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


dag = DAG(
    dag_id="unesa_kg_construction",
    default_args=default_args,
    description="Build UNESA Academic Knowledge Graph and optional dual index storage",
    schedule=None,
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["unesa", "kg", "graph", "neo4j", "milvus"],
    max_active_runs=1,
    params={
        "default_mode": "sample",
        "default_sample_size": ETL_SAMPLE_SIZE,
        "default_graph_name": "yunesa_academic_kg",
        "default_use_gliner": False,
        "default_write_stores": False,
        "default_clear_stores": False,
    },
)

dag.doc_md = """
### Manual KG construction

Safe sample run:

```json
{
  "mode": "sample",
  "sample_size": 50,
  "use_gliner": false
}
```

Production rebuild:

```json
{
  "mode": "full",
  "graph_name": "yunesa_academic_kg",
  "use_gliner": false,
  "write_neo4j": true,
  "write_milvus": true,
  "clear_neo4j": true,
  "clear_milvus": true
}
```

GLiNER remains optional and GLiREL is disabled by default because ontology
relations are built deterministically from the academic KG schema.
"""


def _kg_environment() -> dict[str, str]:
    env = worker_env()
    env.update(
        {
            "YUNESA_KG_GRAPH_NAME": GRAPH_NAME_TEMPLATE,
            "YUNESA_USE_GLINER": USE_GLINER_TEMPLATE,
            "YUNESA_USE_GLIREL": "0",
            "YUNESA_KG_WRITE_NEO4J": WRITE_NEO4J_TEMPLATE,
            "YUNESA_KG_WRITE_MILVUS": WRITE_MILVUS_TEMPLATE,
            "YUNESA_KG_CLEAR_NEO4J": CLEAR_NEO4J_TEMPLATE,
            "YUNESA_KG_CLEAR_MILVUS": CLEAR_MILVUS_TEMPLATE,
            "YUNESA_RUN_ID": "{{ run_id }}",
        }
    )
    return env


def _worker_command(task_name: str) -> str:
    return (
        f"{task_name} --mode {MODE_TEMPLATE}"
        "{% if (dag_run.conf.get('mode', params.default_mode) if dag_run else params.default_mode) == 'sample' %}"
        f" --sample-size {SAMPLE_SIZE_TEMPLATE}"
        "{% endif %}"
    )


def create_operator(task_id: str, worker_task: str) -> DockerOperator:
    return DockerOperator(
        task_id=task_id,
        image=ETL_WORKER_IMAGE,
        command=_worker_command(worker_task),
        docker_url="unix://var/run/docker.sock",
        network_mode=DOCKER_NETWORK,
        mounts=worker_mounts(),
        environment=_kg_environment(),
        auto_remove="success",
        mount_tmp_dir=False,
        dag=dag,
    )


load_data = create_operator("load_data", "kg_load_data")
extract_entities = create_operator("extract_entities", "kg_extract_entities")
build_graph = create_operator("build_graph", "kg_build_graph")
write_stores = create_operator("write_stores", "kg_write_stores")

load_data >> extract_entities >> build_graph >> write_stores
