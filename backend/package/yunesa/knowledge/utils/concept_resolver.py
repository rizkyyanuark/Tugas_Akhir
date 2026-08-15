"""
concept_resolver.py — Academic Concept Identity Resolver
===========================================================
Metric value parsing, curated alias lookup, IEEE URI matching, and regex concept extraction.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any, Iterable
import pandas as pd

try:
    import yaml
except ImportError:
    yaml = None

from yunesa.knowledge.constants import (
    DEFAULT_CONCEPT_ALIASES,
    MODEL_PATTERNS,
    DATASET_PATTERNS,
    METRIC_PATTERNS,
    TASK_PATTERNS,
    METHOD_PATTERNS,
    INNOVATION_PATTERNS,
    RESULT_PATTERNS,
    DOMAIN_PATTERNS,
    PROBLEM_PATTERNS,
    GENERIC_IEEE_TEXT_TERMS,
)
from yunesa.knowledge.utils.text_processing import (
    safe_str,
    normalize_text,
    slugify,
    canonical_concept_type,
    field_value,
    split_list_field,
)
from yunesa.knowledge.utils.ieee_semantic import IeeeSemanticIndex


def _metric_label_from_base(base: str) -> str:
    mapping = {
        "roc auc": "AUC",
        "auc": "AUC",
        "accuracy": "Accuracy",
        "precision": "Precision",
        "recall": "Recall",
        "f1": "F1-score",
        "f1-score": "F1-score",
        "f1 score": "F1-score",
        "rmse": "RMSE",
        "mae": "MAE",
        "flops": "FLOPs",
    }
    return mapping.get(normalize_text(base), safe_str(base))


def extract_metric_value(label: Any) -> dict[str, Any]:
    text = safe_str(label)
    norm = normalize_text(text)
    base_match = re.search(r"\b(roc auc|f1 score|f1-score|f1|auc|accuracy|precision|recall|rmse|mae|flops)\b", norm)
    if not base_match:
        return {}

    tail = norm[base_match.end() :]
    value_match = re.search(r"(\d+(?:\.\d+)?)\s*%", tail)
    unit = "%"
    if not value_match:
        value_match = re.search(
            r"\b(?:of|around|about|sebesar|=|:)\s*(0?\.\d+|1\.0+|\d+(?:\.\d+)?)\b",
            tail,
            flags=re.IGNORECASE,
        )
        unit = ""

    result = {
        "metric_base": normalize_text(base_match.group(1)).replace("f1 score", "f1-score"),
        "metric_label": _metric_label_from_base(base_match.group(1)),
    }
    if value_match:
        value_text = value_match.group(1)
        try:
            result["metric_value"] = float(value_text)
            result["metric_unit"] = unit
        except ValueError:
            pass
    return result


def _load_alias_records(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load curated concept aliases and merge them with built-in aliases."""
    records = json.loads(json.dumps(DEFAULT_CONCEPT_ALIASES))
    if not path or not path.exists():
        return records

    loaded: dict[str, Any] = {}
    try:
        if yaml is not None:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return records

    alias_records = loaded.get("aliases", loaded) if isinstance(loaded, dict) else {}
    if not isinstance(alias_records, dict):
        return records

    for key, value in alias_records.items():
        if not isinstance(value, dict):
            continue
        canonical_key = slugify(value.get("canonical_key") or key)
        aliases = [safe_str(item) for item in value.get("aliases", []) if safe_str(item)]
        canonical_label = safe_str(value.get("canonical_label") or value.get("label") or key)
        if canonical_label and canonical_label not in aliases:
            aliases.append(canonical_label)
        records[canonical_key] = {
            "canonical_label": canonical_label,
            "concept_type": safe_str(value.get("concept_type") or "ResearchTopic"),
            "aliases": aliases,
            "source": safe_str(value.get("source") or "curated_alias"),
        }
    return records


