import os
import sys
from neo4j import GraphDatabase
from dotenv import load_dotenv
from pathlib import Path

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

env_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\.env")
load_dotenv(env_path)

uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USERNAME")
password = os.getenv("NEO4J_PASSWORD")
database = os.getenv("NEO4J_DATABASE")

print(f"URI: {uri}")
print(f"User: {user}")
print(f"Database: {database}")

driver = GraphDatabase.driver(uri, auth=(user, password))

with driver.session(database=database) as session:
    # 1. Get sample publication node properties
    print("\n--- Sample Publication Properties ---")
    result = session.run("""
        MATCH (p:Publication)
        RETURN p.title AS title, keys(p) AS keys, labels(p) AS labels, p.graph_name AS graph_name
        LIMIT 3
    """)
    for r in result:
        print("Title:", r["title"])
        print("Keys:", r["keys"])
        print("Labels:", r["labels"])
        print("Graph Name:", r["graph_name"])
        print("-" * 40)

    # 2. Get count of Publication nodes and distinct graph_name
    print("\n--- Publication Counts by Graph Name ---")
    result = session.run("""
        MATCH (p:Publication)
        RETURN p.graph_name AS graph_name, count(p) AS cnt
    """)
    for r in result:
        print(f"Graph: {r['graph_name']}, Count: {r['cnt']}")

    # 3. Check for KGNode labels vs other labels
    print("\n--- Sample Node Labels in DB ---")
    result = session.run("""
        MATCH (n)
        RETURN DISTINCT labels(n) AS labels, count(n) AS count
        LIMIT 10
    """)
    for r in result:
        print(f"Labels: {r['labels']}, Count: {r['count']}")

    # 4. Check if we have nodes with label KGNode
    print("\n--- Check KGNode Label Count ---")
    result = session.run("""
        MATCH (n:KGNode)
        RETURN count(n) AS cnt
    """)
    for r in result:
        print("Count of KGNode:", r["cnt"])

driver.close()
