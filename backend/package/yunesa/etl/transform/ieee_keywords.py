from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class IeeeKeywordTerm:
    canonical: str
    aliases: tuple[str, ...]


_LABEL_RE = re.compile(r'rdfs:label\s+"([^"]+)"')
_ALT_LABEL_RE = re.compile(r'skos:altLabel\s+"([^"]+)"')
_PREF_LABEL_RE = re.compile(r'skos:prefLabel\s+"([^"]+)"')
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "paper",
    "study",
    "the",
    "this",
    "to",
    "using",
    "with",
}
_GENERIC_SINGLE_TERMS = {
    "application",
    "applications",
    "construction",
    "data",
    "design",
    "framework",
    "information",
    "lead",
    "machine",
    "method",
    "methods",
    "model",
    "models",
    "modeling",
    "optimisation",
    "optimization",
    "performance",
    "processing",
    "research",
    "study",
    "system",
    "systems",
    "technology",
    "technologies",
}
_AMBIGUOUS_RELAXED_TOKENS = {
    "cyber",
    "digital",
    "low",
    "machine",
    "media",
    "medium",
    "power",
    "protection",
    "security",
    "small",
}


def _normalize_text(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_token(token: str) -> str:
    token = token.lower()
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _content_tokens(text: str) -> list[str]:
    return [
        _normalize_token(token)
        for token in _WORD_RE.findall(text)
        if len(token) > 2 and token not in _STOPWORDS and _normalize_token(token) not in _GENERIC_SINGLE_TERMS
    ]


def _is_valid_term(term: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(term or "")).strip()
    normalized = _normalize_text(cleaned)
    if not normalized or len(normalized) < 3 or len(normalized) > 80:
        return False
    if normalized in {"general", "miscellaneous", "other", "others"}:
        return False
    if not re.search(r"[a-z]", normalized):
        return False
    if re.fullmatch(r"[a-z]?\d+[a-z]?", normalized):
        return False
    if len(normalized.split()) == 1 and normalized in _GENERIC_SINGLE_TERMS:
        return False
    if "............" in cleaned:
        return False
    return True


def _is_acronym(value: str) -> bool:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(value or ""))
    return 2 <= len(cleaned) <= 8 and cleaned.upper() == cleaned and re.search(r"[A-Z]", cleaned) is not None


def _is_valid_alias(alias: str, canonical: str) -> bool:
    if not _is_valid_term(alias):
        return False
    if re.search(r"\b(?:BT|NT|RT)\s*:", alias):
        return False

    alias_norm = _normalize_text(alias)
    canonical_norm = _normalize_text(canonical)
    if alias_norm.startswith("security ") and "security" not in canonical_norm:
        return False
    if alias_norm == canonical_norm:
        return True

    alias_tokens = _content_tokens(alias_norm)
    canonical_tokens = _content_tokens(canonical_norm)
    if len(alias_tokens) >= 2:
        return True

    # IEEE thesaurus often contains broad one-word labels as redirects. They are
    # too ambiguous for paper-level keyword assignment unless the canonical term
    # is also one token or the alias is a clear acronym such as NLP.
    if len(alias_tokens) == 1 and (len(canonical_tokens) == 1 or _is_acronym(alias)):
        return True

    return False


def _candidate_resource_paths() -> Iterable[Path]:
    current = Path(__file__).resolve()
    for parent in current.parents:
        yield parent / "knowledge" / "etl" / "resources" / "ieee-thesaurus.ttl"
        yield parent / "notebooks" / "build-graph" / "ieee-thesaurus.ttl"


def extract_ieee_terms_from_ttl(ttl_text: str) -> tuple[IeeeKeywordTerm, ...]:
    """Parse IEEE SKOS TTL into canonical terms with aliases.

    The local IEEE thesaurus has aliases in ``rdfs:label`` and canonical labels in
    ``skos:prefLabel``. We match aliases but emit the canonical preferred label.
    """
    terms: dict[str, set[str]] = {}

    block_lines: list[str] = []
    blocks: list[str] = []
    for line in ttl_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("@prefix"):
            continue

        block_lines.append(stripped)
        if stripped.endswith(" ."):
            blocks.append("\n".join(block_lines))
            block_lines = []

    for block in blocks:
        if "skos:Concept" not in block:
            continue

        pref_labels = [label.strip() for label in _PREF_LABEL_RE.findall(block)]
        if not pref_labels:
            continue

        canonical = pref_labels[0]
        if not _is_valid_term(canonical):
            continue

        aliases = set(pref_labels)
        aliases.update(label.strip() for label in _LABEL_RE.findall(block))
        aliases.update(label.strip() for label in _ALT_LABEL_RE.findall(block))
        aliases = {alias for alias in aliases if _is_valid_alias(alias, canonical)}
        if not aliases:
            aliases = {canonical}

        terms.setdefault(canonical, set()).update(aliases)

    return tuple(
        IeeeKeywordTerm(canonical=canonical, aliases=tuple(sorted(aliases)))
        for canonical, aliases in sorted(terms.items(), key=lambda item: item[0].lower())
    )


