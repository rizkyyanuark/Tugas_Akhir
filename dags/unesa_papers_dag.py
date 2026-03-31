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
    from src.etl.services.unesa_papers import run_scholars_extraction
    
    # Enable test_mode to limit to 1 author for now, exactly as before
    return run_scholars_extraction(test_mode=True)


# ─── Task 1B: Extract Scopus ────────────────────────────────────

@task(dag=dag)
def extract_scopus():
    """Extract raw papers from Scopus via SciVal/Selenium."""
    from src.etl.services.unesa_papers import run_scopus_extraction
    return run_scopus_extraction()


# ─── Task 2: Merge (Cross-Source Deduplication) ─────────────────

@task(dag=dag)
def merge(scholar_path: str, scopus_path: str):
    """Merge and remove duplicate papers across both isolated sources."""
    from src.etl.services.unesa_papers import run_merge
    return run_merge(scholar_path, scopus_path)


# ─── Task 3: Enrich ─────────────────────────────────────────────

@task(dag=dag)
def enrich(merged_csv_path: str):
    """Enrich papers with S2 + OpenAlex metadata (micro-batch)."""
    from src.etl.services.unesa_papers import run_enrichment
    # Enable test_mode to limit to 5 papers for now, exactly as before
    return run_enrichment(merged_csv_path, test_mode=True)


# ─── Task 4: Transform (Clean Data) ─────────────────────────────

@task(dag=dag)
def transform(enriched_csv_path: str):
    """Transform by aggressively scrubbing HTML, whitespace, and Unicode artifacts."""
    from src.etl.services.unesa_papers import run_transform
    return run_transform(enriched_csv_path)


# ─── Task 5: Load ───────────────────────────────────────────────

@task(dag=dag)
def load(cleaned_csv_path: str):
    """UPSERT papers to Supabase PostgreSQL and Neo4j Graph DB."""
    from src.etl.services.unesa_papers import run_database_commit
    return run_database_commit(cleaned_csv_path)


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
