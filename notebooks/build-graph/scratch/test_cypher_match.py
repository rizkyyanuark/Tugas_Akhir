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

driver = GraphDatabase.driver(uri, auth=(user, password))

title = "Is retirement the end or the beginning? A psychological perspective on productivity among Indonesian retirees"
entity_ids = ["concept:e536fa975d85a4f4"]
graph_name = "yunesa_academic_kg"

with driver.session(database=database) as session:
    res = session.run(
        """
        UNWIND $titles AS paper_title
        MATCH (p:Publication) WHERE p.title = paper_title
        AND ($graph_name = '' OR p.graph_name = $graph_name)
        OPTIONAL MATCH (p)-[r]-(e:KGNode)
        WHERE e.id IN $entity_ids
        RETURN paper_title, count(DISTINCT e) AS match_count
        """,
        titles=[title],
        entity_ids=entity_ids,
        graph_name=graph_name
    )
    for record in res:
        print("Record:", record["paper_title"], "| Match Count:", record["match_count"])

driver.close()
