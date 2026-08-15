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


DYNAMIC_ENV_PREFIXES = (
    "SUPABASE_",
    "NEO4J_",
    "MILVUS_",
    "YUNESA_",
    "ETL_",
    "SILICONFLOW_",
    "BD_",
    "SCIVAL_",
    "SERPAPI_",
    "GROQ_",
    "HF_",
    "AWS_",
    "OPENROUTER_",
    "TELEGRAM_",
    "SEMANTIC_SCHOLAR_",
    "S2_",
    "OPIK_",
)

EXPLICIT_ENV_KEYS = (
    "SCIVAL_EMAIL",
    "SCIVAL_PASS",
    "SERPAPI_KEY",
    "GROQ_API_KEY",
    "HF_TOKEN",
    "HF_HOME",
    "GLOBAL_PASSWORD",
)


def worker_env() -> dict[str, str]:
    """Dynamically scan and build environment dictionary for etl-worker containers."""
    env_dict: dict[str, str] = {
        # Core container environment settings
        "DOCKER_ENVIRONMENT": "true",
        "DATA_SOURCE_PATH": "/app/data",
        "PYTHONPATH": "/app/package",
        "PYTHONDONTWRITEBYTECODE": "1",
        "ETL_RUN_MODE": ETL_RUN_MODE,
        "ETL_SAMPLE_SIZE": ETL_SAMPLE_SIZE,
        "HF_HOME": _clean_env("HF_HOME", "/app/data/huggingface"),
        "ETL_FRESHNESS_HOURS": _clean_env("ETL_FRESHNESS_HOURS", "72"),
        "ETL_STORAGE_TYPE": _clean_env("ETL_STORAGE_TYPE", "local"),
        "BRIGHT_DATA_HOST": _clean_env("BRIGHT_DATA_HOST", "brd.superproxy.io:33335"),
        "YUNESA_EMBEDDING_CACHE_PATH": _clean_env(
            "YUNESA_EMBEDDING_CACHE_PATH",
            "/app/data/kg/cache/embeddings.sqlite3",
        ),
    }

    # 1. Dynamic Prefix Auto-Scanner (Auto-discovers any current & future env vars)
    for raw_key in os.environ:
        clean_key = raw_key
        if raw_key.startswith("AIRFLOW_VAR_"):
            clean_key = raw_key[len("AIRFLOW_VAR_") :]
            if clean_key.endswith("_SECRET"):
                clean_key = clean_key[: -len("_SECRET")]

        if clean_key.startswith(DYNAMIC_ENV_PREFIXES) or clean_key in EXPLICIT_ENV_KEYS:
            if clean_key not in env_dict or not env_dict[clean_key]:
                val = _clean_env(clean_key)
                if val:
                    env_dict[clean_key] = val

    # 2. Aliases fallback resolution
    if "SUPABASE_SERVICE_ROLE_KEY" not in env_dict:
        svc_key = _clean_env("SUPABASE_SERVICE_ROLE_KEY", _clean_env("SUPABASE_SERVICE_KEY"))
        if svc_key:
            env_dict["SUPABASE_SERVICE_ROLE_KEY"] = svc_key

    if "SEMANTIC_SCHOLAR_API_KEY" not in env_dict:
        s2_key = _clean_env("SEMANTIC_SCHOLAR_API_KEY", _clean_env("S2_API_KEY"))
        if s2_key:
            env_dict["SEMANTIC_SCHOLAR_API_KEY"] = s2_key

    return env_dict

