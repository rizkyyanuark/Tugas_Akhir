from typing import Any

from yunesa.utils import logger

from .base import BaseNeo4jAdapter, GraphAdapter, GraphMetadata


class LightRAGGraphAdapter(GraphAdapter):
    """LightRAG graphadapter (LightRAG Graph Adapter)"""

    def __init__(self, config: dict[str, Any] = None):
        super().__init__(config)

        # Use shared Neo4j adapter instead of GraphDatabase wrapper.
        self._db = BaseNeo4jAdapter()

        # Read kb_id from configuration.
        self.kb_id = self.config.get("kb_id")

    def _get_metadata(self) -> GraphMetadata:
        """Get LightRAG graph metadata."""
        return GraphMetadata(
            graph_type="lightrag",
            id_field="element_id",
            name_field="entity_id",  # LightRAG stores entity name in entity_id
            supports_embedding=False,
            supports_threshold=False,
        )

    async def query_nodes(self, keyword: str, **kwargs) -> dict[str, Any]:
        """querynode (Query nodes)"""
        kb_id = kwargs.get("kb_id") or self.kb_id
        limit = kwargs.get("max_nodes", kwargs.get("limit", 50))
        max_depth = kwargs.get("max_depth", 1)  # Default to 1 to return edges

        # If keyword is *, enforce max_depth >= 1.
        if keyword == "*":
            max_depth = max(max_depth, 1)

        query = self._build_cypher_query(keyword, kb_id, limit, max_depth)

        try:
            with self._db.driver.session() as session:
                result = session.run(query, keyword=keyword,
                                     kb_id=kb_id, limit=limit)
                return self._process_query_result(result, limit=limit)
        except Exception as e:
            logger.error(f"Neo4j query failed: {e}")
            return {"nodes": [], "edges": []}

    async def get_labels(self) -> list[str]:
        """Get all labels."""
        query = "CALL db.labels()"
        try:
            with self._db.driver.session() as session:
                result = session.run(query)
                return [record["label"] for record in result if not record["label"].startswith("kb_")]
        except Exception as e:
            logger.error(f"Failed to get labels: {e}")
            return []

    async def get_stats(self, **kwargs) -> dict[str, Any]:
        """Get statistics."""
        kb_id = kwargs.get("kb_id") or self.kb_id

        # Safety check
        if kb_id and not all(c.isalnum() or c == "_" for c in kb_id):
            logger.warning(f"Invalid kb_id format: {kb_id}")
            return {"total_nodes": 0, "total_edges": 0, "entity_types": []}

        if not kb_id:
            # Without kb_id, return empty/global stats as applicable.
            return {"total_nodes": 0, "total_edges": 0, "entity_types": []}

        try:
            # Count nodes and edges
            query = f"""
            MATCH (n:`{kb_id}`)
            WITH count(n) as node_count
            OPTIONAL MATCH (n:`{kb_id}`)-[r]->(m:`{kb_id}`)
            RETURN node_count, count(r) as edge_count
            """

            # Label distribution statistics
            label_query = f"""
            MATCH (n:`{kb_id}`)
            UNWIND labels(n) as label
            WITH label, count(*) as count
            WHERE label <> 'Entity' AND NOT label STARTS WITH 'kb_'
            RETURN label, count
            ORDER BY count DESC
            """

            with self._db.driver.session() as session:
                stats = session.run(query).single()
                label_stats = session.run(label_query)

                entity_types_list = [
                    {"type": record["label"], "count": record["count"]} for record in label_stats]

                return {
                    "total_nodes": stats["node_count"],
                    "total_edges": stats["edge_count"],
                    "entity_types": entity_types_list,
                }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"total_nodes": 0, "total_edges": 0, "entity_types": []}

    def normalize_node(self, raw_node: Any) -> dict[str, Any]:
        """Normalize node format."""
        if hasattr(raw_node, "element_id"):  # neo4j.graph.Node
            node_id = raw_node.element_id
            labels = list(raw_node.labels)
            properties = dict(raw_node.items())
        elif isinstance(raw_node, dict):
            node_id = raw_node.get("id") or raw_node.get("element_id")
            labels = raw_node.get("labels", [])
            properties = raw_node.get("properties", {})
            if not properties:
                properties = {k: v for k, v in raw_node.items() if k not in [
                    "id", "element_id", "labels"]}
        else:
            return {}

        # Prefer entity_id as name (LightRAG style); fallback to name.
        # In many cases, entity_id stores the actual entity name.
        name = properties.get("entity_id", properties.get("name", "Unknown"))

        # Filter out labels starting with kb_.
        filtered_labels = [
            label for label in labels if not label.startswith("kb_")]

        # Extract entity type
        entity_type = "Entity"
        for label in filtered_labels:
            if label != "Entity":
                entity_type = label
                break

        return self._create_standard_node(
            node_id=node_id,
            name=name,
            entity_type=entity_type,
            labels=filtered_labels,
            properties=properties,
            source="neo4j",
        )

    def normalize_edge(self, raw_edge: Any) -> dict[str, Any]:
        """Normalize edge format."""
        logger.info(raw_edge._properties)
        if hasattr(raw_edge, "element_id"):  # neo4j.graph.Relationship
            edge_id = raw_edge.element_id
            edge_type = raw_edge._properties["keywords"] or raw_edge.type
            start_node_id = raw_edge.start_node.element_id if hasattr(
                raw_edge.start_node, "element_id") else None
            end_node_id = raw_edge.end_node.element_id if hasattr(
                raw_edge.end_node, "element_id") else None
            properties = dict(raw_edge.items())
        elif isinstance(raw_edge, dict):
            edge_id = raw_edge.get("id")
            edge_type = raw_edge.get("type")
            start_node_id = raw_edge.get("source_id")
            end_node_id = raw_edge.get("target_id")
            properties = raw_edge.get("properties", {})
        else:
            return {}

        return self._create_standard_edge(
            edge_id=edge_id, source_id=start_node_id, target_id=end_node_id, edge_type=edge_type, properties=properties
        )

    def _build_cypher_query(self, keyword: str, kb_id: str = None, limit: int = 50, max_depth: int = 0) -> str:
        """build Cypher query"""
        # Safety check: kb_id can only contain letters, numbers, and underscores.
        if kb_id:
            if not all(c.isalnum() or c == "_" for c in kb_id):
                logger.warning(f"Invalid kb_id: {kb_id}")
                kb_id = None

        where_clauses = []

        # Determine MATCH clause
        if kb_id:
            # If kb_id is provided, match that label directly.
            # This can match nodes even if they do not have the Entity label.
            match_clause = f"MATCH (n:`{kb_id}`)"
        else:
            match_clause = "MATCH (n:Entity)"

        if keyword and keyword != "*":
            # Support both LightRAG format (entity_id) and standard format (name)
            where_clauses.append(
                "(toLower(n.name) CONTAINS toLower($keyword) OR toLower(n.entity_id) CONTAINS toLower($keyword))"
            )

        where_str = " AND ".join(where_clauses)
        if where_str:
            where_str = "WHERE " + where_str

        # If max_depth > 0, extend query to subgraph retrieval.
        # To avoid overly complex queries, use a two-step strategy:
        # 1) Find seed nodes
        # 2) Retrieve their surrounding relationships

        # Step 1: Find seed nodes
        # If keyword is * and kb_id exists, random sampling could be used.
        # Here query_nodes is mainly for search use cases.

        if max_depth > 0:
            # Return subgraph when expansion is needed.
            query = f"""
            {match_clause}
            {where_str}
            WITH n LIMIT {limit}

            // Collect seed nodes
            WITH collect(n) as seeds

            // Expand 1 hop (if max_depth >= 1)
            UNWIND seeds as s
            OPTIONAL MATCH (s)-[r1]-(m1)
            // Ensure m1 is also in the same KB (if kb_id is specified)
            {f"WHERE m1:`{kb_id}`" if kb_id else ""}

            WITH seeds, collect(DISTINCT {{h: s, r: r1, t: m1}}) as hop1

            // Expand 2 hops (if max_depth >= 2)
            // For simplicity, only 1-hop expansion is done here; 2-hop can be added if needed.
            // Considering performance, 1-hop is usually sufficient.

            // Reshape return results
            UNWIND hop1 as triple
            RETURN triple.h as h, triple.r as r, triple.t as t
            LIMIT {limit * 10}
            """

            # Simplified expansion query: return seed nodes and directly connected edges
            # (including one-hop neighbors).

            query = f"""
            {match_clause}
            {where_str}
            WITH n LIMIT {limit}

            // Expansion query: get n and its neighbors
            OPTIONAL MATCH (n)-[r]-(m)
            {f"WHERE m:`{kb_id}`" if kb_id else ""}

            RETURN n, r, m
            """
        else:
            # Return nodes only
            query = f"""
            {match_clause}
            {where_str}
            RETURN n
            LIMIT {limit}
            """

        return query

    def _build_subgraph_query(self, limit: int, kb_id: str = None) -> str:
        """Build subgraph query."""
        # Safety check
        if kb_id:
            if not all(c.isalnum() or c == "_" for c in kb_id):
                kb_id = None

        if kb_id:
            match_clause = f"MATCH (n:`{kb_id}`)"
        else:
            match_clause = "MATCH (n:Entity)"

        query = f"""
        {match_clause}
        WITH n LIMIT {limit}
        WITH collect(n) as nodes
        UNWIND nodes as n
        UNWIND nodes as m
        OPTIONAL MATCH (n)-[r]-(m)
        WHERE elementId(n) < elementId(m)
        RETURN n, r, m
        """

        return query

    def _process_query_result(self, result, limit: int = None) -> dict[str, list]:
        """Process query result and keep node count within limit."""
        nodes = []
        edges = []
        node_ids = set()
        edge_ids = set()

        for record in result:
            # Check whether node limit is reached.
            if limit is not None and len(node_ids) >= limit:
                break

            for key in record.keys():
                val = record[key]
                if val is None:
                    continue

                if hasattr(val, "element_id") and hasattr(val, "labels"):  # Node
                    if val.element_id not in node_ids:
                        # Re-check limit before append.
                        if limit is not None and len(node_ids) >= limit:
                            break
                        nodes.append(self.normalize_node(val))
                        node_ids.add(val.element_id)
                elif hasattr(val, "element_id") and hasattr(val, "start_node"):  # Relationship
                    if val.element_id not in edge_ids:
                        edges.append(self.normalize_edge(val))
                        edge_ids.add(val.element_id)
                elif isinstance(val, list):
                    for item in val:
                        if hasattr(item, "element_id") and hasattr(item, "labels"):
                            if item.element_id not in node_ids:
                                if limit is not None and len(node_ids) >= limit:
                                    break
                                nodes.append(self.normalize_node(item))
                                node_ids.add(item.element_id)

        # Filter out edges whose endpoints do not exist in current node set.
        valid_edges = []
        for edge in edges:
            source_id = edge.get("source_id")
            target_id = edge.get("target_id")
            if source_id in node_ids and target_id in node_ids:
                valid_edges.append(edge)

        return {"nodes": nodes, "edges": valid_edges}
