import pytest
import pandas as pd
from ta_backend_core.knowledge.etl.transform.cleaner import clean_text


def test_clean_text_basic():
    """Test basic cleaning operations like strip and html unescape."""
    assert clean_text("  This is clean  ") == "This is clean"
    assert clean_text("Title &amp; Subtitle") == "Title & Subtitle"


def test_clean_text_html_removal():
    """Test aggressive HTML tag removal."""
    dirty = "<p><i>Title</i> of <b>Paper</b><br/></p>"
    assert clean_text(dirty) == "Title of Paper"


def test_clean_text_nan_handling():
    """Test how None/NaN values are handled gracefully."""
    assert clean_text(None) == ""
    assert clean_text(pd.NA) == ""
    # Returns empty string for non-string types per signature expectation
    assert clean_text(1234) == ""


def test_clean_text_whitespace():
    """Test whitespace and zero-width char normalization."""
    # Simulating zero-width space (\u200b) and weird tabs/newlines
    dirty = "This\u200b \t is   a \n mess"
    # Should replace multiple whitespaces with single spaces
    assert clean_text(dirty) == "This is a mess"
