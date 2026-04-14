"""Skills middleware for prompt injection, dependency expansion, and dynamic activation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Annotated, Any, NotRequired, TypedDict

from deepagents.middleware.skills import SKILLS_SYSTEM_PROMPT
from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from yunesa.agents.toolkits import get_all_tool_instances
from yunesa.repositories.skill_repository import SkillRepository
from yunesa.services.mcp_service import get_enabled_mcp_tools
from yunesa.services.skill_service import _normalize_string_list, is_valid_skill_slug
from yunesa.storage.postgres.manager import pg_manager
from yunesa.utils.logging_config import logger

# =============================================================================
# Type definitions
# =============================================================================


class SkillPromptMetadata(TypedDict):
    name: str
    description: str
    path: str


class SkillDependencyNode(TypedDict):
    tools: list[str]
    mcps: list[str]
    skills: list[str]


# =============================================================================
# Runtime data loading functions
# =============================================================================


async def _list_skills_from_db(db: AsyncSession | None = None) -> list:
    """Load skill list from the database."""
    if db is not None:
        repo = SkillRepository(db)
        return await repo.list_all()

    async with pg_manager.get_async_session_context() as session:
        repo = SkillRepository(session)
        return await repo.list_all()


async def get_prompt_metadata(db: AsyncSession | None = None) -> dict[str, SkillPromptMetadata]:
    """Get prompt metadata (loaded directly from database)."""
    skills = await _list_skills_from_db(db)
    return {
        item.slug: {
            "name": item.name,
            "description": item.description,
            "path": f"/home/gem/skills/{item.slug}/SKILL.md",
        }
        for item in skills
    }


async def get_dependency_map(db: AsyncSession | None = None) -> dict[str, SkillDependencyNode]:
    """Get dependency mapping (loaded directly from database)."""
    skills = await _list_skills_from_db(db)
    result: dict[str, SkillDependencyNode] = {}
    for item in skills:
        result[item.slug] = {
            "tools": normalize_selected_skills(item.tool_dependencies or []),
            "mcps": normalize_selected_skills(item.mcp_dependencies or []),
            "skills": normalize_selected_skills(item.skill_dependencies or []),
        }
    return result


def normalize_selected_skills(selected_skills: list[str] | None) -> list[str]:
    """Normalize skill list by deduping and filtering invalid values."""
    return _normalize_string_list(selected_skills)


def expand_skill_closure(
    slugs: list[str] | None,
    dependency_map: dict[str, SkillDependencyNode],
) -> list[str]:
    """Expand skill dependency closure and return all transitive dependencies."""
    ordered_roots = normalize_selected_skills(slugs)
    if not ordered_roots:
        return []

    result: list[str] = []
    seen: set[str] = set()

    def dfs(slug: str, stack: set[str]) -> None:
        if slug in stack:
            logger.warning(
                f"Cycle detected in skill dependencies, skip: {' -> '.join([*stack, slug])}")
            return
        if slug in seen:
            return

        node = dependency_map.get(slug)
        if not node:
            logger.warning(
                f"Skill dependency target not found in DB, skip: {slug}")
            return

        seen.add(slug)
        result.append(slug)
        next_stack = set(stack)
        next_stack.add(slug)
        for dep in node.get("skills", []):
            dfs(dep, next_stack)

    for root in ordered_roots:
        dfs(root, set())
    return result


def _activated_skills_reducer(left: list[str] | None, right: list[str] | None) -> list[str]:
    """Merge activated_skills lists."""
    merged: list[str] = []
    seen: set[str] = set()
    for group in (left or [], right or []):
        for value in group:
            if not isinstance(value, str):
                continue
            slug = value.strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            merged.append(slug)
    return merged


class SkillsState(AgentState):
    """Skills state definition."""

    activated_skills: NotRequired[Annotated[list[str],
                                            _activated_skills_reducer]]


class SkillsMiddleware(AgentMiddleware):
    """Skills middleware for prompt injection, dependency expansion, and dynamic activation.

    Responsibilities:
    - Skills prompt injection (directly loaded from database)
    - Dependency expansion (user config + dynamic activation)
    - Dynamic loading of tools/MCP tools
    """

    state_schema = SkillsState

    def __init__(
        self,
        *,
        skills_context_name: str = "skills",
        enable_skills_prompt: bool = True,
        skills_sources_for_prompt: list[str] | None = None,
    ):
        """Initialize middleware.

        Args:
            skills_context_name: Context field name for skills list (default: "skills").
            enable_skills_prompt: Whether to inject skills prompt section (default: True).
            skills_sources_for_prompt: Skill source paths for prompt display (default: ["/home/gem/skills/"]).
        """
        super().__init__()
        self.skills_context_name = skills_context_name
        self.enable_skills_prompt = enable_skills_prompt
        self.skills_sources_for_prompt = skills_sources_for_prompt or [
            "/home/gem/skills/"]

    async def abefore_agent(self, state: SkillsState, runtime) -> dict[str, Any] | None:
        """Inject skills prompt section before agent execution."""
        runtime_context = runtime.context

        # Check whether injection is needed.
        if not self.enable_skills_prompt:
            return None
        if getattr(runtime_context, "_skills_prompt_injected", False):
            return None

        # Load skills data from database (with cache).
        dependency_map = await get_dependency_map()

        # Get configured skills.
        configured_skills = getattr(
            runtime_context, self.skills_context_name, None) or []
        selected_skills = normalize_selected_skills(configured_skills)

        if not selected_skills:
            return None

        # Compute visible_skills.
        visible_skills = expand_skill_closure(selected_skills, dependency_map)

        if not visible_skills:
            return None

        # Collect prompt metadata and build skills section.
        skills_meta = await self._collect_prompt_metadata(visible_skills)
        skills_section = self._build_skills_section(skills_meta)

        # Inject prompt section.
        base_prompt = getattr(runtime_context, "system_prompt", "") or ""
        merged_prompt = f"{base_prompt}\n\n{skills_section}" if base_prompt else skills_section
        setattr(runtime_context, "system_prompt", merged_prompt)
        setattr(runtime_context, "_skills_prompt_injected", True)

        # Store visible_skills for downstream usage.
        setattr(runtime_context, "_visible_skills", visible_skills)

        return None

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        """Wrap model call to handle dynamic activation and dependency expansion."""
        runtime_context = request.runtime.context

        # Load skills data from cache.
        dependency_map = await get_dependency_map()

        # 1. Get configured skills.
        configured_skills = getattr(
            runtime_context, self.skills_context_name, None) or []
        configured = normalize_selected_skills(configured_skills)

        # 2. Get runtime dynamically activated skills.
        state = request.state if isinstance(request.state, dict) else {}
        activated = state.get("activated_skills", []) or []
        if not isinstance(activated, list):
            activated = []

        # 3. Merge and expand closure.
        all_skills = normalize_selected_skills(configured + activated)
        visible_skills = expand_skill_closure(all_skills, dependency_map)

        # 4. Update visible_skills in runtime_context.
        setattr(runtime_context, "_visible_skills", visible_skills)

        # 5. Build dependency bundle from directly activated skills only.
        deps_bundle = await self._build_dependency_bundle(activated)

        # 6. Load dependent tools (regular tools + MCP tools).
        enabled_tools = []

        # 6.1 Load regular tools from toolkits.
        if deps_bundle["tools"]:
            all_tools = get_all_tool_instances()
            required_tool_names = set(deps_bundle["tools"])
            enabled_tools = [
                t for t in all_tools if t.name in required_tool_names]

        # 6.2 Load MCP tools.
        if deps_bundle["mcps"]:
            mcp_tools = await self._get_mcp_tools_from_context(
                runtime_context,
                extra_mcps=deps_bundle["mcps"],
            )
            enabled_tools.extend(mcp_tools)

        # Merge tools: keep existing tools + append new dependency tools.
        if enabled_tools:
            existing_tool_names = {t.name for t in request.tools or []}
            merged_tools = list(request.tools or [])
            for t in enabled_tools:
                if t.name not in existing_tool_names:
                    merged_tools.append(t)
            request = request.override(tools=merged_tools)

        return await handler(request)

    async def _build_dependency_bundle(self, activated_skills: list[str]) -> dict[str, list[str]]:
        """Build dependency bundle from directly activated skills only."""
        dependency_map = await get_dependency_map()

        tools: list[str] = []
        mcps: list[str] = []
        seen_tools: set[str] = set()
        seen_mcps: set[str] = set()

        for slug in activated_skills:
            dep = dependency_map.get(slug, {})
            for tool_name in dep.get("tools", []):
                if tool_name in seen_tools:
                    continue
                seen_tools.add(tool_name)
                tools.append(tool_name)
            for mcp_name in dep.get("mcps", []):
                if mcp_name in seen_mcps:
                    continue
                seen_mcps.add(mcp_name)
                mcps.append(mcp_name)

        return {"tools": tools, "mcps": mcps, "skills": activated_skills}

    async def _collect_prompt_metadata(self, slugs: list[str]) -> list[SkillPromptMetadata]:
        """Collect prompt metadata for specified slugs."""
        prompt_metadata = await get_prompt_metadata()

        result: list[SkillPromptMetadata] = []
        seen: set[str] = set()

        for slug in slugs:
            if not isinstance(slug, str):
                continue
            normalized = slug.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)

            item = prompt_metadata.get(normalized)
            if not item:
                logger.debug(
                    f"Skill slug not found in prompt metadata, skip: {normalized}")
                continue
            result.append(dict(item))

        return result

    async def _get_mcp_tools_from_context(
        self,
        context,
        *,
        extra_mcps: list[str] | None = None,
    ) -> list:
        """Get MCP tools from context configuration."""
        import asyncio

        # MCP tools (loaded in parallel).
        mcps = getattr(context, "mcps", None) or []
        all_mcp_names: list[str] = []
        for server_name in mcps:
            if isinstance(server_name, str):
                all_mcp_names.append(server_name)
        for server_name in extra_mcps or []:
            if isinstance(server_name, str):
                all_mcp_names.append(server_name)

        # Deduplicate.
        unique_mcp_names = list(dict.fromkeys(all_mcp_names))

        async def load_mcp_tools(server_name: str) -> list:
            """Load tools from one MCP server."""
            try:
                mcp_tools = await get_enabled_mcp_tools(server_name)
                if not mcp_tools:
                    logger.warning(
                        f"SkillsMiddleware: mcp dependency unavailable, skip: {server_name}")
                return mcp_tools
            except Exception as e:
                logger.warning(
                    f"SkillsMiddleware: failed to load mcp dependency '{server_name}': {e}")
                return []

        # Load all MCP tools in parallel.
        results = await asyncio.gather(*[load_mcp_tools(name) for name in unique_mcp_names])
        selected_tools = []
        for tools in results:
            selected_tools.extend(tools)

        return selected_tools

    def _process_tool_call_result(self, result: Any, request: ToolCallRequest) -> Any:
        """Process tool call result and handle dynamic skill activation."""
        if request.tool_call.get("name") != "read_file":
            return result

        args = request.tool_call.get("args") or {}
        file_path = args.get("file_path") if isinstance(args, dict) else None
        slug = self._extract_skill_slug_from_skill_md_path(file_path)

        if not slug:
            return result

        if not self._is_visible_skill_slug(request, slug):
            logger.warning(
                f"SkillsMiddleware: deny skill activation for invisible slug: {slug}")
            return result

        logger.debug(f"SkillsMiddleware: activated skill by read_file: {slug}")
        return self._merge_activated_skill_update(result, slug)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ):
        """Wrap tool call and handle dynamic skill activation."""
        result = await handler(request)
        return self._process_tool_call_result(result, request)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ):
        """Synchronous version of tool-call wrapper."""
        result = handler(request)
        return self._process_tool_call_result(result, request)

    def _extract_skill_slug_from_skill_md_path(self, file_path: Any) -> str | None:
        """Extract skill slug from file path."""
        if not isinstance(file_path, str):
            return None
        raw = file_path.strip()
        if not raw:
            return None
        pure = PurePosixPath(raw if raw.startswith("/") else f"/{raw}")
        parts = [p for p in pure.parts if p not in ("/", "")]
        slug: str | None = None
        if (
            len(parts) == 5
            and parts[0] == "home"
            and parts[1] == "gem"
            and parts[2] == "skills"
            and parts[4] == "SKILL.md"
        ):
            slug = parts[3]

        if not is_valid_skill_slug(slug):
            return None
        return slug

    def _is_visible_skill_slug(self, request: ToolCallRequest, slug: str) -> bool:
        """Check whether slug is visible."""
        runtime_context = request.runtime.context
        visible_skills = getattr(runtime_context, "_visible_skills", None)

        if isinstance(visible_skills, list):
            return slug in visible_skills

        # Fallback: check against configured skills.
        configured_skills = getattr(
            runtime_context, self.skills_context_name, None) or []
        normalized = normalize_selected_skills(configured_skills)
        return slug in normalized

    def _merge_activated_skill_update(self, result: Any, slug: str):
        """Merge update for dynamically activated skill."""
        from langchain_core.messages import ToolMessage

        if isinstance(result, Command):
            update = dict(result.update or {})
            current = update.get("activated_skills") or []
            update["activated_skills"] = _activated_skills_reducer(current, [
                                                                   slug])
            return Command(graph=result.graph, update=update, resume=result.resume, goto=result.goto)

        if isinstance(result, ToolMessage):
            return Command(update={"messages": [result], "activated_skills": [slug]})

        return result

    def _format_skills_locations(self, sources: list[str]) -> str:
        """Format skills location information."""
        locations = []
        for i, source_path in enumerate(sources):
            name = PurePosixPath(source_path.rstrip("/")).name.capitalize()
            suffix = " (higher priority)" if i == len(sources) - 1 else ""
            locations.append(f"**{name} Skills**: `{source_path}`{suffix}")
        return "\n".join(locations)

    def _format_skills_list(self, skills_meta: list[dict[str, str]]) -> str:
        """Format skills list."""
        if not skills_meta:
            return f"(No skills available yet. You can create skills in {' or '.join(self.skills_sources_for_prompt)})"

        lines = []
        for skill in skills_meta:
            lines.append(f"- **{skill['name']}**: {skill['description']}")
            lines.append(f"  -> Read `{skill['path']}` for full instructions")
        return "\n".join(lines)

    def _build_skills_section(self, skills_meta: list[dict[str, str]]) -> str:
        """Build skills prompt section."""
        skills_locations = self._format_skills_locations(
            self.skills_sources_for_prompt)
        skills_list = self._format_skills_list(skills_meta)
        return SKILLS_SYSTEM_PROMPT.format(
            skills_locations=skills_locations,
            skills_list=skills_list,
        )
