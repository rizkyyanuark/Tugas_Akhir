from __future__ import annotations

import asyncio
import json

import pytest

from yunesa.knowledge.graphrag import academic_graphrag
from yunesa.knowledge.graphrag.academic_graphrag import (
    ACADEMIC_COLLECTIONS,
    AcademicGraphRAGService,
)
from yunesa.knowledge.graphrag.query_planner import AcademicQueryParam, AcademicQueryPlanner
from yunesa.knowledge.graphrag.storage import normalize_milvus_uri
from yunesa.agents.toolkits.kbs.tools import _academic_tool_response


def test_academic_modes_preserve_reference_semantics() -> None:
    assert AcademicGraphRAGService.normalize_mode("naive") == "vector"
    assert AcademicGraphRAGService.normalize_mode("local") == "subgraph"
    assert AcademicGraphRAGService.normalize_mode("subgraph") == "subgraph"
    assert AcademicGraphRAGService.normalize_mode("global") == "global"
    assert AcademicGraphRAGService.normalize_mode("hybrid") == "hybrid"
    assert AcademicGraphRAGService.normalize_mode("academic") == "hybrid"

    assert AcademicGraphRAGService.uses_graph("subgraph")
    assert AcademicGraphRAGService.uses_graph("hybrid")
    assert not AcademicGraphRAGService.uses_graph("global")
    assert AcademicGraphRAGService._milvus_db_candidates("default") == [None, "default"]
    assert AcademicGraphRAGService._milvus_db_candidates("research") == [
        "research",
        None,
    ]


def test_default_mix_routes_structured_academic_queries() -> None:
    author_route = AcademicGraphRAGService.route_retrieval_mode(
        "Apa saja paper yang ditulis oleh Yuni Yamasari?",
        requested_mode="mix",
    )
    assert author_route["effective_mode"] == "hybrid"
    assert author_route["auto_routed"] is False
    assert author_route["reason"] == "llm_router_active"

    lecturer_topic_route = AcademicGraphRAGService.route_retrieval_mode(
        "Dosen S2 Informatika mana yang menulis paper tentang machine learning di bidang pendidikan?",
        requested_mode="mix",
    )
    assert lecturer_topic_route["effective_mode"] == "hybrid"
    assert lecturer_topic_route["intents"]["lecturer_topic_publications"] is True

    factual_route = AcademicGraphRAGService.route_retrieval_mode(
        "Paper apa yang membahas retinopati diabetik dengan EfficientNet dan dataset APTOS?",
        requested_mode="mix",
    )
    assert factual_route["effective_mode"] == "hybrid"
    assert factual_route["auto_routed"] is False

    explicit_vector_route = AcademicGraphRAGService.route_retrieval_mode(
        "Apa paper tentang EfficientNet?",
        requested_mode="vector",
    )
    assert explicit_vector_route["effective_mode"] == "vector"
    assert explicit_vector_route["auto_routed"] is False


def test_normalize_milvus_uri_uses_explicit_https_port() -> None:
    assert (
        normalize_milvus_uri("https://example.serverless.zilliz.com")
        == "https://example.serverless.zilliz.com:443"
    )
    assert (
        normalize_milvus_uri("https://example.serverless.zilliz.com:8443")
        == "https://example.serverless.zilliz.com:8443"
    )
    assert normalize_milvus_uri("http://milvus:19530") == "http://milvus:19530"