@lru_cache(maxsize=1)
def load_ieee_terms() -> tuple[IeeeKeywordTerm, ...]:
    for path in _candidate_resource_paths():
        if path.exists():
            return extract_ieee_terms_from_ttl(path.read_text(encoding="utf-8", errors="ignore"))
    return ()


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    variants = {phrase}
    if phrase.endswith("s"):
        variants.add(phrase[:-1])
    if phrase.endswith("ies"):
        variants.add(f"{phrase[:-3]}y")
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])", text) is not None
        for candidate in variants
        if candidate
    )


def _token_overlap_score(term: str, text_tokens: set[str]) -> tuple[float, set[str]]:
    term_tokens = list(dict.fromkeys(_content_tokens(term)))
    if len(term_tokens) < 2:
        if term_tokens and term_tokens[0] in text_tokens and term_tokens[0] not in _GENERIC_SINGLE_TERMS:
            return 0.5, {term_tokens[0]}
        return 0.0, set()
    matched_tokens = {token for token in term_tokens if token in text_tokens}
    ratio = len(matched_tokens) / len(term_tokens)
    return ratio, matched_tokens


def generate_ieee_keywords(
    *,
    title: str,
    abstract: str,
    terms: Sequence[IeeeKeywordTerm] | None = None,
    min_keywords: int = 3,
    max_keywords: int = 5,
) -> str:
    """Return controlled IEEE keywords inferred from title and abstract.

    This function is intentionally deterministic. It does not invent free-form
    keywords; it only emits canonical IEEE terms.
    """
    source_title = _normalize_text(title)
    source_abstract = _normalize_text(abstract)
    source_all = f"{source_title} {source_abstract}".strip()
    if not source_all:
        return ""

    vocabulary = tuple(terms) if terms is not None else load_ieee_terms()
    if not vocabulary:
        return ""

    text_tokens = set(_content_tokens(source_all))
    scored: dict[str, float] = {}
    relaxed_scored: dict[str, float] = {}

    for term in vocabulary:
        best_score = 0.0
        for alias in term.aliases:
            normalized_alias = _normalize_text(alias)
            if not normalized_alias:
                continue

            alias_tokens = _content_tokens(normalized_alias)
            alias_weight = min(len(alias_tokens), 5) * 0.15

            if _contains_phrase(source_title, normalized_alias):
                best_score = max(best_score, 8.0 + alias_weight)
            if _contains_phrase(source_abstract, normalized_alias):
                best_score = max(best_score, 4.0 + alias_weight)

            overlap, matched_tokens = _token_overlap_score(normalized_alias, text_tokens)
            if best_score == 0.0 and overlap >= 0.66:
                best_score = max(best_score, 2.0 * overlap + alias_weight)
            elif (
                overlap >= 0.50
                and len(matched_tokens) >= 2
                and not (len(matched_tokens) == 1 and next(iter(matched_tokens)) in _AMBIGUOUS_RELAXED_TOKENS)
            ):
                relaxed_scored[term.canonical] = max(
                    relaxed_scored.get(term.canonical, 0.0),
                    1.0 * overlap + alias_weight,
                )

        if best_score:
            scored[term.canonical] = max(scored.get(term.canonical, 0.0), best_score)

    ranked = sorted(scored.items(), key=lambda item: (-item[1], item[0].lower()))
    selected: list[str] = []
    selected_norms: list[str] = []
    for keyword, _ in ranked:
        keyword_norm = _normalize_text(keyword)
        if any(
            keyword_norm == existing
            or (keyword_norm in existing and len(keyword_norm.split()) < len(existing.split()))
            for existing in selected_norms
        ):
            continue
        selected.append(keyword)
        selected_norms.append(keyword_norm)
        if len(selected) >= max_keywords:
            break

    if len(selected) < min_keywords:
        relaxed_ranked = sorted(relaxed_scored.items(), key=lambda item: (-item[1], item[0].lower()))
        for keyword, _ in relaxed_ranked:
            keyword_norm = _normalize_text(keyword)
            if keyword in selected:
                continue
            if any(
                keyword_norm == existing
                or (keyword_norm in existing and len(keyword_norm.split()) < len(existing.split()))
                for existing in selected_norms
            ):
                continue
            selected.append(keyword)
            selected_norms.append(keyword_norm)
            if len(selected) >= min_keywords or len(selected) >= max_keywords:
                break

    return ", ".join(selected)
