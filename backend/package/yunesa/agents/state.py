"""Define the state structures for the agent."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain.agents import AgentState


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """Merge artifact file paths while preserving order and removing duplicates."""
    if existing is None:
        return new or []
    if new is None:
        return existing
    return list(dict.fromkeys(existing + new))


def merge_citations(existing: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """Merge citations list."""
    if existing is None:
        return new or []
    if new is None:
        return existing
    # Simple append for now, could be de-duplicated by ID later
    return existing + (new or [])


def merge_files(existing: dict | None, new: dict | None) -> dict:
    """Merge files dictionary."""
    if existing is None:
        return new or {}
    if new is None:
        return existing
    return {**existing, **new}


def merge_routing_metadata(existing: dict | None, new: dict | None) -> dict:
    """Merge routing metadata dictionary."""
    if existing is None:
        return new or {}
    if new is None:
        return existing
    return {**existing, **new}


class BaseState(AgentState):
    """Shared state fields for YUNESA agents."""

    artifacts: Annotated[list[str], merge_artifacts]
    citations: Annotated[list[dict], merge_citations]
    files: Annotated[dict, merge_files]
    routing_metadata: Annotated[dict, merge_routing_metadata]


class AgentStatePayload(TypedDict):
    """Serialized agent state payload consumed by the frontend."""

    todos: list
    files: dict
    artifacts: list[str]
    citations: list[dict]
    routing_metadata: dict