def test_query_param_maps_yunesa_runtime_modes_to_academicrag_modes() -> None:
    vector_param = AcademicQueryParam.from_runtime("vector", top_k=5, keyword_top_k=3)
    assert vector_param.runtime_mode == "vector"
    assert vector_param.mode == "naive"
    assert vector_param.retrieval_layers()["raw_vector"] is True
    assert vector_param.retrieval_layers()["clues"] is False
    assert vector_param.route_plan()["steps"] == [
        "naive_vector_query",
        "rrf_fusion",
        "cross_encoder_rerank",
        "naive_rag_response",
    ]

    mix_param = AcademicQueryParam.from_runtime("mix", top_k=5, keyword_top_k=3)
    mix_param.with_keywords(
        high_level_keywords=["machine learning"],
        low_level_keywords=["Yuni Yamasari"],
    )
    assert mix_param.mode == "hybrid"
    assert mix_param.resolved_kg_mode() == "hybrid"
    assert mix_param.retrieval_layers()["local"] is True
    assert mix_param.retrieval_layers()["global"] is True
    assert mix_param.route_plan()["steps"] == [
        "content_keyword_query",
        "keyword_extraction",
        "naive_vector_query",
        "subgraph_entity_query",
        "global_relationship_query",
        "rrf_fusion",
        "cross_encoder_rerank",
        "rag_response",
    ]

    subgraph_fallback = AcademicQueryParam.from_runtime("subgraph", top_k=5, keyword_top_k=3)
    subgraph_fallback.with_keywords(
        high_level_keywords=["education"],
        low_level_keywords=[],
    )
    assert subgraph_fallback.resolved_kg_mode() == "global"
    assert subgraph_fallback.route_plan()["steps"] == [
        "content_keyword_query",
        "keyword_extraction",
        "global_relationship_query",
        "rrf_fusion",
        "cross_encoder_rerank",
        "rag_response",
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

    assert result["provider"] == "academicrag_heuristic"
    assert "EfficientNet" in result["low_level_keywords"]
    assert "APTOS" in result["low_level_keywords"]
    assert "medical image analysis" in result["high_level_keywords"]
    assert "high_level_keywords" in result["prompt"]
    assert result["intents"]["lecturer_topic_publications"] is False


def test_query_planner_builds_academicrag_style_prompt_and_intents() -> None:
    plan = AcademicQueryPlanner.decompose_keywords(
        "Dosen S2 Informatika mana yang menulis paper tentang machine learning di bidang pendidikan?",
        [{"keywords": "machine learning; education; student performance"}],
    )

    assert plan.provider == "academicrag_heuristic"
    assert "Current Query:" in plan.prompt
    assert "Database Content Keywords:" in plan.prompt
    assert "high_level_keywords" in plan.prompt
    assert "low_level_keywords" in plan.prompt
    assert plan.intents["lecturer_topic_publications"] is True
    assert "machine learning" in plan.high_level_keywords + plan.low_level_keywords


def test_query_planner_parses_academicrag_keyword_json_response() -> None:
    plan = AcademicQueryPlanner.plan_from_model_response(
        query_text="paper EfficientNet APTOS",
        keyword_rows=[{"keywords": "EfficientNet; APTOS; medical image analysis"}],
        raw_response=(
            "Output:\n"
            '{"high_level_keywords": ["medical image analysis"], '
            '"low_level_keywords": ["EfficientNet", "APTOS"]}'
        ),
    )

    assert plan is not None
    assert plan.provider == "academicrag_llm"
    assert plan.high_level_keywords == ["medical image analysis"]
    assert plan.low_level_keywords == ["EfficientNet", "APTOS"]
    assert "Database Content Keywords:" in plan.prompt


def test_mix_mode_can_use_academicrag_llm_keyword_extractor(monkeypatch) -> None:
    search_calls: list[tuple[str, str]] = []
    captured_prompt = ""

    def fake_embed_queries(cls, texts: list[str]) -> dict[str, list[float]]:
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
        return []

    async def fake_keyword_extractor(prompt: str) -> str:
        nonlocal captured_prompt
        captured_prompt = prompt
        return (
            '{"high_level_keywords": ["medical image analysis"], '
            '"low_level_keywords": ["EfficientNet", "APTOS"]}'
        )

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
            keyword_extractor=fake_keyword_extractor,
        )
    )

    assert "Database Content Keywords:" in captured_prompt
    assert result["keyword_decomposition"]["provider"] == "academicrag_llm"
    assert result["local_query"] == "EfficientNet, APTOS"
    assert result["global_query"] == "medical image analysis"
    assert result["kg_mode"] == "hybrid"
    assert (ACADEMIC_COLLECTIONS["entities"], "EfficientNet, APTOS") in search_calls
    assert (
        ACADEMIC_COLLECTIONS["relationships"],
        "medical image analysis",
    ) in search_calls


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
            return [{"entityName": "EfficientNet", "entityType": "Model", "nodeId": "node-1"}]
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
    assert result["mode"] == "hybrid"
    assert result["academicrag_mode"] == "hybrid"
    assert result["kg_mode"] == "hybrid"
    assert result["route_plan"]["steps"][-1] == "rag_response"
    assert "subgraph_entity_query" in result["route_plan"]["steps"]
    assert "global_relationship_query" in result["route_plan"]["steps"]
    assert result["paper_chunks"]
    assert result["keywords"]
    assert result["entities"]
    assert result["relationships"]
    assert result["local_query"] != result["global_query"]
    assert result["diagnostics"]["embedding_batches"] == 2
    assert len(embedding_calls) == 2
    assert {collection for collection, _ in search_calls} == set(ACADEMIC_COLLECTIONS.values()) | {"community_summaries"}


