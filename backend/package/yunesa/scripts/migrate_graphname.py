#!/usr/bin/env python
"""Migration script to rename graphName in local Milvus collections.

Updates graphName from 'yunesa_academic_kg_gliner' to 'yunesa_academic_kg'.
"""
import os
import sys
import logging
from pymilvus import MilvusClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("migrate_graphname")

def migrate():
    uri = os.getenv("MILVUS_URI") or "http://localhost:19530"
    token = os.getenv("MILVUS_TOKEN") or ""
    db_name = os.getenv("MILVUS_DB_NAME") or "default"
    if db_name.strip().lower() in {"default", "none", "null"}:
        db_name = "default"

    logger.info(f"Connecting to Milvus at {uri} (DB: {db_name})...")
    try:
        client = MilvusClient(uri=uri, token=token, db_name=db_name)
    except Exception as e:
        logger.error(f"Failed to connect to Milvus: {e}")
        sys.exit(1)

    collections_fields = {
        "PaperChunk": ["id", "graphName", "title", "content", "year", "paperUrl", "authors", "embedding"],
        "EntityEmbedding": ["id", "graphName", "entityName", "entityType", "description", "nodeId", "sourceId", "embedding"],
        "RelationshipEmbedding": ["id", "graphName", "srcId", "tgtId", "relType", "description", "sourceId", "embedding"],
        "ContentKeyword": ["id", "graphName", "keywords", "sourcePaper", "embedding"]
    }

    source_graph = "yunesa_academic_kg_gliner"
    target_graph = "yunesa_academic_kg"

    existing_cols = client.list_collections()
    logger.info(f"Existing collections in Milvus: {existing_cols}")

    for col, fields in collections_fields.items():
        if col not in existing_cols:
            logger.warning(f"Collection {col} does not exist. Skipping.")
            continue

        logger.info(f"Processing collection {col}...")
        try:
            # Query all records matching yunesa_academic_kg_gliner
            expr = f'graphName == "{source_graph}"'
            records = client.query(
                collection_name=col,
                filter=expr,
                output_fields=fields,
                limit=16384  # high limit since counts are small (<2000 per collection)
            )
            
            count = len(records)
            logger.info(f"Found {count} records in {col} with graphName='{source_graph}'")
            if count == 0:
                logger.info(f"No migration needed for {col}.")
                continue

            # Update graphName
            for r in records:
                r["graphName"] = target_graph
                # Strip out any fields that are not in the schema just in case
                keys_to_remove = [k for k in r.keys() if k not in fields]
                for k in keys_to_remove:
                    del r[k]

            # Upsert in batches of 500
            batch_size = 500
            for i in range(0, len(records), batch_size):
                batch = records[i:i+batch_size]
                client.upsert(collection_name=col, data=batch)
                logger.info(f"  Upserted batch {i//batch_size + 1}/{(len(records)-1)//batch_size + 1} ({len(batch)} records)")

            logger.info(f"Successfully migrated {col} graphName to '{target_graph}'.")

            # Post-migration validation count
            val_res_gliner = client.query(col, filter=f'graphName == "{source_graph}"', output_fields=["count(*)"])
            val_res_academic = client.query(col, filter=f'graphName == "{target_graph}"', output_fields=["count(*)"])
            logger.info(f"Validation: {col} count for '{source_graph}': {val_res_gliner}")
            logger.info(f"Validation: {col} count for '{target_graph}': {val_res_academic}")

        except Exception as e:
            logger.error(f"Failed to migrate collection {col}: {e}", exc_info=True)

    logger.info("Migration complete.")

if __name__ == "__main__":
    migrate()
