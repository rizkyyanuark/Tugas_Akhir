"""
Entity Resolver: 3-Layer Entity Resolution
============================================
Resolves duplicate entities using a progressive strategy:
  Layer 1: Lemma-key dedup (handled by EntityStore)
  Layer 2: Abbreviation extraction via regex from abstracts
  Layer 3: LLM synonym clustering via Groq

Adapted from Strwythura's entity resolution pipeline.
"""

import re
import logging
from typing import Dict, List, Optional, Set

from .llm_client import GroqClient
from .utils import make_lemma_key
from .config import LLM_BATCH_SIZE

logger = logging.getLogger(__name__)

# ── Abbreviation regex patterns ──
# Pattern 1: "Convolutional Neural Network (CNN)"
_ABBR_PAT1 = re.compile(r"([A-Za-z][\w\s\-]+?)\s*\(([A-Z][A-Za-z0-9\s\-\.]*?)\)")
# Pattern 2: "CNN (Convolutional Neural Network)"
_ABBR_PAT2 = re.compile(r"([A-Z][A-Z0-9]{1,10})\s*\(([A-Za-z][\w\s\-]+?)\)")

# LLM prompt for synonym clustering
_CLUSTER_PROMPT = (
    "Kamu ahli Entity Resolution untuk KG akademik.\n"
    "Kelompokkan entitas yang BERMAKNA SAMA (sinonim, singkatan, terjemahan).\n\n"
    'Contoh: "QoS" = "Quality of Service" | "CNN" = "Convolutional Neural Network" | "akurasi" = "accuracy"\n\n'
    "Daftar entitas:\n{ents}\n\n"
    'Output JSON: {{"groups": [{{"canonical": "English standard name", "members": ["var1", "var2"]}}]}}\n'
    "Hanya kelompokkan yang BENAR-BENAR sinonim. Entitas unik tidak perlu dimasukkan."
)


def extract_abbreviations(
    paper_abstracts: Dict[str, str],
    paper_titles: Dict[str, str],
) -> Dict[str, str]:
    """Layer 2: Extract abbreviation aliases from paper texts.

    Scans abstracts for patterns like:
      "Convolutional Neural Network (CNN)" → alias CNN → full form
      "CNN (Convolutional Neural Network)" → alias CNN → full form

    Args:
        paper_abstracts: Dict of {paper_id: abstract_text}.
        paper_titles: Dict of {paper_id: title_text}.

    Returns:
        Dict of {short_lemma_key: long_lemma_key} aliases.
    """
    alias_map: Dict[str, str] = {}
    match_count = 0

    for pid, abstract in paper_abstracts.items():
        title = paper_titles.get(pid, "")
        full = f"{title}. {abstract}"

        for pat in [_ABBR_PAT1, _ABBR_PAT2]:
            for m in pat.finditer(full):
                a, b = m.group(1).strip(), m.group(2).strip()
                short, long_ = (a, b) if len(a) < len(b) else (b, a)

                if len(short) >= 2:
                    lk_short = make_lemma_key(short)
                    lk_long = make_lemma_key(long_)

                    if lk_short and lk_long and lk_short != lk_long:
                        alias_map[lk_short] = lk_long
                        match_count += 1
                        logger.debug(f'ABBREV alias: "{short}" → "{long_}"')

    logger.info(f"Layer 2 (Regex): {len(alias_map)} abbreviation aliases from {match_count} matches")
    return alias_map


