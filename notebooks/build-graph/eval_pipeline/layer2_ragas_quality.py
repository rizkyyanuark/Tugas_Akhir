"""
layer2_ragas_quality.py — Lapis 2: Answer Quality via RAGAS + LLM-as-Judge
============================================================================
Mengukur KUALITAS JAWABAN yang dihasilkan LLM menggunakan framework RAGAS.

Metrik yang dihitung (tanpa reference, non-LLM-judge variants):
  - faithfulness       : apakah klaim dalam jawaban didukung konteks retrieval?
  - answer_relevancy   : apakah jawaban relevan dengan pertanyaan?
  - context_recall     : seberapa banyak informasi relevan ada di konteks?
  - context_precision  : seberapa padat/presisi konteks yang diambil?

Mode yang dievaluasi: subgraph, mix (mode terbaik dari Lapis 1)
Kategori: A dan B (kecuali Guardrail)

Cara jalankan:
  cd notebooks/build-graph
  python -m eval_pipeline.layer2_ragas_quality

Dependensi:
  pip install ragas datasets langchain_openai
  (RAGAS menggunakan LLM untuk judge — gunakan Gemini atau GPT-4o)
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock
# Mock the deprecated langchain_community.chat_models.vertexai module to prevent RAGAS imports from crashing
sys.modules['langchain_community.chat_models.vertexai'] = MagicMock()

import json
import os
import time
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ── path setup ──────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent.parent
SRC  = HERE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from yunesa_academic_kg import (                        # noqa: E402
    GraphRAGQueryParam,
    GraphRAGGenerationParam,
    KGConfig,
    format_graphrag_context,
    generate_graphrag_answer_with_groq,
    graphrag_retrieve,
    load_project_env,
)

sys.path.insert(0, str(HERE))
from eval_pipeline.eval_dataset import EVAL_DATASET    # noqa: E402

# ── constants ────────────────────────────────────────────────────────────────
GRAPH_NAME     = "yunesa_academic_kg"
TOP_K          = 10
EVAL_MODES     = ["subgraph", "hybrid"]    # evaluate best modes from Layer 1
GROQ_MODEL     = "deepseek-v4-flash"
OUT_DIR        = HERE / "outputs" / "evaluation"

# RAGAS judge LLM: gunakan DeepSeek-V3, Google Gemini, atau OpenAI-compatible.
RAGAS_LLM_PROVIDER = "deepseek"  # "deepseek" | "gemini" | "openai" | "groq"


# ── LLM setup untuk RAGAS ────────────────────────────────────────────────────

def get_ragas_llm_and_embeddings():
    """Return (llm, embeddings) tuple for RAGAS evaluation."""
    if RAGAS_LLM_PROVIDER == "deepseek":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model="deepseek-v4-flash",
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url=os.environ.get("DEEPSEEK_API_BASE") or "https://api.deepseek.com",
            temperature=0.1,
        )
        
        from langchain_openai import OpenAIEmbeddings
        embeddings = OpenAIEmbeddings(
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=os.environ.get("SILICONFLOW_API_KEY"),
            base_url="https://api.siliconflow.com/v1",
        )
        return llm, embeddings

    if RAGAS_LLM_PROVIDER == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
                google_api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
            )
            embeddings = GoogleGenerativeAIEmbeddings(
                model="models/text-embedding-004",
                google_api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
            )
            return llm, embeddings
        except ImportError:
            print("[WARN] langchain-google-genai not installed. Falling back to openai-compatible.")

    if RAGAS_LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=os.environ.get("OPENAI_API_KEY"),
        )
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=os.environ.get("OPENAI_API_KEY"),
        )
        return llm, embeddings


# ── retrieval + answer generation ─────────────────────────────────────────────

def get_answer_and_context(query: str, mode: str) -> dict[str, Any]:
    """Run full retrieval + LLM generation pipeline for one query."""
    t0 = time.perf_counter()
    retrieval = graphrag_retrieve(
        query,
        param=GraphRAGQueryParam(mode=mode, top_k=TOP_K, graph_name=GRAPH_NAME),
    )
    answer_obj = generate_graphrag_answer_with_groq(
        query,
        retrieval,
        param=GraphRAGGenerationParam(
            model=GROQ_MODEL,
            max_tokens=600,
            temperature=0.1,
        ),
    )
    context_str = format_graphrag_context(retrieval, max_chars=6000)
    latency = time.perf_counter() - t0

    # Split context into sentences/chunks for RAGAS (expects list of strings)
    context_chunks = [
        chunk.strip()
        for chunk in context_str.split("\n")
        if len(chunk.strip()) > 20
    ][:20]

    return {
        "question":        query,
        "answer":          answer_obj["answer"],
        "contexts":        context_chunks,
        "context_full":    context_str,
        "latency":         round(latency, 3),
        "usage":           answer_obj.get("usage"),
    }


# ── RAGAS evaluation ──────────────────────────────────────────────────────────

def run_ragas_evaluation(
    samples: list[dict],
    llm,
    embeddings,
) -> dict:
    """
    Run RAGAS evaluation on a list of samples.
    Each sample: {question, answer, contexts, ground_truth}
    Returns: dict of metric_name -> list[float]
    """
    try:
        from ragas import evaluate as ragas_evaluate
        from ragas.metrics import (
            faithfulness,
            answer_relevancy,
            context_recall,
            context_precision,
        )
        from datasets import Dataset
    except ImportError as e:
        print(f"[ERROR] ragas/datasets not installed: {e}")
        print("Install with: pip install ragas datasets")
        return {}

    dataset = Dataset.from_dict({
        "question":    [s["question"]    for s in samples],
        "answer":      [s["answer"]      for s in samples],
        "contexts":    [s["contexts"]    for s in samples],
        "ground_truth":[s["ground_truth"] for s in samples],
    })

    result = ragas_evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy, context_recall, context_precision],
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=False,
    )
    return result.to_pandas().to_dict(orient="list")


# ── lightweight faithfulness fallback (no external LLM needed) ───────────────

def faithfulness_local(answer: str, contexts: list[str]) -> float:
    """
    Simple heuristic faithfulness: what fraction of answer sentences
    can be grounded in at least one context chunk?
    (No LLM needed — useful as fast sanity check)
    """
    import re
    sentences = [s.strip() for s in re.split(r'[.!?]', answer) if len(s.strip()) > 10]
    if not sentences:
        return 0.0

    ctx_combined = " ".join(contexts).casefold()
    grounded = 0
    for sent in sentences:
        sent_words = [w for w in sent.casefold().split() if len(w) >= 4]
        if not sent_words:
            continue
        # sentence is "grounded" if ≥50% of its keywords appear in context
        matches = sum(1 for w in sent_words if w in ctx_combined)
        if matches / len(sent_words) >= 0.50:
            grounded += 1
    return grounded / len(sentences)


def answer_relevancy_local(query: str, answer: str) -> float:
    """
    Simple heuristic: what fraction of query keywords appear in answer?
    """
    q_words = [w for w in query.casefold().split() if len(w) >= 3]
    if not q_words:
        return 0.0
    a_lower = answer.casefold()
    return sum(1 for w in q_words if w in a_lower) / len(q_words)


# ── main evaluation loop ──────────────────────────────────────────────────────

def evaluate_layer2(cases: list[dict], modes: list[str], use_ragas: bool = True) -> dict:
    """
    Returns: {
      mode: {
        case_id: {answer, contexts, faithfulness, answer_relevancy, ...}
      }
    }
    """
    all_results: dict[str, dict] = {m: {} for m in modes}

    ragas_llm, ragas_emb = None, None
    if use_ragas:
        try:
            ragas_llm, ragas_emb = get_ragas_llm_and_embeddings()
        except Exception as e:
            print(f"[WARN] Could not initialize RAGAS LLM: {e}. Using local heuristics.")
            use_ragas = False

    # Collect samples per mode
    for mode in modes:
        print(f"\n{'='*60}")
        print(f"Mode: {mode.upper()}")
        print(f"{'='*60}")

        mode_samples: list[dict] = []
        mode_case_ids: list[str] = []

        for case in cases:
            if case["category"] == "G":
                continue
            print(f"  [{case['id']}] Retrieving + generating ...", end=" ", flush=True)
            try:
                res = get_answer_and_context(case["query"], mode)
                res["ground_truth"]  = case["reference_answer"]
                res["case_id"]       = case["id"]
                res["category"]      = case["category"]
                mode_samples.append(res)
                mode_case_ids.append(case["id"])
                print(f"OK (lat={res['latency']}s)")
            except Exception as exc:
                print(f"ERROR: {exc}")

        # Compute metrics
        if use_ragas and ragas_llm and mode_samples:
            print(f"\n  Running RAGAS evaluation ({len(mode_samples)} samples)...")
            try:
                ragas_result = run_ragas_evaluation(mode_samples, ragas_llm, ragas_emb)
            except Exception as e:
                print(f"  [WARN] RAGAS failed: {e}. Falling back to local heuristics.")
                ragas_result = {}
        else:
            ragas_result = {}

        for i, sample in enumerate(mode_samples):
            cid = sample["case_id"]
            faith = (
                ragas_result.get("faithfulness", [None] * (i + 1))[i]
                if ragas_result else None
            )
            arel = (
                ragas_result.get("answer_relevancy", [None] * (i + 1))[i]
                if ragas_result else None
            )
            cprec = (
                ragas_result.get("context_precision", [None] * (i + 1))[i]
                if ragas_result else None
            )
            crec = (
                ragas_result.get("context_recall", [None] * (i + 1))[i]
                if ragas_result else None
            )

            # Local heuristics as fallback / complement
            faith_local = faithfulness_local(sample["answer"], sample["contexts"])
            arel_local  = answer_relevancy_local(sample["question"], sample["answer"])

            all_results[mode][cid] = {
                "category":           sample["category"],
                "question":           sample["question"],
                "answer":             sample["answer"],
                "ground_truth":       sample["ground_truth"],
                "contexts_count":     len(sample["contexts"]),
                "latency":            sample["latency"],
                # RAGAS metrics (None if unavailable)
                "faithfulness_ragas":     faith,
                "answer_relevancy_ragas": arel,
                "context_precision_ragas":cprec,
                "context_recall_ragas":   crec,
                # Local heuristic fallback
                "faithfulness_local":     round(faith_local, 4),
                "answer_relevancy_local": round(arel_local, 4),
            }

    return all_results


# ── aggregation ───────────────────────────────────────────────────────────────

def aggregate_layer2(results: dict, category_filter: str | None = None) -> dict:
    agg: dict[str, dict] = {}
    for mode, cases in results.items():
        filtered = {
            cid: v for cid, v in cases.items()
            if category_filter is None or v["category"] == category_filter
        }
        n = len(filtered)
        if n == 0:
            continue

        def mean_metric(key: str) -> float | None:
            vals = [v[key] for v in filtered.values() if v.get(key) is not None]
            return round(sum(vals) / len(vals), 4) if vals else None

        agg[mode] = {
            "n":                        n,
            "faithfulness_ragas":       mean_metric("faithfulness_ragas"),
            "answer_relevancy_ragas":   mean_metric("answer_relevancy_ragas"),
            "context_precision_ragas":  mean_metric("context_precision_ragas"),
            "context_recall_ragas":     mean_metric("context_recall_ragas"),
            "faithfulness_local":       mean_metric("faithfulness_local"),
            "answer_relevancy_local":   mean_metric("answer_relevancy_local"),
            "avg_latency_s":            mean_metric("latency"),
        }
    return agg


# ── visualization ─────────────────────────────────────────────────────────────

def plot_layer2(agg_all: dict, agg_A: dict, agg_B: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    modes  = list(agg_all.keys())
    colors = {"naive": "#7F8C8D", "subgraph": "#2980B9", "hybrid": "#27AE60"}

    # Radar chart: per mode, semua metrik
    metrics_local = ["faithfulness_local", "answer_relevancy_local"]
    metrics_ragas = ["faithfulness_ragas", "answer_relevancy_ragas",
                     "context_precision_ragas", "context_recall_ragas"]

    # Use whichever metrics are available
    available_metrics = [
        m for m in metrics_ragas
        if any(agg_all.get(mode, {}).get(m) is not None for mode in modes)
    ] or metrics_local

    labels = [m.replace("_ragas", "").replace("_local", "").replace("_", " ").title()
              for m in available_metrics]
    N = len(labels)
    if N < 2:
        return

    fig, axes = plt.subplots(1, len(modes), figsize=(5 * len(modes), 5),
                             subplot_kw=dict(polar=True))
    if len(modes) == 1:
        axes = [axes]

    for ax, mode in zip(axes, modes):
        vals_all = [agg_all.get(mode, {}).get(m) or 0 for m in available_metrics]
        vals_A   = [agg_A.get(mode, {}).get(m) or 0 for m in available_metrics]
        vals_B   = [agg_B.get(mode, {}).get(m) or 0 for m in available_metrics]

        angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
        angles += angles[:1]

        for vals, label, color, alpha in [
            (vals_all, "Semua", "#2C3E50", 0.15),
            (vals_A,   "Kat. A", "#2980B9", 0.25),
            (vals_B,   "Kat. B", "#E74C3C", 0.25),
        ]:
            v = vals + vals[:1]
            ax.plot(angles, v, color=color, linewidth=1.8, label=label)
            ax.fill(angles, v, color=color, alpha=alpha)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels, fontsize=7.5)
        ax.set_ylim(0, 1)
        ax.set_yticks([0.25, 0.5, 0.75, 1.0])
        ax.set_yticklabels(["0.25", "0.5", "0.75", "1.0"], fontsize=6.5)
        # ax.set_title(f"Mode: {mode.capitalize()}", fontsize=10, pad=14, fontweight="bold",
        #              color=colors.get(mode, "#2C3E50"))
        ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.15), fontsize=7)

    fig.tight_layout()
    p = out_dir / "eval_layer2_radar.png"
    fig.savefig(p, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"[SAVED] {p.name}")

    # Bar chart: answer quality comparison between modes
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x   = np.arange(len(labels))
    w   = 0.35 / max(len(modes), 1)
    off = -(len(modes) - 1) * w / 2
    for i, mode in enumerate(modes):
        vals = [agg_all.get(mode, {}).get(m) or 0 for m in available_metrics]
        ax.bar(x + off + i * w, vals, w,
               label=mode.capitalize(),
               color=colors.get(mode, "#95A5A6"),
               edgecolor="white", linewidth=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Skor Metrik", fontsize=9)
    ax.legend(fontsize=8.5, framealpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, linestyle="--", alpha=0.4)
    fig.tight_layout()
    p = out_dir / "eval_layer2_bar.png"
    fig.savefig(p, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"[SAVED] {p.name}")


# ── report ────────────────────────────────────────────────────────────────────

def write_report_layer2(results: dict, agg_all: dict, agg_A: dict, agg_B: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "results_per_case": results,
        "aggregate": {"all": agg_all, "category_A": agg_A, "category_B": agg_B},
    }
    (out_dir / "eval_layer2_results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )

    def fmt(v): return f"{v:.4f}" if isinstance(v, float) else str(v or "-")

    lines = [
        "# Laporan Evaluasi Lapis 2: Answer Quality (RAGAS + Local Heuristic)",
        "",
        "## Agregat Semua Query",
        "",
        "| Mode | n | Faithfulness | Ans.Relevancy | Ctx.Precision | Ctx.Recall | Lat.(s) |",
        "|------|---|-------------|--------------|--------------|-----------|---------|",
    ]
    for mode in EVAL_MODES:
        a = agg_all.get(mode, {})
        if not a.get("n"):
            continue
        lines.append(
            f"| {mode} | {a['n']} | "
            f"{fmt(a.get('faithfulness_ragas') or a.get('faithfulness_local'))} | "
            f"{fmt(a.get('answer_relevancy_ragas') or a.get('answer_relevancy_local'))} | "
            f"{fmt(a.get('context_precision_ragas'))} | "
            f"{fmt(a.get('context_recall_ragas'))} | "
            f"{fmt(a.get('avg_latency_s'))} |"
        )

    lines += ["", "## Detail Jawaban per Case", ""]
    for mode, cases in results.items():
        lines.append(f"### Mode: {mode}")
        for cid, v in sorted(cases.items()):
            lines.extend([
                f"**[{cid}] {v['question'][:70]}**",
                f"- Faithfulness (local): {v['faithfulness_local']}",
                f"- Answer Relevancy (local): {v['answer_relevancy_local']}",
                f"- Jawaban: {v['answer'][:200]}...",
                "",
            ])

    (out_dir / "eval_layer2_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("[SAVED] eval_layer2_report.md")


# ── main ──────────────────────────────────────────────────────────────────────

def main(use_ragas: bool = True) -> None:
    config = KGConfig.default()
    load_project_env(config.project_root)

    eval_cases = [c for c in EVAL_DATASET if c["category"] != "G"]
    print(f"Layer 2 evaluation: {len(eval_cases)} cases × {len(EVAL_MODES)} modes")
    print(f"RAGAS enabled: {use_ragas}")

    results  = evaluate_layer2(eval_cases, EVAL_MODES, use_ragas=use_ragas)
    agg_all  = aggregate_layer2(results)
    agg_A    = aggregate_layer2(results, "A")
    agg_B    = aggregate_layer2(results, "B")

    print("\n\n═══ ANSWER QUALITY SUMMARY ═══")
    for mode in EVAL_MODES:
        a = agg_all.get(mode, {})
        if not a.get("n"):
            continue
        print(f"  {mode}: faithfulness={a.get('faithfulness_local'):.3f}  "
              f"relevancy={a.get('answer_relevancy_local'):.3f}")

    plot_layer2(agg_all, agg_A, agg_B, OUT_DIR)
    write_report_layer2(results, agg_all, agg_A, agg_B, OUT_DIR)
    print(f"\n[DONE] {OUT_DIR}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ragas", action="store_true",
                        help="Skip RAGAS (use local heuristics only)")
    args = parser.parse_args()
    main(use_ragas=not args.no_ragas)
