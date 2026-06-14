"""Milvus storage adapter using an injected collection search function."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..base import BaseVectorStorage


VectorSearch = Callable[..., Awaitable[list[dict[str, Any]]]]


def normalize_milvus_uri(uri: str) -> str:
    """Use the HTTPS service port explicitly for Zilliz-style endpoints."""
    value = str(uri or "").strip()
    if not value:
        return ""

    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.port is not None:
        return value

    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    return urlunsplit(
        (
            parsed.scheme,
            f"{hostname}:443",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


class MilvusVectorStorage(BaseVectorStorage):
    """Delegate vector queries without coupling storage to the orchestrator."""

    def __init__(self, search: VectorSearch) -> None:
        self._search = search

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
        return await self._search(
            query_text=query_text,
            collection_name=collection_name,
            output_fields=output_fields,
            text_fields=text_fields,
            top_k=top_k,
            graph_name=graph_name,
            query_vector=query_vector,
            embed_if_missing=embed_if_missing,
        )
