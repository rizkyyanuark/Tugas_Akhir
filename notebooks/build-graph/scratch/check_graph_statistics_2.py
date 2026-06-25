import json
import networkx as nx
from networkx.readwrite import json_graph
from pathlib import Path

path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\data\kg_pipeline_test\kg\output\kg_node_link.json")

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

graph = json_graph.node_link_graph(data)

print("Nodes in graph:", graph.number_of_nodes())
print("Edges in graph:", graph.number_of_edges())

pub_count = sum(1 for n, d in graph.nodes(data=True) if d.get("node_type") == "Publication")
print("Publication nodes:", pub_count)

import sys
sys_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\notebooks\build-graph\src")
sys.path.insert(0, str(sys_path))
from yunesa_academic_kg import _content_keyword_records, _relationship_embedding_records

content_kw = _content_keyword_records(graph, graph_name="yunesa_academic_kg")
print("ContentKeyword records:", len(content_kw))

rel_emb = _relationship_embedding_records(graph, graph_name="yunesa_academic_kg")
print("RelationshipEmbedding records:", len(rel_emb))
