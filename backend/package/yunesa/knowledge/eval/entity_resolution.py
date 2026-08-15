"""
entity_resolution.py — Entity Resolution Reporting & LLM Alias Review
=======================================================================
Audit entity resolution quality and generate conservative LLM-assisted candidate aliases.
"""

from __future__ import annotations

import os
import re
import json
from pathlib import Path
from collections import Counter, defaultdict
from typing import Any
import networkx as nx

from yunesa.knowledge.config import LLMAliasSuggestionConfig
from yunesa.knowledge.utils.text_processing import (
    safe_str,
    normalize_text,
    split_list_field,
)
from yunesa.knowledge.implementations.milvus import _node_label


def entity_resolution_report(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Summarize concept canonicalization quality and remaining review targets."""
    concept_nodes = [
        (node_id, data)
        for node_id, data in graph.nodes(data=True)
        if data.get("node_type") == "Concept"
    ]
    merged_nodes: list[dict[str, Any]] = []
    unresolved_local: list[dict[str, Any]] = []
    acronym_like: list[dict[str, Any]] = []

    for node_id, data in concept_nodes:
        raw_labels = split_list_field(data.get("raw_labels", ""))
        resolution_source = safe_str(data.get("resolution_source"))
        label = _node_label(data, node_id)
        concept_type = safe_str(data.get("concept_type"))
        canonical_key = safe_str(data.get("canonical_key"))
        if len({normalize_text(item) for item in raw_labels}) > 1:
            merged_nodes.append(
                {
                    "id": node_id,
                    "label": label,
                    "concept_type": concept_type,
                    "canonical_key": canonical_key,
                    "raw_labels": raw_labels,
                    "resolution_source": resolution_source,
                }
            )
        if canonical_key.startswith("local:"):
            unresolved_local.append(
                {
                    "id": node_id,
                    "label": label,
                    "concept_type": concept_type,
                    "source": safe_str(data.get("source")),
                    "canonical_key": canonical_key,
                }
            )
        if re.fullmatch(r"[A-Z0-9]{2,8}", safe_str(label)):
            acronym_like.append(
                {
                    "id": node_id,
                    "label": label,
                    "concept_type": concept_type,
                    "canonical_key": canonical_key,
                    "resolution_source": resolution_source,
                }
            )

    duplicate_candidates: list[dict[str, Any]] = []
    by_compact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node_id, data in concept_nodes:
        label = _node_label(data, node_id)
        compact = re.sub(r"[^a-z0-9]", "", normalize_text(label))
        if len(compact) >= 3:
            by_compact[compact].append(
                {
                    "id": node_id,
                    "label": label,
                    "concept_type": safe_str(data.get("concept_type")),
                    "canonical_key": safe_str(data.get("canonical_key")),
                }
            )
    for compact, items in by_compact.items():
        keys = {item["canonical_key"] for item in items}
        if len(items) > 1 and len(keys) > 1:
            duplicate_candidates.append({"compact_label": compact, "items": items[:10]})

    resolution_sources = Counter(
        data.get("resolution_source", "unknown") or "unknown"
        for _, data in concept_nodes
    )
    return {
        "concept_nodes": len(concept_nodes),
        "resolution_source_counts": dict(resolution_sources),
        "merged_canonical_nodes": len(merged_nodes),
        "merged_examples": merged_nodes[:20],
        "unresolved_local_concepts": len(unresolved_local),
        "unresolved_examples": unresolved_local[:30],
        "acronym_like_concepts": len(acronym_like),
        "acronym_like_examples": acronym_like[:20],
        "duplicate_candidate_groups": len(duplicate_candidates),
        "duplicate_candidate_examples": duplicate_candidates[:20],
    }


def _json_value_from_text(text: Any) -> Any:
    content = safe_str(text)
    if not content:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        content = fenced.group(1)
    for opener, closer in [("{", "}"), ("[", "]")]:
        start = content.find(opener)
        end = content.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except Exception:
                continue
    try:
        return json.loads(content)
    except Exception:
        return None


def _candidate_terms_for_llm_review(report: dict[str, Any], *, max_candidates: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in report.get("duplicate_candidate_examples") or []:
        for concept in item.get("items") or []:
            label = safe_str(concept.get("label"))
            key = normalize_text(label)
            if label and key not in seen:
                seen.add(key)
                candidates.append(
                    {
                        "label": label,
                        "concept_type": safe_str(concept.get("concept_type")),
                        "source": "duplicate_candidate",
                        "canonical_key": safe_str(concept.get("canonical_key")),
                    }
                )

    for item in report.get("acronym_like_examples") or []:
        label = safe_str(item.get("label"))
        key = normalize_text(label)
        if label and key not in seen:
            seen.add(key)
            candidates.append(
                {
                    "label": label,
                    "concept_type": safe_str(item.get("concept_type")),
                    "source": "acronym_like",
                    "canonical_key": safe_str(item.get("canonical_key")),
                }
            )

    for item in report.get("unresolved_examples") or []:
        label = safe_str(item.get("label"))
        key = normalize_text(label)
        if label and key not in seen:
            seen.add(key)
            candidates.append(
                {
                    "label": label,
                    "concept_type": safe_str(item.get("concept_type")),
                    "source": "unresolved_local",
                    "canonical_key": safe_str(item.get("canonical_key")),
                }
            )

    return candidates[:max_candidates]


def _groq_alias_suggestions(
    candidates: list[dict[str, Any]],
    *,
    model: str,
    min_confidence: float,
) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set.")
    try:
        from groq import Groq
    except ImportError as exc:
        raise ImportError("Install groq first.") from exc

    prompt = {
        "task": "Review unresolved academic KG concepts and propose canonical alias mappings.",
        "strict_rules": [
            "Return JSON only.",
            "Do not invent papers, results, authors, datasets, or metrics.",
            "Only propose exact synonyms, acronym expansions, metric canonicalization, or obvious spelling variants.",
            "Do not merge broader/narrower/related concepts. Mark those as related_only.",
            "For metric values such as 'AUC of 0.9', use canonical_label 'AUC' and action 'metric_value'.",
            "Confidence must be between 0 and 1.",
            f"Only mark review_status='auto_candidate' when confidence >= {min_confidence}.",
        ],
        "allowed_actions": ["exact_synonym", "metric_value", "spelling_variant", "related_only", "keep_separate", "noise"],
        "output_schema": {
            "suggestions": [
                {
                    "raw_label": "input label",
                    "suggested_canonical_label": "canonical label or empty",
                    "suggested_canonical_key": "snake_case key or empty",
                    "concept_type": "Model|Dataset|Metric|Method|Task|Domain|ResearchTopic|Result|Innovation|Problem",
                    "action": "one allowed action",
                    "confidence": 0.0,
                    "aliases": ["optional exact aliases"],
                    "review_status": "auto_candidate|needs_review|reject",
                    "rationale": "short factual reason",
                }
            ]
        },
        "candidates": candidates,
    }
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an entity-resolution reviewer for an academic knowledge graph. "
                    "You are conservative: exact synonyms can merge, related concepts cannot."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=1800,
    )
    parsed = _json_value_from_text(response.choices[0].message.content)
    if isinstance(parsed, list):
        parsed = {"suggestions": parsed}
    if not isinstance(parsed, dict):
        parsed = {"suggestions": [], "parse_error": safe_str(response.choices[0].message.content)}
    parsed.setdefault("suggestions", [])
    return parsed


def generate_llm_alias_suggestions(
    report: dict[str, Any],
    *,
    config: LLMAliasSuggestionConfig | None = None,
) -> dict[str, Any]:
    """Generate LLM-assisted alias suggestions from an entity resolution report."""
    config = config or LLMAliasSuggestionConfig.from_env()
    provider = normalize_text(config.provider)
    candidates = _candidate_terms_for_llm_review(report, max_candidates=config.max_candidates)
    suggestions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for start in range(0, len(candidates), max(1, config.batch_size)):
        batch = candidates[start : start + max(1, config.batch_size)]
        if not batch:
            continue
        try:
            if provider == "groq":
                result = _groq_alias_suggestions(
                    batch,
                    model=config.model,
                    min_confidence=config.min_confidence_for_auto_candidate,
                )
            else:
                raise ValueError(f"Unsupported entity resolution LLM provider: {config.provider}")
            for item in result.get("suggestions") or []:
                if isinstance(item, dict):
                    suggestions.append(item)
        except Exception as exc:
            errors.append(
                {
                    "batch_start": start,
                    "batch_size": len(batch),
                    "error_type": type(exc).__name__,
                    "error": safe_str(exc),
                }
            )

    return {
        "provider": config.provider,
        "model": config.model,
        "candidate_count": len(candidates),
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
        "errors": errors,
        "policy": {
            "auto_candidate_threshold": config.min_confidence_for_auto_candidate,
            "auto_merge": False,
            "requires_human_review": True,
        },
    }


def write_llm_alias_suggestions(
    report_path: Path,
    output_path: Path,
    *,
    config: LLMAliasSuggestionConfig | None = None,
) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = generate_llm_alias_suggestions(report, config=config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result
