"""YUNESA Academic Knowledge Graph public entrypoints.

The canonical KG construction and GraphRAG implementation lives in
``yunesa_academic_kg.py``. Older modules in this package are kept only for
backward compatibility with historical notebooks.

Production Airflow tasks, CLI runners, and Jupyter notebooks should all
import from this package::

    from knowledge.etl.kg import AcademicKGBuilder, graphrag_retrieve
    from knowledge.etl.kg.yunesa_academic_kg import run_local_kg_pipeline
"""

from .yunesa_academic_kg import (
    AcademicKGBuilder,
    GraphRAGGenerationParam,
    GraphRAGQueryParam,
    KGConfig,
    fetch_postgres_sample,
    fetch_supabase_sample,
    generate_graphrag_answer_with_groq,
    graphrag_answer,
    graphrag_retrieve,
    run_local_kg_pipeline,
    write_graph_to_neo4j,
    write_vector_index_to_milvus,
)

__all__ = [
    "AcademicKGBuilder",
    "GraphRAGGenerationParam",
    "GraphRAGQueryParam",
    "KGConfig",
    "fetch_postgres_sample",
    "fetch_supabase_sample",
    "generate_graphrag_answer_with_groq",
    "graphrag_answer",
    "graphrag_retrieve",
    "run_local_kg_pipeline",
    "write_graph_to_neo4j",
    "write_vector_index_to_milvus",
]
