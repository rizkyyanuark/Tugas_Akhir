"""
Global Retriever: Edge Network Global Retrieval
=================================================
Implements Step ③ of AcademicRAG (Eq. 3.4 Proposal):
  high_level keywords → RelationshipEmbedding VDB → top-k edges
  → nodes by degree → text units

Output: ℒ_global = (ℰ, ℛ, 𝒯)
"""

import logging
from typing import Dict, List, Any

from .storage.neo4j_adapter import Neo4jGraphStorage
from .storage.milvus_adapter import MilvusVectorStorage
from .storage.kv_adapter import JsonKVStore
from .config import RELATIONSHIP_TOP_K

logger = logging.getLogger(__name__)


async def global_edge_retrieve(
    hl_keywords: List[str],
    neo4j: Neo4jGraphStorage,
    milvus: MilvusVectorStorage,
    chunks_db: JsonKVStore,
    rel_top_k: int = RELATIONSHIP_TOP_K,
) -> Dict[str, Any]:
    """Global edge network retrieval (Eq. 3.4 Proposal).

    1. high_level keywords → RelationshipEmbedding VDB → top-k edges
    2. Collect unique node_ids from edge endpoints → rank by degree
    3. Source_ids from edges → text units from KV store

    Args:
        hl_keywords: High-level keywords from keyword extraction.
        neo4j: Neo4j graph storage adapter.
        milvus: Milvus vector storage adapter.
        chunks_db: JSON KV store for text chunks.
        rel_top_k: Max relationships to retrieve from VDB.

    Returns:
        Dict with entities, relationships, text_units.
    """
    if not hl_keywords:
        logger.info("Global retrieval: no high-level keywords provided")
        return {"entities": [], "relationships": [], "text_units": []}

    # Step 1: Query RelationshipEmbedding VDB
    combined_query = " ".join(hl_keywords)
    rel_results = milvus.query_relationships(combined_query, top_k=rel_top_k)

    logger.info(f"Global retrieval: {len(rel_results)} relationships matched")

    if not rel_results:
        return {"entities": [], "relationships": rel_results, "text_units": []}

    # Step 2: Collect unique node_ids from edge endpoints
    node_ids = set()
    for r in rel_results:
        if r.get("srcId"):
            node_ids.add(r["srcId"])
        if r.get("tgtId"):
            node_ids.add(r["tgtId"])

    # Step 3: Rank nodes by degree in Neo4j
    ranked_nodes = neo4j.get_nodes_by_degree(list(node_ids), top_k=20)
    logger.info(f"Global nodes ranked by degree: {len(ranked_nodes)}")

    # Step 4: Extract text units via source_id
    source_ids = set()
    for r in rel_results:
        sid = r.get("sourceId")
        if sid:
            source_ids.add(sid)

    text_units = chunks_db.get_by_ids(list(source_ids))
    logger.info(f"Text units retrieved: {len(text_units)} from {len(source_ids)} source_ids")

    return {
        "entities": ranked_nodes,
        "relationships": rel_results,
        "text_units": text_units,
    }
