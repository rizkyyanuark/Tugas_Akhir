"""
academic_tabular.py — Tabular Supabase Graph Extractor
======================================================
Extracts Lecturer, Publication, and Author relation entities from Supabase tabular data.
"""

from __future__ import annotations

from typing import Any
from yunesa.knowledge.graphs.extractors.base import GraphExtractor, normalize_extraction_result


class AcademicTabularExtractor(GraphExtractor):
    """Extracts Academic Knowledge Graph entities from tabular DataFrames (Lecturers & Papers)."""

    extractor_type: str = "tabular"

    async def extract(self, input_data: Any, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Extract lecturer and publication entities from dataframes or dicts."""
        entities: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []

        if isinstance(input_data, dict):
            df_papers = input_data.get("papers")
            df_lecturers = input_data.get("lecturers")

            if df_papers is not None and hasattr(df_papers, "to_dict"):
                for row in df_papers.to_dict(orient="records"):
                    paper_id = str(row.get("id") or row.get("paper_id") or "").strip()
                    if paper_id:
                        entities.append({
                            "id": f"Paper::{paper_id}",
                            "type": "Publication",
                            "name": row.get("title") or paper_id,
                            "attributes": row,
                        })

            if df_lecturers is not None and hasattr(df_lecturers, "to_dict"):
                for row in df_lecturers.to_dict(orient="records"):
                    nip = str(row.get("nip") or row.get("nidn") or "").strip()
                    if nip:
                        entities.append({
                            "id": f"Lecturer::{nip}",
                            "type": "Lecturer",
                            "name": row.get("nama_dosen") or nip,
                            "attributes": row,
                        })

        raw_result = {"entities": entities, "relations": relations}
        return normalize_extraction_result(raw_result, self.extractor_type)
