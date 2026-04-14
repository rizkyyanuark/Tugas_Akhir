"""
Utils: Shared Utility Functions for KG Pipeline
================================================
Text normalisation, hashing, and lemma-key generation.
The make_lemma_key function is adapted from Strwythura's
tokenize_lemma pattern for entity deduplication.
"""

import hashlib
import re
import logging
from typing import Optional

# import spacy  # Deferred to get_nlp()

from .config import SPACY_MODEL_NAME

logger = logging.getLogger(__name__)

_nlp = None


def get_nlp():
    """Lazy loader for spaCy model."""
    global _nlp
    if _nlp is None:
        logger.info(f"Loading spaCy model: {SPACY_MODEL_NAME}...")
        try:
            import spacy
            _nlp = spacy.load(SPACY_MODEL_NAME)
            logger.info(f"✅ spaCy model loaded: {SPACY_MODEL_NAME}")
        except OSError:
            logger.warning(
                f"spaCy model '{SPACY_MODEL_NAME}' not found. "
                f"Downloading... Run: python -m spacy download {SPACY_MODEL_NAME}"
            )
            import spacy.cli
            spacy.cli.download(SPACY_MODEL_NAME)
            _nlp = spacy.load(SPACY_MODEL_NAME)
            logger.info(f"✅ spaCy model downloaded and loaded: {SPACY_MODEL_NAME}")
    return _nlp


def md5(text: str) -> str:
    """Generate a truncated MD5 hash for use as a node ID suffix.

    Args:
        text: Input string to hash.

    Returns:
        12-character hex digest.
    """
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def normalize_text(text: str) -> str:
    """Normalize text: lowercase, strip special characters, collapse whitespace.

    Args:
        text: Raw input text.

    Returns:
        Cleaned, lowercased text.
    """
    text = re.sub(r"[^\w\s]", "", str(text).lower().strip())
    return re.sub(r"\s+", " ", text).strip()


def make_lemma_key(text: str) -> str:
    """Generate a POS-prefixed lemma key for entity deduplication.

    Adapted from Strwythura's `tokenize_lemma` pattern.
    Only keeps NOUN, ADJ, VERB tokens for meaningful keys.

    Examples:
        "Convolutional Neural Network" → "NOUN.convolutional ADJ.neural NOUN.network"
        "CNN"                          → "NOUN.cnn"
        "akurasi"                      → "NOUN.akurasi"

    Args:
        text: Entity surface text.

    Returns:
        Lemma key string, or normalized text if no valid POS found.
    """
    nlp = get_nlp()
    doc = nlp(str(text).strip())
    parts = []
    for tok in doc:
        # Merge PROPN into NOUN for consistency
        pos = "NOUN" if tok.pos_ in ("PROPN", "NOUN") else tok.pos_
        if pos in ("NOUN", "ADJ", "VERB"):
            parts.append(f"{pos}.{tok.lemma_.lower()}")
    return " ".join(parts) if parts else normalize_text(text)


def safe_str(value, default: str = "") -> str:
    """Safely convert a value to string, handling NaN and None.

    Args:
        value: Any value that might be NaN, None, or a valid string.
        default: Default to return for invalid values.

    Returns:
        Clean string or default.
    """
    s = str(value).strip()
    if s.lower() in ("nan", "none", ""):
        return default
    return s


def truncate(text: str, max_len: int = 2000) -> str:
    """Truncate text to max_len characters for API payloads.

    Args:
        text: Input text.
        max_len: Maximum character count.

    Returns:
        Truncated text.
    """
    return text[:max_len] if len(text) > max_len else text
