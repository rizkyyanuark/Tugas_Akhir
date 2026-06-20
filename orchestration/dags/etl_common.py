"""Shared ETL DockerOperator configuration for Airflow DAGs.

Development can bind-mount backend/package into the spawned etl-worker
containers, while production should run immutable images without code mounts.
"""

from __future__ import annotations

import os

from docker.types import Mount


TRUE_VALUES = {"1", "true", "yes", "on"}
VALID_RUN_MODES = {"full", "incremental", "sample"}


def _clean_env(key: str, default: str = "") -> str:
    for candidate in (key, f"AIRFLOW_VAR_{key}", f"AIRFLOW_VAR_{key}_SECRET"):
        value = os.environ.get(candidate)
        if value:
            return value.strip()
    return default


def _env_bool(key: str, default: bool = False) -> bool:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES


def _host_path(value: str) -> str:
    return value.strip().replace("\\", "/")


def _default_worker_image() -> str:
    environment = _clean_env("ENVIRONMENT", _clean_env("AIRFLOW_ENV", "dev")).lower()
    if environment in {"prod", "production"}:
        return "tugas-akhir-etl-worker:prod"
    return "tugas-akhir-etl-worker:latest"


def _default_run_mode() -> str:
    environment = _clean_env("ENVIRONMENT", _clean_env("AIRFLOW_ENV", "dev")).lower()
    if environment in {"prod", "production"}:
        return "incremental"
    return "sample"


def _run_mode() -> str:
    mode = _clean_env("ETL_RUN_MODE", _default_run_mode()).lower()
    if mode in VALID_RUN_MODES:
        return mode
    return _default_run_mode()


def _sample_size() -> str:
    value = _clean_env("ETL_SAMPLE_SIZE", "5" if _run_mode() == "sample" else "50")
    try:
        size = int(value)
    except ValueError:
        return "5" if _run_mode() == "sample" else "50"
    return str(max(size, 1))


def _default_package_dir(host_data_dir: str) -> str:
    data_dir = host_data_dir.rstrip("/")
    if data_dir.endswith("/data"):
        return f"{data_dir[:-5]}/backend/package"
    return "/home/ubuntu/Tugas_Akhir/backend/package"


ETL_WORKER_IMAGE = _clean_env("ETL_WORKER_IMAGE", _default_worker_image())
DOCKER_NETWORK = _clean_env("DOCKER_NETWORK", "tugas-akhir-network")
HOST_DATA_DIR = _host_path(_clean_env("HOST_DATA_DIR", "/home/ubuntu/Tugas_Akhir/data"))
ETL_RUN_MODE = _run_mode()
ETL_SAMPLE_SIZE = _sample_size()

DEFAULT_MOUNT_CODE = _clean_env("AIRFLOW_ENV", "dev").lower() == "dev"
ETL_WORKER_MOUNT_CODE = _env_bool("ETL_WORKER_MOUNT_CODE", DEFAULT_MOUNT_CODE)
HOST_PACKAGE_DIR = _host_path(
    _clean_env("HOST_PACKAGE_DIR", _default_package_dir(HOST_DATA_DIR))
)

DATA_MOUNT = Mount(source=HOST_DATA_DIR, target="/app/data", type="bind")


def worker_mounts() -> list[Mount]:
    mounts = [DATA_MOUNT]
    if ETL_WORKER_MOUNT_CODE:
        mounts.append(
            Mount(
                source=HOST_PACKAGE_DIR,
                target="/app/package",
                type="bind",
                read_only=True,
            )
        )
    return mounts


def worker_command(task_name: str) -> str:
    """Build an ETL worker command from the deployment runtime mode."""
    command = f"{task_name} --mode {ETL_RUN_MODE}"
    if ETL_RUN_MODE == "sample":
        command = f"{command} --sample-size {ETL_SAMPLE_SIZE}"
    return command


