"""
RAG evaluation metrics calculation utilities.
Simplified version: keep only Recall/F1 (retrieval) and LLM Judge (answer correctness).
"""

import json
import textwrap
from typing import Any

from yunesa.utils import logger


class RetrievalMetrics:
    """Retrieval evaluation metric calculators."""

    @staticmethod
    def precision_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
        """Calculate Precision@K."""
        if not retrieved_ids[:k]:
            return 0.0
        retrieved_set = set(retrieved_ids[:k])
        relevant_set = set(relevant_ids)
        return len(retrieved_set & relevant_set) / k

    @staticmethod
    def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
        """Calculate Recall@K."""
        if not relevant_ids:
            return 0.0
        retrieved_set = set(retrieved_ids[:k])
        relevant_set = set(relevant_ids)
        return len(retrieved_set & relevant_set) / len(relevant_set)

    @staticmethod
    def f1_score_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
        """Calculate F1@K."""
        precision = RetrievalMetrics.precision_at_k(
            retrieved_ids, relevant_ids, k)
        recall = RetrievalMetrics.recall_at_k(retrieved_ids, relevant_ids, k)
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)


class AnswerMetrics:
    """Answer evaluation metric calculators."""

    @staticmethod
    async def judge_correctness(query: str, generated_answer: str, gold_answer: str, judge_llm: Any) -> dict[str, Any]:
        """
        Use an LLM to judge whether the generated answer is correct.
        """
        if not generated_answer:
            return {"score": 0.0, "reasoning": "No generated answer"}
        if not gold_answer:
            return {"score": 0.0, "reasoning": "No reference answer"}

        prompt = textwrap.dedent(f"""You are a fair evaluator. Please assess the accuracy of the AI-generated answer against the gold answer.

            Question: {query}

            Gold answer:
            {gold_answer}

            AI-generated answer:
            {generated_answer}

            Determine whether the AI-generated answer is factually consistent with the gold answer.
            Ignore minor differences in wording, punctuation, or formatting.
            Focus only on whether the core facts are accurately included.

            Return the result in the following JSON format (do not include any extra text):
            {{
                "score": 1.0,  // Return 1.0 if correct, return 0.0 if incorrect
                "reasoning": "Brief explanation of the judgment"
            }}
            """)
        try:
            response = await judge_llm.call(prompt, stream=False)
            content = response.content.strip()

            # Try to clean up potential markdown code blocks.
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            result = json.loads(content)
            return {"score": float(result.get("score", 0.0)), "reasoning": result.get("reasoning", "")}
        except Exception as e:
            logger.error(f"LLM judgment failed: {e}")
            return {"score": 0.0, "reasoning": f"Judgment error: {str(e)}"}


class EvaluationMetricsCalculator:
    """Comprehensive evaluation metric calculator."""

    @staticmethod
    def calculate_retrieval_metrics(
        retrieved_chunks: list[dict[str, Any]], gold_chunk_ids: list[str], k_values: list[int] = [1, 3, 5, 10]
    ) -> dict[str, float]:
        """Calculate retrieval metrics (Recall, F1)."""
        if not retrieved_chunks or not gold_chunk_ids:
            return {}

        # extract ID
        retrieved_ids = []
        for chunk in retrieved_chunks:
            chunk_id = chunk.get("chunk_id") or chunk.get(
                "metadata", {}).get("chunk_id")
            retrieved_ids.append(str(chunk_id) if chunk_id else "")

        metrics = {}
        for k in k_values:
            metrics[f"recall@{k}"] = RetrievalMetrics.recall_at_k(
                retrieved_ids, gold_chunk_ids, k)
            metrics[f"f1@{k}"] = RetrievalMetrics.f1_score_at_k(
                retrieved_ids, gold_chunk_ids, k)

        return metrics

    @staticmethod
    async def calculate_answer_metrics(
        query: str, generated_answer: str, gold_answer: str, judge_llm: Any = None
    ) -> dict[str, Any]:
        """Calculate answer metrics (LLM Judge)."""
        if not judge_llm:
            return {}

        return await AnswerMetrics.judge_correctness(query, generated_answer, gold_answer, judge_llm)

    @staticmethod
    def calculate_overall_score(
        retrieval_metrics_list: list[dict[str, float]], answer_metrics_list: list[dict[str, Any]]
    ) -> float:
        """Calculate an overall average score."""
        total_score = 0.0
        count = 0

        # Simple averaging strategy: average retrieval metric values and answer scores together.
        # Users may prefer to view them separately, but this method returns a single score.

        # Calculate average retrieval score.
        for m in retrieval_metrics_list:
            if m:
                total_score += sum(m.values()) / len(m)
                count += 1

        # Calculate average answer score.
        for m in answer_metrics_list:
            if "score" in m:
                total_score += m["score"]
                count += 1

        return total_score / count if count > 0 else 0.0
