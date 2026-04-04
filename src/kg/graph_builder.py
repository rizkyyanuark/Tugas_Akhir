"""
Graph Builder: Node & Edge Assembly
====================================
Constructs the KG node/edge dictionaries from:
  1. Structural backbone (Dosen, Paper, Journal, Year, Keyword)
  2. Semantic entities (Method, Model, etc. from NER + LLM curation)

All assembly is pure data transformation — no database I/O.
"""

import re
import json
import logging
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any

import pandas as pd

from .ontology import ONTOLOGY, get_valid_semantic_labels, map_ner_label
from .utils import md5, normalize_text, safe_str, truncate
from .ner_extractor import EntityStore
from .entity_resolver import resolve
from .llm_client import GroqClient

logger = logging.getLogger(__name__)

# ── LLM Curation Prompt (Cell 5) ──
_CURATION_PROMPT = (
    "Kamu ahli NLP. Validasi dan perkaya entitas dari paper akademik ini.\n\n"
    "## Judul: {title}\n"
    "## Abstrak: {abstract}\n"
    "## Entitas terdeteksi NER (mungkin noisy): {entities}\n\n"
    "## Tugas:\n"
    "1. VALIDASI: hapus yang bukan entitas ilmiah (kata umum).\n"
    "2. PERBAIKI label jika salah. Label valid: Method, Model, Metric, Dataset, Problem, Task, Field, Tool, Innovation\n"
    "3. TAMBAHKAN entitas penting yang terlewat oleh NER.\n"
    "4. Berikan DESCRIPTION 1 kalimat per entitas (untuk vector search).\n"
    "5. Ekstrak RELASI antar entitas: USES (source uses target), ADDRESSES, PROPOSES\n\n"
    "## Output JSON:\n"
    '{{"entities": [{{"text": "exact text", "label": "Method", "description": "1 sentence"}}],\n'
    '  "relations": [{{"source": "entity1", "target": "entity2", "relation": "USES", "description": "1 sentence"}}]}}\n\n'
    "PENTING: Entitas harus text spans yang ADA di abstrak/judul. Minimal 3 entitas per abstrak."
)


