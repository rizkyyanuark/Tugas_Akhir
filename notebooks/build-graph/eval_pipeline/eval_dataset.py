"""Evaluation dataset loader for YUNESA Hybrid GraphRAG.

The evaluation cases are stored as JSON data files so the dataset can be
reviewed, versioned, and edited without touching pipeline code.

Dataset split:
- data/eval_cases_ranked_56.json: 56 main evaluation cases.
- data/eval_cases_guardrail_4.json: 4 out-of-scope guardrail cases.

The public constants below are kept for backward compatibility with the
existing evaluation layers.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from eval_pipeline.paths import DATA_DIR, GUARDRAIL_CASES_PATH, RANKED_CASES_PATH
except Exception:  # pragma: no cover - direct script fallback
    from paths import DATA_DIR, GUARDRAIL_CASES_PATH, RANKED_CASES_PATH


def _load_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Evaluation dataset file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Evaluation dataset must be a list: {path}")
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Evaluation case #{index + 1} in {path.name} is not an object")
        for field in ["id", "category", "intent", "query", "relevant_titles", "key_concepts", "reference_answer"]:
            if field not in item:
                raise ValueError(f"Evaluation case {item.get('id', index + 1)} missing field: {field}")
    return data


RANKED_CASES = _load_cases(RANKED_CASES_PATH)
GUARDRAIL_CASES = _load_cases(GUARDRAIL_CASES_PATH)
EVAL_DATASET = [*RANKED_CASES, *GUARDRAIL_CASES]

CATEGORY_COUNTS = dict(Counter(case["category"] for case in EVAL_DATASET))
TOTAL = len(EVAL_DATASET)
DATASET_INDEX = {case["id"]: case for case in EVAL_DATASET}


def dataset_summary() -> dict[str, Any]:
    """Return a small summary used by reports and CLI checks."""
    return {
        "total": TOTAL,
        "ranked_cases": len(RANKED_CASES),
        "guardrail_cases": len(GUARDRAIL_CASES),
        "category_counts": CATEGORY_COUNTS,
        "data_dir": str(DATA_DIR),
        "ranked_cases_path": str(RANKED_CASES_PATH),
        "guardrail_cases_path": str(GUARDRAIL_CASES_PATH),
    }


if __name__ == "__main__":
    summary = dataset_summary()
    print(f"Total eval cases: {summary['total']}")
    print(f"  Ranked cases:  {summary['ranked_cases']}")
    print(f"  Guardrail:     {summary['guardrail_cases']}")
    for category in ["A", "B", "C", "G"]:
        print(f"  Category {category}: {CATEGORY_COUNTS.get(category, 0)}")
    print()
    print(f"Data directory: {DATA_DIR}")
