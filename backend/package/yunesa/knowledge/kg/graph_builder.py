"""
Graph Builder: Node & Edge Assembly
====================================
Constructs the KG node/edge dictionaries from:
  1. Structural backbone (Dosen, Paper, Journal, Year, Keyword)
  2. Semantic entities (Method, Model, etc. from NER + LLM curation)

All assembly is pure data transformation — no database I/O.

GraphRAG Enhancement:
  - source_id tracking: every entity/relationship traces back to its chunk
  - text_chunks_db: JSON-serialisable mapping {chunk_id: {content, paper_id, title}}
"""

import re
import json
import logging
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any

import pandas as pd

from .ontology import ONTOLOGY, get_valid_semantic_labels, map_ner_label
from .utils import md5, normalize_text, safe_str, truncate, make_lemma_key
from .ner_extractor import EntityStore
from .entity_resolver import resolve
from .llm_client import GroqClient

logger = logging.getLogger(__name__)

# ── LLM Curation Prompt ──
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

# ── ID Generators ──
def _dosen_id(sid: str, name: str) -> str:
    return f"dosen_{sid}" if sid else f"dosen_{md5(name)}"

def _prodi_id(prodi: str) -> str:
    return f'prodi_{normalize_text(prodi).replace(" ", "_")}'

def _paper_id(title: str) -> str:
    return f"paper_{md5(title)}"

def _year_id(year: str) -> str:
    return f"year_{year}"

def _journal_id(journal_name: str) -> str:
    return f"journal_{md5(journal_name)}"

def _keyword_id(keyword: str) -> str:
    return f"keyword_{md5(keyword)}"


# ── Backbone Processors ──
def _process_dosen_row(row: pd.Series) -> Tuple[Optional[str], Optional[str], Optional[Dict], Optional[Tuple]]:
    """Process a single Dosen row and return ids, node dict, and edge tuple."""
    name = safe_str(row.get("nama_norm")) or safe_str(row.get("nama_dosen"))
    if not name:
        return None, None, None, None

    sid = safe_str(row.get("scholar_id"))
    d_id = _dosen_id(sid, name)
    prodi = safe_str(row.get("prodi"), "Unknown")

    node = {
        "_label": "Dosen",
        "name": name,
        "prodi": prodi,
        "scholar_id": sid,
        "nip": safe_str(row.get("nip")),
        "nidn": safe_str(row.get("nidn")),
    }
    
    p_id = _prodi_id(prodi)
    edge = (d_id, p_id, "MEMBER_OF", {})
    return d_id, p_id, node, edge


def _build_dosen_lookups(df_dosen: pd.DataFrame) -> Tuple[Dict[str, Dict], Dict[str, str]]:
    """Build fast lookup dictionaries for Dosen resolution."""
    dosen_lookup = {}
    dosen_name_lookup = {}
    
    for _, r in df_dosen.iterrows():
        sid = safe_str(r.get("scholar_id"))
        name = safe_str(r.get("nama_norm")) or safe_str(r.get("nama_dosen"))
        
        if sid:
            dosen_lookup[sid.strip()] = r.to_dict()
        if name and sid:
            dosen_name_lookup[name.lower().strip()] = sid
            
    return dosen_lookup, dosen_name_lookup


