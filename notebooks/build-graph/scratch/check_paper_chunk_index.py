import os
from pymilvus import MilvusClient
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\.env")
load_dotenv(env_path)

uri = os.getenv("MILVUS_URI")
token = os.getenv("MILVUS_TOKEN")

client = MilvusClient(uri=uri, token=token)
print("PaperChunk Index Description:")
print(client.describe_index('PaperChunk', 'embedding'))
client.close()
