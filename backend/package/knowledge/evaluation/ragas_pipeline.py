"""
RAGAS Pipeline: Evaluation Framework for GraphRAG
===================================================
Evaluates the GraphRAG system using 5 RAGAS metrics (sesuai Proposal Bab 3):
  1. Context Precision  > 0.85
  2. Context Recall      > 0.80
  3. Faithfulness        > 0.90
  4. Answer Correctness  > 0.75
  5. Answer Relevancy

Benchmarks: GraphRAG vs Vector RAG (baseline)
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Lazy imports to avoid hard dependency
_ragas = None
_opik = None


def _ensure_ragas():
    global _ragas
    if _ragas is None:
        try:
            import ragas
            _ragas = ragas
        except ImportError:
            raise ImportError("Install ragas: pip install ragas")
    return _ragas


def _ensure_opik():
    global _opik
    if _opik is None:
        try:
            import opik
            _opik = opik
        except ImportError:
            logger.warning("Opik not installed. Evaluation scores won't be logged.")
    return _opik


class RAGASEvaluator:
    """RAGAS evaluation pipeline for GraphRAG vs Vector RAG.

    Usage:
        evaluator = RAGASEvaluator()
        results = await evaluator.evaluate_graphrag(questions_path="src/evaluation/questions.json")
        evaluator.print_report(results)
    """

    THRESHOLDS = {
        "context_precision": 0.85,
        "context_recall": 0.80,
        "faithfulness": 0.90,
        "answer_correctness": 0.75,
        "answer_relevancy": 0.0,  # No threshold, just measure
    }

    def __init__(self):
        self.results: List[Dict] = []

    async def evaluate_graphrag(
        self,
        questions_path: str = "src/evaluation/questions.json",
        mode: str = "hybrid",
    ) -> Dict[str, Any]:
        """Run RAGAS evaluation on GraphRAG system.

        Args:
            questions_path: Path to questions.json with ground truth.
            mode: GraphRAG retrieval mode.

        Returns:
            Evaluation results dict.
        """
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

        from knowledge.graphrag.query import GraphRAGQuery

        # Load questions
        qpath = Path(questions_path)
        if not qpath.exists():
            # Try relative to project root
            qpath = Path(__file__).resolve().parent / "questions.json"
        
        with open(qpath, "r", encoding="utf-8") as f:
            questions_data = json.load(f)

        questions = questions_data.get("questions", [])
        logger.info(f"Loaded {len(questions)} evaluation questions from {qpath}")

        # Run queries
        gq = GraphRAGQuery()
        eval_records = []

        try:
            for i, q in enumerate(questions):
                question = q["question"]
                ground_truth = q.get("ground_truth", "")
                category = q.get("category", "unknown")

                logger.info(f"Evaluating [{i+1}/{len(questions)}] ({category}): {question[:60]}...")

                result = await gq.query(question, mode=mode)

                eval_records.append({
                    "question": question,
                    "answer": result["response"],
                    "ground_truth": ground_truth,
                    "contexts": [
                        result["debug"]["fused_context"].get("text_units_context", ""),
                        result["debug"]["fused_context"].get("entities_context", ""),
                    ],
                    "category": category,
                    "latency_s": result["metadata"]["latency_s"],
                })

        finally:
            gq.close()

        # Calculate metrics using RAGAS
        metrics = self._calculate_metrics(eval_records)

        # Log to Opik
        self._log_to_opik(metrics, mode)

        return {
            "mode": mode,
            "total_questions": len(questions),
            "metrics": metrics,
            "records": eval_records,
        }

    def _calculate_metrics(self, records: List[Dict]) -> Dict[str, float]:
        """Calculate RAGAS metrics from evaluation records."""
        try:
            ragas = _ensure_ragas()
            from ragas import evaluate
            from ragas.metrics import (
                context_precision,
                context_recall,
                faithfulness,
                answer_correctness,
                answer_relevancy,
            )
            from datasets import Dataset

            # Build dataset
            data = {
                "question": [r["question"] for r in records],
                "answer": [r["answer"] for r in records],
                "ground_truth": [r["ground_truth"] for r in records],
                "contexts": [r["contexts"] for r in records],
            }
            dataset = Dataset.from_dict(data)

            result = evaluate(
                dataset,
                metrics=[
                    context_precision,
                    context_recall,
                    faithfulness,
                    answer_correctness,
                    answer_relevancy,
                ],
            )

            return dict(result)

        except Exception as e:
            logger.warning(f"RAGAS evaluation failed: {e}. Using manual scoring.")
            # Fallback: basic metrics
            return {
                "context_precision": 0.0,
                "context_recall": 0.0,
                "faithfulness": 0.0,
                "answer_correctness": 0.0,
                "answer_relevancy": 0.0,
                "error": str(e),
            }

    def _log_to_opik(self, metrics: Dict, mode: str):
        """Log evaluation metrics to Opik."""
        opik = _ensure_opik()
        if opik:
            try:
                from knowledge.graphrag.config import OPIK_URL, OPIK_WORKSPACE, OPIK_PROJECT
                client = opik.Opik(
                    url=OPIK_URL,
                    workspace=OPIK_WORKSPACE,
                    project_name=OPIK_PROJECT,
                )
                client.log_trace(
                    name=f"ragas_evaluation_{mode}",
                    input={"mode": mode},
                    output={"metrics": metrics},
                    metadata={"evaluation_type": "ragas", "mode": mode},
                )
                logger.info("✅ RAGAS metrics logged to Opik")
            except Exception as e:
                logger.debug(f"Opik logging failed: {e}")

    def print_report(self, results: Dict[str, Any]):
        """Print formatted evaluation report."""
        print("\n" + "=" * 60)
        print(f"📊 RAGAS EVALUATION REPORT (mode={results['mode']})")
        print("=" * 60)
        print(f"Total questions: {results['total_questions']}")
        print()

        metrics = results["metrics"]
        for name, value in metrics.items():
            if name == "error":
                continue
            threshold = self.THRESHOLDS.get(name, 0.0)
            status = "✅" if value >= threshold else "❌"
            print(f"  {status} {name:25s}: {value:.4f}  (threshold: {threshold:.2f})")

        print("=" * 60)


async def run_evaluation(mode: str = "hybrid"):
    """Convenience function to run full evaluation."""
    evaluator = RAGASEvaluator()
    results = await evaluator.evaluate_graphrag(mode=mode)
    evaluator.print_report(results)
    return results


if __name__ == "__main__":
    asyncio.run(run_evaluation())
