"""
Milvus Adapter: VectorStorage Interface for GraphRAG
======================================================
Wraps Milvus vector search for the 4 collections:
  - EntityEmbedding, RelationshipEmbedding, ContentKeyword, PaperChunk

Mirrors the WeaviateVectorStorage API so all downstream retrievers
work without change beyond import swaps.
"""

import os
import logging
from typing import Dict, List, Optional, Any

from pymilvus import connections, Collection

from ..config import MILVUS_HOST, MILVUS_PORT

logger = logging.getLogger(__name__)

# Lazy-loaded embedding model (shared with milvus_writer)
_EMBED_MODEL_NAME = os.environ.get(
    "MILVUS_EMBED_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)
_embed_model = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(_EMBED_MODEL_NAME)
        logger.info(f"Loaded embedding model: {_EMBED_MODEL_NAME}")
    return _embed_model


class MilvusVectorStorage:
    """Read-only Milvus adapter for GraphRAG retrieval."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        alias: str = "graphrag_reader",
    ):
        self.host = host or MILVUS_HOST
        self.port = port or MILVUS_PORT
        self.alias = alias
        connections.connect(
            alias=self.alias,
            host=self.host,
            port=str(self.port),
        )
        logger.info(f"✅ MilvusVectorStorage connected to {self.host}:{self.port}")

    def close(self):
        try:
            connections.disconnect(alias=self.alias)
        except Exception:
            pass

    def query(
        self,
        collection_name: str,
        query_text: str,
        top_k: int = 10,
        return_properties: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform embedding similarity search on a collection.

        Args:
            collection_name: One of EntityEmbedding, RelationshipEmbedding,
                             ContentKeyword, PaperChunk.
            query_text: Natural language query string.
            top_k: Number of results to return.
            return_properties: Specific properties to return (None = all).

        Returns:
            List of result dicts with properties + distance score.
        """
        model = _get_embed_model()
        query_embedding = model.encode([query_text])[0].tolist()

        col = Collection(collection_name, using=self.alias)
        col.load()

        # Determine output fields (exclude id and embedding)
        if return_properties:
            output_fields = return_properties
        else:
            output_fields = [
                f.name for f in col.schema.fields
                if f.name not in ("id", "embedding")
            ]

        search_params = {"metric_type": "L2", "params": {"nprobe": 16}}

        hits = col.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            output_fields=output_fields,
        )

        results = []
        for hit in hits[0]:
            item = {field: hit.entity.get(field) for field in output_fields}
            item["_distance"] = hit.distance
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