class AcademicConceptResolver:
    """Resolve raw concept labels into canonical KG identities."""

    def __init__(self, alias_path: Path | None = None) -> None:
        self.alias_path = alias_path
        self.alias_records = _load_alias_records(alias_path)
        self.alias_lookup: dict[str, dict[str, Any]] = {}
        for canonical_key, record in self.alias_records.items():
            aliases = list(record.get("aliases") or [])
            canonical_label = safe_str(record.get("canonical_label"))
            if canonical_label:
                aliases.append(canonical_label)
            for alias in aliases:
                norm = normalize_text(alias)
                if norm:
                    self.alias_lookup[norm] = {"canonical_key": canonical_key, **record}

    @classmethod
    def from_path(cls, alias_path: Path | None = None) -> "AcademicConceptResolver":
        return cls(alias_path=alias_path)

    def resolve(
        self,
        *,
        label: Any,
        concept_type: Any = "",
        ieee_uri: Any = "",
        source: Any = "",
    ) -> dict[str, Any]:
        raw_label = safe_str(label)
        norm = normalize_text(raw_label)
        inferred_type = canonical_concept_type(concept_type, fallback_label=raw_label)

        metric = extract_metric_value(raw_label)
        if metric and inferred_type == "Metric":
            canonical_label = metric["metric_label"]
            canonical_key = f"metric:{slugify(canonical_label)}"
            return {
                "raw_label": raw_label,
                "label": canonical_label,
                "canonical_label": canonical_label,
                "canonical_key": canonical_key,
                "concept_type": "Metric",
                "resolution_source": "metric_value_parser" if "metric_value" in metric else "metric_parser",
                **metric,
            }

        alias_record = self.alias_lookup.get(norm)
        if alias_record:
            resolved_type = canonical_concept_type(alias_record.get("concept_type"), fallback_label=raw_label)
            canonical_label = safe_str(alias_record.get("canonical_label") or raw_label)
            return {
                "raw_label": raw_label,
                "label": canonical_label,
                "canonical_label": canonical_label,
                "canonical_key": f"alias:{alias_record['canonical_key']}",
                "concept_type": resolved_type,
                "resolution_source": alias_record.get("source") or "curated_alias",
            }

        uri = safe_str(ieee_uri)
        if uri:
            canonical_key = f"ieee_label:{slugify(raw_label)}" if norm else f"ieee:{uri}"
            return {
                "raw_label": raw_label,
                "label": raw_label,
                "canonical_label": raw_label,
                "canonical_key": canonical_key,
                "concept_type": inferred_type,
                "resolution_source": safe_str(source) or "ieee_uri",
            }

        local_key = f"local:{inferred_type}:{slugify(norm or raw_label)}"
        return {
            "raw_label": raw_label,
            "label": raw_label,
            "canonical_label": raw_label,
            "canonical_key": local_key,
            "concept_type": inferred_type,
            "resolution_source": safe_str(source) or "local_fallback",
        }

    def summary(self) -> dict[str, Any]:
        return {
            "alias_records": len(self.alias_records),
            "alias_terms": len(self.alias_lookup),
            "alias_path": str(self.alias_path) if self.alias_path else "",
        }


