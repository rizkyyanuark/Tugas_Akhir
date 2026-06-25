import os
from pymilvus import MilvusClient
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\.env")
load_dotenv(env_path)

uri = os.getenv("MILVUS_URI")
token = os.getenv("MILVUS_TOKEN")

client = MilvusClient(uri=uri, token=token)

collections = ["ContentKeyword", "EntityEmbedding", "RelationshipEmbedding", "PaperChunk"]

for col in collections:
    print(f"\n=== Collection: {col} ===")
    try:
        # Query distinct graphName
        res = client.query(
            collection_name=col,
            filter="",
            output_fields=["graphName"],
            limit=100
        )
        graph_names = set(r.get("graphName") for r in res if r.get("graphName") is not None)
        print("Sample Graph Names in Milvus:", graph_names)
        
        # Print total count
        count_res = client.query(
            collection_name=col,
            filter="",
            output_fields=["count(*)"]
        )
        print("Total Count:", count_res)
    except Exception as e:
        print("Error:", e)

client.close()
