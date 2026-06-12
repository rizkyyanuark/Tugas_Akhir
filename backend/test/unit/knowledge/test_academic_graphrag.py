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
    assert AcademicGraphRAGService._milvus_db_candidates("default") == [None, "default"]
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
            "title": "Combining the Unsupervised Discretization Method and the Statistical Machine Learning on the Students' Performance",
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
    assert "do not use model memory" in evidence


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
                "Rule-Based Adaptive Chatbot on WhatsApp for Visual, Auditory, and Kinesthetic Learning Style Detection",
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
