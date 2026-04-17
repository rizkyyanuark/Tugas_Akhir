from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import SubAgentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import (
    TodoListMiddleware,
    ToolCallLimitMiddleware,
)

from yunesa.agents import BaseAgent, BaseState, load_chat_model
from yunesa.agents.backends import create_agent_composite_backend
from yunesa.agents.middlewares import (
    RuntimeConfigMiddleware,
    SummaryOffloadMiddleware,
    save_attachments_to_fs,
)
from yunesa.agents.middlewares.knowledge_base_middleware import KnowledgeBaseMiddleware
from yunesa.agents.middlewares.skills_middleware import SkillsMiddleware
from yunesa.agents.toolkits.buildin.tools import _create_tavily_search
from yunesa.services.mcp_service import get_tools_from_all_servers
from yunesa.services.subagent_service import get_subagents_from_names
from yunesa.utils import logger

from .prompt import DEEP_PROMPT


class DeepAgent(BaseAgent):
    name = "Deep Analysis"
    description = "An agent with planning, deep analysis, and sub-agent collaboration capabilities for complex multi-step tasks"
    capabilities = ["file_upload", "files"]  # Supports file upload capability
    metadata = {"examples": ["Research papers related to multimodal GraphRAG"]}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.graph = None
        self.checkpointer = None

    async def get_tools(self):
        """Return Deep Agent specific tools."""
        from yunesa import config

        tools = []
        if config.enable_web_search:
            tavily = _create_tavily_search()
            if tavily:
                tools.append(tavily)

        if not tools:
            logger.warning(
                "No search tools configured, DeepAgent will work without web search")
        return tools

    async def get_graph(self, context=None, **kwargs):

        # Get context configuration.
        context = context or self.context_schema()
        system_prompt = f"{DEEP_PROMPT.strip()}\n\n{context.system_prompt or ''}"

        model = load_chat_model(context.model)
        sub_model = load_chat_model(context.subagents_model)
        search_tools = await self.get_tools()
        all_mcp_tools = await get_tools_from_all_servers()
        # Merge search tools and MCP tools.

        # Load subagent specs from DB (tool names already resolved).
        user_subagents = await get_subagents_from_names(context.subagents)

        # Main agent context optimization: trigger compression at 90k tokens (70% of 128k context window).
        summary_middleware = SummaryOffloadMiddleware(
            model=model,
            trigger=("tokens", 90000),
            trim_tokens_to_summarize=4000,
            summary_offload_threshold=500,
            max_retention_ratio=0.5,
        )

        subagents_middleware = SubAgentMiddleware(
            default_model=sub_model,
            default_tools=search_tools,
            subagents=user_subagents,
            default_middleware=[
                # Filesystem backend
                FilesystemMiddleware(backend=create_agent_composite_backend),
                PatchToolCallsMiddleware(),
                summary_middleware,
                # Sub-agent search tool limit: tavily_search at most 8 times.
                ToolCallLimitMiddleware(
                    tool_name="tavily_search",
                    run_limit=8,
                    exit_behavior="continue",
                ),
            ],
            general_purpose_agent=True,
        )

        # Create deep agent graph using create_agent.
        graph = create_agent(
            model=model,
            system_prompt=system_prompt,
            middleware=[
                # Filesystem backend
                FilesystemMiddleware(backend=create_agent_composite_backend),
                RuntimeConfigMiddleware(extra_tools=all_mcp_tools),
                # Skills middleware (prompt injection, dependency expansion, dynamic activation)
                SkillsMiddleware(),
                save_attachments_to_fs,  # Inject attachment context into prompt
                TodoListMiddleware(
                    system_prompt="Before ending the task, check whether the maintained todo list is completed."),
                PatchToolCallsMiddleware(),
                KnowledgeBaseMiddleware(),  # Knowledge-base tools
                subagents_middleware,
                summary_middleware,
                # Tool call limit: tavily_search at most 20 calls per thread.
                ToolCallLimitMiddleware(
                    tool_name="tavily_search",
                    thread_limit=20,
                    exit_behavior="continue",
                ),
                # Total tool-call round limit: prevent infinite loops in a single run.
                ToolCallLimitMiddleware(
                    run_limit=50,
                    exit_behavior="end",
                ),
            ],
            state_schema=BaseState,
            checkpointer=await self._get_checkpointer(),
        )

        return graph
