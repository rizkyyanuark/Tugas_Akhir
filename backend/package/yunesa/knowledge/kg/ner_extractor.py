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
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from gliner import GLiNER

from .config import GLINER_MODEL_NAME, GLINER_THRESHOLD
from .ontology import ONTOLOGY, map_ner_label
from .utils import make_lemma_key, truncate

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Auto-load GLiNER model at module level
# ══════════════════════════════════════════════════════════════
logger.info(f"Loading GLiNER model: {GLINER_MODEL_NAME}...")
gliner_model = GLiNER.from_pretrained(
    GLINER_MODEL_NAME,
    load_tokenizer=True,
    resize_token_embeddings=True,
)
logger.info(f"✅ GLiNER model loaded: {GLINER_MODEL_NAME}")

# Source priority constants (lower = higher priority)
SRC_NER = 0        # GLiNER NER (highest)
SRC_TITLE = 1      # Title regex patterns
SRC_CSV = 2        # CSV keywords (lowest)

# GLiNER label sets (split to avoid context window issues)
GLINER_SET1 = ["method", "metric", "dataset", "task"]
GLINER_SET2 = ["problem", "model", "results", "innovation"]


class EntityStore:
    """Lemma-key based entity store for deduplication.

    Adapted from Strwythura's EntityStore pattern.
    Entities are keyed by POS-lemma normalisation, ensuring that
    'CNN' and 'Convolutional Neural Network' can be merged later.

    Each entity has:
      - uid: unique integer ID
      - text: original surface text
      - label: mapped Neo4j label (e.g. 'Method')
      - count: occurrence count
      - source: source priority (0=NER, 1=Title, 2=CSV)
      - description: LLM-generated description (filled in curation)
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
        """Register an entity in the store. Deduplicates by lemma_key.

        If the entity already exists:
          - If new source has higher priority, update text/label/source
          - Always increment count

        Args:
            text: Entity surface text.
            label: Raw NER label (e.g. 'method', 'model').
            source_priority: 0=NER, 1=Title, 2=CSV.

        Returns:
            lemma_key if registered, None if rejected (too short).
        """
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

    Pass 1: GLiNER zero-shot NER on TLDR/abstract text
    Pass 2: Title regex (acronyms, CamelCase multi-word)
    Pass 3: CSV keywords (author-assigned)

    Args:
        title: Paper title.
        text: TLDR or abstract text (preferably English TLDR).
        csv_keywords: Comma/semicolon separated keywords string.
        entity_store: Existing EntityStore to add to (creates new if None).
        threshold: GLiNER confidence threshold.

    Returns:
        Tuple of (entity_store, list of lemma_keys found in this paper).
    """
    if entity_store is None:
        entity_store = EntityStore()

    paper_lemma_keys: List[str] = []
    full_text = f"{title}. {text}"
    input_text = truncate(full_text, 2000)
    gliner_errors = 0

    # ── Pass 1: GLiNER NER ──
    for label_set in [GLINER_SET1, GLINER_SET2]:
        try:
            ents = gliner_model.predict_entities(
                input_text, label_set, threshold=threshold
            )
            for e in ents:
                lk = entity_store.register(e["text"], e["label"], SRC_NER)
                if lk:
                    paper_lemma_keys.append(lk)
        except Exception as ex:
            gliner_errors += 1
            logger.debug(f"GLiNER error: {type(ex).__name__}: {ex}")

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
