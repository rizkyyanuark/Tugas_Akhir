"""SubAgent service layer."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from yunesa.repositories.subagent_repository import SubAgentRepository
from yunesa.storage.postgres.manager import pg_manager
from yunesa.utils import logger
from yunesa.utils.paths import OUTPUTS_DIR_NAME

# SubAgent specs cache for get_subagent_specs
_subagent_specs_cache: list[dict[str, Any]] | None = None
_subagent_specs_lock = asyncio.Lock()


@asynccontextmanager
async def _get_session(db: AsyncSession | None = None):
    """Database session context manager."""
    if db is not None:
        yield db
    else:
        async with pg_manager.get_async_session_context() as session:
            yield session


# Built-in SubAgent configurations
_DEFAULT_SUBAGENTS = [
    {
        "name": "research-agent",
        "description": "Use search tools for deeper research questions and write results to a topic research file.",
        "system_prompt": (
            "You are a focused researcher. Your job is to research based on the user's question. "
            "Perform thorough research and reply with a detailed answer. Only your final response will be passed to "
            "the user. They will not see anything else, so your final report must be complete. "
            f"Save research results to the topic research file at {OUTPUTS_DIR_NAME}/sub_research/xxx.md."
        ),
        "tools": ["tavily_search"],
        "is_builtin": True,
    },
    {
        "name": "critique-agent",
        "description": "Review the final report and provide detailed critique guidance.",
        "system_prompt": (
            "You are a focused editor. Your task is to critique a report.\n\n"
            "You can find the report in `final_report.md`.\n\n"
            "You can find the report topic/question in `question.txt`.\n\n"
            "The user may ask you to critique specific aspects. Provide detailed feedback and point out areas for improvement.\n\n"
            "If useful, you may use search tools to gather supporting information.\n\n"
            "Do not write to `final_report.md` yourself.\n\n"
            "Checklist:\n"
            "- Check whether each section title is appropriate\n"
            "- Check whether the writing style resembles a paper or textbook; it should be prose-heavy, not just bullet lists\n"
            "- Check whether the report is comprehensive; point out sections/paragraphs that are too short or missing key details\n"
            "- Check whether it covers key domain areas and avoids major omissions\n"
            "- Check whether it analyzes causes, impacts, and trends deeply enough to provide useful insights\n"
            "- Check whether it stays focused on the research topic and answers the question directly\n"
            "- Check whether structure and language are clear, fluent, and easy to understand"
        ),
        "tools": [],
        "is_builtin": True,
    },
]

_SYNCED_SUBAGENT_FIELDS = (
    "description", "system_prompt", "tools", "model", "is_builtin")


async def init_builtin_subagents() -> None:
    """Initialize built-in SubAgents and sync display fields from code definitions."""
    async with pg_manager.get_async_session_context() as session:
        repo = SubAgentRepository(session)
        for data in _DEFAULT_SUBAGENTS:
            item = await repo.get_by_name(data["name"])
            if item is None:
                await repo.create(
                    name=data["name"],
                    description=data["description"],
                    system_prompt=data["system_prompt"],
                    tools=data.get("tools", []),
                    model=None,
                    is_builtin=data.get("is_builtin", False),
                    created_by="system",
                )
                continue

            changed = False
            for field in _SYNCED_SUBAGENT_FIELDS:
                next_value = data.get(field)
                current_value = getattr(item, field)
                if current_value != next_value:
                    setattr(item, field, deepcopy(next_value))
                    changed = True
            if changed:
                item.updated_by = "system"
        await session.commit()
    clear_specs_cache()


async def get_subagent_specs(db: AsyncSession | None = None) -> list[dict[str, Any]]:
    """Get all subagent specs for SubAgentMiddleware (tool names not resolved yet)."""
    global _subagent_specs_cache
    if _subagent_specs_cache is not None:
        return deepcopy(_subagent_specs_cache)
    async with _subagent_specs_lock:
        if _subagent_specs_cache is not None:
            return deepcopy(_subagent_specs_cache)
        async with _get_session(db) as session:
            repo = SubAgentRepository(session)
            _subagent_specs_cache = await repo.list_all_specs()
    return deepcopy(_subagent_specs_cache)


def clear_specs_cache() -> None:
    """Clear subagent specs cache."""
    global _subagent_specs_cache
    _subagent_specs_cache = None


async def get_subagents_from_names(selected_names: Any, *, db: AsyncSession | None = None) -> list[dict[str, Any]]:
    """Get subagent specs by name (with resolved tool objects)."""
    specs = await get_subagent_specs(db)

    if not selected_names:
        return []

    selected_set = set(selected_names)
    available = {spec["name"]
                 for spec in specs if isinstance(spec.get("name"), str)}

    matched = [spec for spec in specs if spec.get("name") in selected_set]
    missing = [n for n in selected_names if n not in available]
    if missing:
        logger.warning(f"Configured subagents not found, skip: {missing}")

    # Resolve tools.
    # Only resolve tool names from SubAgent configuration; do not do Tavily/MCP special injection.
    from yunesa.agents.toolkits import get_all_tool_instances

    all_tools = get_all_tool_instances()
    all_tool_names = {tool.name: tool for tool in all_tools}
    resolved_specs = []
    for spec in matched:
        resolved_spec = dict(spec)
        tool_names = spec.get("tools", [])
        resolved_spec["tools"] = [all_tool_names[name]
                                  for name in tool_names if name in all_tool_names]
        resolved_specs.append(resolved_spec)

    return resolved_specs


async def get_all_subagents(db: AsyncSession | None = None) -> list[dict[str, Any]]:
    """Get all SubAgents (including disabled ones)."""
    async with _get_session(db) as session:
        repo = SubAgentRepository(session)
        items = await repo.list_all()
    return [item.to_dict() for item in items]


async def get_subagent(name: str, db: AsyncSession | None = None) -> dict[str, Any] | None:
    """Get a single SubAgent."""
    async with _get_session(db) as session:
        repo = SubAgentRepository(session)
        item = await repo.get_by_name(name)
    return item.to_dict() if item else None


async def create_subagent(
    data: dict[str, Any],
    created_by: str | None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """Create SubAgent."""
    async with _get_session(db) as session:
        repo = SubAgentRepository(session)
        item = await repo.create(
            name=data["name"],
            description=data["description"],
            system_prompt=data["system_prompt"],
            tools=data.get("tools"),
            model=data.get("model"),
            is_builtin=False,
            created_by=created_by,
        )
    clear_specs_cache()
    return item.to_dict()


async def update_subagent(
    name: str,
    data: dict[str, Any],
    updated_by: str | None,
    db: AsyncSession | None = None,
) -> dict[str, Any] | None:
    """Update SubAgent."""
    async with _get_session(db) as session:
        repo = SubAgentRepository(session)
        item = await repo.get_by_name(name)
        if not item:
            return None
        if item.is_builtin:
            raise ValueError("Built-in SubAgent cannot be edited")
        item = await repo.update(
            item,
            description=data.get("description"),
            system_prompt=data.get("system_prompt"),
            tools=data.get("tools"),
            model=data.get("model"),
            model_provided="model" in data,
            updated_by=updated_by,
        )
    clear_specs_cache()
    return item.to_dict()


async def delete_subagent(name: str, db: AsyncSession | None = None) -> bool:
    """Delete SubAgent."""
    async with _get_session(db) as session:
        repo = SubAgentRepository(session)
        item = await repo.get_by_name(name)
        if not item:
            return False
        if item.is_builtin:
            raise ValueError("Built-in SubAgent cannot be deleted")
        await repo.delete(item)
    clear_specs_cache()
    return True


async def set_subagent_enabled(
    name: str,
    enabled: bool,
    *,
    updated_by: str | None,
    db: AsyncSession | None = None,
) -> dict[str, Any] | None:
    """Update SubAgent enabled status."""
    async with _get_session(db) as session:
        repo = SubAgentRepository(session)
        item = await repo.get_by_name(name)
        if not item:
            return None
        item.enabled = enabled
        item.updated_by = updated_by
        await session.commit()
        await session.refresh(item)
    clear_specs_cache()
    return item.to_dict()
