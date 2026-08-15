"""
ieee_concept.py — IEEE Thesaurus & Concept Extractor
======================================================
Maps text keywords and concepts to IEEE Thesaurus taxonomy terms.
"""

from __future__ import annotations

from typing import Any
from yunesa.knowledge.graphs.extractors.base import GraphExtractor, normalize_extraction_result
from yunesa.knowledge.utils.concept_resolver import AcademicConceptResolver


class IEEEConceptExtractor(GraphExtractor):
    """Extracts concept entities mapped against IEEE Thesaurus vocabulary."""

    extractor_type: str = "concept"

    def __init__(self, options: dict[str, Any] | None = None):
        super().__init__(options)
        self.resolver = AcademicConceptResolver()

    async def extract(self, input_data: Any, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Resolve concept terms to canonical IEEE Thesaurus terms."""
        terms = input_data if isinstance(input_data, list) else [str(input_data or "")]
        entities: list[dict[str, Any]] = []

        for term in terms:
            resolved = self.resolver.resolve_concept(str(term))
            if resolved:
                entities.append({
                    "id": f"Concept::{resolved.get('canonical_term', term)}",
                    "type": "Concept",
                    "name": resolved.get("canonical_term", term),
                    "attributes": resolved,
                })

        raw_result = {"entities": entities, "relations": []}
        return normalize_extraction_result(raw_result, self.extractor_type)
