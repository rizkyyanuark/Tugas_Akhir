"""Export Bab 4-ready evaluation artifacts.

This script does not rerun retrieval or LLM generation. It reads the current
evaluation outputs and produces:

- booktabs LaTeX tables,
- PGFPlots/TikZ figure snippets,
- includegraphics snippets for PNG figures,
- a manifest that records available/missing inputs,
- copies of final PNG figures into docs/proposal tugas akhir/Gambar.

Run from repo root:

    notebooks\\.venv\\Scripts\\python.exe notebooks\\build-graph\\eval_pipeline\\bab4_artifact_export.py
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any


EVAL_PIPELINE_DIR = Path(__file__).resolve().parent
BUILD_GRAPH_DIR = EVAL_PIPELINE_DIR.parent
if str(BUILD_GRAPH_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_GRAPH_DIR))

try:
    from eval_pipeline.eval_dataset import EVAL_DATASET, dataset_summary
    from eval_pipeline.paths import (
        BAB4_ARTIFACT_DIR,
        DOCS_BAB4_EVAL_DIR,
        DOCS_GAMBAR_DIR,
        OUTPUT_DIR,
        relative_to_repo,
    )
except Exception:  # pragma: no cover - direct fallback
    from eval_dataset import EVAL_DATASET, dataset_summary
    from paths import BAB4_ARTIFACT_DIR, DOCS_BAB4_EVAL_DIR, DOCS_GAMBAR_DIR, OUTPUT_DIR, relative_to_repo


MODES = ["naive", "subgraph", "hybrid"]
MODE_LABELS = {
    "naive": "Vector RAG",
    "subgraph": "Subgraph",
    "hybrid": "Hybrid",
}
CATEGORY_LABELS = {
    "A": "Faktual",
    "B": "Relasional",
    "C": "Multi-hop",
    "G": "Guardrail",
}

PNG_FIGURES = [
    {
        "file": "eval_layer1_hit_rate.png",
        "caption": "Perbandingan Hit@K pada evaluasi retrieval.",
        "label": "fig:eval-layer1-hit-rate",
        "width": "0.82\\linewidth",
    },
    {
        "file": "eval_layer1_mrr.png",
        "caption": "Perbandingan Mean Reciprocal Rank pada evaluasi retrieval.",
        "label": "fig:eval-layer1-mrr",
        "width": "0.82\\linewidth",
    },
    {
        "file": "eval_layer1_latency.png",
        "caption": "Rata-rata latensi retrieval pada setiap mode.",
        "label": "fig:eval-layer1-latency",
        "width": "0.78\\linewidth",
    },
    {
        "file": "eval_layer3_hit_curves.png",
        "caption": "Kurva Hit@K untuk membandingkan mode retrieval.",
        "label": "fig:eval-layer3-hit-curves",
        "width": "0.86\\linewidth",
    },
    {
        "file": "eval_layer3_mrr_by_category.png",
        "caption": "MRR tiap mode retrieval berdasarkan kategori pertanyaan.",
        "label": "fig:eval-layer3-mrr-category",
        "width": "0.86\\linewidth",
    },
    {
        "file": "eval_layer3_latency_quality.png",
        "caption": "Trade-off antara kualitas retrieval dan latensi.",
        "label": "fig:eval-layer3-latency-quality",
        "width": "0.82\\linewidth",
    },
    {
        "file": "eval_layer3_scorecard.png",
        "caption": "Scorecard perbandingan mode retrieval.",
        "label": "fig:eval-layer3-scorecard",
        "width": "0.86\\linewidth",
    },
    {
        "file": "eval_layer4_winrate.png",
        "caption": "Win rate LLM judge terhadap baseline Vector RAG.",
        "label": "fig:eval-layer4-winrate",
        "width": "0.82\\linewidth",
    },
    {
        "file": "eval_layer4_category.png",
        "caption": "Win rate LLM judge berdasarkan kategori pertanyaan.",
        "label": "fig:eval-layer4-category",
        "width": "0.82\\linewidth",
    },
    {
        "file": "eval_layer4_heatmap.png",
        "caption": "Heatmap hasil pairwise LLM judge per kasus evaluasi.",
        "label": "fig:eval-layer4-heatmap",
        "width": "0.90\\linewidth",
    },
    {
        "file": "eval_layer4_radar.png",
        "caption": "Perbandingan dimensi jawaban menurut LLM judge.",
        "label": "fig:eval-layer4-radar",
        "width": "0.76\\linewidth",
    },
]
LATEX_ARTIFACT_PREFIX = "generated/bab4_eval"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _escape_latex(value: Any) -> str:
    text = str(value if value is not None else "")
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return _escape_latex(value)


def _booktabs_table(
    *,
    caption: str,
    label: str,
    columns: list[str],
    rows: list[list[Any]],
    align: str,
) -> str:
    if not rows:
        rows = [["-" for _ in columns]]
    lines = [
        r"\begin{table}[htbp]",
        r"    \centering",
        r"    \small",
        rf"    \caption{{{_escape_latex(caption)}}}",
        rf"    \label{{{label}}}",
        rf"    \begin{{tabular}}{{{align}}}",
        r"        \toprule",
        "        " + " & ".join(_escape_latex(col) for col in columns) + r" \\",
        r"        \midrule",
    ]
    for row in rows:
        lines.append("        " + " & ".join(_escape_latex(item) for item in row) + r" \\")
    lines.extend(
        [
            r"        \bottomrule",
            r"    \end{tabular}",
            r"\end{table}",
            "",
        ]
    )
    return "\n".join(lines)


def _dataset_rows() -> list[list[Any]]:
    counts = Counter(item.get("category", "?") for item in EVAL_DATASET)
    rows: list[list[Any]] = []
    for category in ["A", "B", "C", "G"]:
        rows.append([category, CATEGORY_LABELS.get(category, category), str(counts.get(category, 0))])
    rows.append(["Total", "Seluruh pertanyaan evaluasi", str(sum(counts.values()))])
    return rows


def _retrieval_overall_rows(layer1: dict[str, Any] | None) -> list[list[Any]]:
    if not layer1:
        return []
    aggregate = layer1.get("aggregate", {}).get("all", {})
    rows: list[list[Any]] = []
    for mode in MODES:
        item = aggregate.get(mode, {})
        if item:
            rows.append(
                [
                    MODE_LABELS.get(mode, mode),
                    str(item.get("n", "-")),
                    _fmt(item.get("MRR")),
                    _fmt(item.get("Hit@1")),
                    _fmt(item.get("Hit@5")),
                    _fmt(item.get("Hit@10")),
                    _fmt(item.get("P@5")),
                    _fmt(item.get("avg_latency_s"), digits=2),
                ]
            )
    return rows


def _retrieval_category_rows(layer1: dict[str, Any] | None) -> list[list[Any]]:
    if not layer1:
        return []
    aggregate = layer1.get("aggregate", {})
    rows: list[list[Any]] = []
    for mode in MODES:
        row = [MODE_LABELS.get(mode, mode)]
        for category_key in ["category_A", "category_B", "category_C"]:
            item = aggregate.get(category_key, {}).get(mode, {})
            row.append(_fmt(item.get("MRR")))
            row.append(_fmt(item.get("Hit@5")))
        rows.append(row)
    return rows


def _answer_quality_rows(layer2: dict[str, Any] | None) -> list[list[Any]]:
    if not layer2:
        return []
    aggregate = layer2.get("aggregate", {}).get("all", {})
    rows: list[list[Any]] = []
    for mode in MODES:
        item = aggregate.get(mode, {})
        if item:
            rows.append(
                [
                    MODE_LABELS.get(mode, mode),
                    str(item.get("n", "-")),
                    _fmt(item.get("faithfulness_ragas") or item.get("faithfulness_local")),
                    _fmt(item.get("answer_relevancy_ragas") or item.get("answer_relevancy_local")),
                    _fmt(item.get("context_precision_ragas")),
                    _fmt(item.get("context_recall_ragas")),
                    _fmt(item.get("avg_latency_s"), digits=2),
                ]
            )
    return rows


def _judge_rows(layer4: dict[str, Any] | None) -> list[list[Any]]:
    if not layer4:
        return []
    aggregate = layer4.get("aggregate", {}).get("all", {})
    rows: list[list[Any]] = []
    for mode in ["subgraph", "hybrid"]:
        item = aggregate.get(mode, {})
        if item:
            rows.append(
                [
                    f"{MODE_LABELS.get(mode, mode)} vs Vector RAG",
                    str(item.get("n", "-")),
                    str(item.get("failed", 0)),
                    _fmt(item.get("Faithfulness") or item.get("faithfulness")),
                    _fmt(item.get("Traceability") or item.get("traceability")),
                    _fmt(item.get("Comprehensiveness") or item.get("comprehensiveness")),
                    _fmt(item.get("Overall") or item.get("overall")),
                ]
            )
    return rows


def _pgfplots_grouped_mrr(layer1: dict[str, Any] | None) -> str:
    aggregate = (layer1 or {}).get("aggregate", {})
    coords: dict[str, list[tuple[str, float]]] = {}
    for category_key, label in [
        ("category_A", "Faktual"),
        ("category_B", "Relasional"),
        ("category_C", "Multi-hop"),
    ]:
        coords[label] = []
        for mode in MODES:
            value = aggregate.get(category_key, {}).get(mode, {}).get("MRR", 0) or 0
            coords[label].append((MODE_LABELS.get(mode, mode), float(value)))

    plots = []
    for label, values in coords.items():
        coord_text = " ".join(f"({_escape_latex(mode)},{value:.4f})" for mode, value in values)
        plots.append(
            "        \\addplot coordinates {" + coord_text + "};\n"
            f"        \\addlegendentry{{{_escape_latex(label)}}}"
        )

    return "\n".join(
        [
            r"\begin{figure}[htbp]",
            r"    \centering",
            r"    \begin{tikzpicture}",
            r"    \begin{axis}[",
            r"        ybar,",
            r"        width=0.92\textwidth,",
            r"        height=0.42\textwidth,",
            r"        bar width=8pt,",
            r"        ymin=0, ymax=1.05,",
            r"        ylabel={MRR},",
            r"        symbolic x coords={Vector RAG,Subgraph,Hybrid},",
            r"        xtick=data,",
            r"        x tick label style={rotate=0, anchor=center},",
            r"        legend style={at={(0.5,-0.22)}, anchor=north, legend columns=3},",
            r"        ymajorgrids=true,",
            r"        grid style=dashed,",
            r"    ]",
            *plots,
            r"    \end{axis}",
            r"    \end{tikzpicture}",
            r"    \caption{Perbandingan MRR mode retrieval pada setiap kategori pertanyaan}",
            r"    \label{fig:bab4-eval-mrr-category}",
            r"\end{figure}",
            "",
        ]
    )


def _pgfplots_latency_hit(layer1: dict[str, Any] | None) -> str:
    aggregate = (layer1 or {}).get("aggregate", {}).get("all", {})
    coords = []
    labels = []
    for mode in MODES:
        item = aggregate.get(mode, {})
        if not item:
            continue
        latency = float(item.get("avg_latency_s", 0) or 0)
        hit5 = float(item.get("Hit@5", 0) or 0)
        coords.append(f"({latency:.4f},{hit5:.4f})")
        labels.append(
            f"        \\node[font=\\scriptsize, anchor=west] at (axis cs:{latency:.4f},{hit5:.4f}) "
            f"{{{_escape_latex(MODE_LABELS.get(mode, mode))}}};"
        )

    return "\n".join(
        [
            r"\begin{figure}[htbp]",
            r"    \centering",
            r"    \begin{tikzpicture}",
            r"    \begin{axis}[",
            r"        width=0.82\textwidth,",
            r"        height=0.42\textwidth,",
            r"        xlabel={Rata-rata latensi (detik)},",
            r"        ylabel={Hit@5},",
            r"        ymin=0, ymax=1.0,",
            r"        xmin=0,",
            r"        ymajorgrids=true,",
            r"        xmajorgrids=true,",
            r"        grid style=dashed,",
            r"    ]",
            "        \\addplot+[only marks, mark=*, mark size=2.8pt] coordinates {"
            + " ".join(coords)
            + "};",
            *labels,
            r"    \end{axis}",
            r"    \end{tikzpicture}",
            r"    \caption{Trade-off antara latensi dan Hit@5 pada mode retrieval}",
            r"    \label{fig:bab4-eval-latency-hit}",
            r"\end{figure}",
            "",
        ]
    )


def _includegraphics_fragment(figures: list[dict[str, Any]]) -> str:
    lines: list[str] = [
        "% Auto-generated by eval_pipeline/bab4_artifact_export.py",
        "% These figures assume this file is included from docs/proposal tugas akhir/Skripsi.tex.",
        "",
    ]
    for item in figures:
        filename = item["file"]
        lines.extend(
            [
                r"\begin{figure}[htbp]",
                r"    \centering",
                rf"    \includegraphics[width={item['width']}]{{Gambar/{filename}}}",
                rf"    \caption{{{_escape_latex(item['caption'])}}}",
                rf"    \label{{{item['label']}}}",
                r"\end{figure}",
                "",
            ]
        )
    return "\n".join(lines)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_artifact(filename: str, content: str) -> list[str]:
    """Write an artifact to both the technical output dir and thesis dir."""
    targets = [BAB4_ARTIFACT_DIR / filename, DOCS_BAB4_EVAL_DIR / filename]
    for path in targets:
        _write_text(path, content)
    return [relative_to_repo(path) for path in targets]


def _copy_png_figures(*, copy_figures: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    copied: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for spec in PNG_FIGURES:
        source = OUTPUT_DIR / spec["file"]
        target = DOCS_GAMBAR_DIR / spec["file"]
        if not source.exists():
            missing.append({**spec, "source": relative_to_repo(source)})
            continue
        if copy_figures:
            DOCS_GAMBAR_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        copied.append(
            {
                **spec,
                "source": relative_to_repo(source),
                "target": relative_to_repo(target),
            }
        )
    return copied, missing


def export_artifacts(*, copy_figures: bool = True, strict: bool = False) -> dict[str, Any]:
    BAB4_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_BAB4_EVAL_DIR.mkdir(parents=True, exist_ok=True)
    layer_paths = {
        "layer1": OUTPUT_DIR / "eval_layer1_results.json",
        "layer2": OUTPUT_DIR / "eval_layer2_results.json",
        "layer4": OUTPUT_DIR / "eval_layer4_results.json",
    }
    layer1 = _load_json(layer_paths["layer1"])
    layer2 = _load_json(layer_paths["layer2"])
    layer4 = _load_json(layer_paths["layer4"])
    if not layer1:
        raise FileNotFoundError(f"Layer 1 result is required but not found: {layer_paths['layer1']}")

    input_status = {
        name: {
            "path": relative_to_repo(path),
            "exists": path.exists(),
            "modified_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(path.stat().st_mtime))
            if path.exists()
            else None,
        }
        for name, path in layer_paths.items()
    }
    if strict:
        missing_required = [name for name, item in input_status.items() if not item["exists"]]
        if missing_required:
            raise FileNotFoundError(f"Missing evaluation input(s): {', '.join(missing_required)}")

    tables = {
        "bab4_table_eval_dataset.tex": _booktabs_table(
            caption="Distribusi pertanyaan evaluasi",
            label="tab:bab4-eval-dataset",
            columns=["Kategori", "Jenis pertanyaan", "Jumlah"],
            rows=_dataset_rows(),
            align="llr",
        ),
        "bab4_table_retrieval_overall.tex": _booktabs_table(
            caption="Hasil retrieval keseluruhan per mode",
            label="tab:bab4-retrieval-overall",
            columns=["Mode", "n", "MRR", "Hit@1", "Hit@5", "Hit@10", "P@5", "Latensi"],
            rows=_retrieval_overall_rows(layer1),
            align="lrrrrrrr",
        ),
        "bab4_table_retrieval_by_category.tex": _booktabs_table(
            caption="Hasil retrieval berdasarkan kategori pertanyaan",
            label="tab:bab4-retrieval-category",
            columns=["Mode", "MRR A", "Hit@5 A", "MRR B", "Hit@5 B", "MRR C", "Hit@5 C"],
            rows=_retrieval_category_rows(layer1),
            align="lrrrrrr",
        ),
        "bab4_table_answer_quality.tex": _booktabs_table(
            caption="Evaluasi kualitas jawaban",
            label="tab:bab4-answer-quality",
            columns=[
                "Mode",
                "n",
                "Faithfulness",
                "Answer Relevancy",
                "Context Precision",
                "Context Recall",
                "Latensi",
            ],
            rows=_answer_quality_rows(layer2),
            align="lrrrrrr",
        ),
        "bab4_table_llm_judge.tex": _booktabs_table(
            caption="Pairwise LLM judge terhadap Vector RAG",
            label="tab:bab4-llm-judge",
            columns=[
                "Perbandingan",
                "n valid",
                "failed",
                "Faithfulness",
                "Traceability",
                "Comprehensiveness",
                "Overall",
            ],
            rows=_judge_rows(layer4),
            align="lrrrrrr",
        ),
    }
    figures = {
        "bab4_fig_mrr_by_category.tex": _pgfplots_grouped_mrr(layer1),
        "bab4_fig_latency_hit.tex": _pgfplots_latency_hit(layer1),
    }
    copied_figures, missing_figures = _copy_png_figures(copy_figures=copy_figures)
    figure_include_file = "bab4_figures_includegraphics.tex"
    tables_include_file = "bab4_tables_all.tex"
    all_include_file = "bab4_eval_all.tex"

    written_artifacts: dict[str, list[str]] = {}
    for filename, content in {**tables, **figures}.items():
        written_artifacts[filename] = _write_artifact(filename, content)

    written_artifacts[figure_include_file] = _write_artifact(
        figure_include_file,
        _includegraphics_fragment(copied_figures),
    )
    written_artifacts[tables_include_file] = _write_artifact(
        tables_include_file,
        "\n".join(rf"\input{{{LATEX_ARTIFACT_PREFIX}/{name}}}" for name in sorted(tables)),
    )
    written_artifacts[all_include_file] = _write_artifact(
        all_include_file,
        "\n".join(
            [
                "% Auto-generated Bab 4 evaluation include file.",
                *[rf"\input{{{LATEX_ARTIFACT_PREFIX}/{name}}}" for name in sorted(tables)],
                *[rf"\input{{{LATEX_ARTIFACT_PREFIX}/{name}}}" for name in sorted(figures)],
                rf"\input{{{LATEX_ARTIFACT_PREFIX}/{figure_include_file}}}",
                "",
            ]
        ),
    )

    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "output_dir": relative_to_repo(OUTPUT_DIR),
        "artifact_dir": relative_to_repo(BAB4_ARTIFACT_DIR),
        "docs_bab4_eval_dir": relative_to_repo(DOCS_BAB4_EVAL_DIR),
        "docs_gambar_dir": relative_to_repo(DOCS_GAMBAR_DIR),
        "latex_artifact_prefix": LATEX_ARTIFACT_PREFIX,
        "dataset": dataset_summary(),
        "input_status": input_status,
        "tables": sorted(tables),
        "pgfplots_figures": sorted(figures),
        "written_artifacts": written_artifacts,
        "png_figures_copied": copied_figures,
        "png_figures_missing": missing_figures,
        "include_files": [tables_include_file, figure_include_file, all_include_file],
        "copy_figures": copy_figures,
        "strict": strict,
        "notes": [
            "Tables use booktabs style; include \\usepackage{booktabs}.",
            "PGFPlots snippets require \\usepackage{pgfplots} and \\pgfplotsset{compat=1.18}.",
            "PNG figure snippets assume the thesis root can resolve Gambar/<filename>.",
            "Layer 2/4 artifacts are preliminary if their corresponding result JSON was generated from a subset run.",
        ],
    }
    _write_artifact("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    missing_lines = [f"- `{item['file']}`" for item in missing_figures] if missing_figures else ["- None"]
    readme = [
        "# Bab 4 Evaluation Artifacts",
        "",
        "Generated from evaluation outputs by `eval_pipeline/bab4_artifact_export.py`.",
        "",
        "## Recommended Include",
        "",
        "From `docs/proposal tugas akhir/Skripsi.tex`, include selected files manually.",
        "For a full generated block, use:",
        "",
        "```tex",
        f"\\input{{{LATEX_ARTIFACT_PREFIX}/bab4_eval_all.tex}}",
        "```",
        "",
        "## Tables",
        *[f"- `{name}`" for name in sorted(tables)],
        "",
        "## PGFPlots/TikZ Figures",
        *[f"- `{name}`" for name in sorted(figures)],
        "",
        "## PNG Figure Include File",
        f"- `{figure_include_file}`",
        "",
        "## Copied PNG Figures",
        *[f"- `{item['file']}` -> `{item['target']}`" for item in copied_figures],
        "",
        "## Missing PNG Figures",
        *missing_lines,
        "",
    ]
    _write_artifact("README.md", "\n".join(readme))

    if missing_figures and strict:
        raise FileNotFoundError(
            "Missing PNG figure(s): " + ", ".join(item["file"] for item in missing_figures)
        )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Bab 4-ready evaluation artifacts.")
    parser.add_argument("--no-copy-figures", action="store_true", help="Do not copy PNG figures to docs/proposal tugas akhir/Gambar.")
    parser.add_argument("--strict", action="store_true", help="Fail if optional Layer 2/4 outputs or PNG figures are missing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = export_artifacts(copy_figures=not args.no_copy_figures, strict=args.strict)
    print(f"Bab 4 artifacts exported to: {BAB4_ARTIFACT_DIR}")
    print(f"Bab 4 thesis include artifacts exported to: {DOCS_BAB4_EVAL_DIR}")
    print(f"PNG figures copied: {len(manifest['png_figures_copied'])}")
    if manifest["png_figures_missing"]:
        print("Missing PNG figures:")
        for item in manifest["png_figures_missing"]:
            print(f"  - {item['file']}")
    print("Include file:")
    print(f"  {DOCS_BAB4_EVAL_DIR / 'bab4_eval_all.tex'}")


if __name__ == "__main__":
    main()
