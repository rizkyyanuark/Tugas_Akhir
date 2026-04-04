"""
Weaviate Adapter: VectorStorage Interface for GraphRAG
=======================================================
Wraps Weaviate vector search for the 4 collections:
  - EntityEmbedding, RelationshipEmbedding, ContentKeyword, PaperChunk
"""

import os
import logging
from typing import Dict, List, Optional, Any

import weaviate
from weaviate.classes.query import MetadataQuery

from ..config import WEAVIATE_HOST, WEAVIATE_PORT

logger = logging.getLogger(__name__)


class WeaviateVectorStorage:
    """Read-only Weaviate adapter for GraphRAG retrieval."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        self.host = host or WEAVIATE_HOST
        self.port = port or WEAVIATE_PORT
        self.client = weaviate.connect_to_local(
            host=self.host,
            port=self.port,
            skip_init_checks=True,
            headers={
                "X-HuggingFace-Api-Key": os.environ.get("HF_TOKEN", ""),
            },
        )
        logger.info(f"✅ WeaviateVectorStorage connected to {self.host}:{self.port}")

    def close(self):
        if self.client:
            self.client.close()

    def query(
        self,
        collection_name: str,
        query_text: str,
        top_k: int = 10,
        return_properties: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform near_text vector search on a collection.

        Args:
            collection_name: One of EntityEmbedding, RelationshipEmbedding,
                             ContentKeyword, PaperChunk.
            query_text: Natural language query string.
            top_k: Number of results to return.
            return_properties: Specific properties to return (None = all).

        Returns:
            List of result dicts with properties + distance score.
        """
        col = self.client.collections.get(collection_name)

        response = col.query.near_text(
            query=query_text,
            limit=top_k,
            return_metadata=MetadataQuery(distance=True),
            return_properties=return_properties,
        )

        results = []
        for obj in response.objects:
            item = dict(obj.properties)
            if obj.metadata and obj.metadata.distance is not None:
                item["_distance"] = obj.metadata.distance
            results.append(item)

        return results

    def query_entities(self, query_text: str, top_k: int = 20) -> List[Dict]:
        """Search EntityEmbedding collection."""
        return self.query(
            "EntityEmbedding", query_text, top_k,
            return_properties=["entityName", "entityType", "description", "nodeId", "sourceId"],
        )

    def query_relationships(self, query_text: str, top_k: int = 30) -> List[Dict]:
        """Search RelationshipEmbedding collection."""
        return self.query(
            "RelationshipEmbedding", query_text, top_k,
            return_properties=["srcId", "tgtId", "relType", "description", "sourceId"],
        )

    def query_keywords(self, query_text: str, top_k: int = 10) -> List[Dict]:
        """Search ContentKeyword collection."""
        return self.query(
            "ContentKeyword", query_text, top_k,
            return_properties=["keywords", "sourcePaper"],
        )

    def query_chunks(self, query_text: str, top_k: int = 10) -> List[Dict]:
        """Search PaperChunk collection."""
        return self.query(
            "PaperChunk", query_text, top_k,
            return_properties=["title", "content", "year", "paperUrl", "authors"],
        )
