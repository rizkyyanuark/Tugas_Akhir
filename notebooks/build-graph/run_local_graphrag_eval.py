"""Run a compact end-to-end GraphRAG evaluation against AuraDB, Zilliz, and Groq.

The goal is not to benchmark LLM quality statistically. This script checks
whether the current academic KG can answer representative user questions with
evidence grounded in the stored graph/vector indexes.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import warnings


os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TQDM_DISABLE", "1")

warnings.filterwarnings("ignore", message=r"The `resume_download` argument is deprecated.*")

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
        inspect_neo4j_graph,
        load_project_env,
        opik_trace,
        retrieval_observability_summary,
        set_observation_output,
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
        inspect_neo4j_graph,
        load_project_env,
        opik_trace,
        retrieval_observability_summary,
        set_observation_output,
    )


TEST_CASES = [
    {
        "id": "race_gender_model_dataset",
        "query": "Model apa yang digunakan untuk race and gender recognition dan dataset apa yang dipakai?",
        "expected_terms": ["ViT-Face", "ViT-Emotion", "DemogPairs"],
        "expected_sources": ["Dual Vision Transformer Integration for Race and Gender Recognition Based on Facial Images"],
        "forbidden_terms": [],
        "intent": "model_dataset_metric",
    },
    {
        "id": "credit_default_boosting",
        "query": "Paper mana yang membahas credit default risk prediction dan model boosting apa yang digunakan?",
        "expected_terms": ["XGBoost", "CatBoost", "LightGBM", "Optuna"],
        "expected_sources": ["Implementing Optuna and Ensemble Learning on Boosting Models for Credit Default Risk Prediction"],
        "forbidden_terms": [],
        "intent": "paper_model_method",
    },
    {
        "id": "chatbot_learning_style",
        "query": "Jelaskan paper tentang deteksi learning style menggunakan chatbot WhatsApp, termasuk metode dan metriknya.",
        "expected_terms": ["WhatsApp", "rule-based", "80.2", "0.902"],
        "expected_sources": ["Rule-Based Adaptive Chatbot on WhatsApp for Visual, Auditory, and Kinesthetic Learning Style Detection"],
        "forbidden_terms": [],
        "intent": "paper_method_metric",
    },
    {
        "id": "student_comprehension_svm",
        "query": "Apa metode yang digunakan untuk mendeteksi pemahaman mahasiswa dari feedback berbahasa Indonesia?",
        "expected_terms": ["Support Vector Machine", "student", "feedback"],
        "expected_sources": ["Detecting Students’ Comprehension Based on Sentiment Analysis of Students’ Feedback in Indonesian Using Support Vector Machine"],
        "forbidden_terms": [],
        "intent": "method_task_domain",
    },
    {
        "id": "photovoltaic_optimizer",
        "query": "Paper mana yang membahas optimasi parameter photovoltaic dan apa hasil metriknya?",
        "expected_terms": ["modified puma optimizer", "photovoltaic", "0.0026"],
        "expected_sources": ["Enhancing photovoltaic parameters based on modified puma optimizer"],
        "forbidden_terms": [],
        "intent": "paper_method_metric",
    },
    {
        "id": "credit_authors",
        "query": "Siapa saja penulis paper credit default risk prediction?",
        "expected_terms": ["Ramadhan Cakra Wibawa", "Achmad Kautsar", "Yuni Yamasari", "Ricky Eka Putra"],
        "expected_sources": ["Implementing Optuna and Ensemble Learning on Boosting Models for Credit Default Risk Prediction"],
        "forbidden_terms": [],
        "intent": "author_lookup",
    },
    {
        "id": "topic_overview",
        "query": "Topik riset apa saja yang terlihat dari graph sample ini?",
        "expected_terms": ["race", "gender", "credit", "learning style"],
        "expected_sources": [],
        "forbidden_terms": [],
        "intent": "overview",
    },
    {
        "id": "out_of_scope_retinopathy",
        "query": "Apakah graph ini punya paper tentang diabetic retinopathy dengan dataset APTOS 2019?",
        "expected_terms": ["tidak"],
        "expected_sources": [],
        "forbidden_terms": ["93.24", "MobileViT", "EfficientNet-B1"],
        "intent": "out_of_scope_guardrail",
    },
]


def normalize_text(value: object) -> str:
    return str(value or "").casefold().replace(",", ".")


def contains_term(text: str, term: str) -> bool:
    return normalize_text(term) in normalize_text(text)


def source_titles(retrieval: dict) -> list[str]:
    titles: list[str] = []
    for row in retrieval.get("paper_chunks", []) or []:
        title = str(row.get("title") or "").strip()
        if title and title not in titles:
            titles.append(title)
    for row in retrieval.get("overview_publications", []) or []:
        title = str(row.get("title") or "").strip()
        if title and title not in titles:
            titles.append(title)
    return titles


def evaluate_case(case: dict, *, graph_name: str, model: str, top_k: int) -> dict:
    started_at = time.perf_counter()
    with opik_trace(
        "academic_graphrag.eval_case",
        input={
            "case_id": case["id"],
            "intent": case["intent"],
            "query": case["query"],
            "expected_terms": case["expected_terms"],
            "expected_sources": case["expected_sources"],
            "forbidden_terms": case.get("forbidden_terms", []),
        },
        metadata={"graph_name": graph_name, "model": model, "top_k": top_k},
        tags=["evaluation", "graphrag", case["intent"]],
    ) as trace:
        retrieval = graphrag_retrieve(
            case["query"],
            param=GraphRAGQueryParam(mode="mix", top_k=top_k, graph_name=graph_name),
        )
        answer = generate_graphrag_answer_with_groq(
            case["query"],
            retrieval,
            param=GraphRAGGenerationParam(model=model, max_tokens=650, temperature=0.1),
        )
        answer_text = answer["answer"]
        context = format_graphrag_context(retrieval, max_chars=5000)
        titles = source_titles(retrieval)

        found_terms = [term for term in case["expected_terms"] if contains_term(answer_text, term)]
        missing_terms = [term for term in case["expected_terms"] if term not in found_terms]
        found_sources = [title for title in case["expected_sources"] if any(contains_term(src, title) for src in titles)]
        missing_sources = [title for title in case["expected_sources"] if title not in found_sources]
        forbidden_hits = [term for term in case.get("forbidden_terms", []) if contains_term(answer_text, term)]

        passed = not missing_terms and not missing_sources and not forbidden_hits
        result = {
            "id": case["id"],
            "intent": case["intent"],
            "query": case["query"],
            "pass": passed,
            "expected_terms": case["expected_terms"],
            "found_terms": found_terms,
            "missing_terms": missing_terms,
            "expected_sources": case["expected_sources"],
            "source_titles": titles,
            "missing_sources": missing_sources,
            "forbidden_hits": forbidden_hits,
            "usage": answer["usage"],
            "answer": answer_text,
            "context_preview": context[:2500],
        }
        set_observation_output(
            trace,
            output={
                "pass": passed,
                "missing_terms": missing_terms,
                "missing_sources": missing_sources,
                "forbidden_hits": forbidden_hits,
                "source_titles": titles,
                "retrieval": retrieval_observability_summary(retrieval),
            },
            metadata={"duration_seconds": round(time.perf_counter() - started_at, 3)},
            usage=answer.get("usage") or None,
        )
        return result


def write_report(results: list[dict], *, output_dir: Path, graph_name: str, model: str, duration_seconds: float) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "graph_name": graph_name,
        "model": model,
        "total_cases": len(results),
        "passed": sum(1 for row in results if row["pass"]),
        "failed": sum(1 for row in results if not row["pass"]),
        "duration_seconds": round(duration_seconds, 3),
        "total_tokens": sum((row.get("usage") or {}).get("total_tokens") or 0 for row in results),
        "cases": [
            {
                "id": row["id"],
                "intent": row["intent"],
                "pass": row["pass"],
                "missing_terms": row["missing_terms"],
                "missing_sources": row["missing_sources"],
                "forbidden_hits": row["forbidden_hits"],
                "usage": row["usage"],
            }
            for row in results
        ],
    }

    json_path = output_dir / "graphrag_groq_eval_results.json"
    md_path = output_dir / "graphrag_groq_eval_report.md"
    json_path.write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# GraphRAG Groq Evaluation Report",
        "",
        f"- Graph namespace: `{graph_name}`",
        f"- Groq model: `{model}`",
        f"- Cases: {summary['passed']}/{summary['total_cases']} passed",
        f"- Total tokens: {summary['total_tokens']}",
        f"- Duration: {summary['duration_seconds']} seconds",
        "",
        "## Case Summary",
        "",
        "| Case | Intent | Pass | Missing Terms | Missing Sources | Forbidden Hits |",
        "|---|---|---:|---|---|---|",
    ]
    for row in results:
        lines.append(
            "| {id} | {intent} | {passed} | {missing_terms} | {missing_sources} | {forbidden_hits} |".format(
                id=row["id"],
                intent=row["intent"],
                passed="yes" if row["pass"] else "no",
                missing_terms=", ".join(row["missing_terms"]) or "-",
                missing_sources=", ".join(row["missing_sources"]) or "-",
                forbidden_hits=", ".join(row["forbidden_hits"]) or "-",
            )
        )
    lines.extend(["", "## Answers", ""])
    for row in results:
        lines.extend(
            [
                f"### {row['id']}",
                "",
                f"**Question:** {row['query']}",
                "",
                f"**Pass:** {'yes' if row['pass'] else 'no'}",
                "",
                "**Answer:**",
                "",
                row["answer"],
                "",
                f"**Sources:** {', '.join(row['source_titles']) or '-'}",
                "",
            ]
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"summary": summary, "json_path": str(json_path), "md_path": str(md_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate YUNESA Academic GraphRAG responses with Groq.")
    parser.add_argument("--graph-name", default="yunesa_academic_kg_debug_20260604")
    parser.add_argument("--model", default="llama-3.3-70b-versatile")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--limit", type=int, default=len(TEST_CASES))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = KGConfig.default()
    load_project_env(config.project_root)
    os.environ.setdefault("NEO4J_TRUST_SELF_SIGNED", "1")

    try:
        graph_report = inspect_neo4j_graph(graph_name=args.graph_name)
        print(f"Graph check: nodes={graph_report['nodes']} relationships={graph_report['relationships']}")
    except Exception as exc:  # noqa: BLE001
        print(f"Graph inspect warning: {type(exc).__name__}: {exc}")

    started = time.perf_counter()
    results = []
    for case in TEST_CASES[: max(0, args.limit)]:
        print(f"Running {case['id']}...")
        results.append(evaluate_case(case, graph_name=args.graph_name, model=args.model, top_k=args.top_k))
    duration = time.perf_counter() - started
    report = write_report(
        results,
        output_dir=config.output_dir,
        graph_name=args.graph_name,
        model=args.model,
        duration_seconds=duration,
    )
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
    print(f"JSON: {report['json_path']}")
    print(f"Markdown: {report['md_path']}")


if __name__ == "__main__":
    main()
