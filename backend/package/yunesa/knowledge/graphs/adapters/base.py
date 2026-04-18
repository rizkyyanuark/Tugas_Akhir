import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase as GD

from yunesa.utils import logger


@dataclass
class GraphQueryConfig:
    """graphqueryconfigure (Graph Query Configuration)"""

    keyword: str = ""
    kb_id: str | None = None
    kgdb_name: str | None = None
    max_nodes: int = 50
    max_depth: int = 2
    hops: int = 2
    threshold: float = 0.9
    filters: dict = None
    context: dict = None

    def __post_init__(self):
        if self.filters is None:
            self.filters = {}
        if self.context is None:
            self.context = {}


@dataclass
class GraphMetadata:
    """Graph metadata."""

    graph_type: str
    id_field: str = "id"
    name_field: str = "name"
    supports_embedding: bool = False
    supports_threshold: bool = False


class GraphAdapter(ABC):
    """Base graph adapter."""

    def __init__(self, config: dict[str, Any] = None):
        self.config = config or {}
        self.metadata = self._get_metadata()

    @abstractmethod
    def _get_metadata(self) -> GraphMetadata:
        """Get graph metadata."""
        pass

    @abstractmethod
    async def query_nodes(self, keyword: str, **kwargs) -> dict[str, Any]:
        """querynode (Query nodes)"""
        pass

    @abstractmethod
    def normalize_node(self, raw_node: Any) -> dict[str, Any]:
        """Normalize node format."""
        pass

    @abstractmethod
    def normalize_edge(self, raw_edge: Any) -> dict[str, Any]:
        """Normalize edge format."""
        pass

    @abstractmethod
    async def get_labels(self) -> list[str]:
        """Get all labels."""
        pass

    async def get_stats(self, **kwargs) -> dict[str, Any]:
        """Get statistics."""
        return {}

    def _create_query_config(self, **kwargs) -> GraphQueryConfig:
        """Create query configuration."""
        # Prefer adapter defaults first.
        config_dict = self.config.copy()
        config_dict.update(kwargs)

        return GraphQueryConfig(
            keyword=config_dict.get("keyword", ""),
            kb_id=config_dict.get("kb_id") or self.config.get("kb_id"),
            kgdb_name=config_dict.get(
                "kgdb_name") or self.config.get("kgdb_name", "neo4j"),
            max_nodes=config_dict.get(
                "max_nodes", config_dict.get("limit", 50)),
            max_depth=config_dict.get("max_depth", 2),
            hops=config_dict.get("hops", 2),
            threshold=config_dict.get("threshold", 0.9),
            filters=config_dict.get("filters", {}),
            context=config_dict.get("context", {}),
        )

    def _create_standard_node(
        self,
        node_id: str,
        name: str,
        entity_type: str,
        labels: list[str],
        properties: dict[str, Any],
        source: str,
    ) -> dict[str, Any]:
        """
        Helper to create a standardized node dictionary.
        """
        return {
            "id": node_id,
            "name": name,
            "original_id": node_id,
            "type": entity_type,
            "labels": labels,
            "properties": properties,
            "normalized": {
                "name": name,
                "type": entity_type,
                "source": source,
            },
            "graph_type": source,
        }

    def _create_standard_edge(
        self,
        edge_id: str,
        source_id: str,
        target_id: str,
        edge_type: str,
        properties: dict[str, Any],
        direction: str = "directed",
    ) -> dict[str, Any]:
        """
        Helper to create a standardized edge dictionary.
        """
        return {
            "id": edge_id,
            "source_id": source_id,
            "target_id": target_id,
            "type": edge_type,
            "properties": properties,
            "normalized": {
                "type": edge_type,
                "direction": direction,
            },
        }


class Neo4jConnectionManager:
    """
    Neo4j connection manager.
    Focuses on database connection management without business logic.
    """

    def __init__(self):
        self.driver = None
        self.status = "closed"
        if os.environ.get("LITE_MODE", "").lower() in ("true", "1"):
            logger.info("LITE_MODE enabled, skipping Neo4j connection")
            return
        self._connect()

    def _connect(self):
        """Establish Neo4j connection."""
        if self.driver and self._is_connected():
            return

        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        username = os.environ.get("NEO4J_USERNAME", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "0123456789")

        try:
            self.driver = GD.driver(uri, auth=(username, password))
            # Test connection
            with self.driver.session() as session:
                session.run("RETURN 1")
            self.status = "open"
            logger.info("Successfully connected to Neo4j")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise

    def _is_connected(self) -> bool:
        """Check whether connection is valid."""
        if not self.driver:
            return False
        try:
            with self.driver.session() as session:
                session.run("RETURN 1")
            return True
        except Exception:
            return False

    def is_running(self):
        """Check if graph database is running"""
        return self.status == "open" or self.status == "processing"

    def close(self):
        """Close database connection"""
        if self.driver:
            self.driver.close()
            self.driver = None
            self.status = "closed"


