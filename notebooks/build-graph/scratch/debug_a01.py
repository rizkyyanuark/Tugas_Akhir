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

query = "Metode klasifikasi apa yang digunakan untuk mendeteksi gaya belajar visual, auditory, kinesthetic melalui aplikasi pesan instan?"

for mode in ["naive", "subgraph"]:
    print(f"\n=================== MODE: {mode} ===================")
    res = graphrag_retrieve(
        query,
        param=GraphRAGQueryParam(mode=mode, top_k=10, graph_name="yunesa_academic_kg")
    )
    
    print("Keyword decomposition:", res.get("keyword_decomposition"))
    
    print("\n--- Entities (top 5) ---")
    for ent in res.get("entities", [])[:5]:
        print(f"Name: {ent.get('entityName')} | Type: {ent.get('entityType')} | Dist: {ent.get('distance')} | Deg: {ent.get('degree')}")
        
    print("\n--- Retrieved papers (top 10) ---")
    chunks = res.get("paper_chunks") if mode == "naive" else res.get("text_units")
    for idx, chunk in enumerate(chunks, 1):
        print(f"{idx}. Title: {chunk.get('title')} | Dist: {chunk.get('distance')}")
