"""
Neo4j Writer: Idempotent Graph Database Ingestion
===================================================
Handles all Neo4j write operations for the KG pipeline:
  - Uniqueness constraint creation
  - MERGE-based node upserts
  - MERGE-based edge upserts
  - Statistics queries

Fully idempotent: re-running produces zero duplicates.
"""

import time
import logging
from typing import Dict, List, Tuple, Optional, Any

from neo4j import GraphDatabase

from .config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE
from .ontology import get_all_labels

logger = logging.getLogger(__name__)


class Neo4jKGWriter:
    """Production-grade Neo4j writer for the KG pipeline.

    Uses MERGE (never CREATE) for complete idempotency.
    Connects to the 'Infokom_unesa' database by default.

    Usage:
        writer = Neo4jKGWriter()
        writer.ensure_constraints()
        writer.ingest_nodes(nodes)
        writer.ingest_edges(edges, nodes)
        stats = writer.get_stats()
        writer.close()
    """

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

        try:
            self.driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            self.driver.verify_connectivity()
            logger.info(f"✅ Neo4jKGWriter connected to {self.uri} (db={self.database})")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Neo4j at {self.uri}: {e}")
            raise

    def close(self):
        """Cleanly close the driver."""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j driver closed.")

    def _session(self):
        """Create a session targeting the configured database."""
        return self.driver.session(database=self.database)

    def clear_database(self):
        """Delete all nodes and relationships. USE WITH CAUTION.

        Only for development/testing. In production, use incremental MERGE.
        """
        with self._session() as s:
            s.run("MATCH (n) DETACH DELETE n")
            logger.info("  Neo4j: all existing data deleted")

    def ensure_constraints(self):
        """Create uniqueness constraints for all node types in the ontology.

        Idempotent: uses IF NOT EXISTS.
        """
        labels = get_all_labels()
        with self._session() as s:
            for lbl in labels:
                s.run(
                    f"CREATE CONSTRAINT IF NOT EXISTS "
                    f"FOR (n:{lbl}) REQUIRE n.node_id IS UNIQUE"
                )
        logger.info(f"  Neo4j: {len(labels)} uniqueness constraints ensured")

    def ingest_nodes(self, nodes: Dict[str, Dict]) -> Dict[str, int]:
        """Ingest nodes using MERGE (idempotent upsert).

        Each node dict must have '_label' key. All other keys become properties.
        The dict key becomes 'node_id'.

        Args:
            nodes: Dict of {node_id: {_label, ...properties}}.

        Returns:
            Stats dict with counts by label and errors.
        """
        logger.info(f"Ingesting {len(nodes)} nodes to Neo4j...")
        errors = 0
        label_counts: Dict[str, int] = {}
        t0 = time.time()

        with self._session() as s:
            for nid, d in nodes.items():
                try:
                    lbl = d["_label"]
                    props = {
                        k: str(v)
                        for k, v in d.items()
                        if k != "_label" and v and str(v) != "nan"
                    }
                    props["node_id"] = nid
                    set_clause = ", ".join(
                        [f"n.`{k}` = ${k}" for k in props]
                    )
                    s.run(
                        f"MERGE (n:{lbl} {{node_id: $node_id}}) SET {set_clause}",
                        **props,
                    )
                    label_counts[lbl] = label_counts.get(lbl, 0) + 1
                except Exception as e:
                    errors += 1
                    logger.error(
                        f"Node insert error [{nid}]: {type(e).__name__}: {e}"
                    )

        elapsed = time.time() - t0
        logger.info(f"  Neo4j nodes ingested in {elapsed:.1f}s (errors: {errors})")
        return {"label_counts": label_counts, "errors": errors}

    def ingest_edges(
        self,
        edges: List[Tuple[str, str, str, Dict]],
        nodes: Dict[str, Dict],
    ) -> Dict[str, int]:
        """Ingest edges using MERGE (idempotent upsert).

        Skips edges where source or target node doesn't exist in `nodes`.

        Args:
            edges: List of (src_id, tgt_id, rel_type, props).
            nodes: Nodes dict for existence validation.

        Returns:
            Stats dict with counts and errors.
        """
        logger.info(f"Ingesting {len(edges)} edges to Neo4j...")
        errors, skipped = 0, 0
        rel_counts: Dict[str, int] = {}
        t0 = time.time()

        with self._session() as s:
            for src, tgt, rel, props in edges:
                if src not in nodes or tgt not in nodes:
                    skipped += 1
                    continue
                try:
                    # Build SET clause for edge properties
                    prop_clause = ""
                    if props:
                        sp = [
                            f'r.`{k}` = "{v}"'
                            for k, v in props.items()
                            if v
                        ]
                        if sp:
                            prop_clause = " SET " + ", ".join(sp)

                    s.run(
                        f"MATCH (a {{node_id: $s}}) "
                        f"MATCH (b {{node_id: $t}}) "
                        f"MERGE (a)-[r:{rel}]->(b){prop_clause}",
                        s=src,
                        t=tgt,
                    )
                    rel_counts[rel] = rel_counts.get(rel, 0) + 1
                except Exception as e:
                    errors += 1
                    logger.error(
                        f"Edge insert error [{src}]-[{rel}]→[{tgt}]: "
                        f"{type(e).__name__}: {e}"
                    )

        elapsed = time.time() - t0
        logger.info(
            f"  Neo4j edges ingested in {elapsed:.1f}s "
            f"(errors: {errors}, skipped: {skipped})"
        )
        return {"rel_counts": rel_counts, "errors": errors, "skipped": skipped}

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics: node count, edge count, distributions.

        Returns:
            Dict with node_count, edge_count, label_distribution, rel_distribution.
        """
        with self._session() as s:
            nc = s.run("MATCH (n) RETURN count(n) as c").single()["c"]
            ec = s.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
            lc = s.run(
                "MATCH (n) RETURN labels(n)[0] as label, count(n) as cnt "
                "ORDER BY cnt DESC"
            ).data()
            rc = s.run(
                "MATCH ()-[r]->() RETURN type(r) as relType, count(r) as cnt "
                "ORDER BY cnt DESC"
            ).data()

        return {
            "node_count": nc,
            "edge_count": ec,
            "label_distribution": {r["label"]: r["cnt"] for r in lc},
            "rel_distribution": {r["relType"]: r["cnt"] for r in rc},
        }

    def derive_collaborations(self) -> int:
        """Derive COLLABORATES_WITH edges from co-authorship patterns.

        For every pair of Dosen who co-author at least one Paper,
        creates/updates a COLLABORATES_WITH edge with paper list and count.

        Returns:
            Number of collaboration edges created/updated.
        """
        cypher = """
        MATCH (a:Dosen)-[:WRITES]->(p:Paper)<-[:WRITES]-(b:Dosen)
        WHERE elementId(a) < elementId(b)
        WITH a, b, COLLECT(DISTINCT p.node_id) AS paper_ids
        MERGE (a)-[r:COLLABORATES_WITH]->(b)
        SET r.papers = paper_ids,
            r.count = SIZE(paper_ids),
            r.updated_at = toString(datetime())
        RETURN COUNT(r) AS total
        """
        with self._session() as s:
            result = s.run(cypher).single()
            total = result["total"] if result else 0
            logger.info(f"  COLLABORATES_WITH edges derived: {total}")
            return total

    def run_query(self, cypher: str, **params) -> list:
        """Execute an arbitrary Cypher query and return results as list of dicts.

        Useful for exploration notebooks and analytics endpoints.

        Args:
            cypher: Cypher query string.
            **params: Query parameters.

        Returns:
            List of result dicts.
        """
        with self._session() as s:
            return s.run(cypher, **params).data()

    def print_summary(self):
        """Print a formatted summary of the database contents."""
        stats = self.get_stats()
        sep = "=" * 60

        logger.info(f"\n{sep}")
        logger.info("KG CONSTRUCTION PIPELINE COMPLETE!")
        logger.info(sep)
        logger.info(f"Neo4j: {stats['node_count']} nodes, {stats['edge_count']} edges")

        logger.info("--- Node Distribution ---")
        for label, cnt in stats["label_distribution"].items():
            logger.info(f"  {label:20s}: {cnt}")

        logger.info("--- Edge Distribution ---")
        for rel, cnt in stats["rel_distribution"].items():
            logger.info(f"  {rel:20s}: {cnt}")
