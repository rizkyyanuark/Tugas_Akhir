"""Optional Opik instrumentation utilities.

The application must keep running when Opik is not installed or not configured.
These helpers therefore expose no-op context managers by default and only send
traces when observability is explicitly available through environment variables.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import os
from typing import Any, Iterator

from yunesa.utils import logger


class NoopObservation:
    """Small mutable object matching the attributes used on Opik spans/traces."""

    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = None
    usage: dict[str, Any] | None = None
    model: str | None = None
    provider: str | None = None


def _truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def opik_project_name() -> str:
    return (
        os.getenv("OPIK_PROJECT_NAME")
        or os.getenv("OPIK_PROJECT")
        or "yunesa-academic-graphrag"
    )


def opik_environment() -> str:
    return os.getenv("OPIK_ENVIRONMENT") or os.getenv("ENVIRONMENT") or "development"


def opik_enabled() -> bool:
    if not _truthy(os.getenv("OPIK_ENABLED"), default=True):
        return False
    return bool(
        os.getenv("OPIK_API_KEY")
        or os.getenv("OPIK_URL_OVERRIDE")
        or os.getenv("OPIK_USE_LOCAL")
    )


@lru_cache(maxsize=1)
def _opik_module() -> Any | None:
    if not opik_enabled():
        return None
    try:
        import opik

        return opik
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Opik SDK is unavailable; observability disabled: {exc}")
        return None


def _base_metadata(metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "application": "yunesa",
        "component": "academic-graphrag",
        "environment": opik_environment(),
        **(metadata or {}),
    }


def _base_tags(tags: list[str] | None = None) -> list[str]:
    merged = ["yunesa", "academic-graphrag", opik_environment()]
    for tag in tags or []:
        if tag and tag not in merged:
            merged.append(tag)
    return merged


@contextmanager
def opik_trace(
    name: str,
    *,
    input: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    thread_id: str | None = None,
    flush: bool | None = None,
) -> Iterator[Any]:
    opik = _opik_module()
    if opik is None:
        yield NoopObservation()
        return

    try:
        manager = opik.start_as_current_trace(
            name=name,
            input=input,
            metadata=_base_metadata(metadata),
            tags=_base_tags(tags),
            thread_id=thread_id,
            project_name=opik_project_name(),
            flush=_truthy(os.getenv("OPIK_FLUSH"), default=bool(flush)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Opik trace failed for {name}: {exc}")
        yield NoopObservation()
        return

    with manager as trace:
        yield trace


@contextmanager
def opik_span(
    name: str,
    *,
    type: str = "general",
    input: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    model: str | None = None,
    provider: str | None = None,
    flush: bool | None = None,
) -> Iterator[Any]:
    opik = _opik_module()
    if opik is None:
        yield NoopObservation()
        return

    try:
        manager = opik.start_as_current_span(
            name=name,
            type=type,
            input=input,
            metadata=_base_metadata(metadata),
            tags=_base_tags(tags),
            project_name=opik_project_name(),
            model=model,
            provider=provider,
            flush=_truthy(os.getenv("OPIK_FLUSH"), default=bool(flush)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Opik span failed for {name}: {exc}")
        yield NoopObservation()
        return

    with manager as span:
        yield span


def set_observation_output(
    observation: Any,
    *,
    output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
) -> None:
    """Best-effort update for Opik spans/traces and no-op observations."""
    try:
        if output is not None:
            observation.output = output
        if metadata:
            current = getattr(observation, "metadata", None) or {}
            observation.metadata = {**current, **metadata}
        if usage:
            observation.usage = usage
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Failed to update Opik observation: {exc}")
