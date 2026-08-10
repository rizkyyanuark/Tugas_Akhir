"""Run AcademicRAG-style retrieval over the YUNESA KG storage layer."""

from __future__ import annotations

import argparse
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
PROJECT_ROOT = HERE.parents[1]
BACKEND_PKG_PATH = PROJECT_ROOT / "backend" / "package"

# Prefer production package import; fallback to legacy src/ path
if str(BACKEND_PKG_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PKG_PATH))
try:
    from knowledge.etl.kg.yunesa_academic_kg import (  # noqa: E402
        GraphRAGGenerationParam,
        GraphRAGQueryParam,
        KGConfig,
        format_graphrag_context,
        generate_graphrag_answer_with_groq,
        graphrag_retrieve,
        inspect_milvus_collections,
        inspect_neo4j_graph,
        load_project_env,
    )
except ImportError:
    SRC = HERE / "src"
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from yunesa_academic_kg import (  # noqa: E402
        GraphRAGGenerationParam,
        GraphRAGQueryParam,
        KGConfig,
        format_graphrag_context,
        generate_graphrag_answer_with_groq,
        graphrag_retrieve,
        inspect_milvus_collections,
        inspect_neo4j_graph,
        load_project_env,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local GraphRAG retrieval diagnostics.")
    parser.add_argument("query", nargs="?", default="retinopati diabetik menggunakan EfficientNet dan dataset APTOS")
    parser.add_argument("--mode", choices=["naive", "subgraph", "global", "hybrid", "mix"], default="mix")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--graph-name", default="yunesa_academic_kg_local")
    parser.add_argument("--skip-storage-inspect", action="store_true")
    parser.add_argument("--generate", action="store_true", help="Call Groq to synthesize a grounded answer.")
    parser.add_argument("--model", default="llama-3.3-70b-versatile")
    parser.add_argument("--max-tokens", type=int, default=700)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = KGConfig.default()
    load_project_env(config.project_root)

    if not args.skip_storage_inspect:
        print("Neo4j:")
        print(inspect_neo4j_graph(graph_name=args.graph_name))
        print("\nMilvus:")
        print(inspect_milvus_collections())
        print()

    retrieval = graphrag_retrieve(
        args.query,
        param=GraphRAGQueryParam(mode=args.mode, top_k=args.top_k, graph_name=args.graph_name),
    )
    print(format_graphrag_context(retrieval))
    if args.generate:
        print("\nGroq answer:")
        answer = generate_graphrag_answer_with_groq(
            args.query,
            retrieval,
            param=GraphRAGGenerationParam(model=args.model, max_tokens=args.max_tokens),
        )
        print(answer["answer"])
        print("\nUsage:")
        print(answer["usage"])


if __name__ == "__main__":
    main()