def test_mix_mode_uses_entity_ids_for_shortest_path_and_pruning(monkeypatch) -> None:
    class FakeVectorStorage:
        async def query(self, query_text: str, *, collection_name: str, **kwargs):
            if collection_name == ACADEMIC_COLLECTIONS["content_keywords"]:
                return [{"keywords": "EfficientNet; APTOS; medical image analysis"}]
            if collection_name == ACADEMIC_COLLECTIONS["paper_chunks"]:
                return [{"title": "Paper A", "content": "Evidence"}]
            if collection_name == ACADEMIC_COLLECTIONS["entities"]:
                return [
                    {
                        "entityName": "Paper A",
                        "entityType": "Publication",
                        "nodeId": "paper-1",
                    },
                    {
                        "entityName": "EfficientNet",
                        "entityType": "Model",
                        "nodeId": "model-1",
                    },
                    {
                        "entityName": "APTOS",
                        "entityType": "Dataset",
                        "nodeId": "dataset-1",
                    },
                ]
            if collection_name == ACADEMIC_COLLECTIONS["relationships"]:
                return [
                    {
                        "srcId": "paper-1",
                        "tgtId": "model-1",
                        "relType": "USES_MODEL",
                    }
                ]
            return []

    class FakeGraphStorage:
        def __init__(self):
            self.calls = []

        async def get_shortest_path(self, node_ids, max_hops=3, **kwargs):
            self.calls.append((node_ids, max_hops, kwargs))
            return {
                "nodes": [
                    {"id": "paper-1"},
                    {"id": "model-1"},
                    {"id": "dataset-1"},
                ],
                "edges": [
                    {
                        "id": "edge-model",
                        "source_id": "paper-1",
                        "target_id": "model-1",
                        "type": "USES_MODEL",
                    },
                    {
                        "id": "edge-dataset",
                        "source_id": "paper-1",
                        "target_id": "dataset-1",
                        "type": "USES_DATASET",
                    },
                ],
            }

    monkeypatch.setattr(
        AcademicGraphRAGService,
        "_embed_queries",
        classmethod(
            lambda cls, texts: {
                text: [0.1, 0.2]
                for text in texts
            }
        ),
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
    graph_storage = FakeGraphStorage()

    result = asyncio.run(
        AcademicGraphRAGService.query_academic_indexes(
            "paper retinopati diabetik dengan EfficientNet dan APTOS",
            retrieval_mode="mix",
            vector_storage=FakeVectorStorage(),
            graph_storage=graph_storage,
        )
    )

    assert graph_storage.calls
    assert graph_storage.calls[0][0] == ["paper-1", "model-1", "dataset-1"]
    assert [edge["id"] for edge in result["subgraph"]["edges"]] == [
        "edge-model"
    ]
    assert {node["id"] for node in result["subgraph"]["nodes"]} == {
        "paper-1",
        "model-1",
        "dataset-1",
    }


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
    assert ACADEMIC_COLLECTIONS["paper_chunks"] not in searched


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


def test_author_publication_queries_detect_lowercase_indonesian_names() -> None:
    assert AcademicGraphRAGService._is_author_publication_query(
        "apa saja paper yang ditulis oleh yuni yamasari"
    )
    assert "yuni yamasari" in AcademicGraphRAGService._extract_author_name_candidates(
        "apa saja paper yang ditulis oleh yuni yamasari"
    )
    assert "yuni yamasari" in AcademicGraphRAGService._extract_author_name_candidates(
        "metode optimasi oleh yuni yamasari dkk (2024)"
    )


def test_author_publication_chunks_prioritize_matching_paper() -> None:
    rows = [
        {
            "author": "Yuni Yamasari",
            "paper_id": "p-1",
            "title": "Rule-Based Adaptive Chatbot",
            "year": 2026,
            "authors": "Yuni Yamasari, Ricky Eka Putra",
            "tldr": "Chatbot paper.",
        },
        {
            "author": "Yuni Yamasari",
            "paper_id": "p-2",
            "title": "Optimizing ANN Architecture for Classifying Student Stress Levels",
            "year": 2024,
            "authors": "Yuni Yamasari, Anita Qoiriah",
            "abstract": "This study compares Ranger, Adam, and Adagrad optimizers.",
        },
        {
            "author": "Yuni Yamasari",
            "paper_id": "p-3",
            "title": "Predicting student's psychomotor domain on the vocational senior high school",
            "year": 2018,
            "authors": "Yuni Yamasari",
            "abstract": "A solo-authored linear regression paper.",
        },
    ]

    normalized = AcademicGraphRAGService.normalize_author_publication_chunks(
        rows,
        query_text=(
            "Metode optimasi apa saja yang dibandingkan dalam penelitian klasifikasi "
            "tingkat stres mahasiswa menggunakan ANN oleh Yuni Yamasari dkk (2024)?"
        ),
    )

    assert normalized[0]["source"] == "Optimizing ANN Architecture for Classifying Student Stress Levels"
    assert "Ranger, Adam, and Adagrad" in normalized[0]["content"]
    assert any("Yuni Yamasari" == item["metadata"]["authors"] for item in normalized)


def test_exact_publication_title_produces_direct_metadata_chunk() -> None:
    query = 'Siapa penulis paper "Optimizing ANN Architecture for Classifying Student Stress Levels"?'
    assert AcademicGraphRAGService._extract_publication_title_candidates(query) == [
        "Optimizing ANN Architecture for Classifying Student Stress Levels"
    ]

    chunks = AcademicGraphRAGService.normalize_publication_detail_chunks(
        [
            {
                "paper_id": "paper-ann",
                "title": "Optimizing ANN Architecture for Classifying Student Stress Levels",
                "year": 2024,
                "authors": [
                    "Yuni Yamasari",
                    "Anita Qoiriah",
                    "Agus Prihanto",
                    "Andi Iwan Nurhidayat",
                ],
                "abstract": "The study compares Ranger, Adam, and Adagrad.",
                "concepts": [{"relation": "USES_METHOD", "value": "Adam optimizer"}],
            }
        ]
    )

    assert "Yuni Yamasari, Anita Qoiriah" in chunks[0]["content"]
    assert "Ranger, Adam, and Adagrad" in chunks[0]["content"]
    assert chunks[0]["metadata"]["retrieval_source"] == "neo4j_publication_details"


def test_author_publication_evidence_makes_context_grounded() -> None:
    grounding = AcademicGraphRAGService._grounding_status(
        [],
        {"triples": []},
        {
            "author_publications": [
                {
                    "title": "Predicting student's psychomotor domain",
                    "authors": "Yuni Yamasari",
                }
            ],
            "keywords": [],
            "entities": [],
            "relationships": [],
        },
    )

    assert grounding["status"] == "grounded"
    assert grounding["answerable"] is True


def test_lecturer_topic_query_terms_and_chunks_support_education_questions() -> None:
    query = "Dosen S2 Informatika mana yang menulis paper tentang machine learning di bidang pendidikan?"

    assert AcademicGraphRAGService._is_lecturer_topic_query(query)
    assert "informatika" in AcademicGraphRAGService._department_terms(query)

    topic_terms = AcademicGraphRAGService._topic_terms_for_neo4j(query)
    assert "machine learning" in topic_terms
    assert "education" in topic_terms
    assert "student" in topic_terms

    rows = [
        {
            "lecturer": "Asmunin",
            "affiliation": "S2 Informatika",
            "paper_id": "p-education",
            "title": (
                "Combining the Unsupervised Discretization Method and the Statistical "
                "Machine Learning on the Students' Performance"
            ),
            "year": 2020,
            "authors": "Asmunin, Yuni Yamasari",
            "matched_terms": ["machine learning", "student"],
            "doi": "10.1109/example",
        }
    ]

    chunks = AcademicGraphRAGService.normalize_lecturer_topic_chunks(rows)
    assert chunks[0]["metadata"]["lecturer"] == "Asmunin"
    assert "S2 Informatika" in chunks[0]["content"]
    assert "machine learning, student" in chunks[0]["content"]

    grounding = AcademicGraphRAGService._grounding_status(
        [],
        {"triples": []},
        {"lecturer_topic_publications": rows, "keywords": [], "entities": [], "relationships": []},
    )
    assert grounding["status"] == "grounded"


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
    assert "-----Entities-----" in evidence
    assert "-----Relationships-----" in evidence
    assert "-----Sources-----" in evidence
    assert '"id","source","content","score"' in evidence


def test_compact_evidence_uses_academicrag_csv_context_sections() -> None:
    evidence = AcademicGraphRAGService._compact_evidence_text(
        [
            {
                "rank": 1,
                "source": "Paper A",
                "score": 0.91,
                "content": "Title: Paper A\nTLDR: Uses EfficientNet.",
            }
        ],
        {
            "status": "ok",
            "triples": [
                {
                    "source": "Paper A",
                    "relation": "USES_MODEL",
                    "target": "EfficientNet",
                }
            ],
        },
        {"keywords": [], "entities": [], "relationships": []},
        {"status": "grounded", "answerable": True, "direct_evidence_count": 1},
    )

    assert "-----Entities-----" in evidence
    assert "-----Relationships-----" in evidence
    assert "-----Sources-----" in evidence
    assert '"Paper A","Title: Paper A' in evidence
    assert '"USES_MODEL"' in evidence


def test_compact_evidence_format_is_stable_across_retrieval_modes() -> None:
    chunk = {
        "rank": 1,
        "source": "Paper A",
        "score": 0.91,
        "content": "Title: Paper A\nTLDR: Uses EfficientNet.",
    }
    graph = {
        "status": "ok",
        "triples": [{"source": "Paper A", "relation": "USES_MODEL", "target": "EfficientNet"}],
    }
    grounding = {"status": "grounded", "answerable": True, "direct_evidence_count": 1}

    vector_evidence = AcademicGraphRAGService._compact_evidence_text(
        [chunk],
        {"status": "skipped", "triples": []},
        academic={},
        grounding=grounding,
        mode="naive",
    )
    graph_evidence = AcademicGraphRAGService._compact_evidence_text(
        [],
        graph,
        academic={},
        grounding=grounding,
        mode="hybrid",
    )
    mix_evidence = AcademicGraphRAGService._compact_evidence_text(
        [chunk],
        graph,
        academic={},
        grounding=grounding,
        mode="mix",
    )

    assert vector_evidence.startswith("-----Entities-----")
    assert graph_evidence.startswith("-----Entities-----")
    assert mix_evidence.startswith("-----Entities-----")
    assert "-----Sources-----" in vector_evidence
    assert "-----Relationships-----" in graph_evidence
    assert "-----Sources-----" in mix_evidence


def test_compact_evidence_escapes_csv_content() -> None:
    evidence = AcademicGraphRAGService._compact_evidence_text(
        [
            {
                "rank": 1,
                "source": 'Paper "A", revised',
                "score": 0.9,
                "content": "Line one,\nline two",
            }
        ],
        {"nodes": [], "edges": []},
    )

    assert '"Paper ""A"", revised"' in evidence
    assert '"Line one,\nline two"' in evidence


def test_author_publication_context_keeps_more_than_twenty_four_sources() -> None:
    chunks = [
        {
            "rank": index,
            "source": f"Paper {index}",
            "score": 1.0,
            "content": f"Title: Paper {index}",
        }
        for index in range(1, 31)
    ]
    academic = {
        "author_publications": [
            {
                "author": "Yuni Yamasari",
                "paper_id": f"paper-{index}",
                "title": f"Paper {index}",
            }
            for index in range(1, 31)
        ],
        "structured_counts": {
            "author_publications": {
                "returned": 30,
                "limit": 60,
                "complete": True,
                "enumeration_query": True,
            }
        },
        "keywords": [],
        "entities": [],
        "relationships": [],
    }

    evidence = AcademicGraphRAGService._compact_evidence_text(
        chunks,
        {"nodes": [], "edges": [], "triples": []},
        academic=academic,
    )

    assert '"Paper 25","Title: Paper 25","1.0"' in evidence
    assert '"Paper 30","Title: Paper 30","1.0"' in evidence


def test_structured_rows_map_to_deterministic_virtual_graph() -> None:
    academic = {
        "lecturer_topic_publications": [
            {
                "lecturer": "Yuni Yamasari",
                "affiliation": "S2 Informatika",
                "paper_id": "paper-1",
                "title": "Student Stress Classification",
                "year": 2024,
            }
        ],
        "collaborations": [
            {
                "lecturer": "Yuni Yamasari",
                "collaborator": "Ricky Eka Putra",
                "paper_count": 2,
            }
        ],
        "publication_details": [
            {
                "paper_id": "paper-1",
                "title": "Student Stress Classification",
                "concepts": [
                    {
                        "relation": "USES_MODEL",
                        "value": "Artificial Neural Network",
                        "concept_type": "Model",
                    }
                ],
            }
        ],
    }

    first = AcademicGraphRAGService._map_structured_rows_to_graph(academic)
    second = AcademicGraphRAGService._map_structured_rows_to_graph(academic)

    assert first == second
    assert {edge["type"] for edge in first["edges"]} >= {
        "HAS_AUTHOR",
        "HAS_AFFILIATION",
        "COLLABORATES_WITH",
        "USES_MODEL",
    }
    assert len({edge["id"] for edge in first["edges"]}) == len(first["edges"])


def test_structured_publication_id_matches_canonical_kg_node_id() -> None:
    graph = AcademicGraphRAGService._map_structured_rows_to_graph(
        {
            "publication_details": [
                {
                    "paper_id": "043646cd797123859ca284ad6b32ee92",
                    "title": "Predicting student's psychomotor domain",
                }
            ]
        }
    )

    assert graph["nodes"][0]["id"] == "paper:043646cd797123859ca284ad6b32ee92"


def test_graph_merge_deduplicates_actual_and_virtual_edge_signatures() -> None:
    actual_node = {
        "id": "paper:1",
        "name": "Paper",
        "type": "Publication",
        "graph_type": "core",
    }
    virtual_node = {**actual_node, "graph_type": "virtual"}
    lecturer = {
        "id": "lecturer:1",
        "name": "Lecturer",
        "type": "Lecturer",
        "graph_type": "core",
    }
    virtual_edge = {
        "id": "virtual-edge",
        "source_id": "paper:1",
        "target_id": "lecturer:1",
        "type": "HAS_AUTHOR",
        "properties": {"source": "structured_query"},
    }
    actual_edge = {
        "id": "actual-edge",
        "source_id": "paper:1",
        "target_id": "lecturer:1",
        "type": "HAS_AUTHOR",
        "properties": {"source": "neo4j"},
    }

    merged = AcademicGraphRAGService._merge_graph_results(
        [
            {"nodes": [virtual_node, lecturer], "edges": [virtual_edge]},
            {"nodes": [actual_node, lecturer], "edges": [actual_edge]},
        ],
        max_nodes=10,
    )

    assert len(merged["nodes"]) == 2
    assert len(merged["edges"]) == 1
    assert merged["edges"][0]["id"] == "actual-edge"
    assert next(node for node in merged["nodes"] if node["id"] == "paper:1")["graph_type"] == "core"


def test_evidence_chunks_are_deduplicated_by_source() -> None:
    chunks = AcademicGraphRAGService._dedupe_evidence_chunks(
        [
            {"source": "Paper A", "content": "Direct evidence"},
            {"source": " paper  a ", "content": "Duplicate vector evidence"},
            {"source": "Paper B", "content": "Other evidence"},
        ]
    )

    assert [chunk["source"] for chunk in chunks] == ["Paper A", "Paper B"]
    assert [chunk["rank"] for chunk in chunks] == [1, 2]


def test_relationship_pruning_keeps_supported_edges_and_seed_nodes() -> None:
    graph = {
        "nodes": [
            {"id": "paper-1"},
            {"id": "model-1"},
            {"id": "dataset-1"},
        ],
        "edges": [
            {
                "id": "edge-1",
                "source_id": "paper-1",
                "target_id": "model-1",
                "type": "USES_MODEL",
            },
            {
                "id": "edge-2",
                "source_id": "paper-1",
                "target_id": "dataset-1",
                "type": "USES_DATASET",
            },
        ],
    }

    pruned = AcademicGraphRAGService._prune_shortest_path_graph(
        graph,
        [
            {
                "srcId": "model-1",
                "tgtId": "paper-1",
                "relType": "USES_MODEL",
            }
        ],
        seed_node_ids=["paper-1", "dataset-1"],
    )

    assert [edge["id"] for edge in pruned["edges"]] == ["edge-1"]
    assert {node["id"] for node in pruned["nodes"]} == {
        "paper-1",
        "model-1",
        "dataset-1",
    }
    assert (
        AcademicGraphRAGService._prune_shortest_path_graph(
            graph,
            [],
            seed_node_ids=["paper-1"],
        )
        == graph
    )


def test_tool_response_preserves_raw_citation_payload() -> None:
    payload = {
        "evidence_text": "-----Entities-----",
        "chunks": [{"source": "Paper A", "content": "Evidence"}],
        "graph": {
            "status": "ok",
            "nodes": [{"id": "paper-1"}],
            "edges": [{"id": "edge-1"}],
            "triples": [],
        },
        "academic_retrieval": {
            "status": "ok",
            "subgraph": {
                "nodes": [{"id": "paper-1"}],
                "edges": [],
            },
            "author_publications": [{"title": "Paper A"}],
            "keyword_decomposition": {
                "prompt": "private prompt",
                "low_level_keywords": ["Paper A"],
            },
        },
        "storage_layer": {"graph": {"backend": "neo4j_aura"}},
        "grounding": {"status": "grounded"},
    }

    response = _academic_tool_response(
        payload=payload,
        query_text="Paper A",
        kb_name="yunesa_academic_kg",
        retrieval_mode="mix",
        tool_call_id="tool-1",
    )

    citation = response.update["citations"][0]
    assert citation["entities"] == [{"id": "paper-1"}]
    assert citation["relationships"] == [{"id": "edge-1"}]
    assert citation["chunks"] == payload["chunks"]
    assert citation["academic_retrieval"]["author_publications"] == [
        {"title": "Paper A"}
    ]
    assert "prompt" not in citation["academic_retrieval"]["keyword_decomposition"]


def test_tool_response_sanitizes_graph_payload_for_ui_and_llm() -> None:
    payload = {
        "evidence_text": "-----Entities-----",
        "chunks": [],
        "graph": {
            "status": "ok",
            "nodes": [
                {
                    "id": "concept:internal-secret-id",
                    "name": "Machine learning",
                    "type": "Concept",
                },
                {
                    "id": "publication:internal-paper-id",
                    "name": "Paper A",
                    "type": "Publication",
                },
            ],
            "edges": [
                {
                    "id": "relationship:internal-id",
                    "source_id": "publication:internal-paper-id",
                    "target_id": "concept:internal-secret-id",
                    "type": "HAS_TOPIC",
                }
            ],
            "triples": [],
        },
        "academic_retrieval": {"status": "ok"},
        "grounding": {"status": "grounded"},
    }

    response = _academic_tool_response(
        payload=payload,
        query_text="Paper A",
        kb_name="yunesa_academic_kg",
        retrieval_mode="mix",
        tool_call_id="tool-1",
    )

    parsed_payload = json.loads(response.update["messages"][0].content)
    assert [node["id"] for node in parsed_payload["graph"]["nodes"]] == [
        "node-1",
        "node-2",
    ]
    assert parsed_payload["graph"]["edges"][0]["source_id"] == "node-2"
    assert parsed_payload["graph"]["edges"][0]["target_id"] == "node-1"
    assert "concept:internal-secret-id" not in response.update["messages"][0].content
    assert response.update["citations"][0]["entities"][0]["id"] == (
        "concept:internal-secret-id"
    )


def test_tool_response_returns_author_publication_enumeration_window() -> None:
    author_rows = [
        {
            "title": f"Paper {index}",
            "year": 2020 + (index % 5),
            "authors": "Yuni Yamasari",
        }
        for index in range(1, 31)
    ]
    payload = {
        "evidence_text": "-----Entities-----",
        "chunks": [],
        "graph": {"status": "ok", "nodes": [], "edges": [], "triples": []},
        "academic_retrieval": {
            "status": "ok",
            "author_publications": author_rows,
            "structured_counts": {
                "author_publications": {
                    "returned": 30,
                    "limit": 60,
                    "complete": True,
                    "enumeration_query": True,
                }
            },
        },
        "grounding": {"status": "grounded"},
    }

    response = _academic_tool_response(
        payload=payload,
        query_text="paper Yuni Yamasari",
        kb_name="yunesa_academic_kg",
        retrieval_mode="mix",
        tool_call_id="tool-1",
    )

    tool_payload = response.update["messages"][0].content
    parsed_payload = json.loads(tool_payload)
    assert "Paper 30" in tool_payload
    assert '"returned": 30' in tool_payload
    assert '"complete": true' in tool_payload
    assert "answer_hints" in parsed_payload
    assert "author_publications_markdown" in parsed_payload["answer_hints"]
    assert "| 30 | Paper 30 |" in parsed_payload["answer_hints"]["author_publications_markdown"]
    assert "Do not rename titles" in parsed_payload["answer_hints"][
        "author_publications_instruction"
    ]


def test_tool_response_adds_structured_answer_hints_for_relational_rows() -> None:
    payload = {
        "evidence_text": "-----Entities-----",
        "chunks": [],
        "graph": {"status": "ok", "nodes": [], "edges": [], "triples": []},
        "academic_retrieval": {
            "status": "ok",
            "route_decision": {
                "requested_mode": "mix",
                "effective_mode": "subgraph",
                "auto_routed": True,
                "reason": "lecturer_topic_structured_query",
            },
            "lecturer_topic_publications": [
                {
                    "lecturer": "Yuni Yamasari",
                    "affiliation": "S2 Informatika",
                    "matched_terms": ["machine learning", "education"],
                    "title": "Combining the Unsupervised Discretization Method and the Statistical Machine Learning on the Students' Performance",
                    "year": 2020,
                    "doi": "10.example/test",
                }
            ],
            "topic_frequencies": [
                {
                    "topic": "machine learning",
                    "concept_type": "ResearchTopic",
                    "publication_count": 12,
                    "sample_titles": ["Paper A", "Paper B"],
                }
            ],
        },
        "grounding": {"status": "grounded"},
    }

    response = _academic_tool_response(
        payload=payload,
        query_text="Dosen S2 Informatika mana yang menulis paper tentang machine learning?",
        kb_name="yunesa_academic_kg",
        retrieval_mode="mix",
        tool_call_id="tool-1",
    )

    parsed_payload = json.loads(response.update["messages"][0].content)
    hints = parsed_payload["answer_hints"]
    assert "lecturer_topic_publications_markdown" in hints
    assert "Yuni Yamasari" in hints["lecturer_topic_publications_markdown"]
    assert "topic_frequencies_markdown" in hints
    assert "machine learning" in hints["topic_frequencies_markdown"]
    assert parsed_payload["academic_retrieval"]["route_decision"]["effective_mode"] == "subgraph"


def test_broad_graph_triples_are_supporting_not_direct_evidence() -> None:
    grounding = AcademicGraphRAGService._grounding_status(
        [],
        {
            "triples": [
                {
                    "source": "Paper A",
                    "relation": "PUBLISHED_IN_YEAR",
                    "target": "2024",
                }
            ]
        },
        {"keywords": [], "entities": [], "relationships": []},
        query_text="paper tentang machine learning",
    )

    assert grounding["status"] == "supporting_only"
    assert grounding["answerable"] is False


def test_relationship_query_can_use_graph_triples_as_direct_evidence() -> None:
    grounding = AcademicGraphRAGService._grounding_status(
        [],
        {
            "triples": [
                {
                    "source": "Yuni Yamasari",
                    "relation": "COLLABORATES_WITH",
                    "target": "Ricky Eka Putra",
                }
            ]
        },
        {"keywords": [], "entities": [], "relationships": []},
        query_text="Siapa yang berkolaborasi dengan Yuni Yamasari?",
    )

    assert grounding["status"] == "grounded"
    assert grounding["graph_direct_evidence_count"] == 1


def test_topic_frequency_query_requires_explicit_frequency_intent() -> None:
    assert AcademicGraphRAGService._is_topic_frequency_query(
        "Topik riset apa yang paling sering muncul?"
    )
    assert not AcademicGraphRAGService._is_topic_frequency_query(
        "Paper apa yang membahas topik machine learning?"
    )

    chunks = AcademicGraphRAGService.normalize_topic_frequency_chunks(
        [
            {
                "topic": "machine learning",
                "concept_type": "ResearchTopic",
                "publication_count": 12,
                "sample_titles": ["Paper A", "Paper B"],
            }
        ]
    )
    assert "Publication count: 12" in chunks[0]["content"]


def test_collaboration_evidence_is_direct_and_grounded() -> None:
    rows = [
        {
            "lecturer": "Ricky Eka Putra",
            "collaborator": "Yuni Yamasari",
            "paper_count": 3,
            "paper_titles": [
                (
                    "Rule-Based Adaptive Chatbot on WhatsApp for Visual, Auditory, "
                    "and Kinesthetic Learning Style Detection"
                ),
                "Implementing Optuna and Ensemble Learning on Boosting Models for Credit Default Risk Prediction",
            ],
        }
    ]

    assert AcademicGraphRAGService._is_collaboration_query(
        "Siapa dosen yang berkolaborasi dengan Ricky Eka Putra?"
    )
    chunks = AcademicGraphRAGService.normalize_collaboration_chunks(rows)
    assert "Collaborator: Yuni Yamasari" in chunks[0]["content"]

    grounding = AcademicGraphRAGService._grounding_status(
        [],
        {"triples": []},
        {"collaborations": rows, "keywords": [], "entities": [], "relationships": []},
        query_text="Siapa dosen yang berkolaborasi dengan Ricky Eka Putra?",
    )
    assert grounding["status"] == "grounded"
    assert grounding["answerable"] is True


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


def test_grounding_status_with_irrelevant_query_topic_is_empty() -> None:
    # A query with specific topic terms that don't match any retrieved text
    grounding = AcademicGraphRAGService._grounding_status(
        [
            {
                "content": "Optimizing ANN Architecture for Classifying Student Stress Levels",
                "source": "Paper A",
            }
        ],
        {"triples": []},
        {"keywords": [], "entities": [], "relationships": []},
        query_text="carikan saya paper implementasi graph di lingkungan peternakan ayam?",
    )
    assert grounding["status"] == "empty"
    assert grounding["answerable"] is False

    # A query with matching topic terms
    grounding_matching = AcademicGraphRAGService._grounding_status(
        [
            {
                "content": "Optimizing ANN Architecture for Classifying Student Stress Levels",
                "source": "Paper A",
            }
        ],
        {"triples": []},
        {"keywords": [], "entities": [], "relationships": []},
        query_text="dosen stress levels",
    )
    assert grounding_matching["status"] == "grounded"
    assert grounding_matching["answerable"] is True
