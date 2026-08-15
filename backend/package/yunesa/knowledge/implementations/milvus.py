"""
milvus.py — Production-Grade Milvus Vector Knowledge Base & Academic GraphRAG Storage
=======================================================================================
Unified Milvus vector engine for UNESA Academic Knowledge Graph & RAG retrieval.

Classes:
- MilvusKB: KnowledgeBase concrete class for document lifecycle & hybrid vector search.
- AcademicKGVectorStore: Object-oriented vector store manager for UNESA Academic Knowledge Graph.

Module Wrappers (Backward Compatibility):
- write_vector_index_to_milvus, build_milvus_index_records, inspect_milvus_collections.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any
import networkx as nx

try:
    from pymilvus import (
        AnnSearchRequest,
        Collection,
        CollectionSchema,
        DataType,
        FieldSchema,
        Function,
        FunctionType,
        MilvusClient,
        WeightedRanker,
        connections,
        db,
        utility,
    )
    MILVUS_AVAILABLE = True
except ImportError:
    MILVUS_AVAILABLE = False
    MilvusClient = Any

from yunesa.config import config
from yunesa.knowledge.base import FileStatus, KnowledgeBase
from yunesa.knowledge.config import (
    MilvusVectorIndexConfig,
    _positive_env_int,
    milvus_config_from_env,
)
from yunesa.knowledge.constants import (
    CONCEPT_RELATIONS,
    MILVUS_VARCHAR_LIMITS,
)
from yunesa.knowledge.graphs.builder import (
    _truncate_milvus,
    _validate_milvus_varchar_records,
)
from yunesa.knowledge.implementations.embedding_engine import _embed_milvus_record_batch
from yunesa.knowledge.utils.text_processing import (
    canonical_relation,
    content_hash,
    field_value,
    normalize_text,
    safe_str,
    semantic_text_chunks,
    split_list_field,
    stable_id,
)
from yunesa.utils import hashstr, logger

DEFAULT_MILVUS_DB_NAME = "default"
VECTOR_METRIC_TYPE = "COSINE"
CONTENT_SPARSE_FIELD = "content_sparse"


# ═══════════════════════════════════════════════════════════════════════════
# 1. Retrieval Configuration Data Model
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(kw_only=True)
class MilvusRetrievalConfig:
    """Retrieval configuration options for Milvus vector queries."""

    search_mode: str = field(
        default="vector",
        metadata={
            "label": "Search Mode",
            "type": "select",
            "options": [
                {"value": "vector", "label": "Vector Search", "description": "Dense vector similarity search"},
                {"value": "keyword", "label": "BM25 Search", "description": "Milvus BM25 sparse keyword search"},
                {"value": "hybrid", "label": "Hybrid Search", "description": "Combined vector + BM25 search"},
            ],
            "description": "Select retrieval algorithm mode",
        },
    )
    final_top_k: int = field(
        default=10,
        metadata={
            "label": "Final Top K",
            "type": "number",
            "min": 1,
            "max": 100,
            "description": "Number of top results returned to client",
        },
    )
    similarity_threshold: float = field(
        default=0.0,
        metadata={
            "label": "Similarity Threshold (0-1)",
            "type": "number",
            "min": 0.0,
            "max": 1.0,
            "step": 0.1,
            "description": "Minimum vector similarity score cutoff",
        },
    )
    vector_weight: float = field(
        default=0.7,
        metadata={
            "label": "Vector Search Weight",
            "type": "number",
            "min": 0.0,
            "max": 1.0,
            "step": 0.1,
            "description": "Weight of vector search in hybrid ranking",
        },
    )
    bm25_weight: float = field(
        default=0.3,
        metadata={
            "label": "BM25 Weight",
            "type": "number",
            "min": 0.0,
            "max": 1.0,
            "step": 0.1,
            "description": "Weight of BM25 search in hybrid ranking",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# 2. Milvus KnowledgeBase Class (Standard Document & Hybrid RAG Store)
# ═══════════════════════════════════════════════════════════════════════════

class MilvusKB(KnowledgeBase):
    """
    Production Milvus Knowledge Base implementation.
    Manages vector collections, document indexing, and hybrid semantic retrieval.
    """

    def __init__(self, work_dir: str, **kwargs: Any):
        super().__init__(work_dir)
        if not MILVUS_AVAILABLE:
            raise ImportError("pymilvus is not installed. Please install with: pip install pymilvus")

        self.milvus_token = kwargs.get("milvus_token", os.getenv("MILVUS_TOKEN") or "")
        self.milvus_uri = kwargs.get("milvus_uri", os.getenv("MILVUS_URI") or "http://localhost:19530")
        self.milvus_db = kwargs.get("milvus_db") or os.getenv("MILVUS_DB_NAME") or DEFAULT_MILVUS_DB_NAME
        self.connection_alias = f"milvus_{hashstr(work_dir, 6)}"
        self.collections: dict[str, Any] = {}
        self.chunk_size = kwargs.get("chunk_size", 1000)
        self.chunk_overlap = kwargs.get("chunk_overlap", 200)
        self._metadata_lock = asyncio.Lock()
        self._init_connection()
        logger.info("MilvusKB initialized | uri=%s | db=%s", self.milvus_uri, self.milvus_db)

    @property
    def kb_type(self) -> str:
        return "milvus"

    def _init_connection(self) -> None:
        """Initialize connection to Milvus standalone server or Zilliz Cloud cluster."""
        try:
            candidates: list[str | None] = []
            configured_db = str(self.milvus_db or "").strip()
            if configured_db and configured_db != DEFAULT_MILVUS_DB_NAME:
                candidates.append(configured_db)
            candidates.append(None)
            if DEFAULT_MILVUS_DB_NAME not in candidates:
                candidates.append(DEFAULT_MILVUS_DB_NAME)

            last_error: Exception | None = None
            self._using_implicit_database = False
            for candidate_db in candidates:
                try:
                    connect_kwargs: dict[str, Any] = {
                        "alias": self.connection_alias,
                        "uri": self.milvus_uri,
                    }
                    if self.milvus_token:
                        connect_kwargs["token"] = self.milvus_token
                    if candidate_db:
                        connect_kwargs["db_name"] = candidate_db
                    connections.connect(**connect_kwargs)
                    if candidate_db is None:
                        self._using_implicit_database = True
                    break
                except Exception as exc:
                    last_error = exc
                    continue
            else:
                if last_error:
                    raise last_error
        except Exception as exc:
            logger.error("Failed to connect to Milvus at %s: %s", self.milvus_uri, exc)
            raise

    async def aquery(self, query_text: str, kb_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Perform semantic search against Milvus vector store."""
        vector_store = AcademicKGVectorStore()
        return vector_store.search(query_text, top_k=kwargs.get("top_k", 10))

    def get_query_params_config(self) -> dict[str, Any]:
        """Return UI query parameter options schema."""
        return {
            "type": "milvus",
            "options": [
                {"key": "search_mode", "label": "Search Mode", "type": "select", "default": "vector"},
                {"key": "top_k", "label": "Top K", "type": "number", "default": 10},
            ],
        }

    def __del__(self) -> None:
        """Safely disconnect connection alias on object deletion."""
        try:
            if hasattr(self, "connection_alias"):
                connections.disconnect(self.connection_alias)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# 3. AcademicKGVectorStore Class (Object-Oriented GraphRAG Vector Store)
