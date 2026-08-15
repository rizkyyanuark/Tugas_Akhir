"""
quality.py — Knowledge Graph Quality Assessment & Quality Gates
=================================================================
Thesis-oriented quality gate metrics for built knowledge graphs.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
import networkx as nx

from yunesa.knowledge.constants import ONTOLOGY_RELATIONS
from yunesa.knowledge.utils.text_processing import (
    canonical_relation,
    field_value,
)
from yunesa.knowledge.graphs.relation_ops import duplicate_relation_report
from yunesa.knowledge.implementations.milvus import (
    _publication_author_labels,
    _publication_concept_labels,
    build_milvus_index_records,
    summarize_milvus_records,
)
from yunesa.knowledge.eval.entity_resolution import entity_resolution_report


def graph_quality_report(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Return thesis-oriented quality gates for the constructed graph."""
    node_type_counts = Counter(data.get("node_type", "Unknown") for _, data in graph.nodes(data=True))
    edge_counts = Counter(canonical_relation(data.get("relation", "UNKNOWN")) for _, _, data in graph.edges(data=True))
    paper_nodes = [node_id for node_id, data in graph.nodes(data=True) if data.get("node_type") == "Publication"]

    missing: dict[str, list[str]] = {
        "title": [],
        "abstract": [],
        "tldr": [],
        "keywords": [],
        "authors": [],
        "concepts": [],
    }
    for paper_node in paper_nodes:
        data = graph.nodes[paper_node]
        if not field_value(data, "title", "label"):
            missing["title"].append(paper_node)
        if not field_value(data, "abstract"):
            missing["abstract"].append(paper_node)
        if not field_value(data, "tldr"):
            missing["tldr"].append(paper_node)
        if not field_value(data, "keywords"):
            missing["keywords"].append(paper_node)
        if not _publication_author_labels(graph, paper_node):
            missing["authors"].append(paper_node)
        if not _publication_concept_labels(graph, paper_node):
            missing["concepts"].append(paper_node)

    concept_type_counts = Counter(
        data.get("concept_type", "unknown")
        for _, data in graph.nodes(data=True)
        if data.get("node_type") == "Concept"
    )
    non_ontology_edges = {
        relation: count
        for relation, count in edge_counts.items()
        if relation not in ONTOLOGY_RELATIONS and not relation.startswith("SKOS_")
    }
    duplicates = duplicate_relation_report(graph)

    vector_records = build_milvus_index_records(graph)
    return {
        "total_nodes": graph.number_of_nodes(),
        "total_edges": graph.number_of_edges(),
        "node_type_counts": dict(node_type_counts),
        "edge_counts": dict(edge_counts),
        "concept_type_counts": dict(concept_type_counts),
        "missing_counts": {key: len(value) for key, value in missing.items()},
        "missing_examples": {key: value[:10] for key, value in missing.items() if value},
        "non_ontology_edges": non_ontology_edges,
        "duplicate_relations": duplicates,
        "entity_resolution": entity_resolution_report(graph),
        "milvus_prepared_rows": summarize_milvus_records(vector_records),
        "quality_gates": {
            "has_publications": node_type_counts.get("Publication", 0) > 0,
            "all_publications_have_concepts": len(missing["concepts"]) == 0,
            "all_publications_have_authors": len(missing["authors"]) == 0,
            "all_publications_have_tldr": len(missing["tldr"]) == 0,
            "relations_are_ontology_aligned": not non_ontology_edges,
            "relations_are_deduplicated": duplicates["duplicate_relation_groups"] == 0,
        },
    }
