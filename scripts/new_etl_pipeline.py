#!/usr/bin/env python3
"""Create a new ETL pipeline module and matching DAG.

Example:
  python scripts/new_etl_pipeline.py \
    --pipeline research \
    --task-prefix res \
    --tasks extract,transform,load \
    --schedule "0 1 * * *"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINES_DIR = ROOT / "backend" / "package" / "knowledge" / "etl" / "pipelines"
DAGS_DIR = ROOT / "orchestration" / "dags"
DOC_PATH = ROOT / "backend" / "package" / "knowledge" / "etl" / "PIPELINES.md"


def _slugify(value: str) -> str:
    value = value.strip().lower().replace("-", "_")
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        raise ValueError("Pipeline name must contain letters or numbers.")
    return value


def _parse_tasks(value: str) -> list[str]:
    tasks = [t.strip().lower().replace("-", "_")
             for t in value.split(",") if t.strip()]
    if not tasks:
        raise ValueError("Tasks list cannot be empty.")
    return tasks


def _write_file(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"File already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _render_pipeline_module(pipeline: str, prefix: str, tasks: list[str]) -> str:
    handlers = []
    registry_lines = []
    for task in tasks:
        command = f"{prefix}_{task}"
        func_name = f"_{command}"
        handlers.append(
            "\n\n".join(
                [
                    f"def {func_name}(test_mode: bool):",
                    f"    logger.info(\"TODO: implement {command}\")",
                    f"    raise NotImplementedError(\"TODO: implement {command}\")",
                ]
            )
        )
        registry_lines.append(f"    \"{command}\": {func_name},")

    handlers_block = "\n\n".join(handlers)
    registry_block = "\n".join(registry_lines)

    return (
        '"""ETL pipeline handlers for ' + pipeline + '."""\n\n'
        "import logging\n\n"
        "logger = logging.getLogger(\"etl-worker\")\n\n\n"
        f"{handlers_block}\n\n\n"
        f"{pipeline.upper()}_TASKS = {{\n{registry_block}\n}}\n\n"
        "TASKS = " + f"{pipeline.upper()}_TASKS" + "\n"
    )


def _render_dag_file(
    dag_id: str,
    description: str,
    schedule: str,
    tags: list[str],
    task_commands: list[str],
    owner: str,
) -> str:
    tags_list = ", ".join([f"\"{t}\"" for t in tags])
    task_list = ", ".join([f"\"{t}\"" for t in task_commands])

    return (
        '"""Auto-generated ETL DAG (DockerOperator)."""\n\n'
        "import os\n"
        "from datetime import datetime, timedelta\n\n"
        "from airflow import DAG\n"
        "from airflow.providers.docker.operators.docker import DockerOperator\n"
        "from docker.types import Mount\n\n"
        "ETL_WORKER_IMAGE = os.environ.get(\"ETL_WORKER_IMAGE\", \"tugas-akhir-etl-worker:prod\")\n"
        "DOCKER_NETWORK = os.environ.get(\"DOCKER_NETWORK\", \"tugas-akhir-network\")\n"
        "HOST_DATA_DIR = os.environ.get(\"HOST_DATA_DIR\", \"/home/ubuntu/Tugas_Akhir/data\").replace(\\\\\"\\\\\", \"/\")\n\n"
        "DATA_MOUNT = Mount(source=HOST_DATA_DIR, target=\"/app/data\", type=\"bind\")\n\n\n"
        "def _worker_env() -> dict[str, str]:\n"
        "    return {\n"
        "        \"SUPABASE_URL\": \"{{ var.value.SUPABASE_URL_SECRET }}\",\n"
        "        \"SUPABASE_KEY\": \"{{ var.value.SUPABASE_KEY_SECRET }}\",\n"
        "        \"NOTIFICATION_EMAIL\": \"{{ var.value.NOTIFICATION_EMAIL_SECRET }}\",\n"
        "        \"DOCKER_ENVIRONMENT\": \"true\",\n"
        "    }\n\n\n"
        "default_args = {\n"
        f"    \"owner\": \"{owner}\",\n"
        "    \"depends_on_past\": False,\n"
        "    \"email_on_failure\": False,\n"
        "    \"email_on_retry\": False,\n"
        "    \"retries\": 2,\n"
        "    \"retry_delay\": timedelta(minutes=5),\n"
        "}\n\n"
        "dag = DAG(\n"
        f"    dag_id=\"{dag_id}\",\n"
        f"    default_args=default_args,\n"
        f"    description=\"{description}\",\n"
        f"    schedule=\"{schedule}\",\n"
        "    start_date=datetime(2026, 1, 1),\n"
        "    catchup=False,\n"
        f"    tags=[{tags_list}],\n"
        "    max_active_runs=1,\n"
        ")\n\n\n"
        "def create_operator(task_id: str, command_suffix: str):\n"
        "    return DockerOperator(\n"
        "        task_id=task_id,\n"
        "        image=ETL_WORKER_IMAGE,\n"
        "HOST_DATA_DIR = os.environ.get(\"HOST_DATA_DIR\", \"/home/ubuntu/Tugas_Akhir/data\").replace(\"\\\\\", \"/\")\n\n"
        "        docker_url=\"unix://var/run/docker.sock\",\n"
        "        network_mode=DOCKER_NETWORK,\n"
        "        mounts=[DATA_MOUNT],\n"
        "        environment=_worker_env(),\n"
        "        auto_remove=True,\n"
        "        dag=dag,\n"
        "    )\n\n\n"
        f"TASK_NAMES = [{task_list}]\n"
        "TASKS = {name: create_operator(name, name) for name in TASK_NAMES}\n\n"
        "for i in range(len(TASK_NAMES) - 1):\n"
        "    TASKS[TASK_NAMES[i]] >> TASKS[TASK_NAMES[i + 1]]\n"
    )


def _append_doc(pipeline: str, prefix: str, commands: list[str]) -> None:
    if not DOC_PATH.exists():
        return

    lines = [
        "",
        f"## {pipeline} pipeline",
        "",
        f"- Module: knowledge.etl.pipelines.{pipeline}",
        f"- Task prefix: {prefix}_",
        "- Tasks:",
    ]
    lines.extend([f"  - {cmd}" for cmd in commands])
    lines.append("")

    DOC_PATH.write_text(DOC_PATH.read_text(
        encoding="utf-8") + "\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a new ETL pipeline and DAG")
    parser.add_argument("--pipeline", required=True,
                        help="Pipeline name (e.g., papers, lecturers)")
    parser.add_argument("--task-prefix", default=None,
                        help="Task prefix (defaults to pipeline name)")
    parser.add_argument(
        "--tasks", default="extract,transform,load", help="Comma-separated task list")
    parser.add_argument("--schedule", default="0 1 * * *",
                        help="Cron schedule expression")
    parser.add_argument("--dag-id", default=None,
                        help="DAG id (defaults to <pipeline>_etl)")
    parser.add_argument("--dag-file", default=None,
                        help="DAG filename (defaults to <pipeline>_etl.py)")
    parser.add_argument("--owner", default="team", help="DAG owner")
    parser.add_argument("--tags", default=None, help="Comma-separated tags")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing files")

    args = parser.parse_args()

    pipeline = _slugify(args.pipeline)
    prefix = _slugify(args.task_prefix or pipeline)
    tasks = _parse_tasks(args.tasks)

    task_commands = [f"{prefix}_{task}" for task in tasks]

    dag_id = args.dag_id or f"{pipeline}_etl"
    dag_file = args.dag_file or f"{pipeline}_etl.py"
    dag_path = DAGS_DIR / dag_file

    tags = [t.strip()
            for t in (args.tags or f"etl,{pipeline}").split(",") if t.strip()]

    module_path = PIPELINES_DIR / f"{pipeline}.py"
    module_content = _render_pipeline_module(pipeline, prefix, tasks)

    dag_description = f"ETL pipeline for {pipeline}"
    dag_content = _render_dag_file(
        dag_id, dag_description, args.schedule, tags, task_commands, args.owner)

    _write_file(module_path, module_content, args.force)
    _write_file(dag_path, dag_content, args.force)
    _append_doc(pipeline, prefix, task_commands)

    print("Created:")
    print(f"- {module_path}")
    print(f"- {dag_path}")
    print("Next:")
    print("- Implement handlers in the pipeline module")
    print("- Rebuild the etl-worker image after code changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
