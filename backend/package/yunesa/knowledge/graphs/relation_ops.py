"""
graph_ops.py — UNESA Academic Knowledge Graph Operations
==========================================================
Graph manipulation, relation canonicalization, edge property merging, and deduplication.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any
import networkx as nx

from yunesa.knowledge.utils.text_processing import (
    safe_str,
    normalize_text,
    canonical_relation,
)


def has_relation(graph: nx.MultiDiGraph, source: str, target: str, relation: str) -> bool:
    relation = canonical_relation(relation)
    if not graph.has_edge(source, target):
        return False
    for edge_data in graph.get_edge_data(source, target, default={}).values():
        if canonical_relation(edge_data.get("relation")) == relation:
            return True
    return False


def _edge_key_for_relation(graph: nx.MultiDiGraph, source: str, target: str, relation: str) -> Any | None:
    relation = canonical_relation(relation)
    for key, edge_data in graph.get_edge_data(source, target, default={}).items():
        if canonical_relation(edge_data.get("relation")) == relation:
            return key
    return None


def _unique_text_values(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                add(item)
            return
        text = safe_str(value)
        if not text:
            return
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                add(parsed)
                return
        parts = text.split(" | ") if " | " in text and not text.lstrip().startswith("{") else [text]
        for part in parts:
            item = part.strip()
            key = normalize_text(item)
            if item and key not in seen:
                seen.add(key)
                result.append(item)

    for value in values:
        add(value)
    return result


def _decode_provenance_values(*values: Any) -> list[Any]:
    decoded: list[Any] = []
    seen: set[str] = set()

    def add(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, list):
            for nested in item:
                add(nested)
            return
        if isinstance(item, str):
            text = item.strip()
            if not text:
                return
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
            add(parsed)
            return
        key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            decoded.append(item)

    for value in values:
        add(value)
    return decoded


def _encode_provenance_values(values: list[Any]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return json.dumps(values[0], ensure_ascii=False, default=str)
    return json.dumps(values, ensure_ascii=False, default=str)


def _score_values(*values: Any) -> list[float]:
    scores: list[float] = []
    for value in values:
        for item in _unique_text_values(value):
            try:
                scores.append(float(item))
            except ValueError:
                continue
    return scores


def _normalise_edge_evidence(data: dict[str, Any]) -> None:
    sources = _unique_text_values(data.get("sources"), data.get("source"))
    match_types = _unique_text_values(data.get("match_types"), data.get("match_type"))
    matched_texts = _unique_text_values(data.get("matched_texts"), data.get("matched_text"))
    provenances = _decode_provenance_values(data.get("provenances"), data.get("provenance"))
    scores = _score_values(data.get("scores"), data.get("score"))

    if sources:
        joined = " | ".join(sources)
        data["source"] = joined
        data["sources"] = joined
    if match_types:
        joined = " | ".join(match_types)
        data["match_type"] = joined
        data["match_types"] = joined
    if matched_texts:
        joined = " | ".join(matched_texts)
        data["matched_text"] = joined
        data["matched_texts"] = joined
    if provenances:
        encoded = _encode_provenance_values(provenances)
        data["provenance"] = encoded
        data["provenances"] = encoded
    if scores:
        data["score"] = max(scores)
        data["scores"] = " | ".join(f"{score:g}" for score in sorted(set(scores), reverse=True))

    evidence_count = max(
        [int(data.get("evidence_count") or 0), 1]
        + [len(values) for values in (sources, match_types, matched_texts, provenances) if values]
    )
    data["evidence_count"] = evidence_count


def _merge_edge_properties(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    relation = canonical_relation(incoming.get("relation") or existing.get("relation"))
    existing["relation"] = relation

    for key, value in incoming.items():
        if key in {
            "relation",
            "source",
            "sources",
            "match_type",
            "match_types",
            "matched_text",
            "matched_texts",
            "provenance",
            "provenances",
            "score",
            "scores",
            "evidence_count",
        }:
            continue
        if not safe_str(existing.get(key)) and safe_str(value):
            existing[key] = value
        elif key in {"paper_ids", "paper_titles", "raw_labels", "ieee_uris"}:
            merged = _unique_text_values(existing.get(key), value)
            existing[key] = merged

    existing_sources = _unique_text_values(existing.get("sources"), existing.get("source"))
    incoming_sources = _unique_text_values(incoming.get("sources"), incoming.get("source"))
    existing_match_types = _unique_text_values(existing.get("match_types"), existing.get("match_type"))
    incoming_match_types = _unique_text_values(incoming.get("match_types"), incoming.get("match_type"))
    existing_matched = _unique_text_values(existing.get("matched_texts"), existing.get("matched_text"))
    incoming_matched = _unique_text_values(incoming.get("matched_texts"), incoming.get("matched_text"))
    existing_provenance = _decode_provenance_values(existing.get("provenances"), existing.get("provenance"))
    incoming_provenance = _decode_provenance_values(incoming.get("provenances"), incoming.get("provenance"))
    scores = _score_values(existing.get("scores"), existing.get("score"), incoming.get("scores"), incoming.get("score"))

    if existing_sources or incoming_sources:
        joined = " | ".join(_unique_text_values(existing_sources, incoming_sources))
        existing["source"] = joined
        existing["sources"] = joined
    if existing_match_types or incoming_match_types:
        joined = " | ".join(_unique_text_values(existing_match_types, incoming_match_types))
        existing["match_type"] = joined
        existing["match_types"] = joined
    if existing_matched or incoming_matched:
        joined = " | ".join(_unique_text_values(existing_matched, incoming_matched))
        existing["matched_text"] = joined
        existing["matched_texts"] = joined
    if existing_provenance or incoming_provenance:
        merged_provenance = _decode_provenance_values(existing_provenance, incoming_provenance)
        encoded = _encode_provenance_values(merged_provenance)
        existing["provenance"] = encoded
        existing["provenances"] = encoded
    if scores:
        existing["score"] = max(scores)
        existing["scores"] = " | ".join(f"{score:g}" for score in sorted(set(scores), reverse=True))

    _normalise_edge_evidence(existing)


def add_or_merge_relation(
    graph: nx.MultiDiGraph,
    source_node: str,
    target_node: str,
    relation: str,
    **properties: Any,
) -> bool:
    """Add one canonical edge per source-target-relation and merge evidence."""
    relation = canonical_relation(relation)
    incoming = {"relation": relation, **properties}
    _normalise_edge_evidence(incoming)

    edge_key = _edge_key_for_relation(graph, source_node, target_node, relation)
    if edge_key is None:
        graph.add_edge(source_node, target_node, **incoming)
        return True

    edge_data = graph[source_node][target_node][edge_key]
    _merge_edge_properties(edge_data, incoming)
    return False


def deduplicate_graph_relations(graph: nx.MultiDiGraph) -> int:
    """Merge accidental parallel edges that share source, target, and relation."""
    first_edge_by_signature: dict[tuple[str, str, str], tuple[Any, dict[str, Any]]] = {}
    merged = 0
    for source, target, key, data in list(graph.edges(keys=True, data=True)):
        relation = canonical_relation(data.get("relation", "RELATED_TO"))
        data["relation"] = relation
        signature = (source, target, relation)
        if signature not in first_edge_by_signature:
            _normalise_edge_evidence(data)
            first_edge_by_signature[signature] = (key, data)
            continue
        _, existing = first_edge_by_signature[signature]
        _merge_edge_properties(existing, data)
        graph.remove_edge(source, target, key=key)
        merged += 1
    return merged


def duplicate_relation_report(graph: nx.MultiDiGraph, *, limit: int = 20) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for source, target, key, data in graph.edges(keys=True, data=True):
        relation = canonical_relation(data.get("relation", "RELATED_TO"))
        groups[(source, target, relation)].append({"key": key, **data})

    duplicate_groups = {signature: rows for signature, rows in groups.items() if len(rows) > 1}
    examples: list[dict[str, Any]] = []
    for (source, target, relation), rows in sorted(
        duplicate_groups.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    )[:limit]:
        examples.append(
            {
                "source": source,
                "target": target,
                "relation": relation,
                "count": len(rows),
                "match_types": _unique_text_values(*(row.get("match_type") for row in rows)),
                "sources": _unique_text_values(*(row.get("source") for row in rows)),
                "matched_texts": _unique_text_values(*(row.get("matched_text") for row in rows)),
            }
        )

    return {
        "duplicate_relation_groups": len(duplicate_groups),
        "duplicate_relation_edges_extra": sum(len(rows) - 1 for rows in duplicate_groups.values()),
        "duplicate_relation_examples": examples,
    }
