"""
Integration tests for knowledge router and mindmap router endpoints.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _assert_forbidden_response(response):
    """Validate the response format for HTTP 403 Forbidden."""
    assert response.status_code == 403
    payload = response.json()
    assert "detail" in payload
    assert isinstance(payload["detail"], str)


async def test_admin_can_manage_knowledge_databases(test_client, admin_headers, knowledge_database):
    db_id = knowledge_database["db_id"]

    list_response = await test_client.get("/api/knowledge/databases", headers=admin_headers)
    assert list_response.status_code == 200, list_response.text
    databases = list_response.json().get("databases", [])
    assert any(entry["db_id"] == db_id for entry in databases)

    get_response = await test_client.get(f"/api/knowledge/databases/{db_id}", headers=admin_headers)
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["db_id"] == db_id

    update_response = await test_client.put(
        f"/api/knowledge/databases/{db_id}",
        json={"name": knowledge_database["name"],
              "description": "Updated by pytest"},
        headers=admin_headers,
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json(
    )["database"]["description"] == "Updated by pytest"


async def test_create_database_with_chunk_preset(test_client, admin_headers):
    db_name = f"pytest_chunk_preset_{uuid.uuid4().hex[:6]}"
    payload = {
        "database_name": db_name,
        "description": "Chunk preset create test",
        "embed_model_name": "siliconflow/BAAI/bge-m3",
        "kb_type": "milvus",
        "additional_params": {"chunk_preset_id": "book"},
    }

    create_response = await test_client.post("/api/knowledge/databases", json=payload, headers=admin_headers)
    assert create_response.status_code == 200, create_response.text
    db_id = create_response.json()["db_id"]

    info_response = await test_client.get(f"/api/knowledge/databases/{db_id}", headers=admin_headers)
    assert info_response.status_code == 200, info_response.text
    assert info_response.json(
    )["additional_params"]["chunk_preset_id"] == "book"

    delete_response = await test_client.delete(f"/api/knowledge/databases/{db_id}", headers=admin_headers)
    assert delete_response.status_code == 200, delete_response.text


async def test_update_database_additional_params_merge_keeps_chunk_preset(
    test_client, admin_headers, knowledge_database
):
    db_id = knowledge_database["db_id"]

    first_update = await test_client.put(
        f"/api/knowledge/databases/{db_id}",
        json={
            "name": knowledge_database["name"],
            "description": "update with chunk preset",
            "additional_params": {"chunk_preset_id": "qa"},
        },
        headers=admin_headers,
    )
    assert first_update.status_code == 200, first_update.text

    second_update = await test_client.put(
        f"/api/knowledge/databases/{db_id}",
        json={
            "name": knowledge_database["name"],
            "description": "update without additional params",
        },
        headers=admin_headers,
    )
    assert second_update.status_code == 200, second_update.text

    info_response = await test_client.get(f"/api/knowledge/databases/{db_id}", headers=admin_headers)
    assert info_response.status_code == 200, info_response.text
    assert info_response.json()["additional_params"]["chunk_preset_id"] == "qa"


async def test_knowledge_routes_enforce_permissions(test_client, standard_user, knowledge_database):
    db_id = knowledge_database["db_id"]

    forbidden_create = await test_client.post(
        "/api/knowledge/databases",
        json={
            "database_name": "unauthorized_db",
            "description": "Should not succeed",
            "embed_model_name": "siliconflow/BAAI/bge-m3",
        },
        headers=standard_user["headers"],
    )
    _assert_forbidden_response(forbidden_create)

    forbidden_list = await test_client.get("/api/knowledge/databases", headers=standard_user["headers"])
    _assert_forbidden_response(forbidden_list)

    forbidden_get = await test_client.get(f"/api/knowledge/databases/{db_id}", headers=standard_user["headers"])
    _assert_forbidden_response(forbidden_get)


async def test_admin_can_create_vector_db_with_reranker(test_client, admin_headers):
    """Test creating a vector database and configuring reranker options.

    Note: database cleanup is handled automatically by the session fixture in conftest.py.
    """
    db_name = f"pytest_rerank_{uuid.uuid4().hex[:6]}"
    payload = {
        "database_name": db_name,
        "description": "Vector DB with reranker",
        "embed_model_name": "siliconflow/BAAI/bge-m3",
        "kb_type": "milvus",
        "additional_params": {},
    }

    create_response = await test_client.post("/api/knowledge/databases", json=payload, headers=admin_headers)
    assert create_response.status_code == 200, create_response.text

    db_payload = create_response.json()
    db_id = db_payload["db_id"]

    # Get query-parameter configuration
    params_response = await test_client.get(f"/api/knowledge/databases/{db_id}/query-params", headers=admin_headers)
    assert params_response.status_code == 200, params_response.text

    params_payload = params_response.json()
    options = params_payload.get("params", {}).get("options", [])
    option_keys = {option.get("key") for option in options}

    # Validate new parameter keys
    assert "final_top_k" in option_keys
    assert "use_reranker" in option_keys
    assert "recall_top_k" in option_keys
    assert "reranker_model" in option_keys

    # Validate parameter defaults
    final_top_k_option = next(
        (opt for opt in options if opt.get("key") == "final_top_k"), None)
    assert final_top_k_option is not None
    assert final_top_k_option.get("default") == 10

    use_reranker_option = next(
        (opt for opt in options if opt.get("key") == "use_reranker"), None)
    assert use_reranker_option is not None
    assert use_reranker_option.get("default") is False

    # Save query params (simulate frontend configuration)
    update_params = {
        "final_top_k": 5,
        "use_reranker": True,
        "recall_top_k": 20,
    }
    update_response = await test_client.put(
        f"/api/knowledge/databases/{db_id}/query-params", json=update_params, headers=admin_headers
    )
    assert update_response.status_code == 200, update_response.text

    # Fetch parameters again and verify persistence
    params_response2 = await test_client.get(f"/api/knowledge/databases/{db_id}/query-params", headers=admin_headers)
    assert params_response2.status_code == 200, params_response2.text

    params_payload2 = params_response2.json()
    options2 = params_payload2.get("params", {}).get("options", [])

    # Verify persisted values
    final_top_k_option2 = next(
        (opt for opt in options2 if opt.get("key") == "final_top_k"), None)
    assert final_top_k_option2 is not None
    assert final_top_k_option2.get("default") == 5  # persisted value

    use_reranker_option2 = next(
        (opt for opt in options2 if opt.get("key") == "use_reranker"), None)
    assert use_reranker_option2 is not None
    assert use_reranker_option2.get("default") is True  # persisted value


async def test_create_dify_database_success(test_client, admin_headers):
    db_name = f"pytest_dify_{uuid.uuid4().hex[:6]}"
    payload = {
        "database_name": db_name,
        "description": "Dify KB create test",
        "kb_type": "dify",
        "additional_params": {
            "dify_api_url": "https://api.dify.ai/v1",
            "dify_token": "test-token",
            "dify_dataset_id": "dataset-123",
        },
    }

    create_response = await test_client.post("/api/knowledge/databases", json=payload, headers=admin_headers)
    assert create_response.status_code == 200, create_response.text
    db_id = create_response.json()["db_id"]

    info_response = await test_client.get(f"/api/knowledge/databases/{db_id}", headers=admin_headers)
    assert info_response.status_code == 200, info_response.text
    additional_params = info_response.json()["additional_params"]
    assert additional_params["dify_api_url"] == "https://api.dify.ai/v1"
    assert additional_params["dify_token"] == "test-token"
    assert additional_params["dify_dataset_id"] == "dataset-123"


async def test_create_dify_database_missing_params_failed(test_client, admin_headers):
    payload = {
        "database_name": f"pytest_dify_missing_{uuid.uuid4().hex[:6]}",
        "description": "Dify KB missing params",
        "kb_type": "dify",
        "additional_params": {
            "dify_api_url": "https://api.dify.ai/v1",
            "dify_token": "",
            "dify_dataset_id": "",
        },
    }

    response = await test_client.post("/api/knowledge/databases", json=payload, headers=admin_headers)
    assert response.status_code == 400, response.text
    assert "Missing Dify parameters" in response.json()["detail"]


async def test_create_dify_database_invalid_api_url_failed(test_client, admin_headers):
    payload = {
        "database_name": f"pytest_dify_bad_url_{uuid.uuid4().hex[:6]}",
        "description": "Dify KB invalid api url",
        "kb_type": "dify",
        "additional_params": {
            "dify_api_url": "https://api.dify.ai",
            "dify_token": "test-token",
            "dify_dataset_id": "dataset-123",
        },
    }

    response = await test_client.post("/api/knowledge/databases", json=payload, headers=admin_headers)
    assert response.status_code == 400, response.text
    assert "/v1" in response.json()["detail"]


async def test_dify_query_params_and_documents_readonly(test_client, admin_headers):
    payload = {
        "database_name": f"pytest_dify_ro_{uuid.uuid4().hex[:6]}",
        "description": "Dify readonly routes",
        "kb_type": "dify",
        "additional_params": {
            "dify_api_url": "https://api.dify.ai/v1",
            "dify_token": "test-token",
            "dify_dataset_id": "dataset-123",
        },
    }

    create_response = await test_client.post("/api/knowledge/databases", json=payload, headers=admin_headers)
    assert create_response.status_code == 200, create_response.text
    db_id = create_response.json()["db_id"]

    params_response = await test_client.get(f"/api/knowledge/databases/{db_id}/query-params", headers=admin_headers)
    assert params_response.status_code == 200, params_response.text
    options = params_response.json().get("params", {}).get("options", [])
    option_keys = {item.get("key") for item in options}
    assert option_keys == {"search_mode", "final_top_k",
                           "score_threshold_enabled", "similarity_threshold"}

    add_response = await test_client.post(
        f"/api/knowledge/databases/{db_id}/documents",
        json={"items": ["/tmp/demo.txt"], "params": {"content_type": "file"}},
        headers=admin_headers,
    )
    assert add_response.status_code == 400, add_response.text
    assert "Only retrieval is supported" in add_response.json()["detail"]

    parse_response = await test_client.post(
        f"/api/knowledge/databases/{db_id}/documents/parse",
        json=["file_id_1"],
        headers=admin_headers,
    )
    assert parse_response.status_code == 400, parse_response.text
    assert "Only retrieval is supported" in parse_response.json()["detail"]

    index_response = await test_client.post(
        f"/api/knowledge/databases/{db_id}/documents/index",
        json={"file_ids": ["file_id_1"], "params": {}},
        headers=admin_headers,
    )
    assert index_response.status_code == 400, index_response.text
    assert "Only retrieval is supported" in index_response.json()["detail"]


# =============================================================================
# === Mindmap Router Tests ===
# =============================================================================


async def test_get_databases_overview(test_client, admin_headers, knowledge_database):
    """Test retrieving the overview of all knowledge bases."""
    response = await test_client.get("/api/mindmap/databases", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "success"
    assert "databases" in payload
    assert "total" in payload

    # Verify the target knowledge base is listed
    db_ids = [db["db_id"] for db in payload["databases"]]
    assert knowledge_database["db_id"] in db_ids


async def test_get_database_files(test_client, admin_headers, knowledge_database):
    """Test retrieving the file list of a knowledge base."""
    db_id = knowledge_database["db_id"]
    response = await test_client.get(f"/api/mindmap/databases/{db_id}/files", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "success"
    assert payload["db_id"] == db_id
    assert "files" in payload
    assert "total" in payload
    assert payload["db_name"] == knowledge_database["name"]


async def test_get_database_files_not_found(test_client, admin_headers):
    """Test retrieving file list for a non-existent knowledge base."""
    response = await test_client.get("/api/mindmap/databases/nonexistent_db_id/files", headers=admin_headers)
    assert response.status_code == 404


async def test_generate_mindmap_empty_files(test_client, admin_headers, knowledge_database):
    """Test mindmap generation with an empty file list."""
    db_id = knowledge_database["db_id"]
    response = await test_client.post(
        "/api/mindmap/generate",
        json={"db_id": db_id, "file_ids": [], "user_prompt": ""},
        headers=admin_headers,
    )
    # Empty file list should return HTTP 400
    assert response.status_code == 400
    assert "contains no files" in response.json()["detail"]


async def test_get_database_mindmap_not_exists(test_client, admin_headers, knowledge_database):
    """Test retrieving a mindmap when none has been generated yet."""
    db_id = knowledge_database["db_id"]
    response = await test_client.get(f"/api/mindmap/database/{db_id}", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["db_id"] == db_id
    assert payload["mindmap"] is None  # Mindmap has not been generated yet.


async def test_generate_and_get_mindmap(test_client, admin_headers, knowledge_database):
    """Test generating and retrieving a mindmap.

    Note: this test requires existing files in the knowledge base to fully exercise core behavior.
    Since there is no pre-upload fixture yet, it first validates the empty-file scenario (expected 400),
    then skips until upload support is added.
    """
    db_id = knowledge_database["db_id"]

    # Empty-file scenario should return HTTP 400
    generate_response = await test_client.post(
        "/api/mindmap/generate",
        json={"db_id": db_id, "file_ids": [], "user_prompt": ""},
        headers=admin_headers,
    )
    assert generate_response.status_code == 400
    assert "contains no files" in generate_response.json()["detail"]

    # Mark skipped until file-upload support is available for full coverage
    pytest.skip("Files must be uploaded before fully testing mindmap generation")


# =============================================================================
# === Knowledge Router Additional Tests ===
# =============================================================================


async def test_get_accessible_databases(test_client, admin_headers, knowledge_database):
    """Test retrieving the list of accessible knowledge bases."""
    response = await test_client.get("/api/knowledge/databases/accessible", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "databases" in payload

    # Verify the target knowledge base is listed
    db_ids = [db["db_id"] for db in payload["databases"]]
    assert knowledge_database["db_id"] in db_ids


async def test_get_knowledge_base_types(test_client, admin_headers):
    """Test retrieving supported knowledge-base types."""
    response = await test_client.get("/api/knowledge/types", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "success"
    assert "kb_types" in payload


async def test_get_knowledge_base_statistics(test_client, admin_headers):
    """Test retrieving knowledge-base statistics."""
    response = await test_client.get("/api/knowledge/stats", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "success"
    assert "stats" in payload


async def test_get_supported_file_types(test_client, admin_headers):
    """Test retrieving supported file types."""
    response = await test_client.get("/api/knowledge/files/supported-types", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "success"
    assert "file_types" in payload
    assert isinstance(payload["file_types"], list)


async def test_markdown_endpoint_parses_uploaded_text_file(test_client, admin_headers):
    """Test that /files/markdown parses uploaded files and returns markdown."""
    data_dir = Path(__file__).resolve().parents[2] / "data"
    test_file = data_dir / "A_Dream_of_Red_Mansions_10hui.txt"

    assert test_file.exists(), f"Test file does not exist: {test_file}"

    with test_file.open("rb") as f:
        response = await test_client.post(
            "/api/knowledge/files/markdown",
            headers=admin_headers,
            files={"file": (test_file.name, f, "text/plain")},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "success"
    assert isinstance(payload.get("markdown_content"), str)
    assert payload["markdown_content"].strip()


async def test_duplicate_database_name(test_client, admin_headers, knowledge_database):
    """Test creating a duplicate knowledge-base name."""
    db_name = knowledge_database["name"]
    response = await test_client.post(
        "/api/knowledge/databases",
        json={
            "database_name": db_name,
            "description": "Duplicate name test",
            "embed_model_name": "siliconflow/BAAI/bge-m3",
            "kb_type": "lightrag",
            "additional_params": {},
        },
        headers=admin_headers,
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


async def test_create_milvus_knowledge_base(test_client, admin_headers):
    """Test creating a Milvus knowledge base.

    Note: database cleanup is handled automatically by the session fixture in conftest.py.
    """
    db_name = f"pytest_milvus_{uuid.uuid4().hex[:6]}"
    payload = {
        "database_name": db_name,
        "description": "Pytest Milvus knowledge base",
        "embed_model_name": "siliconflow/BAAI/bge-m3",
        "kb_type": "milvus",
        "additional_params": {},
    }

    create_response = await test_client.post("/api/knowledge/databases", json=payload, headers=admin_headers)
    assert create_response.status_code == 200, create_response.text

    db_payload = create_response.json()
    assert db_payload["kb_type"] == "milvus"


async def test_sample_questions_endpoints(test_client, admin_headers, knowledge_database):
    """Test sample-question endpoints (expect 400 when no files exist)."""
    db_id = knowledge_database["db_id"]

    # Get sample questions (empty KB should return an empty list)
    get_response = await test_client.get(f"/api/knowledge/databases/{db_id}/sample-questions", headers=admin_headers)
    assert get_response.status_code == 200, get_response.text
    get_payload = get_response.json()
    assert get_payload["db_id"] == db_id
    assert "questions" in get_payload
    assert get_payload["count"] == 0  # Empty KB has no sample questions.

    # Generate sample questions (empty KB should return 400)
    generate_response = await test_client.post(
        f"/api/knowledge/databases/{db_id}/sample-questions",
        json={"count": 5},
        headers=admin_headers,
    )
    assert generate_response.status_code == 400
    assert "contains no files" in generate_response.json()["detail"]


async def test_mindmap_permissions(test_client, standard_user, knowledge_database):
    """Test permission control on mindmap endpoints."""
    db_id = knowledge_database["db_id"]

    # Standard users should not have access
    forbidden_list = await test_client.get("/api/mindmap/databases", headers=standard_user["headers"])
    _assert_forbidden_response(forbidden_list)

    forbidden_files = await test_client.get(f"/api/mindmap/databases/{db_id}/files", headers=standard_user["headers"])
    _assert_forbidden_response(forbidden_files)

    forbidden_generate = await test_client.post(
        "/api/mindmap/generate",
        json={"db_id": db_id, "file_ids": []},
        headers=standard_user["headers"],
    )
    _assert_forbidden_response(forbidden_generate)