def build_backbone(
    df_papers: pd.DataFrame,
    df_dosen: pd.DataFrame,
    max_papers: int = 500,
) -> Tuple[Dict[str, Dict], List[Tuple[str, str, str, Dict]], Dict[str, str], Dict[str, str], Dict[str, Dict]]:
    """Build the structural backbone of the knowledge graph.

    Returns:
        Tuple of (nodes, edges, paper_abstracts, paper_titles, text_chunks_db).
        text_chunks_db maps {chunk_id: {content, paper_id, title}} for GraphRAG retrieval.
    """
    nodes: Dict[str, Dict] = {}
    edges: List[Tuple[str, str, str, Dict]] = []
    paper_abstracts: Dict[str, str] = {}
    paper_titles: Dict[str, str] = {}
    text_chunks_db: Dict[str, Dict] = {}

    dosen_lookup, dosen_name_lookup = _build_dosen_lookups(df_dosen)

    # ── 1. Dosen & ProgramStudi ──
    dosen_count = 0
    for _, row in df_dosen.iterrows():
        d_id, p_id, d_node, d_edge = _process_dosen_row(row)
        if not d_id:
            continue
            
        dosen_count += 1
        nodes[d_id] = d_node
        
        if p_id not in nodes:
            nodes[p_id] = {"_label": "ProgramStudi", "name": d_node["prodi"]}
        edges.append(d_edge)

    logger.info(f"Dosen backbone: {dosen_count} dosen registered")

    # ── 2. Filter & Sample Papers ──
    df_with_abstract = df_papers[df_papers["Abstract"].str.len() > 50]
    df_sample = df_with_abstract.sample(n=min(max_papers, len(df_with_abstract)), random_state=42).copy()
    logger.info(f"Filtered: {len(df_with_abstract)} with abstracts, sampled {len(df_sample)}")

    # ── 3. Process Papers ──
    paper_count, keyword_count, skipped_external = 0, 0, 0
    
    for _, row in df_sample.iterrows():
        t = safe_str(row.get("Title"))
        if not t:
            continue

        a = safe_str(row.get("Abstract"))
        y = safe_str(row.get("Year"))[:4] if safe_str(row.get("Year")) else ""
        journal = safe_str(row.get("Journal"))
        link = safe_str(row.get("Link"))
        doi = safe_str(row.get("DOI"))

        if ("scholar" in link.lower() or not link) and doi:
            link = f"https://doi.org/{doi}"

        tldr = safe_str(row.get("tldr"))
        text_for_analysis = tldr if len(tldr) > 20 else a

        pid = _paper_id(t)
        chunk_id = f"chunk_{md5(t)}"
        nodes[pid] = {
            "_label": "Paper",
            "title": t,
            "year": y,
            "url": link,
            "journal": journal,
            "source_id": chunk_id,
        }
        paper_abstracts[pid] = text_for_analysis
        paper_titles[pid] = t
        paper_count += 1

        # Build text_chunks_db entry for GraphRAG retrieval
        text_chunks_db[chunk_id] = {
            "content": text_for_analysis,
            "paper_id": pid,
            "title": t,
            "full_content": f"{t}. {text_for_analysis}",
        }

        # Year Processing
        if y:
            yid = _year_id(y)
            if yid not in nodes:
                nodes[yid] = {"_label": "Year", "value": y}
            edges.append((pid, yid, "PUBLISHED_YEAR", {}))

        # Journal Processing
        j_clean = journal.split(",")[0].strip() if journal else ""
        if j_clean:
            jid = _journal_id(j_clean)
            if jid not in nodes:
                nodes[jid] = {"_label": "Journal", "name": j_clean}
            edges.append((pid, jid, "PUBLISHED_IN", {}))

        # Author Processing
        authors = [x.strip() for x in str(row.get("Authors", "")).split(",") if x.strip()]
        aids = [x.strip() for x in str(row.get("Author IDs", "")).split(";") if x.strip()]

        for i, aname in enumerate(authors):
            if not aname or aname.lower() == "nan":
                continue
                
            asid = aids[i] if i < len(aids) else ""
            is_internal = asid and asid in dosen_lookup

            if not is_internal:
                matched_sid = dosen_name_lookup.get(aname.lower().strip())
                if matched_sid:
                    asid = matched_sid
                    is_internal = True

            if is_internal:
                did = f"dosen_{asid}"
                edges.append((did, pid, "WRITES", {"position": "first" if i == 0 else "co"}))
            else:
                skipped_external += 1

        # Keyword Processing
        kw_raw = safe_str(row.get("Keywords"))
        if kw_raw:
            for kw in re.split(r"[;,]", kw_raw):
                kw = kw.strip()
                if kw and len(kw) > 2:
                    kwid = _keyword_id(kw)
                    if kwid not in nodes:
                        nodes[kwid] = {"_label": "Keyword", "name": kw}
                        keyword_count += 1
                    edges.append((pid, kwid, "HAS_KEYWORD", {}))

    logger.info(
        f"Backbone: {paper_count} papers, {dosen_count} dosen, "
        f"{skipped_external} external skipped, {keyword_count} keywords | "
        f"Nodes: {len(nodes)}, Edges: {len(edges)}"
    )

    return nodes, edges, paper_abstracts, paper_titles, text_chunks_db


