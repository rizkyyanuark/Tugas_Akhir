"""RRF fusion and Neo4j degree-based reranking services for Academic GraphRAG."""

from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import Any

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

# Hardcoded default values
RRF_K = 60


def run_cypher_query(
    query: str,
    params: dict[str, Any],
    neo4j_storage: Any = None,
) -> list[dict[str, Any]]:
    """Execute a Cypher query on Neo4j.

    Tries to reuse the active connection driver from neo4j_storage first.
    Falls back to environment variables if driver is missing.
    """
    driver_to_close = None
    driver = None
    database = "neo4j"

    # Try to extract the driver from the active storage adapter
    if neo4j_storage is not None:
        try:
            adapter = getattr(neo4j_storage, "adapter", None)
            service = getattr(adapter, "service", None)
            if service is not None:
                driver = getattr(service, "driver", None)
                database = getattr(service, "_neo4j_database", lambda: "neo4j")()
        except Exception as e:
            logger.debug(f"Could not extract Neo4j driver from storage: {e}")

    # Fallback to creating a temporary driver from environment variables
    if driver is None:
        uri = os.getenv("NEO4J_URI")
        username = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        database = os.getenv("NEO4J_DATABASE") or "neo4j"
        if uri and username and password:
            try:
                driver = GraphDatabase.driver(uri, auth=(username, password))
                driver_to_close = driver
            except Exception as e:
                logger.error(f"Failed to create temporary Neo4j driver: {e}")

    if driver is None:
        logger.warning("No Neo4j driver available. Cypher query skipped.")
        return []

    try:
        with driver.session(database=database) as session:
            res = session.run(query, **params)
            return [dict(r) for r in res]
    except Exception as e:
        logger.error(f"Neo4j Cypher query execution failed: {e}")
        return []
    finally:
        if driver_to_close is not None:
            try:
                driver_to_close.close()
            except Exception:
                pass


def reciprocal_rank_fusion(
    papers: list[dict[str, Any]],
    graph_ranks: dict[str, int],
    k: int = RRF_K,
) -> list[dict[str, Any]]:
    """Merge vector search ranks and graph connection ranks using Reciprocal Rank Fusion (RRF)."""
    if not papers:
        return []

    # Sort papers by vector semantic distance to establish vector ranks (1-indexed)
    sorted_by_vector = sorted(papers, key=lambda x: x.get("distance", 0.0), reverse=False)
    vector_ranks = {id(paper): i + 1 for i, paper in enumerate(sorted_by_vector)}

    # Graph ranks represent the match counts (higher count is better).
    # Sort papers by match_count descending to establish graph connection ranks (1-indexed)
    sorted_by_graph = sorted(papers, key=lambda x: graph_ranks.get(x.get("title") or "", 0), reverse=True)
    graph_ranks_indices = {id(paper): i + 1 for i, paper in enumerate(sorted_by_graph)}

    for paper in papers:
        p_id = id(paper)
        v_rank = vector_ranks.get(p_id, len(papers) + 1)
        g_rank = graph_ranks_indices.get(p_id, len(papers) + 1)
        # RRF formula
        rrf_score = 1.0 / (k + v_rank) + 1.0 / (k + g_rank)
        paper["rrf_score"] = rrf_score

    # Sort descending by rrf_score (highest score first)
    return sorted(papers, key=lambda x: x.get("rrf_score", 0.0), reverse=True)


async def degree_rerank_entities(
    entities: list[dict[str, Any]],
    neo4j_storage: Any,
    graph_name: str,
) -> list[dict[str, Any]]:
    """Rerank entities by scaling distance based on their Neo4j node degree."""
    if not entities:
        return []

    node_ids = list({str(e.get("nodeId")) for e in entities if e.get("nodeId")})
    if not node_ids:
        return entities

    query = """
    UNWIND $node_ids AS nid
    MATCH (n:KGNode {id: nid})
    WHERE $graph_name = '' OR n.graph_name = $graph_name
    RETURN n.id AS nodeId, count { (n)-[]-() } AS degree
    """
    params = {"node_ids": node_ids, "graph_name": graph_name}

    try:
        rows = await asyncio.to_thread(run_cypher_query, query, params, neo4j_storage)
        degrees = {r["nodeId"]: r["degree"] for r in rows if "nodeId" in r}

        for ent in entities:
            node_id = ent.get("nodeId")
            deg = degrees.get(node_id, 0)
            ent["degree"] = deg
            # Scale down distance based on degree (lower distance is better)
            # Formula matching notebook: distance / (1.0 + 0.15 * log(degree + 1.0))
            ent["distance"] = ent.get("distance", 0.0) / (1.0 + 0.15 * math.log(deg + 1.0))

        # Sort ascending (lower distance is better)
        return sorted(entities, key=lambda x: x.get("distance", 0.0), reverse=False)

    except Exception as e:
        logger.warning(f"Entity degree reranking failed: {e}. Returning original.")
        return entities


