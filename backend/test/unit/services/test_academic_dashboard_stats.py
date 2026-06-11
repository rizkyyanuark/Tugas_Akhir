from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx

from yunesa.services.academic_dashboard_service import (
    AcademicDashboardService,
    _content_range_count,
)


def test_content_range_count_prefers_postgrest_exact_count():
    response = httpx.Response(
        206,
        headers={"content-range": "0-0/57"},
        json=[{"paper_id": "paper-1"}],
    )

    assert _content_range_count(response) == 57


def test_supabase_stats_use_current_academic_tables(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
    service = AcademicDashboardService()
    count_method = AsyncMock(side_effect=[50, 116, 125, 48, 45, 50])
    monkeypatch.setattr(service, "_postgrest_count", count_method)

    result = asyncio.run(service._collect_supabase())

    assert result["papers_count"] == 50
    assert result["lecturers_count"] == 116
    assert result["authorship_links_count"] == 125
    assert result["source_status"]["status"] == "ready"
    tables = [call.args[2] for call in count_method.await_args_list]
    assert tables == [
        "papers",
        "lecturers",
        "paper_lecturers",
        "papers",
        "papers",
        "papers",
    ]


def test_collect_keeps_storage_layers_separate(monkeypatch):
    service = AcademicDashboardService(graph_name="yunesa_academic_kg")
    monkeypatch.setattr(
        service,
        "_collect_supabase",
        AsyncMock(
            return_value={
                "papers_count": 50,
                "lecturers_count": 116,
                "authorship_links_count": 125,
                "papers_with_abstract": 48,
                "papers_with_keywords": 45,
                "papers_with_tldr": 50,
                "source_status": {"status": "ready", "detail": "ok"},
            }
        ),
    )
    monkeypatch.setattr(
        service,
        "_collect_neo4j",
        AsyncMock(
            return_value={
                "total_nodes": 687,
                "total_edges": 900,
                "entity_distribution": {"Publication": 50, "Lecturer": 116},
                "relationship_distribution": {"HAS_AUTHOR": 125},
                "source_status": {"status": "ready", "detail": "ok"},
            }
        ),
    )
    monkeypatch.setattr(
        service,
        "_collect_milvus",
        AsyncMock(
            return_value={
                "total_records": 1090,
                "collections": {
                    "PaperChunk": 50,
                    "EntityEmbedding": 687,
                    "ContentKeyword": 50,
                },
                "database": "default",
                "source_status": {"status": "ready", "detail": "ok"},
            }
        ),
    )

    result = asyncio.run(service.collect())

    assert result["papers_count"] == 50
    assert result["kg_nodes_count"] == 687
    assert result["vector_records_count"] == 1090
    assert result["graph_name"] == "yunesa_academic_kg"
    assert result["embedding_dimension"] == 1024
    assert result["storage_consistency"]["status"] == "in_sync"


def test_storage_consistency_reports_cross_store_drift():
    result = AcademicDashboardService._storage_consistency(
        supabase={
            "papers_count": 51,
            "lecturers_count": 128,
            "authorship_links_count": 140,
            "source_status": {"status": "ready"},
        },
        neo4j={
            "entity_distribution": {"Publication": 50, "Lecturer": 128},
            "relationship_distribution": {"HAS_AUTHOR": 139},
            "source_status": {"status": "ready"},
        },
        milvus={
            "collections": {"ContentKeyword": 49},
            "source_status": {"status": "ready"},
        },
    )

    assert result["status"] == "drift_detected"
    assert result["checks"]["publications"]["gap"] == 1
    assert result["checks"]["authorship_links"]["gap"] == 1
    assert result["checks"]["content_keywords"]["gap"] == 2
