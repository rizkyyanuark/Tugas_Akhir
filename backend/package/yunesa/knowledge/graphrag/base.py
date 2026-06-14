"""Storage contracts used by the Academic GraphRAG orchestrator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseGraphStorage(ABC):
    """Async graph retrieval contract."""

    @abstractmethod
    async def query_nodes(
        self,
        keyword: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Retrieve a bounded graph neighborhood."""

    @abstractmethod
    async def get_shortest_path(
        self,
        node_ids: list[str],
        max_hops: int = 3,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Retrieve shortest paths connecting canonical graph node IDs."""


class BaseVectorStorage(ABC):
    """Async vector retrieval contract."""

    @abstractmethod
    async def query(
        self,
        query_text: str,
        *,
        collection_name: str,
        output_fields: list[str],
        text_fields: list[str],
        top_k: int,
        graph_name: str,
        query_vector: list[float] | None = None,
        embed_if_missing: bool = True,
    ) -> list[dict[str, Any]]:
        """Query one vector collection."""


class BaseKVStorage(ABC):
    """Minimal key-value metadata contract for source records."""

    @abstractmethod
    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        """Return source records matching the supplied IDs."""
