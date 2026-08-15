"""Prompt and context templates aligned with the AcademicRAG backbone."""

from __future__ import annotations

from typing import Any


RAG_RESPONSE_TEMPLATE = """---Role---

You are a helpful assistant responding to user query about Knowledge Base
provided below.

---Goal---

Generate a concise response based on Knowledge Base and follow Response Rules,
considering both the conversation history and the current query. Summarize all
information in the provided Knowledge Base. Do not include information not
provided by Knowledge Base.

When handling relationships with timestamps:
1. Each relationship may have a timestamp indicating when we acquired this
   knowledge
2. When encountering conflicting relationships, consider both the semantic
   content and the timestamp
3. Do not automatically prefer the most recently created relationships; use
   judgment based on the context
4. For time-specific queries, prioritize temporal information in the content
   before considering creation timestamps

---Conversation History---
{history}

---Grounding---
{grounding}

---Knowledge Base---
{context_data}

---Response Rules---

- Target format and length: {response_type}
- Use markdown formatting with appropriate section headings.
- Answer in the same language as the user's question.
- Ensure the response maintains continuity with the conversation history.
- List up to 5 most important reference sources at the end under "References".
  Clearly indicate whether each source is from Knowledge Graph (KG) or Vector
  Data (DC), and include the file path or source id if available.
- If grounding.status is "empty" or "supporting_only", say the requested
  academic data was not found in the YUNESA academic knowledge graph.
- Do not answer from model memory, web knowledge, or external academic databases.
- If you do not know the answer, say so. Do not make anything up.
- Do not include information not provided by the Knowledge Base.
"""


NAIVE_RAG_RESPONSE_TEMPLATE = """---Role---

You are a helpful assistant responding to user query about Document Chunks
provided below.

---Goal---

Generate a concise response based on Document Chunks and follow Response Rules,
considering both the conversation history and the current query. Summarize all
information in the provided Document Chunks. Do not include information not
provided by Document Chunks.

When handling content with timestamps:
1. Each piece of content may have a timestamp indicating when we acquired this
   knowledge
2. When encountering conflicting information, consider both the content and the
   timestamp
3. Do not automatically prefer the most recent content; use judgment based on
   the context
4. For time-specific queries, prioritize temporal information in the content
   before considering creation timestamps

---Conversation History---
{history}

---Grounding---
{grounding}

---Document Chunks---
{content_data}

---Response Rules---

- Target format and length: {response_type}
- Use markdown formatting with appropriate section headings.
- Answer in the same language as the user's question.
- Ensure the response maintains continuity with the conversation history.
- List up to 5 most important reference sources at the end under "References".
  Clearly indicate whether each source is from Vector Data (DC), and include the
  file path or source id if available.
- If grounding.status is "empty" or "supporting_only", say the requested
  academic data was not found in the YUNESA academic knowledge graph.
- Do not answer from model memory, web knowledge, or external academic databases.
- If you do not know the answer, say so.
- Do not include information not provided by the Document Chunks.
"""


MIX_RAG_RESPONSE_TEMPLATE = """---Role---

You are a helpful assistant responding to user query about Data Sources provided
below.

---Goal---

Generate a concise response based on Data Sources and follow Response Rules,
considering both the conversation history and the current query. Data sources
contain two parts: Knowledge Graph(KG) and Document Chunks(DC). Summarize all
information in the provided Data Sources. Do not include information not
provided by Data Sources.

When handling information with timestamps:
1. Each piece of information may have a timestamp indicating when we acquired
   this knowledge
2. When encountering conflicting information, consider both the
   content/relationship and the timestamp
3. Do not automatically prefer the most recent information; use judgment based
   on the context
4. For time-specific queries, prioritize temporal information in the content
   before considering creation timestamps

---Conversation History---
{history}

---Grounding---
{grounding}

---Data Sources---

1. From Knowledge Graph(KG):
{kg_context}

2. From Document Chunks(DC):
{vector_context}

---Response Rules---

- Target format and length: {response_type}
- Use markdown formatting with appropriate section headings.
- Answer in the same language as the user's question.
- Ensure the response maintains continuity with the conversation history.
- Organize answer in sections focusing on one main point or aspect of the
  answer.
- Use clear and descriptive section titles that reflect the content.
- List up to 5 most important reference sources at the end under "References".
  Clearly indicate whether each source is from Knowledge Graph (KG) or Vector
  Data (DC), and include the file path or source id if available.
- Prefer direct KG/DC evidence over broad supporting triples.
- If grounding.status is "empty" or "supporting_only", say the requested
  academic data was not found in the YUNESA academic knowledge graph.
- Do not answer from model memory, web knowledge, or external academic databases.
- Cite source indices returned by the knowledge base when making factual claims.
- If you do not know the answer, say so. Do not make anything up.
- Do not include information not provided by the Data Sources.
"""

MIX_CONTEXT_TEMPLATE = MIX_RAG_RESPONSE_TEMPLATE


def _empty_section() -> str:
    return "No relevant evidence found."


def format_grounding(grounding: dict[str, Any] | None) -> str:
    grounding = grounding or {}
    return (
        f"status={grounding.get('status', 'unknown')} | "
        f"answerable={grounding.get('answerable', False)} | "
        f"direct={grounding.get('direct_evidence_count', 0)} | "
        f"supporting={grounding.get('supporting_evidence_count', 0)}"
    )


def build_mix_context_text(
    *,
    kg_lines: list[str],
    vector_lines: list[str],
    grounding: dict[str, Any] | None,
    history: str = "",
    response_type: str = "Multiple Paragraphs",
) -> str:
    """Render an AcademicRAG-style mix response prompt/context.

    This mirrors upstream AcademicRAG's `mix_rag_response` structure. YUNESA
    still lets the Yuxi agent runtime perform the final generation, so this text
    is returned as the tool's evidence package instead of being used as a direct
    system prompt inside this module.
    """
    kg_context = "\n".join(kg_lines).strip() if kg_lines else _empty_section()
    vector_context = "\n".join(vector_lines).strip() if vector_lines else _empty_section()
    return MIX_RAG_RESPONSE_TEMPLATE.format(
        history=history or "",
        grounding=format_grounding(grounding),
        kg_context=kg_context,
        vector_context=vector_context,
        response_type=response_type,
    )


def build_academicrag_context_text(
    *,
    mode: str,
    kg_lines: list[str],
    vector_lines: list[str],
    grounding: dict[str, Any] | None,
    history: str = "",
    response_type: str = "Multiple Paragraphs",
) -> str:
    """Render the prompt/context variant matching AcademicRAG query mode."""
    normalized_mode = str(mode or "").strip().lower()
    kg_context = "\n".join(kg_lines).strip() if kg_lines else _empty_section()
    vector_context = "\n".join(vector_lines).strip() if vector_lines else _empty_section()
    formatted_grounding = format_grounding(grounding)

    if normalized_mode in {"naive", "vector", "keyword"}:
        return NAIVE_RAG_RESPONSE_TEMPLATE.format(
            history=history or "",
            grounding=formatted_grounding,
            content_data=vector_context,
            response_type=response_type,
        )
    if normalized_mode in {"subgraph", "global", "hybrid", "graph"}:
        return RAG_RESPONSE_TEMPLATE.format(
            history=history or "",
            grounding=formatted_grounding,
            context_data=kg_context,
            response_type=response_type,
        )
    return MIX_RAG_RESPONSE_TEMPLATE.format(
        history=history or "",
        grounding=formatted_grounding,
        kg_context=kg_context,
        vector_context=vector_context,
        response_type=response_type,
    )
