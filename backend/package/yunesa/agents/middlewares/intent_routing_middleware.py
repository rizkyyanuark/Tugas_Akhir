import hashlib
import time
import json
from collections.abc import Callable, Awaitable
from typing import Any
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage, HumanMessage
from yunesa.agents.models import load_chat_model
from yunesa.utils.logging_config import logger

class IntentRoutingMiddleware(AgentMiddleware):
    """Middleware to perform LLM-based query intent classification and entity extraction before agent execution.

    Analyzes the user query into:
    - intent: graph_search | vector_search | hybrid_search
    - sub_intents: list of specific query sub-types (e.g. collaboration, lecturer_topic)
    - entities: structured academic entities (author_names, department, topics, publication_title)
    - is_enumeration: boolean

    Caches results with a 5-minute TTL per query hash.
    Saves the analyzed payload into the state's routing_metadata.
    """

    _cache: dict[str, tuple[dict[str, Any], float]] = {}  # Class-level cache: {query_hash: (analysis_dict, timestamp)}

    def __init__(self, router_model: str | None = None, cache_ttl: int = 300):
        super().__init__()
        self.router_model_name = router_model
        self.cache_ttl = cache_ttl
        self._router_model = None
        logger.info(f"Initialized IntentRoutingMiddleware with router model: {self.router_model_name}")

    def _get_router_model(self, fallback_model):
        if self._router_model is not None:
            return self._router_model
        if not self.router_model_name:
            return fallback_model
        try:
            self._router_model = load_chat_model(self.router_model_name)
            return self._router_model
        except Exception as e:
            logger.warning(f"Failed to load router model {self.router_model_name}: {e}")
            return fallback_model

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        # Find the last human message (the query)
        last_human = None
        for msg in reversed(messages):
            if getattr(msg, "type", None) == "human" or getattr(msg, "role", None) == "user":
                last_human = msg
                break

        if not last_human:
            return None

        query = str(last_human.content or "").strip()
        if not query:
            return None

        # Check if we already classified this exact query in this state turn
        existing_routing = state.get("routing_metadata") or {}
        if existing_routing.get("classified_query") == query:
            return None

        # Perform intent analysis and entity extraction
        analysis = await self._analyze_query(query, runtime)
        return {
            "routing_metadata": {
                "detected_intent": analysis.get("intent", "hybrid_search"),
                "sub_intents": analysis.get("sub_intents", []),
                "entities": analysis.get("entities", {}),
                "is_enumeration": analysis.get("is_enumeration", False),
                "classified_query": query,
            }
        }

    async def _analyze_query(self, query: str, runtime: Any) -> dict[str, Any]:
        query_hash = hashlib.md5(query.encode("utf-8")).hexdigest()
        now = time.time()

        # Check in-memory cache
        if query_hash in self._cache:
            analysis, ts = self._cache[query_hash]
            if now - ts < self.cache_ttl:
                logger.info(f"Intent routing cache hit for query: '{query[:40]}'")
                return analysis

        fallback_result = {
            "intent": "hybrid_search",
            "sub_intents": [],
            "entities": {
                "author_names": [],
                "department": None,
                "topics": [query],  # fallback generic keyword
                "publication_title": None,
            },
            "is_enumeration": False,
        }

        fallback_model = None
        if hasattr(runtime, "model"):
            fallback_model = runtime.model

        model = self._get_router_model(fallback_model)
        if not model:
            logger.warning("No model available for classification; using fallback analysis dict")
            return fallback_result

        prompt = (
            "You are a query intent analyzer and academic entity extractor for a university knowledge base.\n"
            "Analyze the following query and respond with exactly ONE JSON object matching this schema:\n"
            "{\n"
            '  "intent": "graph_search" | "vector_search" | "hybrid_search",\n'
            '  "sub_intents": ["collaboration" | "lecturer_topic" | "author_publications" | '
            '"topic_frequency" | "publication_details" | <other>],\n'
            '  "entities": {\n'
            '    "author_names": ["Name 1", ...],  # Capitalize first letters if lowercase.\n'
            '    "department": "sains data" | "informatika" | null,\n'
            '    "topics": ["topic 1", ...],  # Fallback to generic keywords if no specific topic found.\n'
            '    "publication_title": "title" | null\n'
            "  },\n"
            '  "is_enumeration": true | false\n'
            "}\n\n"
            f"Query: \"{query}\"\n\n"
            "Respond with ONLY a JSON object. Do not include markdown code block formatting (like ```json)."
        )

        try:
            logger.info(
                f"Intent routing: Analyzing query '{query[:40]}' using "
                f"{self.router_model_name or 'main model'}"
            )
            response = await model.ainvoke([HumanMessage(content=prompt)])
            resp_text = str(response.content).strip()

            # Clean markdown code blocks from response
            if "```" in resp_text:
                parts = resp_text.split("```")
                if len(parts) >= 2:
                    resp_text = parts[1]
                    if resp_text.startswith("json"):
                        resp_text = resp_text[4:]
            resp_text = resp_text.strip()

            data = json.loads(resp_text)
            intent = data.get("intent", "hybrid_search")
            if intent not in ("graph_search", "vector_search", "hybrid_search"):
                data["intent"] = "hybrid_search"

            # Check and clean up entities dict
            if "entities" not in data or not isinstance(data["entities"], dict):
                data["entities"] = fallback_result["entities"]
            else:
                ent = data["entities"]
                if "author_names" not in ent or not isinstance(ent["author_names"], list):
                    ent["author_names"] = []
                if "topics" not in ent or not isinstance(ent["topics"], list):
                    ent["topics"] = [query] if not ent.get("author_names") else []
                if "department" not in ent:
                    ent["department"] = None
                if "publication_title" not in ent:
                    ent["publication_title"] = None

            self._cache[query_hash] = (data, now)
            logger.info(f"Intent routing: Detected intent '{data['intent']}' and entities for query '{query[:40]}'")
            return data
        except Exception as e:
            logger.error(f"Intent routing analysis failure: {e}. Using fallback analysis dict.")
            return fallback_result

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        state = request.state if isinstance(request.state, dict) else {}
        routing_metadata = state.get("routing_metadata") or {}
        intent = routing_metadata.get("detected_intent")
        entities = routing_metadata.get("entities") or {}
        sub_intents = routing_metadata.get("sub_intents") or []

        if intent:
            entities_summary = []
            if entities.get("author_names"):
                entities_summary.append(f"Authors: {', '.join(entities['author_names'])}")
            if entities.get("department"):
                entities_summary.append(f"Department: {entities['department']}")
            if entities.get("topics"):
                entities_summary.append(f"Topics: {', '.join(entities['topics'])}")
            if entities.get("publication_title"):
                entities_summary.append(f"Publication: {entities['publication_title']}")

            summary_str = " | ".join(entities_summary) if entities_summary else "None"

            guidance = (
                f"\n\n[RETRIEVAL INTENT SUGGESTION]\n"
                f"The user's query has been pre-analyzed.\n"
                f"- Detected intent: {intent}\n"
                f"- Sub-intents: {', '.join(sub_intents) if sub_intents else 'None'}\n"
                f"- Extracted Entities: {summary_str}\n"
                f"Recommend retrieval parameters for the query_kb tool:\n"
                f"- For graph_search: use retrieval_mode='subgraph', include_graph=true\n"
                f"- For vector_search: use retrieval_mode='vector', include_graph=false\n"
                f"- For hybrid_search: use retrieval_mode='hybrid', include_graph=true\n"
                f"This is a suggestion — you may override based on the conversation context."
            )
            content_blocks = list(request.system_message.content_blocks) if request.system_message else []
            new_content = content_blocks + [{"type": "text", "text": guidance}]
            new_system_message = SystemMessage(content=new_content)
            request = request.override(system_message=new_system_message)

        return await handler(request)

