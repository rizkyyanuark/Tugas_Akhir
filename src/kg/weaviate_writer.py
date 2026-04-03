"""
Weaviate Writer: Vector Database Ingestion
============================================
Handles all Weaviate write operations for the KG pipeline:
  - Collection schema creation (4 collections)
  - Batch insert with error handling

Uses text2vec-transformers for automatic vectorisation.
"""

import logging
from typing import Dict, List, Optional

import weaviate
from weaviate.classes.config import Configure, Property, DataType
from weaviate.classes.data import DataObject

from .config import WEAVIATE_HOST, WEAVIATE_PORT

logger = logging.getLogger(__name__)

# Collection schemas: {name: [properties]}
_COLLECTIONS_CONFIG = {
    "EntityEmbedding": [
        Property(name="entityName", data_type=DataType.TEXT),
        Property(name="entityType", data_type=DataType.TEXT),
        Property(name="description", data_type=DataType.TEXT),
        Property(name="nodeId", data_type=DataType.TEXT),
    ],
    "RelationshipEmbedding": [
        Property(name="srcId", data_type=DataType.TEXT),
        Property(name="tgtId", data_type=DataType.TEXT),
        Property(name="relType", data_type=DataType.TEXT),
        Property(name="description", data_type=DataType.TEXT),
    ],
    "ContentKeyword": [
        Property(name="keywords", data_type=DataType.TEXT),
        Property(name="sourcePaper", data_type=DataType.TEXT),
    ],
    "PaperChunk": [
        Property(name="title", data_type=DataType.TEXT),
        Property(name="content", data_type=DataType.TEXT),
        Property(name="year", data_type=DataType.TEXT),
        Property(name="paperUrl", data_type=DataType.TEXT),
    ],
}


class WeaviateKGWriter:
    """Production-grade Weaviate writer for the KG pipeline.

    Creates 4 collections with text2vec-transformers vectoriser
    and performs batched inserts with error handling.

    Usage:
        writer = WeaviateKGWriter()
        writer.ensure_collections(recreate=True)
        writer.ingest("EntityEmbedding", entity_data)
        writer.ingest("PaperChunk", chunk_data)
        writer.close()
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        self.host = host or WEAVIATE_HOST
        self.port = port or WEAVIATE_PORT

        try:
            self.client = weaviate.connect_to_local(
                host=self.host, port=self.port
            )
            logger.info(f"✅ WeaviateKGWriter connected to {self.host}:{self.port}")
        except Exception as e:
            logger.error(
                f"❌ Failed to connect to Weaviate at {self.host}:{self.port}: {e}"
            )
            raise

    def close(self):
        """Cleanly close the Weaviate client."""
        if self.client:
            self.client.close()
            logger.info("Weaviate client closed.")

    def ensure_collections(self, recreate: bool = True):
        """Create all 4 Weaviate collections for the KG pipeline.

        Args:
            recreate: If True, delete existing collections first (fresh start).
                      If False, skip creation if collection already exists.
        """
        for name, props in _COLLECTIONS_CONFIG.items():
            if self.client.collections.exists(name):
                if recreate:
                    self.client.collections.delete(name)
                    logger.info(f"  Deleted existing collection: {name}")
                else:
                    logger.info(f"  Collection already exists (kept): {name}")
                    continue

            self.client.collections.create(
                name=name,
                vectorizer_config=Configure.Vectorizer.text2vec_transformers(),
                properties=props,
            )
            logger.info(f"  Created collection: {name}")

    def ingest(
        self,
        collection_name: str,
        data: List[Dict],
        batch_size: int = 50,
    ) -> int:
        """Batch-insert data into a Weaviate collection.

        Args:
            collection_name: Name of the target collection.
            data: List of property dicts to insert.
            batch_size: Number of objects per batch insert.

        Returns:
            Number of batch errors.
        """
        if not data:
            logger.info(f"  {collection_name}: no data to ingest")
            return 0

        col = self.client.collections.get(collection_name)
        batch_errors = 0

        for start in range(0, len(data), batch_size):
            try:
                batch = data[start : start + batch_size]
                col.data.insert_many(
                    [DataObject(properties=item) for item in batch]
                )
            except Exception as e:
                batch_errors += 1
                logger.error(
                    f"Weaviate batch error [{collection_name}] at offset {start}: "
                    f"{type(e).__name__}: {e}"
                )

        logger.info(
            f"  {collection_name}: {len(data)} objects "
            f"(batch errors: {batch_errors})"
        )
        return batch_errors

    def ingest_all(
        self,
        entity_vdb: List[Dict],
        relationship_vdb: List[Dict],
        keywords_vdb: List[Dict],
        chunk_vdb: List[Dict],
    ) -> Dict[str, int]:
        """Ingest all VDB data into their respective collections.

        Args:
            entity_vdb: EntityEmbedding data.
            relationship_vdb: RelationshipEmbedding data.
            keywords_vdb: ContentKeyword data.
            chunk_vdb: PaperChunk data.

        Returns:
            Dict of {collection_name: error_count}.
        """
        logger.info("Ingesting to Weaviate (batched)...")
        errors = {}
        errors["EntityEmbedding"] = self.ingest("EntityEmbedding", entity_vdb)
        errors["RelationshipEmbedding"] = self.ingest("RelationshipEmbedding", relationship_vdb)
        errors["ContentKeyword"] = self.ingest("ContentKeyword", keywords_vdb)
        errors["PaperChunk"] = self.ingest("PaperChunk", chunk_vdb)
        return errors
