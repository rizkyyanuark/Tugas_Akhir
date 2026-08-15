"""
ner_extraction.py — Zero-Shot Academic NER & RE via GLiNER / GLiREL
====================================================================
Optional deep-learning extractions for paper titles, abstracts, and TLDRs.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any
import pandas as pd

from yunesa.knowledge.constants import (
    GLINER_LABEL_TO_CONCEPT_TYPE,
    ACADEMIC_NER_LABELS,
    ACADEMIC_RELATION_LABELS,
    GLIREL_RELATION_TO_EDGE,
)
from yunesa.knowledge.config import AcademicExtractionConfig
from yunesa.knowledge.utils.text_processing import (
    safe_str,
    normalize_text,
    canonical_concept_type,
    canonical_relation,
    academic_document_id,
    academic_document_text,
    field_value,
    split_list_field,
)
from yunesa.knowledge.utils.concept_resolver import infer_concept_type


def _concept_type_from_ner_label(label: Any) -> str:
    normalized = normalize_text(label)
    return GLINER_LABEL_TO_CONCEPT_TYPE.get(normalized, infer_concept_type(normalized))


def _dedupe_entities(entities: list[dict[str, Any]], max_entities: int) -> list[dict[str, Any]]:
    ranked: dict[str, dict[str, Any]] = {}
    for entity in entities:
        text = safe_str(entity.get("text") or entity.get("label"))
        if not text:
            continue
        key = normalize_text(text)
        if len(key) < 2:
            continue
        score = float(entity.get("score") or 0.0)
        current = ranked.get(key)
        if not current or score > float(current.get("score") or 0.0):
            ranked[key] = {**entity, "text": text, "score": score}
    return sorted(ranked.values(), key=lambda item: float(item.get("score") or 0.0), reverse=True)[:max_entities]


def _token_spans(text: str) -> list[tuple[str, int, int]]:
    return [(match.group(0), match.start(), match.end()) for match in re.finditer(r"\S+", text)]


def _entity_to_token_span(entity: dict[str, Any], spans: list[tuple[str, int, int]]) -> list[Any] | None:
    start = entity.get("start")
    end = entity.get("end")
    if start is None or end is None:
        entity_text = safe_str(entity.get("text"))
        if not entity_text:
            return None
        return None
    try:
        char_start = int(start)
        char_end = int(end)
    except (TypeError, ValueError):
        return None
    token_indexes = [
        idx
        for idx, (_, token_start, token_end) in enumerate(spans)
        if token_start < char_end and token_end > char_start
    ]
    if not token_indexes:
        return None
    return [
        min(token_indexes),
        max(token_indexes),
        safe_str(entity.get("concept_type") or entity.get("label")).upper(),
        safe_str(entity.get("text")),
    ]


@lru_cache(maxsize=2)
def _load_gliner_model(model_name: str) -> Any:
    try:
        from gliner import GLiNER
    except ImportError as exc:
        raise ImportError(
            "GLiNER could not be imported. Install the backend 'kg' dependency group or "
            "disable extraction with YUNESA_USE_GLINER=0. "
            f"Underlying error: {type(exc).__name__}: {exc}"
        ) from exc
    return GLiNER.from_pretrained(model_name)


@lru_cache(maxsize=2)
def _load_glirel_model(model_name: str) -> Any:
    try:
        from glirel import GLiREL
    except ImportError as exc:
        raise ImportError(
            "GLiREL could not be imported. If glirel is already installed, inspect the "
            "underlying ImportError; on Windows this can happen when security policy blocks "
            "pyarrow/transformers DLLs. Disable extraction with YUNESA_USE_GLIREL=0, or run "
            "the extraction step in Colab/server runtime where GLiREL imports cleanly."
        ) from exc
    try:
        return GLiREL.from_pretrained(model_name)
    except TypeError as exc:
        if "proxies" not in str(exc) and "resume_download" not in str(exc):
            raise
        return GLiREL._from_pretrained(
            model_id=model_name,
            revision=None,
            cache_dir=None,
            force_download=False,
            proxies=None,
            resume_download=False,
            local_files_only=False,
            token=None,
            map_location="cpu",
        )


def _run_glirel_relations(
    text: str,
    entities: list[dict[str, Any]],
    config: AcademicExtractionConfig,
) -> list[dict[str, Any]]:
    if not config.use_glirel or len(entities) < 2:
        return []

    spans = _token_spans(text)
    if not spans:
        return []
    ner = [_entity_to_token_span(entity, spans) for entity in entities]
    ner = [item for item in ner if item is not None]
    if len(ner) < 2:
        return []

    model = _load_glirel_model(config.glirel_model)
    tokens = [token for token, _, _ in spans]
    raw_relations = model.predict_relations(
        tokens,
        ACADEMIC_RELATION_LABELS,
        threshold=config.relation_threshold,
        ner=ner,
        top_k=1,
    )

    relations: list[dict[str, Any]] = []
    for relation in raw_relations or []:
        label = safe_str(relation.get("label"))
        head = safe_str(relation.get("head_text") or relation.get("head"))
        tail = safe_str(relation.get("tail_text") or relation.get("tail"))
        if not label or not head or not tail:
            continue
        relations.append(
            {
                "head": head,
                "tail": tail,
                "label": label,
                "relation": GLIREL_RELATION_TO_EDGE.get(normalize_text(label), canonical_relation(label)),
                "score": float(relation.get("score") or 0.0),
                "source": "glirel",
            }
        )
        if len(relations) >= config.max_relations_per_paper:
            break
    return relations


def extract_academic_elements_with_gliner_glirel(
    papers_df: pd.DataFrame,
    config: AcademicExtractionConfig | None = None,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Run optional GLiNER/GLiREL extraction over paper text."""
    config = config or AcademicExtractionConfig.from_env()
    if not config.use_gliner:
        return {}

    gliner_model = _load_gliner_model(config.gliner_model)
    extraction_by_doc: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for _, paper in papers_df.iterrows():
        doc_id = academic_document_id(paper)
        text = academic_document_text(paper, max_chars=config.max_text_chars)
        if not text:
            extraction_by_doc[doc_id] = {"entities": [], "relationships": [], "keywords": []}
            continue

        raw_entities = gliner_model.predict_entities(
            text,
            ACADEMIC_NER_LABELS,
            threshold=config.entity_threshold,
        )
        entities = []
        for entity in raw_entities or []:
            entity_text = safe_str(entity.get("text"))
            if not entity_text:
                continue
            label = safe_str(entity.get("label"))
            concept_type = _concept_type_from_ner_label(label)
            entities.append(
                {
                    "text": entity_text,
                    "label": label,
                    "concept_type": canonical_concept_type(concept_type, fallback_label=entity_text),
                    "score": float(entity.get("score") or 0.0),
                    "start": entity.get("start"),
                    "end": entity.get("end"),
                    "source": "gliner",
                }
            )
        entities = _dedupe_entities(entities, config.max_entities_per_paper)
        relationships = _run_glirel_relations(text, entities, config) if config.use_glirel else []
        keywords = [
            {
                "keyword": item,
                "source": "paper_metadata",
                "score": 1.0,
            }
            for item in split_list_field(field_value(paper, "keywords", "Keywords"))
        ]
        extraction_by_doc[doc_id] = {
            "entities": entities,
            "relationships": relationships,
            "keywords": keywords,
        }

    return extraction_by_doc


def summarize_extracted_elements(
    extracted_elements: dict[str, dict[str, list[dict[str, Any]]]]
) -> dict[str, int]:
    return {
        "documents": len(extracted_elements),
        "entities": sum(len(value.get("entities", [])) for value in extracted_elements.values()),
        "relationships": sum(len(value.get("relationships", [])) for value in extracted_elements.values()),
        "keywords": sum(len(value.get("keywords", [])) for value in extracted_elements.values()),
    }
