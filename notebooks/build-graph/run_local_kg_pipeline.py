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

from yunesa_academic_kg import run_local_kg_pipeline  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and optionally write the YUNESA Academic KG locally.")
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--source", choices=["supabase", "local_csv"], default="supabase")
    parser.add_argument("--graph-name", default="yunesa_academic_kg_local")
    parser.add_argument("--write-neo4j", action="store_true")
    parser.add_argument("--write-milvus", action="store_true")
    parser.add_argument("--clear-neo4j", action="store_true")
    parser.add_argument("--clear-milvus", action="store_true")
    parser.add_argument("--use-extraction", action="store_true", help="Enable GLiNER and GLiREL extraction.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_local_kg_pipeline(
        sample_size=args.sample_size,
        source=args.source,
        graph_name=args.graph_name,
        write_neo4j=args.write_neo4j,
        write_milvus=args.write_milvus,
        clear_neo4j=args.clear_neo4j,
        clear_milvus=args.clear_milvus,
        use_extraction=args.use_extraction,
    )
    printable = {
        "manifest_path": str(result["manifest_path"]),
        "validation": result["validation"],
        "quality": result["quality"],
        "storage_reports": result["storage_reports"],
    }
    print(json.dumps(printable, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
