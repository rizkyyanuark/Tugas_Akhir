import os
from neo4j import GraphDatabase
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\.env")
load_dotenv(env_path)

uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USERNAME")
password = os.getenv("NEO4J_PASSWORD")
database = os.getenv("NEO4J_DATABASE")

driver = GraphDatabase.driver(uri, auth=(user, password))

with driver.session(database=database) as session:
    res = session.run("""
        MATCH ()-[r]->()
        WHERE r.graph_name = 'yunesa_academic_kg' OR r.graph_name IS NULL
        RETURN type(r) AS rel_type, count(r) AS cnt
    """)
    total = 0
    for record in res:
        print(f"Rel Type: {record['rel_type']}, Count: {record['cnt']}")
        total += record['cnt']
    print("Total edges:", total)

driver.close()
