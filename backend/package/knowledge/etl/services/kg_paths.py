"""Knowledge Graph construction artifact paths.

All intermediate artifacts live under ``SAVE_DIR/kg`` so Airflow
DockerOperator tasks can exchange state through the mounted ``/app/data``
volume without keeping large objects in memory.
"""

from __future__ import annotations

from ..config import SAVE_DIR
from ..utils.storage import get_path_obj

# Input snapshots fetched from Supabase.
KG_PAPERS_PARQUET = get_path_obj(SAVE_DIR, "kg/input/kg_papers.parquet")
KG_LECTURERS_PARQUET = get_path_obj(SAVE_DIR, "kg/input/kg_lecturers.parquet")
KG_LINKS_PARQUET = get_path_obj(SAVE_DIR, "kg/input/kg_paper_lecturers.parquet")

# Optional GLiNER extraction output.
KG_ENTITIES_JSON = get_path_obj(SAVE_DIR, "kg/extraction/kg_extracted_entities.json")

# Graph build output.
KG_GRAPH_JSON = get_path_obj(SAVE_DIR, "kg/output/kg_node_link.json")
KG_NODES_PARQUET = get_path_obj(SAVE_DIR, "kg/output/kg_nodes.parquet")
KG_EDGES_PARQUET = get_path_obj(SAVE_DIR, "kg/output/kg_edges.parquet")
KG_SUMMARY_JSON = get_path_obj(SAVE_DIR, "kg/output/kg_build_summary.json")
KG_ENTITY_RESOLUTION_JSON = get_path_obj(SAVE_DIR, "kg/output/kg_entity_resolution_report.json")

# IEEE resources baked into the Docker image.
IEEE_THESAURUS_DOCKER = "/app/package/knowledge/etl/resources/ieee-thesaurus.ttl"
IEEE_TAXONOMY_DOCKER = "/app/package/knowledge/etl/resources/ieee-taxonomy.ttl"
CONCEPT_ALIASES_DOCKER = "/app/package/knowledge/etl/resources/concept_aliases.yml"
