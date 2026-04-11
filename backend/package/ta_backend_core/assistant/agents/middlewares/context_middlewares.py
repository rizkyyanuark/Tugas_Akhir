"""Common context-related middlewares"""

from collections.abc import Callable

from langchain.agents.middleware import ModelRequest, ModelResponse, dynamic_prompt, wrap_model_call

from ta_backend_core.assistant.agents import load_chat_model
from ta_backend_core.assistant.utils import logger


@dynamic_prompt
def context_aware_prompt(request: ModelRequest) -> str:
    """Dynamically generate the system prompt from the runtime context"""
    return request.runtime.context.system_prompt


@wrap_model_call
async def context_based_model(request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelResponse:
    """Dynamically select the model from the runtime context"""
    model_spec = request.runtime.context.model
    model = load_chat_model(model_spec)

    request = request.override(model=model)
    logger.debug(
        f"Using model {model_spec} for request {request.messages[-1].content[:200]}")
    return await handler(request)
