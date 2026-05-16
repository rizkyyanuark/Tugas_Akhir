"""Shared ETL DockerOperator configuration for Airflow DAGs.

Development can bind-mount backend/package into the spawned etl-worker
containers, while production should run immutable images without code mounts.
"""

from __future__ import annotations

import os

from docker.types import Mount


TRUE_VALUES = {"1", "true", "yes", "on"}


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


def _default_package_dir(host_data_dir: str) -> str:
    data_dir = host_data_dir.rstrip("/")
    if data_dir.endswith("/data"):
        return f"{data_dir[:-5]}/backend/package"
    return "/home/ubuntu/Tugas_Akhir/backend/package"


ETL_WORKER_IMAGE = _clean_env("ETL_WORKER_IMAGE", _default_worker_image())
DOCKER_NETWORK = _clean_env("DOCKER_NETWORK", "tugas-akhir-network")
HOST_DATA_DIR = _host_path(_clean_env("HOST_DATA_DIR", "/home/ubuntu/Tugas_Akhir/data"))

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


def worker_env() -> dict[str, str]:
    return {
        # Credentials
        "SUPABASE_URL": _clean_env("SUPABASE_URL"),
        "SUPABASE_KEY": _clean_env("SUPABASE_KEY"),
        "SCIVAL_EMAIL": _clean_env("SCIVAL_EMAIL"),
        "SCIVAL_PASS": _clean_env("SCIVAL_PASS"),
        "SERPAPI_KEY": _clean_env("SERPAPI_KEY"),
        "BRIGHT_DATA_HOST": _clean_env("BRIGHT_DATA_HOST", "brd.superproxy.io:33335"),
        "BD_USER_UNLOCKER": _clean_env("BD_USER_UNLOCKER"),
        "BD_PASS_UNLOCKER": _clean_env("BD_PASS_UNLOCKER"),
        "BD_USER_SERP": _clean_env("BD_USER_SERP"),
        "BD_PASS_SERP": _clean_env("BD_PASS_SERP"),
        "BRIGHTDATA_SERP_TOKEN": _clean_env("BRIGHTDATA_SERP_TOKEN"),
        "BRIGHTDATA_SERP_ZONE": _clean_env("BRIGHTDATA_SERP_ZONE", "serp_api1"),
        "GROQ_API_KEY": _clean_env("GROQ_API_KEY"),
        "NOTIFICATION_EMAIL": _clean_env("NOTIFICATION_EMAIL"),
        # Storage
        "ETL_STORAGE_TYPE": _clean_env("ETL_STORAGE_TYPE", "local"),
        "AWS_S3_BUCKET": _clean_env("AWS_S3_BUCKET"),
        "AWS_S3_PATH": _clean_env("AWS_S3_PATH", "etl/data"),
        "AWS_ACCESS_KEY_ID": _clean_env("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": _clean_env("AWS_SECRET_ACCESS_KEY"),
        # Runtime tuning
        "ETL_RUN_MODE": _clean_env("ETL_RUN_MODE", "incremental"),
        "ETL_SAMPLE_SIZE": _clean_env("ETL_SAMPLE_SIZE", "50"),
        "ETL_FORCE_EXTRACT": _clean_env("ETL_FORCE_EXTRACT", "false"),
        "ETL_FRESHNESS_HOURS": _clean_env("ETL_FRESHNESS_HOURS", "168"),
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
