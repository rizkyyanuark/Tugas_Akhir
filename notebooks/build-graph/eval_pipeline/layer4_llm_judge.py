"""
layer4_llm_judge.py â€” Lapis 4: LLM-as-a-Judge (Pairwise Win Rate)
===================================================================
Mengukur kualitas JAWABAN menggunakan LLM sebagai hakim (judge) dengan
metode pairwise comparison â€” mengadopsi metodologi dari AcademicRAG
(Liu & Chen, 2025) dan Microsoft GraphRAG (Edge et al., 2024).

Relevansi terhadap Rumusan Masalah:
  Poin 3: "Bagaimana efektivitas integrasi KG dalam MENGURANGI HALUSINASI
           dan meningkatkan TRACEABILITY referensi dalam jawaban yang dihasilkan?"

  â†’ Faithfulness     : mengukur pengurangan halusinasi (klaim vs konteks KG)
  â†’ Traceability     : seberapa mudah pembaca memverifikasi sumber jawaban
  â†’ Comprehensiveness: kedalaman dan kelengkapan jawaban
  â†’ Overall          : pemenang head-to-head per kasus

Metode evaluasi:
  â€¢ Setiap kasus dievaluasi 2 arah (A vs B dan B vs A) untuk mitigasi
    positional bias â€” win rate dirata-rata (3-trial seperti AcademicRAG)
  â€¢ Baseline: naive (Vector RAG murni, tanpa KG)
  â€¢ Challenged: subgraph, hybrid, mix (dengan KG)
  â€¢ Judge LLM: Gemini 2.5 Flash via Google AI Studio (GEMINI_API_KEY_JUDGE; paced for 15 requests/minute)

Output:
  â€¢ eval_layer4_winrate.png   â€” win rate bar chart per dimensi
  â€¢ eval_layer4_heatmap.png   â€” heatmap win rate per kasus
  â€¢ eval_layer4_radar.png     â€” radar chart 4 dimensi per mode
  â€¢ eval_layer4_report.md     â€” laporan lengkap
  â€¢ eval_layer4_results.json  â€” raw data

Cara jalankan:
  cd notebooks/build-graph
  python -m eval_pipeline.layer4_llm_judge
  python -m eval_pipeline.layer4_llm_judge --modes naive subgraph hybrid
  python -m eval_pipeline.layer4_llm_judge --max-cases 15   # quick test
"""

from __future__ import annotations

import json
import os
import sys
import time
import re
import random
import shutil
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# â”€â”€ path setup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
from eval_pipeline.eval_dataset import EVAL_DATASET, RANKED_CASES   # noqa: E402

# â”€â”€ constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
GRAPH_NAME   = "yunesa_academic_kg"
TOP_K        = 10
GROQ_MODEL   = "deepseek-v4-flash"
DEFAULT_JUDGE_PROVIDER = "deepseek"
DEFAULT_GROQ_JUDGE_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GEMINI_JUDGE_MODEL = "gemini-2.5-flash-lite"
DEFAULT_OPENAI_COMPATIBLE_JUDGE_MODEL = "deepseek-v4-flash"
JUDGE_MODEL  = DEFAULT_OPENAI_COMPATIBLE_JUDGE_MODEL
try:
    from eval_pipeline.paths import DOCS_GAMBAR_DIR as GAMBAR_DIR, OUTPUT_DIR as OUT_DIR
except Exception:  # pragma: no cover - direct script fallback
    from paths import DOCS_GAMBAR_DIR as GAMBAR_DIR, OUTPUT_DIR as OUT_DIR
ANSWER_CACHE_FILE = OUT_DIR / "eval_layer4_answer_cache.json"

# Dimensi evaluasi (mengikuti AcademicRAG + tambahan Traceability untuk RM-3)
DIMENSIONS = ["Faithfulness", "Traceability", "Comprehensiveness", "Overall"]

# Mode comparison: naive = baseline (Vector RAG murni, tanpa KG traversal)
BASELINE_MODE   = "naive"
CHALLENGER_MODES = ["subgraph", "hybrid"]

COLORS = {
    "naive":    "#7F8C8D",
    "subgraph": "#2980B9",
    "hybrid":   "#27AE60",
}

# â”€â”€ Groq judge model â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def get_judge_provider() -> str:
    """Return the configured LLM judge provider."""
    return os.environ.get("YUNESA_JUDGE_PROVIDER", DEFAULT_JUDGE_PROVIDER).strip().lower()


def get_judge_model_name() -> str:
    provider = get_judge_provider()
    if provider == "gemini":
        default_model = DEFAULT_GEMINI_JUDGE_MODEL
    elif provider in {"openai_compatible", "deepseek", "openai"}:
        default_model = DEFAULT_OPENAI_COMPATIBLE_JUDGE_MODEL
    else:
        default_model = DEFAULT_GROQ_JUDGE_MODEL
    return os.environ.get("YUNESA_JUDGE_MODEL", default_model)


def judge_label() -> str:
    return f"{get_judge_provider()}:{get_judge_model_name()}"


