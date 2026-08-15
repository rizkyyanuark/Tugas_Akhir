"""Concrete knowledge base implementations for UNESA Academic Knowledge Graph.

Available backends:
- MilvusKB: Standard vector knowledge base powered by Milvus / Zilliz Cloud.
- AcademicKGVectorStore: Object-oriented GraphRAG vector store manager.
"""

from .milvus import (
    MilvusKB,
    AcademicKGVectorStore,
    write_vector_index_to_milvus,
    build_milvus_index_records,
    summarize_milvus_records,
    inspect_milvus_collections,
)

__all__ = [
    "MilvusKB",
    "AcademicKGVectorStore",
    "write_vector_index_to_milvus",
    "build_milvus_index_records",
    "summarize_milvus_records",
    "inspect_milvus_collections",
]
