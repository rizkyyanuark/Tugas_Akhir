from __future__ import annotations

import logging
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


# Airflow DockerOperator already prefixes streamed container output with its own
# log level, so the ETL line itself avoids a second level prefix like
# "INFO - WARNING | ...".
LOG_FORMAT = "%(name)s | %(message)s"
TRACE_ENV = "ETL_LOG_TRACEBACK"


def configure_etl_logging(level: int = logging.INFO) -> None:
    """Configure concise ETL logs for Airflow and local worker runs."""
    logging.basicConfig(level=level, format=LOG_FORMAT, force=True)


def tracebacks_enabled() -> bool:
    return os.environ.get(TRACE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _clean_value(value: Any, max_length: int = 180) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, Path):
        text = str(value)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_length:
        return f"{text[: max_length - 3]}..."
    return text


def kv(**fields: Any) -> str:
    """Format key/value fields consistently for human-readable log lines."""
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        if value == "":
            continue
        parts.append(f"{key}={_clean_value(value)}")
    return " | ".join(parts)


def log_event(logger: logging.Logger, event: str, message: str = "", **fields: Any) -> None:
    line = event if not message else f"{event}: {message}"
    suffix = kv(**fields)
    logger.info("%s%s", line, f" | {suffix}" if suffix else "")


def log_warning(logger: logging.Logger, event: str, message: str = "", **fields: Any) -> None:
    line = event if not message else f"{event}: {message}"
    suffix = kv(**fields)
    logger.warning("%s%s", line, f" | {suffix}" if suffix else "")


def log_error(
    logger: logging.Logger,
    event: str,
    exc: Exception | None = None,
    message: str = "",
    **fields: Any,
) -> None:
    if exc is not None:
        fields = {
            **fields,
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
    line = event if not message else f"{event}: {message}"
    suffix = kv(**fields)
    logger.error("%s%s", line, f" | {suffix}" if suffix else "", exc_info=tracebacks_enabled())


def result_fields(result: Any) -> dict[str, Any]:
    """Summarize common ETL return values without dumping large payloads."""
    if result is None:
        return {"result": "none"}
    if hasattr(result, "shape") and hasattr(result, "columns"):
        return {"rows": len(result), "columns": len(result.columns)}
    if isinstance(result, dict):
        return result
    if isinstance(result, (str, Path)):
        return {"path": result}
    try:
        return {"records": len(result)}
    except TypeError:
        return {"result": result}


@contextmanager
def timed_event(logger: logging.Logger, event: str, **fields: Any) -> Iterator[None]:
    start = time.perf_counter()
    log_event(logger, f"{event}.start", **fields)
    try:
        yield
    except Exception as exc:
        elapsed = time.perf_counter() - start
        log_error(logger, f"{event}.failed", exc=exc, duration_seconds=elapsed, **fields)
        raise
    else:
        elapsed = time.perf_counter() - start
        log_event(logger, f"{event}.done", duration_seconds=elapsed, **fields)
