"""
Airflow DAG: UNESA Lecturers ETL Pipeline (Weekly)
==================================================
Orchestrates the extraction and unification of Lecturer Profiles.
Exactly mirrors 'scraping_dosen_infokom_v4.ipynb'.

Tasks:
  1. extract_web      → pipeline.run_web_step()
  2. extract_pddikti  → pipeline.run_pddikti_step()
  3. merge            → pipeline.run_smart_merge()
  4. enrich           → pipeline.run_enrichment()
  5. transform        → pipeline.run_post_processing()
  6. load             → pipeline.run_supabase_sync()

Schedule: Weekly (Sunday 02:00 WIB = Saturday 19:00 UTC)
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

from airflow import DAG
from airflow.decorators import task

# Add notebooks/scraping to Python path to access scraping_modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRAPING_DIR = PROJECT_ROOT / "notebooks" / "scraping"
if str(SCRAPING_DIR) not in sys.path:
    sys.path.append(str(SCRAPING_DIR))

# ─── DAG Configuration ──────────────────────────────────────────

default_args = {
    "owner": "rizky",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="unesa_lecturers_etl",
    default_args=default_args,
    description="ETL Pipeline: V4 Lecturer Profiles → Supabase (Weekly)",
    schedule_interval="0 19 * * 6",  # Sunday 02:00 WIB = Saturday 19:00 UTC
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["dosen", "weekly", "pddikti", "sinta", "unesa"],
    max_active_runs=1,
)

# ─── Task Definitions ───────────────────────────────────────────

@task(dag=dag)
def extract_web():
    """Step 1: Scrape lecturer data from 10+ prodi websites."""
    from scraping_modules import pipeline
    output_path = pipeline.run_web_step()
    return str(output_path) if output_path else ""


@task(dag=dag)
def extract_pddikti():
    """Step 2: Fetch lecturer data from PDDIKTI API."""
    from scraping_modules import pipeline
    output_path = pipeline.run_pddikti_step()
    return str(output_path) if output_path else ""


@task(dag=dag)
def merge(web_path: str, pddikti_path: str):
    """Step 3: Web-First Smart Merge with comprehensive deduplication."""
    from scraping_modules import pipeline
    output_path = pipeline.run_smart_merge()
    return str(output_path) if output_path else ""


@task(dag=dag)
def enrich(merged_path: str):
    """Step 4: API Enrichment (SimCV, Sinta, SciVal, Scholar/BrightData)."""
    from scraping_modules import pipeline
    # We use scholar_sample=5 just like in the V4 notebook to prevent
    # BrightData proxy exhaustion. Can be set to None for full run.
    output_path = pipeline.run_enrichment(scholar_sample=5) 
    return str(output_path) if output_path else ""


@task(dag=dag)
def transform(enriched_path: str):
    """Step 5: Final Post-Processing (Dedup, type enforcement)."""
    from scraping_modules import pipeline
    output_path = pipeline.run_post_processing()
    return str(output_path) if output_path else ""


@task(dag=dag)
def load(cleaned_path: str):
    """Step 6: UPSERT cleaned lecturer data to Supabase PostgreSQL."""
    from scraping_modules import pipeline
    synced_count = pipeline.run_supabase_sync()
    if synced_count is not None:
        print(f"✅ Supabase Sync completed. {synced_count} records sent to DB.")
    else:
        print("⚠️ Supabase Sync skipped or failed.")


# ─── DAG Pipeline Flow ──────────────────────────────────────────

# Step 1 & 2: extraction
web_raw = extract_web()
pddikti_raw = extract_pddikti()

# Step 3: Merge both sources
merged_path = merge(web_raw, pddikti_raw)

# Step 4: Enrich with external APIs
enriched_path = enrich(merged_path)

# Step 5: Post-Process & Clean
transformed_path = transform(enriched_path)

# Step 6: Load to database
load(transformed_path)
