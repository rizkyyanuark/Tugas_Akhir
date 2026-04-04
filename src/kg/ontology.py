"""
Ontology: Academic Knowledge Graph Schema
==========================================
Defines the complete ontology for the UNESA academic KG.
Adapted from Strwythura's ontology pipeline (vocabulary → taxonomy → thesaurus)
but simplified to a flat JSON config that is thesis-feasible.

This is the CONTRACT between NER extraction and graph construction.
Lock it down before running the pipeline.
"""

from typing import Set, Dict


# ══════════════════════════════════════════════════════════════
# Academic KG Ontology
# ══════════════════════════════════════════════════════════════
ONTOLOGY: Dict = {
    "node_types": {
        # Structural (from metadata backbone)
        "Dosen":           {"description": "Internal UNESA faculty member"},
        "Paper":           {"description": "Research publication"},
        "ProgramStudi":    {"description": "Study program / department"},
        "Journal":         {"description": "Publication venue"},
        "Year":            {"description": "Publication year"},
        "Keyword":         {"description": "Author-assigned keyword"},
        # Semantic (from NER + LLM curation)
        "Method":          {"description": "Research method or algorithm"},
        "Model":           {"description": "ML/AI model architecture"},
        "Metric":          {"description": "Evaluation metric"},
        "Dataset":         {"description": "Dataset used in study"},
        "Problem":         {"description": "Research problem addressed"},
        "Task":            {"description": "Computational/research task"},
        "Field":           {"description": "Research domain/field"},
        "Tool":            {"description": "Software tool or framework"},
        "Innovation":      {"description": "Novel contribution"},
    },
    "edge_types": {
        "WRITES":          ("Dosen", "Paper"),
        "MEMBER_OF":       ("Dosen", "ProgramStudi"),
        "PUBLISHED_YEAR":  ("Paper", "Year"),
        "PUBLISHED_IN":    ("Paper", "Journal"),
        "HAS_KEYWORD":     ("Paper", "Keyword"),
        "HAS_METHOD":      ("Paper", "Method"),
        "HAS_MODEL":       ("Paper", "Model"),
        "HAS_METRIC":      ("Paper", "Metric"),
        "HAS_DATASET":     ("Paper", "Dataset"),
        "ADDRESSES":       ("Paper", "Problem"),
        "HAS_TASK":        ("Paper", "Task"),
        "IN_FIELD":        ("Paper", "Field"),
        "HAS_TOOL":        ("Paper", "Tool"),
        "PROPOSES":        ("Paper", "Innovation"),
        "USES":            ("Entity", "Entity"),
    },
    "ner_labels": [
        "method", "model", "metric", "dataset",
        "problem", "task", "results", "innovation",
    ],
    "ner_label_map": {
        # GLiNER label → Neo4j node type
        "method": "Method",
        "algorithm": "Method",
        "technique": "Method",
        "research method": "Method",
        "model": "Model",
        "metric": "Metric",
        "evaluation metric": "Metric",
        "dataset": "Dataset",
        "problem": "Problem",
        "task": "Task",
        "field": "Field",
        "scientific concept": "Field",
        "tool": "Tool",
        "framework": "Tool",
        "software": "Tool",
        "platform": "Tool",
        "technology": "Tool",
        "programming language": "Tool",
        "innovation": "Innovation",
        "results": "Innovation",
    },
}


# ══════════════════════════════════════════════════════════════
# Helper Functions
# ══════════════════════════════════════════════════════════════

# Structural labels that come from metadata (not from NER)
_STRUCTURAL_LABELS: Set[str] = {
    "Dosen", "Paper", "ProgramStudi",
    "Journal", "Year", "Keyword",
}


def get_valid_semantic_labels() -> Set[str]:
    """Returns the set of labels that can be assigned by NER/LLM curation.
    These are all node types MINUS the structural ones from metadata.
    """
    return set(ONTOLOGY["node_types"].keys()) - _STRUCTURAL_LABELS


def map_ner_label(raw_label: str) -> str:
    """Map a raw NER label (from GLiNER or LLM) to the canonical Neo4j node type.

    Falls back to 'Field' for unknown labels.

    Args:
        raw_label: Raw label string (e.g. 'method', 'algorithm', 'Model')

    Returns:
        Canonical label (e.g. 'Method', 'Field')
    """
    # Try exact match first
    mapped = ONTOLOGY["ner_label_map"].get(raw_label.lower())
    if mapped:
        return mapped

    # Try capitalised match against node_types
    cap = raw_label.capitalize()
    if cap in ONTOLOGY["node_types"]:
        return cap

    return "Field"


def get_all_labels() -> list:
    """Returns all node type labels for constraint creation."""
    return list(ONTOLOGY["node_types"].keys())


def validate_ontology() -> bool:
    """Validate internal consistency of the ontology definition.

    Returns:
        True if valid, raises ValueError otherwise.
    """
    node_types = set(ONTOLOGY["node_types"].keys())

    # Check all edge endpoints reference valid node types
    for edge_type, (src, tgt) in ONTOLOGY["edge_types"].items():
        for endpoint in [src, tgt]:
            # Handle composite endpoints like 'Dosen/ExternalAuthor' and generic 'Entity'
            parts = endpoint.split("/")
            for part in parts:
                if part != "Entity" and part not in node_types:
                    raise ValueError(
                        f"Edge '{edge_type}' references unknown node type '{part}'"
                    )

    # Check all ner_label_map values are valid node types
    for raw_label, mapped in ONTOLOGY["ner_label_map"].items():
        if mapped not in node_types:
            raise ValueError(
                f"NER label map '{raw_label}' → '{mapped}' references unknown node type"
            )

    return True