async def degree_rerank_relationships(
    relationships: list[dict[str, Any]],
    neo4j_storage: Any,
    graph_name: str,
) -> list[dict[str, Any]]:
    """Rerank relationships by scaling distance based on source and target Neo4j degrees."""
    if not relationships:
        return []

    node_ids = set()
    for rel in relationships:
        if rel.get("srcId"):
            node_ids.add(str(rel.get("srcId")))
        if rel.get("tgtId"):
            node_ids.add(str(rel.get("tgtId")))

    if not node_ids:
        return relationships

    query = """
    UNWIND $node_ids AS nid
    MATCH (n:KGNode {id: nid})
    WHERE $graph_name = '' OR n.graph_name = $graph_name
    RETURN n.id AS nodeId, count { (n)-[]-() } AS degree
    """
    params = {"node_ids": list(node_ids), "graph_name": graph_name}

    try:
        rows = await asyncio.to_thread(run_cypher_query, query, params, neo4j_storage)
        degrees = {r["nodeId"]: r["degree"] for r in rows if "nodeId" in r}

        for rel in relationships:
            src_id = rel.get("srcId")
            tgt_id = rel.get("tgtId")
            src_deg = degrees.get(src_id, 0)
            tgt_deg = degrees.get(tgt_id, 0)
            # Scale down distance based on source + target degrees
            # Formula matching notebook: distance / (1.0 + 0.05 * (log(src_deg + 1) + log(tgt_deg + 1)))
            rel["distance"] = rel.get("distance", 0.0) / (
                1.0 + 0.05 * (math.log(src_deg + 1.0) + math.log(tgt_deg + 1.0))
            )

        # Sort ascending
        return sorted(relationships, key=lambda x: x.get("distance", 0.0), reverse=False)

    except Exception as e:
        logger.warning(f"Relationship degree reranking failed: {e}. Returning original.")
        return relationships


async def graph_connection_rank(
    papers: list[dict[str, Any]],
    entity_ids: list[str],
    neo4j_storage: Any,
    graph_name: str,
) -> dict[str, int]:
    """Query Neo4j to find the match count of each paper against the retrieved entities."""
    if not papers or not entity_ids:
        return {}

    paper_titles = list({p.get("title") for p in papers if p.get("title")})
    if not paper_titles:
        return {}

    query = """
    UNWIND $titles AS paper_title
    MATCH (p:Publication) WHERE p.title = paper_title
    AND ($graph_name = '' OR p.graph_name = $graph_name)
    OPTIONAL MATCH (p)-[r]-(e:KGNode)
    WHERE e.id IN $entity_ids
    RETURN paper_title, count(DISTINCT e) AS match_count
    """
    params = {
        "titles": paper_titles,
        "entity_ids": entity_ids,
        "graph_name": graph_name,
    }

    try:
        rows = await asyncio.to_thread(run_cypher_query, query, params, neo4j_storage)
        return {r["paper_title"]: r["match_count"] for r in rows if "paper_title" in r}
    except Exception as e:
        logger.warning(f"Graph connection ranking failed: {e}")
        return {}


async def match_mentioned_entities(
    query_text: str,
    neo4j_storage: Any,
    graph_name: str,
) -> list[dict[str, Any]]:
    """Query Neo4j to find Lecturer/Venue entities explicitly mentioned in the query.

    Matches the name or label of the entity, returning them with a distance of 0.0 (highest priority).
    """
    if not query_text:
        return []

    query = """
    MATCH (n:KGNode)
    WHERE n.node_type IN ['Lecturer', 'Venue']
      AND (
        (n.nama_norm IS NOT NULL AND toLower($q) CONTAINS toLower(n.nama_norm))
        OR toLower($q) CONTAINS toLower(n.label)
      )
    RETURN n.id AS id, n.label AS label, n.node_type AS type, n.description AS description
    """
    params = {"q": query_text}

    try:
        rows = await asyncio.to_thread(run_cypher_query, query, params, neo4j_storage)
        mentioned_entities: list[dict[str, Any]] = []
        for r in rows:
            mentioned_entities.append({
                "graphName": graph_name,
                "entityName": r.get("label"),
                "entityType": r.get("type"),
                "description": r.get("description") or f"{r.get('type')}: {r.get('label')}",
                "nodeId": r.get("id"),
                "sourceId": "",
                "distance": 0.0,
            })
        return mentioned_entities
    except Exception as e:
        logger.warning(f"Failed to match mentioned entities in Neo4j: {e}")
        return []
