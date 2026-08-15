"""Unit tests for production KG vector-write resilience."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import requests


def _load_kg_module():
    repo_root = Path(__file__).resolve().parents[5]
    source = repo_root / "notebooks" / "build-graph" / "src" / "yunesa_academic_kg.py"
    module_name = "yunesa_academic_kg_vector_test"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_utf8_truncation_respects_byte_limit():
    kg = _load_kg_module()
    source = "penelitian–akademik’" * 500

    result = kg._truncate_utf8(source, 4096)

    assert len(result.encode("utf-8")) <= 4096
    assert result.endswith("...")
    assert result.encode("utf-8").decode("utf-8") == result


def test_split_storage_tasks_are_registered():
    from yunesa.etl.worker import TASK_REGISTRY

    assert callable(TASK_REGISTRY["kg_write_neo4j"])
    assert callable(TASK_REGISTRY["kg_write_milvus"])


def test_milvus_preflight_reports_byte_safe_records():
    kg = _load_kg_module()
    value = kg._truncate_milvus("EntityEmbedding", "description", "é" * 4096)
    records = {
        "EntityEmbedding": [
            {
                "graphName": "yunesa_academic_kg",
                "entityName": "Concept",
                "entityType": "ResearchTopic",
                "description": value,
                "nodeId": "concept:1",
                "sourceId": "concept:1",
            }
        ]
    }

    report = kg._validate_milvus_varchar_records(records)

    assert report["rows"] == 1
    assert report["maximum_bytes"]["EntityEmbedding"]["description"] <= 4096


def test_siliconflow_retries_transient_server_error(monkeypatch):
    kg = _load_kg_module()
    calls = []

    class FakeResponse:
        headers = {}

        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

        def json(self):
            return self._payload

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return FakeResponse(500, {})
        return FakeResponse(
            200,
            {"data": [{"index": 0, "embedding": [0.1, 0.2]}]},
        )

    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
    monkeypatch.setenv("SILICONFLOW_EMBEDDING_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("SILICONFLOW_EMBEDDING_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("SILICONFLOW_EMBEDDING_RETRY_MAX_SECONDS", "0")
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(kg.time, "sleep", lambda _: None)

    vectors = kg._siliconflow_embeddings(["academic graph"], model_name="test-model")

    assert vectors == [[0.1, 0.2]]
    assert len(calls) == 2


def test_embedding_cache_reuses_vectors_after_retry(monkeypatch, tmp_path):
    kg = _load_kg_module()
    calls = []

    def fake_embeddings(texts, *, model_name, split_depth=0):
        calls.append(list(texts))
        return [[float(index), 1.0] for index, _ in enumerate(texts)]

    monkeypatch.setenv("YUNESA_EMBEDDING_CACHE_PATH", str(tmp_path / "embeddings.sqlite3"))
    monkeypatch.setattr(kg, "_siliconflow_embeddings", fake_embeddings)
    texts = ["paper one", "paper two", "paper one"]

    first = kg._embed_texts(
        texts,
        provider="siliconflow",
        model_name="test-model",
        batch_size=32,
    )
    second = kg._embed_texts(
        texts,
        provider="siliconflow",
        model_name="test-model",
        batch_size=32,
    )

    assert first == second
    assert len(calls) == 1
    assert calls[0] == ["paper one", "paper two"]