class BaseNeo4jAdapter:
    """
    Common Neo4j operations class that provides basic database connection and query methods.
    Focuses on graph management itself and is decoupled from upload logic.
    """

    def __init__(self):
        self.connection = Neo4jConnectionManager()

    @property
    def driver(self):
        """Get database driver (backward compatible)."""
        return self.connection.driver

    def _is_connected(self) -> bool:
        """Check whether connection is valid."""
        return self.connection._is_connected()

    def _process_record_props(self, record: dict) -> dict:
        """
        Process record properties: flatten `properties` and remove embedding.
        """
        if record is None:
            return None

        # Copy to avoid modifying the original dictionary.
        data = dict(record)
        props = data.pop("properties", {}) or {}

        # Remove embedding to reduce transfer bandwidth.
        if "embedding" in props:
            del props["embedding"]

        # Merge properties (prioritize core fields in original dict such as id, name, and type).
        return {**props, **data}

    def _get_sample_nodes_with_connections(self, num: int = 50, label_filter: str = None) -> dict[str, list]:
        """
        Get a connected node subgraph, prioritizing connected nodes in return results.
        Args:
            num: Number of nodes to return.
            label_filter: Node label filter (e.g. "kb_123").
        """
        if not self._is_connected():
            raise Exception("Neo4j connection is not available")

        label_clause = f":{label_filter}" if label_filter else ""

        def query(tx, num):
            # Connected subgraph query
            query_str = f"""
                // Get high-degree nodes as seed nodes
                MATCH (seed{label_clause})
                WITH seed, COUNT{{(seed)-[]->()}} + COUNT{{(seed)<-[]-()}} as degree
                WHERE degree > 0
                ORDER BY degree DESC
                LIMIT 5

                // Collect more neighbor nodes for each seed node
                UNWIND seed as s
                MATCH (s)-[*1..1]-(neighbor{label_clause})
                WITH s, neighbor, COUNT{{(s)-[]->()}} + COUNT{{(s)<-[]-()}} as s_degree
                WITH s, s_degree, collect(DISTINCT neighbor) as neighbors
                WITH s, s_degree, neighbors[0..toInteger($num * 0.15)] as limited_neighbors

                // Extend from neighbor nodes to second-hop nodes
                UNWIND limited_neighbors as neighbor
                OPTIONAL MATCH (neighbor)-[*1..1]-(second_hop{label_clause})
                WHERE second_hop <> s
                WITH s, limited_neighbors, neighbor, collect(DISTINCT second_hop)[0..5] as second_hops

                // Collect all connected nodes
                WITH collect(DISTINCT s) as seeds,
                    collect(DISTINCT neighbor) as first_hop_nodes,
                    reduce(acc = [], x IN collect(second_hops) | acc + x) as second_hop_nodes
                WITH seeds + first_hop_nodes + second_hop_nodes as connected_nodes

                // Ensure node count does not exceed requested size
                WITH connected_nodes[0..$num] as final_nodes

                // Get relationships among these nodes and avoid duplicate bidirectional edges
                UNWIND final_nodes as n
                OPTIONAL MATCH (n)-[rel]-(m)
                WHERE m IN final_nodes AND elementId(n) < elementId(m)
                RETURN
                    {{id: elementId(n), name: n.name, properties: properties(n)}} AS h,
                    CASE WHEN rel IS NOT NULL THEN
                        {{
                            id: elementId(rel),
                            type: rel.type,
                            source_id: elementId(startNode(rel)),
                            target_id: elementId(endNode(rel)),
                            properties: properties(rel)
                        }}
                    ELSE null END AS r,
                    CASE WHEN m IS NOT NULL THEN
                        {{id: elementId(m), name: m.name, properties: properties(m)}}
                    ELSE null END AS t
            """

            try:
                results = tx.run(query_str, num=int(num))
                formatted_results = {"nodes": [], "edges": []}
                node_ids = set()

                for item in results:
                    h_node = self._process_record_props(item["h"])
                    if h_node and h_node["id"] not in node_ids:
                        formatted_results["nodes"].append(h_node)
                        node_ids.add(h_node["id"])

                    if item["r"] is not None and item["t"] is not None:
                        t_node = self._process_record_props(item["t"])
                        r_edge = self._process_record_props(item["r"])

                        if t_node and t_node["id"] not in node_ids:
                            formatted_results["nodes"].append(t_node)
                            node_ids.add(t_node["id"])

                        if r_edge:
                            formatted_results["edges"].append(r_edge)

                # If node count is insufficient, supplement with more nodes.
                if len(formatted_results["nodes"]) < num:
                    remaining_count = num - len(formatted_results["nodes"])
                    supplement_query = f"""
                    MATCH (n{label_clause})
                    WHERE NOT elementId(n) IN $existing_ids
                    RETURN {{id: elementId(n), name: n.name, properties: properties(n)}} AS node
                    LIMIT $count
                    """
                    supplement_results = tx.run(
                        supplement_query, existing_ids=list(node_ids), count=remaining_count)
                    for item in supplement_results:
                        node = self._process_record_props(item["node"])
                        if node:
                            formatted_results["nodes"].append(node)

                return formatted_results

            except Exception as e:
                logger.warning(
                    f"Connected subgraph query failed, using fallback: {e}")
                # Simple fallback query
                fallback_query = f"""
                MATCH (n{label_clause})-[r]-(m{label_clause})
                WHERE elementId(n) < elementId(m)
                RETURN
                    {{id: elementId(n), name: n.name, properties: properties(n)}} AS h,
                    {{
                        id: elementId(r),
                        type: r.type,
                        source_id: elementId(startNode(r)),
                        target_id: elementId(endNode(r)),
                        properties: properties(r)
                    }} AS r,
                    {{id: elementId(m), name: m.name, properties: properties(m)}} AS t
                LIMIT $num
                """
                results = tx.run(fallback_query, num=int(num))
                formatted_results = {"nodes": [], "edges": []}
                node_ids = set()

                for item in results:
                    h_node = self._process_record_props(item["h"])
                    t_node = self._process_record_props(item["t"])
                    r_edge = self._process_record_props(item["r"])

                    if h_node and h_node["id"] not in node_ids:
                        formatted_results["nodes"].append(h_node)
                        node_ids.add(h_node["id"])
                    if t_node and t_node["id"] not in node_ids:
                        formatted_results["nodes"].append(t_node)
                        node_ids.add(t_node["id"])
                    if r_edge:
                        formatted_results["edges"].append(r_edge)

                return formatted_results

        with self.driver.session() as session:
            return session.execute_read(query, num)

    def _get_graph_stats(self, label_filter: str = None) -> dict[str, Any]:
        """
        Get graph statistics.
        Args:
            label_filter: Node label filter (e.g. "kb_123").
        """
        if not self._is_connected():
            return {"total_nodes": 0, "total_edges": 0, "entity_types": []}

        label_clause = f":{label_filter}" if label_filter else ""

        def query(tx):
            # Count nodes
            node_query = f"MATCH (n{label_clause}) RETURN count(n) as node_count"
            node_count = tx.run(node_query).single()["node_count"]

            # Count edges
            edge_query = f"MATCH (n{label_clause})-[r]-(m{label_clause}) RETURN count(r) as edge_count"
            edge_count = tx.run(edge_query).single()["edge_count"]

            # Label distribution stats (exclude system labels)
            label_dist_query = f"""
            MATCH (n{label_clause})
            UNWIND labels(n) as label
            WHERE label <> 'Entity' AND NOT label STARTS WITH 'kb_'
            WITH label, count(*) as count
            RETURN label, count
            ORDER BY count DESC
            """
            label_stats = tx.run(label_dist_query)
            entity_types = [{"type": record["label"],
                             "count": record["count"]} for record in label_stats]

            return {
                "total_nodes": node_count,
                "total_edges": edge_count,
                "entity_types": entity_types,
            }

        try:
            with self.driver.session() as session:
                return session.execute_read(query)
        except Exception as e:
            logger.error(f"Failed to get graph stats: {e}")
            return {"total_nodes": 0, "total_edges": 0, "entity_types": []}

    def _get_all_labels(self, exclude_system_labels: bool = True) -> list[str]:
        """
        Get all labels.
        Args:
            exclude_system_labels: Whether to exclude system labels (starting with kb_).
        """
        if not self._is_connected():
            return []

        def query(tx):
            result = tx.run(
                "CALL db.labels() YIELD label RETURN collect(label) AS labels")
            labels = result.single()["labels"]

            if exclude_system_labels:
                labels = [
                    label for label in labels if not label.startswith("kb_")]

            return labels

        try:
            with self.driver.session() as session:
                return session.execute_read(query)
        except Exception as e:
            logger.error(f"Failed to get labels: {e}")
            return []

    def close(self):
        """Close database connection"""
        self.connection.close()
