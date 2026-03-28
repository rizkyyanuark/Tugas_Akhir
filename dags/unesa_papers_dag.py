"""
Airflow DAG: UNESA Papers ETL Pipeline
======================================
Orchestrates the end-to-end paper ingestion flow from multiple sources:

  Task 1A: Extract papers from Google Scholar (SerpAPI)
  Task 1B: Extract papers from Scopus (SciVal)
  Task 2: Merge & Deduplicate papers cross-source
  Task 3: Enrich papers with Semantic Scholar & OpenAlex metadata (limited to 10 for testing)
  Task 4: Transform & Clean noisy data
  Task 5: Load enriched papers to Supabase & Link to Lecturers

Schedule: Daily at 01:00 WIB (UTC+7)
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

from airflow import DAG
from airflow.decorators import task
from airflow.models import Variable

# Add project root to Python path so we can import src.etl
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ─── DAG Configuration ──────────────────────────────────────────

default_args = {
    "owner": "rizky",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="unesa_papers_etl",
    default_args=default_args,
    description="ETL Pipeline: Scopus & Scholar Papers → Supabase (Micro-batch)",
    schedule_interval="0 18 * * *",  # 01:00 WIB = 18:00 UTC previous day
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["etl", "scholar", "scopus", "unesa"],
    max_active_runs=1,
)

# ─── Task 1A: Extract Scholar ───────────────────────────────────

@task(dag=dag)
def extract_scholar():
    """Extract raw papers from Google Scholar via SerpAPI."""
    import pandas as pd
    from src.etl.config import RAW_DATA_DIR
    from src.etl.extract.scholar import extract_scholar_papers

    dosen_csv = PROJECT_ROOT / "data" / "raw" / "dosen_infokom_final.csv"
    if not dosen_csv.exists():
        dosen_csv = PROJECT_ROOT / "notebooks" / "scraping" / "file_tabulars" / "dosen_infokom_final.csv"

    df_dosen = pd.read_csv(dosen_csv, dtype=str)
    targets = []
    for _, r in df_dosen.iterrows():
        sid = str(r.get("scholar_id", "")).strip().replace('.0', '')
        if sid not in ("", "nan", "NaN"):
            targets.append({"id": sid, "name": r["nama_dosen"]})

    # --- TEST MODE OVERRIDE ---
    targets = targets[:1] # Ambil 1 dosen saja untuk testing
    
    df = extract_scholar_papers(targets, limit_per_author=5)
    output_path = str(RAW_DATA_DIR / "scholar_papers_raw.csv")
    return output_path


# ─── Task 1B: Extract Scopus ────────────────────────────────────

@task(dag=dag)
def extract_scopus():
    """Extract raw papers from Scopus via SciVal/Selenium."""
    from src.etl.extract.scopus import extract_scopus_papers
    
    # Run the full scraper for all Scopus IDs in the dosen list (as in the Jupyter Notebook)
    papers = extract_scopus_papers()
    
    # Path is usually data/raw/dosen_papers_scopus_raw.csv
    from src.etl.config import RAW_DATA_DIR
    output_path = str(RAW_DATA_DIR / "dosen_papers_scopus_raw.csv")
    return output_path


# ─── Task 2: Merge (Cross-Source Deduplication) ─────────────────

@task(dag=dag)
def merge(scholar_path: str, scopus_path: str):
    """Merge and remove duplicate papers across both isolated sources."""
    import pandas as pd
    import os
    from src.etl.config import PROCESSED_DATA_DIR
    from src.etl.transform.deduplicator import deduplicate_papers
    
    df_combined = pd.DataFrame()
    
    if scholar_path and os.path.exists(scholar_path):
        try:
            df_sch = pd.read_csv(scholar_path, dtype=str).fillna("")
            df_combined = pd.concat([df_combined, df_sch], ignore_index=True)
        except pd.errors.EmptyDataError:
            print(f"⚠️ Warning: Scholar file is empty ({scholar_path})")
    elif not scholar_path:
        print("⚠️ Warning: scholar_path is None (XCom missing)")
            
    if scopus_path and os.path.exists(scopus_path):
        try:
            df_sco = pd.read_csv(scopus_path, dtype=str).fillna("")
            df_combined = pd.concat([df_combined, df_sco], ignore_index=True)
        except pd.errors.EmptyDataError:
            print(f"⚠️ Warning: Scopus file is empty ({scopus_path})")
    elif not scopus_path:
        print("⚠️ Warning: scopus_path is None (XCom missing)")

    if df_combined.empty:
        print("⚠️ Both sources are empty. Returning empty output.")
        df_clean = pd.DataFrame()
    else:
        df_clean = deduplicate_papers(df_combined)

    output_path = str(PROCESSED_DATA_DIR / "unesa_papers_deduped.csv")
    df_clean.to_csv(output_path, index=False)
    print(f"✅ Saved {len(df_clean)} deduplicated cross-source papers -> {output_path}")
    return output_path


# ─── Task 3: Enrich ─────────────────────────────────────────────

@task(dag=dag)
def enrich(merged_csv_path: str):
    """Enrich papers with S2 + OpenAlex metadata (micro-batch)."""
    import pandas as pd
    from src.etl.config import PROCESSED_DATA_DIR
    from src.etl.transform.enricher import enrich_paper_batch

    df = pd.read_csv(merged_csv_path, dtype=str).fillna("")

    # --- TEST MODE OVERRIDE ---
    if len(df) > 5:
        print(f"🧪 TEST MODE: Limiting enrichment from {len(df)} to 5 papers.")
        df = df.head(5)
    else:
        print(f"📊 Enriching {len(df)} papers...")

    # Process in micro-batches of 200
    BATCH_SIZE = 200
    for start in range(0, len(df), BATCH_SIZE):
        df = enrich_paper_batch(df, batch_size=BATCH_SIZE, start_idx=start, allow_paid_proxy=True)

    output_path = str(PROCESSED_DATA_DIR / "unesa_papers_enriched.csv")
    df.to_csv(output_path, index=False)
    print(f"✅ Saved {len(df)} enriched papers -> {output_path}")
    return output_path


# ─── Task 4: Transform (Clean Data) ─────────────────────────────

@task(dag=dag)
def transform(enriched_csv_path: str):
    """Transform by aggressively scrubbing HTML, whitespace, and Unicode artifacts."""
    import pandas as pd
    from src.etl.config import PROCESSED_DATA_DIR
    from src.etl.transform.cleaner import clean_papers_batch

    df = pd.read_csv(enriched_csv_path, dtype=str).fillna("")
    df_clean = clean_papers_batch(df)

    output_path = str(PROCESSED_DATA_DIR / "unesa_papers_cleaned.csv")
    df_clean.to_csv(output_path, index=False)
    print(f"✅ Saved {len(df_clean)} cleaned papers -> {output_path}")
    return output_path


# ─── Task 5: Load ───────────────────────────────────────────────

@task(dag=dag)
def load(cleaned_csv_path: str):
    """UPSERT papers to Supabase PostgreSQL and Link to Lecturers."""
    import pandas as pd
    from src.etl.load.supabase_loader import SupabaseLoader

    df = pd.read_csv(cleaned_csv_path, dtype=str).fillna("")
    loader = SupabaseLoader()
    
    # 1. Upsert Papers
    papers_count = loader.upsert_papers(df)
    print(f"✅ Loaded {papers_count} papers to Supabase")
    
    # 2. Link to Lecturers
    links_count = loader.link_papers_to_lecturers(df)
    print(f"✅ Linked {links_count} paper-lecturer relationships")


# ─── DAG Pipeline (TaskFlow) ────────────────────────────────────

# Step 1: Parallel extraction from Scholar and Scopus
scholar_raw = extract_scholar()
scopus_raw = extract_scopus()

# Step 2: Combine and Merge
merged_path = merge(scholar_raw, scopus_raw)

# Step 3: Enrich with missing DOIs/Abstracts (Limited)
enriched_path = enrich(merged_path)

# Step 4: Transform noisy texts
transformed_path = transform(enriched_path)

# Step 5: Load DB and Link
load(transformed_path)
