"""
Query Orchestrator: Main GraphRAG Query Pipeline
==================================================
Orchestrates the full AcademicRAG retrieval-generation pipeline:
  ① Keyword Extraction → ② Local Retrieval → ③ Global Retrieval
  → ④ Context Fusion → ⑤ LLM Generation

Supports 4 modes: local, global, hybrid, mix (KG + Vector)
"""

import time
import logging
from typing import Dict, Any, Optional

from .llm_adapter import LLMAdapter
from .keyword_extractor import extract_keywords_with_clues
from .local_retriever import subgraph_retrieve
from .global_retriever import global_edge_retrieve
from .context_builder import fuse_contexts, build_entities_context, build_relationships_context, build_text_units_context
from .prompts import RAG_RESPONSE, MIX_RAG_RESPONSE
from .storage.neo4j_adapter import Neo4jGraphStorage
from .storage.weaviate_adapter import WeaviateVectorStorage
from .storage.kv_adapter import JsonKVStore

logger = logging.getLogger(__name__)


class GraphRAGQuery:
    """Main query orchestrator for the AcademicRAG pipeline.

    Usage:
        gq = GraphRAGQuery()
        result = await gq.query("Siapa dosen yang meneliti deep learning?")
        print(result["response"])
        gq.close()
    """

    def __init__(self):
        self.neo4j = Neo4jGraphStorage()
        self.weaviate = WeaviateVectorStorage()
        self.chunks_db = JsonKVStore()
        self.llm = LLMAdapter()
        logger.info("✅ GraphRAGQuery initialised (all adapters connected)")

    def close(self):
        """Close all connections."""
        self.neo4j.close()
        self.weaviate.close()
        logger.info("GraphRAGQuery connections closed.")

    async def query(
        self,
        query_text: str,
        mode: str = "hybrid",
    ) -> Dict[str, Any]:
        """Execute a full GraphRAG query.

        Args:
            query_text: User's question in natural language.
            mode: Retrieval mode — 'local', 'global', 'hybrid', 'mix'.

        Returns:
            Dict with response, metadata, and debug info.
        """
        t0 = time.time()
        logger.info(f"═══ GraphRAG Query (mode={mode}): \"{query_text[:80]}...\" ═══")

        # ① Keyword Extraction
        hl_keywords, ll_keywords = await extract_keywords_with_clues(
            query=query_text,
            weaviate_storage=self.weaviate,
            llm=self.llm,
        )

        # ② + ③ Retrieval (based on mode)
        local_context = {"entities": [], "relationships": [], "text_units": []}
        global_context = {"entities": [], "relationships": [], "text_units": []}

        if mode in ("local", "hybrid"):
            local_context = await subgraph_retrieve(
                ll_keywords=ll_keywords,
                neo4j=self.neo4j,
                weaviate=self.weaviate,
                chunks_db=self.chunks_db,
            )

        if mode in ("global", "hybrid"):
            global_context = await global_edge_retrieve(
                hl_keywords=hl_keywords,
                neo4j=self.neo4j,
                weaviate=self.weaviate,
                chunks_db=self.chunks_db,
            )

        # ④ Context Fusion
        fused = fuse_contexts(local_context, global_context)

        # ⑤ LLM Generation
        if mode == "mix":
            response = await self._mix_kg_vector_query(query_text, fused)
        else:
            prompt = RAG_RESPONSE.format(
                entities_context=fused["entities_context"],
                relationships_context=fused["relationships_context"],
                text_units_context=fused["text_units_context"],
                query=query_text,
            )
            response = await self.llm.chat(user_prompt=prompt)

        elapsed = time.time() - t0
        logger.info(f"═══ Query completed in {elapsed:.2f}s ═══")

        return {
            "response": response,
            "metadata": {
                "mode": mode,
                "query": query_text,
                "hl_keywords": hl_keywords,
                "ll_keywords": ll_keywords,
                "latency_s": round(elapsed, 3),
                "llm_stats": self.llm.stats,
            },
            "debug": {
                "local_entities": len(local_context.get("entities", [])),
                "global_entities": len(global_context.get("entities", [])),
                "local_relationships": len(local_context.get("relationships", [])),
                "global_relationships": len(global_context.get("relationships", [])),
                "text_units": len(
                    local_context.get("text_units", []) +
                    global_context.get("text_units", [])
                ),
                "fused_context": fused,
            },
        }

    async def _mix_kg_vector_query(
        self,
        query_text: str,
        kg_context: Dict[str, str],
    ) -> str:
        """Hybrid KG + Vector RAG query.

        Retrieves additional context from PaperChunk VDB
        and merges with structured KG context.
        """
        # Additional vector search on PaperChunk
        vector_results = self.weaviate.query_chunks(query_text, top_k=5)
        vector_context_parts = []
        for i, r in enumerate(vector_results):
            title = r.get("title", "")
            content = r.get("content", "")[:500]
            authors = r.get("authors", "")
            url = r.get("paperUrl", "")
            vector_context_parts.append(
                f"[{i+1}] {title} (oleh: {authors})\n{content}\nURL: {url}"
            )
        vector_context = "\n\n".join(vector_context_parts) or "Tidak ada hasil vector search."

        prompt = MIX_RAG_RESPONSE.format(
            entities_context=kg_context["entities_context"],
            relationships_context=kg_context["relationships_context"],
            vector_context=vector_context,
            query=query_text,
        )

        return await self.llm.chat(user_prompt=prompt)