def get_gemini_judge_model():
    import google.generativeai as genai

    api_key = (
        os.environ.get("GEMINI_API_KEY_JUDGE")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if not api_key:
        raise RuntimeError(
            "Set GEMINI_API_KEY_JUDGE first "
            "(or GEMINI_API_KEY/GOOGLE_API_KEY as fallback)."
        )

    genai.configure(api_key=api_key)
    return genai.GenerativeModel(get_judge_model_name())


def get_judge_client() -> dict[str, Any]:
    """Create a judge client descriptor without exposing credentials."""
    provider = get_judge_provider()
    model = get_judge_model_name()

    if provider == "gemini":
        return {"provider": provider, "model": model, "client": get_gemini_judge_model()}

    if provider == "groq":
        try:
            from groq import Groq
        except ImportError as exc:
            raise ImportError("Install groq first: uv sync --project notebooks") from exc
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("Set GROQ_API_KEY first for YUNESA_JUDGE_PROVIDER=groq.")
        return {"provider": provider, "model": model, "client": Groq(api_key=api_key)}

    if provider in {"openai_compatible", "deepseek", "openai"}:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError("Install openai first: uv sync --project notebooks") from exc
        
        api_key = (
            os.environ.get("YUNESA_JUDGE_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        base_url = (
            os.environ.get("YUNESA_JUDGE_BASE_URL")
            or os.environ.get("DEEPSEEK_API_BASE")
            or os.environ.get("OPENAI_API_BASE")
        )

        if provider == "deepseek" and not base_url:
            base_url = "https://api.deepseek.com"

        if not api_key:
            raise RuntimeError(
                "Set YUNESA_JUDGE_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY first."
            )
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return {"provider": provider, "model": model, "client": OpenAI(**kwargs)}

    raise ValueError(
        "Unsupported YUNESA_JUDGE_PROVIDER. Use groq, gemini, openai_compatible, deepseek, or openai."
    )


# â”€â”€ answer generation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def generate_answer(query: str, mode: str) -> dict[str, Any]:
    """Retrieve + generate answer for one query in given mode."""
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
            max_tokens=500,
            temperature=0.1,
        ),
    )
    context_str = format_graphrag_context(retrieval, max_chars=4000)
    latency = time.perf_counter() - t0
    return {
        "answer":   answer_obj["answer"],
        "context":  context_str,
        "latency":  round(latency, 2),
    }


