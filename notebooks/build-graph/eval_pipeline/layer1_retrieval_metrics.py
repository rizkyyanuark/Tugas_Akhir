"""
layer1_retrieval_metrics.py — Lapis 1: Hit Rate & MRR Evaluasi
================================================================
Mengukur KUALITAS RETRIEVAL tanpa LLM — murni apakah dokumen yang
benar berhasil diambil oleh sistem.

Metrik yang dihitung per mode:
  - Hit@K   : proporsi query di mana ≥1 paper relevan masuk top-K
  - MRR     : Mean Reciprocal Rank — 1/rank_paper_relevan_pertama
  - Precision@K : berapa fraksi dari top-K yang memang relevan

Mode yang dibandingkan: naive, subgraph, hybrid
Kategori yang dibandingkan:
  A (Factual-Hard)   — 20 kasus, query implisit tanpa sebut judul
  B (Relational)     — 30 kasus, butuh entity traversal
  C (Multi-hop)      — 6 kasus, ≥2 hop graf diperlukan

Cara jalankan:
  cd notebooks/build-graph
  python -m eval_pipeline.layer1_retrieval_metrics
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ── path setup ──────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent.parent          # notebooks/build-graph
SRC  = HERE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from yunesa_academic_kg import (                        # noqa: E402
    GraphRAGQueryParam,
    KGConfig,
    graphrag_retrieve,
    load_project_env,
)

# ── local imports ────────────────────────────────────────────────────────────
sys.path.insert(0, str(HERE))
from eval_pipeline.eval_dataset import EVAL_DATASET, RANKED_CASES  # noqa: E402

# ── constants ────────────────────────────────────────────────────────────────
GRAPH_NAME = "yunesa_academic_kg"
TOP_K      = 10          # retrieve top-10, measure @1,3,5,10
K_VALUES   = [1, 3, 5, 10]
MODES      = ["naive", "subgraph", "hybrid"]
OUT_DIR    = HERE / "outputs" / "evaluation"

# ── helpers ──────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    return str(text or "").strip().casefold()


def extract_retrieved_titles(retrieval: dict) -> list[str]:
    """
    Pull out all paper titles from graphrag_retrieve() output, in ranked order.
    Each mode stores titles in DIFFERENT keys:
      naive   : paper_chunks[*].title         (ranked by vector distance)
      subgraph: text_units[*].title           (ranked by local distance)
      hybrid  : paper_chunks[*].title + overview_publications[*].title (RRF reranked)
    """
    titles: list[str] = []

    # 1. paper_chunks (naive & mix) — ranked
    for chunk in retrieval.get("paper_chunks", []) or []:
        t = normalize(chunk.get("title") or chunk.get("paper_title") or "")
        if t and t not in titles:
            titles.append(t)

    # 2. text_units (subgraph & hybrid) — ranked by distance, has title field
    for chunk in retrieval.get("text_units", []) or []:
        t = normalize(chunk.get("title") or chunk.get("paper_title") or "")
        if t and t not in titles:
            titles.append(t)

    # 3. overview_publications (hybrid & mix) — graph-traversal, less ranked
    for pub in retrieval.get("overview_publications", []) or []:
        t = normalize(pub.get("title") or "")
        if t and t not in titles:
            titles.append(t)

    # 4. publication_details fallback
    for pub in retrieval.get("publication_details", []) or []:
        t = normalize(pub.get("title") or "")
        if t and t not in titles:
            titles.append(t)

    # 5. author_publications fallback
    for pub in retrieval.get("author_publications", []) or []:
        t = normalize(pub.get("title") or "")
        if t and t not in titles:
            titles.append(t)

    return titles[:TOP_K]


def is_relevant(retrieved_title: str, relevant_titles: list[str]) -> bool:
    """Fuzzy match: relevant if retrieved title contains any relevant title word (≥3 chars)."""
    r = normalize(retrieved_title)
    for rel in relevant_titles:
        rel_norm = normalize(rel)
        # substring match (titles can be truncated)
        if rel_norm in r or r in rel_norm:
            return True
        # word-level overlap (≥4 distinctive words match)
        words_rel = [w for w in rel_norm.split() if len(w) >= 3]
        words_ret = set(r.split())
        if len(words_rel) >= 3 and sum(1 for w in words_rel if w in words_ret) >= 3:
            return True
    return False


def reciprocal_rank(retrieved: list[str], relevant: list[str]) -> float:
    """1/rank of first relevant document, 0 if none found."""
    for rank, title in enumerate(retrieved, start=1):
        if is_relevant(title, relevant):
            return 1.0 / rank
    return 0.0


def hit_at_k(retrieved: list[str], relevant: list[str], k: int) -> int:
    """1 if any relevant doc in top-k, else 0."""
    return int(any(is_relevant(t, relevant) for t in retrieved[:k]))


def precision_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    if not retrieved:
        return 0.0
    hits = sum(1 for t in retrieved[:k] if is_relevant(t, relevant))
    return hits / min(k, len(retrieved))


# ── retrieval call ────────────────────────────────────────────────────────────

def retrieve_for_mode(query: str, mode: str) -> tuple[dict, float]:
    """Call graphrag_retrieve for a given mode. Return (retrieval, latency_sec)."""
    t0 = time.perf_counter()
    retrieval = graphrag_retrieve(
        query,
        param=GraphRAGQueryParam(mode=mode, top_k=TOP_K, graph_name=GRAPH_NAME),
    )
    latency = time.perf_counter() - t0
    return retrieval, latency


# ── core evaluation ────────────────────────────────────────────────────────────

def evaluate_layer1(cases: list[dict], modes: list[str]) -> dict[str, Any]:
    """
    For each (case, mode) pair: retrieve, compute metrics.
    Returns nested dict: results[mode][case_id] = {...metrics...}
    """
    results: dict[str, dict] = {m: {} for m in modes}

    for case in cases:
        cid      = case["id"]
        category = case["category"]
        query    = case["query"]
        relevant = case["relevant_titles"]

        # Skip guardrail cases (no relevant titles to rank)
        if category == "G":
            print(f"  [SKIP {cid}] guardrail case")
            continue

        print(f"\n── Case {cid} ({category}) ──────────────────────────────")
        print(f"   Q: {query[:80]}")
        print(f"   Relevant: {[t[:40] for t in relevant]}")

        for mode in modes:
            print(f"   [{mode}] ...", end=" ", flush=True)
            try:
                retrieval, latency = retrieve_for_mode(query, mode)
                retrieved = extract_retrieved_titles(retrieval)
            except Exception as exc:
                print(f"ERROR: {exc}")
                retrieved = []
                latency   = 0.0

            rr      = reciprocal_rank(retrieved, relevant)
            hits    = {k: hit_at_k(retrieved, relevant, k) for k in K_VALUES}
            precs   = {k: precision_at_k(retrieved, relevant, k) for k in K_VALUES}

            results[mode][cid] = {
                "category":  category,
                "query":     query,
                "relevant":  relevant,
                "retrieved": retrieved,
                "rr":        rr,
                "hits":      hits,
                "precision": precs,
                "latency":   round(latency, 3),
                "n_retrieved": len(retrieved),
            }
            print(f"RR={rr:.3f}  Hit@5={hits[5]}  P@5={precs[5]:.2f}  lat={latency:.1f}s")

    return results


# ── aggregation ───────────────────────────────────────────────────────────────

def aggregate(results: dict[str, dict], category_filter: str | None = None) -> dict:
    """
    Compute mean Hit@K, MRR, P@K across cases (optionally filtered by category).
    """
    agg: dict[str, dict] = {}
    for mode, cases in results.items():
        filtered = {
            cid: v for cid, v in cases.items()
            if category_filter is None or v["category"] == category_filter
        }
        n = len(filtered)
        if n == 0:
            agg[mode] = {"n": 0}
            continue

        mrr    = sum(v["rr"] for v in filtered.values()) / n
        hits   = {k: sum(v["hits"][k] for v in filtered.values()) / n for k in K_VALUES}
        precs  = {k: sum(v["precision"][k] for v in filtered.values()) / n for k in K_VALUES}
        latency = sum(v["latency"] for v in filtered.values()) / n

        agg[mode] = {
            "n":         n,
            "MRR":       round(mrr, 4),
            "Hit@1":     round(hits[1], 4),
            "Hit@3":     round(hits[3], 4),
            "Hit@5":     round(hits[5], 4),
            "Hit@10":    round(hits[10], 4),
            "P@5":       round(precs[5], 4),
            "P@10":      round(precs[10], 4),
            "avg_latency_s": round(latency, 3),
        }
    return agg


# ── visualization ─────────────────────────────────────────────────────────────

def plot_comparison(agg_all: dict, agg_A: dict, agg_B: dict, agg_C: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    modes  = [m for m in MODES if agg_all.get(m, {}).get("n", 0) > 0]
    colors = {"naive": "#7F8C8D", "subgraph": "#2980B9", "hybrid": "#27AE60"}

    # ── Fig 1: Hit Rate comparison (All / A / B) ──────────────────
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), sharey=True)
    for ax, (agg, label) in zip(axes, [
        (agg_all, "Semua Query (n={})".format(agg_all.get(modes[0], {}).get("n", "?"))),
        (agg_A,   "Kat-A Faktual (n={})".format(agg_A.get(modes[0], {}).get("n", "?"))),
        (agg_B,   "Kat-B Relasional (n={})".format(agg_B.get(modes[0], {}).get("n", "?"))),
    ]):
        x   = np.arange(len(modes))
        w   = 0.2
        for i, k in enumerate([1, 3, 5, 10]):
            vals = [agg.get(m, {}).get(f"Hit@{k}", 0) for m in modes]
            bars = ax.bar(x + (i - 1.5) * w, vals, w,
                          label=f"Hit@{k}",
                          color=plt.cm.Blues(0.35 + 0.2 * i),
                          edgecolor="white", linewidth=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels([m.capitalize() for m in modes], fontsize=9)
        ax.set_ylim(0, 1.15)
        ax.set_ylabel("Hit Rate", fontsize=9)
        # ax.set_title(f"({chr(97 + axes.tolist().index(ax))}) {label}", fontsize=9, style="italic")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, linestyle="--", alpha=0.4)
    axes[0].legend(loc="upper right", fontsize=7.5, framealpha=0.9)
    fig.tight_layout()
    p = out_dir / "eval_layer1_hit_rate.png"
    fig.savefig(p, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"[SAVED] {p.name}")

    # ── Fig 2: MRR per mode per kategori (A / B / C) ─────────────
    fig, ax = plt.subplots(figsize=(10, 4))
    x  = np.arange(4)
    w  = 0.18
    cat_labels = [
        "Semua Query\n(n={})".format(agg_all.get(modes[0], {}).get("n", "?")),
        "Kat-A Faktual\n(n={})".format(agg_A.get(modes[0], {}).get("n", "?")),
        "Kat-B Relasional\n(n={})".format(agg_B.get(modes[0], {}).get("n", "?")),
        "Kat-C Multi-hop\n(n={})".format(agg_C.get(modes[0], {}).get("n", "?")),
    ]
    for i, mode in enumerate(modes):
        vals = [
            agg_all.get(mode, {}).get("MRR", 0),
            agg_A.get(mode, {}).get("MRR", 0),
            agg_B.get(mode, {}).get("MRR", 0),
            agg_C.get(mode, {}).get("MRR", 0),
        ]
        bars = ax.bar(x + (i - 1.5) * w, vals, w,
               label=mode.capitalize(), color=colors.get(mode, "#95A5A6"),
               edgecolor="white", linewidth=0.6)
        for bar, v in zip(bars, vals):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                        f"{v:.2f}", ha="center", va="bottom", fontsize=6.5)
    ax.set_xticks(x)
    ax.set_xticklabels(cat_labels, fontsize=8.5)
    ax.set_ylim(0, 1.18)
    ax.set_ylabel("MRR (Mean Reciprocal Rank)", fontsize=9)
    ax.legend(fontsize=8.5, framealpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, linestyle="--", alpha=0.4)
    fig.tight_layout()
    p = out_dir / "eval_layer1_mrr.png"
    fig.savefig(p, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"[SAVED] {p.name}")

    # ── Fig 3: Latency ────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(7, 3.5))
    lat = [agg_all.get(m, {}).get("avg_latency_s", 0) for m in modes]
    bars = ax.barh([m.capitalize() for m in modes], lat,
                   color=[colors.get(m, "#95A5A6") for m in modes],
                   edgecolor="white", height=0.5)
    for bar, v in zip(bars, lat):
        ax.text(bar.get_width() + 0.02, bar.get_y() + bar.get_height() / 2,
                f"{v:.2f}s", va="center", fontsize=9)
    ax.set_xlabel("Rata-rata Latensi per Query (detik)", fontsize=9)
    ax.invert_yaxis()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_axisbelow(True)
    ax.xaxis.grid(True, linestyle="--", alpha=0.4)
    fig.tight_layout()
    p = out_dir / "eval_layer1_latency.png"
    fig.savefig(p, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"[SAVED] {p.name}")


# ── report ────────────────────────────────────────────────────────────────────

def write_report(
    results: dict,
    agg_all: dict,
    agg_A: dict,
    agg_B: dict,
    agg_C: dict,
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON dump
    payload = {
        "results_per_case": results,
        "aggregate": {
            "all":       agg_all,
            "category_A": agg_A,
            "category_B": agg_B,
            "category_C": agg_C,
        },
    }
    (out_dir / "eval_layer1_results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Markdown report
    lines = [
        "# Laporan Evaluasi Lapis 1: Retrieval Quality",
        "",
        "**Metrik:** Hit@K, MRR, Precision@K",
        f"**Mode yang dievaluasi:** {', '.join(MODES)}",
        f"**Top-K:** {TOP_K}",
        "",
        "## Hasil Keseluruhan (Semua Kategori)",
        "",
        "| Mode | n | MRR | Hit@1 | Hit@3 | Hit@5 | Hit@10 | P@5 | Latency (s) |",
        "|------|---|-----|-------|-------|-------|--------|-----|-------------|",
    ]
    for mode in MODES:
        a = agg_all.get(mode, {})
        if not a.get("n"):
            continue
        lines.append(
            f"| {mode} | {a['n']} | {a['MRR']:.4f} | {a['Hit@1']:.4f} | "
            f"{a['Hit@3']:.4f} | {a['Hit@5']:.4f} | {a['Hit@10']:.4f} | "
            f"{a['P@5']:.4f} | {a['avg_latency_s']:.2f} |"
        )

    lines += [
        "",
        "## Kategori A — Factual",
        "",
        "| Mode | n | MRR | Hit@1 | Hit@3 | Hit@5 | Hit@10 |",
        "|------|---|-----|-------|-------|-------|--------|",
    ]
    for mode in MODES:
        a = agg_A.get(mode, {})
        if not a.get("n"):
            continue
        lines.append(
            f"| {mode} | {a['n']} | {a['MRR']:.4f} | {a['Hit@1']:.4f} | "
            f"{a['Hit@3']:.4f} | {a['Hit@5']:.4f} | {a['Hit@10']:.4f} |"
        )

    lines += [
        "",
        "## Kategori B — Relational",
        "",
        "| Mode | n | MRR | Hit@1 | Hit@3 | Hit@5 | Hit@10 |",
        "|------|---|-----|-------|-------|-------|--------|",
    ]
    for mode in MODES:
        a = agg_B.get(mode, {})
        if not a.get("n"):
            continue
        lines.append(
            f"| {mode} | {a['n']} | {a['MRR']:.4f} | {a['Hit@1']:.4f} | "
            f"{a['Hit@3']:.4f} | {a['Hit@5']:.4f} | {a['Hit@10']:.4f} |"
        )

    lines += [
        "",
        "## Kategori C — Multi-hop",
        "",
        "| Mode | n | MRR | Hit@1 | Hit@3 | Hit@5 | Hit@10 |",
        "|------|---|-----|-------|-------|-------|--------|",
    ]
    for mode in MODES:
        a = agg_C.get(mode, {})
        if not a.get("n"):
            continue
        lines.append(
            f"| {mode} | {a['n']} | {a['MRR']:.4f} | {a['Hit@1']:.4f} | "
            f"{a['Hit@3']:.4f} | {a['Hit@5']:.4f} | {a['Hit@10']:.4f} |"
        )

    lines += ["", "## Detail per Case", ""]
    for mode, cases in results.items():
        lines.append(f"### Mode: {mode}")
        lines.append("")
        lines.append("| ID | Cat | RR | Hit@5 | P@5 | Retrieved (top-3) |")
        lines.append("|----|----|-----|-------|-----|------------------|")
        for cid, v in sorted(cases.items()):
            top3 = "; ".join(t[:35] for t in v["retrieved"][:3]) or "-"
            lines.append(
                f"| {cid} | {v['category']} | {v['rr']:.3f} | "
                f"{v['hits'][5]} | {v['precision'][5]:.2f} | {top3} |"
            )
        lines.append("")

    (out_dir / "eval_layer1_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[SAVED] eval_layer1_report.md")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    config = KGConfig.default()
    load_project_env(config.project_root)

    # Filter: only ranked cases (A + B + C), skip Guardrail
    ranked_cases = RANKED_CASES
    print(f"Evaluating {len(ranked_cases)} ranked cases × {len(MODES)} modes ...")
    print(f"  Cat-A: {sum(1 for c in ranked_cases if c['category']=='A')}")
    print(f"  Cat-B: {sum(1 for c in ranked_cases if c['category']=='B')}")
    print(f"  Cat-C: {sum(1 for c in ranked_cases if c['category']=='C')}")
    print(f"Output → {OUT_DIR}\n")

    results = evaluate_layer1(ranked_cases, MODES)

    agg_all = aggregate(results)
    agg_A   = aggregate(results, category_filter="A")
    agg_B   = aggregate(results, category_filter="B")
    agg_C   = aggregate(results, category_filter="C")

    print("\n\n=== AGGREGATED RESULTS ===")
    for label, agg in [
        ("ALL", agg_all),
        ("Cat-A Factual-Hard", agg_A),
        ("Cat-B Relational", agg_B),
        ("Cat-C Multi-hop", agg_C),
    ]:
        print(f"\n  [{label}]")
        for mode in MODES:
            a = agg.get(mode, {})
            if not a.get("n"):
                continue
            print(f"    {mode:10s}  MRR={a['MRR']:.4f}  Hit@5={a['Hit@5']:.4f}  P@5={a['P@5']:.4f}")

    plot_comparison(agg_all, agg_A, agg_B, agg_C, OUT_DIR)
    write_report(results, agg_all, agg_A, agg_B, agg_C, OUT_DIR)

    print(f"\n[DONE] Results saved to: {OUT_DIR}")


if __name__ == "__main__":
    main()
