from typing import TYPE_CHECKING, Any

from yunesa.knowledge.graphs.adapters.base import BaseNeo4jAdapter

from .base import GraphAdapter, GraphMetadata

if TYPE_CHECKING:
    pass


class UploadGraphAdapter(GraphAdapter):
    """Uploadgraphadapter (Upload Graph Adapter)"""

    def __init__(self, graph_db_instance=None, config: dict[str, Any] = None):
        super().__init__(config)

        # Delayed import to avoid circular imports.
        from yunesa.knowledge.graphs.upload_graph_service import UploadGraphService

        # Initialize business-logic service.
        if graph_db_instance and hasattr(graph_db_instance, "_service"):
            # If a wrapped GraphDatabase instance is passed in.
            self.service = graph_db_instance._service
        else:
            self.service = graph_db_instance if graph_db_instance else UploadGraphService()
            if not self.service.is_running():
                self.service.start()

        # Initialize query adapter (pure query operations).
        self._db = BaseNeo4jAdapter()

    def _get_metadata(self) -> GraphMetadata:
        """Get Upload graph metadata."""
        return GraphMetadata(
            graph_type="upload",
            id_field="id",
            name_field="name",
            supports_embedding=True,
            supports_threshold=True,
        )

    async def query_nodes(self, keyword: str, **kwargs) -> dict[str, Any]:
        params = self._normalize_query_params(keyword, kwargs)

        # If keyword is "*" or empty, run sampling query.
        if not params["keyword"] or params["keyword"] == "*":
            # Use BaseNeo4jAdapter connected subgraph query.
            num = kwargs.get("max_nodes", 100)
            raw_results = self._db._get_sample_nodes_with_connections(
                num=num,
                label_filter="Upload",
            )
        else:
            # Otherwise execute keyword search via service query method.
            raw_results = self.service.query_node(
                keyword=params["keyword"],
                threshold=params.get("threshold", 0.9),
                kgdb_name=params.get("kgdb_name", "neo4j"),
                hops=params.get("hops", 2),
                return_format="graph",
            )

        return self._format_results(raw_results)

    def normalize_node(self, raw_node: Any) -> dict[str, Any]:
        """
        raw_node expected format: {id: str, name: str, ...}
        """
        node_id = raw_node.get("id")
        name = raw_node.get("name")

        return self._create_standard_node(
            node_id=node_id,
            name=name,
            entity_type="entity",
            labels=["Entity", "Upload"],
            properties=raw_node,
            source="upload",
        )

    def normalize_edge(self, raw_edge: Any) -> dict[str, Any]:
        """
        raw_edge expected format: {type: str, source_id: str, target_id: str, ...}
        """
        # Generate an ID if not present (Upload graph edges might not have explicit ID in simple dict return)
        edge_id = raw_edge.get("id")
        if not edge_id:
            edge_id = f"{raw_edge.get('source_id')}_{raw_edge.get('type')}_{raw_edge.get('target_id')}"

        return self._create_standard_edge(
            edge_id=edge_id,
            source_id=raw_edge.get("source_id"),
            target_id=raw_edge.get("target_id"),
            edge_type=raw_edge.get("type"),
            properties=raw_edge,
        )

    async def get_labels(self) -> list[str]:
        """Get all labels using UploadGraphService."""
        kgdb_name = self.config.get("kgdb_name", "neo4j")
        info = self.service.get_graph_info(graph_name=kgdb_name)
        return info.get("labels", []) if info else []

    def _normalize_query_params(self, keyword: str, kwargs: dict) -> dict[str, Any]:
        # Map max_depth to hops if present
        hops = kwargs.get("hops")
        if hops is None:
            hops = kwargs.get("max_depth", 2)

        return {
            "keyword": keyword,
            "threshold": kwargs.get("threshold", 0.9),
            "kgdb_name": kwargs.get("kgdb_name", "neo4j"),
            "hops": hops,
            "filters": kwargs.get("filters", {}),
            "context": kwargs.get("context", {}),
        }

    def _format_results(self, raw_results: dict[str, list]) -> dict[str, list]:
        nodes = [self.normalize_node(n) for n in raw_results.get("nodes", [])]
        edges = [self.normalize_edge(e) for e in raw_results.get("edges", [])]
        return {"nodes": nodes, "edges": edges}
