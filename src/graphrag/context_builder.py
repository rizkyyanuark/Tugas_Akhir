"""
Context Builder: Context Fusion & Prompt Assembly
===================================================
Implements Step ④ of AcademicRAG:
  Local context + Global context → structured CSV prompt for LLM generation
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def build_entities_context(entities: List[Dict]) -> str:
    """Format entity data as structured CSV context."""
    if not entities:
        return "Tidak ada entitas relevan ditemukan."

    lines = ["entity_name,entity_type,description"]
    for e in entities:
        name = e.get("entityName") or e.get("name") or ""
        etype = e.get("entityType") or e.get("label") or ""
        desc = e.get("description") or ""
        if name:
            # Escape commas in fields for CSV format
            lines.append(f'"{name}","{etype}","{desc}"')

    return "\n".join(lines)


def build_relationships_context(relationships: List[Dict]) -> str:
    """Format relationship data as structured CSV context."""
    if not relationships:
        return "Tidak ada relasi relevan ditemukan."

    lines = ["source,relationship,target,description"]
    for r in relationships:
        src = r.get("srcId") or r.get("src") or ""
        tgt = r.get("tgtId") or r.get("tgt") or ""
        rel = r.get("relType") or r.get("rel_type") or ""
        desc = r.get("description") or ""
        if src and tgt:
            lines.append(f'"{src}","{rel}","{tgt}","{desc}"')

    return "\n".join(lines)


def build_text_units_context(text_units: List[Dict], max_units: int = 5) -> str:
    """Format text unit data as numbered context blocks."""
    if not text_units:
        return "Tidak ada konten paper terkait."

    blocks = []
    for i, unit in enumerate(text_units[:max_units]):
        title = unit.get("title", "")
        content = unit.get("content") or unit.get("full_content", "")
        # Truncate long content
        if len(content) > 500:
            content = content[:500] + "..."
        blocks.append(f"[Paper {i+1}] {title}\n{content}")

    return "\n\n".join(blocks)


def fuse_contexts(
    local_context: Dict[str, Any],
    global_context: Dict[str, Any],
) -> Dict[str, str]:
    """Fuse local and global retrieval contexts into prompt-ready strings.

    Args:
        local_context: Output from local_retriever.subgraph_retrieve()
        global_context: Output from global_retriever.global_edge_retrieve()

    Returns:
        Dict with entities_context, relationships_context, text_units_context.
    """
    # Merge entities (deduplicate by name)
    all_entities = []
    seen_names = set()
    for e in local_context.get("entities", []) + global_context.get("entities", []):
        name = e.get("entityName") or e.get("name") or ""
        if name and name not in seen_names:
            seen_names.add(name)
            all_entities.append(e)

    # Merge relationships (deduplicate by src-rel-tgt)
    all_rels = []
    seen_rels = set()
    for r in local_context.get("relationships", []) + global_context.get("relationships", []):
        src = r.get("srcId") or r.get("src") or ""
        tgt = r.get("tgtId") or r.get("tgt") or ""
        rel = r.get("relType") or r.get("rel_type") or ""
        key = f"{src}-{rel}-{tgt}"
        if key not in seen_rels:
            seen_rels.add(key)
            all_rels.append(r)

    # Merge text units (deduplicate by title)
    all_units = []
    seen_titles = set()
    for u in local_context.get("text_units", []) + global_context.get("text_units", []):
        title = u.get("title", "")
        if title not in seen_titles:
            seen_titles.add(title)
            all_units.append(u)

    logger.info(
        f"Context fusion: {len(all_entities)} entities, "
        f"{len(all_rels)} relationships, {len(all_units)} text units"
    )

    return {
        "entities_context": build_entities_context(all_entities),
        "relationships_context": build_relationships_context(all_rels),
        "text_units_context": build_text_units_context(all_units),
    }
