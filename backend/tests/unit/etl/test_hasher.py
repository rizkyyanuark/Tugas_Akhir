import pytest
from ta_backend_core.knowledge.etl.utils.hasher import generate_paper_id


def test_generate_paper_id_with_doi():
    """Test generating a deterministic ID when DOI is present."""
    doi = "10.1234/test.doi"
    id1 = generate_paper_id(doi=doi, title="Some Topic", year=2024)
    id2 = generate_paper_id(
        doi=doi, title="A Completely Different Topic", year=2020)

    # DOI always takes precedence, so these should be identical
    assert id1 == id2, "Paper ID should be deterministic based exclusively on DOI if provided."
    # Case sensitivity check
    id3 = generate_paper_id(doi="10.1234/TEST.DOI", title="X", year=2021)
    assert id1 == id3, "Paper ID generation from DOI should be case-insensitive."


def test_generate_paper_id_without_doi():
    """Test generating an ID using Title + Year when DOI is absent or invalid."""
    id1 = generate_paper_id(doi=None, title="Deep Learning in AI", year=2022)
    id2 = generate_paper_id(doi="", title="Deep Learning in AI", year=2022)
    id3 = generate_paper_id(doi="nan", title="Deep-Learning in AI!", year=2022)

    # Special characters and spaces are stripped, so "Deep Learning in AI" == "Deep-Learning in AI!"
    assert id1 == id2, "Empty strings should trigger title+year fallback."
    assert id1 == id3, "Invalid 'nan' strings and special characters should still map to the same id."


def test_generate_paper_id_case_insensitivity_title():
    """Ensure Title+Year hashing ignores case and whitespace entirely."""
    id1 = generate_paper_id(doi=None, title="Hello World", year=2020)
    id2 = generate_paper_id(doi=None, title="hello world", year=2020)
    id3 = generate_paper_id(doi=None, title="HeLLo    WOrLD  ", year=2020)

    assert id1 == id2 == id3, "Title-based hashing must be perfectly case/whitespace invariant."
