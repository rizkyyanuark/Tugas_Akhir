from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import SubAgentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware, TodoListMiddleware

from yunesa.agents import BaseAgent, BaseState, load_chat_model
from yunesa.agents.backends import create_agent_composite_backend
from yunesa.agents.middlewares import (
    RuntimeConfigMiddleware,
    SummaryOffloadMiddleware,
    save_attachments_to_fs,
)
from yunesa.agents.middlewares.knowledge_base_middleware import KnowledgeBaseMiddleware
from yunesa.agents.middlewares.skills_middleware import SkillsMiddleware
from yunesa.services.mcp_service import get_tools_from_all_servers
from yunesa.services.subagent_service import get_subagents_from_names

from .prompt import TODO_MID_PROMPT, build_prompt_with_context


async def _build_middlewares(context):
    """Build the middleware list."""
    all_mcp_tools = await get_tools_from_all_servers()  # Async loading cannot be done in RuntimeConfigMiddleware.__init__.

    # summary middleware
    # Main agent context optimization: trigger compression at 90k tokens (70% of 128k context window).
    summary_middleware = SummaryOffloadMiddleware(
        model=load_chat_model(fully_specified_name=context.model),
        trigger=("tokens", getattr(context, "summary_threshold", 100) * 1024),
        trim_tokens_to_summarize=4000,
        summary_offload_threshold=500,
        max_retention_ratio=0.5,
    )

    # subagents
    subagents = await get_subagents_from_names(context.subagents)
    sub_model = load_chat_model(fully_specified_name=context.subagents_model)
    for sa in subagents:
        if not sa.get("model"):
            sa["model"] = sub_model

    subagents_middleware = SubAgentMiddleware(
        subagents=subagents,
        general_purpose_agent=True,
        default_middleware=[
            # Filesystem backend
            FilesystemMiddleware(backend=create_agent_composite_backend),
            PatchToolCallsMiddleware(),
            summary_middleware,
        ],
    )
    # all middlewares
    middlewares = [
        # Filesystem backend
        FilesystemMiddleware(backend=create_agent_composite_backend),
        save_attachments_to_fs,  # Inject attachment context into prompt
        KnowledgeBaseMiddleware(),  # Knowledge-base tools
        # Apply runtime config (model/tools/MCP/prompt)
        RuntimeConfigMiddleware(extra_tools=all_mcp_tools),
        # Skills middleware (prompt injection, dependency expansion, dynamic activation)
        SkillsMiddleware(),
        subagents_middleware,
        summary_middleware,
        # Todo-list middleware
        TodoListMiddleware(system_prompt=TODO_MID_PROMPT),
        PatchToolCallsMiddleware(),
        ModelRetryMiddleware(),  # Model retry middleware
    ]

    return middlewares


class ChatbotAgent(BaseAgent):
    name = "Smart Assistant"
    description = "A basic conversational agent that answers questions and supports configurable tools."
    capabilities = ["file_upload", "files"]  # Supports file upload capability
    metadata = {
        "examples": [
            "Hello, please introduce yourself",
            "Help me write a business email",
            "Explain what machine learning is",
            "Create a Python bubble sort and save the result",
        ]
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def get_graph(self, context=None, **kwargs):

        # Get context configuration.
        context = context or self.context_schema()

        # Create the agent graph using create_agent.
        graph = create_agent(
            model=load_chat_model(fully_specified_name=context.model),
            system_prompt=build_prompt_with_context(context),
            middleware=await _build_middlewares(context),
            state_schema=BaseState,
            checkpointer=await self._get_checkpointer(),
        )

        return graph


def main():
    pass


if __name__ == "__main__":
    main()
    # asyncio.run(main())
