"""
observability.py — Opik Tracing & Observability Wrappers
=========================================================
Wrappers for Opik telemetry and local observation fallback.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from contextlib import contextmanager
from functools import lru_cache
from typing import Any


class NoopObservation:
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = None
    usage: dict[str, Any] | None = None
    model: str | None = None
    provider: str | None = None


def truthy_env(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def opik_project_name() -> str:
    return os.getenv("OPIK_PROJECT_NAME") or os.getenv("OPIK_PROJECT") or "yunesa-academic-graphrag"


def opik_environment() -> str:
    return os.getenv("OPIK_ENVIRONMENT") or os.getenv("ENVIRONMENT") or "development"


def opik_enabled() -> bool:
    if not truthy_env("OPIK_ENABLED", default=True):
        return False
    return bool(os.getenv("OPIK_API_KEY") or os.getenv("OPIK_URL_OVERRIDE") or os.getenv("OPIK_USE_LOCAL"))


@lru_cache(maxsize=1)
def _opik_module() -> Any | None:
    if not opik_enabled():
        return None
    try:
        import opik

        return opik
    except Exception:
        return None


def _opik_metadata(metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "application": "yunesa",
        "component": "academic-graphrag-notebook",
        "environment": opik_environment(),
        **(metadata or {}),
    }


def _opik_tags(tags: list[str] | None = None) -> list[str]:
    merged = ["yunesa", "academic-graphrag", "notebook", opik_environment()]
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
) -> Iterable[Any]:
    opik = _opik_module()
    if opik is None:
        yield NoopObservation()
        return
    try:
        manager = opik.start_as_current_trace(
            name=name,
            input=input,
            metadata=_opik_metadata(metadata),
            tags=_opik_tags(tags),
            thread_id=thread_id,
            project_name=opik_project_name(),
            flush=truthy_env("OPIK_FLUSH", default=False),
        )
    except Exception:
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
) -> Iterable[Any]:
    opik = _opik_module()
    if opik is None:
        yield NoopObservation()
        return
    try:
        manager = opik.start_as_current_span(
            name=name,
            type=type,
            input=input,
            metadata=_opik_metadata(metadata),
            tags=_opik_tags(tags),
            project_name=opik_project_name(),
            model=model,
            provider=provider,
            flush=truthy_env("OPIK_FLUSH", default=False),
        )
    except Exception:
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
    try:
        if output is not None:
            observation.output = output
        if metadata:
            current = getattr(observation, "metadata", None) or {}
            observation.metadata = {**current, **metadata}
        if usage:
            observation.usage = usage
    except Exception:
        return
