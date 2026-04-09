import pytest
from ta_backend_core.knowledge.kg.utils import md5, normalize_text, safe_str, truncate


def test_md5():
    """Test MD5 hashing limits to 12 chars."""
    res = md5("test_string")
    assert len(res) == 12
    # Ensure deterministic
    assert md5("test_string") == res
    assert md5("different") != res


def test_normalize_text():
    """Test text normalization."""
    assert normalize_text("  Hello World!  ") == "hello world"
    assert normalize_text("AI & Machine Learning") == "ai machine learning"
    assert normalize_text("NLP\t\n\rstuff") == "nlp stuff"


def test_safe_str():
    """Test safe string conversion for data frames."""
    assert safe_str("valid") == "valid"
    assert safe_str("  spaces  ") == "spaces"
    assert safe_str("NaN") == ""
    assert safe_str("none") == ""
    assert safe_str(None) == ""
    assert safe_str(float("nan"), "default") == "default"


def test_truncate():
    """Test string truncation for API safety."""
    text = "A" * 50
    assert len(truncate(text, max_len=20)) == 20
    assert len(truncate(text, max_len=100)) == 50
