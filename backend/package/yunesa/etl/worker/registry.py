"""Task registry discovery for ETL pipeline modules."""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable

from yunesa.etl import pipelines as pipelines_pkg
from yunesa.etl.worker.runtime import RunConfig

TaskHandler = Callable[[RunConfig], None]


def load_task_registry() -> dict[str, TaskHandler]:
    """Import pipeline modules and collect their ``TASKS`` dictionaries."""
    registry: dict[str, TaskHandler] = {}

    for module_info in pkgutil.iter_modules(pipelines_pkg.__path__, pipelines_pkg.__name__ + "."):
        module = importlib.import_module(module_info.name)
        tasks = getattr(module, "TASKS", None)
        if not isinstance(tasks, dict):
            continue

        duplicates = set(tasks).intersection(registry)
        if duplicates:
            raise ValueError(f"Duplicate ETL task names found: {sorted(duplicates)}")

        registry.update(tasks)

    return registry


TASK_REGISTRY: dict[str, TaskHandler] = load_task_registry()
TASK_CHOICES: list[str] = sorted(TASK_REGISTRY.keys())


def dispatch_task(task: str, config: RunConfig) -> None:
    """Route a task name to its handler."""
    try:
        handler = TASK_REGISTRY[task]
    except KeyError as exc:
        raise ValueError(f"Unknown ETL task: {task}") from exc

    handler(config)

