"""Read-only Academic GraphRAG statistics for the administration dashboard."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from yunesa.config.static.models import DEFAULT_EMBED_MODELS
from yunesa.knowledge.graphrag.storage import normalize_milvus_uri
from yunesa.utils import logger


ACADEMIC_COLLECTIONS = {
    "paper_chunks": "PaperChunk",
    "entities": "EntityEmbedding",
    "relationships": "RelationshipEmbedding",
    "content_keywords": "ContentKeyword",
}
DEFAULT_ACADEMIC_EMBEDDING_PROVIDER = "siliconflow"
DEFAULT_ACADEMIC_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_MILVUS_DB_NAME = "default"


def _source_status(status: str, detail: str) -> dict[str, str]:
    return {"status": status, "detail": detail}


def _content_range_count(response: httpx.Response) -> int:
    content_range = response.headers.get("content-range", "")
    if "/" in content_range:
        count = content_range.rsplit("/", 1)[-1]
        if count.isdigit():
            return int(count)
    payload = response.json()
    return len(payload) if isinstance(payload, list) else 0


class AcademicDashboardService:
    """Aggregate the canonical academic corpus, graph, and vector indexes."""

    def __init__(self, *, graph_name: str | None = None) -> None:
        self.graph_name = (
            str(graph_name or "").strip()
            or os.getenv("YUNESA_NEO4J_GRAPH_NAME")
            or os.getenv("YUNESA_GRAPH_NAME")
            or "yunesa_academic_kg"
        )

    @staticmethod
    def _milvus_credentials() -> tuple[str, str, str | None]:
        uri = os.getenv("MILVUS_URI") or os.getenv("ZILLIZ_URI") or ""
        token = os.getenv("MILVUS_TOKEN") or os.getenv("ZILLIZ_TOKEN") or ""
        db_name = os.getenv("MILVUS_DB_NAME") or os.getenv("ZILLIZ_DB_NAME") or None
        if db_name and db_name.strip().lower() in {"default", "none", "null"}:
            db_name = None
        return (
            normalize_milvus_uri(uri),
            token.strip(),
            str(db_name).strip() if db_name else None,
        )

    @staticmethod
    def _milvus_db_candidates(db_name: str | None) -> list[str | None]:
        candidates: list[str | None] = []
        configured = str(db_name or "").strip()
        if configured and configured.lower() not in {"none", "null", DEFAULT_MILVUS_DB_NAME}:
            candidates.append(configured)
        candidates.append(None)
        if DEFAULT_MILVUS_DB_NAME not in candidates:
            candidates.append(DEFAULT_MILVUS_DB_NAME)
        return candidates

    @staticmethod
    def _graph_filter(graph_name: str) -> str:
        safe_graph_name = str(graph_name or "").replace("\\", "\\\\").replace('"', '\\"')
        return f'graphName == "{safe_graph_name}"' if safe_graph_name else ""

    async def collect(self) -> dict[str, Any]:
        postgres_data, neo4j, milvus = await asyncio.gather(
            self._collect_postgres(),
            self._collect_neo4j(),
            self._collect_milvus(),
        )
        embedding = self._embedding_metadata()
        storage_consistency = self._storage_consistency(
            supabase=postgres_data,
            neo4j=neo4j,
            milvus=milvus,
        )

        return {
            "graph_name": self.graph_name,
            "papers_count": postgres_data["papers_count"],
            "lecturers_count": postgres_data["lecturers_count"],
            "authorship_links_count": postgres_data["authorship_links_count"],
            "papers_with_abstract": postgres_data["papers_with_abstract"],
            "papers_with_keywords": postgres_data["papers_with_keywords"],
            "papers_with_tldr": postgres_data["papers_with_tldr"],
            "kg_nodes_count": neo4j["total_nodes"],
            "kg_edges_count": neo4j["total_edges"],
            "graph_entity_distribution": neo4j["entity_distribution"],
            "graph_relationship_distribution": neo4j["relationship_distribution"],
            "vector_records_count": milvus["total_records"],
            "vector_collections": milvus["collections"],
            "vector_database": milvus["database"],
            "embedding_provider": embedding["provider"],
            "embedding_model": embedding["model"],
            "embedding_dimension": embedding["dimension"],
            "storage_consistency": storage_consistency,
            "source_status": {
                "supabase": postgres_data["source_status"],
                "neo4j": neo4j["source_status"],
                "milvus": milvus["source_status"],
            },
            "generated_at": datetime.now(UTC).isoformat(),
        }

    async def _collect_postgres(self) -> dict[str, Any]:
        result = {
            "papers_count": 0,
            "lecturers_count": 0,
            "authorship_links_count": 0,
            "papers_with_abstract": 0,
            "papers_with_keywords": 0,
            "papers_with_tldr": 0,
            "source_status": _source_status("unconfigured", "PostgreSQL credentials are not configured."),
        }
        host = os.getenv("POSTGRES_HOST") or os.getenv("PGHOST") or "postgres-prod"
        port = int(os.getenv("POSTGRES_PORT") or os.getenv("PGPORT") or "5432")
        db = os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE") or "tugas_akhir"
        user = os.getenv("POSTGRES_USER") or os.getenv("PGUSER") or "postgres"
        password = os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD") or "71509325"

        try:
            import asyncpg
            conn = await asyncpg.connect(user=user, password=password, database=db, host=host, port=port, timeout=5.0)
            try:
                row_papers = await conn.fetchrow("SELECT count(*) FROM papers;")
                row_lecturers = await conn.fetchrow("SELECT count(*) FROM lecturers;")
                row_links = await conn.fetchrow("SELECT count(*) FROM (SELECT unnest(string_to_array(author_ids, ',')) FROM papers WHERE author_ids IS NOT NULL AND author_ids != '') sub;")
                row_abstract = await conn.fetchrow("SELECT count(*) FROM papers WHERE abstract IS NOT NULL AND abstract != '';")
                row_keywords = await conn.fetchrow("SELECT count(*) FROM papers WHERE keywords IS NOT NULL AND keywords != '';")
                row_tldr = await conn.fetchrow("SELECT count(*) FROM papers WHERE tldr IS NOT NULL AND tldr != '';")

                result["papers_count"] = int(row_papers[0]) if row_papers else 0
                result["lecturers_count"] = int(row_lecturers[0]) if row_lecturers else 0
                result["authorship_links_count"] = int(row_links[0]) if row_links else 0
                result["papers_with_abstract"] = int(row_abstract[0]) if row_abstract else 0
                result["papers_with_keywords"] = int(row_keywords[0]) if row_keywords else 0
                result["papers_with_tldr"] = int(row_tldr[0]) if row_tldr else 0
                result["source_status"] = _source_status("ready", "Self-hosted PostgreSQL corpus is available.")
                return result
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning(f"academic_dashboard.postgres_failed | error_type={type(exc).__name__} | detail={exc}")
            return await self._collect_supabase()

    @staticmethod
    def _storage_consistency(
        *,
        supabase: dict[str, Any],
        neo4j: dict[str, Any],
        milvus: dict[str, Any],
    ) -> dict[str, Any]:
        entity_distribution = neo4j.get("entity_distribution") or {}
        relationship_distribution = neo4j.get("relationship_distribution") or {}
        collections = milvus.get("collections") or {}

        checks = {
            "publications": {
                "source": int(supabase.get("papers_count") or 0),
                "indexed": int(entity_distribution.get("Publication") or 0),
            },
            "lecturers": {
                "source": int(supabase.get("lecturers_count") or 0),
                "indexed": int(entity_distribution.get("Lecturer") or 0),
            },
            "authorship_links": {
                "source": int(supabase.get("authorship_links_count") or 0),
                "indexed": int(
                    relationship_distribution.get("HAS_AUTHOR")
                    or relationship_distribution.get("PUBLISHES")
                    or 0
                ),
            },
            "content_keywords": {
                "source": int(supabase.get("papers_count") or 0),
                "indexed": int(collections.get("ContentKeyword") or 0),
            },
        }
        for values in checks.values():
            values["gap"] = values["source"] - values["indexed"]
            values["in_sync"] = values["gap"] == 0

        configured = all(
            source.get("source_status", {}).get("status") == "ready"
            for source in (supabase, neo4j, milvus)
        )
        return {
            "status": (
                "in_sync"
                if configured and all(item["in_sync"] for item in checks.values())
                else "drift_detected"
                if configured
                else "unavailable"
            ),
            "checks": checks,
        }

    async def _collect_supabase(self) -> dict[str, Any]:
        result = {
            "papers_count": 0,
            "lecturers_count": 0,
            "authorship_links_count": 0,
            "papers_with_abstract": 0,
            "papers_with_keywords": 0,
            "papers_with_tldr": 0,
            "source_status": _source_status("unconfigured", "Supabase credentials are not configured."),
        }
        base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        api_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY", "")
        if not base_url or not api_key:
            return result

        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Prefer": "count=exact",
            "Range": "0-0",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                counts = await asyncio.gather(
                    self._postgrest_count(client, base_url, "papers", "paper_id"),
                    self._postgrest_count(client, base_url, "lecturers", "nip"),
                    self._postgrest_count(client, base_url, "paper_lecturers", "paper_id"),
                    self._postgrest_count(
                        client,
                        base_url,
                        "papers",
                        "paper_id",
                        filters=[("abstract", "not.is.null"), ("abstract", "neq.")],
                    ),
                    self._postgrest_count(
                        client,
                        base_url,
                        "papers",
                        "paper_id",
                        filters=[("keywords", "not.is.null"), ("keywords", "neq.")],
                    ),
                    self._postgrest_count(
                        client,
                        base_url,
                        "papers",
                        "paper_id",
                        filters=[("tldr", "not.is.null"), ("tldr", "neq.")],
                    ),
                )
        except Exception as exc:
            logger.warning(
                f"academic_dashboard.supabase_failed | error_type={type(exc).__name__}"
            )
            result["source_status"] = _source_status(
                "error", "Academic corpus statistics could not be read."
            )
            return result

        (
            result["papers_count"],
            result["lecturers_count"],
            result["authorship_links_count"],
            result["papers_with_abstract"],
            result["papers_with_keywords"],
            result["papers_with_tldr"],
        ) = counts
        result["source_status"] = _source_status("ready", "Academic corpus is available.")
        return result

    @staticmethod
    async def _postgrest_count(
        client: httpx.AsyncClient,
        base_url: str,
        table: str,
        select_column: str,
        *,
        filters: list[tuple[str, str]] | None = None,
    ) -> int:
        params: list[tuple[str, str]] = [
            ("select", select_column),
            ("limit", "1"),
            *(filters or []),
        ]
        response = await client.get(f"{base_url}/rest/v1/{table}", params=params)
        response.raise_for_status()
        return _content_range_count(response)

    async def _collect_neo4j(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "total_nodes": 0,
            "total_edges": 0,
            "entity_distribution": {},
            "relationship_distribution": {},
            "source_status": _source_status("unconfigured", "Neo4j credentials are not configured."),
        }
        uri = os.getenv("NEO4J_URI", "").strip()
        username = (os.getenv("NEO4J_USERNAME") or os.getenv("NEO4J_USER") or "neo4j").strip()
        password = os.getenv("NEO4J_PASSWORD", "")
        database = (os.getenv("NEO4J_DATABASE") or "neo4j").strip()
        if not uri or not password:
            return result

        from neo4j import AsyncGraphDatabase

        driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
        try:
            async with driver.session(database=database) as session:
                node_record = await (
                    await session.run(
                        "MATCH (n) "
                        "WHERE $graph_name IS NULL OR n.graph_name = $graph_name "
                        "RETURN count(n) AS total",
                        graph_name=self.graph_name,
                    )
                ).single()
                edge_record = await (
                    await session.run(
                        "MATCH ()-[r]->() "
                        "WHERE $graph_name IS NULL OR r.graph_name = $graph_name "
                        "RETURN count(r) AS total",
                        graph_name=self.graph_name,
                    )
                ).single()
                entity_rows = await (
                    await session.run(
                        "MATCH (n) "
                        "WHERE $graph_name IS NULL OR n.graph_name = $graph_name "
                        "WITH coalesce(head(labels(n)), n.node_type, 'Unknown') AS entity_type, count(*) AS total "
                        "RETURN entity_type, total ORDER BY total DESC",
                        graph_name=self.graph_name,
                    )
                ).data()
                relationship_rows = await (
                    await session.run(
                        "MATCH ()-[r]->() "
                        "WHERE $graph_name IS NULL OR r.graph_name = $graph_name "
                        "RETURN type(r) AS relation_type, count(*) AS total "
                        "ORDER BY total DESC",
                        graph_name=self.graph_name,
                    )
                ).data()

            result.update(
                total_nodes=int((node_record or {}).get("total", 0)),
                total_edges=int((edge_record or {}).get("total", 0)),
                entity_distribution={
                    str(row["entity_type"]): int(row["total"]) for row in entity_rows
                },
                relationship_distribution={
                    str(row["relation_type"]): int(row["total"]) for row in relationship_rows
                },
                source_status=_source_status("ready", "Academic knowledge graph is available."),
            )
        except Exception as exc:
            logger.warning(
                f"academic_dashboard.neo4j_failed | error_type={type(exc).__name__}"
            )
            result["source_status"] = _source_status(
                "error", "Academic graph statistics could not be read."
            )
        finally:
            await driver.close()
        return result

    async def _collect_milvus(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._collect_milvus_sync)

    def _collect_milvus_sync(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "total_records": 0,
            "collections": {},
            "database": "",
            "source_status": _source_status("unconfigured", "Milvus credentials are not configured."),
        }
        uri, token, configured_db = self._milvus_credentials()
        if not uri:
            return result

        graph_filter = self._graph_filter(self.graph_name)
        last_error: Exception | None = None
        for database in self._milvus_db_candidates(configured_db):
            client = None
            try:
                from pymilvus import MilvusClient

                kwargs: dict[str, Any] = {"uri": uri}
                if token:
                    kwargs["token"] = token
                client = MilvusClient(**kwargs)
                if database and hasattr(client, "using_database"):
                    client.using_database(database)

                available = set(client.list_collections())
                canonical = set(ACADEMIC_COLLECTIONS.values())
                if not available.intersection(canonical):
                    continue

                counts: dict[str, int] = {}
                for collection_name in ACADEMIC_COLLECTIONS.values():
                    if collection_name not in available:
                        counts[collection_name] = 0
                        continue
                    rows = client.query(
                        collection_name=collection_name,
                        filter=graph_filter,
                        output_fields=["count(*)"],
                    )
                    counts[collection_name] = int((rows[0] if rows else {}).get("count(*)", 0))

                result.update(
                    total_records=sum(counts.values()),
                    collections=counts,
                    database=database or "default",
                    source_status=_source_status("ready", "Academic vector indexes are available."),
                )
                return result
            except Exception as exc:
                last_error = exc
            finally:
                if client is not None and hasattr(client, "close"):
                    try:
                        client.close()
                    except Exception:
                        pass

        if last_error is not None:
            logger.warning(
                f"academic_dashboard.milvus_failed | error_type={type(last_error).__name__}"
            )
            result["source_status"] = _source_status(
                "error", "Academic vector index statistics could not be read."
            )
        else:
            result["source_status"] = _source_status(
                "empty", "Canonical Academic GraphRAG collections were not found."
            )
        return result

    @staticmethod
    def _embedding_metadata() -> dict[str, Any]:
        model_id = f"{DEFAULT_ACADEMIC_EMBEDDING_PROVIDER}/{DEFAULT_ACADEMIC_EMBEDDING_MODEL}"
        model = DEFAULT_EMBED_MODELS.get(model_id)
        return {
            "provider": DEFAULT_ACADEMIC_EMBEDDING_PROVIDER,
            "model": DEFAULT_ACADEMIC_EMBEDDING_MODEL,
            "dimension": int(model.dimension if model else 0),
        }
