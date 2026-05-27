from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Iterable, List, Optional, Set, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from pandas import DataFrame

logger = logging.getLogger(__name__)


def _normalize_text(text: Any) -> str:
    """Normalize text for deduplication purposes."""
    if pd.isna(text):
        return ""
    return str(text).lower().strip().replace(' ', '')


def _trigrams(text: str) -> Set[str]:
    """Generate trigrams for a given string."""
    s = _normalize_text(text)
    if len(s) < 3:
        return set()
    return set(s[i:i+3] for i in range(len(s) - 2))


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return bool(text) and text.lower() not in {"nan", "none", "null", "na"}


def _split_multi_value(value: Any, *, allow_comma: bool = True) -> list[str]:
    if not _is_present(value):
        return []
    normalized = str(value).replace("|", ";")
    if allow_comma:
        normalized = normalized.replace(",", ";")
    parts = normalized.split(";")
    return [part.strip() for part in parts if part.strip() and part.strip().lower() not in {"nan", "none", "null"}]


def _join_unique(values: list[Any], *, allow_comma: bool = True) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        for part in _split_multi_value(value, allow_comma=allow_comma):
            key = part.lower()
            if key not in seen:
                seen.add(key)
                ordered.append(part)
    return "; ".join(ordered)


def _merge_rows(base: pd.Series, incoming: pd.Series) -> pd.Series:
    """Merge duplicate paper rows while preserving lecturer relationships."""
    merged = base.copy()
    multi_value_columns = {
        "Authors",
        "Author IDs",
        "authors",
        "author_ids",
        "scholar_id",
        "scopus_id",
        "lecturer_name",
        "source",
        "citation_id",
        "Keywords",
        "keywords",
    }

    for column in incoming.index:
        if column == "_title_norm":
            continue
        current = merged.get(column, "")
        new_value = incoming.get(column, "")
        if column in multi_value_columns:
            merged[column] = _join_unique(
                [current, new_value],
                allow_comma=column not in {"Authors", "authors", "lecturer_name"},
            )
        elif not _is_present(current) and _is_present(new_value):
            merged[column] = new_value

    return merged


def _merge_exact_title_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    kept_rows: list[pd.Series] = []
    key_to_position: dict[str, int] = {}
    removed = 0

    for _, row in df.iterrows():
        key = row.get("_title_norm", "")
        if key and key in key_to_position:
            position = key_to_position[key]
            kept_rows[position] = _merge_rows(kept_rows[position], row)
            removed += 1
            continue
        key_to_position[key] = len(kept_rows)
        kept_rows.append(row.copy())

    return pd.DataFrame(kept_rows).reset_index(drop=True), removed


def deduplicate_papers(
    df: pd.DataFrame,
    existing_titles: Iterable[str] | None = None,
    fuzzy_threshold: float = 0.80,
) -> pd.DataFrame:
    """
    Remove duplicates from a DataFrame of papers.

    Args:
        df: DataFrame with a 'Title' column.
        existing_titles: Set of normalized titles to dedup against (e.g., Scopus).
        fuzzy_threshold: Jaccard trigram threshold for fuzzy matching.

    Returns:
        Deduplicated DataFrame.
    """
    if df.empty:
        return df

    logger.info(f"[DEDUP] Processing {len(df)} papers...")

    df = df.copy()
    df['_title_norm'] = df['Title'].apply(_normalize_text)
    total_before = len(df)

    # 1. Exact dedup vs existing titles (e.g., Scopus)
    if existing_titles:
        mask = df['_title_norm'].isin(existing_titles)
        removed = mask.sum()
        df = df[~mask].reset_index(drop=True)
        logger.info(f"   [DEDUP] Cross-source exact dedup: {removed} removed")

    # 2. Self exact dedup with author/source aggregation.
    df, exact_removed = _merge_exact_title_duplicates(df)
    logger.info(f"   [DEDUP] Self exact dedup: {exact_removed} merged")

    # 3. Fuzzy dedup via trigram Jaccard (O(N) amortized with inverted index)
    logger.info(f"   Fuzzy dedup on {len(df)} papers...")
    trigram_index: Dict[str, Set[int]] = defaultdict(set)
    trigram_cache: Dict[int, Set[str]] = {}
    dup_indices: Set[int] = set()

    for idx, row in df.iterrows():
        norm = row['_title_norm']
        if not norm or len(norm) < 10:
            continue

        tg = _trigrams(row['Title'])
        if not tg:
            continue

        candidate_counts = defaultdict(int)
        for t in tg:
            for cand_idx in trigram_index.get(t, set()):
                if cand_idx not in dup_indices:
                    candidate_counts[cand_idx] += 1

        min_shared = len(tg) * 0.5
        is_dup = False
        duplicate_of: Optional[int] = None
        for cand_idx, shared_count in candidate_counts.items():
            if shared_count >= min_shared:
                cand_tg = trigram_cache[cand_idx]
                jaccard = len(tg & cand_tg) / len(tg | cand_tg)
                if jaccard >= fuzzy_threshold:
                    is_dup = True
                    duplicate_of = cand_idx
                    break

        if is_dup:
            if duplicate_of is not None:
                df.loc[duplicate_of] = _merge_rows(df.loc[duplicate_of], row)
            dup_indices.add(idx)
        else:
            trigram_cache[idx] = tg
            for t in tg:
                trigram_index[t].add(idx)

    df = df.drop(index=dup_indices).reset_index(drop=True)
    logger.info(f"   Fuzzy dedup complete: {len(dup_indices)} removed")

    df = df.drop(columns=['_title_norm'], errors='ignore')
    total_after = len(df)
    logger.info(f"   [DEDUP] Summary: {total_before} -> {total_after} ({total_before - total_after} removed)")

    return df
