"""
embedding.py — UNESA Academic KG Embedding Layer
==================================================
Handles two types of embeddings:
1. Chunk Embeddings  — sentence-transformers → LanceDB
2. Entity Embeddings — gensim Word2Vec trained on co-occurrence sequences

Provides vector search interface for GraphRAG retrieval.
"""

import os
import logging
import json
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

import numpy as np
import networkx as nx

logger = logging.getLogger(__name__)


class EmbeddingEngine:
    """
    Manages chunk embeddings (sentence-transformers → LanceDB)
    and entity embeddings (Word2Vec on co-occurrence walks).
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", lancedb_path: str = "./lancedb_store"):
        self.model_name = model_name
        self.lancedb_path = lancedb_path
        self.encoder = None
        self.db = None
        self.chunk_table = None
        self.w2v_model = None

    # ──────────────────────────────────────────────────────────────
    # Lazy initialization
    # ──────────────────────────────────────────────────────────────

    def _init_encoder(self):
        if self.encoder is None:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading SentenceTransformer: {self.model_name}")
            self.encoder = SentenceTransformer(self.model_name)

    def _init_lancedb(self):
        if self.db is None:
            try:
                import lancedb
                os.makedirs(self.lancedb_path, exist_ok=True)
                self.db = lancedb.connect(self.lancedb_path)
                logger.info(f"LanceDB connected at: {self.lancedb_path}")
            except ImportError:
                logger.error("lancedb not installed. Run: pip install lancedb")
                raise

    # ──────────────────────────────────────────────────────────────
    # 1. Chunk Embeddings
    # ──────────────────────────────────────────────────────────────

    def build_chunk_embeddings(self, graph: nx.MultiDiGraph) -> int:
        """
        Extracts all CHUNK nodes from graph, encodes their text,
        and stores vectors in LanceDB table 'chunks'.

        Returns the number of chunks embedded.
        """
        self._init_encoder()
        self._init_lancedb()

        # Collect chunks
        chunks_data = []
        for node, data in graph.nodes(data=True):
            if data.get("node_type") == "CHUNK":
                chunks_data.append({
                    "chunk_iri": node,
                    "text": data.get("text", ""),
                    "paper_id": data.get("paper_id", ""),
                    "chunk_index": data.get("chunk_index", 0),
                })

        if not chunks_data:
            logger.warning("No CHUNK nodes found in graph. Skipping chunk embeddings.")
            return 0

        # Encode
        texts = [c["text"] for c in chunks_data]
        logger.info(f"Encoding {len(texts)} chunks with {self.model_name}...")
        vectors = self.encoder.encode(texts, show_progress_bar=True, convert_to_numpy=True)

        # Build records for LanceDB
        records = []
        for i, chunk in enumerate(chunks_data):
            records.append({
                "chunk_iri": chunk["chunk_iri"],
                "text": chunk["text"],
                "paper_id": chunk["paper_id"],
                "chunk_index": chunk["chunk_index"],
                "vector": vectors[i].tolist(),
            })

        # Upsert into LanceDB
        import pyarrow as pa
        table_name = "chunks"

        if table_name in self.db.table_names()  if hasattr(self.db, 'table_names') else table_name in self.db.list_tables():
            self.db.drop_table(table_name)

        self.chunk_table = self.db.create_table(table_name, records)
        logger.info(f"LanceDB: stored {len(records)} chunk embeddings in '{table_name}'.")

        # Also store vectors back on graph nodes
        for i, chunk in enumerate(chunks_data):
            graph.nodes[chunk["chunk_iri"]]["embedding"] = vectors[i].tolist()

        return len(records)

    def search_chunks(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Vector search over chunk embeddings in LanceDB.
        Returns top_k nearest chunks with similarity scores.
        """
        self._init_encoder()
        self._init_lancedb()

        if self.chunk_table is None:
            if "chunks" in self.db.table_names():
                self.chunk_table = self.db.open_table("chunks")
            else:
                logger.warning("No chunks table in LanceDB. Build embeddings first.")
                return []

        query_vec = self.encoder.encode(query, convert_to_numpy=True).tolist()
        results = self.chunk_table.search(query_vec).limit(top_k).to_list()

        return [
            {
                "chunk_iri": r["chunk_iri"],
                "text": r["text"],
                "paper_id": r["paper_id"],
                "score": r.get("_distance", 0),
            }
            for r in results
        ]

    # ──────────────────────────────────────────────────────────────
    # 2. Entity Embeddings (Word2Vec)
    # ──────────────────────────────────────────────────────────────

    def build_entity_embeddings(self, graph: nx.MultiDiGraph, vector_size: int = 64,
                                 window: int = 3, min_count: int = 1, epochs: int = 50) -> int:
        """
        Trains Word2Vec on entity co-occurrence sequences derived from the graph.
        Walks: for each CHUNK, collect all entities MENTIONED_IN it → co-occurrence sentence.

        Returns the number of entities with embeddings.
        """
        from gensim.models import Word2Vec

        # Build co-occurrence sentences: for each chunk, list entities mentioned in it
        chunk_entities = defaultdict(list)
        for u, v, data in graph.edges(data=True):
            if data.get("edge_type") == "MENTIONED_IN":
                entity_iri = u
                chunk_iri = v
                entity_label = graph.nodes[entity_iri].get("label", entity_iri)
                chunk_entities[chunk_iri].append(entity_label)

        sentences = [ents for ents in chunk_entities.values() if len(ents) >= 2]

        if not sentences:
            logger.warning("No co-occurrence sentences found. Skipping entity embeddings.")
            return 0

        logger.info(f"Training Word2Vec on {len(sentences)} co-occurrence sentences...")
        self.w2v_model = Word2Vec(
            sentences=sentences,
            vector_size=vector_size,
            window=window,
            min_count=min_count,
            sg=1,  # Skip-gram
            epochs=epochs,
            seed=42,
        )

        # Store embeddings back on ENTITY nodes
        count = 0
        for node, data in graph.nodes(data=True):
            if data.get("node_type") == "ENTITY":
                label = data.get("label", "")
                if label in self.w2v_model.wv:
                    graph.nodes[node]["w2v_embedding"] = self.w2v_model.wv[label].tolist()
                    count += 1

        logger.info(f"Entity embeddings: {count}/{len([n for n, d in graph.nodes(data=True) if d.get('node_type') == 'ENTITY'])} entities embedded.")
        return count

    def find_similar_entities(self, entity_label: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """
        Returns top_k most similar entities by Word2Vec cosine similarity.
        """
        if self.w2v_model is None or entity_label not in self.w2v_model.wv:
            return []
        return self.w2v_model.wv.most_similar(entity_label, topn=top_k)

    def save_w2v(self, path: str):
        """Save Word2Vec model to disk."""
        if self.w2v_model:
            self.w2v_model.save(path)
            logger.info(f"Word2Vec saved to {path}")

    def load_w2v(self, path: str):
        """Load Word2Vec model from disk."""
        from gensim.models import Word2Vec
        self.w2v_model = Word2Vec.load(path)
        logger.info(f"Word2Vec loaded from {path}")

    # ──────────────────────────────────────────────────────────────
    # Summary
    # ──────────────────────────────────────────────────────────────

    def get_summary(self, graph: nx.MultiDiGraph) -> str:
        """Returns a summary of the embedding state."""
        chunk_count = sum(1 for _, d in graph.nodes(data=True)
                         if d.get("node_type") == "CHUNK" and "embedding" in d)
        entity_count = sum(1 for _, d in graph.nodes(data=True)
                          if d.get("node_type") == "ENTITY" and "w2v_embedding" in d)
        lines = [
            "+--------------------------------------------------+",
            "|          Embedding Layer Summary                  |",
            "+--------------------------------------------------+",
            f"|  Chunk embeddings (LanceDB) : {chunk_count:<19}|",
            f"|  Entity embeddings (W2V)    : {entity_count:<19}|",
            f"|  LanceDB path               : {self.lancedb_path:<19}|",
            "+--------------------------------------------------+",
        ]
        return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Quick smoke test
    G = nx.MultiDiGraph()
    G.add_node("c1", node_type="CHUNK", text="Deep learning for image classification", paper_id="p1", chunk_index=0)
    G.add_node("c2", node_type="CHUNK", text="Vision Transformer achieves state of the art", paper_id="p1", chunk_index=1)
    G.add_node("e1", node_type="ENTITY", label="deep learning")
    G.add_node("e2", node_type="ENTITY", label="vision transformer")
    G.add_node("e3", node_type="ENTITY", label="image classification")
    G.add_edge("e1", "c1", edge_type="MENTIONED_IN")
    G.add_edge("e3", "c1", edge_type="MENTIONED_IN")
    G.add_edge("e2", "c2", edge_type="MENTIONED_IN")

    engine = EmbeddingEngine(lancedb_path="./test_lancedb")
    n_chunks = engine.build_chunk_embeddings(G)
    n_entities = engine.build_entity_embeddings(G)
    print(engine.get_summary(G))

    results = engine.search_chunks("transformer model", top_k=2)
    print("\nSearch results for 'transformer model':")
    for r in results:
        print(f"  {r['text'][:50]}... (score: {r['score']:.4f})")
