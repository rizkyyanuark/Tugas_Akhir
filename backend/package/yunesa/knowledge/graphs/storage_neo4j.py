"""
storage_neo4j.py — Neo4j / AuraDB Graph Database Persistence & Inspection
=============================================================================
Neo4j driver configuration, graph writing, and storage inspection.
"""

from __future__ import annotations

import os
import re
import time
import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Any
import networkx as nx

from yunesa.knowledge.utils.text_processing import (
    safe_str,
    canonical_relation,
)
from yunesa.knowledge.graphs.builder import serialisable_graph_copy

logger = logging.getLogger(__name__)


def _neo4j_label(value: Any) -> str:
    label = re.sub(r"[^A-Za-z0-9_]", "", safe_str(value))
    if not label:
        return "KGNode"
    if label[0].isdigit():
        label = f"N{label}"
    return label


def _neo4j_relation(value: Any) -> str:
    relation = canonical_relation(value)
    relation = re.sub(r"[^A-Za-z0-9_]", "_", relation.upper()).strip("_")
    return relation or "RELATED_TO"


def neo4j_credential_status() -> dict[str, bool]:
    """Return non-secret Neo4j credential availability for notebook debugging."""
    return {
        "NEO4J_URI": bool(os.getenv("NEO4J_URI")),
        "NEO4J_USERNAME": bool(os.getenv("NEO4J_USERNAME")),
        "NEO4J_PASSWORD": bool(os.getenv("NEO4J_PASSWORD")),
        "NEO4J_DATABASE": bool(os.getenv("NEO4J_DATABASE")),
    }


def neo4j_uri_for_driver(uri: str | None = None) -> str:
    """Return Neo4j URI adjusted for local host execution or container environment."""
    uri = uri or os.getenv("NEO4J_URI") or "bolt://localhost:7687"
    if "graph:" in uri:
        import socket
        try:
            socket.gethostbyname("graph")
        except Exception:
            uri = uri.replace("://graph:", "://localhost:")

    trust_self_signed = os.getenv("NEO4J_TRUST_SELF_SIGNED", "0") == "1"
    if trust_self_signed:
        uri = uri.replace("neo4j+s://", "neo4j+ssc://").replace("bolt+s://", "bolt+ssc://")
    return uri


def write_graph_to_neo4j(
    graph: nx.MultiDiGraph,
    *,
    uri: str | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
    graph_name: str = "yunesa_academic_kg",
    clear_existing: bool = False,
    batch_size: int = 500,
) -> dict[str, int]:
    """Write the NetworkX graph to Neo4j/AuraDB."""
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise ImportError("Install neo4j first: pip install neo4j") from exc

    uri = neo4j_uri_for_driver(uri)
    username = username or os.getenv("NEO4J_USERNAME")
    password = password or os.getenv("NEO4J_PASSWORD")
    database = database or os.getenv("NEO4J_DATABASE") or "neo4j"
    if not uri or not username or not password:
        raise ValueError("Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD first.")

    serialisable = serialisable_graph_copy(graph)
    node_rows_by_label_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for node_id, data in serialisable.nodes(data=True):
        node_type = _neo4j_label(data.get("node_type", "KGNode"))
        concept_type = _neo4j_label(data.get("concept_type", "")) if node_type == "Concept" and data.get("concept_type") else ""
        props = {"id": node_id, "graph_name": graph_name, **data}
        node_rows_by_label_pair[(node_type, concept_type)].append(props)

    edge_rows_by_relation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source, target, key, data in serialisable.edges(keys=True, data=True):
        relation = _neo4j_relation(data.get("relation", "RELATED_TO"))
        edge_rows_by_relation[relation].append(
            {
                "source": source,
                "target": target,
                "edge_key": str(key),
                "graph_name": graph_name,
                "props": {**data, "graph_name": graph_name, "edge_key": str(key)},
            }
        )

    def chunks(rows: list[dict[str, Any]]) -> Iterable[list[dict[str, Any]]]:
        for start in range(0, len(rows), batch_size):
            yield rows[start : start + batch_size]

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            if clear_existing:
                session.run(
                    "MATCH (n:KGNode {graph_name: $graph_name}) DETACH DELETE n",
                    graph_name=graph_name,
                )

            session.run("CREATE CONSTRAINT kg_node_id IF NOT EXISTS FOR (n:KGNode) REQUIRE n.id IS UNIQUE")
            session.run(
                "CREATE INDEX kg_node_graph_name IF NOT EXISTS "
                "FOR (n:KGNode) ON (n.graph_name)"
            )
            session.run(
                "CREATE INDEX kg_publication_year IF NOT EXISTS "
                "FOR (n:Publication) ON (n.year)"
            )

            nodes_written = 0
            for (label, sub_label), rows in node_rows_by_label_pair.items():
                label_expr = f":{label}:{sub_label}" if sub_label else f":{label}"
                query = (
                    f"UNWIND $rows AS row "
                    f"MERGE (n:KGNode{label_expr} {{id: row.id}}) "
                    f"SET n += row"
                )
                for batch in chunks(rows):
                    session.run(query, rows=batch)
                    nodes_written += len(batch)

            edges_written = 0
            for relation, rows in edge_rows_by_relation.items():
                query = (
                    f"UNWIND $rows AS row "
                    f"MATCH (s:KGNode {{id: row.source, graph_name: row.graph_name}}) "
                    f"MATCH (t:KGNode {{id: row.target, graph_name: row.graph_name}}) "
                    f"MERGE (s)-[r:{relation} {{edge_key: row.edge_key, graph_name: row.graph_name}}]->(t) "
                    f"SET r += row.props"
                )
                for batch in chunks(rows):
                    session.run(query, rows=batch)
                    edges_written += len(batch)

        return {"nodes_written": nodes_written, "edges_written": edges_written}
    finally:
        driver.close()


