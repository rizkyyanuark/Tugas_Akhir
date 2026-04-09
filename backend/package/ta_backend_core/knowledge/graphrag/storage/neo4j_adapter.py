"""
Neo4j Adapter: GraphStorage Interface for GraphRAG
====================================================
Provides graph traversal methods for the retrieval pipeline:
  - Node/edge lookup by ID
  - BFS shortest-path subgraph extraction (pure Python, no APOC)
  - Node/edge degree queries
"""

import logging
from collections import deque
from typing import Dict, List, Optional, Set, Tuple, Any

from neo4j import GraphDatabase

from ..config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE, BFS_MAX_DEPTH

logger = logging.getLogger(__name__)


class Neo4jGraphStorage:
    """Read-only Neo4j adapter for GraphRAG retrieval."""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        self.uri = uri or NEO4J_URI
        self.user = user or NEO4J_USER
        self.password = password or NEO4J_PASSWORD
        self.database = database or NEO4J_DATABASE
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self.driver.verify_connectivity()
        logger.info(f"✅ Neo4jGraphStorage connected to {self.uri}")

    def close(self):
        if self.driver:
            self.driver.close()

    def _session(self):
        return self.driver.session(database=self.database)

    # ── Node Operations ──

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get a single node by node_id."""
        with self._session() as s:
            result = s.run(
                "MATCH (n {node_id: $nid}) RETURN n, labels(n) AS labels",
                nid=node_id,
            ).single()
            if result:
                props = dict(result["n"])
                props["_labels"] = result["labels"]
                return props
        return None

    def get_node_edges(self, node_id: str) -> List[Dict[str, Any]]:
        """Get all edges connected to a node (both directions)."""
        with self._session() as s:
            records = s.run(
                """
                MATCH (n {node_id: $nid})-[r]-(m)
                RETURN type(r) AS rel_type, r AS rel,
                       n.node_id AS src, m.node_id AS tgt,
                       labels(m)[0] AS tgt_label, m.name AS tgt_name
                """,
                nid=node_id,
            ).data()
        return records

    def node_degree(self, node_id: str) -> int:
        """Get the degree (number of connections) of a node."""
        with self._session() as s:
            result = s.run(
                "MATCH (n {node_id: $nid})-[r]-() RETURN count(r) AS deg",
                nid=node_id,
            ).single()
            return result["deg"] if result else 0

    # ── Edge Operations ──

    def get_edge(self, src_id: str, tgt_id: str, rel_type: Optional[str] = None) -> Optional[Dict]:
        """Get an edge between two nodes."""
        if rel_type:
            query = f"MATCH (a {{node_id: $s}})-[r:{rel_type}]->(b {{node_id: $t}}) RETURN r, type(r) AS rtype"
        else:
            query = "MATCH (a {node_id: $s})-[r]->(b {node_id: $t}) RETURN r, type(r) AS rtype"
        with self._session() as s:
            result = s.run(query, s=src_id, t=tgt_id).single()
            if result:
                props = dict(result["r"])
                props["_type"] = result["rtype"]
                return props
        return None

    def edge_degree(self, src_id: str, tgt_id: str) -> int:
        """Get the combined degree of both endpoints of an edge."""
        return self.node_degree(src_id) + self.node_degree(tgt_id)

    # ── BFS Subgraph Extraction (No APOC) ──

    def get_smallest_subgraph(
        self,
        seed_node_ids: List[str],
        max_depth: int = BFS_MAX_DEPTH,
    ) -> Tuple[List[Dict], List[Dict]]:
        """Extract the smallest connected subgraph containing all seed nodes.

        Uses BFS from each seed node, then finds shortest paths between pairs.
        Falls back to individual neighborhoods if no connecting paths exist.

        Args:
            seed_node_ids: List of node_ids to connect.
            max_depth: Maximum BFS depth per seed.

        Returns:
            Tuple of (subgraph_nodes, subgraph_edges).
        """
        if not seed_node_ids:
            return [], []

        all_nodes: Dict[str, Dict] = {}
        all_edges: List[Dict] = []
        seen_edges: Set[str] = set()

        # For each pair of seed nodes, find shortest path via BFS
        for i, src in enumerate(seed_node_ids):
            for tgt in seed_node_ids[i + 1:]:
                path_nodes, path_edges = self._bfs_shortest_path(src, tgt, max_depth)
                for n in path_nodes:
                    all_nodes[n["node_id"]] = n
                for e in path_edges:
                    edge_key = f"{e.get('src', '')}-{e.get('rel_type', '')}-{e.get('tgt', '')}"
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        all_edges.append(e)

        # If no paths found, fallback to 1-hop neighborhoods
        if not all_nodes:
            for nid in seed_node_ids:
                node = self.get_node(nid)
                if node:
                    all_nodes[nid] = node
                    for edge in self.get_node_edges(nid):
                        tgt_node = self.get_node(edge["tgt"])
                        if tgt_node:
                            all_nodes[edge["tgt"]] = tgt_node
                        edge_key = f"{edge['src']}-{edge['rel_type']}-{edge['tgt']}"
                        if edge_key not in seen_edges:
                            seen_edges.add(edge_key)
                            all_edges.append(edge)

        return list(all_nodes.values()), all_edges

    def _bfs_shortest_path(
        self, src_id: str, tgt_id: str, max_depth: int
    ) -> Tuple[List[Dict], List[Dict]]:
        """BFS shortest path between two nodes (pure Python, no APOC)."""
        with self._session() as s:
            # Use Cypher shortestPath with variable-length pattern
            result = s.run(
                f"""
                MATCH p = shortestPath(
                    (a {{node_id: $src}})-[*..{max_depth}]-(b {{node_id: $tgt}})
                )
                UNWIND nodes(p) AS n
                UNWIND relationships(p) AS r
                RETURN
                    collect(DISTINCT {{
                        node_id: n.node_id, name: n.name,
                        labels: labels(n), source_id: n.source_id
                    }}) AS path_nodes,
                    collect(DISTINCT {{
                        src: startNode(r).node_id, tgt: endNode(r).node_id,
                        rel_type: type(r), description: r.description
                    }}) AS path_edges
                """,
                src=src_id,
                tgt=tgt_id,
            ).single()

            if result:
                return result["path_nodes"] or [], result["path_edges"] or []
        return [], []

    def get_nodes_by_degree(self, node_ids: List[str], top_k: int = 10) -> List[Dict]:
        """Rank nodes by degree and return top-k."""
        with self._session() as s:
            result = s.run(
                """
                UNWIND $nids AS nid
                MATCH (n {node_id: nid})
                OPTIONAL MATCH (n)-[r]-()
                WITH n, count(r) AS deg
                ORDER BY deg DESC
                LIMIT $k
                RETURN n.node_id AS node_id, n.name AS name,
                       labels(n)[0] AS label, deg AS degree,
                       n.source_id AS source_id
                """,
                nids=node_ids,
                k=top_k,
            ).data()
        return result
