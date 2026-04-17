"""Knowledge base middleware providing common KB tools."""

from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from yunesa.agents.backends.knowledge_base_backend import resolve_visible_knowledge_bases_for_context
from yunesa.agents.toolkits.kbs import get_common_kb_tools
from yunesa.utils.logging_config import logger


class KnowledgeBaseMiddleware(AgentMiddleware):
    """Knowledge base middleware providing common KB tools.

    Provides 3 generic tools:
    - list_kbs: list user-accessible knowledge bases
    - get_mindmap: get mindmap of a specified knowledge base
    - query_kb: retrieve content from a specified knowledge base
    """

    def __init__(self):
        super().__init__()
        # Preload common KB tools.
        self.kb_tools = get_common_kb_tools()
        self.tools = self.kb_tools
        logger.debug(
            f"Initialized KnowledgeBaseMiddleware with {len(self.kb_tools)} tools")

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        await resolve_visible_knowledge_bases_for_context(request.runtime.context)
        return await handler(request)
