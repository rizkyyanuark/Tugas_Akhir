"""Generate LLM-assisted concept alias suggestions from a KG build report.

This script is intentionally review-only. It does not mutate Neo4j, Milvus, or
the canonical alias file. Review accepted suggestions in the Yunesa entity
resolution UI, then export the approved YAML for the KG construction pipeline.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
BACKEND_PKG_PATH = PROJECT_ROOT / "backend" / "package"

# Prefer production package import; fallback to legacy src/ path
if str(BACKEND_PKG_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PKG_PATH))
try:
    from yunesa.knowledge import LLMAliasSuggestionConfig, load_project_env, write_llm_alias_suggestions
except ImportError:
    SRC_DIR = HERE / "src"
    sys.path.insert(0, str(SRC_DIR))
    from yunesa_academic_kg import LLMAliasSuggestionConfig, load_project_env, write_llm_alias_suggestions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate LLM-assisted KG entity-resolution suggestions.")
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "data" / "kg_pipeline_test" / "kg" / "output" / "kg_entity_resolution_report.json",
        help="Path to kg_entity_resolution_report.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "kg" / "entity_resolution" / "concept_alias_suggestions.json",
        help="Output JSON path for suggestions.",
    )
    parser.add_argument("--provider", default=os.getenv("YUNESA_ENTITY_RESOLUTION_LLM_PROVIDER", "groq"))
    parser.add_argument("--model", default=os.getenv("YUNESA_ENTITY_RESOLUTION_LLM_MODEL", "llama-3.3-70b-versatile"))
    parser.add_argument("--max-candidates", type=int, default=int(os.getenv("YUNESA_ENTITY_RESOLUTION_LLM_MAX_CANDIDATES", "60")))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("YUNESA_ENTITY_RESOLUTION_LLM_BATCH_SIZE", "15")))
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=float(os.getenv("YUNESA_ENTITY_RESOLUTION_LLM_MIN_CONFIDENCE", "0.95")),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_project_env(PROJECT_ROOT)
    if not args.report.exists():
        raise FileNotFoundError(f"Entity-resolution report not found: {args.report}")

    config = LLMAliasSuggestionConfig(
        provider=args.provider,
        model=args.model,
        max_candidates=max(1, args.max_candidates),
        batch_size=max(1, args.batch_size),
        min_confidence_for_auto_candidate=args.min_confidence,
    )
    result = write_llm_alias_suggestions(args.report, args.output, config=config)
    print(
        "LLM alias suggestions generated | "
        f"candidates={result['candidate_count']} | "
        f"suggestions={result['suggestion_count']} | "
        f"errors={len(result['errors'])} | "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
