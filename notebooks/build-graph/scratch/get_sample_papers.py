import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
from pathlib import Path

env_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\.env")
load_dotenv(env_path)

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
)

database = os.getenv("NEO4J_DATABASE", "neo4j")
with driver.session(database=database) as session:
    res = session.run("""
        MATCH (p:Publication {graph_name: 'yunesa_academic_kg'}) 
        RETURN p.title, p.keywords, p.year 
        LIMIT 5
    """)
    for r in res:
        print(f"Title: {r['p.title']}")
        print(f"Keywords: {r['p.keywords']}")
        print(f"Year: {r['p.year']}")
        print("-" * 50)

driver.close()
