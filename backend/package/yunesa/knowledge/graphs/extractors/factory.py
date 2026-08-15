"""
factory.py — Graph Extractor Factory
====================================
Factory for creating registered graph extractor instances.
"""

from __future__ import annotations

from typing import Any
from yunesa.knowledge.graphs.extractors.base import GraphExtractor
from yunesa.knowledge.graphs.extractors.academic_tabular import AcademicTabularExtractor
from yunesa.knowledge.graphs.extractors.academic_ner import AcademicNERExtractor
from yunesa.knowledge.graphs.extractors.ieee_concept import IEEEConceptExtractor


class GraphExtractorFactory:
    """Registry factory for Graph Extractor classes."""

    _registry: dict[str, type[GraphExtractor]] = {
        "tabular": AcademicTabularExtractor,
        "ner": AcademicNERExtractor,
        "concept": IEEEConceptExtractor,
    }

    @classmethod
    def create(cls, extractor_type: str | None, options: dict[str, Any] | None = None) -> GraphExtractor:
        """Create an extractor instance by type name."""
        normalized_type = (extractor_type or "tabular").lower()
        extractor_class = cls._registry.get(normalized_type)
        if not extractor_class:
            raise ValueError(f"Unsupported extractor type: {extractor_type!r}. Available: {list(cls._registry.keys())}")
        extractor = extractor_class(options or {})
        extractor.validate_options()
        return extractor

    @classmethod
    def register(cls, extractor_type: str, extractor_class: type[GraphExtractor]) -> None:
        """Register a new extractor class."""
        cls._registry[extractor_type.lower()] = extractor_class

    @classmethod
    def supported_types(cls) -> list[str]:
        """Return list of registered extractor type names."""
        return list(cls._registry.keys())
