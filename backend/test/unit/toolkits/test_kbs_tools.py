from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from yunesa.agents.toolkits.kbs import tools


def _query_kb_callable():
    callback = getattr(tools.query_kb, "coroutine", None)
    if callback is not None:
        return callback

    callback = getattr(tools.query_kb, "func", None)
    if callback is not None:
        return callback

    raise AssertionError("query_kb tool has no callable entry")


def _list_kbs_callable():
    callback = getattr(tools.list_kbs, "coroutine", None)
    if callback is not None:
        return callback

    callback = getattr(tools.list_kbs, "func", None)
    if callback is not None:
        return callback

    raise AssertionError("list_kbs tool has no callable entry")


async def _run_list_kbs(**kwargs):
    callback = _list_kbs_callable()
    result = callback(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def _run_query_kb(**kwargs):
    callback = _query_kb_callable()
    result = callback(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


@pytest.mark.asyncio
async def test_list_kbs_always_exposes_curated_academic_kg(monkeypatch) -> None:
    async def _fake_get_databases_by_raw_id(user_id: str):
        assert user_id == "user-1"
        return {"databases": []}

    monkeypatch.setattr(
        tools.knowledge_base,
        "get_databases_by_raw_id",
        _fake_get_databases_by_raw_id,
    )

    runtime = SimpleNamespace(context=SimpleNamespace(user_id="user-1", knowledges=[]))
    result = await _run_list_kbs(dummy="", runtime=runtime)

    assert result == [
        {
            "name": "yunesa_academic_kg",
            "description": "Curated YUNESA academic knowledge graph stored in Neo4j and Zilliz.",
        }
    ]


@pytest.mark.asyncio
async def test_list_kbs_does_not_duplicate_curated_academic_kg(monkeypatch) -> None:
    async def _fake_get_databases_by_raw_id(user_id: str):
        assert user_id == "user-1"
        return {
            "databases": [
                {
                    "name": "yunesa_academic_kg",
                    "description": "Session-selected academic KG",
                }
            ]
        }

    monkeypatch.setattr(
        tools.knowledge_base,
        "get_databases_by_raw_id",
        _fake_get_databases_by_raw_id,
    )

    runtime = SimpleNamespace(
        context=SimpleNamespace(user_id="user-1", knowledges=["yunesa_academic_kg"])
    )
    result = await _run_list_kbs(dummy="", runtime=runtime)

    assert result == [
        {
            "name": "yunesa_academic_kg",
            "description": "Session-selected academic KG",
        }
    ]


@pytest.mark.asyncio
async def test_query_kb_injects_filepath_into_chunk_metadata(monkeypatch) -> None:
    async def _fake_retriever(query_text: str, **kwargs):
        assert query_text == "auth"
        return [
            {
                "content": "auth guide",
                "metadata": {
                    "file_id": "file-1",
                    "source": "auth-guide.pdf",
                },
            }
        ]

    monkeypatch.setattr(
        tools.knowledge_base,
        "get_retrievers",
        lambda: {
            "db-1": {
                "name": "FAQ",
                "retriever": _fake_retriever,
                "metadata": {"kb_type": "milvus"},
            }
        },
    )

    async def _fake_visible_kbs(runtime):
        return [{"db_id": "db-1", "name": "FAQ"}]

    monkeypatch.setattr(tools, "_resolve_visible_knowledge_bases_for_query", _fake_visible_kbs)

    async def _fake_inject(*, retrieval_chunks, visible_kbs, target_db_id, target_kb_name=None):
        assert visible_kbs == [{"db_id": "db-1", "name": "FAQ"}]
        assert target_db_id == "db-1"
        retrieval_chunks[0]["metadata"]["filepath"] = "/home/gem/kbs/FAQ/API/auth-guide.pdf"
        retrieval_chunks[0]["metadata"]["parsed_path"] = "/home/gem/kbs/FAQ/parsed/API/auth-guide.pdf.md"
        return retrieval_chunks

    monkeypatch.setattr(
        "yunesa.agents.backends.knowledge_base_backend.inject_filepaths_into_retrieval_result",
        _fake_inject,
    )

    runtime = SimpleNamespace(context=SimpleNamespace())
    result = await _run_query_kb(kb_name="FAQ", query_text="auth", retrieval_mode="naive", runtime=runtime)

    assert result[0]["metadata"]["filepath"] == "/home/gem/kbs/FAQ/API/auth-guide.pdf"
    assert result[0]["metadata"]["parsed_path"] == "/home/gem/kbs/FAQ/parsed/API/auth-guide.pdf.md"


@pytest.mark.asyncio
async def test_query_kb_allows_dify_knowledge_base(monkeypatch) -> None:
    async def _fake_retriever(query_text: str, **kwargs):
        assert query_text == "auth"
        return [
            {
                "content": "auth guide",
                "score": 0.98,
                "metadata": {
                    "file_id": "dify-doc-1",
                    "source": "Dify Doc",
                },
            }
        ]

    monkeypatch.setattr(
        tools.knowledge_base,
        "get_retrievers",
        lambda: {
            "db-1": {
                "name": "FAQ",
                "retriever": _fake_retriever,
                "metadata": {"kb_type": "dify"},
            }
        },
    )

    async def _fake_visible_kbs(runtime):
        return [{"db_id": "db-1", "name": "FAQ"}]

    monkeypatch.setattr(tools, "_resolve_visible_knowledge_bases_for_query", _fake_visible_kbs)
    monkeypatch.setattr(
        "yunesa.agents.backends.knowledge_base_backend.inject_filepaths_into_retrieval_result",
        pytest.fail,
    )

    runtime = SimpleNamespace(context=SimpleNamespace())
    result = await _run_query_kb(kb_name="FAQ", query_text="auth", retrieval_mode="naive", runtime=runtime)

    assert result == [
        {
            "content": "auth guide",
            "score": 0.98,
            "metadata": {
                "file_id": "dify-doc-1",
                "source": "Dify Doc",
            },
        }
    ]


@pytest.mark.asyncio
async def test_query_kb_returns_lightrag_result_without_filepath_injection(monkeypatch) -> None:
    async def _fake_retriever(query_text: str, **kwargs):
        assert query_text == "auth"
        return "LightRAG context"

    monkeypatch.setattr(
        tools.knowledge_base,
        "get_retrievers",
        lambda: {
            "db-1": {
                "name": "FAQ",
                "retriever": _fake_retriever,
                "metadata": {"kb_type": "lightrag"},
            }
        },
    )

    async def _fake_visible_kbs(runtime):
        return [{"db_id": "db-1", "name": "FAQ"}]

    monkeypatch.setattr(tools, "_resolve_visible_knowledge_bases_for_query", _fake_visible_kbs)
    monkeypatch.setattr(
        "yunesa.agents.backends.knowledge_base_backend.inject_filepaths_into_retrieval_result",
        pytest.fail,
    )

    runtime = SimpleNamespace(context=SimpleNamespace())
    result = await _run_query_kb(kb_name="FAQ", query_text="auth", retrieval_mode="naive", runtime=runtime)

    assert result == "LightRAG context"


@pytest.mark.asyncio
async def test_query_kb_uses_backend_filepath_injector(monkeypatch) -> None:
    async def _fake_retriever(query_text: str, **kwargs):
        assert query_text == "auth"
        return [
            {
                "content": "auth guide",
                "metadata": {
                    "file_id": "file-1",
                    "source": "auth-guide.pdf",
                },
            }
        ]

    monkeypatch.setattr(
        tools.knowledge_base,
        "get_retrievers",
        lambda: {
            "db-1": {
                "name": "FAQ",
                "retriever": _fake_retriever,
                "metadata": {"kb_type": "milvus"},
            }
        },
    )

    async def _fake_visible_kbs(runtime):
        return [{"db_id": "db-1", "name": "FAQ"}]

    async def _fake_inject(*, retrieval_chunks, visible_kbs, target_db_id, target_kb_name=None):
        assert visible_kbs == [{"db_id": "db-1", "name": "FAQ"}]
        assert target_db_id == "db-1"
        retrieval_chunks[0]["metadata"]["filepath"] = "/home/gem/kbs/FAQ/auth-guide.pdf"
        retrieval_chunks[0]["metadata"]["parsed_path"] = "/home/gem/kbs/FAQ/parsed/auth-guide.pdf.md"
        return retrieval_chunks

    monkeypatch.setattr(tools, "_resolve_visible_knowledge_bases_for_query", _fake_visible_kbs)
    monkeypatch.setattr(
        "yunesa.agents.backends.knowledge_base_backend.inject_filepaths_into_retrieval_result",
        _fake_inject,
    )

    runtime = SimpleNamespace(context=SimpleNamespace())
    result = await _run_query_kb(kb_name="FAQ", query_text="auth", retrieval_mode="naive", runtime=runtime)

    assert result[0]["metadata"]["filepath"] == "/home/gem/kbs/FAQ/auth-guide.pdf"
    assert result[0]["metadata"]["parsed_path"] == "/home/gem/kbs/FAQ/parsed/auth-guide.pdf.md"


@pytest.mark.asyncio
async def test_virtual_academic_kb_preserves_vector_ablation_mode(monkeypatch) -> None:
    monkeypatch.setattr(tools.knowledge_base, "get_retrievers", lambda: {})

    async def _fake_visible_kbs(runtime):
        return []

    async def _fake_build_context(**kwargs):
        assert kwargs["retrieval_mode"] == "vector"
        assert kwargs["include_graph"] is False
        assert kwargs["query_text"] == "retinopati EfficientNet APTOS"
        assert kwargs["original_query_text"] == (
            "Paper apa yang membahas retinopati diabetik dengan EfficientNet dan dataset APTOS?"
        )
        assert kwargs["trace_metadata"]["request_id"] == "request-1"
        return {
            "mode": "vector",
            "query": kwargs["query_text"],
            "chunks": [],
            "academic_retrieval": {"status": "empty", "mode": "vector"},
            "graph": {"status": "skipped", "nodes": [], "edges": [], "triples": []},
            "grounding": {"status": "empty", "answerable": False},
            "evidence_text": "No relevant evidence was found.",
        }

    monkeypatch.setattr(tools, "_resolve_visible_knowledge_bases_for_query", _fake_visible_kbs)
    monkeypatch.setattr(tools, "_build_academic_graphrag_context", _fake_build_context)

    result = await _run_query_kb(
        kb_name="yunesa_academic_kg",
        query_text="retinopati EfficientNet APTOS",
        retrieval_mode="vector",
        include_graph=False,
        runtime=SimpleNamespace(
            context=SimpleNamespace(thread_id="thread-1", user_id="user-1"),
            state={
                "messages": [
                    {
                        "type": "human",
                        "content": (
                            "Paper apa yang membahas retinopati diabetik dengan EfficientNet "
                            "dan dataset APTOS?"
                        ),
                    }
                ]
            },
            config={"metadata": {"request_id": "request-1"}},
        ),
    )

    assert result["mode"] == "vector"
    assert result["grounding"]["status"] == "empty"