# ── Entity Curation Processors ──
def _parse_curated_entity(
    ent: Any, alias_map: Dict[str, str], valid_labels: List[str]
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Parse and validate a single entity from LLM JSON output."""
    if not isinstance(ent, dict):
        return None, None, None, None, None
        
    txt = str(ent.get("text", "")).strip()
    lbl = str(ent.get("label", "Field")).strip()
    desc = str(ent.get("description", "")).strip()

    lbl_cap = lbl.capitalize()
    if lbl_cap not in valid_labels:
        lbl_cap = map_ner_label(lbl)
        
    if not txt or len(txt) < 2:
        return None, None, None, None, None

    lk = resolve(make_lemma_key(txt), alias_map)
    nid = f"{lbl_cap.lower()}_{md5(lk)}"
    return lk, nid, txt, lbl_cap, desc


def _parse_curated_relation(
    rel: Any, entity_node_map: Dict[str, str], alias_map: Dict[str, str]
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Parse and validate a single relation from LLM JSON output."""
    if not isinstance(rel, dict):
        return None, None, None, None
        
    slk = resolve(make_lemma_key(str(rel.get("source", ""))), alias_map)
    tlk = resolve(make_lemma_key(str(rel.get("target", ""))), alias_map)

    if slk in entity_node_map and tlk in entity_node_map:
        rtype = str(rel.get("relation", "USES")).upper().replace(" ", "_")
        rdesc = str(rel.get("description", ""))
        return entity_node_map[slk], entity_node_map[tlk], rtype, rdesc
        
    return None, None, None, None


def curate_entities_llm(
    extracted_entities: Dict[str, List[str]],
    entity_store: EntityStore,
    paper_abstracts: Dict[str, str],
    paper_titles: Dict[str, str],
    alias_map: Dict[str, str],
    nodes: Dict[str, Dict],
    edges: List,
    llm_client: GroqClient,
    text_chunks_db: Optional[Dict[str, Dict]] = None,
) -> Tuple[Dict, List, List, List, List, Dict]:
    """LLM-based entity curation and enrichment."""
    entity_vdb: List[Dict] = []
    relationship_vdb: List[Dict] = []
    keywords_vdb: List[Dict] = []
    entity_node_map: Dict[str, str] = {}
    valid_labels = get_valid_semantic_labels()
    
    logger.info(f"Valid entity labels for curation: {valid_labels}")

    curated_ent_count, curated_rel_count, llm_errors, skipped = 0, 0, 0, 0

    for i, (pid, lemma_keys) in enumerate(extracted_entities.items()):
        abstract = paper_abstracts.get(pid, "")
        title = paper_titles.get(pid, "")

        if len(abstract) < 50:
            skipped += 1
            logger.debug(f"SKIPPED paper {pid}: abstract too short")
            continue

        ent_hints = [
            {"text": entity_store.get(lk)["text"], "label": entity_store.get(lk)["label"]}
            for lk in lemma_keys if lk in entity_store
        ]

        enriched = llm_client.call_with_delay(
            _CURATION_PROMPT.format(
                title=title, abstract=truncate(abstract, 2000),
                entities=json.dumps(ent_hints, ensure_ascii=False)
            )
        )

        if not enriched or not isinstance(enriched, dict):
            llm_errors += 1
            logger.warning(f'LLM returned empty or invalid for paper: "{title[:60]}..."')
            continue

        # 1. Process curated entities
        for ent in enriched.get("entities", []):
            lk, nid, txt, lbl_cap, desc = _parse_curated_entity(ent, alias_map, valid_labels)
            if not lk:
                continue

            # Resolve source_id from paper node
            paper_source_id = nodes.get(pid, {}).get("source_id", "")

            if lk not in entity_node_map:
                entity_node_map[lk] = nid
                nodes[nid] = {"_label": lbl_cap, "name": txt, "description": desc, "source_id": paper_source_id}
                entity_vdb.append({
                    "nodeId": nid, "entityName": txt, "entityType": lbl_cap,
                    "description": desc, "sourceId": paper_source_id,
                })
                curated_ent_count += 1
                
                if lk in entity_store:
                    entity_store.entities[lk]["description"] = desc

            edges.append((pid, entity_node_map[lk], f"HAS_{lbl_cap.upper()}", {}))

        # 2. Process curated relations
        for rel in enriched.get("relations", []):
            src_nid, tgt_nid, rtype, rdesc = _parse_curated_relation(rel, entity_node_map, alias_map)
            if not src_nid:
                continue

            paper_source_id = nodes.get(pid, {}).get("source_id", "")
            edges.append((src_nid, tgt_nid, rtype, {"description": rdesc}))
            relationship_vdb.append({
                "srcId": src_nid, "tgtId": tgt_nid, "relType": rtype,
                "description": rdesc, "sourceId": paper_source_id,
            })
            curated_rel_count += 1

        # 3. Content keywords
        kws = [entity_store.get(lk)["text"] for lk in lemma_keys if lk in entity_store]
        if kws:
            keywords_vdb.append({"keywords": "; ".join(kws), "sourcePaper": pid})

        if (i + 1) % 50 == 0:
            logger.info(f"  Curated {i+1}/{len(extracted_entities)} | entities: {curated_ent_count} | relations: {curated_rel_count} | errors: {llm_errors}")

    logger.info(f"LLM Curation complete: {curated_ent_count} entities, {curated_rel_count} relations, {llm_errors} errors, {skipped} skipped")

    return nodes, edges, entity_vdb, relationship_vdb, keywords_vdb, entity_node_map
