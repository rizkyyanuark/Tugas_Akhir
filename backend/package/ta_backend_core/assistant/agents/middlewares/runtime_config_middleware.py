from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from ta_backend_core.assistant.agents import load_chat_model
from ta_backend_core.assistant.agents.toolkits import get_all_tool_instances
from ta_backend_core.assistant.services.mcp_service import get_enabled_mcp_tools
from ta_backend_core.assistant.utils.datetime_utils import shanghai_now
from ta_backend_core.assistant.utils.logging_config import logger


class RuntimeConfigMiddleware(AgentMiddleware):
    """Runtime configuration middleware — apply model/tools/MCP/prompt overrides.

    Knowledge base tools have been moved to a separate `KnowledgeBaseMiddleware`.
    Skills features have been moved to a separate `SkillsMiddleware`.

    Supports custom context field names so different scenarios (e.g. main agent / subagent)
    can use different configuration fields.
    """

    def __init__(
        self,
        *,
        extra_tools: list[Any] | None = None,
        model_context_name: str = "model",
        system_prompt_context_name: str = "system_prompt",
        tools_context_name: str = "tools",
        knowledges_context_name: str = "knowledges",
        mcps_context_name: str = "mcps",
        enable_model_override: bool = True,
        enable_system_prompt_override: bool = True,
        enable_tools_override: bool = True,
    ):
        """Initialize middleware.

        Args:
            extra_tools: extra tools list (passed from create_agent's tools parameter)
            model_context_name: field name for model in context (default "model")
            system_prompt_context_name: field name for system prompt in context (default "system_prompt")
            tools_context_name: field name for tools list in context (default "tools")
            knowledges_context_name: field name for knowledge bases list in context (default "knowledges")
            mcps_context_name: field name for MCP servers list in context (default "mcps")
            enable_model_override: whether to allow model overrides (default True)
            enable_system_prompt_override: whether to allow system prompt overrides (default True)
            enable_tools_override: whether to allow tools list overrides (default True)
        """
        super().__init__()
        # Store custom field names
        self.model_context_name = model_context_name
        self.system_prompt_context_name = system_prompt_context_name
        self.tools_context_name = tools_context_name
        self.knowledges_context_name = knowledges_context_name
        self.mcps_context_name = mcps_context_name
        # Store override flags
        self.enable_model_override = enable_model_override
        self.enable_system_prompt_override = enable_system_prompt_override
        self.enable_tools_override = enable_tools_override

        self.tools: list[Any] = []
        # Preload tool instances (only when tools override is enabled)
        # Note: knowledge base tools have been moved to a separate KnowledgeBaseMiddleware
        if self.enable_tools_override:
            self.base_tools = get_all_tool_instances()
            self.tools = self.base_tools + (extra_tools or [])
        elif extra_tools:
            logger.warning(
                "RuntimeConfigMiddleware: extra_tools was provided but enable_tools_override=False;"
                " extra_tools will be ignored and no tools override will be applied."
            )

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        runtime_context = request.runtime.context
        overrides: dict[str, Any] = {}

        # 1. Model override (optional)
        if self.enable_model_override:
            model = load_chat_model(
                getattr(runtime_context, self.model_context_name, None))
            overrides["model"] = model

        # 2. Tools override (optional)
        # Note: tools required by Skills are loaded in SkillsMiddleware
        if self.enable_tools_override:
            # Get tools configured in the runtime context
            enabled_tools = await self.get_tools_from_context(runtime_context)
            existing_tools = list(request.tools or [])
            enabled_tool_names = {t.name for t in enabled_tools}
            managed_tool_names = {t.name for t in self.tools}
            merged_tools = []
            for t_bind in existing_tools:
                # (1) Keep tools that are already enabled
                # (2) Keep tools not managed by this middleware
                if t_bind.name in enabled_tool_names or t_bind.name not in managed_tool_names:
                    merged_tools.append(t_bind)
            overrides["tools"] = merged_tools
            logger.debug(
                f"RuntimeConfigMiddleware selected tools: {[t.name for t in merged_tools]}")

        # 3. System prompt override (optional)
        if self.enable_system_prompt_override:
            cur_datetime = f"Current time: {shanghai_now().strftime('%Y-%m-%d %H:%M:%S')} UTC"
            system_prompt = getattr(
                runtime_context, self.system_prompt_context_name, "") or ""
            merged_system_prompt = f"{cur_datetime}\n\n{system_prompt}"

            content_blocks = list(
                request.system_message.content_blocks) if request.system_message else []
            new_content = content_blocks + \
                [{"type": "text", "text": merged_system_prompt}]
            new_system_message = SystemMessage(content=new_content)
            overrides["system_message"] = new_system_message

        if overrides:
            request = request.override(**overrides)

        return await handler(request)

    async def get_tools_from_context(self, context) -> list:
        """Get tools list from context configuration"""
        selected_tools = []
        selected_tool_names: set[str] = set()

        # 1. Base tools (filter from context.tools)
        tools = getattr(context, self.tools_context_name, None) or []
        all_tool_names = []
        for tool_name in tools:
            if isinstance(tool_name, str):
                all_tool_names.append(tool_name)

        tools_map = {t.name: t for t in self.tools}
        for tool_name in all_tool_names:
            if tool_name in selected_tool_names:
                continue
            if tool_name in tools_map:
                selected_tools.append(tools_map[tool_name])
                selected_tool_names.add(tool_name)
                continue
            logger.warning(
                f"RuntimeConfigMiddleware: tool dependency not found, skip: {tool_name}")

        # 2. MCP tools (use unified entry, automatically filter disabled_tools)
        mcps = getattr(context, self.mcps_context_name, None) or []
        all_mcp_names: list[str] = []
        for server_name in mcps:
            if isinstance(server_name, str):
                all_mcp_names.append(server_name)

        selected_mcp_servers: set[str] = set()
        for server_name in all_mcp_names:
            if server_name in selected_mcp_servers:
                continue
            selected_mcp_servers.add(server_name)
            try:
                mcp_tools = await get_enabled_mcp_tools(server_name)
                if not mcp_tools:
                    logger.warning(
                        f"RuntimeConfigMiddleware: mcp dependency unavailable, skip: {server_name}")
                selected_tools.extend(mcp_tools)
            except Exception as e:
                logger.warning(
                    f"RuntimeConfigMiddleware: failed to load mcp dependency '{server_name}': {e}")

        return selected_tools
