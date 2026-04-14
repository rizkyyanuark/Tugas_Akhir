"""
ETL Worker CLI Bridge
=====================
Level 3 Architecture: Standalone entrypoint for the ETL Worker container.
Airflow's DockerOperator calls this via:
    python -m src.etl.run_worker <task_name> [--test-mode]

This module does NOT depend on Airflow in any way.
All secrets are injected as environment variables by the DockerOperator.

Supported tasks:
  - extract_scholar   → Scrape Google Scholar papers
  - extract_scopus    → Scrape Scopus/SciVal papers
  - merge             → Deduplicate cross-source papers
  - enrich            → Enrich with S2 + OpenAlex metadata
  - transform         → Clean HTML/Unicode artifacts
  - load              → UPSERT to Supabase PostgreSQL

  Lecturer Pipeline Tasks:
  - lec_extract_web    → Scrape prodi websites
  - lec_extract_pddikti→ Fetch from PDDIKTI API
  - lec_merge          → Merge web and pddikti data
  - lec_enrich         → API enrichment (SimCV, Sinta, SciVal, Scholar)
  - lec_transform      → Final post-processing
  - lec_load           → UPSERT to Supabase PostgreSQL
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


def main():
    parser = argparse.ArgumentParser(
        description="ETL Worker CLI — Level 3 Decoupled Architecture"
    )
    parser.add_argument(
        "task",
        choices=[
            "extract_scholar",
            "extract_scopus",
            "merge",
            "enrich",
            "transform",
            "load",
            "lec_extract_web",
            "lec_extract_pddikti",
            "lec_merge",
            "lec_enrich",
            "lec_transform",
            "lec_load",
        ],
        help="Name of the ETL task to execute",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        default=False,
        help="Limit data volume for testing (e.g., 1 author, 5 papers)",
    )
    args = parser.parse_args()

    logger.info(f"🚀 ETL Worker starting task: {args.task} (test_mode={args.test_mode})")

    try:
        if args.task == "extract_scholar":
            from knowledge.etl.services.unesa_papers import run_scholars_extraction
            result = run_scholars_extraction(test_mode=args.test_mode)
            logger.info(f"✅ extract_scholar complete → {result}")

        elif args.task == "extract_scopus":
            from knowledge.etl.services.unesa_papers import run_scopus_extraction
            result = run_scopus_extraction()
            logger.info(f"✅ extract_scopus complete → {result}")

        elif args.task == "merge":
            from knowledge.etl.services.unesa_papers import run_merge
            from knowledge.etl.config import RAW_DATA_DIR
            # Level 3: Read fixed paths from shared volume instead of XCom
            scholar_path = str(RAW_DATA_DIR / "scholar_papers_raw.csv")
            scopus_path = str(RAW_DATA_DIR / "dosen_papers_scopus_raw.csv")
            result = run_merge(scholar_path, scopus_path)
            logger.info(f"✅ merge complete → {result}")

        elif args.task == "enrich":
            from knowledge.etl.services.unesa_papers import run_enrichment
            from knowledge.etl.config import PROCESSED_DATA_DIR
            merged_path = str(PROCESSED_DATA_DIR / "unesa_papers_deduped.csv")
            result = run_enrichment(merged_path, test_mode=args.test_mode)
            logger.info(f"✅ enrich complete → {result}")

        elif args.task == "transform":
            from knowledge.etl.services.unesa_papers import run_transform
            from knowledge.etl.config import PROCESSED_DATA_DIR
            enriched_path = str(PROCESSED_DATA_DIR / "unesa_papers_enriched.csv")
            result = run_transform(enriched_path)
            logger.info(f"✅ transform complete → {result}")

        elif args.task == "load":
            from knowledge.etl.services.unesa_papers import run_database_commit
            from knowledge.etl.config import PROCESSED_DATA_DIR
            cleaned_path = str(PROCESSED_DATA_DIR / "unesa_papers_cleaned.csv")
            run_database_commit(cleaned_path)
            logger.info("✅ load complete")

        # ==========================================
        # LECTURERS PIPELINE TASKS (V4)
        # ==========================================
        elif args.task.startswith("lec_"):
            # Inject notebooks/scraping into sys.path to allow scraping_modules import
            from pathlib import Path
            
            # Since this container ran with WORKDIR /app, the notebooks dir is at /app/notebooks
            scraping_dir = Path("/app/notebooks/scraping")
            if str(scraping_dir) not in sys.path:
                sys.path.append(str(scraping_dir))
                
            from scraping_modules import pipeline
            from scraping_modules import pipeline

            if args.task == "lec_extract_web":
                output_path = pipeline.run_web_step()
                logger.info(f"✅ lec_extract_web complete → {output_path}")
            elif args.task == "lec_extract_pddikti":
                output_path = pipeline.run_pddikti_step()
                logger.info(f"✅ lec_extract_pddikti complete → {output_path}")
            elif args.task == "lec_merge":
                output_path = pipeline.run_smart_merge()
                logger.info(f"✅ lec_merge complete → {output_path}")
            elif args.task == "lec_enrich":
                # For testing limit scholar to 5 if in test mode
                sample_limit = 5 if args.test_mode else None
                output_path = pipeline.run_enrichment(scholar_sample=sample_limit)
                logger.info(f"✅ lec_enrich complete → {output_path}")
            elif args.task == "lec_transform":
                output_path = pipeline.run_post_processing()
                logger.info(f"✅ lec_transform complete → {output_path}")
            elif args.task == "lec_load":
                synced_count = pipeline.run_supabase_sync()
                logger.info(f"✅ lec_load complete → Synced {synced_count} records")

    except Exception as e:
        logger.error(f"❌ Task '{args.task}' failed: {e}", exc_info=True)
        sys.exit(1)

    logger.info(f"🏁 ETL Worker task '{args.task}' finished successfully.")


if __name__ == "__main__":
    main()
