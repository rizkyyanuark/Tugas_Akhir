"""ETL Worker CLI.

Airflow calls this module from DockerOperator with commands such as:

    python -m knowledge.etl.run_worker lec_extract_web --mode incremental

The worker is intentionally independent from Airflow. Airflow only injects
environment variables and selects the task name; this module resolves the run
configuration and dispatches to task handlers registered by pipeline modules.
"""

from __future__ import annotations

import argparse
import functools
import logging
import os
import sys

from knowledge.etl.config import ETL_RUN_MODE, ETL_SAMPLE_SIZE
from knowledge.etl.utils.logging import configure_etl_logging, log_error, log_event, timed_event
from knowledge.etl.worker import RunConfig, TASK_CHOICES, TASK_REGISTRY, dispatch_task

configure_etl_logging()
logger = logging.getLogger("etl-worker")

# Backward-compatible alias for older tests/imports.
_dispatch_task = dispatch_task


def _print_available_tasks() -> None:
    print("\nAvailable Tasks:")
    last_prefix = ""
    for task_name in TASK_CHOICES:
        prefix = task_name.split("_", 1)[0]
        if prefix != last_prefix:
            print(f"  {prefix.upper()}:")
            last_prefix = prefix
        print(f"    - {task_name}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Yunesa ETL Worker CLI")
    parser.add_argument(
        "task",
        nargs="?",
        choices=TASK_CHOICES,
        help="Name of the ETL task to execute. Omit to list tasks.",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "incremental", "sample"],
        default=None,
        help="Run mode: full, incremental, or sample.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Number of records to process in sample mode.",
    )
    parser.add_argument(
        "--prodi",
        type=str,
        default=None,
        help="Specific study-program code to process, for example S1-TI.",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        default=False,
        help="[DEPRECATED] Alias for --mode sample.",
    )
    return parser


def _resolve_run_config(args: argparse.Namespace) -> RunConfig:
    if args.test_mode and not args.mode:
        mode = "sample"
        logger.warning("config.deprecated_flag | flag=--test-mode | replacement=--mode sample")
    elif args.mode:
        mode = args.mode
    else:
        mode = ETL_RUN_MODE

    return RunConfig(
        mode=mode,
        sample_size=args.sample_size or ETL_SAMPLE_SIZE,
        prodi_filter=args.prodi,
    )


def _run_with_optional_reload(task_name: str, config: RunConfig) -> None:
    reload_enabled = os.environ.get("BACKEND_RELOAD", "").lower() == "true"

    if not reload_enabled:
        dispatch_task(task_name, config)
        return

    try:
        from watchfiles import run_process
    except ImportError:
        logger.warning("reload.unavailable | package=watchfiles | action=run_once")
        dispatch_task(task_name, config)
        return

    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_event(logger, "reload.enabled", package_dir=package_dir)
    task_func = functools.partial(dispatch_task, task_name, config)
    run_process(package_dir, target=task_func)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.task:
        parser.print_help()
        _print_available_tasks()
        sys.exit(0)

    config = _resolve_run_config(args)
    log_event(
        logger,
        "task.start",
        task=args.task,
        mode=config.mode,
        sample_size=config.sample_size if config.is_sample else None,
        prodi_filter=config.prodi_filter,
    )

    try:
        with timed_event(logger, "task.run", task=args.task):
            _run_with_optional_reload(args.task, config)
    except Exception as exc:
        log_error(logger, "task.failed", exc=exc, task=args.task)
        sys.exit(1)

    log_event(logger, "task.success", task=args.task)


if __name__ == "__main__":
    main()
