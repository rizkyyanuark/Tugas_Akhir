"""Knowledge base middleware - provides common knowledge base tools"""

from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from ta_backend_core.assistant.agents.backends.knowledge_base_backend import resolve_visible_knowledge_bases_for_context
from ta_backend_core.assistant.agents.toolkits.kbs import get_common_kb_tools
from ta_backend_core.assistant.utils.logging_config import logger


class KnowledgeBaseMiddleware(AgentMiddleware):
    """Knowledge base middleware - provides common knowledge base tools

    Provides 3 common tools:
    - list_kbs: list knowledge bases accessible to the user
    - get_mindmap: retrieve a mindmap for a specified knowledge base
    - query_kb: query/retrieve information within a specified knowledge base
    """

    def __init__(self):
        super().__init__()
        # Preload common knowledge base tools
        self.kb_tools = get_common_kb_tools()
        self.tools = self.kb_tools
        logger.debug(f"Initialized KnowledgeBaseMiddleware with {len(self.kb_tools)} tools")

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        await resolve_visible_knowledge_bases_for_context(request.runtime.context)
        return await handler(request)
