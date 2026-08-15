"""
utils.py — UNESA Academic Knowledge Graph Text & ID Utilities
================================================================
Text normalization, slugification, document text building, and ID generators.
"""

from __future__ import annotations

import re
import json
import hashlib
from typing import Any
import pandas as pd

from yunesa.knowledge.constants import (
    RELATION_ALIASES,
    CONCEPT_TYPES,
)


def safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, float) and pd.isna(value):
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    return text


def normalize_text(text: Any) -> str:
    text = safe_str(text).lower()
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"[_/]+", " ", text)
    text = re.sub(r"[^a-z0-9%+.\- ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text


def slugify(text: Any) -> str:
    norm = normalize_text(text)
    norm = re.sub(r"[^a-z0-9]+", "_", norm).strip("_")
    return norm or "unknown"


def stable_id(prefix: str, value: Any) -> str:
    raw = safe_str(value)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def split_list_field(value: Any) -> list[str]:
    text = safe_str(value)
    if not text:
        return []

    # Handle JSON-like arrays from some exports.
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text.replace("'", '"'))
            if isinstance(parsed, list):
                return [safe_str(item) for item in parsed if safe_str(item)]
        except json.JSONDecodeError:
            pass

    parts = re.split(r"\s*[;,|]\s*", text)
    seen: set[str] = set()
    cleaned: list[str] = []
    for part in parts:
        item = safe_str(part)
        key = normalize_text(item)
        if item and len(key) >= 2 and key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


def canonical_document_type(value: Any) -> str:
    doc = normalize_text(value)
    if not doc:
        return "article"
    mapping = {
        "artikel": "article",
        "article": "article",
        "journal article": "article",
        "journal-article": "article",
        "conference": "conference paper",
        "conference paper": "conference paper",
        "conference-paper": "conference paper",
        "proceedings article": "conference paper",
        "proceedings-article": "conference paper",
    }
    return mapping.get(doc, doc.replace("-", " "))


def canonical_venue_name(value: Any) -> str:
    """Return a clean, normalized canonical journal/venue name."""
    venue = re.sub(r"\s+", " ", safe_str(value)).strip(" ,.-")
    if not venue:
        return ""

    # 1. Filter out known Google Scholar scraping garbage / non-venues
    garbage_patterns = [
        r"^\(No Title\)",
        r"^KATA PENGANTAR\b",
        r"^BOARD OF EDITOR\b",
        r"^DAFTAR ISI\b",
    ]
    for pattern in garbage_patterns:
        if re.search(pattern, venue, re.IGNORECASE):
            return ""

    # 2. Strip trailing zeros and years like ", 0" or ", 2022" or ", 0, 2023"
    venue = re.sub(r",\s*\d+\s*$", "", venue)
    venue = re.sub(r",\s*(?:19|20)\d{2}\s*$", "", venue)
    venue = re.sub(r",\s*\d+\s*$", "", venue)

    # 3. Strip Volume (Issue), Pages: e.g., " 15 (4), 473-479" or " 8 (2), 561-570" or " 3 (01), 20-27"
    venue = re.sub(r"\s+\d+\s*\([^)]*\)\s*(?:,\s*[\d\-–]+\s*)?.*$", "", venue)

    # 4. Strip standalone volume/pages: e.g. " 15, 473-479" or ", 473-479"
    venue = re.sub(r"\s+\d+\s*,\s*[\d\-–]+\s*.*$", "", venue)
    venue = re.sub(r",\s*[\d\-–]+\s*.*$", "", venue)

    # 5. Strip trailing year or page numbers at the very end
    venue = re.sub(r"\s+(?:19|20)\d{2}\b.*$", "", venue)
    venue = re.sub(r",\s*\d+\s*$", "", venue)

    # 6. Final whitespace & punctuation trim
    venue = re.sub(r"\s+", " ", venue).strip(" ,.-:;")

    # If the remaining string is too short or just numbers, discard
    if len(venue) < 3 or venue.isdigit():
        return ""

    return venue


def canonical_relation(value: Any) -> str:
    """Map legacy/internal relation labels into the thesis ontology vocabulary."""
    relation = re.sub(r"[^A-Za-z0-9_]", "_", safe_str(value).upper()).strip("_")
    if not relation:
        return "RELATED_TO"
    return RELATION_ALIASES.get(relation, relation)


def canonical_concept_type(value: Any, *, fallback_label: Any = "") -> str:
    concept_type = safe_str(value)
    aliases = {
        "Topic": "ResearchTopic",
        "Research Topic": "ResearchTopic",
        "Field": "Domain",
        "ApplicationDomain": "Domain",
        "Application Domain": "Domain",
        "Results": "Result",
        "Main Result": "Result",
    }
    concept_type = aliases.get(concept_type, concept_type)

    label_inferred = ""
    if safe_str(fallback_label):
        from yunesa.knowledge.utils.concept_resolver import infer_concept_type
        label_inferred = infer_concept_type(safe_str(fallback_label))

    if label_inferred in {"Model", "Dataset", "Metric"}:
        return label_inferred
    if concept_type in CONCEPT_TYPES:
        return concept_type
    return label_inferred if label_inferred in CONCEPT_TYPES else "ResearchTopic"


def field_value(row: pd.Series | dict[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        if isinstance(row, pd.Series):
            if name in row:
                value = safe_str(row.get(name))
                if value:
                    return value
        elif name in row:
            value = safe_str(row.get(name))
            if value:
                return value
    return default


def academic_document_id(paper: pd.Series | dict[str, Any]) -> str:
    paper_id = field_value(paper, "paper_id", "id")
    doi = field_value(paper, "doi", "DOI")
    title = field_value(paper, "title", "Title")
    if paper_id:
        return safe_str(paper_id)
    if doi:
        return stable_id("doc", doi)
    return stable_id("doc", title)


def academic_document_text(paper: pd.Series | dict[str, Any], max_chars: int | None = None) -> str:
    title = field_value(paper, "title", "Title")
    tldr = field_value(paper, "tldr", "TLDR")
    abstract = field_value(paper, "abstract", "Abstract")
    keywords = ", ".join(split_list_field(field_value(paper, "keywords", "Keywords")))
    text = "\n".join(
        part
        for part in [
            f"Title: {title}" if title else "",
            f"TLDR: {tldr}" if tldr else "",
            f"Abstract: {abstract}" if abstract else "",
            f"Keywords: {keywords}" if keywords else "",
        ]
        if part
    )
    if max_chars and len(text) > max_chars:
        return text[:max_chars].rsplit(" ", 1)[0].strip()
    return text


def content_hash(text: Any) -> str:
    return hashlib.md5(safe_str(text).encode("utf-8")).hexdigest()


def semantic_text_chunks(text: str, max_chars: int = 2024, overlap_chars: int = 50) -> list[str]:
    """Split academic text into lightweight semantic-ish chunks without external tokenizers."""
    text = re.sub(r"\s+", " ", safe_str(text)).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = sentence
        while len(current) > max_chars:
            chunks.append(current[:max_chars].strip())
            current = current[max(0, max_chars - overlap_chars) :].strip()
    if current:
        chunks.append(current)
    return chunks


def _looks_like_noise(label: str) -> bool:
    text = safe_str(label)
    norm = normalize_text(text)
    if len(norm) < 3 or len(norm) > 90:
        return True
    if norm.count(".") >= 3:
        return True
    if re.search(r"(copyright|download|license|ieee terms|page \d+)", norm):
        return True
    if len(re.findall(r"[a-z]", norm)) < 3:
        return True
    if len(norm.split()) > 8:
        return True
    return False
