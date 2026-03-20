"""
Transform: Paper Deduplication
==============================
Removes duplicate papers using exact + trigram fuzzy matching.
"""
import pandas as pd
from collections import defaultdict
from difflib import SequenceMatcher


def _normalize_text(text) -> str:
    if pd.isna(text):
        return ""
    return str(text).lower().strip().replace(' ', '')


def _trigrams(text: str) -> set:
    s = _normalize_text(text)
    if len(s) < 3:
        return set()
    return set(s[i:i+3] for i in range(len(s) - 2))


def deduplicate_papers(
    df: pd.DataFrame,
    existing_titles = None,
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

    print(f"\n🔍 DEDUP: {len(df)} papers")

    df = df.copy()
    df['_title_norm'] = df['Title'].apply(_normalize_text)
    total_before = len(df)

    # 1. Exact dedup vs existing titles (e.g., Scopus)
    if existing_titles:
        mask = df['_title_norm'].isin(existing_titles)
        removed = mask.sum()
        df = df[~mask].reset_index(drop=True)
        print(f"   ✅ Cross-source exact dedup: {removed} removed")

    # 2. Self exact dedup
    before = len(df)
    df = df.drop_duplicates(subset='_title_norm', keep='first').reset_index(drop=True)
    print(f"   ✅ Self exact dedup: {before - len(df)} removed")

    # 3. Fuzzy dedup via trigram Jaccard (O(N) amortized with inverted index)
    print(f"   🔄 Fuzzy dedup on {len(df)} papers...")
    trigram_index = defaultdict(set)
    trigram_cache = {}
    dup_indices = set()

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
        for cand_idx, shared_count in candidate_counts.items():
            if shared_count >= min_shared:
                cand_tg = trigram_cache[cand_idx]
                jaccard = len(tg & cand_tg) / len(tg | cand_tg)
                if jaccard >= fuzzy_threshold:
                    is_dup = True
                    break

        if is_dup:
            dup_indices.add(idx)
        else:
            trigram_cache[idx] = tg
            for t in tg:
                trigram_index[t].add(idx)

    df = df.drop(index=dup_indices).reset_index(drop=True)
    print(f"   ✅ Fuzzy dedup: {len(dup_indices)} removed")

    df = df.drop(columns=['_title_norm'], errors='ignore')
    total_after = len(df)
    print(f"   📊 Summary: {total_before} → {total_after} ({total_before - total_after} removed)")

    return df
