"""Shared filesystem paths for the KG evaluation pipeline."""

from __future__ import annotations

from pathlib import Path


EVAL_PIPELINE_DIR = Path(__file__).resolve().parent
BUILD_GRAPH_DIR = EVAL_PIPELINE_DIR.parent
REPO_ROOT = BUILD_GRAPH_DIR.parent.parent

OUTPUT_DIR = BUILD_GRAPH_DIR / "outputs" / "evaluation"
BAB4_ARTIFACT_DIR = OUTPUT_DIR / "bab4_artifacts"
DOCS_PROPOSAL_DIR = REPO_ROOT / "docs" / "proposal tugas akhir"
DOCS_GAMBAR_DIR = DOCS_PROPOSAL_DIR / "Gambar"
DOCS_BAB4_EVAL_DIR = DOCS_PROPOSAL_DIR / "generated" / "bab4_eval"

DATA_DIR = EVAL_PIPELINE_DIR / "data"
RANKED_CASES_PATH = DATA_DIR / "eval_cases_ranked_56.json"
GUARDRAIL_CASES_PATH = DATA_DIR / "eval_cases_guardrail_4.json"


def ensure_output_dirs() -> None:
    """Create generated-output directories used by evaluators/exporters."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BAB4_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_GAMBAR_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_BAB4_EVAL_DIR.mkdir(parents=True, exist_ok=True)


def relative_to_repo(path: Path) -> str:
    """Return a stable repo-relative path for logs and manifests."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return str(path)