# ═══════════════════════════════════════════════════════════════════════════

class AcademicKGVectorStore:
    """
    Object-oriented Milvus Vector Store Manager for UNESA Academic Knowledge Graph.
    Encapsulates schema creation, record building, vector embedding, and persistence
    across 4 specialized GraphRAG collections:
    1. PaperChunk — Abstract & text chunk vector embeddings.
    2. EntityEmbedding — Node entity embeddings (Lecturer, Publication, Concept, Venue, Institution).
    3. RelationshipEmbedding — Edge sub-graph relation embeddings (HAS_AUTHOR, COLLABORATES_WITH, REFERS_TO).
    4. ContentKeyword — IEEE thesaurus & keyphrase term embeddings.
    """

    def __init__(self, config: MilvusVectorIndexConfig | None = None):
        self.config = config or milvus_config_from_env()

    # ── CLIENT & CONNECTION MANAGEMENT ─────────────────────────────────────

    def _get_client(self) -> Any:
        """Instantiate MilvusClient from configuration."""
        if not MILVUS_AVAILABLE:
            raise ImportError("Install pymilvus first: pip install pymilvus")

        uri = self.config.uri or os.getenv("MILVUS_URI", "http://localhost:19530")
        if "milvus:" in uri or "milvus" in uri:
            import socket
            try:
                socket.gethostbyname("milvus")
            except Exception:
                uri = uri.replace("://milvus:", "://localhost:").replace("http://milvus:", "http://localhost:")

        kwargs: dict[str, Any] = {"uri": uri, "token": self.config.token}
        db_name = self.config.db_name
        if db_name:
            try:
                temp_client = MilvusClient(uri=uri, token=self.config.token)
                dbs = temp_client.list_databases()
                if db_name not in dbs and hasattr(temp_client, "create_database"):
                    temp_client.create_database(db_name)
                temp_client.close()
                kwargs["db_name"] = db_name
            except Exception:
                pass

        try:
            return MilvusClient(**kwargs)
        except Exception:
            kwargs.pop("db_name", None)
            client = MilvusClient(**kwargs)
            if db_name and hasattr(client, "using_database"):
                try:
                    client.using_database(db_name)
                except Exception:
                    pass
            return client

    # ── PUBLIC GRAPH VECTOR STORE API ──────────────────────────────────────

    def build_index_records(self, graph: nx.MultiDiGraph, *, graph_name: str = "") -> dict[str, list[dict[str, Any]]]:
        """Build Milvus records for 3 AcademicRAG collections (chunks_vdb, entities_vdb, relationships_vdb)."""
        return {
            "chunks_vdb": self._paper_chunk_records(graph, graph_name=graph_name),
            "entities_vdb": self._entity_embedding_records(graph, graph_name=graph_name),
            "relationships_vdb": self._relationship_embedding_records(graph, graph_name=graph_name),
        }

    def write_vector_index(
        self,
        graph: nx.MultiDiGraph,
        *,
        clear_existing: bool = False,
        normalize_embeddings: bool = False,
        graph_name: str = "yunesa_academic_kg",
    ) -> dict[str, Any]:
        """Write Academic GraphRAG Dual-Index vector collections to Milvus / Zilliz Cloud."""
        records = self.build_index_records(graph, graph_name=graph_name)
        preflight = _validate_milvus_varchar_records(records)
        logger.info(
            "milvus.preflight.passed | graph_name=%s | collections=%s | rows=%s",
            graph_name,
            preflight["collections"],
            preflight["rows"],
        )
        client = self._get_client()
        insert_batch_size = _positive_env_int("YUNESA_MILVUS_INSERT_BATCH_SIZE", 128)

        report: dict[str, Any] = {
            "uri_configured": bool(self.config.uri),
            "db_name": self.config.db_name or "",
            "embedding_model": self.config.embedding_model,
            "embedding_provider": self.config.embedding_provider,
            "embedding_dim": self.config.embedding_dim,
            "metric_type": self.config.metric_type,
            "graph_name": graph_name,
            "varchar_preflight": preflight,
            "collections": {},
        }

        try:
            for collection_name, rows in records.items():
                self._ensure_collection(
                    client,
                    collection_name=collection_name,
                    embedding_dim=self.config.embedding_dim,
                    metric_type=self.config.metric_type,
                    clear_existing=clear_existing,
                )
                deleted_report: dict[str, Any] = {}
                if clear_existing:
                    deleted_report = self._delete_graph_records(client, collection_name, graph_name)
                inserted = 0
                for start in range(0, len(rows), insert_batch_size):
                    batch = rows[start : start + insert_batch_size]
                    if not batch:
                        continue
                    embedded_batch = _embed_milvus_record_batch(
                        batch,
                        provider=self.config.embedding_provider,
                        model_name=self.config.embedding_model,
                        batch_size=self.config.batch_size,
                        normalize_embeddings=normalize_embeddings,
                    )
                    client.insert(collection_name=collection_name, data=embedded_batch)
                    inserted += len(embedded_batch)
                    del embedded_batch
                try:
                    client.flush(collection_name)
                except Exception:
                    pass
                try:
                    client.load_collection(collection_name)
                except Exception:
                    pass
                try:
                    stats = client.get_collection_stats(collection_name)
                except Exception:
                    stats = {}
                graph_row_count = self._count_graph_records(client, collection_name, graph_name)
                report["collections"][collection_name] = {
                    "prepared_rows": len(records.get(collection_name, [])),
                    "inserted_rows": inserted,
                    "deleted_existing_graph_rows": deleted_report,
                    "graph_row_count": graph_row_count,
                    "stats": stats,
                }
            return report
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def inspect_collections(self) -> dict[str, Any]:
        """Read collection schemas and row counts from Milvus / Zilliz Cloud."""
        client = self._get_client()
        try:
            collections = client.list_collections()
            report: dict[str, Any] = {
                "db_name": self.config.db_name or "",
                "collections": {},
            }
            for collection_name in collections:
                try:
                    stats = client.get_collection_stats(collection_name)
                except Exception:
                    stats = {}
                try:
                    desc = client.describe_collection(collection_name)
                except Exception:
                    desc = {}
                fields = [
                    {
                        "name": field.get("name"),
                        "type": str(field.get("type")),
                        "params": field.get("params", {}),
                    }
                    for field in desc.get("fields", [])
                ]
                try:
                    sample = client.query(collection_name=collection_name, filter="", limit=1, output_fields=["*"])
                    sample_keys = sorted(sample[0].keys()) if sample else []
                except Exception:
                    sample_keys = []
                report["collections"][collection_name] = {
                    "stats": stats,
                    "fields": fields,
                    "sample_keys": sample_keys,
                }
            return report
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def search(self, query_text: str, collection_name: str = "PaperChunk", top_k: int = 10) -> list[dict[str, Any]]:
        """Perform semantic search against a target Milvus collection."""
        client = self._get_client()
        try:
            results = client.search(
                collection_name=collection_name,
                data=[query_text],
                limit=top_k,
                output_fields=["*"],
            )
            hits: list[dict[str, Any]] = []
            for raw_hit in (results[0] if results else []):
                entity = raw_hit.get("entity", {})
                hits.append({
                    "content": entity.get("content", entity.get("description", "")),
                    "score": float(raw_hit.get("distance", 0.0)),
                    "metadata": entity,
                })
            return hits
        except Exception as exc:
            logger.warning("Milvus vector search error on collection %s: %s", collection_name, exc)
            return []

    # ── PRIVATE GRAPH RECORD GENERATION HELPERS ────────────────────────────

    def _node_label(self, data: dict[str, Any], node_id: str) -> str:
        return field_value(data, "label", "name", "title", "nama_norm", default=node_id)

    def _node_source_id(self, data: dict[str, Any], node_id: str) -> str:
        return field_value(
            data,
            "paper_id",
            "nip",
            "scopus_id",
            "scholar_id",
            "ieee_uri",
            "value",
            default=node_id,
        )

    def _node_description(self, node_id: str, data: dict[str, Any]) -> str:
        node_type = field_value(data, "node_type", default="KGNode")
        label = self._node_label(data, node_id)
        parts = [f"{node_type}: {label}"]

        if node_type == "Publication":
            for key in ["title", "tldr", "abstract", "keywords", "document_type", "year", "venue"]:
                val = field_value(data, key)
                if val:
                    parts.append(f"{key}: {val}")
        elif node_type == "Lecturer":
            for key in ["nama_dosen", "prodi", "nidn", "scopus_id", "scholar_id", "sinta_id"]:
                val = field_value(data, key)
                if val:
                    parts.append(f"{key}: {val}")
        elif node_type == "Concept":
            for key in ["concept_type", "source", "ieee_uri"]:
                val = field_value(data, key)
                if val:
                    parts.append(f"{key}: {val}")
        else:
            for key in ["name", "value", "institution_type", "source"]:
                val = field_value(data, key)
                if val:
                    parts.append(f"{key}: {val}")

        return " | ".join(parts)

    def _publication_concept_labels(self, graph: nx.MultiDiGraph, paper_node: str) -> list[str]:
        labels: list[str] = []
        for _, target, data in graph.out_edges(paper_node, data=True):
            if canonical_relation(data.get("relation")) not in CONCEPT_RELATIONS:
                continue
            target_data = graph.nodes[target]
            lbl = self._node_label(target_data, target)
            if lbl:
                labels.append(lbl)
        return list(dict.fromkeys(labels))

    def _publication_author_labels(self, graph: nx.MultiDiGraph, paper_node: str) -> list[str]:
        labels: list[str] = []
        for _, target, data in graph.out_edges(paper_node, data=True):
            if canonical_relation(data.get("relation")) != "HAS_AUTHOR":
                continue
            target_data = graph.nodes[target]
            lbl = self._node_label(target_data, target)
            if lbl:
                labels.append(lbl)
        for source, _, data in graph.in_edges(paper_node, data=True):
            if canonical_relation(data.get("relation")) not in {"PUBLISHES", "WRITES"}:
                continue
            source_data = graph.nodes[source]
            lbl = self._node_label(source_data, source)
            if lbl:
                labels.append(lbl)
        return list(dict.fromkeys(labels))

    def _publication_document_payload(self, graph: nx.MultiDiGraph, paper_node: str) -> dict[str, Any]:
        data = graph.nodes[paper_node]
        concepts = self._publication_concept_labels(graph, paper_node)
        authors = self._publication_author_labels(graph, paper_node)
        keywords = split_list_field(field_value(data, "keywords"))
        doc_text = "\n".join(
            part
            for part in [
                f"Title: {field_value(data, 'title', 'label')}",
                f"TLDR: {field_value(data, 'tldr')}",
                f"Abstract: {field_value(data, 'abstract')}",
                f"Keywords: {', '.join(keywords)}",
                f"Concepts: {', '.join(concepts)}",
                f"Authors: {', '.join(authors)}",
                f"Document type: {field_value(data, 'document_type')}",
                f"DOI: {field_value(data, 'doi')}",
                f"Link: {field_value(data, 'link')}",
            ]
            if not part.endswith(": ")
        )
        doc_id = field_value(data, "paper_id", default=paper_node)
        return {
            "doc_id": doc_id,
            "paper_node": paper_node,
            "title": field_value(data, "title", "label"),
            "content": doc_text,
            "content_hash": content_hash(doc_text),
            "year": field_value(data, "year"),
            "paperUrl": field_value(data, "link", "doi"),
            "authors": ", ".join(authors),
            "keywords": ", ".join(keywords),
            "concepts": ", ".join(concepts),
        }

    def _paper_chunk_records(self, graph: nx.MultiDiGraph, *, graph_name: str = "") -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for node_id, data in graph.nodes(data=True):
            if data.get("node_type") != "Publication":
                continue
            payload = self._publication_document_payload(graph, node_id)
            for index, chunk in enumerate(semantic_text_chunks(payload["content"])):
                content = (
                    f"doc_id: {payload['doc_id']} | chunk_order_index: {index} | "
                    f"content_hash: {content_hash(chunk)} | {chunk}"
                )
                rows.append({
                    "graphName": _truncate_milvus("chunks_vdb", "graphName", graph_name),
                    "title": _truncate_milvus("chunks_vdb", "title", payload["title"]),
                    "content": _truncate_milvus("chunks_vdb", "content", content),
                    "year": _truncate_milvus("chunks_vdb", "year", payload["year"]),
                    "paperUrl": _truncate_milvus("chunks_vdb", "paperUrl", payload["paperUrl"]),
                    "authors": _truncate_milvus("chunks_vdb", "authors", payload["authors"]),
                    "_embedding_text": content,
                })
        return rows

    def _entity_embedding_records(self, graph: nx.MultiDiGraph, *, graph_name: str = "") -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for node_id, data in graph.nodes(data=True):
            node_type = field_value(data, "concept_type", "node_type", default="KGNode")
            if data.get("node_type") == "Year":
                continue
            label = self._node_label(data, node_id)
            description = self._node_description(node_id, data)
            rows.append({
                "graphName": _truncate_milvus("entities_vdb", "graphName", graph_name),
                "entityName": _truncate_milvus("entities_vdb", "entityName", label),
                "entityType": _truncate_milvus("entities_vdb", "entityType", node_type),
                "description": _truncate_milvus("entities_vdb", "description", description),
                "nodeId": _truncate_milvus("entities_vdb", "nodeId", node_id),
                "sourceId": _truncate_milvus("entities_vdb", "sourceId", self._node_source_id(data, node_id)),
                "_embedding_text": description,
            })
        return rows

    def _relationship_embedding_records(self, graph: nx.MultiDiGraph, *, graph_name: str = "") -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for source, target, key, data in graph.edges(keys=True, data=True):
            source_data = graph.nodes[source]
            target_data = graph.nodes[target]
            rel_type = canonical_relation(field_value(data, "relation", default="RELATED_TO"))
            source_label = self._node_label(source_data, source)
            target_label = self._node_label(target_data, target)
            provenance = field_value(data, "provenance", "source")
            description = (
                f"{source_label} ({source_data.get('node_type', 'Node')}) "
                f"-[{rel_type}]-> "
                f"{target_label} ({target_data.get('node_type', 'Node')})"
            )
            if provenance:
                description += f" | provenance: {provenance}"
            rows.append({
                "graphName": _truncate_milvus("relationships_vdb", "graphName", graph_name),
                "srcId": _truncate_milvus("relationships_vdb", "srcId", source),
                "tgtId": _truncate_milvus("relationships_vdb", "tgtId", target),
                "relType": _truncate_milvus("relationships_vdb", "relType", rel_type),
                "description": _truncate_milvus("relationships_vdb", "description", description),
                "sourceId": _truncate_milvus(
                    "relationships_vdb",
                    "sourceId",
                    f"{self._node_source_id(source_data, source)}::{self._node_source_id(target_data, target)}::{key}",
                ),
                "_embedding_text": description,
            })
        return rows

    # ── PRIVATE MILVUS SCHEMA & COLLECTION MANAGERS ────────────────────────

    def _create_collection_schema(self, collection_name: str, embedding_dim: int) -> Any:
        schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        for field_name, max_length in MILVUS_VARCHAR_LIMITS[collection_name].items():
            schema.add_field(field_name=field_name, datatype=DataType.VARCHAR, max_length=max_length)
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=embedding_dim)
        return schema

    def _delete_graph_records(self, client: Any, collection_name: str, graph_name: str) -> dict[str, Any]:
        if not graph_name:
            return {"skipped": True, "reason": "graph_name_empty"}
        try:
            safe_val = safe_str(graph_name).replace("\\", "\\\\").replace('"', '\\"')
            result = client.delete(
                collection_name=collection_name,
                filter=f'graphName == "{safe_val}"',
            )
            return {"skipped": False, "result": result}
        except Exception as exc:
            return {"skipped": False, "error_type": type(exc).__name__, "error": str(exc)}

    def _count_graph_records(self, client: Any, collection_name: str, graph_name: str) -> dict[str, Any]:
        if not graph_name:
            return {"skipped": True, "reason": "graph_name_empty"}
        limit = 16384
        try:
            safe_val = safe_str(graph_name).replace("\\", "\\\\").replace('"', '\\"')
            rows = client.query(
                collection_name=collection_name,
                filter=f'graphName == "{safe_val}"',
                output_fields=["graphName"],
                limit=limit,
            )
            return {"skipped": False, "count": len(rows), "limit": limit, "exact": len(rows) < limit}
        except Exception as exc:
            return {"skipped": False, "error_type": type(exc).__name__, "error": str(exc)}

    def _ensure_collection(
        self,
        client: Any,
        *,
        collection_name: str,
        embedding_dim: int,
        metric_type: str,
        clear_existing: bool,
    ) -> None:
        exists = bool(client.has_collection(collection_name))
        if exists:
            try:
                desc = client.describe_collection(collection_name)
                field_names = {safe_str(f.get("name")) for f in desc.get("fields", []) if f.get("name")}
            except Exception:
                field_names = set()

            if "graphName" not in field_names:
                if clear_existing:
                    client.drop_collection(collection_name)
                    exists = False
                else:
                    raise RuntimeError(
                        f"Milvus collection {collection_name!r} uses an old schema without graphName. "
                        "Run with clear_existing=True once to rebuild it safely."
                    )
            else:
                return

        if not exists:
            schema = self._create_collection_schema(collection_name, embedding_dim)
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="AUTOINDEX",
                metric_type=metric_type,
            )
            client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
            )