def load_answer_cache() -> dict[str, Any]:
    if not ANSWER_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(ANSWER_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_answer_cache(cache: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ANSWER_CACHE_FILE.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def generate_answer_cached(
    case_id: str,
    query: str,
    mode: str,
    cache: dict[str, Any],
) -> dict[str, Any]:
    cache_key = f"{case_id}:{mode}"
    if cache_key in cache:
        cached = dict(cache[cache_key])
        cached["from_cache"] = True
        return cached
    result = generate_answer(query, mode)
    cache[cache_key] = result
    save_answer_cache(cache)
    result["from_cache"] = False
    return result


# â”€â”€ LLM Judge prompt â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

JUDGE_SYSTEM = """Anda adalah hakim ahli yang bertugas mengevaluasi dua jawaban terhadap pertanyaan yang sama berdasarkan empat kriteria. Jawab HANYA dengan JSON valid, tanpa teks tambahan.

Kriteria evaluasi:
1. Faithfulness (Kesetiaan): Apakah jawaban hanya mengklaim hal yang didukung oleh konteks yang diberikan? Jawaban dengan halusinasi (klaim tanpa dasar konteks) harus dinilai lebih rendah.
2. Traceability (Keterlacakan): Seberapa mudah pembaca memverifikasi sumber klaim dalam jawaban? Apakah menyebutkan judul paper, nama penulis, atau detail spesifik yang dapat dilacak?
3. Comprehensiveness (Kelengkapan): Seberapa lengkap dan mendalam jawaban dalam mencakup semua aspek pertanyaan?
4. Overall (Keseluruhan): Pemenang secara keseluruhan berdasarkan ketiga kriteria di atas."""

JUDGE_TEMPLATE = """Pertanyaan: {query}

Konteks yang tersedia untuk Jawaban Alpha:
{context_alpha}

Konteks yang tersedia untuk Jawaban Beta:
{context_beta}

Jawaban Alpha:
{answer_alpha}

Jawaban Beta:
{answer_beta}

Evaluasi kedua jawaban menggunakan empat kriteria. Output HANYA JSON:
{{
  "Faithfulness": {{"winner": "Alpha|Beta|Tie", "reasoning": "..."}},
  "Traceability": {{"winner": "Alpha|Beta|Tie", "reasoning": "..."}},
  "Comprehensiveness": {{"winner": "Alpha|Beta|Tie", "reasoning": "..."}},
  "Overall": {{"winner": "Alpha|Beta|Tie", "reasoning": "..."}}
}}"""


def _gemini_response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text)
    candidates = getattr(response, "candidates", None) or []
    parts: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            value = getattr(part, "text", None)
            if value:
                parts.append(str(value))
    return "\n".join(parts)


def _extract_json_payload(raw: Any) -> dict | None:
    """Parse a judge JSON object from plain text or markdown-wrapped output."""
    text = str(raw or "").strip()
    if not text:
        return None
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not json_match:
        return None
    try:
        return json.loads(json_match.group())
    except json.JSONDecodeError:
        return None


def _call_chat_completion_judge(judge: dict[str, Any], prompt: str) -> str:
    """Call Groq/OpenAI-compatible chat completions and return message content."""
    client = judge["client"]
    kwargs = {
        "model": judge["model"],
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }
    if "deepseek" in judge["model"].lower():
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    try:
        response = client.chat.completions.create(
            **kwargs,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        message = str(exc).lower()
        if "response_format" not in message and "json" not in message:
            raise
        response = client.chat.completions.create(**kwargs)
    return str(response.choices[0].message.content or "")


def call_judge(
    judge: dict[str, Any],
    query: str,
    answer_alpha: str, context_alpha: str,
    answer_beta: str, context_beta: str,
    retries: int = 3,
) -> dict | None:
    """Call the configured judge provider. Returns parsed JSON or None on failure."""
    prompt = JUDGE_TEMPLATE.format(
        query=query,
        context_alpha=context_alpha[:1500],
        context_beta=context_beta[:1500],
        answer_alpha=answer_alpha[:800],
        answer_beta=answer_beta[:800],
    )
    wait_seconds = int(os.environ.get("YUNESA_JUDGE_RATE_LIMIT_SLEEP_SECONDS", "65"))
    for attempt in range(retries):
        try:
            if judge["provider"] == "gemini":
                response = judge["client"].generate_content(
                    f"{JUDGE_SYSTEM}\n\n{prompt}",
                    generation_config={
                        "temperature": 0.1,
                        "max_output_tokens": 700,
                        "response_mime_type": "application/json",
                    },
                )
                raw = _gemini_response_text(response).strip()
            else:
                raw = _call_chat_completion_judge(judge, prompt)
            parsed = _extract_json_payload(raw)
            if parsed:
                return parsed
        except Exception as e:
            err_msg = str(e).lower()
            if "quota" in err_msg or "429" in err_msg or "rate limit" in err_msg:
                is_daily_quota = any(
                    marker in err_msg
                    for marker in (
                        "perday",
                        "per day",
                        "daily",
                        "free_tier_requests",
                        "generaterequestsperday",
                    )
                )
                if is_daily_quota:
                    print(f"    [Quota exhausted] Daily quota hit; not retrying. ({e})")
                    break
                print(f"    [Rate Limit] Waiting {wait_seconds}s... ({e})")
                time.sleep(wait_seconds)
            else:
                print(f"    [Judge attempt {attempt+1} failed]: {e}")
                time.sleep(2 ** attempt)
    return None


def judge_pair(
    client,
    query: str,
    answer_A: str, context_A: str,
    answer_B: str, context_B: str,
    n_trials: int = 2,
) -> dict[str, dict]:
    """
    Run pairwise judge with order alternation (A vs B, then B vs A).
    Returns win counts per dimension: {dim: {"A": int, "B": int, "Tie": int}}
    """
    wins: dict[str, dict[str, int]] = {
        d: {"A": 0, "B": 0, "Tie": 0} for d in DIMENSIONS
    }
    reasonings: dict[str, list[str]] = {d: [] for d in DIMENSIONS}
    judge_successes = 0
    judge_failures = 0

    for trial in range(n_trials):
        # Alternate order to mitigate positional bias
        if trial % 2 == 0:
            alpha_name, beta_name = "A", "B"
            alpha_ans, alpha_ctx = answer_A, context_A
            beta_ans, beta_ctx   = answer_B, context_B
        else:
            alpha_name, beta_name = "B", "A"
            alpha_ans, alpha_ctx = answer_B, context_B
            beta_ans, beta_ctx   = answer_A, context_A

        result = call_judge(
            client, query,
            alpha_ans, alpha_ctx,
            beta_ans, beta_ctx,
        )
        if result is None:
            judge_failures += 1
            continue
        judge_successes += 1

        for dim in DIMENSIONS:
            dim_result = result.get(dim, {})
            raw_winner = dim_result.get("winner", "Tie")
            reasoning  = dim_result.get("reasoning", "")

            # Map Alpha/Beta back to A/B
            if raw_winner == "Alpha":
                actual_winner = alpha_name
            elif raw_winner == "Beta":
                actual_winner = beta_name
            else:
                actual_winner = "Tie"

            if actual_winner in wins[dim]:
                wins[dim][actual_winner] += 1
            else:
                wins[dim]["Tie"] += 1
            reasonings[dim].append(reasoning)

        call_interval = float(os.environ.get("YUNESA_JUDGE_CALL_INTERVAL_SECONDS", "4.2"))
        if call_interval > 0:
            time.sleep(call_interval)

    return {
        "wins": wins,
        "reasonings": reasonings,
        "judge_successes": judge_successes,
        "judge_failures": judge_failures,
    }


# â”€â”€ main evaluation loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_layer4(
    cases: list[dict],
    challenger_modes: list[str] = CHALLENGER_MODES,
    n_trials: int = 2,
) -> dict:
    """
    For each case and each challenger mode, compare:
        baseline (naive) vs challenger
    Returns:
    {
      challenger_mode: {
        case_id: {
          "query": str,
          "category": str,
          "baseline_answer": str,
          "challenger_answer": str,
          "wins": {dim: {"A": int, "B": int, "Tie": int}},  # A=naive, B=challenger
          "win_rate_challenger": {dim: float},   # fraction challenger wins
        }
      }
    }
    """
    judge_model = get_judge_client()
    results: dict[str, dict] = {m: {} for m in challenger_modes}
    answer_cache = load_answer_cache()

    # Pre-generate all baseline answers first
    baseline_answers: dict[str, dict] = {}
    print(f"\n{'='*60}")
    print(f"  PRE-GENERATING BASELINE (naive) ANSWERS")
    print(f"{'='*60}")
    for case in cases:
        cid = case["id"]
        print(f"  [{cid}] naive ...", end=" ", flush=True)
        try:
            res = generate_answer_cached(cid, case["query"], BASELINE_MODE, answer_cache)
            baseline_answers[cid] = res
            source = "CACHE" if res.get("from_cache") else "OK"
            print(f"{source} ({res['latency']}s)")
        except Exception as e:
            print(f"ERROR: {e}")
            baseline_answers[cid] = {"answer": "", "context": "", "latency": 0}
        time.sleep(0.3)

    # Evaluate each challenger mode
    for challenger in challenger_modes:
        print(f"\n{'='*60}")
        print(f"  CHALLENGER: {challenger.upper()} vs BASELINE: {BASELINE_MODE.upper()}")
        print(f"{'='*60}")

        for case in cases:
            cid      = case["id"]
            query    = case["query"]
            category = case["category"]

            print(f"\n  [{cid}] ({category}) {query[:60]}...")

            # Generate challenger answer
            print(f"    â†’ Generating [{challenger}] answer ...", end=" ", flush=True)
            try:
                challenger_res = generate_answer_cached(cid, query, challenger, answer_cache)
                source = "CACHE" if challenger_res.get("from_cache") else "OK"
                print(f"{source} ({challenger_res['latency']}s)")
            except Exception as e:
                print(f"ERROR: {e}")
                continue

            baseline_res = baseline_answers.get(cid, {})
            if not baseline_res.get("answer"):
                print(f"    [SKIP] no baseline answer for {cid}")
                continue

            # LLM judge pairwise (naive=A, challenger=B)
            print(f"    â†’ LLM judging ({n_trials} trials) ...", end=" ", flush=True)
            judge_result = judge_pair(
                judge_model,
                query,
                answer_A=baseline_res["answer"],   context_A=baseline_res["context"],
                answer_B=challenger_res["answer"],  context_B=challenger_res["context"],
                n_trials=n_trials,
            )
            print("done")

            # Compute win rates (B = challenger)
            wins = judge_result["wins"]
            judge_successes = judge_result.get("judge_successes", 0)
            judge_failures = judge_result.get("judge_failures", 0)
            judge_failed = judge_successes == 0
            win_rate_challenger = {}
            for dim in DIMENSIONS:
                total_decided = wins[dim]["A"] + wins[dim]["B"] + wins[dim]["Tie"]
                if total_decided == 0:
                    win_rate_challenger[dim] = None
                else:
                    # Win rate = challenger wins + 0.5 * ties
                    win_rate_challenger[dim] = round(
                        (wins[dim]["B"] + 0.5 * wins[dim]["Tie"]) / total_decided, 4
                    )

            results[challenger][cid] = {
                "query":               query,
                "category":            category,
                "baseline_answer":     baseline_res["answer"][:300],
                "challenger_answer":   challenger_res["answer"][:300],
                "wins":                wins,
                "win_rate_challenger": win_rate_challenger,
                "judge_failed":        judge_failed,
                "judge_successes":     judge_successes,
                "judge_failures":      judge_failures,
                "reasonings":          {d: judge_result["reasonings"][d][-1]
                                        if judge_result["reasonings"][d] else ""
                                        for d in DIMENSIONS},
            }

            # Print per-case summary
            if judge_failed:
                print(f"      [JUDGE FAILED] {judge_failures} failed call(s); excluded from aggregate")
                continue
            for dim in DIMENSIONS:
                wr = win_rate_challenger[dim]
                symbol = "â†‘" if wr > 0.55 else ("â†“" if wr < 0.45 else "â‰ˆ")
                print(f"      {dim:20s}: {wr:.2%} {symbol}")

    return results


# â”€â”€ aggregation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def aggregate_layer4(
    results: dict,
    category_filter: str | None = None,
) -> dict:
    """
    Returns: {challenger_mode: {dim: avg_win_rate, "n": int, ...}}
    Win rate > 0.5 â†’ challenger beats baseline.
    """
    agg: dict[str, dict] = {}
    for mode, cases in results.items():
        filtered = {
            cid: v for cid, v in cases.items()
            if not v.get("judge_failed")
            and (category_filter is None or v["category"] == category_filter)
        }
        failed = sum(
            1
            for v in cases.values()
            if v.get("judge_failed")
            and (category_filter is None or v["category"] == category_filter)
        )
        n = len(filtered)
        if n == 0:
            if failed:
                agg[mode] = {"n": 0, "failed": failed}
            continue

        dim_wr: dict[str, list[float]] = {d: [] for d in DIMENSIONS}
        for v in filtered.values():
            for d in DIMENSIONS:
                score = v["win_rate_challenger"].get(d)
                if score is not None:
                    dim_wr[d].append(score)

        agg[mode] = {
            "n": n,
            "failed": failed,
            **{d: round(sum(dim_wr[d]) / len(dim_wr[d]), 4)
               for d in DIMENSIONS if dim_wr[d]},
        }
    return agg


