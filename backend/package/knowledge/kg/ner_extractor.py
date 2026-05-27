"""
NER Extractor: Entity Extraction Pipeline
==========================================
Extracts entities from academic paper TLDRs using:
  1. GLiNER zero-shot NER (highest priority)
  2. Title regex patterns (acronyms, CamelCase)
  3. CSV keywords (author-assigned, lowest priority)

Adapted from Strwythura's EntityStore pattern with lemma-key dedup.
"""

import re
import logging
import json
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from .config import (
    GLINER_THRESHOLD,
    LLM_MODEL,
    GROQ_API_KEY,
)
from .utils import (
    make_lemma_key,
    truncate,
    logger,
)
from .ontology import map_ner_label
from .llm_client import GroqClient

# Source priority constants (lower = higher priority)
SRC_NER = 0        # LLM NER (highest)
SRC_TITLE = 1      # Title regex patterns
SRC_CSV = 2        # CSV keywords (lowest)

# Global LLM client for NER
_ner_client: Optional[GroqClient] = None

def get_ner_client() -> Optional[GroqClient]:
    """Lazy loader for GroqClient used in NER."""
    global _ner_client
    if _ner_client is None:
        try:
            if not GROQ_API_KEY:
                logger.warning("GROQ_API_KEY not found. LLM NER will be skipped.")
                return None
            _ner_client = GroqClient()
            logger.info("✅ LLM NER Client (Groq) initialised.")
        except Exception as e:
            logger.error(f"Failed to initialise GroqClient for NER: {e}")
            return None
    return _ner_client


class EntityStore:
    """Lemma-key based entity store for deduplication.

    Adapted from Strwythura's EntityStore pattern.
    Entities are keyed by POS-lemma normalisation, ensuring that
    'CNN' and 'Convolutional Neural Network' can be merged later.
    """

    def __init__(self):
        self.entities: OrderedDict = OrderedDict()
        self._uid_counter: int = 0
        self._counts = {"ner": 0, "title": 0, "csv": 0}

    def register(
        self,
        text: str,
        label: str,
        source_priority: int,
    ) -> Optional[str]:
        """Register an entity in the store. Deduplicates by lemma_key."""
        lemma_key = make_lemma_key(text)
        if not lemma_key or len(lemma_key) < 3:
            return None

        mapped_label = map_ner_label(label)

        if lemma_key not in self.entities:
            # New entity
            self.entities[lemma_key] = {
                "uid": self._uid_counter,
                "text": text.strip(),
                "label": mapped_label,
                "count": 1,
                "source": source_priority,
                "description": "",
            }
            self._uid_counter += 1

            # Track source stats
            if source_priority == SRC_NER:
                self._counts["ner"] += 1
            elif source_priority == SRC_TITLE:
                self._counts["title"] += 1
            else:
                self._counts["csv"] += 1

            logger.debug(
                f'NEW entity [{mapped_label}]: "{text.strip()}" '
                f'→ lemma_key="{lemma_key}" (src={source_priority})'
            )
        elif source_priority < self.entities[lemma_key]["source"]:
            # Higher priority source → update
            old_src = self.entities[lemma_key]["source"]
            self.entities[lemma_key]["text"] = text.strip()
            self.entities[lemma_key]["label"] = mapped_label
            self.entities[lemma_key]["source"] = source_priority
            self.entities[lemma_key]["count"] += 1
            logger.debug(f'PROMOTED entity: "{text.strip()}" source {old_src} → {source_priority}')
        else:
            # Same or lower priority → just increment count
            self.entities[lemma_key]["count"] += 1

        return lemma_key

    def get(self, lemma_key: str) -> Optional[Dict]:
        """Get entity by lemma_key."""
        return self.entities.get(lemma_key)

    def get_all_texts(self) -> List[str]:
        """Return all entity surface texts."""
        return [e["text"] for e in self.entities.values()]

    @property
    def stats(self) -> Dict:
        """Return extraction statistics."""
        return {
            "unique_entities": len(self.entities),
            "from_ner": self._counts["ner"],
            "from_title_regex": self._counts["title"],
            "from_csv_keywords": self._counts["csv"],
        }

    def __len__(self) -> int:
        return len(self.entities)

    def __contains__(self, lemma_key: str) -> bool:
        return lemma_key in self.entities


def extract_entities_from_paper(
    title: str,
    text: str,
    csv_keywords: str = "",
    entity_store: Optional[EntityStore] = None,
    threshold: float = GLINER_THRESHOLD,
) -> Tuple[EntityStore, List[str]]:
    """Extract entities from a single paper using 3-pass NER.

    Pass 1: LLM-based NER on TLDR/abstract text (via Groq)
    Pass 2: Title regex (acronyms, CamelCase multi-word)
    Pass 3: CSV keywords (author-assigned)
    """
    if entity_store is None:
        entity_store = EntityStore()

    paper_lemma_keys: List[str] = []
    full_text = f"{title}. {text}"
    input_text = truncate(full_text, 2000)

    # ── Pass 1: LLM NER (Replacing GLiNER) ──
    client = get_ner_client()
    if client:
        prompt = f"""
You are an expert academic NER system. Extract scientific entities from the text.
Categories:
- method: Algorithms, research methods, techniques.
- model: Specific ML/AI model architectures.
- metric: Evaluation metrics, performance measures.
- dataset: Datasets used or proposed.
- problem: The research problem or gap being addressed.
- task: The computational or research task being performed.
- innovation: Specific novel contributions.

Input Text: {input_text}

Respond ONLY with a JSON object:
{{
  "entities": [
    {{"text": "Entity Name", "label": "method"}},
    ...
  ]
}}
"""
        try:
            res = client.call(prompt)
            if "entities" in res:
                for e in res["entities"]:
                    # Basic validation of extracted entity
                    if "text" in e and "label" in e:
                        lk = entity_store.register(e["text"], e["label"], SRC_NER)
                        if lk:
                            paper_lemma_keys.append(lk)
        except Exception as ex:
            logger.warning(f"LLM NER error: {ex}")

    # ── Pass 2: Title regex (acronyms + CamelCase) ──
    for term in re.findall(r"[A-Z]{2,}[0-9]*", title):
        lk = entity_store.register(term, "method", SRC_TITLE)
        if lk:
            paper_lemma_keys.append(lk)

    for term in re.findall(r"[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)+", title):
        lk = entity_store.register(term, "method", SRC_TITLE)
        if lk:
            paper_lemma_keys.append(lk)

    # ── Pass 3: CSV Keywords ──
    if csv_keywords and csv_keywords.lower() != "nan":
        for kw in re.split(r"[;,]", csv_keywords):
            kw = kw.strip()
            if kw and len(kw) > 2:
                lk = entity_store.register(kw, "field", SRC_CSV)
                if lk:
                    paper_lemma_keys.append(lk)

    return entity_store, list(set(paper_lemma_keys))