def inspect_neo4j_graph(
    *,
    uri: str | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
    graph_name: str | None = None,
) -> dict[str, Any]:
    """Read storage counts from Neo4j/AuraDB without mutating data."""
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise ImportError("Install neo4j first: pip install neo4j") from exc

    uri = neo4j_uri_for_driver(uri)
    username = username or os.getenv("NEO4J_USERNAME")
    password = password or os.getenv("NEO4J_PASSWORD")
    database = database or os.getenv("NEO4J_DATABASE") or "neo4j"
    if not uri or not username or not password:
        raise ValueError("Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD first.")

    graph_filter = "WHERE n.graph_name = $graph_name" if graph_name else ""
    publication_filter = "WHERE p.graph_name = $graph_name" if graph_name else ""
    rel_filter = "WHERE r.graph_name = $graph_name" if graph_name else ""
    params = {"graph_name": graph_name}

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            node_count = session.run(
                f"MATCH (n:KGNode) {graph_filter} RETURN count(n) AS count",
                **params,
            ).single()["count"]
            rel_count = session.run(
                f"MATCH (:KGNode)-[r]->(:KGNode) {rel_filter} RETURN count(r) AS count",
                **params,
            ).single()["count"]
            label_rows = session.run(
                f"""
                MATCH (n:KGNode)
                {graph_filter}
                UNWIND labels(n) AS label
                WITH label, count(*) AS count
                WHERE label <> 'KGNode'
                RETURN label, count
                ORDER BY count DESC, label
                """,
                **params,
            ).data()
            relationship_rows = session.run(
                f"""
                MATCH (:KGNode)-[r]->(:KGNode)
                {rel_filter}
                RETURN type(r) AS relation, count(*) AS count
                ORDER BY count DESC, relation
                """,
                **params,
            ).data()
            sample_publications = session.run(
                f"""
                MATCH (p:KGNode:Publication)
                {publication_filter}
                RETURN p.id AS id, p.title AS title, p.tldr AS tldr, p.keywords AS keywords
                LIMIT 5
                """,
                **params,
            ).data()
        return {
            "database": database,
            "graph_name": graph_name or "",
            "nodes": node_count,
            "relationships": rel_count,
            "label_counts": label_rows,
            "relationship_counts": relationship_rows,
            "sample_publications": sample_publications,
        }
    finally:
        driver.close()
