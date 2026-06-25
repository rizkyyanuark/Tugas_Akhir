import os
import sys
import json
from dotenv import load_dotenv
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

env_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\.env")
load_dotenv(env_path)

sys.path.insert(0, str(Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\notebooks\build-graph\src")))
from yunesa_academic_kg import graphrag_retrieve, GraphRAGQueryParam

print("Running graphrag_retrieve in subgraph mode...")
res = graphrag_retrieve(
    "Deep Learning",
    param=GraphRAGQueryParam(mode="subgraph", top_k=5, graph_name="yunesa_academic_kg")
)

print("\n--- Entities retrieved ---")
for ent in res.get("entities", []):
    print(f"Name: {ent.get('entityName')}, Distance: {ent.get('distance')}, Degree: {ent.get('degree')}")

print("\n--- Text Units retrieved ---")
for unit in res.get("text_units", []):
    print(f"Title: {unit.get('title')}, Distance: {unit.get('distance')}")
