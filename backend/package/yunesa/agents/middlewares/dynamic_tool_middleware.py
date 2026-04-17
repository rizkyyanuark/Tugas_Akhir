from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from yunesa.services.mcp_service import get_mcp_tools
from yunesa.utils import logger


class DynamicToolMiddleware(AgentMiddleware):
    """Dynamic tool selection middleware with MCP tool preloading and registration.

    Note: all potentially used MCP tools must be preloaded and registered in
    `self.tools` during initialization. Runtime only filters tools by config;
    it does not add new tools dynamically.
    """

    def __init__(self, base_tools: list[Any], mcp_servers: list[str] | None = None):
        """Initialize middleware.

        Args:
            base_tools: Base tool list.
            mcp_servers: MCP server list to preload (optional).
        """
        super().__init__()
        self.tools: list[Any] = base_tools
        self._all_mcp_tools: dict[str, list[Any]] = {}  # All loaded MCP tools.
        self._mcp_servers = mcp_servers or []

    async def initialize_mcp_tools(self) -> None:
        """Async initialization: preload all potentially used MCP tools."""
        for mcp_name in self._mcp_servers:
            if mcp_name not in self._all_mcp_tools:
                logger.info(f"Pre-loading MCP tools from: {mcp_name}")
                mcp_tools = await get_mcp_tools(mcp_name)
                self._all_mcp_tools[mcp_name] = mcp_tools
                # Register MCP tools into middleware.tools.
                self.tools.extend(mcp_tools)
                logger.info(
                    f"Registered {len(mcp_tools)} tools from {mcp_name}")

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        """Dynamically select tools based on config (filtering from registered tools)."""
        # Read config from runtime context.
        selected_tools = request.runtime.context.tools
        selected_mcps = request.runtime.context.mcps

        enabled_tools = []

        # Filter base tools by config.
        if selected_tools and isinstance(selected_tools, list) and len(selected_tools) > 0:
            enabled_tools = [
                tool for tool in self.tools if tool.name in selected_tools]

        # Filter MCP tools by config (select from pre-registered tools).
        if selected_mcps and isinstance(selected_mcps, list) and len(selected_mcps) > 0:
            for mcp in selected_mcps:
                if mcp in self._all_mcp_tools:
                    enabled_tools.extend(self._all_mcp_tools[mcp])
                else:
                    logger.warning(
                        f"MCP server '{mcp}' not pre-loaded. Please add it to mcp_servers list.")

        logger.info(
            f"Dynamic tool selection: {len(enabled_tools)} tools enabled: {[tool.name for tool in enabled_tools]}, "
            f"selected_tools: {selected_tools}, selected_mcps: {selected_mcps}"
        )

        # Update tool list in request.
        request = request.override(tools=enabled_tools)
        return await handler(request)
