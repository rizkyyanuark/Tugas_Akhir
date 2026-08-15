"""
academic_ner.py — GLiNER / GLiREL Zero-Shot NER Extractor
===========================================================
Extracts academic entities and relations from text using GLiNER & GLiREL models.
"""

from __future__ import annotations

from typing import Any
from yunesa.knowledge.graphs.extractors.base import GraphExtractor, normalize_extraction_result
from yunesa.knowledge.parser.ner_extraction import extract_academic_elements_with_gliner_glirel


class AcademicNERExtractor(GraphExtractor):
    """Extracts entities and relations from paper text using GLiNER & GLiREL."""

    extractor_type: str = "ner"

    async def extract(self, input_data: Any, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run GLiNER and GLiREL extraction on text or publication record."""
        text = str(input_data or "")
        extracted = extract_academic_elements_with_gliner_glirel(text)
        
        entities = [
            {"id": f"{e.get('type', 'Entity')}::{e.get('name')}", "type": e.get("type"), "name": e.get("name")}
            for e in extracted.get("entities", [])
        ]
        relations = [
            {"source": r.get("source"), "relation": r.get("relation"), "target": r.get("target")}
            for r in extracted.get("relations", [])
        ]

        raw_result = {"entities": entities, "relations": relations}
        return normalize_extraction_result(raw_result, self.extractor_type)
