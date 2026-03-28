"""
🧪 Local ETL Integration Test: Extract → Enrich → Load
========================================================
Tests the full pipeline with a limited scope:
  - Extract: 1 lecturer (first with scholar_id) via SerpAPI
  - Enrich:  5 papers only (S2 → OpenAlex → Qwen TLDR → Author Resolution)
  - Load:    Upsert to Supabase + Link junction table

Usage:
  python -X utf8 test_etl_local.py
"""
import sys
import os
import time
import traceback
import psutil  # For memory monitoring

# ─── Setup ──────────────────────────────────────────────────────
# Ensure project root is in PYTHONPATH
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("PYTHONPATH", str(PROJECT_ROOT))

# Load .env
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import pandas as pd

# ─── Config ─────────────────────────────────────────────────────
TEST_LECTURER_LIMIT = 1      # Number of lecturers to extract
TEST_PAPER_LIMIT = 5         # Number of papers to enrich
DOSEN_CSV = PROJECT_ROOT / "notebooks" / "scraping" / "file_tabulars" / "dosen_infokom_final.csv"


def get_memory_mb():
    """Get current process memory usage in MB."""
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def run_test():
    wall_start = time.time()
    mem_start = get_memory_mb()
    
    print("=" * 70)
    print("🧪 LOCAL ETL INTEGRATION TEST")
    print(f"   Scope: {TEST_LECTURER_LIMIT} lecturer, {TEST_PAPER_LIMIT} papers")
    print(f"   Memory at start: {mem_start:.0f} MB")
    print("=" * 70)

    # ════════════════════════════════════════════════════════════════
    # PHASE 1: EXTRACT (Scholar via SerpAPI)
    # ════════════════════════════════════════════════════════════════
    print("\n" + "─" * 70)
    print("📡 PHASE 1: EXTRACT (Google Scholar via SerpAPI)")
    print("─" * 70)
    
    t1 = time.time()
    
    from src.etl.extract.scholar import extract_scholar_papers
    
    # Load lecturer database and pick the first one with a scholar_id
    df_dosen = pd.read_csv(DOSEN_CSV, dtype=str)
    targets = []
    for _, r in df_dosen.iterrows():
        sid = str(r.get("scholar_id", "")).strip()
        if sid and sid not in ("", "nan", "NaN", "None"):
            targets.append({"id": sid, "name": r["nama_dosen"]})
            if len(targets) >= TEST_LECTURER_LIMIT:
                break
    
    if not targets:
        print("❌ No lecturers with scholar_id found!")
        return
    
    print(f"   🎯 Target: {targets[0]['name']} ({targets[0]['id']})")
    
    df_extracted = extract_scholar_papers(
        targets, 
        limit_per_author=TEST_PAPER_LIMIT * 2,  # Extract a bit more to have margin
        resume_from_temp=False,
    )
    
    # Limit to TEST_PAPER_LIMIT
    if len(df_extracted) > TEST_PAPER_LIMIT:
        df_extracted = df_extracted.head(TEST_PAPER_LIMIT)
        print(f"   ✂️ Trimmed to {TEST_PAPER_LIMIT} papers for testing")
    
    t1_elapsed = time.time() - t1
    mem_after_extract = get_memory_mb()
    
    print(f"\n   ⏱️ Extract Time: {t1_elapsed:.1f}s")
    print(f"   📊 Papers Extracted: {len(df_extracted)}")
    print(f"   💾 Memory: {mem_after_extract:.0f} MB (+{mem_after_extract - mem_start:.0f} MB)")
    
    if df_extracted.empty:
        print("❌ No papers extracted, stopping.")
        return

    # ════════════════════════════════════════════════════════════════
    # PHASE 2: ENRICH (S2 → OpenAlex → Qwen TLDR → Author Resolve)
    # ════════════════════════════════════════════════════════════════
    print("\n" + "─" * 70)
    print("🔬 PHASE 2: ENRICH (Semantic Scholar → OpenAlex → TLDR → Authors)")
    print("─" * 70)
    
    t2 = time.time()
    
    from src.etl.transform.enricher import enrich_paper_batch
    
    # Add required columns if missing
    for col in ["Abstract", "Keywords", "DOI", "TLDR", "Document Type", "Author IDs", "enriched"]:
        if col not in df_extracted.columns:
            df_extracted[col] = ""
    
    df_enriched = enrich_paper_batch(df_extracted, allow_paid_proxy=False)
    
    t2_elapsed = time.time() - t2
    mem_after_enrich = get_memory_mb()
    
    print(f"\n   ⏱️ Enrich Time: {t2_elapsed:.1f}s")
    print(f"   💾 Memory: {mem_after_enrich:.0f} MB (+{mem_after_enrich - mem_after_extract:.0f} MB from enrichment)")
    
    # Show a sample of enriched data
    print("\n   📋 Sample Enriched Paper:")
    sample = df_enriched.iloc[0]
    print(f"      Title:    {str(sample.get('Title', ''))[:70]}")
    print(f"      Authors:  {str(sample.get('Authors', ''))[:70]}")
    print(f"      AuthIDs:  {str(sample.get('Author IDs', ''))[:70]}")
    print(f"      Abstract: {'✅ Yes' if str(sample.get('Abstract', '')).strip() else '❌ No'}")
    print(f"      Keywords: {'✅ Yes' if str(sample.get('Keywords', '')).strip() else '❌ No'}")
    print(f"      DOI:      {str(sample.get('DOI', ''))[:50] or '❌ No'}")
    print(f"      TLDR:     {'✅ Yes' if str(sample.get('TLDR', '')).strip() else '❌ No'}")

    # ════════════════════════════════════════════════════════════════
    # PHASE 3: LOAD (Supabase Upsert + Junction Table)
    # ════════════════════════════════════════════════════════════════
    print("\n" + "─" * 70)
    print("📤 PHASE 3: LOAD (Supabase Upsert → Papers + Junction Table)")
    print("─" * 70)
    
    t3 = time.time()
    
    from src.etl.load.supabase_loader import SupabaseLoader
    
    loader = SupabaseLoader()
    
    # Upsert Papers
    papers_count = loader.upsert_papers(df_enriched)
    
    # Link to Lecturers
    links_count = loader.link_papers_to_lecturers(df_enriched)
    
    t3_elapsed = time.time() - t3
    mem_after_load = get_memory_mb()
    
    print(f"\n   ⏱️ Load Time: {t3_elapsed:.1f}s")
    print(f"   📊 Papers Upserted: {papers_count}")
    print(f"   🔗 Links Created: {links_count}")
    print(f"   💾 Memory: {mem_after_load:.0f} MB")

    # ════════════════════════════════════════════════════════════════
    # FINAL REPORT
    # ════════════════════════════════════════════════════════════════
    wall_total = time.time() - wall_start
    mem_peak = get_memory_mb()
    
    print("\n" + "=" * 70)
    print("📊 FINAL TEST REPORT")
    print("=" * 70)
    print(f"   Lecturer:       {targets[0]['name']}")
    print(f"   Papers Tested:  {len(df_enriched)}")
    print()
    print(f"   ⏱️ TIMING:")
    print(f"      Extract:     {t1_elapsed:>8.1f}s")
    print(f"      Enrich:      {t2_elapsed:>8.1f}s")
    print(f"      Load:        {t3_elapsed:>8.1f}s")
    print(f"      ─────────────────────")
    print(f"      TOTAL:       {wall_total:>8.1f}s ({wall_total/60:.1f} min)")
    print()
    print(f"   💾 MEMORY:")
    print(f"      Start:       {mem_start:>8.0f} MB")
    print(f"      After Extract:{mem_after_extract:>7.0f} MB")
    print(f"      After Enrich: {mem_after_enrich:>7.0f} MB")
    print(f"      After Load:   {mem_after_load:>7.0f} MB")
    print(f"      Peak (end):   {mem_peak:>7.0f} MB")
    print()
    
    # Enrichment quality stats
    n = len(df_enriched)
    abs_count = df_enriched['Abstract'].apply(lambda x: bool(str(x).strip())).sum()
    kw_count = df_enriched['Keywords'].apply(lambda x: bool(str(x).strip())).sum()
    doi_count = df_enriched['DOI'].apply(lambda x: bool(str(x).strip())).sum()
    tldr_count = df_enriched['TLDR'].apply(lambda x: bool(str(x).strip())).sum()
    
    print(f"   📈 ENRICHMENT QUALITY:")
    print(f"      Abstract:    {abs_count}/{n} ({abs_count/n*100:.0f}%)")
    print(f"      Keywords:    {kw_count}/{n} ({kw_count/n*100:.0f}%)")
    print(f"      DOI:         {doi_count}/{n} ({doi_count/n*100:.0f}%)")
    print(f"      TLDR:        {tldr_count}/{n} ({tldr_count/n*100:.0f}%)")
    print("=" * 70)
    
    # Save results
    output_path = PROJECT_ROOT / "data" / "processed" / "test_etl_result.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_enriched.to_csv(output_path, index=False)
    print(f"\n💾 Results saved to: {output_path}")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        traceback.print_exc()