def count_valid_judgements(results: dict) -> int:
    """Count case-mode pairs with at least one successful judge call."""
    return sum(
        1
        for cases in results.values()
        for case in cases.values()
        if not case.get("judge_failed")
    )


def count_failed_judgements(results: dict) -> int:
    """Count case-mode pairs where all judge calls failed."""
    return sum(
        1
        for cases in results.values()
        for case in cases.values()
        if case.get("judge_failed")
    )


def _suffix_output_dir(out_dir: Path, suffix: str | None) -> Path:
    if not suffix:
        return out_dir
    return out_dir / suffix


def write_failed_attempt_report(
    results: dict,
    cases: list[dict],
    modes: list[str],
    out_dir: Path,
) -> None:
    """Persist failed judge attempts separately without overwriting valid outputs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "judge_provider": get_judge_provider(),
        "judge_model": get_judge_model_name(),
        "cases_requested": len(cases),
        "modes": modes,
        "valid_judgements": count_valid_judgements(results),
        "failed_judgements": count_failed_judgements(results),
        "results_per_case": results,
    }
    (out_dir / "eval_layer4_failed_attempt.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    lines = [
        "# Layer 4 Judge Attempt Failed",
        "",
        f"- Judge provider: `{get_judge_provider()}`",
        f"- Judge model: `{get_judge_model_name()}`",
        f"- Cases requested: {len(cases)}",
        f"- Modes: {', '.join(modes)}",
        f"- Valid case-mode judgements: {payload['valid_judgements']}",
        f"- Failed case-mode judgements: {payload['failed_judgements']}",
        "",
        "Tidak ada judgement valid yang cukup untuk membuat grafik atau laporan utama. "
        "File utama `eval_layer4_results.json` dan gambar Bab 4 tidak ditimpa.",
    ]
    (out_dir / "eval_layer4_failed_attempt.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    print("[WARN] No valid judge results. Main Layer 4 outputs were not overwritten.")


# â”€â”€ visualization â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def plot_layer4(
    agg_all: dict,
    agg_A:   dict,
    agg_B:   dict,
    agg_C:   dict,
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    challengers = [m for m in CHALLENGER_MODES if m in agg_all]
    if not challengers:
        print("[WARN] No aggregated results to plot.")
        return

    # â”€â”€ Fig 1: Win Rate Bar Chart â€” 4 dimensi Ã— mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    fig, axes = plt.subplots(1, len(DIMENSIONS), figsize=(14, 4.5), sharey=True)

    for ax, dim in zip(axes, DIMENSIONS):
        x   = np.arange(len(challengers))
        w   = 0.55
        for i, mode in enumerate(challengers):
            wr = agg_all.get(mode, {}).get(dim, 0.5)
            color = COLORS.get(mode, "#95A5A6")
            bar = ax.bar(i, wr, w, color=color, edgecolor="white",
                         linewidth=0.8, alpha=0.92)
            ax.text(i, wr + 0.015, f"{wr:.0%}",
                    ha="center", va="bottom", fontsize=8.5, fontweight="bold",
                    color=COLORS.get(mode, "#2C3E50"))

        # Reference line at 0.5 (tie)
        ax.axhline(0.5, color="#E74C3C", linestyle="--", linewidth=1.1,
                   alpha=0.8, label="50% (tie)")
        ax.set_xticks(x)
        ax.set_xticklabels([m.capitalize() for m in challengers], fontsize=8.5)
        ax.set_ylim(0, 1.12)
        ax.set_xlabel(dim, fontsize=9.5, fontweight="bold",
                      color="#2C3E50", labelpad=6)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, linestyle="--", alpha=0.35)
        if ax == axes[0]:
            ax.set_ylabel("Win Rate vs Naive (Vector RAG)", fontsize=9)
        if ax == axes[-1]:
            ax.legend(fontsize=7.5, loc="lower right")

    # Shaded region: above 0.5 = KG wins
    for ax in axes:
        ax.axhspan(0.5, 1.12, alpha=0.04, color="#27AE60")
        ax.axhspan(0, 0.5, alpha=0.04, color="#E74C3C")

    fig.tight_layout()
    p = out_dir / "eval_layer4_winrate.png"
    fig.savefig(p, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"[SAVED] {p.name}")

    # â”€â”€ Fig 2: Win Rate per Kategori (A / B / C) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Focus on Overall win rate across categories
    fig, ax = plt.subplots(figsize=(10, 4.5))
    categories  = ["All", "Cat-A\nFaktual", "Cat-B\nRelasional", "Cat-C\nMulti-hop"]
    cat_aggs    = [agg_all, agg_A, agg_B, agg_C]
    x           = np.arange(len(categories))
    w           = 0.22

    for i, mode in enumerate(challengers):
        vals = [agg.get(mode, {}).get("Overall", 0.5) for agg in cat_aggs]
        bars = ax.bar(x + (i - len(challengers)/2 + 0.5) * w, vals, w,
                      label=f"{mode.capitalize()} vs Naive",
                      color=COLORS.get(mode, "#95A5A6"),
                      edgecolor="white", linewidth=0.7, alpha=0.9)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.012,
                    f"{v:.0%}", ha="center", va="bottom", fontsize=7,
                    fontweight="bold")

    ax.axhline(0.5, color="#E74C3C", linestyle="--", linewidth=1.2,
               alpha=0.8, label="50% (setara)")
    ax.axhspan(0.5, 1.1, alpha=0.04, color="#27AE60")
    ax.axhspan(0, 0.5, alpha=0.04, color="#E74C3C")
    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=9.5)
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Overall Win Rate vs Naive", fontsize=9.5)
    ax.legend(fontsize=8.5, framealpha=0.9, loc="upper right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, linestyle="--", alpha=0.35)

    # Annotation
    ax.text(0.02, 0.96, "Area hijau: KG unggul  |  Area merah: Naive unggul",
            transform=ax.transAxes, fontsize=7.5,
            color="#555", va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7))

    fig.tight_layout()
    p = out_dir / "eval_layer4_category.png"
    fig.savefig(p, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"[SAVED] {p.name}")

    # â”€â”€ Fig 3: Radar Chart â€” 4 dimensi per mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    N      = len(DIMENSIONS)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]
    dim_labels = DIMENSIONS + [DIMENSIONS[0]]

    fig, axes = plt.subplots(
        1, len(challengers),
        figsize=(5 * len(challengers), 5),
        subplot_kw=dict(polar=True),
    )
    if len(challengers) == 1:
        axes = [axes]

    for ax, mode in zip(axes, challengers):
        vals_all = [agg_all.get(mode, {}).get(d, 0.5) for d in DIMENSIONS] + \
                   [agg_all.get(mode, {}).get(DIMENSIONS[0], 0.5)]
        vals_A   = [agg_A.get(mode, {}).get(d, 0.5) for d in DIMENSIONS] + \
                   [agg_A.get(mode, {}).get(DIMENSIONS[0], 0.5)]
        vals_B   = [agg_B.get(mode, {}).get(d, 0.5) for d in DIMENSIONS] + \
                   [agg_B.get(mode, {}).get(DIMENSIONS[0], 0.5)]

        # Reference circle at 0.5
        ref = [0.5] * (N + 1)
        ax.plot(angles, ref, color="#E74C3C", linewidth=1,
                linestyle="--", alpha=0.6, label="50% (tie)")
        ax.fill(angles, ref, color="#E74C3C", alpha=0.05)

        for vals, label, color, alpha in [
            (vals_all, "All",      COLORS.get(mode, "#2C3E50"), 0.20),
            (vals_A,   "Cat-A",    "#3498DB",                   0.25),
            (vals_B,   "Cat-B",    "#E67E22",                   0.25),
        ]:
            ax.plot(angles, vals, color=color, linewidth=1.8, label=label)
            ax.fill(angles, vals, color=color, alpha=alpha)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(DIMENSIONS, fontsize=8.5)
        ax.set_ylim(0, 1)
        ax.set_yticks([0.25, 0.5, 0.75, 1.0])
        ax.set_yticklabels(["25%", "50%", "75%", "100%"], fontsize=6)
        # ax.set_title(f"{mode.capitalize()} vs Naive",
        #              fontsize=10.5, pad=18, fontweight="bold",
        #              color=COLORS.get(mode, "#2C3E50"))
        ax.legend(loc="upper right", bbox_to_anchor=(1.4, 1.1), fontsize=7.5)

    # fig.suptitle("LLM Judge Win Rate per Dimensi (Challenger vs Naive/Vector RAG)",
    #              fontsize=11, fontweight="bold", color="#2C3E50", y=1.02)
    fig.tight_layout()
    p = out_dir / "eval_layer4_radar.png"
    fig.savefig(p, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"[SAVED] {p.name}")

    # â”€â”€ Fig 4: Summary scorecard â€” halusinasi & traceability focus â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    fig, ax = plt.subplots(figsize=(10, 5))

    # Build scorecard data
    scorecard_modes = challengers
    scorecard_dims  = ["Faithfulness", "Traceability", "Comprehensiveness", "Overall"]
    data = np.array([
        [agg_all.get(mode, {}).get(d, 0.5) for d in scorecard_dims]
        for mode in scorecard_modes
    ])

    im = ax.imshow(data, cmap="RdYlGn", vmin=0.3, vmax=0.7, aspect="auto")

    ax.set_xticks(np.arange(len(scorecard_dims)))
    ax.set_yticks(np.arange(len(scorecard_modes)))
    ax.set_xticklabels(scorecard_dims, fontsize=10, fontweight="bold")
    ax.set_yticklabels([m.capitalize() for m in scorecard_modes],
                       fontsize=10, fontweight="bold")

    # Annotate cells
    for i in range(len(scorecard_modes)):
        for j in range(len(scorecard_dims)):
            val = data[i, j]
            txt_color = "white" if abs(val - 0.5) > 0.15 else "#2C3E50"
            verdict = "â†‘ KG Wins" if val > 0.55 else ("â†“ Naive Wins" if val < 0.45 else "â‰ˆ Tie")
            ax.text(j, i, f"{val:.0%}\n{verdict}",
                    ha="center", va="center", fontsize=8.5,
                    fontweight="bold", color=txt_color)

    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.set_label("Win Rate (challenger vs naive)", fontsize=8.5)
    cbar.set_ticks([0.3, 0.4, 0.5, 0.6, 0.7])
    cbar.set_ticklabels(["30% (Naiveâ†‘)", "40%", "50% (Tie)", "60%", "70% (KGâ†‘)"])

    ax.set_xlabel("Dimensi Evaluasi (LLM Judge)", fontsize=10, labelpad=10)
    ax.set_ylabel("Mode Retrieval vs Naive (Vector RAG)", fontsize=10, labelpad=10)

    fig.tight_layout()
    p = out_dir / "eval_layer4_heatmap.png"
    fig.savefig(p, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"[SAVED] {p.name}")


# â”€â”€ report â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def write_report_layer4(
    results: dict,
    agg_all: dict,
    agg_A:   dict,
    agg_B:   dict,
    agg_C:   dict,
    out_dir: Path,
    run_metadata: dict[str, Any] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_metadata = run_metadata or {}

    # JSON
    payload = {
        "run_metadata": run_metadata,
        "results_per_case": {
            mode: {
                cid: {k: v for k, v in case.items() if k != "reasonings"}
                for cid, case in cases.items()
            }
            for mode, cases in results.items()
        },
        "aggregate": {
            "all":        agg_all,
            "category_A": agg_A,
            "category_B": agg_B,
            "category_C": agg_C,
        },
    }
    (out_dir / "eval_layer4_results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Markdown report
    lines = [
        "# Laporan Evaluasi Lapis 4: LLM Judge (Pairwise Win Rate)",
        "",
        "**Metode**: Pairwise comparison â€” Challenger vs Baseline (Naive/Vector RAG)",
        f"**Judge Provider**: {get_judge_provider()}",
        f"**Judge Model**: {get_judge_model_name()}",
        f"**Cakupan run**: {run_metadata.get('scope_label', 'full')}",
        "**Dimensi**: Faithfulness (halusinasi), Traceability, Comprehensiveness, Overall",
        "**Relevansi RM-3**: Mengukur efektivitas KG dalam mengurangi halusinasi & meningkatkan traceability",
        "",
        "> Win Rate > 50% â†’ KG mode unggul atas Vector RAG murni",
        "> Win Rate < 50% â†’ Naive (Vector RAG) lebih baik",
        "> Win Rate â‰ˆ 50% â†’ Setara",
        "",
        "## Hasil Keseluruhan (All Categories)",
        "",
        "| Mode vs Naive | n valid | failed | Faithfulness | Traceability | Comprehensiveness | Overall |",
        "|---------------|---------|--------|-------------|-------------|------------------|---------|",
    ]
    for mode in CHALLENGER_MODES:
        a = agg_all.get(mode, {})
        if not a.get("n"):
            continue
        lines.append(
            f"| {mode.capitalize()} | {a['n']} | {a.get('failed', 0)} | "
            f"{a.get('Faithfulness', 0):.1%} | "
            f"{a.get('Traceability', 0):.1%} | "
            f"{a.get('Comprehensiveness', 0):.1%} | "
            f"{a.get('Overall', 0):.1%} |"
        )

    for cat_label, cat_agg in [
        ("A â€” Faktual", agg_A),
        ("B â€” Relasional", agg_B),
        ("C â€” Multi-hop", agg_C),
    ]:
        if not any(cat_agg.get(m, {}).get("n") for m in CHALLENGER_MODES):
            continue
        lines += [
            "",
            f"## Kategori {cat_label}",
            "",
            "| Mode vs Naive | n valid | failed | Faithfulness | Traceability | Comprehensiveness | Overall |",
            "|---------------|---------|--------|-------------|-------------|------------------|---------|",
        ]
        for mode in CHALLENGER_MODES:
            a = cat_agg.get(mode, {})
            if not a.get("n"):
                continue
            lines.append(
                f"| {mode.capitalize()} | {a['n']} | {a.get('failed', 0)} | "
                f"{a.get('Faithfulness', 0):.1%} | "
                f"{a.get('Traceability', 0):.1%} | "
                f"{a.get('Comprehensiveness', 0):.1%} | "
                f"{a.get('Overall', 0):.1%} |"
            )

    # Detail per case
    lines += ["", "## Detail per Case", ""]
    for mode, cases in results.items():
        lines.append(f"### Challenger: {mode.capitalize()} vs Naive")
        for cid, v in sorted(cases.items()):
            lines.extend([
                f"**[{cid}] ({v['category']}) {v['query'][:70]}**",
                "",
                "| Dimensi | Win Rate | Reasoning |",
                "|---------|----------|-----------|",
            ])
            for dim in DIMENSIONS:
                wr = v["win_rate_challenger"].get(dim)
                wr_text = "-" if wr is None else f"{wr:.0%}"
                reason = v.get("reasonings", {}).get(dim, "")[:120]
                lines.append(f"| {dim} | {wr_text} | {reason} |")
            lines.append("")

    (out_dir / "eval_layer4_report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print("[SAVED] eval_layer4_report.md")


# â”€â”€ copy to Gambar dir â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def copy_to_gambar(out_dir: Path, gambar_dir: Path) -> None:
    gambar_dir.mkdir(parents=True, exist_ok=True)
    figs = [
        "eval_layer4_winrate.png",
        "eval_layer4_category.png",
        "eval_layer4_radar.png",
        "eval_layer4_heatmap.png",
    ]
    for fname in figs:
        src = out_dir / fname
        if src.exists():
            shutil.copy2(src, gambar_dir / fname)
            print(f"  [COPY]  â†’ Gambar/{fname}")


# â”€â”€ main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main(
    challenger_modes: list[str] | None = None,
    max_cases: int | None = None,
    case_ids: list[str] | None = None,
    n_trials: int = 2,
    skip_generation: bool = False,
    write_main_outputs: bool = True,
) -> None:
    config = KGConfig.default()
    load_project_env(config.project_root)

    modes   = challenger_modes or CHALLENGER_MODES
    all_cases = RANKED_CASES
    cases   = all_cases
    if case_ids:
        selected = {cid.upper() for cid in case_ids}
        cases = [case for case in cases if str(case.get("id", "")).upper() in selected]
        missing = sorted(selected - {str(case.get("id", "")).upper() for case in cases})
        if missing:
            raise ValueError(f"Unknown case id(s): {', '.join(missing)}")
    if max_cases:
        cases = cases[:max_cases]
    is_partial_run = len(cases) < len(all_cases)
    output_suffix = None if write_main_outputs else f"layer4_subset_{len(cases)}cases"
    effective_out_dir = _suffix_output_dir(OUT_DIR, output_suffix)
    scope_label = (
        f"partial ({len(cases)}/{len(all_cases)} ranked cases)"
        if is_partial_run
        else f"full ({len(cases)} ranked cases)"
    )

    print(f"\n{'='*60}")
    print(f"  LAYER 4 â€” LLM Judge (Pairwise Win Rate)")
    print(f"  Baseline : {BASELINE_MODE.upper()} (Vector RAG)")
    print(f"  Challengers: {[m.upper() for m in modes]}")
    print(f"  Cases    : {len(cases)}")
    print(f"  Trials   : {n_trials} per pair (order alternated)")
    print(f"  Judge    : {judge_label()}")
    print(f"{'='*60}\n")

    results_file = effective_out_dir / "eval_layer4_results.json"

    if skip_generation and results_file.exists():
        print("[INFO] Loading cached results from JSON ...")
        with open(results_file, encoding="utf-8") as f:
            cached = json.load(f)
        cached_results = cached.get("results_per_case", {})
        results = {
            mode: cached_results.get(mode, {})
            for mode in modes
            if mode in cached_results
        }
        cached_case_ids = {
            str(case_id).upper()
            for mode_cases in results.values()
            for case_id in mode_cases.keys()
        }
        if cached_case_ids:
            case_by_id = {
                str(case.get("id", "")).upper(): case
                for case in cases
            }
            cases = [
                case_by_id[case_id]
                for case_id in sorted(cached_case_ids)
                if case_id in case_by_id
            ]
            is_partial_run = len(cases) < len(all_cases)
            scope_label = (
                f"partial cached ({len(cases)}/{len(all_cases)} ranked cases)"
                if is_partial_run
                else f"full cached ({len(cases)} ranked cases)"
            )
        print(f"[INFO] Loaded {sum(len(v) for v in results.values())} cached cases.")
    else:
        results = run_layer4(cases, modes, n_trials=n_trials)

    agg_all = aggregate_layer4(results)
    agg_A   = aggregate_layer4(results, "A")
    agg_B   = aggregate_layer4(results, "B")
    agg_C   = aggregate_layer4(results, "C")
    valid_judgements = count_valid_judgements(results)
    if valid_judgements == 0:
        write_failed_attempt_report(results, cases, modes, OUT_DIR)
        raise RuntimeError(
            "Layer 4 judge produced zero valid judgements. "
            "Likely quota/provider failure; main outputs were left untouched."
        )

    print("\n\n=== LLM JUDGE AGGREGATED RESULTS ===")
    print(f"\n  {'Mode':12s} {'Faith':10s} {'Trace':10s} {'Comp':10s} {'Overall':10s}")
    print(f"  {'-'*52}")
    for mode in modes:
        a = agg_all.get(mode, {})
        if not a.get("n"):
            continue
        print(f"  {mode:12s} "
              f"{a.get('Faithfulness', 0):.1%}      "
              f"{a.get('Traceability', 0):.1%}      "
              f"{a.get('Comprehensiveness', 0):.1%}      "
              f"{a.get('Overall', 0):.1%}")

    run_metadata = {
        "judge_provider": get_judge_provider(),
        "judge_model": get_judge_model_name(),
        "baseline_mode": BASELINE_MODE,
        "challenger_modes": modes,
        "cases_requested": len(cases),
        "cases_total_ranked": len(all_cases),
        "scope_label": scope_label,
        "trials_per_pair": n_trials,
        "valid_judgements": valid_judgements,
        "failed_judgements": count_failed_judgements(results),
        "is_partial_run": is_partial_run,
    }
    plot_layer4(agg_all, agg_A, agg_B, agg_C, effective_out_dir)
    write_report_layer4(
        results,
        agg_all,
        agg_A,
        agg_B,
        agg_C,
        effective_out_dir,
        run_metadata=run_metadata,
    )
    if write_main_outputs:
        copy_to_gambar(effective_out_dir, GAMBAR_DIR)
    else:
        print(f"[INFO] Partial outputs saved under: {effective_out_dir}")

    print(f"\n[DONE] All Layer 4 outputs saved to: {effective_out_dir}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Layer 4: LLM Judge Evaluation")
    parser.add_argument(
        "--modes", nargs="+",
        default=["subgraph", "hybrid"],
        choices=["subgraph", "hybrid"],
        help="Challenger modes to evaluate against naive baseline",
    )
    parser.add_argument(
        "--max-cases", type=int, default=None,
        help="Limit number of cases (for quick testing)",
    )
    parser.add_argument(
        "--case-ids", nargs="+", default=None,
        help="Explicit case IDs to evaluate, e.g. A01 A02 B01 B02 C01 C02",
    )
    parser.add_argument(
        "--trials", type=int, default=2,
        help="Number of judge trials per pair (default: 2)",
    )
    parser.add_argument(
        "--from-cache", action="store_true",
        help="Skip generation, use cached JSON results",
    )
    parser.add_argument(
        "--no-write-main", action="store_true",
        help="Write outputs to a subset folder instead of replacing main Layer 4 files",
    )
    args = parser.parse_args()

    main(
        challenger_modes=args.modes,
        max_cases=args.max_cases,
        case_ids=args.case_ids,
        n_trials=args.trials,
        skip_generation=args.from_cache,
        write_main_outputs=not args.no_write_main,
    )
