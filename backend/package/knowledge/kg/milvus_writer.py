"""
Milvus Writer: Vector Database Ingestion
==========================================
Handles all Milvus write operations for the KG pipeline:
  - Collection schema creation (4 collections)
  - Batch insert with error handling

Uses SiliconFlow API for embedding generation,
matching the Yuxi architecture's lean integration.
"""

import logging
import os
from typing import Dict, List, Optional
import requests

from pymilvus import (
    connections,
    utility,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
)

from .config import MILVUS_HOST, MILVUS_PORT

logger = logging.getLogger(__name__)

# ── Embedding Configuration ──
# Using SiliconFlow API for embeddings to keep the environment lean
_EMBED_MODEL_NAME = os.environ.get(
    "MILVUS_EMBED_MODEL",
    "BAAI/bge-m3",
)
_API_KEY = os.environ.get("SILICONFLOW_API_KEY")
_API_URL = "https://api.siliconflow.cn/v1/embeddings"

EMBEDDING_DIM = 1024  # BAAI/bge-m3 outputs 1024-dim vectors


def get_embeddings(texts: List[str]) -> List[List[float]]:
    """Fetch embeddings from SiliconFlow API."""
    if not _API_KEY:
        raise ValueError("SILICONFLOW_API_KEY environment variable is not set.")

    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": _EMBED_MODEL_NAME,
        "input": texts
    }

    try:
        response = requests.post(_API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]
    except Exception as e:
        logger.error(f"Failed to fetch embeddings from SiliconFlow: {e}")
        raise RuntimeError(f"Embedding generation failed: {e}")


# ── Collection schemas ──
_COLLECTIONS = {
    "EntityEmbedding": {
        "embed_field": "description",
        "fields": [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="entityName", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="entityType", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=4096),
            FieldSchema(name="nodeId", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="sourceId", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
        ],
    },
    "RelationshipEmbedding": {
        "embed_field": "description",
        "fields": [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="srcId", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="tgtId", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="relType", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=4096),
            FieldSchema(name="sourceId", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
        ],
    },
    "ContentKeyword": {
        "embed_field": "keywords",
        "fields": [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="keywords", dtype=DataType.VARCHAR, max_length=2048),
            FieldSchema(name="sourcePaper", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
        ],
    },
    "PaperChunk": {
        "embed_field": "content",
        "fields": [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8192),
            FieldSchema(name="year", dtype=DataType.VARCHAR, max_length=16),
            FieldSchema(name="paperUrl", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="authors", dtype=DataType.VARCHAR, max_length=2048),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
        ],
    },
}


class MilvusKGWriter:
    """Production-grade Milvus writer for the KG pipeline.

    Creates 4 collections with IVF_FLAT index and performs
    batched inserts with API-based embedding generation.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        alias: str = "kg_writer",
    ):
        self.host = host or MILVUS_HOST
        self.port = port or MILVUS_PORT
        self.alias = alias

        try:
            connections.connect(
                alias=self.alias,
                host=self.host,
                port=str(self.port),
            )
            logger.info(f"✅ MilvusKGWriter connected to {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Milvus at {self.host}:{self.port}: {e}")
            raise

    def close(self):
        """Cleanly disconnect from Milvus."""
        try:
            connections.disconnect(alias=self.alias)
            logger.info("Milvus connection closed.")
        except Exception:
            pass

    def ensure_collections(self, recreate: bool = True):
        """Create all 4 Milvus collections for the KG pipeline."""
        for name, spec in _COLLECTIONS.items():
            if utility.has_collection(name, using=self.alias):
                if recreate:
                    utility.drop_collection(name, using=self.alias)
                    logger.info(f"  Dropped existing collection: {name}")
                else:
                    logger.info(f"  Collection already exists (kept): {name}")
                    continue

            schema = CollectionSchema(fields=spec["fields"], description=f"KG {name}")
            col = Collection(name=name, schema=schema, using=self.alias)

            # Create IVF_FLAT index on the embedding field
            index_params = {
                "index_type": "IVF_FLAT",
                "metric_type": "L2",
                "params": {"nlist": 128},
            }
            col.create_index(field_name="embedding", index_params=index_params)
            col.load()

            logger.info(
                f"  Created collection: {name} "
                f"(index=IVF_FLAT, dim={EMBEDDING_DIM})"
            )

    def ingest(
        self,
        collection_name: str,
        data: List[Dict],
        batch_size: int = 50,
    ) -> int:
        """Batch-insert data into a Milvus collection."""
        if not data:
            logger.info(f"  {collection_name}: no data to ingest")
            return 0

        spec = _COLLECTIONS[collection_name]
        embed_field = spec["embed_field"]
        col = Collection(collection_name, using=self.alias)
        batch_errors = 0

        # Get field names (excluding id and embedding)
        data_field_names = [
            f.name for f in spec["fields"]
            if f.name not in ("id", "embedding")
        ]

        for start in range(0, len(data), batch_size):
            try:
                batch = data[start: start + batch_size]

                # Prepare column-oriented data for Milvus
                columns = {fname: [] for fname in data_field_names}
                texts_to_embed = []

                for item in batch:
                    for fname in data_field_names:
                        val = str(item.get(fname, ""))[:self._max_len(spec, fname)]
                        columns[fname].append(val)
                    texts_to_embed.append(str(item.get(embed_field, "")))

                # Generate embeddings via API
                embeddings = get_embeddings(texts_to_embed)

                # Build insert list in field order
                insert_data = [columns[fname] for fname in data_field_names]
                insert_data.append(embeddings)

                col.insert(insert_data)

            except Exception as e:
                batch_errors += 1
                logger.error(
                    f"Milvus batch error [{collection_name}] at offset {start}: "
                    f"{type(e).__name__}: {e}"
                )

        col.flush()
        logger.info(
            f"  {collection_name}: {len(data)} objects "
            f"(batch errors: {batch_errors})"
        )
        return batch_errors

    @staticmethod
    def _max_len(spec: Dict, field_name: str) -> int:
        """Get max length for a VARCHAR field."""
        for f in spec["fields"]:
            if f.name == field_name:
                return getattr(f, "max_length", 65535)
        return 65535
