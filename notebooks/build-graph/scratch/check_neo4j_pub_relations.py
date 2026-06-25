import os
import sys
from neo4j import GraphDatabase
from dotenv import load_dotenv
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

env_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\.env")
load_dotenv(env_path)

uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USERNAME")
password = os.getenv("NEO4J_PASSWORD")
database = os.getenv("NEO4J_DATABASE")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from yunesa_academic_kg import _milvus_search, milvus_config_from_env

driver = GraphDatabase.driver(uri, auth=(user, password))

print("=== Checking Milvus Entity Search ===")
config = milvus_config_from_env()
res = _milvus_search(
    "Deep Learning",
    "EntityEmbedding",
    output_fields=["graphName", "entityName", "entityType", "description", "nodeId", "sourceId"],
    top_k=5,
    config=config,
    graph_name="yunesa_academic_kg"
)
for r in res:
    print("Entity:", r.get("entityName"), "| nodeId:", r.get("nodeId"), "| keys:", list(r.keys()))

print("\n=== Checking Neo4j Publication Connections ===")
with driver.session(database=database) as session:
    result = session.run("""
        MATCH (p:Publication)-[r]-(e:KGNode)
        WHERE p.graph_name = 'yunesa_academic_kg'
        RETURN p.title AS title, labels(e) AS e_labels, e.id AS e_id, type(r) AS rel_type
        LIMIT 10
    """)
    for r in result:
        print(f"Pub: {r['title']} -[:{r['rel_type']}]-> ({r['e_labels']}: {r['e_id']})")

driver.close()
