"""Neo4j storage adapter backed by the existing core graph adapter."""

from __future__ import annotations

from typing import Any

from yunesa.knowledge.graphs.adapters.core import CoreGraphAdapter

from ..base import BaseGraphStorage


class Neo4jGraphStorage(BaseGraphStorage):
    """Expose the core Neo4j adapter through the GraphRAG storage contract."""

    def __init__(
        self,
        adapter: CoreGraphAdapter | None = None,
        *,
        graph_db_instance: Any = None,
        graph_name: str | None = None,
    ) -> None:
        self.graph_name = graph_name
        self.adapter = adapter or CoreGraphAdapter(
            graph_db_instance=graph_db_instance,
            config={"graph_name": graph_name} if graph_name else {},
        )

    async def query_nodes(
        self,
        keyword: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self.adapter.query_nodes(
            keyword,
            graph_name=kwargs.pop("graph_name", None) or self.graph_name,
            **kwargs,
        )

    async def get_shortest_path(
        self,
        node_ids: list[str],
        max_hops: int = 3,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self.adapter.get_shortest_path(
            node_ids,
            max_hops=max_hops,
            graph_name=kwargs.pop("graph_name", None) or self.graph_name,
            **kwargs,
        )
