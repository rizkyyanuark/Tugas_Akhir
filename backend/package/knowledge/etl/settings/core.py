"""Core runtime settings for the ETL package.

This module resolves configuration from environment variables only. Airflow
injects values into the DockerOperator environment, while local runs can use a
regular shell or dotenv loader before invoking the worker.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

ETL_PACKAGE_DIR: Final[Path] = Path(__file__).resolve().parents[1]


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"true", "1", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer for %s=%r. Using default=%s.", name, value, default)
        return default


def _running_in_docker() -> bool:
    return (
        env_bool("DOCKER_ENVIRONMENT")
        or env_bool("RUNNING_IN_DOCKER")
        or Path("/app/data").exists()
    )


def _find_project_root() -> Path:
    current = ETL_PACKAGE_DIR
    while current != current.parent:
        if (current / "backend").is_dir():
            return current
        current = current.parent
    return ETL_PACKAGE_DIR


def _resolve_data_dir() -> Path:
    default_path = Path("/app/data") if _running_in_docker() else _find_project_root() / "data"
    return Path(os.environ.get("ETL_DATA_DIR", str(default_path)))


# Base directories.
DATA_DIR: Final[Path] = _resolve_data_dir()
RAW_DATA_DIR: Final[Path] = DATA_DIR / "raw"
PROCESSED_DATA_DIR: Final[Path] = DATA_DIR / "processed"

RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Core infrastructure.
SUPABASE_URL: Final[str] = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY: Final[str] = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL:
    logger.warning("ETL Config: SUPABASE_URL is missing.")
else:
    logger.info("ETL Config: Loaded (Supabase: %s...)", SUPABASE_URL[:30])

# Scraping credentials.
SERPAPI_KEY: Final[str] = os.environ.get("SERPAPI_KEY", "")
SCIVAL_EMAIL: Final[str] = os.environ.get("SCIVAL_EMAIL", "")
SCIVAL_PASS: Final[str] = os.environ.get("SCIVAL_PASS", "")

# BrightData proxy settings.
BD_USER_SERP: Final[str] = os.environ.get("BD_USER_SERP", "")
BD_PASS_SERP: Final[str] = os.environ.get("BD_PASS_SERP", "")
BD_USER_UNLOCKER: Final[str] = os.environ.get("BD_USER_UNLOCKER", "")
BD_PASS_UNLOCKER: Final[str] = os.environ.get("BD_PASS_UNLOCKER", "")
BRIGHTDATA_SERP_TOKEN: Final[str] = os.environ.get("BRIGHTDATA_SERP_TOKEN", "")
BRIGHTDATA_SERP_ZONE: Final[str] = os.environ.get("BRIGHTDATA_SERP_ZONE", "serp_api1")
BRIGHT_DATA_HOST: Final[str] = os.environ.get("BRIGHT_DATA_HOST", "brd.superproxy.io:33335")

# AI / LLM.
GROQ_API_KEY: Final[str] = os.environ.get("GROQ_API_KEY", "")

# Non-secret TLDR behavior is intentionally code-owned so .env/GitHub Secrets
# only need to carry provider keys.
GROQ_TLDR_MODEL: Final[str] = "llama-3.3-70b-versatile"
GROQ_FAST_MODEL: Final[str] = "llama-3.1-8b-instant"
GROQ_TLDR_MAX_SOURCE_CHARS: Final[int] = 2200
GROQ_TLDR_SLEEP_SECONDS: Final[float] = 0.4
GROQ_TLDR_OVERWRITE_EXISTING: Final[bool] = True

# Notification.
NOTIFICATION_EMAIL: Final[str] = os.environ.get("NOTIFICATION_EMAIL", "")

# Crawler settings.
CRAWLER_MAX_RETRIES: Final[int] = env_int("ETL_CRAWLER_MAX_RETRIES", 3)
CRAWLER_TIMEOUT: Final[int] = env_int("ETL_CRAWLER_TIMEOUT", 60)
CRAWLER_HEADLESS: Final[bool] = env_bool("ETL_CRAWLER_HEADLESS", True)

# Shared HTTP headers.
HEADERS: Final[dict[str, str]] = {
    "User-Agent": os.environ.get(
        "ETL_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
}


def _build_proxy_url() -> str:
    if BD_USER_SERP and BD_PASS_SERP and BRIGHT_DATA_HOST:
        return f"http://{BD_USER_SERP}:{BD_PASS_SERP}@{BRIGHT_DATA_HOST}"
    return ""


PROXY_URL: Final[str] = _build_proxy_url()

# Feature flags.
ENABLE_SCIVAL: Final[bool] = env_bool("ETL_ENABLE_SCIVAL", True)
ENABLE_SIAKADU: Final[bool] = env_bool("ETL_ENABLE_SIAKADU", True)
LITE_MODE: Final[bool] = env_bool("LITE_MODE", False)
if LITE_MODE:
    logger.info("ETL running in LITE_MODE (Neo4j disabled).")

# Run behavior.
ETL_RUN_MODE: Final[str] = os.getenv("ETL_RUN_MODE", "incremental").lower()
ETL_SAMPLE_SIZE: Final[int] = env_int("ETL_SAMPLE_SIZE", 50)
ETL_FORCE_EXTRACT: Final[bool] = env_bool("ETL_FORCE_EXTRACT", False)
ETL_FRESHNESS_HOURS: Final[int] = env_int("ETL_FRESHNESS_HOURS", 168)

# Storage bridge.
ETL_STORAGE_TYPE: Final[str] = os.getenv("ETL_STORAGE_TYPE", "local").lower()
AWS_S3_BUCKET: Final[str] = os.getenv("AWS_S3_BUCKET", "")
AWS_S3_PATH: Final[str] = os.getenv("AWS_S3_PATH", "etl/data").strip("/")
AWS_ACCESS_KEY_ID: Final[str] = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY: Final[str] = os.getenv("AWS_SECRET_ACCESS_KEY", "")

SAVE_DIR: Final[Path | str]
if ETL_STORAGE_TYPE == "s3" and AWS_S3_BUCKET:
    SAVE_DIR = f"s3://{AWS_S3_BUCKET}/{AWS_S3_PATH}"
    logger.info("Using AWS S3 storage: %s", SAVE_DIR)
else:
    SAVE_DIR = DATA_DIR
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Using local ETL storage: %s", SAVE_DIR)