# ═══════════════════════════════════════════════════════════════════════════
# 4. Public Module-Level API & Backward-Compatibility Wrappers
# ═══════════════════════════════════════════════════════════════════════════

def _node_label(data: dict[str, Any], node_id: str) -> str:
    store = AcademicKGVectorStore()
    return store._node_label(data, node_id)


def _publication_author_labels(graph: nx.MultiDiGraph, paper_node: str) -> list[str]:
    store = AcademicKGVectorStore()
    return store._publication_author_labels(graph, paper_node)


def _publication_concept_labels(graph: nx.MultiDiGraph, paper_node: str) -> list[str]:
    store = AcademicKGVectorStore()
    return store._publication_concept_labels(graph, paper_node)


def build_academicrag_document_records(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Build document status and text chunk records analogous to AcademicRAG KV stores."""
    store = AcademicKGVectorStore()
    payloads = [store._publication_document_payload(graph, node_id) for node_id, data in graph.nodes(data=True) if data.get("node_type") == "Publication"]
    full_docs = [{"doc_id": p["doc_id"], "paper_node": p["paper_node"], "content": p["content"], "content_hash": p["content_hash"], "title": p["title"], "source": "supabase.papers"} for p in payloads]
    text_chunks = []
    for p in payloads:
        chunks = semantic_text_chunks(p["content"])
        for idx, chunk in enumerate(chunks):
            text_chunks.append({
                "chunk_id": stable_id("chunk", f"{p['doc_id']}:{idx}:{chunk}"),
                "doc_id": p["doc_id"],
                "paper_node": p["paper_node"],
                "chunk_order_index": idx,
                "content": chunk,
                "content_hash": content_hash(chunk),
                "tokens_estimate": max(1, len(chunk.split())),
                "source": "notebook_kg_construction",
            })
    return {"full_docs": full_docs, "text_chunks": text_chunks, "doc_status": []}


def summarize_academicrag_document_records(records: dict[str, Any]) -> dict[str, int]:
    return {key: len(value) for key, value in records.items()}


def build_milvus_index_records(graph: nx.MultiDiGraph, *, graph_name: str = "") -> dict[str, list[dict[str, Any]]]:
    """Build Milvus records without embeddings for previewing and deterministic export."""
    store = AcademicKGVectorStore()
    return store.build_index_records(graph, graph_name=graph_name)


def summarize_milvus_records(records_by_collection: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """Return count summary of records across all 4 Milvus GraphRAG collections."""
    return {collection: len(rows) for collection, rows in records_by_collection.items()}


def write_vector_index_to_milvus(
    graph: nx.MultiDiGraph,
    *,
    config: MilvusVectorIndexConfig | None = None,
    clear_existing: bool = False,
    normalize_embeddings: bool = False,
    graph_name: str = "yunesa_academic_kg",
) -> dict[str, Any]:
    """Write Academic GraphRAG Dual-Index vector collections to Milvus / Zilliz Cloud."""
    store = AcademicKGVectorStore(config)
    return store.write_vector_index(
        graph,
        clear_existing=clear_existing,
        normalize_embeddings=normalize_embeddings,
        graph_name=graph_name,
    )


def inspect_milvus_collections(config: MilvusVectorIndexConfig | None = None) -> dict[str, Any]:
    """Read collection schemas and row counts from Milvus / Zilliz Cloud."""
    store = AcademicKGVectorStore(config)
    return store.inspect_collections()
