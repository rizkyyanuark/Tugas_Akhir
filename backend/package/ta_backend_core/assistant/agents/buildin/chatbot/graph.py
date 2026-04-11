from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import SubAgentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware, TodoListMiddleware

from ta_backend_core.assistant.agents import BaseAgent, BaseState, load_chat_model
from ta_backend_core.assistant.agents.backends import create_agent_composite_backend
from ta_backend_core.assistant.agents.middlewares import (
    RuntimeConfigMiddleware,
    SummaryOffloadMiddleware,
    save_attachments_to_fs,
)
from ta_backend_core.assistant.agents.middlewares.knowledge_base_middleware import KnowledgeBaseMiddleware
from ta_backend_core.assistant.agents.middlewares.skills_middleware import SkillsMiddleware
from ta_backend_core.assistant.services.mcp_service import get_tools_from_all_servers
from ta_backend_core.assistant.services.subagent_service import get_subagents_from_names

from .prompt import TODO_MID_PROMPT, build_prompt_with_context


async def _build_middlewares(context):
    """Build middleware list"""
    all_mcp_tools = await get_tools_from_all_servers()  # Loaded asynchronously, so cannot be placed in RuntimeConfigMiddleware's __init__

    # summary middleware
    # Main Agent context optimization: 90k tokens trigger compression (70% of 128k context window)
    summary_middleware = SummaryOffloadMiddleware(
        model=load_chat_model(fully_specified_name=context.model),
        trigger=("tokens", getattr(context, "summary_threshold", 100) * 1024),
        trim_tokens_to_summarize=4000,
        summary_offload_threshold=500,
        max_retention_ratio=0.5,
    )

    # subagents
    subagents = await get_subagents_from_names(context.subagents)
    subagents_middleware = SubAgentMiddleware(
        default_model=load_chat_model(fully_specified_name=context.subagents_model),
        subagents=subagents,
        general_purpose_agent=True,
        default_middleware=[
            FilesystemMiddleware(backend=create_agent_composite_backend),  # Filesystem backend
            PatchToolCallsMiddleware(),
            summary_middleware,
        ],
    )
    # all middlewares
    middlewares = [
        FilesystemMiddleware(backend=create_agent_composite_backend),  # Filesystem backend
        save_attachments_to_fs,  # Inject attachments into prompt
        KnowledgeBaseMiddleware(),  # Knowledge base tool
        RuntimeConfigMiddleware(extra_tools=all_mcp_tools),  # Apply runtime config (models/tools/MCP/prompts)
        SkillsMiddleware(),  # Skills middleware (prompt injection, dependency resolution, dynamic activation)
        subagents_middleware,
        summary_middleware,
        TodoListMiddleware(system_prompt=TODO_MID_PROMPT),  # Todo list middleware
        PatchToolCallsMiddleware(),
        ModelRetryMiddleware(),  # Model retry middleware
    ]

    return middlewares


class ChatbotAgent(BaseAgent):
    name = "Smart Assistant"
    description = "A basic conversational bot that can answer questions and enable the required tools through configuration."
    capabilities = ["file_upload", "files"]  # Supports file uploads
    metadata = {
        "examples": [
            "Hello, please introduce yourself.",
            "Help me write a business email.",
            "Explain what machine learning is.",
            "Create a Python bubble sort and save the result.",
        ]
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def get_graph(self, context=None, **kwargs):

        context = context or self.context_schema()  # Get context configuration

        # Create the agent using create_agent
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
