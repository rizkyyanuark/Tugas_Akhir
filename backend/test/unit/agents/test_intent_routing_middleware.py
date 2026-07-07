import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain.agents.middleware import ModelRequest, ModelResponse
from yunesa.agents.middlewares.intent_routing_middleware import IntentRoutingMiddleware

@pytest.mark.asyncio
async def test_intent_routing_analysis_success() -> None:
    # Arrange
    query = "Dosen prodi sains data"
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=AIMessage(content='{"intent": "graph_search", "sub_intents": ["lecturer_topic"], "entities": {"author_names": ["Budi"], "topics": ["data science"]}, "is_enumeration": false}'))
    
    IntentRoutingMiddleware._cache.clear()
    middleware = IntentRoutingMiddleware(router_model="test-model")
    middleware._router_model = mock_model
    
    # Act
    analysis = await middleware._analyze_query(query, MagicMock())
    
    # Assert
    assert analysis["intent"] == "graph_search"
    assert "lecturer_topic" in analysis["sub_intents"]
    assert analysis["entities"]["author_names"] == ["Budi"]
    mock_model.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_intent_routing_analysis_invalid_json_fallback() -> None:
    # Arrange
    query = "Dosen prodi sains data"
    mock_model = MagicMock()
    # Invalid JSON output
    mock_model.ainvoke = AsyncMock(return_value=AIMessage(content='invalid json'))
    
    IntentRoutingMiddleware._cache.clear()
    middleware = IntentRoutingMiddleware(router_model="test-model")
    middleware._router_model = mock_model
    
    # Act
    analysis = await middleware._analyze_query(query, MagicMock())
    
    # Assert
    assert analysis["intent"] == "hybrid_search"
    assert analysis["entities"]["topics"] == [query]


@pytest.mark.asyncio
async def test_intent_routing_cache_ttl() -> None:
    # Arrange
    query = "Jelaskan konsep deep learning"
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=AIMessage(content='{"intent": "vector_search", "entities": {"topics": ["deep learning"]}}'))
    
    IntentRoutingMiddleware._cache.clear()
    middleware = IntentRoutingMiddleware(router_model="test-model", cache_ttl=5)
    middleware._router_model = mock_model
    
    # Act - 1st call (should hit the model)
    analysis1 = await middleware._analyze_query(query, MagicMock())
    
    # Act - 2nd call (should hit cache)
    analysis2 = await middleware._analyze_query(query, MagicMock())
    
    # Assert
    assert analysis1["intent"] == "vector_search"
    assert analysis2["intent"] == "vector_search"
    assert mock_model.ainvoke.call_count == 1
    
    # Act - expire cache
    middleware._cache[next(iter(middleware._cache))] = (analysis1, time.time() - 10)
    analysis3 = await middleware._analyze_query(query, MagicMock())
    
    # Assert
    assert analysis3["intent"] == "vector_search"
    assert mock_model.ainvoke.call_count == 2


@pytest.mark.asyncio
async def test_intent_routing_abefore_model_state_update() -> None:
    # Arrange
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=AIMessage(content='{"intent": "graph_search", "sub_intents": ["collaboration"], "entities": {"author_names": ["Budi"]}}'))
    
    IntentRoutingMiddleware._cache.clear()
    middleware = IntentRoutingMiddleware(router_model="test-model")
    middleware._router_model = mock_model
    
    state = {
        "messages": [HumanMessage(content="Dosen prodi sains data")],
        "routing_metadata": {}
    }
    
    # Act
    updates = await middleware.abefore_model(state, MagicMock())
    
    # Assert
    assert updates is not None
    assert updates["routing_metadata"]["detected_intent"] == "graph_search"
    assert updates["routing_metadata"]["sub_intents"] == ["collaboration"]
    assert updates["routing_metadata"]["entities"]["author_names"] == ["Budi"]
    assert updates["routing_metadata"]["classified_query"] == "Dosen prodi sains data"


@pytest.mark.asyncio
async def test_intent_routing_awrap_model_call_prompt_injection() -> None:
    # Arrange
    middleware = IntentRoutingMiddleware(router_model="test-model")
    
    request = ModelRequest(
        messages=[HumanMessage(content="Dosen prodi sains data")],
        system_message=SystemMessage(content="You are a helpful assistant."),
        tools=[],
        model="gpt-4o",
        state={
            "routing_metadata": {
                "detected_intent": "graph_search",
                "sub_intents": ["collaboration"],
                "entities": {"author_names": ["Budi Santoso"]},
                "classified_query": "Dosen prodi sains data"
            }
        },
        runtime=MagicMock()
    )
    
    async def mock_handler(req: ModelRequest) -> ModelResponse:
        return ModelResponse(result=[AIMessage(content="Response")])
    
    # Act
    response = await middleware.awrap_model_call(request, mock_handler)
    
    # To check request modifications, we intercept the handler
    captured_request = None
    async def capture_handler(req: ModelRequest) -> ModelResponse:
        nonlocal captured_request
        captured_request = req
        return ModelResponse(result=[AIMessage(content="Response")])
        
    await middleware.awrap_model_call(request, capture_handler)
    
    # Assert
    assert captured_request is not None
    system_text = str(captured_request.system_message.content)
    assert "[RETRIEVAL INTENT SUGGESTION]" in system_text
    assert "Detected intent: graph_search" in system_text
    assert "Sub-intents: collaboration" in system_text
    assert "Extracted Entities: Authors: Budi Santoso" in system_text
    assert "graph_search: use retrieval_mode='subgraph'" in system_text



