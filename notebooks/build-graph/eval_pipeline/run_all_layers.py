"""
run_all_layers.py — Runner untuk semua lapis evaluasi secara berurutan
=======================================================================
Jalankan satu command untuk eksekusi full evaluation pipeline:
  1. Layer 1: Retrieval Quality (Hit@K, MRR, P@K)
  2. Layer 2: Answer Quality (RAGAS / local heuristic)
  3. Layer 3: Mode Comparison (visualisasi komprehensif)
  4. Layer 4: LLM Judge Pairwise Win Rate (Faithfulness, Traceability)
              → Relevan untuk Rumusan Masalah poin 3 (halusinasi & traceability)

Cara jalankan:
  cd notebooks/build-graph
  python -m eval_pipeline.run_all_layers

  Atau tanpa RAGAS (lebih cepat, hanya local heuristics):
  python -m eval_pipeline.run_all_layers --no-ragas

  Untuk hanya jalankan salah satu lapis:
  python -m eval_pipeline.run_all_layers --only-layer 1
  python -m eval_pipeline.run_all_layers --only-layer 2
  python -m eval_pipeline.run_all_layers --only-layer 3
  python -m eval_pipeline.run_all_layers --only-layer 4

  Layer 4 dengan opsi tambahan:
  python -m eval_pipeline.run_all_layers --only-layer 4 --max-cases 15
  python -m eval_pipeline.run_all_layers --only-layer 4 --from-cache
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent.parent
SRC  = HERE / "src"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

# ─────────────────────────────────────────────────────────────────────────────

def banner(text: str) -> None:
    line = "=" * 65
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}\n")


def run_layer1() -> bool:
    banner("LAYER 1 — Retrieval Quality (Hit@K, MRR, Precision@K)")
    t0 = time.perf_counter()
    try:
        from eval_pipeline.layer1_retrieval_metrics import main as l1_main
        l1_main()
        print(f"\n  ✓ Layer 1 completed in {time.perf_counter()-t0:.1f}s")
        return True
    except Exception as e:
        print(f"\n  ✗ Layer 1 FAILED: {e}")
        import traceback; traceback.print_exc()
        return False


def run_layer2(use_ragas: bool = True) -> bool:
    banner("LAYER 2 — Answer Quality (RAGAS + Local Heuristics)")
    t0 = time.perf_counter()
    try:
        from eval_pipeline.layer2_ragas_quality import main as l2_main
        l2_main(use_ragas=use_ragas)
        print(f"\n  ✓ Layer 2 completed in {time.perf_counter()-t0:.1f}s")
        return True
    except Exception as e:
        print(f"\n  ✗ Layer 2 FAILED: {e}")
        import traceback; traceback.print_exc()
        return False


def run_layer3() -> bool:
    banner("LAYER 3 — Mode Comparison (Comprehensive)")
    t0 = time.perf_counter()
    try:
        from eval_pipeline.layer3_mode_comparison import main as l3_main
        l3_main()
        print(f"\n  ✓ Layer 3 completed in {time.perf_counter()-t0:.1f}s")
        return True
    except Exception as e:
        print(f"\n  ✗ Layer 3 FAILED: {e}")
        import traceback; traceback.print_exc()
        return False


def run_layer4(
    challenger_modes: list[str] | None = None,
    max_cases: int | None = None,
    case_ids: list[str] | None = None,
    n_trials: int = 2,
    from_cache: bool = False,
    write_main_outputs: bool = True,
) -> bool:
    banner("LAYER 4 — LLM Judge Pairwise Win Rate (Faithfulness, Traceability, Comprehensiveness)")
    t0 = time.perf_counter()
    try:
        from eval_pipeline.layer4_llm_judge import main as l4_main
        l4_main(
            challenger_modes=challenger_modes,
            max_cases=max_cases,
            case_ids=case_ids,
            n_trials=n_trials,
            skip_generation=from_cache,
            write_main_outputs=write_main_outputs,
        )
        print(f"\n  ✓ Layer 4 completed in {time.perf_counter()-t0:.1f}s")
        return True
    except Exception as e:
        print(f"\n  ✗ Layer 4 FAILED: {e}")
        import traceback; traceback.print_exc()
        return False


def run_bab4_export(*, copy_figures: bool = True, strict: bool = False) -> bool:
    banner("BAB 4 ARTIFACT EXPORT")
    t0 = time.perf_counter()
    try:
        from eval_pipeline.bab4_artifact_export import export_artifacts
        manifest = export_artifacts(copy_figures=copy_figures, strict=strict)
        print(f"\n  Artifacts: {manifest['artifact_dir']}")
        print(f"  Copied PNG figures: {len(manifest['png_figures_copied'])}")
        if manifest["png_figures_missing"]:
            print("  Missing PNG figures:")
            for item in manifest["png_figures_missing"]:
                print(f"    - {item['file']}")
        print(f"\n  [OK] Bab 4 export completed in {time.perf_counter()-t0:.1f}s")
        return True
    except Exception as e:
        print(f"\n  [FAILED] Bab 4 export FAILED: {e}")
        import traceback; traceback.print_exc()
        return False


def print_output_summary() -> None:
    out = HERE / "outputs" / "evaluation"
    banner("OUTPUT SUMMARY")
    if not out.exists():
        print("  No output directory found.")
        return
    for f in sorted(out.iterdir()):
        size = f.stat().st_size
        print(f"  {f.name:50s}  {size:>8,} bytes")
    print(f"\n  All outputs in: {out}")


# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run YUNESA Hybrid Retrieval Evaluation Pipeline"
    )
    p.add_argument(
        "--only-layer", type=int, choices=[1, 2, 3, 4], default=None,
        help="Run only a specific layer (default: run all)"
    )
    p.add_argument(
        "--no-ragas", action="store_true",
        help="Skip RAGAS in Layer 2 (use local heuristics only, faster)"
    )
    p.add_argument(
        "--skip-layer1", action="store_true",
        help="Skip Layer 1 (useful if already have layer1 results)"
    )
    # Layer 4 options
    p.add_argument(
        "--max-cases", type=int, default=None,
        help="[Layer 4] Limit number of cases for quick testing"
    )
    p.add_argument(
        "--case-ids", nargs="+", default=None,
        help="[Layer 4] Explicit case IDs to evaluate, e.g. A01 B01 C01"
    )
    p.add_argument(
        "--trials", type=int, default=2,
        help="[Layer 4] Number of judge trials per pair (default: 2)"
    )
    p.add_argument(
        "--from-cache", action="store_true",
        help="[Layer 4] Skip generation, use cached JSON results"
    )
    p.add_argument(
        "--no-write-main", action="store_true",
        help="[Layer 4] Write partial outputs to a subset folder instead of replacing main Layer 4 files"
    )
    p.add_argument(
        "--l4-modes", nargs="+",
        default=["subgraph", "hybrid"],
        choices=["subgraph", "hybrid"],
        help="[Layer 4] Challenger modes (default: all KG modes)"
    )
    p.add_argument(
        "--export-bab4", action="store_true",
        help="Export LaTeX tables/figures for Bab 4 after the selected run"
    )
    p.add_argument(
        "--no-copy-bab4-figures", action="store_true",
        help="Do not copy generated PNG figures into docs/proposal tugas akhir/Gambar"
    )
    p.add_argument(
        "--strict-bab4-export", action="store_true",
        help="Fail Bab 4 export if optional inputs or PNG figures are missing"
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    from yunesa_academic_kg import KGConfig, load_project_env
    config = KGConfig.default()
    load_project_env(config.project_root)

    total_start = time.perf_counter()
    statuses: dict[int, bool | None] = {1: None, 2: None, 3: None, 4: None}

    if args.only_layer == 1:
        statuses[1] = run_layer1()
    elif args.only_layer == 2:
        statuses[2] = run_layer2(use_ragas=not args.no_ragas)
    elif args.only_layer == 3:
        statuses[3] = run_layer3()
    elif args.only_layer == 4:
        statuses[4] = run_layer4(
            challenger_modes=args.l4_modes,
            max_cases=args.max_cases,
            case_ids=args.case_ids,
            n_trials=args.trials,
            from_cache=args.from_cache,
            write_main_outputs=not args.no_write_main,
        )
    else:
        # Full pipeline
        if not args.skip_layer1:
            statuses[1] = run_layer1()
        else:
            print("[SKIP] Layer 1 (--skip-layer1)")
            statuses[1] = True

        if statuses[1] is not False:
            statuses[2] = run_layer2(use_ragas=not args.no_ragas)
        else:
            print("[SKIP] Layer 2 (Layer 1 failed)")

        # Layer 3 only needs Layer 1 results
        if statuses[1] is not False:
            statuses[3] = run_layer3()

        # Layer 4 runs independently (needs Groq API)
        print("\n[INFO] Layer 4 (LLM Judge) not run by default in full pipeline.")
        print("       Run separately: python eval_pipeline/run_all_layers.py --only-layer 4")
        statuses[4] = None

    total = time.perf_counter() - total_start

    banner(f"EVALUATION COMPLETE — {total:.1f}s total")
    for layer, ok in statuses.items():
        if ok is None:
            icon = "–"
            desc = "skipped"
        elif ok:
            icon = "✓"
            desc = "passed"
        else:
            icon = "✗"
            desc = "FAILED"
        print(f"  Layer {layer}: {icon} {desc}")

    print_output_summary()
    if args.export_bab4:
        run_bab4_export(
            copy_figures=not args.no_copy_bab4_figures,
            strict=args.strict_bab4_export,
        )


if __name__ == "__main__":
    main()