def build_backbone(
    df_papers: pd.DataFrame,
    df_dosen: pd.DataFrame,
    max_papers: int = 500,
) -> Tuple[Dict, List, Dict[str, str], Dict[str, str]]:
    """Build the structural backbone of the knowledge graph.

    Creates nodes and edges for: Dosen, ProgramStudi,
    Paper, Year, Journal, Keyword.

    Args:
        df_papers: Papers DataFrame with columns: Title, Abstract, Year,
                   Authors, Author IDs, Journal, Keywords, DOI, Link, tldr.
        df_dosen: Lecturers DataFrame with columns: scholar_id, nama_norm/nama_dosen,
                  prodi, nip, nidn.
        max_papers: Maximum number of papers to process.

    Returns:
        Tuple of:
          - nodes: Dict[node_id, node_properties]
          - edges: List[Tuple[src_id, tgt_id, rel_type, props]]
          - paper_abstracts: Dict[paper_id, abstract_text]
          - paper_titles: Dict[paper_id, title_text]
    """
    nodes: Dict[str, Dict] = {}
    edges: List[Tuple[str, str, str, Dict]] = []
    paper_abstracts: Dict[str, str] = {}
    paper_titles: Dict[str, str] = {}

    # Build dosen lookup by scholar_id AND by normalised name
    dosen_lookup = {
        str(r["scholar_id"]).strip(): r.to_dict()
        for _, r in df_dosen.iterrows()
        if safe_str(r.get("scholar_id"))
    }
    # Secondary lookup: lowercased name → scholar_id (for Smart Name Fallback)
    dosen_name_lookup = {}
    for _, r in df_dosen.iterrows():
        name = safe_str(r.get("nama_norm")) or safe_str(r.get("nama_dosen"))
        sid = safe_str(r.get("scholar_id"))
        if name and sid:
            dosen_name_lookup[name.lower().strip()] = sid

    # ── Dosen → ProgramStudi ──
    dosen_count = 0
    for _, row in df_dosen.iterrows():
        name = safe_str(row.get("nama_norm")) or safe_str(row.get("nama_dosen"))
        if not name:
            continue
        dosen_count += 1

        sid = safe_str(row.get("scholar_id"))
        d_id = f"dosen_{sid}" if sid else f"dosen_{md5(name)}"
        prodi = safe_str(row.get("prodi"), "Unknown")

        nodes[d_id] = {
            "_label": "Dosen",
            "name": name,
            "prodi": prodi,
            "scholar_id": sid,
            "nip": safe_str(row.get("nip")),
            "nidn": safe_str(row.get("nidn")),
        }

        # ProgramStudi node
        p_id = f'prodi_{normalize_text(prodi).replace(" ", "_")}'
        if p_id not in nodes:
            nodes[p_id] = {"_label": "ProgramStudi", "name": prodi}
        edges.append((d_id, p_id, "MEMBER_OF", {}))

    logger.info(f"Dosen backbone: {dosen_count} dosen registered")

    # ── Filter & Sample Papers ──
    df_with_abstract = df_papers[df_papers["Abstract"].str.len() > 50]
    df_sample = df_with_abstract.sample(
        n=min(max_papers, len(df_with_abstract)), random_state=42
    ).copy()
    logger.info(f"Filtered: {len(df_with_abstract)} with abstracts, sampled {len(df_sample)}")

    # ── Papers → Year, Journal, Authors (Dosen only), Keywords ──
    paper_count, keyword_count = 0, 0
    skipped_external = 0
    for _, row in df_sample.iterrows():
        t = safe_str(row.get("Title"))
        if not t:
            continue

        a = safe_str(row.get("Abstract"))
        y = safe_str(row.get("Year"))[:4] if safe_str(row.get("Year")) else ""
        journal = safe_str(row.get("Journal"))
        link = safe_str(row.get("Link"))
        doi = safe_str(row.get("DOI"))

        # Prefer DOI link over Scholar link
        if ("scholar" in link.lower() or not link) and doi:
            link = f"https://doi.org/{doi}"

        # Use TLDR if available for text analysis, fallback to abstract
        tldr = safe_str(row.get("tldr"))
        # If TLDR is available, prioritize it because it is robustly formatted in English.
        text_for_analysis = tldr if len(tldr) > 20 else a

        pid = f"paper_{md5(t)}"
        nodes[pid] = {
            "_label": "Paper",
            "title": t,
            "year": y,
            "url": link,
            "journal": journal,
        }
        # paper_abstracts is heavily used in downstream NER and LLM tasks.
        paper_abstracts[pid] = text_for_analysis
        paper_titles[pid] = t
        paper_count += 1

        # Year
        if y:
            yid = f"year_{y}"
            if yid not in nodes:
                nodes[yid] = {"_label": "Year", "value": y}
            edges.append((pid, yid, "PUBLISHED_YEAR", {}))

        # Journal
        j_clean = journal.split(",")[0].strip() if journal else ""
        if j_clean:
            jid = f"journal_{md5(j_clean)}"
            if jid not in nodes:
                nodes[jid] = {"_label": "Journal", "name": j_clean}
            edges.append((pid, jid, "PUBLISHED_IN", {}))

        # Authors — Smart Name Fallback: scholar_id first, then name match
        authors = [x.strip() for x in str(row.get("Authors", "")).split(",") if x.strip()]
        aids = [x.strip() for x in str(row.get("Author IDs", "")).split(";") if x.strip()]
        paper_dosen_names = []  # track dosen names for this paper

        for i, aname in enumerate(authors):
            if not aname or aname.lower() == "nan":
                continue
            asid = aids[i] if i < len(aids) else ""
            is_internal = asid and asid in dosen_lookup

            # Smart Name Fallback: if scholar_id is missing/invalid,
            # try matching by lowered name against dosen master data
            if not is_internal:
                matched_sid = dosen_name_lookup.get(aname.lower().strip())
                if matched_sid:
                    asid = matched_sid
                    is_internal = True

            if is_internal:
                did = f"dosen_{asid}"
                # Node may already exist from backbone; safe to skip duplicate
                edges.append(
                    (did, pid, "WRITES", {"position": "first" if i == 0 else "co"})
                )
                paper_dosen_names.append(aname)
            else:
                # Not internal dosen — skip entirely (ETL already filtered)
                skipped_external += 1

        # Keywords
        kw_raw = safe_str(row.get("Keywords"))
        if kw_raw:
            for kw in re.split(r"[;,]", kw_raw):
                kw = kw.strip()
                if kw and len(kw) > 2:
                    kwid = f"keyword_{md5(kw)}"
                    if kwid not in nodes:
                        nodes[kwid] = {"_label": "Keyword", "name": kw}
                        keyword_count += 1
                    edges.append((pid, kwid, "HAS_KEYWORD", {}))

    logger.info(
        f"Backbone: {paper_count} papers, {dosen_count} dosen, "
        f"{skipped_external} external skipped, {keyword_count} keywords | "
        f"Nodes: {len(nodes)}, Edges: {len(edges)}"
    )

    return nodes, edges, paper_abstracts, paper_titles


