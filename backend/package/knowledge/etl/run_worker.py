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
        1. Add a handler in knowledge.etl.pipelines.<your_pipeline>
        2. Add it to the TASKS dict in that module
    3. Add the DockerOperator task in the DAG file
"""
import argparse
import importlib
import logging
import pkgutil
import sys
from collections.abc import Callable

from knowledge.etl import pipelines as pipelines_pkg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("etl-worker")


# ═════════════════════════════════════════════════════════════════════=
#  TASK REGISTRY — Must match DAG DockerOperator `command=` values
# ═════════════════════════════════════════════════════════════════════=

def _load_task_registry() -> dict[str, Callable[[bool], None]]:
    registry: dict[str, Callable[[bool], None]] = {}

    for module_info in pkgutil.iter_modules(pipelines_pkg.__path__, pipelines_pkg.__name__ + "."):
        module = importlib.import_module(module_info.name)
        tasks = getattr(module, "TASKS", None)
        if not isinstance(tasks, dict):
            continue

        duplicates = set(tasks).intersection(registry)
        if duplicates:
            raise ValueError(
                f"Duplicate task names found: {sorted(duplicates)}")

        registry.update(tasks)

    return registry


TASK_REGISTRY = _load_task_registry()
TASK_CHOICES = sorted(TASK_REGISTRY.keys())


def _dispatch_task(task: str, test_mode: bool):
    """Route a task name to its handler."""
    try:
        handler = TASK_REGISTRY[task]
    except KeyError as exc:
        raise ValueError(f"Unknown task: {task}") from exc

    handler(test_mode)


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

            logger.info(
                f"🔄 Hot-Reload enabled. Watching for changes... (Task: {args.task})")

            # Create a partial function that calls the dispatcher
            # This is what watchfiles will restart on every change.
            task_func = functools.partial(
                _dispatch_task, args.task, args.test_mode)

            # Watch the package directory (where the logic lives)
            package_dir = os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))
            run_process(package_dir, target=task_func)

        except ImportError:
            logger.warning(
                "⚠️ watchfiles not found. Running task once without reload.")
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
