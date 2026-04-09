"""
GraphRAG: Hybrid Vector-Graph Retrieval Module
================================================
Implements the AcademicRAG (Chen, 2025) architecture for
querying UNESA's academic Knowledge Graph.

Public API:
    from ta_backend_core.knowledge.graphrag import GraphRAGQuery
    gq = GraphRAGQuery()
    result = await gq.query("Siapa dosen yang meneliti deep learning?")
"""

__version__ = "0.1.0"
