from __future__ import annotations

import asyncio

import pytest

from yunesa.knowledge.graphrag import academic_graphrag
from yunesa.knowledge.graphrag.academic_graphrag import (
    ACADEMIC_COLLECTIONS,
    AcademicGraphRAGService,
)


def test_academic_modes_preserve_reference_semantics() -> None:
    assert AcademicGraphRAGService.normalize_mode("naive") == "vector"
    assert AcademicGraphRAGService.normalize_mode("local") == "subgraph"
    assert AcademicGraphRAGService.normalize_mode("subgraph") == "subgraph"
    assert AcademicGraphRAGService.normalize_mode("global") == "global"
    assert AcademicGraphRAGService.normalize_mode("hybrid") == "hybrid"
    assert AcademicGraphRAGService.normalize_mode("academic") == "mix"

    assert AcademicGraphRAGService.uses_graph("subgraph")
    assert AcademicGraphRAGService.uses_graph("hybrid")
    assert not AcademicGraphRAGService.uses_graph("global")
    assert AcademicGraphRAGService._milvus_db_candidates("default") == ["default"]
    assert AcademicGraphRAGService._milvus_db_candidates("research") == [
        "research",
        None,
    ]


def test_clue_guided_keyword_decomposition_separates_local_and_global_terms() -> None:
    result = AcademicGraphRAGService.decompose_query_keywords(
        "paper retinopati diabetik menggunakan EfficientNet dan dataset APTOS",
        [
            {
                "keywords": (
                    "diabetic retinopathy; EfficientNet; APTOS; "
                    "medical image analysis; artificial intelligence"
                )
            }
        ],
    )

    assert result["provider"] == "heuristic"
    assert "EfficientNet" in result["low_level_keywords"]
    assert "APTOS" in result["low_level_keywords"]
    assert "medical image analysis" in result["high_level_keywords"]


def test_mix_mode_batches_embeddings_and_queries_all_academic_layers(monkeypatch) -> None:
    embedding_calls: list[list[str]] = []
    search_calls: list[tuple[str, str]] = []

    def fake_embed_queries(cls, texts: list[str]) -> dict[str, list[float]]:
        embedding_calls.append(list(texts))
        return {text: [0.1, 0.2] for text in texts}

    async def fake_search(
        cls,
        *,
        query_text: str,
        collection_name: str,
        **kwargs,
    ):
        search_calls.append((collection_name, query_text))
        if collection_name == ACADEMIC_COLLECTIONS["content_keywords"]:
            return [
                {
                    "keywords": "EfficientNet; APTOS; medical image analysis",
                    "sourcePaper": "paper-1",
                }
            ]
        if collection_name == ACADEMIC_COLLECTIONS["paper_chunks"]:
            return [{"title": "Paper A", "content": "Evidence"}]
        if collection_name == ACADEMIC_COLLECTIONS["entities"]:
            return [{"entityName": "EfficientNet", "entityType": "Model"}]
        if collection_name == ACADEMIC_COLLECTIONS["relationships"]:
            return [{"srcId": "paper-1", "relType": "USES_MODEL", "tgtId": "EfficientNet"}]
        return []

    monkeypatch.setattr(
        AcademicGraphRAGService,
        "_embed_queries",
        classmethod(fake_embed_queries),
    )
    monkeypatch.setattr(
        AcademicGraphRAGService,
        "_search_academic_collection",
        classmethod(fake_search),
    )
    monkeypatch.setattr(
        AcademicGraphRAGService,
        "_academic_milvus_enabled",
        staticmethod(lambda: True),
    )
    monkeypatch.setattr(
        AcademicGraphRAGService,
        "_milvus_credentials",
        staticmethod(lambda: ("https://milvus.example", "token", "default")),
    )

    result = asyncio.run(
        AcademicGraphRAGService.query_academic_indexes(
            "paper retinopati diabetik dengan EfficientNet dan APTOS",
            retrieval_mode="mix",
            top_k=5,
        )
    )

    assert result["status"] == "ok"
    assert result["mode"] == "mix"
    assert result["paper_chunks"]
    assert result["keywords"]
    assert result["entities"]
    assert result["relationships"]
    assert result["local_query"] != result["global_query"]
    assert result["diagnostics"]["embedding_batches"] == 2
    assert len(embedding_calls) == 2
    assert {collection for collection, _ in search_calls} == set(ACADEMIC_COLLECTIONS.values())