def curate_entities_llm(
    extracted_entities: Dict[str, List[str]],
    entity_store: EntityStore,
    paper_abstracts: Dict[str, str],
    paper_titles: Dict[str, str],
    alias_map: Dict[str, str],
    nodes: Dict[str, Dict],
    edges: List,
    llm_client: GroqClient,
) -> Tuple[Dict, List, List, List, List, Dict]:
    """LLM-based entity curation and enrichment (Cell 5).

    For each paper, sends NER-detected entities + abstract to Groq for:
      - Validation (remove non-scientific entities)
      - Label correction
      - Description generation (for vector search)
      - Inter-entity relation extraction

    Args:
        extracted_entities: Dict of {paper_id: [lemma_keys]}.
        entity_store: The EntityStore with all detected entities.
        paper_abstracts: Dict of {paper_id: abstract_text}.
        paper_titles: Dict of {paper_id: title_text}.
        alias_map: Combined alias map from entity resolution.
        nodes: Existing nodes dict (mutated in place).
        edges: Existing edges list (mutated in place).
        llm_client: Initialised GroqClient.

    Returns:
        Tuple of:
          - nodes (updated)
          - edges (updated)
          - entity_vdb: List of dicts for Weaviate EntityEmbedding
          - relationship_vdb: List of dicts for Weaviate RelationshipEmbedding
          - keywords_vdb: List of dicts for Weaviate ContentKeyword
          - entity_node_map: Dict of {lemma_key: node_id}
    """
    entity_vdb: List[Dict] = []
    relationship_vdb: List[Dict] = []
    keywords_vdb: List[Dict] = []
    entity_node_map: Dict[str, str] = {}

    VALID_LABELS = get_valid_semantic_labels()
    logger.info(f"Valid entity labels for curation: {VALID_LABELS}")

    total = len(extracted_entities)
    curated_ent_count, curated_rel_count = 0, 0
    llm_errors, skipped = 0, 0

    for i, (pid, lemma_keys) in enumerate(extracted_entities.items()):
        abstract = paper_abstracts.get(pid, "")
        title = paper_titles.get(pid, "")

        if len(abstract) < 50:
            skipped += 1
            logger.debug(f"SKIPPED paper {pid}: abstract too short ({len(abstract)} chars)")
            continue

        # Build entity hints for LLM
        ent_hints = [
            {"text": entity_store.get(lk)["text"], "label": entity_store.get(lk)["label"]}
            for lk in lemma_keys
            if lk in entity_store
        ]

        enriched = llm_client.call_with_delay(
            _CURATION_PROMPT.format(
                title=title,
                abstract=truncate(abstract, 2000),
                entities=json.dumps(ent_hints, ensure_ascii=False),
            )
        )

        if not enriched:
            llm_errors += 1
            logger.warning(f'LLM returned empty for paper: "{title[:60]}..."')
            continue

        # Process curated entities
        for ent in enriched.get("entities", []):
            if not isinstance(ent, dict):
                continue
            txt = str(ent.get("text", "")).strip()
            lbl = str(ent.get("label", "Field")).strip()
            desc = str(ent.get("description", "")).strip()

            lbl_cap = lbl.capitalize()
            if lbl_cap not in VALID_LABELS:
                lbl_cap = map_ner_label(lbl)
            if not txt or len(txt) < 2:
                continue

            from .utils import make_lemma_key as _mlk

            lk = resolve(_mlk(txt), alias_map)
            nid = f"{lbl_cap.lower()}_{md5(lk)}"

            if lk not in entity_node_map:
                entity_node_map[lk] = nid
                nodes[nid] = {"_label": lbl_cap, "name": txt, "description": desc}
                entity_vdb.append({
                    "nodeId": nid,
                    "entityName": txt,
                    "entityType": lbl_cap,
                    "description": desc,
                })
                curated_ent_count += 1
                logger.debug(f'CURATED entity [{lbl_cap}]: "{txt}" → {nid}')

                # Update entity store description
                if lk in entity_store:
                    entity_store.entities[lk]["description"] = desc

            edges.append((pid, entity_node_map[lk], f"HAS_{lbl_cap.upper()}", {}))

        # Process curated relations
        for rel in enriched.get("relations", []):
            if not isinstance(rel, dict):
                continue
            slk = resolve(_mlk(str(rel.get("source", ""))), alias_map)
            tlk = resolve(_mlk(str(rel.get("target", ""))), alias_map)

            if slk in entity_node_map and tlk in entity_node_map:
                rtype = str(rel.get("relation", "USES")).upper().replace(" ", "_")
                rdesc = str(rel.get("description", ""))
                edges.append(
                    (entity_node_map[slk], entity_node_map[tlk], rtype, {"description": rdesc})
                )
                relationship_vdb.append({
                    "srcId": entity_node_map[slk],
                    "tgtId": entity_node_map[tlk],
                    "relType": rtype,
                    "description": rdesc,
                })
                curated_rel_count += 1
                logger.debug(f"RELATION: {entity_node_map[slk]} -[{rtype}]→ {entity_node_map[tlk]}")

        # Content keywords for this paper
        kws = [entity_store.get(lk)["text"] for lk in lemma_keys if lk in entity_store]
        if kws:
            keywords_vdb.append({"keywords": "; ".join(kws), "sourcePaper": pid})

        if (i + 1) % 50 == 0:
            logger.info(
                f"  Curated {i+1}/{total} | entities: {curated_ent_count} | "
                f"relations: {curated_rel_count} | errors: {llm_errors}"
            )

    logger.info(
        f"LLM Curation complete: {curated_ent_count} entities, "
        f"{curated_rel_count} relations, {llm_errors} errors, {skipped} skipped"
    )

    return nodes, edges, entity_vdb, relationship_vdb, keywords_vdb, entity_node_map
