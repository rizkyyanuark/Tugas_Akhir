"""Query reformulation middleware to condense chat history and follow-up query into a standalone query."""

from collections.abc import Callable
import os
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage
from yunesa.agents.models import load_chat_model
from yunesa.observability import opik_span, set_observation_output
from yunesa.utils import logger

class QueryReformulationMiddleware(AgentMiddleware):
    """Query reformulation middleware.
    
    If conversation history exists, condenses the history and follow-up query
    into a standalone search query before the LLM is invoked.
    """

    def __init__(self, model_name: str = "groq/llama-3.1-8b-instant"):
        super().__init__()
        self.model_name = model_name
        self._model = None
        logger.info(f"Initialized QueryReformulationMiddleware with model: {self.model_name}")

    def _get_model(self, fallback_model):
        if self._model is not None:
            return self._model
        
        try:
            # Try loading the fast Groq model configured in static/models.py
            self._model = load_chat_model(self.model_name)
            logger.info(f"Loaded query reformulation model: {self.model_name}")
            return self._model
        except Exception as e:
            logger.warning(
                f"Failed to load query reformulation model '{self.model_name}', falling back to main model. Error: {e}"
            )
            # Fallback to the agent's main model if Groq key is missing or model fails to load
            return fallback_model

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        # Check if we have conversation history and the latest message is a user message
        if not request.messages or len(request.messages) <= 1:
            return await handler(request)

        last_message = request.messages[-1]
        msg_type = getattr(last_message, "type", None) or getattr(last_message, "role", None)
        if msg_type != "human":
            return await handler(request)

        # Build conversation history representation
        history_lines = []
        for msg in request.messages[:-1]:
            m_type = getattr(msg, "type", None) or getattr(msg, "role", None)
            m_content = getattr(msg, "content", "")
            if m_type == "human":
                history_lines.append(f"User: {m_content}")
            elif m_type == "ai":
                history_lines.append(f"Assistant: {m_content}")
        
        history_text = "\n".join(history_lines).strip()
        original_query = getattr(last_message, "content", "")
        
        if not original_query or not history_text:
            return await handler(request)

        # Perform query reformulation inside an Opik span for observability
        with opik_span(
            "query_reformulation",
            type="general",
            input={
                "original_query": original_query,
                "history": history_text
            }
        ) as span:
            try:
                reformulation_model = self._get_model(request.model)
                
                prompt = (
                    "Given the following conversation history and a follow-up question, "
                    "rephrase the follow-up question to be a standalone search query in the same language. "
                    "Do NOT answer the question. Output ONLY the rephrased standalone query and nothing else. "
                    "Do not add any introductory or concluding text.\n\n"
                    f"Conversation History:\n{history_text}\n\n"
                    f"Follow-up Question: {original_query}\n\n"
                    "Standalone Query:"
                )
                
                response = await reformulation_model.ainvoke(prompt)
                standalone_query = response.content.strip()
                
                # Basic cleaning of the output (strip quotes)
                if standalone_query.startswith('"') and standalone_query.endswith('"'):
                    standalone_query = standalone_query[1:-1].strip()
                elif standalone_query.startswith("'") and standalone_query.endswith("'"):
                    standalone_query = standalone_query[1:-1].strip()
                
                if standalone_query:
                    logger.info(f"Query reformulated: '{original_query}' -> '{standalone_query}'")
                    # Safe copy: construct a new HumanMessage to replace the last message
                    new_last_message = HumanMessage(
                        content=standalone_query,
                        additional_kwargs=getattr(last_message, "additional_kwargs", {}),
                        response_metadata=getattr(last_message, "response_metadata", {}),
                        id=getattr(last_message, "id", None)
                    )
                    request.messages = list(request.messages[:-1]) + [new_last_message]
                    set_observation_output(span, output={"reformulated_query": standalone_query})
                else:
                    logger.warning("Query reformulation model returned empty result. Keeping original query.")
                    set_observation_output(span, output={"error": "Empty response", "action": "kept_original"})
            except Exception as e:
                logger.error(f"Error during query reformulation: {e}")
                set_observation_output(span, output={"error": str(e), "action": "kept_original"})

        # Proceed with request
        return await handler(request)
