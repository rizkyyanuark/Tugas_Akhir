from .base import GraphAdapter
from .core import CoreGraphAdapter
from .lightrag import LightRAGGraphAdapter


class GraphAdapterFactory:
    """Graph adapter factory (Graph Adapter Factory)"""

    _registry: dict[str, type[GraphAdapter]] = {
        "core": CoreGraphAdapter,
        "lightrag": LightRAGGraphAdapter,
    }

    @classmethod
    def register(cls, graph_type: str, adapter_class: type[GraphAdapter]):
        """Register adapter class."""
        cls._registry[graph_type] = adapter_class

    @classmethod
    def create_adapter(cls, graph_type: str, **kwargs) -> GraphAdapter:
        """Create adapter instance."""
        adapter_class = cls._registry.get(graph_type)
        if not adapter_class:
            raise ValueError(f"Unknown graph type: {graph_type}")

        return adapter_class(**kwargs)

    @classmethod
    def get_supported_types(cls) -> dict[str, str]:
        """Get supported graph types and their descriptions."""
        return {
            "core": "Core graph - direct Neo4j access for structured data visualization",
            "lightrag": "LightRAG knowledge graph - graph based on kb_id labels",
        }

    @classmethod
    async def detect_graph_type(cls, db_id: str, knowledge_base_manager=None) -> str:
        """
        Automatically detect graph type.

        Args:
            db_id: Database ID.
            knowledge_base_manager: Knowledge base manager instance.

        Returns:
            Graph type: "lightrag" (LightRAG) or "core".
        """
        # 1. First check whether this is a LightRAG database (via knowledge base manager)
        if knowledge_base_manager:
            db_info = await knowledge_base_manager.get_database_info(db_id)
            if db_info and db_info.get("kb_type") == "lightrag":  # Existing metadata indicates LightRAG database
                return "lightrag"

        # 2. Fallback check: kb_ prefix
        if db_id.startswith("kb_"):
            return "lightrag"

        # 3. Default to Core type
        return "core"

    @classmethod
    async def create_adapter_by_db_id(
        cls, db_id: str, knowledge_base_manager=None, graph_db_instance=None
    ) -> GraphAdapter:
        """
        Automatically create the corresponding adapter from database ID.

        Args:
            db_id: Database ID.
            knowledge_base_manager: Knowledge base manager instance.
            graph_db_instance: Graph database instance (for Core type).

        Returns:
            Corresponding graph adapter.
        """
        graph_type = await cls.detect_graph_type(db_id, knowledge_base_manager)

        if graph_type == "lightrag":
            # LightRAG type, use kb_id as config
            return cls.create_adapter("lightrag", config={"kb_id": db_id})
        else:
            # Core type, use kgdb_name as config
            return cls.create_adapter("core", graph_db_instance=graph_db_instance, config={"kgdb_name": db_id})

    @classmethod
    async def create_adapter_for_db_id(
        cls, db_id: str, knowledge_base_manager=None, graph_db_instance=None
    ) -> GraphAdapter:
        """
        Compatibility method that calls create_adapter_by_db_id.
        """
        return await cls.create_adapter_by_db_id(db_id, knowledge_base_manager, graph_db_instance)
