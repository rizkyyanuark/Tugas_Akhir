"""
milvus_graph_vector_store.py — Milvus Graph Vector Store Module
================================================================
Re-exports AcademicKGVectorStore for GraphRAG Milvus vector collection management.
Matches Yuxi's yuxi/knowledge/graphs/milvus_graph_vector_store.py architecture location.
"""

from __future__ import annotations

from yunesa.knowledge.implementations.milvus import (
    AcademicKGVectorStore,
    write_vector_index_to_milvus,
    build_milvus_index_records,
    inspect_milvus_collections,
)

# Alias for Yuxi naming compatibility
MilvusGraphVectorStore = AcademicKGVectorStore

__all__ = [
    "AcademicKGVectorStore",
    "MilvusGraphVectorStore",
    "write_vector_index_to_milvus",
    "build_milvus_index_records",
    "inspect_milvus_collections",
]