def cluster_synonyms_llm(
    entity_texts: List[str],
    llm_client: GroqClient,
    batch_size: int = LLM_BATCH_SIZE,
) -> Dict[str, str]:
    """Layer 3: Cluster synonymous entities using LLM.

    Sends batches of entity texts to Groq and asks for synonym grouping.

    Args:
        entity_texts: List of all entity surface texts.
        llm_client: Initialised GroqClient.
        batch_size: Number of entities per LLM batch.

    Returns:
        Dict of {member_lemma_key: canonical_lemma_key} aliases.
    """
    alias_map: Dict[str, str] = {}
    cluster_count = 0
    batch_count = 0

    for start in range(0, len(entity_texts), batch_size):
        batch = entity_texts[start : start + batch_size]
        if len(batch) < 2:
            continue

        batch_count += 1
        ents_str = "\n".join([f"- {e}" for e in batch])
        result = llm_client.call_with_delay(
            _CLUSTER_PROMPT.format(ents=ents_str),
            delay=0.3,
        )

        for grp in result.get("groups", []):
            if not isinstance(grp, dict):
                continue
            canonical = grp.get("canonical", "")
            members = grp.get("members", [])

            if canonical and len(members) > 1:
                lk_canon = make_lemma_key(canonical)
                for member in members:
                    lk_mem = make_lemma_key(member)
                    if lk_mem and lk_mem != lk_canon:
                        alias_map[lk_mem] = lk_canon
                        logger.debug(f'LLM synonym: "{member}" → "{canonical}"')
                cluster_count += 1

        if batch_count % 5 == 0:
            logger.info(
                f"  LLM clustering batch {batch_count}/{(len(entity_texts) // batch_size) + 1}..."
            )

    logger.info(f"Layer 3 (LLM): {cluster_count} synonym clusters from {batch_count} batches")
    return alias_map


def build_alias_map(
    entity_texts: List[str],
    paper_abstracts: Dict[str, str],
    paper_titles: Dict[str, str],
    llm_client: GroqClient,
    batch_size: int = LLM_BATCH_SIZE,
) -> Dict[str, str]:
    """Build the complete alias map using Layer 2 + Layer 3.

    Layer 1 (lemma dedup) is handled by EntityStore.register().

    Args:
        entity_texts: All entity surface texts from EntityStore.
        paper_abstracts: Dict of {paper_id: abstract_text}.
        paper_titles: Dict of {paper_id: title_text}.
        llm_client: Initialised GroqClient.
        batch_size: Number of entities per LLM batch.

    Returns:
        Combined alias map {source_lemma_key: canonical_lemma_key}.
    """
    # Layer 2: abbreviation extraction
    alias_map = extract_abbreviations(paper_abstracts, paper_titles)

    # Layer 3: LLM synonym clustering
    llm_aliases = cluster_synonyms_llm(entity_texts, llm_client, batch_size)
    alias_map.update(llm_aliases)

    logger.info(f"Total alias mappings: {len(alias_map)}")
    return alias_map


def resolve(lemma_key: str, alias_map: Dict[str, str]) -> str:
    """Resolve a lemma key through transitive alias chain.

    Handles cycles via `visited` set to prevent infinite loops.

    Args:
        lemma_key: The lemma key to resolve.
        alias_map: The combined alias map.

    Returns:
        The canonical lemma key after full resolution.
    """
    visited: Set[str] = set()
    while lemma_key in alias_map and lemma_key not in visited:
        visited.add(lemma_key)
        lemma_key = alias_map[lemma_key]
    return lemma_key


def apply_resolution(
    extracted_entities: Dict[str, List[str]],
    alias_map: Dict[str, str],
) -> int:
    """Apply alias resolution to all extracted entity references.

    Modifies `extracted_entities` in place.

    Args:
        extracted_entities: Dict of {paper_id: [lemma_keys]}.
        alias_map: The combined alias map.

    Returns:
        Number of references that were merged/resolved.
    """
    merged_count = 0

    for pid in extracted_entities:
        resolved = []
        for lk in extracted_entities[pid]:
            canon = resolve(lk, alias_map)
            if canon != lk:
                merged_count += 1
                logger.debug(f'MERGED: "{lk}" → "{canon}" in paper {pid}')
            resolved.append(canon)
        extracted_entities[pid] = list(set(resolved))

    return merged_count
