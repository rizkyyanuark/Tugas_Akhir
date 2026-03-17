"""
Transform: Paper Enrichment (Micro-batch)
==========================================
Enriches papers with metadata from multiple APIs in priority order:
  Phase 1: Semantic Scholar (FREE) -> Abstract, DOI, TLDR
  Phase 2: OpenAlex (FREE) -> Keywords, Author IDs, DOI
  Phase 3: BrightData SERP (PAID) -> Fallback for missing data

Designed for Airflow micro-batch execution with idempotency.
"""
import time
import pandas as pd

from ..extract.semantic_scholar import extract_s2_metadata
from ..extract.openalex import extract_openalex_metadata


def enrich_paper_batch(
    df: pd.DataFrame,
    batch_size: int = 50,
    start_idx: int = 0,
) -> pd.DataFrame:
    """
    Enrich a batch of papers with metadata from free APIs.
    Only processes papers that haven't been enriched yet.

    Args:
        df: DataFrame of papers with at least 'Title' column.
        batch_size: Number of papers to process in this batch.
        start_idx: Starting index for this batch.

    Returns:
        Enriched DataFrame (same length, updated in-place).
    """
    # Ensure columns exist
    for col in ["Abstract", "Keywords", "DOI", "TLDR", "Document Type", "enriched"]:
        if col not in df.columns:
            df[col] = ""

    # Filter un-enriched papers
    mask = df["enriched"].astype(str).str.lower() != "true"
    pending_indices = df[mask].index.tolist()

    if start_idx >= len(pending_indices):
        print("   ✅ All papers already enriched!")
        return df

    batch_indices = pending_indices[start_idx:start_idx + batch_size]
    total = len(batch_indices)

    print(f"\n🔧 ENRICH: Processing batch of {total} papers (idx {start_idx}-{start_idx + total})")
    print("=" * 60)

    stats = {"s2": 0, "oa": 0, "abs": 0, "kw": 0, "doi": 0, "tldr": 0}
    t_start = time.time()

    for count, i in enumerate(batch_indices, 1):
        row = df.loc[i]
        title = str(row.get("Title", "")).strip()
        abstract = str(row.get("Abstract", "")).strip()
        keywords = str(row.get("Keywords", "")).strip()
        doi = str(row.get("DOI", "")).strip()
        tldr = str(row.get("TLDR", "")).strip()
        doc_type = str(row.get("Document Type", "")).strip()
        journal = str(row.get("Journal", "")).strip()
        year = str(row.get("Year", "")).strip()

        print(f"\n[{count}/{total}] {title[:60]}...")

        time.sleep(0.5)  # Rate limiting

        # ── Phase 1: Semantic Scholar ──
        print(f"   [Phase 1] Semantic Scholar...")
        s2 = extract_s2_metadata(doi=doi if doi else None, title=title)
        if s2:
            stats["s2"] += 1
            if not tldr and s2.get('tldr'):
                tldr = str(s2['tldr'].get('text', '')) if isinstance(s2['tldr'], dict) else str(s2['tldr'])
            if not abstract and s2.get('abstract'):
                abstract = str(s2['abstract'])
            if not doi and s2.get('externalIds', {}).get('DOI'):
                doi = s2['externalIds']['DOI']
            if not year and s2.get('year'):
                year = str(s2['year'])
            if not journal and s2.get('venue'):
                journal = str(s2['venue'])
            if not doc_type and s2.get('publicationTypes'):
                doc_type = ", ".join(s2['publicationTypes'])
        else:
            print(f"      -> MISS: Not found in S2")

        # ── Phase 2: OpenAlex ──
        print(f"   [Phase 2] OpenAlex...")
        oa = extract_openalex_metadata(doi=doi if doi else None, title=title)
        if oa:
            stats["oa"] += 1
            if not keywords and oa.get('keywords'):
                keywords = oa['keywords']
            if not doc_type and oa.get('doc_type'):
                doc_type = oa['doc_type']
            if not year and oa.get('publication_year'):
                year = str(oa['publication_year'])
            if not doi and oa.get('doi'):
                doi = oa['doi']
            if not abstract and oa.get('abstract'):
                abstract = oa['abstract']
            loc = oa.get('primary_location') or {}
            if not journal and loc.get('source'):
                journal = str(loc['source'].get('display_name', ''))
        else:
            print(f"      -> MISS: Not found in OpenAlex")

        # ── Fallback defaults ──
        if not doc_type:
            doc_type = "Artikel"

        # ── Update DataFrame ──
        df.at[i, "Abstract"] = abstract
        df.at[i, "Keywords"] = keywords
        df.at[i, "DOI"] = doi
        df.at[i, "TLDR"] = tldr
        df.at[i, "Document Type"] = doc_type
        df.at[i, "Journal"] = journal
        df.at[i, "Year"] = year
        df.at[i, "enriched"] = "True"

        # Stats
        if abstract: stats["abs"] += 1
        if keywords: stats["kw"] += 1
        if doi: stats["doi"] += 1
        if tldr: stats["tldr"] += 1

        elapsed = time.time() - t_start
        avg = elapsed / count
        eta = ((total - count) * avg) / 60
        print(f"   ✅ [{count}/{total}] ETA: {eta:.1f} min")

    # Final report
    print(f"\n{'=' * 60}")
    print(f"ENRICHMENT BATCH DONE - {total} papers processed")
    print(f"   S2 hits : {stats['s2']}/{total}")
    print(f"   OA hits : {stats['oa']}/{total}")
    print(f"   Abstract: {stats['abs']}/{total}")
    print(f"   Keywords: {stats['kw']}/{total}")
    print(f"   DOI     : {stats['doi']}/{total}")
    print(f"   TLDR    : {stats['tldr']}/{total}")
    print(f"{'=' * 60}")

    return df
