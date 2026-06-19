"""Run YUNESA Academic KG construction locally.

This script is intentionally thin: production logic lives in
`src/yunesa_academic_kg.py`, while this file provides a repeatable terminal
entry point for local debugging against Supabase, AuraDB, and Zilliz.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import warnings


os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TQDM_DISABLE", "1")

warnings.filterwarnings("ignore", message=r"The `resume_download` argument is deprecated.*")
warnings.filterwarnings("ignore", message=r"Sentence of length .* has been truncated.*")

try:
    from huggingface_hub.utils import disable_progress_bars

    disable_progress_bars()
except Exception:
    pass

try:
    from transformers.utils import logging as transformers_logging

    transformers_logging.set_verbosity_error()
except Exception:
    pass

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from yunesa_academic_kg import extraction_runtime_status, run_local_kg_pipeline  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and optionally write the YUNESA Academic KG locally.")
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--source", choices=["supabase", "local_csv"], default="supabase")
    parser.add_argument("--graph-name", default="yunesa_academic_kg_local")
    parser.add_argument("--write-neo4j", action="store_true")
    parser.add_argument("--write-milvus", action="store_true")
    parser.add_argument("--clear-neo4j", action="store_true")
    parser.add_argument("--clear-milvus", action="store_true")
    parser.add_argument(
        "--use-gliner",
        action="store_true",
        help="Enable GLiNER zero-shot NER. Ontology relations are mapped deterministically.",
    )
    parser.add_argument(
        "--use-glirel",
        action="store_true",
        help="Enable GLiREL relation extraction as an explicit ablation path.",
    )
    parser.add_argument(
        "--use-extraction",
        action="store_true",
        help="Backward-compatible alias for --use-gliner. Does not enable GLiREL.",
    )
    parser.add_argument("--preflight-only", action="store_true", help="Only print optional extraction readiness.")
    return parser.parse_args()


def _compact_result(result: dict) -> dict:
    return {
        "manifest_path": str(result["manifest_path"]),
        "validation": result["validation"],
        "quality": result["quality"],
        "storage_reports": result["storage_reports"],
    }


def _failed_quality_gates(result: dict) -> dict[str, bool]:
    gates = result.get("quality", {}).get("quality_gates", {})
    return {name: value for name, value in gates.items() if value is not True}


def main() -> int:
    args = parse_args()
    use_gliner = args.use_gliner or args.use_extraction
    runtime_status = extraction_runtime_status()
    if args.preflight_only:
        print(json.dumps({"extraction_runtime": runtime_status}, indent=2, ensure_ascii=False, default=str))
        if use_gliner and not runtime_status.get("gliner_ready"):
            return 2
        if args.use_glirel and not runtime_status.get("glirel_ready"):
            return 2
        return 0

    if use_gliner and not runtime_status.get("gliner_ready"):
        print(json.dumps({"error": "GLiNER runtime is not ready", "extraction_runtime": runtime_status}, indent=2))
        return 2
    if args.use_glirel and not runtime_status.get("glirel_ready"):
        print(json.dumps({"error": "GLiREL runtime is not ready", "extraction_runtime": runtime_status}, indent=2))
        return 2

    result = run_local_kg_pipeline(
        sample_size=args.sample_size,
        source=args.source,
        graph_name=args.graph_name,
        write_neo4j=args.write_neo4j,
        write_milvus=args.write_milvus,
        clear_neo4j=args.clear_neo4j,
        clear_milvus=args.clear_milvus,
        use_extraction=use_gliner,
        use_gliner=use_gliner,
        use_glirel=args.use_glirel,
    )
    printable = _compact_result(result)
    print(json.dumps(printable, indent=2, ensure_ascii=False, default=str))
    failed_gates = _failed_quality_gates(result)
    if failed_gates:
        print(json.dumps({"error": "KG quality gates failed", "failed_gates": failed_gates}, indent=2))
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
