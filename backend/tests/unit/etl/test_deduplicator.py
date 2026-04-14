import pytest
import pandas as pd
from knowledge.etl.transform.deduplicator import deduplicate_papers, _normalize_text, _trigrams


def test_normalize_text():
    """Test normalization to lowercase, trimmed string."""
    assert _normalize_text("  Machine Learning  ") == "machinelearning"
    assert _normalize_text(pd.NA) == ""


def test_trigrams():
    """Ensure trigram breakdown works."""
    assert _trigrams("Ai") == set()  # Too short
    assert _trigrams("Deep") == {"dee", "eep"}


def test_deduplicate_papers_exact():
    """Test exact deduplication logic based on identical titles/doi."""
    data = {
        "Title": ["Paper A", "Paper A", "Paper B", "Paper C"],
        "doi": ["10.123/a", "10.123/a", "10.123/b", None],
        "year": [2020, 2020, 2021, 2022]
    }
    df = pd.DataFrame(data)

    # deduplicate_papers should remove 1 duplicate of 'Paper A'
    # We also need to compute _title_norm before passing if deduplicator expects it,
    # but based on the output earlier, it doesn't compute it inside, wait, it does compute in `deduplicate_papers`?
    # Actually it expects _title_norm to exist if `df['_title_norm']` is used. Wait.
    df['_title_norm'] = df['Title'].apply(_normalize_text)

    result_df = deduplicate_papers(df, fuzzy_threshold=0.85)

    assert len(result_df) == 3
    # Check that Paper A survived with correct DOI
    assert result_df[result_df["Title"] ==
                     "Paper A"].iloc[0]["doi"] == "10.123/a"


def test_deduplicate_papers_fuzzy():
    """Test fuzzy deduplication (similar titles)."""
    data = {
        "Title": [
            "A Deep Learning Approach for NLP",
            "A deep-learning approach for nlp",  # Very similar, should be dropped
            "Completely Different Topic"
        ],
        "doi": [None, None, "10.111/cd"]
    }
    df = pd.DataFrame(data)
    df['_title_norm'] = df['Title'].apply(_normalize_text)

    # Needs to catch the fuzzy match
    result_df = deduplicate_papers(df, fuzzy_threshold=0.70)

    assert len(result_df) == 2
    titles = result_df["Title"].tolist()
    assert "Completely Different Topic" in titles
