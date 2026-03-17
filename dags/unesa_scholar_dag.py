"""
Airflow DAG: UNESA Scholar Paper ETL Pipeline
==============================================
Orchestrates the end-to-end paper ingestion flow:

  Task 1: Extract papers from Google Scholar via SerpAPI
  Task 2: Deduplicate papers (exact + fuzzy matching)
  Task 3: Enrich papers with Semantic Scholar & OpenAlex metadata  
  Task 4: Load enriched papers to Supabase (UPSERT)
  Task 5: Link papers to lecturers (Junction Table)

Schedule: Daily at 01:00 WIB (UTC+7)
Retry: 2 attempts with 5-minute delay
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
    dag_id="unesa_scholar_etl",
    default_args=default_args,
    description="ETL Pipeline: Scholar Papers → Supabase (Micro-batch, Idempotent)",
    schedule_interval="0 18 * * *",  # 01:00 WIB = 18:00 UTC previous day
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["etl", "scholar", "unesa"],
    max_active_runs=1,
)


# ─── Task 1: Extract ────────────────────────────────────────────

@task(dag=dag)
def extract_papers():
    """Extract raw papers from Google Scholar via SerpAPI."""
    import pandas as pd
    from src.etl.config import RAW_DATA_DIR
    from src.etl.extract.scholar import extract_scholar_papers

    # Load lecturer targets
    # In production, this could come from Supabase or an Airflow Variable
    dosen_csv = PROJECT_ROOT / "data" / "raw" / "dosen_infokom_final.csv"

    if not dosen_csv.exists():
        # Fallback: try notebooks location
        dosen_csv = PROJECT_ROOT / "notebooks" / "scraping" / "file_tabulars" / "dosen_infokom_final.csv"

    if not dosen_csv.exists():
        raise FileNotFoundError(f"Dosen CSV not found: {dosen_csv}")

    df_dosen = pd.read_csv(dosen_csv, dtype=str)
    targets = []
    for _, r in df_dosen.iterrows():
        sid = str(r.get("scholar_id", "")).strip().replace('.0', '')
        if sid not in ("", "nan", "NaN"):
            targets.append({"id": sid, "name": r["nama_dosen"]})

    df = extract_scholar_papers(targets)
    output_path = str(RAW_DATA_DIR / "scholar_papers_raw.csv")
    return output_path


# ─── Task 2: Deduplicate ────────────────────────────────────────

@task(dag=dag)
def deduplicate(raw_csv_path: str):
    """Remove duplicate papers (exact + fuzzy matching)."""
    import pandas as pd
    from src.etl.config import PROCESSED_DATA_DIR
    from src.etl.transform.deduplicator import deduplicate_papers

    df = pd.read_csv(raw_csv_path, dtype=str).fillna("")
    df_clean = deduplicate_papers(df)

    output_path = str(PROCESSED_DATA_DIR / "scholar_papers_deduped.csv")
    df_clean.to_csv(output_path, index=False)
    print(f"✅ Saved {len(df_clean)} deduplicated papers -> {output_path}")
    return output_path


# ─── Task 3: Enrich ─────────────────────────────────────────────

@task(dag=dag)
def enrich(deduped_csv_path: str):
    """Enrich papers with S2 + OpenAlex metadata (micro-batch)."""
    import pandas as pd
    from src.etl.config import PROCESSED_DATA_DIR
    from src.etl.transform.enricher import enrich_paper_batch

    df = pd.read_csv(deduped_csv_path, dtype=str).fillna("")

    # Process in micro-batches of 200
    BATCH_SIZE = 200
    for start in range(0, len(df), BATCH_SIZE):
        df = enrich_paper_batch(df, batch_size=BATCH_SIZE, start_idx=start)

    output_path = str(PROCESSED_DATA_DIR / "scholar_papers_enriched.csv")
    df.to_csv(output_path, index=False)
    print(f"✅ Saved {len(df)} enriched papers -> {output_path}")
    return output_path


# ─── Task 4: Load to Supabase ───────────────────────────────────

@task(dag=dag)
def load_to_supabase(enriched_csv_path: str):
    """UPSERT enriched papers to Supabase PostgreSQL."""
    import pandas as pd
    from src.etl.load.supabase_loader import SupabaseLoader

    df = pd.read_csv(enriched_csv_path, dtype=str).fillna("")
    loader = SupabaseLoader()
    count = loader.upsert_papers(df)
    print(f"✅ Loaded {count} papers to Supabase")
    return enriched_csv_path


# ─── Task 5: Link Papers to Lecturers ───────────────────────────

@task(dag=dag)
def link_lecturers(enriched_csv_path: str):
    """Create paper-lecturer relationships in junction table."""
    import pandas as pd
    from src.etl.load.supabase_loader import SupabaseLoader

    df = pd.read_csv(enriched_csv_path, dtype=str).fillna("")
    loader = SupabaseLoader()
    count = loader.link_papers_to_lecturers(df)
    print(f"✅ Linked {count} paper-lecturer relationships")


# ─── DAG Pipeline (TaskFlow) ────────────────────────────────────

raw_path = extract_papers()
deduped_path = deduplicate(raw_path)
enriched_path = enrich(deduped_path)
loaded_path = load_to_supabase(enriched_path)
link_lecturers(loaded_path)
