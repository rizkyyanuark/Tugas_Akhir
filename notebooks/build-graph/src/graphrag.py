"""
graphrag.py — UNESA Academic KG GraphRAG Engine
=================================================
5-Step Query Pipeline:
  1. Question Understanding  — language detect + GLiNER NER on question
  2. Vector Retrieval        — LanceDB nearest-chunk search
  3. Graph Expansion         — entity matching + neighbor traversal + PageRank
  4. Context Assembly        — collect chunk texts + paper metadata + lecturer info
  5. LLM Generation          — Groq API call with assembled context → cited answer
"""

import os
import logging
import json
import re
import requests
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

import networkx as nx

logger = logging.getLogger(__name__)


class GraphRAG:
    """
    Graph-enhanced Retrieval-Augmented Generation for UNESA Academic KG.
    """

    def __init__(self, graph: nx.MultiDiGraph, embedding_engine, nlp_parser=None,
                 llm_model: str = "llama-3.3-70b-versatile",
                 groq_api_key: str = None):
        self.G = graph
        self.embedding_engine = embedding_engine
        self.nlp_parser = nlp_parser
        self.llm_model = llm_model
        self.groq_api_key = groq_api_key or os.environ.get("GROQ_API_KEY", "")

    # ──────────────────────────────────────────────────────────────
    # Step 1: Question Understanding
    # ──────────────────────────────────────────────────────────────

    def _understand_question(self, question: str) -> Dict[str, Any]:
        """
        Analyzes the question: extracts entities and detects query type.
        """
        understanding = {
            "original": question,
            "entities": [],
            "query_type": "general",
        }

        # Extract entities using GLiNER if available
        if self.nlp_parser:
            try:
                _, entities, _ = self.nlp_parser.parse_document(question, "")
                understanding["entities"] = [e["text"] for e in entities]
            except Exception as e:
                logger.debug(f"NER on question failed: {e}")

        # Detect query type heuristically
        q_lower = question.lower()
        if any(w in q_lower for w in ["siapa", "who", "dosen", "lecturer", "peneliti"]):
            understanding["query_type"] = "entity_centric"
        elif any(w in q_lower for w in ["topik", "topic", "tentang", "about", "bidang"]):
            understanding["query_type"] = "topic_centric"
        elif any(w in q_lower for w in ["hubungan", "relasi", "relation", "between", "antara"]):
            understanding["query_type"] = "cross_domain"
        elif any(w in q_lower for w in ["tren", "trend", "tahun", "year", "kapan"]):
            understanding["query_type"] = "temporal"
        elif any(w in q_lower for w in ["kolaborasi", "collaborat", "bersama", "together"]):
            understanding["query_type"] = "collaborative"

        logger.info(f"Question understood: type={understanding['query_type']}, entities={understanding['entities']}")
        return understanding

    # ──────────────────────────────────────────────────────────────
    # Step 2: Vector Retrieval
    # ──────────────────────────────────────────────────────────────

    def _vector_retrieval(self, question: str, top_k: int = 5) -> List[Dict]:
        """
        Search for the most relevant chunks using LanceDB vector search.
        """
        results = self.embedding_engine.search_chunks(question, top_k=top_k)
        logger.info(f"Vector retrieval: {len(results)} chunks found.")
        return results

    # ──────────────────────────────────────────────────────────────
    # Step 3: Graph Expansion
    # ──────────────────────────────────────────────────────────────

    def _graph_expansion(self, anchor_chunks: List[Dict], question_entities: List[str],
                         max_hops: int = 2) -> Dict[str, Any]:
        """
        Starting from anchor chunks, traverse the graph to collect
        related entities, papers, lecturers, and topics.
        """
        expanded = {
            "papers": {},
            "lecturers": {},
            "topics": set(),
            "entities": set(),
            "chunks": [],
        }

        visited = set()

        # Start from anchor chunks
        for chunk_result in anchor_chunks:
            chunk_iri = chunk_result["chunk_iri"]
            paper_id = chunk_result["paper_id"]
            expanded["chunks"].append(chunk_result)

            # Find the paper node
            paper_iri = f"unesa:paper/{paper_id}"
            if self.G.has_node(paper_iri):
                pdata = self.G.nodes[paper_iri]
                expanded["papers"][paper_iri] = {
                    "title": pdata.get("title", ""),
                    "year": pdata.get("year", ""),
                    "doi": pdata.get("doi", ""),
                }

            # BFS expansion from chunk
            queue = [(chunk_iri, 0)]
            while queue:
                current, depth = queue.pop(0)
                if current in visited or depth > max_hops:
                    continue
                visited.add(current)

                for neighbor in self.G.predecessors(current):
                    ndata = self.G.nodes.get(neighbor, {})
                    nt = ndata.get("node_type", "")
                    if nt == "ENTITY":
                        expanded["entities"].add(ndata.get("label", neighbor))
                    if depth < max_hops:
                        queue.append((neighbor, depth + 1))

                for neighbor in self.G.successors(current):
                    ndata = self.G.nodes.get(neighbor, {})
                    nt = ndata.get("node_type", "")
                    if nt == "TOPIC":
                        expanded["topics"].add(ndata.get("prefLabel", neighbor))
                    elif nt == "PAPER":
                        expanded["papers"][neighbor] = {
                            "title": ndata.get("title", ""),
                            "year": ndata.get("year", ""),
                            "doi": ndata.get("doi", ""),
                        }
                    if depth < max_hops:
                        queue.append((neighbor, depth + 1))

        # Also match question entities directly
        for ent_text in question_entities:
            ent_iri = f"unesa:entity/{self._slugify(ent_text)}"
            if self.G.has_node(ent_iri):
                expanded["entities"].add(ent_text)
                # Follow MAPS_TO edges to topics
                for _, target, edata in self.G.edges(ent_iri, data=True):
                    if edata.get("edge_type") == "MAPS_TO":
                        tdata = self.G.nodes.get(target, {})
                        expanded["topics"].add(tdata.get("prefLabel", target))

        # Find lecturers who authored the found papers
        for paper_iri in list(expanded["papers"].keys()):
            for pred in self.G.predecessors(paper_iri):
                edata_list = self.G.get_edge_data(pred, paper_iri)
                if edata_list:
                    for key, ed in edata_list.items():
                        if ed.get("edge_type") == "AUTHORED":
                            ndata = self.G.nodes.get(pred, {})
                            if ndata.get("node_type") == "LECTURER":
                                expanded["lecturers"][pred] = {
                                    "name": ndata.get("name", ndata.get("nama_norm", "")),
                                    "prodi": ndata.get("prodi", ""),
                                }

        expanded["topics"] = list(expanded["topics"])
        expanded["entities"] = list(expanded["entities"])

        logger.info(f"Graph expansion: {len(expanded['papers'])} papers, "
                    f"{len(expanded['lecturers'])} lecturers, "
                    f"{len(expanded['topics'])} topics, "
                    f"{len(expanded['entities'])} entities")
        return expanded

    # ──────────────────────────────────────────────────────────────
    # Step 4: Context Assembly
    # ──────────────────────────────────────────────────────────────

    def _assemble_context(self, expanded: Dict[str, Any]) -> str:
        """
        Assembles retrieved information into a structured context string
        for the LLM prompt.
        """
        sections = []

        # Papers
        if expanded["papers"]:
            sections.append("=== Relevant Papers ===")
            for iri, pdata in expanded["papers"].items():
                sections.append(f"- [{pdata['year']}] {pdata['title']} (DOI: {pdata['doi']})")

        # Lecturers
        if expanded["lecturers"]:
            sections.append("\n=== Related Lecturers ===")
            for iri, ldata in expanded["lecturers"].items():
                sections.append(f"- {ldata['name']} ({ldata['prodi']})")

        # Topics
        if expanded["topics"]:
            sections.append(f"\n=== Related Topics ===")
            sections.append(f"- {', '.join(expanded['topics'])}")

        # Chunk texts
        if expanded["chunks"]:
            sections.append("\n=== Retrieved Text Excerpts ===")
            for chunk in expanded["chunks"][:5]:
                sections.append(f"- {chunk['text']}")

        # Entities
        if expanded["entities"]:
            sections.append(f"\n=== Detected Entities ===")
            sections.append(f"- {', '.join(expanded['entities'][:15])}")

        return "\n".join(sections)

    # ──────────────────────────────────────────────────────────────
    # Step 5: LLM Generation
    # ──────────────────────────────────────────────────────────────

    def _generate_answer(self, question: str, context: str) -> str:
        """
        Calls Groq API with the assembled context to generate an answer.
        """
        if not self.groq_api_key:
            logger.warning("No GROQ_API_KEY set. Returning raw context.")
            return f"[No LLM configured]\n\nContext:\n{context}"

        system_prompt = (
            "You are a research assistant for UNESA (Universitas Negeri Surabaya) academic knowledge graph. "
            "Answer the question based ONLY on the provided context. "
            "Cite specific papers and lecturers when possible. "
            "If the context doesn't contain enough information, say so honestly. "
            "Respond in the same language as the question."
        )

        user_prompt = f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"

        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 500,
        }

        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload, headers=headers, timeout=30,
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"].strip()
            return answer
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return f"[LLM Error: {e}]\n\nContext:\n{context}"

    # ──────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────

    def query(self, question: str, top_k: int = 5, max_hops: int = 2) -> Dict[str, Any]:
        """
        Full GraphRAG query pipeline.

        Returns:
            {
                "question": str,
                "answer": str,
                "context": str,
                "sources": { papers, lecturers, topics, entities },
                "query_type": str,
            }
        """
        logger.info(f"GraphRAG Query: '{question}'")

        # Step 1
        understanding = self._understand_question(question)

        # Step 2
        anchor_chunks = self._vector_retrieval(question, top_k=top_k)

        # Step 3
        expanded = self._graph_expansion(anchor_chunks, understanding["entities"], max_hops=max_hops)

        # Step 4
        context = self._assemble_context(expanded)

        # Step 5
        answer = self._generate_answer(question, context)

        return {
            "question": question,
            "answer": answer,
            "context": context,
            "sources": {
                "papers": expanded["papers"],
                "lecturers": expanded["lecturers"],
                "topics": expanded["topics"],
                "entities": expanded["entities"],
            },
            "query_type": understanding["query_type"],
        }

    def query_without_llm(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        """
        Runs Steps 1-4 without LLM call. Useful for testing retrieval quality.
        """
        understanding = self._understand_question(question)
        anchor_chunks = self._vector_retrieval(question, top_k=top_k)
        expanded = self._graph_expansion(anchor_chunks, understanding["entities"])
        context = self._assemble_context(expanded)

        return {
            "question": question,
            "context": context,
            "sources": {
                "papers": expanded["papers"],
                "lecturers": expanded["lecturers"],
                "topics": expanded["topics"],
                "entities": expanded["entities"],
            },
            "query_type": understanding["query_type"],
        }

    @staticmethod
    def _slugify(text: str) -> str:
        slug = text.lower().strip()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'[\s-]+', '_', slug)
        return slug


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("GraphRAG module loaded. Use within kg_pipeline.ipynb for full execution.")
