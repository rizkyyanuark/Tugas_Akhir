"""
Ground Truth: Helper for Managing Evaluation Ground Truth
==========================================================
Provides utilities to generate and manage ground truth data
from Neo4j + manual annotation for RAGAS evaluation.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class GroundTruthManager:
    """Manages ground truth data for RAGAS evaluation."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else Path(__file__).parent / "questions.json"
        self.data: Dict = {"questions": []}
        self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            logger.info(f"Loaded {len(self.data.get('questions', []))} questions from {self.path}")

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(self.data['questions'])} questions to {self.path}")

    def add_question(
        self,
        question: str,
        ground_truth: str,
        category: str = "factual",
    ):
        """Add a question with ground truth answer."""
        self.data["questions"].append({
            "question": question,
            "ground_truth": ground_truth,
            "category": category,
        })

    def get_questions(self, category: Optional[str] = None) -> List[Dict]:
        """Get questions, optionally filtered by category."""
        questions = self.data.get("questions", [])
        if category:
            return [q for q in questions if q.get("category") == category]
        return questions

    @property
    def count(self) -> int:
        return len(self.data.get("questions", []))

    def summary(self) -> Dict[str, int]:
        """Get category breakdown."""
        cats: Dict[str, int] = {}
        for q in self.data.get("questions", []):
            cat = q.get("category", "unknown")
            cats[cat] = cats.get(cat, 0) + 1
        return cats
