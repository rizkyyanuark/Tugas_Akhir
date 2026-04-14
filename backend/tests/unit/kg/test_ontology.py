import pytest
from knowledge.kg.ontology import validate_ontology, map_ner_label, get_valid_semantic_labels


def test_ontology_validation():
    """Ensure the ontology schema configuration is internally consistent."""
    assert validate_ontology() is True, "Ontology structure must be valid."


def test_map_ner_label():
    """Test mapping of raw string NER labels to canonical Neo4j Graph node types."""
    assert map_ner_label("method") == "Method"
    assert map_ner_label("evaluation metric") == "Metric"
    assert map_ner_label("software") == "Tool"

    # Capitalized passthrough check
    assert map_ner_label("Model") == "Model"
    assert map_ner_label("Dataset") == "Dataset"

    # Fallback default check
    assert map_ner_label("not_a_real_label_at_all") == "Field"
    assert map_ner_label(12345) == "Field"


def test_get_valid_semantic_labels():
    """Test that structural nodes (Papers, Authors) aren't mixed with semantic nodes."""
    semantic = get_valid_semantic_labels()

    # Ensure they are exclusively semantic NER labels
    assert "Method" in semantic
    assert "Model" in semantic

    # Ensure raw backbone labels are stripped
    assert "Dosen" not in semantic
    assert "Paper" not in semantic
    assert "ProgramStudi" not in semantic
