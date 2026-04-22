"""
ETL Worker CLI — Unified Entrypoint
=====================================
Level 3 Architecture: Standalone entrypoint for the ETL Worker container.
Airflow's DockerOperator calls this via:
    python -m knowledge.etl.run_worker <task_name> [--test-mode]

This module does NOT depend on Airflow in any way.
All secrets are injected as environment variables by the DockerOperator.

Supported Commands:
  ┌─────────────────────────────────────────────────────────────────┐
  │  PAPERS PIPELINE  (unesa_papers_etl DAG)                        │
  │    paper_extract_scopus   → Scrape papers from Scopus/SciVal    │
  │    paper_extract_scholar  → Scrape papers from Google Scholar   │
  │    paper_transform        → Merge + Enrich + Clean              │
  │    paper_load             → UPSERT to Supabase PostgreSQL       │
  │    paper_notify           → Email/log notification              │
  │                                                                  │
  │  LECTURERS PIPELINE  (unesa_lecturers_etl DAG)                  │
  │    lec_extract_web        → Scrape prodi websites               │
  │    lec_extract_pddikti    → Fetch from PDDIKTI API              │
  │    lec_merge              → Merge web and pddikti data          │
  │    lec_enrich             → API enrichment (SimCV, Sinta, etc.) │
  │    lec_transform          → Final post-processing               │
  │    lec_load               → UPSERT to Supabase PostgreSQL       │
  └─────────────────────────────────────────────────────────────────┘

Maintenance Guide:
  To add a new task:
    1. Add the command string to TASK_CHOICES below
    2. Add a handler in _dispatch_task()
    3. Add the DockerOperator task in the DAG file
"""
import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("etl-worker")


# ══════════════════════════════════════════════════════════════════════
#  TASK REGISTRY — Must match DAG DockerOperator `command=` values
# ══════════════════════════════════════════════════════════════════════

TASK_CHOICES = [
    # Papers pipeline
    "paper_extract_scopus",
    "paper_extract_scholar",
    "paper_transform",
    "paper_load",
    "paper_notify",
    # Lecturers pipeline
    "lec_extract_web",
    "lec_extract_pddikti",
    "lec_merge",
    "lec_enrich",
    "lec_transform",
    "lec_load",
]


# ══════════════════════════════════════════════════════════════════════
#  PAPERS PIPELINE HANDLERS
# ══════════════════════════════════════════════════════════════════════

def _paper_extract_scopus(test_mode: bool):
    """Extract raw papers from Scopus via SciVal/Selenium."""
    from knowledge.etl.services.unesa_papers import run_scopus_extraction

    result = run_scopus_extraction()
    logger.info(f"✅ paper_extract_scopus complete → {result}")


def _paper_extract_scholar(test_mode: bool):
    """Extract raw papers from Google Scholar via SerpAPI."""
    from knowledge.etl.services.unesa_papers import run_scholars_extraction

    result = run_scholars_extraction(test_mode=test_mode)
    logger.info(f"✅ paper_extract_scholar complete → {result}")


def _paper_transform(test_mode: bool):
    """Full post-extraction pipeline: Merge → Enrich → Clean."""
    from knowledge.etl.services.unesa_papers import (
        run_merge, run_enrichment, run_transform,
    )
    from knowledge.etl.config import RAW_DATA_DIR, PROCESSED_DATA_DIR

    # Step 1: Merge (deduplicate across Scopus + Scholar)
    scholar_path = str(RAW_DATA_DIR / "scholar_papers_raw.csv")
    scopus_path = str(RAW_DATA_DIR / "dosen_papers_scopus_raw.csv")
    merged_path = run_merge(scholar_path, scopus_path)
    logger.info(f"   ✅ Merge complete → {merged_path}")

    # Step 2: Enrich (Semantic Scholar + OpenAlex + TLDR)
    enriched_path = run_enrichment(merged_path, test_mode=test_mode)
    logger.info(f"   ✅ Enrich complete → {enriched_path}")

    # Step 3: Clean (HTML scrubbing, Unicode normalization)
    cleaned_path = run_transform(enriched_path)
    logger.info(f"✅ paper_transform complete → {cleaned_path}")


def _paper_load(test_mode: bool):
    """UPSERT cleaned papers to Supabase PostgreSQL."""
    from knowledge.etl.services.unesa_papers import run_database_commit
    from knowledge.etl.config import PROCESSED_DATA_DIR

    cleaned_path = str(PROCESSED_DATA_DIR / "unesa_papers_cleaned.csv")
    run_database_commit(cleaned_path)
    logger.info("✅ paper_load complete")


