"""
Local Retriever: Subgraph-Based Local Extraction
==================================================
Implements Step ② of AcademicRAG (Eq. 3.3 Proposal):
  low_level keywords → EntityEmbedding VDB → matched nodes
  → BFS shortest path → prune → text units

Output: ℒ_local = (ℰ, ℛ, 𝒯)
"""

import logging
from typing import Dict, List, Any, Optional

from .storage.neo4j_adapter import Neo4jGraphStorage
from .storage.weaviate_adapter import WeaviateVectorStorage
from .storage.kv_adapter import JsonKVStore
from .config import ENTITY_TOP_K

logger = logging.getLogger(__name__)


async def subgraph_retrieve(
    ll_keywords: List[str],
    neo4j: Neo4jGraphStorage,
    weaviate: WeaviateVectorStorage,
    chunks_db: JsonKVStore,
    entity_top_k: int = ENTITY_TOP_K,
) -> Dict[str, Any]:
    """Subgraph-based local retrieval (Eq. 3.3 Proposal).

    1. low_level keywords → EntityEmbedding VDB → matched entity node_ids
    2. Entity nodes → BFS shortest paths → smallest connected subgraph
    3. Subgraph nodes/edges → extract source_ids → text units from KV store

    Args:
        ll_keywords: Low-level keywords from keyword extraction.
        neo4j: Neo4j graph storage adapter.
        weaviate: Weaviate vector storage adapter.
        chunks_db: JSON KV store for text chunks.
        entity_top_k: Max entities to retrieve from VDB.

    Returns:
        Dict with entities, relationships, text_units, and raw subgraph data.
    """
    if not ll_keywords:
        logger.info("Local retrieval: no low-level keywords provided")
        return {"entities": [], "relationships": [], "text_units": []}

    # Step 1: Query EntityEmbedding VDB with all LL keywords
    combined_query = " ".join(ll_keywords)
    entity_results = weaviate.query_entities(combined_query, top_k=entity_top_k)

    # Extract unique node_ids from VDB results
    seed_node_ids = list(set(
        r["nodeId"] for r in entity_results if r.get("nodeId")
    ))

    logger.info(f"Local retrieval: {len(entity_results)} entities matched, {len(seed_node_ids)} unique nodes")

    if not seed_node_ids:
        return {"entities": entity_results, "relationships": [], "text_units": []}

    # Step 2: BFS subgraph extraction
    subgraph_nodes, subgraph_edges = neo4j.get_smallest_subgraph(
        seed_node_ids=seed_node_ids[:10],  # Limit seeds to avoid oversized subgraphs
    )

    logger.info(f"Subgraph extracted: {len(subgraph_nodes)} nodes, {len(subgraph_edges)} edges")

    # Step 3: Extract text units via source_id
    source_ids = set()
    for node in subgraph_nodes:
        sid = node.get("source_id")
        if sid:
            source_ids.add(sid)
    for edge in subgraph_edges:
        sid = edge.get("source_id")
        if sid:
            source_ids.add(sid)
    # Also get source_ids from entity VDB results
    for r in entity_results:
        sid = r.get("sourceId")
        if sid:
            source_ids.add(sid)

    text_units = chunks_db.get_by_ids(list(source_ids))
    logger.info(f"Text units retrieved: {len(text_units)} from {len(source_ids)} source_ids")

    return {
        "entities": entity_results,
        "relationships": subgraph_edges,
        "text_units": text_units,
        "subgraph_nodes": subgraph_nodes,
    }