def infer_concept_type(label: str, evidence_text: str = "") -> str:
    text = normalize_text(label)
    evidence = normalize_text(evidence_text)

    def has(patterns: Iterable[str]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    if has(MODEL_PATTERNS):
        return "Model"
    if has(DATASET_PATTERNS):
        return "Dataset"
    if has(METRIC_PATTERNS):
        return "Metric"
    if has(TASK_PATTERNS):
        return "Task"
    if has(METHOD_PATTERNS):
        return "Method"
    if has(INNOVATION_PATTERNS):
        return "Innovation"
    if has(RESULT_PATTERNS):
        return "Result"
    if has(DOMAIN_PATTERNS):
        return "Domain"
    if has(PROBLEM_PATTERNS):
        return "Problem"
    if text in evidence and any(re.search(pattern, evidence, flags=re.IGNORECASE) for pattern in DOMAIN_PATTERNS):
        return "ResearchTopic"
    return "ResearchTopic"


def extract_regex_concepts(text: str) -> list[dict[str, Any]]:
    """Extract high-value concepts not always covered by IEEE terms."""
    concepts: list[dict[str, Any]] = []
    norm = safe_str(text)

    named_patterns = {
        "Metric": [
            r"\b\d+(?:\.\d+)?\s*%\b",
            r"\b(?:accuracy|precision|recall|f1-score|f1|auc|roc auc|rmse|mae|flops)\b(?:\s+(?:of|around|about|sebesar))?\s*(?:\d+(?:\.\d+)?\s*%?|\d?\.\d+)(?=[\s,.;)]|$)",
            r"\b(?:accuracy|precision|recall|f1-score|f1|auc|roc auc|rmse|mae|flops)\b",
        ],
        "Dataset": [
            r"\bAPTOS\s*2019\b",
            r"\bImageNet\b",
            r"\bCIFAR-?10\b",
            r"\bCIFAR-?100\b",
            r"\bMNIST\b",
        ],
        "Model": [
            r"\bMobileViT-?[A-Z0-9]*\b",
            r"\bEfficientNet-?[A-Z0-9]*\b",
            r"\bIndoBERT\b",
            r"\bBiLSTM(?:[- ]BiGRU)?\b",
            r"\bXGBoost\b",
            r"\bLightGBM\b",
            r"\bCatBoost\b",
            r"\bSupport Vector Machine\b",
            r"\bSVM\b",
        ],
        "Result": [
            r"\bachiev(?:e|ed|es|ing)\s+[^.]{0,80}?\b\d+(?:\.\d+)?\s*%\b",
            r"\breduc(?:e|ed|es|ing|tion)\s+[^.]{0,80}?\b\d+(?:\.\d+)?\s*%\b",
            r"\bimprov(?:e|ed|es|ing|ement)\s+[^.]{0,80}?\b\d+(?:\.\d+)?\s*%\b",
        ],
        "Innovation": [
            r"\bhybrid\s+[A-Za-z0-9][A-Za-z0-9+/ _-]{2,80}?\bmodel\b",
            r"\bnovel\s+[A-Za-z0-9][A-Za-z0-9+/ _-]{2,80}?\b(?:method|framework|approach|model)\b",
        ],
    }

    seen: set[str] = set()
    for concept_type, patterns in named_patterns.items():
        for pattern in patterns:
            for match in re.finditer(pattern, norm, flags=re.IGNORECASE):
                label = match.group(0).strip(" .,-")
                key = normalize_text(label)
                if len(key) < 2 or key in seen:
                    continue
                seen.add(key)
                concepts.append(
                    {
                        "label": label,
                        "concept_type": concept_type,
                        "source": "regex",
                        "matched_label": label,
                        "uri": "",
                        "match_type": "regex",
                    }
                )
    return concepts


def _metric_base(label: Any) -> str:
    text = normalize_text(label)
    match = re.match(r"^(roc auc|f1 score|f1-score|f1|auc|accuracy|precision|recall|rmse|mae|flops)\b", text)
    if match and match.group(1) == "f1 score":
        return "f1-score"
    return match.group(1) if match else ""


def _metric_has_value(label: Any) -> bool:
    text = safe_str(label)
    return bool(
        re.search(r"\b(?:of|around|about|sebesar)\s*\d", text, flags=re.IGNORECASE)
        or re.search(r"\d+(?:\.\d+)?\s*%", text)
        or re.search(r"\b\d?\.\d+\b", text)
        or re.search(r"\b\d{2,}(?:\.\d+)?\b", text)
    )


def suppress_plain_metric_duplicates(concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop plain metric labels when a value-bearing version is already present."""
    valued_metric_bases = {
        base
        for concept in concepts
        if canonical_concept_type(concept.get("concept_type"), fallback_label=concept.get("label")) == "Metric"
        for base in [_metric_base(concept.get("label"))]
        if base and _metric_has_value(concept.get("label"))
    }
    if not valued_metric_bases:
        return concepts

    filtered: list[dict[str, Any]] = []
    for concept in concepts:
        concept_type = canonical_concept_type(concept.get("concept_type"), fallback_label=concept.get("label"))
        label = safe_str(concept.get("label"))
        base = _metric_base(label)
        is_plain_duplicate = concept_type == "Metric" and base in valued_metric_bases and not _metric_has_value(label)
        if not is_plain_duplicate:
            filtered.append(concept)
    return filtered


def extract_concepts_for_paper(
    paper: pd.Series,
    ieee_index: IeeeSemanticIndex,
    max_concepts: int = 14,
) -> list[dict[str, Any]]:
    title = field_value(paper, "title", "Title")
    abstract = field_value(paper, "abstract", "Abstract")
    tldr = field_value(paper, "tldr", "TLDR")
    keywords = split_list_field(field_value(paper, "keywords", "Keywords"))
    text = ". ".join([title, tldr, abstract, " ".join(keywords)])

    candidates: list[dict[str, Any]] = []

    for keyword in keywords:
        matched = ieee_index.match_label(keyword)
        if matched:
            candidates.append({**matched, "match": keyword, "match_type": "keyword_ieee"})
        else:
            candidates.append(
                {
                    "label": keyword,
                    "matched_label": keyword,
                    "uri": "",
                    "source": "author_keyword",
                    "match": keyword,
                    "match_type": "keyword_raw",
                }
            )

    candidates.extend(ieee_index.match_text(f"{title}. {tldr}", max_matches=max(6, max_concepts // 2)))
    candidates.extend(extract_regex_concepts(text))

    ranked: dict[str, dict[str, Any]] = {}
    for item in candidates:
        label = safe_str(item.get("label") or item.get("matched_label"))
        if not label:
            continue
        key = normalize_text(label)
        if not key:
            continue
        if item.get("match_type") == "ieee_text" and key in GENERIC_IEEE_TEXT_TERMS:
            continue

        score = 1.0
        if item.get("match_type") == "keyword_ieee":
            score = 3.0
        elif item.get("match_type") == "keyword_raw":
            score = 2.0
        elif item.get("match_type") == "regex":
            score = 2.5
        elif item.get("match_type") == "ieee_text":
            score = 1.5

        current = ranked.get(key)
        if not current or score > current["score"]:
            concept_type = item.get("concept_type") or infer_concept_type(label, text)
            ranked[key] = {
                "label": label,
                "concept_type": concept_type,
                "source": item.get("source", ""),
                "matched_label": item.get("matched_label", ""),
                "uri": item.get("uri", ""),
                "match": item.get("match", label),
                "match_type": item.get("match_type", ""),
                "score": score,
            }

    ordered = sorted(
        ranked.values(),
        key=lambda item: (item["score"], len(item["label"].split()), len(item["label"])),
        reverse=True,
    )
    ordered = suppress_plain_metric_duplicates(ordered)
    return ordered[:max_concepts]
