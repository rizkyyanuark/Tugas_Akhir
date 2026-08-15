"""
ieee_semantic.py — IEEE Thesaurus & Taxonomy Semantic Index
============================================================
Parses IEEE SKOS RDF thesaurus and taxonomy graphs into in-memory lookup indices.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import rdflib
    from rdflib import RDFS, SKOS, URIRef
except ImportError:
    rdflib = None
    SKOS = None
    RDFS = None
    URIRef = None

from yunesa.knowledge.utils.text_processing import normalize_text, safe_str

logger = logging.getLogger(__name__)


def _looks_like_noise(text: str) -> bool:
    """Check if label looks like a non-semantic ID or numeric string."""
    val = safe_str(text).strip()
    if not val or len(val) <= 1:
        return True
    if val.isdigit() or val.replace(".", "").isdigit():
        return True
    return False


class IeeeSemanticIndex:
    """SKOS-based semantic index for IEEE Thesaurus & Taxonomy."""

    def __init__(self) -> None:
        self.label_index: dict[str, dict[str, str]] = {}
        self.uri_to_label: dict[str, str] = {}
        self.uri_relations: list[tuple[str, str, str]] = []
        self.source_counts: Counter[str] = Counter()
        self._sorted_labels: list[tuple[str, dict[str, str]]] | None = None

    @classmethod
    def from_files(
        cls,
        thesaurus_path: Path,
        taxonomy_path: Path | None = None,
        max_terms: int | None = None,
    ) -> "IeeeSemanticIndex":
        if rdflib is None:
            raise ImportError("rdflib is required to load IEEE taxonomy/thesaurus files.")

        index = cls()
        if thesaurus_path and thesaurus_path.exists():
            index._load_graph(thesaurus_path, source="ieee_thesaurus", max_terms=max_terms)
        if taxonomy_path and taxonomy_path.exists():
            index._load_graph(taxonomy_path, source="ieee_taxonomy", max_terms=max_terms)
        return index

    def _detect_format(self, path: Path) -> str | None:
        ext = path.suffix.lower()
        if ext in (".xml", ".rdf", ".owl"):
            return "xml"
        if ext in (".ttl", ".turtle"):
            return "ttl"
        if ext in (".jsonld", ".json"):
            return "json-ld"
        if ext in (".nt", ".ntriples"):
            return "nt"
        try:
            head = path.read_text(encoding="utf-8", errors="ignore")[:300]
            if "<?xml" in head or "<rdf:RDF" in head:
                return "xml"
            if "@prefix" in head or "@base" in head:
                return "ttl"
        except Exception:
            pass
        return None

    def _load_graph(self, path: Path, source: str, max_terms: int | None) -> None:
        graph = rdflib.Graph()
        detected_fmt = self._detect_format(path)
        
        # Build priority list of RDF formats to attempt
        formats_to_try: list[str | None] = []
        if detected_fmt:
            formats_to_try.append(detected_fmt)
        for fallback in ["xml", "ttl", "json-ld", "nt"]:
            if fallback not in formats_to_try:
                formats_to_try.append(fallback)
        formats_to_try.append(None)  # Auto-guess without format argument

        last_error: Exception | None = None
        for fmt in formats_to_try:
            try:
                if fmt:
                    graph.parse(str(path), format=fmt)
                else:
                    graph.parse(str(path))
                break
            except Exception as exc:
                last_error = exc
                continue
        else:
            if last_error:
                logger.error("Failed to parse RDF graph %s with formats %s: %s", path, formats_to_try, last_error)
                raise last_error

        self._sorted_labels = None
        label_predicates = [SKOS.prefLabel, SKOS.altLabel, RDFS.label]
        loaded = 0

        for subject in set(graph.subjects()):
            labels = []
            for predicate in label_predicates:
                labels.extend(str(label) for label in graph.objects(subject, predicate))

            if not labels:
                continue

            canonical = next((label for label in labels if not _looks_like_noise(label)), "")
            if not canonical:
                canonical = labels[0]

            subj_str = str(subject)
            self.uri_to_label[subj_str] = canonical

            for label in labels:
                norm = normalize_text(label)
                if norm and norm not in self.label_index:
                    self.label_index[norm] = {
                        "canonical_label": canonical,
                        "ieee_uri": subj_str,
                        "source": source,
                    }

            self.source_counts[source] += 1
            loaded += 1
            if max_terms and loaded >= max_terms:
                break

        # Load SKOS hierarchy relations (broader, narrower, related)
        for s, p, o in graph.triples((None, None, None)):
            pred_str = str(p)
            if "skos/core#" in pred_str or "rdf-schema#" in pred_str:
                self.uri_relations.append((str(s), pred_str.split("#")[-1], str(o)))

    def resolve(self, text: str) -> dict[str, str] | None:
        """Look up canonical IEEE concept for a query term."""
        norm = normalize_text(text)
        return self.label_index.get(norm)

    def match_label(self, text: str) -> dict[str, str] | None:
        """Alias for resolve() to support concept extraction callers."""
        return self.resolve(text)

    def match_text(self, text: str, max_matches: int = 10) -> list[dict[str, Any]]:
        """Extract matching IEEE terms from a free-text string."""
        if not text or not self.label_index:
            return []

        matches: list[dict[str, Any]] = []
        text_norm = normalize_text(text)

        if self._sorted_labels is None:
            self._sorted_labels = sorted(
                self.label_index.items(),
                key=lambda x: len(x[0]),
                reverse=True,
            )

        seen_uris: set[str] = set()
        for norm_label, record in self._sorted_labels:
            if len(norm_label) < 4:
                continue
            if norm_label in text_norm:
                uri = record.get("ieee_uri", "")
                if uri and uri in seen_uris:
                    continue
                if uri:
                    seen_uris.add(uri)
                matches.append({
                    "label": record.get("canonical_label", norm_label),
                    "matched_label": norm_label,
                    "uri": uri,
                    "ieee_uri": uri,
                    "source": record.get("source", "ieee_thesaurus"),
                    "match": norm_label,
                    "match_type": "ieee_text",
                })
                if len(matches) >= max_matches:
                    break
        return matches

    def summary(self) -> dict[str, Any]:
        """Return summary statistics of the loaded IEEE index."""
        return {
            "labels": len(self.label_index),
            "concept_uris": len(self.uri_to_label),
            "relations": len(self.uri_relations),
            "source_counts": dict(self.source_counts),
        }