def worker_env() -> dict[str, str]:
    return {
        # Credentials
        "SUPABASE_URL": _clean_env("SUPABASE_URL"),
        "SUPABASE_KEY": _clean_env("SUPABASE_KEY"),
        "SUPABASE_SERVICE_ROLE_KEY": _clean_env(
            "SUPABASE_SERVICE_ROLE_KEY",
            _clean_env("SUPABASE_SERVICE_KEY"),
        ),
        "SCIVAL_EMAIL": _clean_env("SCIVAL_EMAIL"),
        "SCIVAL_PASS": _clean_env("SCIVAL_PASS"),
        "SEMANTIC_SCHOLAR_API_KEY": _clean_env("SEMANTIC_SCHOLAR_API_KEY", _clean_env("S2_API_KEY")),
        "BRIGHT_DATA_HOST": _clean_env("BRIGHT_DATA_HOST", "brd.superproxy.io:33335"),
        "BD_USER_UNLOCKER": _clean_env("BD_USER_UNLOCKER"),
        "BD_PASS_UNLOCKER": _clean_env("BD_PASS_UNLOCKER"),
        "BD_USER_SERP": _clean_env("BD_USER_SERP"),
        "BD_PASS_SERP": _clean_env("BD_PASS_SERP"),
        "GROQ_API_KEY": _clean_env("GROQ_API_KEY"),
        # Knowledge Graph storage and optional extraction.
        "NEO4J_URI": _clean_env("NEO4J_URI"),
        "NEO4J_USERNAME": _clean_env("NEO4J_USERNAME"),
        "NEO4J_PASSWORD": _clean_env("NEO4J_PASSWORD"),
        "NEO4J_DATABASE": _clean_env("NEO4J_DATABASE"),
        "MILVUS_URI": _clean_env("MILVUS_URI"),
        "MILVUS_TOKEN": _clean_env("MILVUS_TOKEN"),
        "MILVUS_DB_NAME": _clean_env("MILVUS_DB_NAME"),
        "SILICONFLOW_API_KEY": _clean_env("SILICONFLOW_API_KEY"),
        "HF_TOKEN": _clean_env("HF_TOKEN"),
        "HF_HOME": _clean_env("HF_HOME", "/app/data/huggingface"),
        "YUNESA_KG_GRAPH_NAME": _clean_env("YUNESA_KG_GRAPH_NAME"),
        "YUNESA_CONCEPT_ALIASES_PATH": _clean_env("YUNESA_CONCEPT_ALIASES_PATH"),
        "YUNESA_KG_WRITE_NEO4J": _clean_env("YUNESA_KG_WRITE_NEO4J"),
        "YUNESA_KG_WRITE_MILVUS": _clean_env("YUNESA_KG_WRITE_MILVUS"),
        "YUNESA_KG_CLEAR_NEO4J": _clean_env("YUNESA_KG_CLEAR_NEO4J"),
        "YUNESA_KG_CLEAR_MILVUS": _clean_env("YUNESA_KG_CLEAR_MILVUS"),
        "YUNESA_USE_GLINER": _clean_env("YUNESA_USE_GLINER", "0"),
        "YUNESA_USE_GLIREL": _clean_env("YUNESA_USE_GLIREL", "0"),
        # Entity Resolution
        "YUNESA_ALIAS_SUGGESTIONS_PATH": _clean_env(
            "YUNESA_ALIAS_SUGGESTIONS_PATH",
            "/app/data/kg/entity_resolution/concept_alias_suggestions.json",
        ),
        "YUNESA_ALIAS_CURATION_STORE": _clean_env(
            "YUNESA_ALIAS_CURATION_STORE",
            "/app/data/kg/entity_resolution/alias_curation_store.json",
        ),
        "YUNESA_APPROVED_CONCEPT_ALIASES_PATH": _clean_env(
            "YUNESA_APPROVED_CONCEPT_ALIASES_PATH",
            "/app/data/kg/entity_resolution/concept_aliases.approved.yml",
        ),
        "YUNESA_ENFORCE_QUALITY_GATES": _clean_env("YUNESA_ENFORCE_QUALITY_GATES", "true"),
        # Storage
        "ETL_STORAGE_TYPE": _clean_env("ETL_STORAGE_TYPE", "local"),
        "AWS_S3_BUCKET": _clean_env("AWS_S3_BUCKET"),
        "AWS_S3_PATH": _clean_env("AWS_S3_PATH", "etl/data"),
        "AWS_ACCESS_KEY_ID": _clean_env("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": _clean_env("AWS_SECRET_ACCESS_KEY"),
        # Runtime tuning
        "ETL_RUN_MODE": ETL_RUN_MODE,
        "ETL_SAMPLE_SIZE": ETL_SAMPLE_SIZE,
        "ETL_ENRICH_MAX_PAPERS_PER_RUN": _clean_env("ETL_ENRICH_MAX_PAPERS_PER_RUN", "0"),
        "ETL_FORCE_EXTRACT": _clean_env("ETL_FORCE_EXTRACT", "false"),
        "ETL_FRESHNESS_HOURS": _clean_env("ETL_FRESHNESS_HOURS", "72"),
        "ETL_CRAWLER_MAX_RETRIES": _clean_env("ETL_CRAWLER_MAX_RETRIES", "3"),
        "ETL_CRAWLER_TIMEOUT": _clean_env("ETL_CRAWLER_TIMEOUT", "60"),
        "ETL_CRAWLER_HEADLESS": _clean_env("ETL_CRAWLER_HEADLESS", "true"),
        "ETL_ENABLE_SIAKADU": _clean_env("ETL_ENABLE_SIAKADU", "true"),
        # Container behavior
        "DOCKER_ENVIRONMENT": "true",
        "DATA_SOURCE_PATH": "/app/data",
        "PYTHONPATH": "/app/package",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
