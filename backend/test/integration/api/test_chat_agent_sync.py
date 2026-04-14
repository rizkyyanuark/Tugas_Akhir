"""
Integration tests for chat_agent_sync non-streaming endpoint.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _get_agent_and_config_id(test_client, headers):
    agents_response = await test_client.get("/api/chat/agent", headers=headers)
    assert agents_response.status_code == 200, agents_response.text
    agents = agents_response.json().get("agents", [])

    if not agents:
        pytest.skip("No agents are registered in the system.")

    agent_id = agents[0].get("id")
    if not agent_id:
        pytest.skip("Agent payload missing id field.")

    configs_response = await test_client.get(f"/api/chat/agent/{agent_id}/configs", headers=headers)
    assert configs_response.status_code == 200, configs_response.text
    configs = configs_response.json().get("configs", [])
    if not configs:
        pytest.skip("No agent configs are available in the system.")

    config_id = configs[0].get("id")
    if not config_id:
        pytest.skip("Agent config payload missing id field.")

    return agent_id, config_id


async def test_chat_agent_sync_requires_authentication(test_client):
    """Non-streaming endpoint requires authentication."""
    response = await test_client.post("/api/chat/agent/sync", json={"query": "hello", "agent_config_id": 1})
    assert response.status_code == 401


async def test_chat_agent_sync_basic_conversation(test_client, admin_headers):
    """Test basic non-streaming conversation behavior."""
    _, agent_config_id = await _get_agent_and_config_id(test_client, admin_headers)

    # Call non-streaming endpoint
    response = await test_client.post(
        "/api/chat/agent/sync",
        json={"query": "Hello, say 'Hi' back to me",
              "agent_config_id": agent_config_id},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()

    # Validate response structure
    assert "status" in payload, f"Missing 'status' in response: {payload}"
    assert payload["status"] in (
        "finished", "error", "interrupted"), f"Unexpected status: {payload['status']}"
    assert "request_id" in payload, f"Missing 'request_id' in response: {payload}"

    # If finished successfully, validate response content
    if payload["status"] == "finished":
        assert "response" in payload, f"Missing 'response' in finished status: {payload}"
        assert isinstance(
            payload["response"], str), f"response should be str, got: {type(payload['response'])}"
        assert len(payload["response"]) > 0, "response should not be empty"
        # thread_id should be present
        assert "thread_id" in payload, f"Missing 'thread_id' in response: {payload}"
        # time_cost should be present
        assert "time_cost" in payload, f"Missing 'time_cost' in response: {payload}"
        assert isinstance(
            payload["time_cost"], float), f"time_cost should be float: {type(payload['time_cost'])}"


async def test_chat_agent_sync_with_thread_id(test_client, admin_headers):
    """Test non-streaming conversation with explicit thread_id."""
    _, agent_config_id = await _get_agent_and_config_id(test_client, admin_headers)

    import uuid

    thread_id = str(uuid.uuid4())

    response = await test_client.post(
        "/api/chat/agent/sync",
        json={
            "query": "Hello",
            "agent_config_id": agent_config_id,
            "thread_id": thread_id,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()

    # Verify thread_id is preserved
    if payload["status"] == "finished":
        assert payload.get("thread_id") == thread_id, (
            f"thread_id mismatch: expected {thread_id}, got {payload.get('thread_id')}"
        )

        threads_response = await test_client.get("/api/chat/threads", headers=admin_headers)
        assert threads_response.status_code == 200, threads_response.text
        threads = threads_response.json()
        target_thread = next(
            (item for item in threads if item.get("id") == thread_id), None)
        assert target_thread is not None, f"thread not found in thread list: {thread_id}"
        assert (target_thread.get("metadata") or {}).get("agent_config_id") == agent_config_id, (
            "agent_config_id mismatch: "
            f"expected {agent_config_id}, got {(target_thread.get('metadata') or {}).get('agent_config_id')}"
        )


async def test_chat_agent_sync_with_meta(test_client, admin_headers):
    """Test non-streaming conversation with meta payload."""
    _, agent_config_id = await _get_agent_and_config_id(test_client, admin_headers)

    import uuid

    request_id = str(uuid.uuid4())

    response = await test_client.post(
        "/api/chat/agent/sync",
        json={
            "query": "Hello",
            "agent_config_id": agent_config_id,
            "meta": {"request_id": request_id},
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()

    # Verify request_id is preserved
    assert payload.get("request_id") == request_id, (
        f"request_id mismatch: expected {request_id}, got {payload.get('request_id')}"
    )


async def test_chat_agent_sync_vs_streaming_consistency(test_client, admin_headers):
    """Comparison test: non-streaming and streaming endpoint consistency."""
    _, agent_config_id = await _get_agent_and_config_id(test_client, admin_headers)

    query = "What is 1+1?"

    # Call streaming endpoint
    import uuid

    thread_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())

    streaming_response = await test_client.post(
        "/api/chat/agent",
        json={
            "query": query,
            "agent_config_id": agent_config_id,
            "thread_id": thread_id,
            "meta": {"request_id": request_id},
        },
        headers=admin_headers,
    )

    assert streaming_response.status_code == 200, streaming_response.text

    # Collect streaming response
    streaming_content = []
    async for line in streaming_response.aiter_lines():
        if line:
            import json as json_lib

            try:
                data = json_lib.loads(line)
                if data.get("response"):
                    streaming_content.append(data["response"])
            except Exception:
                pass

    # Call non-streaming endpoint
    thread_id2 = str(uuid.uuid4())
    request_id2 = str(uuid.uuid4())

    sync_response = await test_client.post(
        "/api/chat/agent/sync",
        json={
            "query": query,
            "agent_config_id": agent_config_id,
            "thread_id": thread_id2,
            "meta": {"request_id": request_id2},
        },
        headers=admin_headers,
    )

    assert sync_response.status_code == 200, sync_response.text
    sync_payload = sync_response.json()

    # Both should succeed
    assert sync_payload["status"] == "finished", f"Sync failed: {sync_payload}"

    # Non-streaming response should contain content
    assert "response" in sync_payload, f"Missing response in sync payload: {sync_payload}"
    assert len(streaming_content) > 0, "Streaming should have collected content"
