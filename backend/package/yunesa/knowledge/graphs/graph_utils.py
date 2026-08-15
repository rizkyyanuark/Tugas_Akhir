"""
graph_utils.py — Graph Payload & Cypher Formatting Utilities
=============================================================
Helper functions for graph ID computation, entity normalization, and Cypher query formatting.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any


def normalize_entity_name(name: str) -> str:
    """Normalize entity name string for canonical comparisons."""
    if not name:
        return ""
    text = str(name).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def compute_entity_id(entity_type: str, entity_name: str) -> str:
    """Compute deterministic entity ID string."""
    norm_type = (entity_type or "KGNode").strip()
    norm_name = normalize_entity_name(entity_name)
    digest = hashlib.md5(f"{norm_type}:{norm_name}".encode("utf-8")).hexdigest()[:12]
    return f"{norm_type}::{digest}"


def compute_triple_id(src_id: str, rel_type: str, tgt_id: str) -> str:
    """Compute deterministic triple/edge ID string."""
    raw = f"{src_id}->{rel_type}->{tgt_id}"
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]
    return f"rel::{digest}"


def cypher_merge_entity_statement(label: str, name: str, props: dict[str, Any] | None = None) -> str:
    """Generate Cypher MERGE query string for an entity node."""
    safe_label = re.sub(r"[^\w]", "", label or "Entity")
    return f"MERGE (n:{safe_label} {{name: $name}}) SET n += $props RETURN n"
