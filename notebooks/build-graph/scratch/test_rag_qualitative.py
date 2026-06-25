import os
import sys
from dotenv import load_dotenv
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

env_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\.env")
load_dotenv(env_path)

sys.path.insert(0, str(Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\notebooks\build-graph\src")))
from yunesa_academic_kg import graphrag_answer, GraphRAGQueryParam, GraphRAGGenerationParam

query = "Bagaimana pengaruh model pembelajaran flipped classroom terhadap prestasi belajar siswa pada mata pelajaran rancang bangun jaringan?"

print(f"Query: {query}\n")

print("=" * 60)
print("Running RAG in NAIVE mode (Vector-only)...")
print("=" * 60)
try:
    res_naive = graphrag_answer(
        query,
        retrieval_param=GraphRAGQueryParam(mode="naive", top_k=3, graph_name="yunesa_academic_kg"),
        generation_param=GraphRAGGenerationParam(max_tokens=500)
    )
    print("\nAnswer (Naive):")
    print(res_naive.get("generation", {}).get("answer"))
except Exception as e:
    print(f"Error in naive: {e}")

print("\n" + "=" * 60)
print("Running RAG in SUBGRAPH mode (Graph-based)...")
print("=" * 60)
try:
    res_subgraph = graphrag_answer(
        query,
        retrieval_param=GraphRAGQueryParam(mode="subgraph", top_k=3, graph_name="yunesa_academic_kg"),
        generation_param=GraphRAGGenerationParam(max_tokens=500)
    )
    print("\nAnswer (Subgraph):")
    print(res_subgraph.get("generation", {}).get("answer"))
    
    print("\nEntities matched:")
    for ent in res_subgraph.get("retrieval", {}).get("entities", []):
        print(f"- {ent.get('entityName')} ({ent.get('entityType')}) | Degree: {ent.get('degree')}")
except Exception as e:
    print(f"Error in subgraph: {e}")