def _paper_notify(test_mode: bool):
    """Send completion notification (log-based for now)."""
    import os

    email = os.environ.get("NOTIFICATION_EMAIL", "")
    logger.info("═" * 60)
    logger.info("📧 PAPERS ETL PIPELINE — COMPLETE")
    logger.info("═" * 60)

    if email:
        logger.info(f"   Notification target: {email}")
        # TODO: Integrate SMTP or Airflow EmailOperator in the future.
        # For now, the Airflow log capture acts as the notification channel.
    else:
        logger.info("   No NOTIFICATION_EMAIL set — skipping email.")

    logger.info("🏁 All papers pipeline tasks finished successfully.")


# ══════════════════════════════════════════════════════════════════════
#  LECTURERS PIPELINE HANDLERS
# ══════════════════════════════════════════════════════════════════════

def _lec_dispatch(task: str, test_mode: bool):
    """
    Dispatch all lec_* tasks to the consolidated scraping pipeline.
    The lecturers pipeline lives in scraping/pipeline.py (V4 architecture).
    """
    from knowledge.etl.scraping import pipeline

    if task == "lec_extract_web":
        output = pipeline.run_web_step()
        logger.info(f"✅ lec_extract_web complete → {output}")

    elif task == "lec_extract_pddikti":
        output = pipeline.run_pddikti_step()
        logger.info(f"✅ lec_extract_pddikti complete → {output}")

    elif task == "lec_merge":
        output = pipeline.run_smart_merge()
        logger.info(f"✅ lec_merge complete → {output}")

    elif task == "lec_enrich":
        sample_limit = 5 if test_mode else None
        output = pipeline.run_enrichment(scholar_sample=sample_limit)
        logger.info(f"✅ lec_enrich complete → {output}")

    elif task == "lec_transform":
        output = pipeline.run_post_processing()
        logger.info(f"✅ lec_transform complete → {output}")

    elif task == "lec_load":
        synced_count = pipeline.run_supabase_sync()
        logger.info(f"✅ lec_load complete → Synced {synced_count} records")


# ══════════════════════════════════════════════════════════════════════
#  TASK DISPATCHER
# ══════════════════════════════════════════════════════════════════════

# Map command names → handler functions for the papers pipeline.
# Lecturers pipeline goes through _lec_dispatch for all lec_* tasks.
_PAPER_HANDLERS = {
    "paper_extract_scopus":  _paper_extract_scopus,
    "paper_extract_scholar": _paper_extract_scholar,
    "paper_transform":       _paper_transform,
    "paper_load":            _paper_load,
    "paper_notify":          _paper_notify,
}


def _dispatch_task(task: str, test_mode: bool):
    """Route a task name to its handler."""
    if task.startswith("lec_"):
        _lec_dispatch(task, test_mode)
    elif task in _PAPER_HANDLERS:
        _PAPER_HANDLERS[task](test_mode)
    else:
        raise ValueError(f"Unknown task: {task}")


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Yunesa ETL Worker CLI — Level 3 Decoupled Architecture"
    )
    parser.add_argument(
        "task",
        choices=TASK_CHOICES,
        help="Name of the ETL task to execute",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        default=False,
        help="Limit data volume for testing (e.g., 1 author, 5 papers)",
    )
    args = parser.parse_args()

    import os
    reload_enabled = os.environ.get("BACKEND_RELOAD", "").lower() == "true"

    if reload_enabled:
        try:
            from watchfiles import run_process
            import functools

            logger.info(f"🔄 Hot-Reload enabled. Watching for changes... (Task: {args.task})")
            
            # Create a partial function that calls the dispatcher
            # This is what watchfiles will restart on every change.
            task_func = functools.partial(_dispatch_task, args.task, args.test_mode)
            
            # Watch the package directory (where the logic lives)
            package_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            run_process(package_dir, target=task_func)
            
        except ImportError:
            logger.warning("⚠️ watchfiles not found. Running task once without reload.")
            _dispatch_task(args.task, args.test_mode)
    else:
        try:
            _dispatch_task(args.task, args.test_mode)
        except Exception as e:
            logger.error(f"❌ Task '{args.task}' failed: {e}", exc_info=True)
            sys.exit(1)

    logger.info(f"🏁 ETL Worker task '{args.task}' finished successfully.")


if __name__ == "__main__":
    main()