@pytest.mark.parametrize(
    ("mode", "expected_collection", "excluded_collection"),
    [
        ("subgraph", "EntityEmbedding", "RelationshipEmbedding"),
        ("global", "RelationshipEmbedding", "EntityEmbedding"),
    ],
)
def test_local_and_global_modes_query_different_indexes(
    monkeypatch,
    mode: str,
    expected_collection: str,
    excluded_collection: str,
) -> None:
    searched: list[str] = []

    def fake_embed_queries(cls, texts: list[str]) -> dict[str, list[float]]:
        return {text: [0.1, 0.2] for text in texts}

    async def fake_search(cls, *, collection_name: str, **kwargs):
        searched.append(collection_name)
        if collection_name == "ContentKeyword":
            return [{"keywords": "machine learning; student analytics"}]
        return []

    monkeypatch.setattr(
        AcademicGraphRAGService,
        "_embed_queries",
        classmethod(fake_embed_queries),
    )
    monkeypatch.setattr(
        AcademicGraphRAGService,
        "_search_academic_collection",
        classmethod(fake_search),
    )
    monkeypatch.setattr(
        AcademicGraphRAGService,
        "_academic_milvus_enabled",
        staticmethod(lambda: True),
    )
    monkeypatch.setattr(
        AcademicGraphRAGService,
        "_milvus_credentials",
        staticmethod(lambda: ("https://milvus.example", "token", "default")),
    )

    asyncio.run(
        AcademicGraphRAGService.query_academic_indexes(
            "student analytics",
            retrieval_mode=mode,
        )
    )

    assert expected_collection in searched
    assert excluded_collection not in searched


def test_paper_chunk_normalization_deduplicates_before_limiting() -> None:
    rows = [
        {"title": "Paper A", "content": "Chunk one", "distance": 0.3},
        {"title": "Paper B", "content": "Chunk B", "distance": 0.2},
        {"title": "Paper A", "content": "Chunk two", "distance": 0.1},
    ]

    normalized = AcademicGraphRAGService.normalize_academic_paper_chunks(
        rows,
        max_chunks=2,
    )

    assert [row["source"] for row in normalized] == ["Paper A", "Paper B"]
    assert "Chunk one" in normalized[0]["content"]
    assert "Chunk two" in normalized[0]["content"]


def test_empty_context_is_marked_unanswerable() -> None:
    grounding = AcademicGraphRAGService._grounding_status(
        [],
        {"triples": []},
        {"keywords": [], "entities": [], "relationships": []},
    )
    evidence = AcademicGraphRAGService._compact_evidence_text(
        [],
        {"status": "ok", "triples": []},
        academic={},
        grounding=grounding,
    )

    assert grounding["status"] == "empty"
    assert grounding["answerable"] is False
    assert "do not use model memory" in evidence


def test_search_stage_timeout_returns_empty_rows(monkeypatch) -> None:
    async def slow_search():
        await asyncio.sleep(0.05)
        return [{"title": "too late"}]

    monkeypatch.setattr(
        academic_graphrag,
        "DEFAULT_RETRIEVAL_STAGE_TIMEOUT_SECONDS",
        0.01,
    )

    result = asyncio.run(
        AcademicGraphRAGService._gather_search_results(
            ["paper_chunks"],
            [slow_search()],
        )
    )

    assert result == {"paper_chunks": []}
