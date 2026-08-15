"""
base.py — Abstract Base Class & Normalizers for Knowledge Graph Extractors
=============================================================================
Defines the GraphExtractor ABC contract and extraction result normalizer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GraphExtractor(ABC):
    """Abstract Base Class for all Graph Entity & Relation Extractors."""

    extractor_type: str

    def __init__(self, options: dict[str, Any] | None = None):
        self.options = options or {}

    @abstractmethod
    async def extract(self, input_data: Any, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Extract entities and relations (triples) from input data."""
        pass

    def validate_options(self) -> None:
        """Validate extractor options configuration."""
        return None


def normalize_extraction_result(result: dict[str, Any], extractor_type: str) -> dict[str, Any]:
    """Normalize extracted entities and relations into a standardized graph payload."""
    if not isinstance(result, dict):
        raise ValueError("extraction_result must be a dict object")

    entities = result.get("entities") or []
    relations = result.get("relations") or []
    if not isinstance(entities, list) or not isinstance(relations, list):
        raise ValueError("entities and relations must be lists")

    return {
        "extractor_type": extractor_type,
        "entities": entities,
        "relations": relations,
        "count_entities": len(entities),
        "count_relations": len(relations),
    }
