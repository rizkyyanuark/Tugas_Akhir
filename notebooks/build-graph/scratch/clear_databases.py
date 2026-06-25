import os
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase
from pymilvus import MilvusClient

# Load .env file
env_path = Path("c:/Users/rizky/Documents/GitHub/Tugas_Akhir/.env")
if env_path.exists():
    load_dotenv(env_path)
    print(f"Loaded environment from {env_path}")
else:
    print("Warning: .env file not found!")

# Get Neo4j credentials
neo4j_uri = os.getenv("NEO4J_URI")
neo4j_user = os.getenv("NEO4J_USERNAME")
neo4j_password = os.getenv("NEO4J_PASSWORD")
neo4j_db = os.getenv("NEO4J_DATABASE", "neo4j")

# Get Milvus credentials
milvus_uri = os.getenv("MILVUS_URI")
milvus_token = os.getenv("MILVUS_TOKEN")
milvus_db = os.getenv("MILVUS_DB_NAME", "default")

print("\n--- Clearing Neo4j (AuraDB) ---")
if neo4j_uri and neo4j_user and neo4j_password:
    print(f"Connecting to Neo4j at {neo4j_uri}...")
    try:
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        with driver.session(database=neo4j_db) as session:
            print("Executing DETACH DELETE...")
            result = session.run("MATCH (n) DETACH DELETE n")
            summary = result.consume()
            nodes_deleted = summary.counters.nodes_deleted
            relationships_deleted = summary.counters.relationships_deleted
            print(f"Success! Deleted {nodes_deleted} nodes and {relationships_deleted} relationships.")
        driver.close()
    except Exception as e:
        print(f"Error clearing Neo4j: {e}")
else:
    print("Skipping Neo4j (credentials missing in .env)")

print("\n--- Clearing Zilliz (Milvus) ---")
if milvus_uri and milvus_token:
    print(f"Connecting to Milvus at {milvus_uri} (DB: {milvus_db})...")
    try:
        client = MilvusClient(
            uri=milvus_uri,
            token=milvus_token,
            db_name=milvus_db
        )
        collections = ["RelationshipEmbedding", "EntityEmbedding", "PaperChunk", "ContentKeyword"]
        existing_cols = client.list_collections()
        print(f"Existing collections: {existing_cols}")
        for col in collections:
            if col in existing_cols:
                print(f"Dropping collection {col}...")
                client.drop_collection(collection_name=col)
                print(f"Dropped {col} successfully.")
            else:
                print(f"Collection {col} does not exist. Skipping.")
        print("Success! Milvus collections cleared.")
    except Exception as e:
        print(f"Error clearing Milvus: {e}")
else:
    print("Skipping Milvus (credentials missing in .env)")
