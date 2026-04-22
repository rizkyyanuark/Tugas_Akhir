"""
KG Pipeline Service: Top-Level Orchestrator
=============================================
Production-ready orchestrator for the full KG construction pipeline.
  - Pure Python, no Airflow dependency
  - Triggered via POST /api/graph/kg/build (superadmin only)
  - Runs as a background task via the Tasker service
  - Step-by-step with clear logging and statistics

Usage (backend API — preferred):
    POST /api/graph/kg/build  {"test_mode": true}

Usage (programmatic):
    from yunesa.knowledge.kg.services.kg_pipeline import KGPipeline
    pipeline = KGPipeline(test_mode=True)
    result = pipeline.run()
"""

import time
import json
import logging
import sys
from datetime import datetime
from typing import Dict, Optional, Any

import pandas as pd

from ..config import (
    SUPABASE_URL, SUPABASE_KEY,
    MAX_PAPERS, LLM_BATCH_SIZE, KG_ARTIFACTS_DIR,
)

from yunesa.utils.logging_config import logger


class KGPipeline:
    """Full KG construction pipeline orchestrator.

    Orchestrates the complete flow:
      1. Source Loading (Supabase → DataFrames)
      2. Backbone Construction (structural nodes/edges)
      3. NER Extraction (GLiNER + title regex + CSV)
      4. Entity Resolution (abbreviation + LLM synonym)
      5. LLM Curation (validation + enrichment)
      6. Database Ingestion (Neo4j + Milvus)

    Args:
        test_mode: If True, limits to 5 papers for quick iteration.
        max_papers: Maximum papers to process (ignored if test_mode).
        clear_db: If True, clears Neo4j before ingestion (dev only).
        batch_size: LLM batch size for entity resolution.
    """

    def __init__(
        self,
        test_mode: bool = False,
        max_papers: Optional[int] = None,
        clear_db: bool = True,
        batch_size: int = LLM_BATCH_SIZE,
        llm_config: Optional[Dict[str, str]] = None,
    ):
        self.test_mode = test_mode
        self.max_papers = 5 if test_mode else (max_papers or MAX_PAPERS)
        self.clear_db = clear_db
        self.batch_size = batch_size
        self.llm_config = llm_config or {}
        self.progress_callback = None

        # Pipeline state (populated during run)
        self.nodes = {}
        self.edges = []
        self.paper_abstracts = {}
        self.paper_titles = {}
        self.entity_store = None
        self.extracted_entities = {}
        self.alias_map = {}
        self.entity_node_map = {}
        self.chunk_vdb = []
        self.entity_vdb = []
        self.relationship_vdb = []
        self.keywords_vdb = []
        self.text_chunks_db = {}

        # Timing
        self._timers = {}

    def _create_llm_client(self):
        """Create a runtime-configured LLM client for KG curation steps."""
        from ..llm_client import GroqClient

        return GroqClient(
            api_key=self.llm_config.get("api_key"),
            model=self.llm_config.get("model"),
            base_url=self.llm_config.get("base_url"),
        )

    def _report_progress(self, data: dict):
        """Invoke progress callback if registered."""
        if self.progress_callback:
            try:
                self.progress_callback(data)
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")

    def _start_step(self, name: str, percentage: int = None):
        if self.progress_callback:
            self.progress_callback(
                {"step": name, "status": "started", "percentage": percentage or 0})
        self._timers[name] = time.time()
        logger.info(f"{'='*60}")
        logger.info(f"START: {name}")
        logger.info(f"{'='*60}")

    def _end_step(self, name: str, stats: Optional[Dict] = None):
        elapsed = time.time() - self._timers.get(name, time.time())
        logger.info(f"{'─'*60}")
        if stats:
            for k, v in stats.items():
                logger.info(f"  {k}: {v}")
        logger.info(f"✅ {name} completed in {elapsed:.1f}s")
        logger.info(f"{'='*60}\n")

    # ══════════════════════════════════════════════════════════
    # Step 1: Source Loading
    # ══════════════════════════════════════════════════════════
    def load_sources(self) -> tuple:
        """Fetch papers and lecturers from Supabase.

        Returns:
            Tuple of (df_papers, df_dosen).
        """
        self._start_step("Step 1: Source Loading")

        from supabase import create_client
        from ..config import SUPABASE_URL, SUPABASE_KEY

        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY must be properly configured.")

        # Create native Supabase client inline (no need for scraping notebooks hack)
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)

        logger.info(
            "Fetching data from Supabase tables: 'papers' and 'lecturers'...")

        res_papers = sb.table("papers").select("*").execute()
        res_dosen = sb.table("lecturers").select("*").execute()

        df_papers = pd.DataFrame(res_papers.data).fillna("")
        df_dosen = pd.DataFrame(res_dosen.data).fillna("")

        # Column mapping: Supabase snake_case → Notebook Title Case
        df_papers = df_papers.rename(columns={
            "title": "Title",
            "abstract": "Abstract",
            "year": "Year",
            "authors": "Authors",
            "author_ids": "Author IDs",
            "journal": "Journal",
            "keywords": "Keywords",
            "doi": "DOI",
            "link": "Link",
        })

        self._end_step("Step 1: Source Loading", {
            "Papers": len(df_papers),
            "Dosen": len(df_dosen),
        })

        return df_papers, df_dosen

    # ══════════════════════════════════════════════════════════
    # Step 2: Backbone Construction
    # ══════════════════════════════════════════════════════════
    def build_backbone(self, df_papers: pd.DataFrame, df_dosen: pd.DataFrame):
        """Build structural backbone nodes and edges."""
        self._start_step("Step 2: Backbone Construction")

        from ..graph_builder import build_backbone

        self.nodes, self.edges, self.paper_abstracts, self.paper_titles, self.text_chunks_db = build_backbone(
            df_papers, df_dosen, max_papers=self.max_papers
        )

        # Persist text_chunks_db to disk for GraphRAG retrieval
        chunks_path = KG_ARTIFACTS_DIR / "text_chunks.json"
        with open(chunks_path, "w", encoding="utf-8") as f:
            json.dump(self.text_chunks_db, f, ensure_ascii=False, indent=2)
        logger.info(
            f"  Saved text_chunks_db: {len(self.text_chunks_db)} chunks → {chunks_path}")

        self._end_step("Step 2: Backbone Construction", {
            "Total nodes": len(self.nodes),
            "Total edges": len(self.edges),
            "Text chunks": len(self.text_chunks_db),
        })

    # ══════════════════════════════════════════════════════════
    # Step 3: NER Extraction
    # ══════════════════════════════════════════════════════════
    def extract_entities(self):
        """Run GLiNER NER + title regex + CSV keyword extraction."""
        self._start_step("Step 3: NER Extraction", percentage=20)

        from ..ner_extractor import EntityStore, extract_entities_from_paper

        self.entity_store = EntityStore()
        self.chunk_vdb = []
        total = len(self.paper_abstracts)

        for i, (pid, abstract) in enumerate(self.paper_abstracts.items()):
            title = self.paper_titles.get(pid, "")

            # Prefer TLDR text (English, clean). Fallback to abstract.
            paper_node = self.nodes.get(pid, {})
            tldr_text = abstract  # Use abstract as TLDR source

            # Build chunk for Milvus VDB (including authors for pre-filtering)
            # Collect dosen names who WRITE this paper from edges
            paper_authors = [
                self.nodes[src]["name"]
                for src, tgt, rel, _ in self.edges
                if tgt == pid and rel == "WRITES" and src in self.nodes
            ]
            full_text = f"{title}. {tldr_text}"
            self.chunk_vdb.append({
                "title": title,
                "content": full_text,
                "year": paper_node.get("year", ""),
                "paperUrl": paper_node.get("url", ""),
                "authors": ", ".join(paper_authors),
            })

            # Get CSV keywords from paper node
            paper_kw = ""  # Keywords already processed in backbone as Keyword nodes

            # Extract entities
            self.entity_store, paper_lks = extract_entities_from_paper(
                title=title,
                text=tldr_text,
                csv_keywords=paper_kw,
                entity_store=self.entity_store,
            )
            self.extracted_entities[pid] = paper_lks

            if total > 0:
                # Step 3 occupies 20% -> 50% of the progress bar.
                # Keep running updates below 50 to reserve 50% for the completion event.
                ner_progress = 20 + int(((i + 1) / total) * 30)
                self._report_progress(
                    {
                        "step": "Step 3: NER Extraction",
                        "status": "running",
                        "percentage": min(49, ner_progress),
                        "message": f"NER extracting {i+1}/{total} papers",
                    }
                )

            if (i + 1) % 10 == 0 or (i + 1) == total:
                logger.info(
                    f"  Parsed {i+1}/{total} papers | unique entities: {len(self.entity_store)}"
                )

        self._end_step("Step 3: NER Extraction", self.entity_store.stats)

    # ══════════════════════════════════════════════════════════
    # Step 4: Entity Resolution
    # ══════════════════════════════════════════════════════════
    def resolve_entities(self):
        """Run 3-layer entity resolution."""
        self._start_step("Step 4: Entity Resolution")

        from ..entity_resolver import build_alias_map, apply_resolution

        llm_client = self._create_llm_client()
        entity_texts = self.entity_store.get_all_texts()

        self.alias_map = build_alias_map(
            entity_texts=entity_texts,
            paper_abstracts=self.paper_abstracts,
            paper_titles=self.paper_titles,
            llm_client=llm_client,
            batch_size=self.batch_size,
        )

        merged_count = apply_resolution(
            self.extracted_entities, self.alias_map)

        self._end_step("Step 4: Entity Resolution", {
            "Total alias mappings": len(self.alias_map),
            "Entity references merged": merged_count,
        })

    # ══════════════════════════════════════════════════════════
    # Step 5: LLM Curation
    # ══════════════════════════════════════════════════════════
    def curate_entities(self):
        """Run LLM curation for entity validation and enrichment."""
        self._start_step("Step 5: LLM Curation")

        from ..graph_builder import curate_entities_llm

        llm_client = self._create_llm_client()

        try:
            (
                self.nodes,
                self.edges,
                self.entity_vdb,
                self.relationship_vdb,
                self.keywords_vdb,
                self.entity_node_map,
            ) = curate_entities_llm(
                extracted_entities=self.extracted_entities,
                entity_store=self.entity_store,
                paper_abstracts=self.paper_abstracts,
                paper_titles=self.paper_titles,
                alias_map=self.alias_map,
                nodes=self.nodes,
                edges=self.edges,
                llm_client=llm_client,
                text_chunks_db=self.text_chunks_db,
            )
        except Exception as e:
            logger.error(f"Error during LLM Curation: {e}")
            self._report_progress(
                {"step": "Step 5: LLM Curation", "status": "error", "message": f"LLM Curation failed: {str(e)}"})
            raise RuntimeError(f"LLM Curation failed: {str(e)}") from e

        self._end_step("Step 5: LLM Curation", {
            "Curated entities": len(self.entity_vdb),
            "Curated relations": len(self.relationship_vdb),
            "Content keywords": len(self.keywords_vdb),
            "Total nodes now": len(self.nodes),
            "Total edges now": len(self.edges),
        })

    # ══════════════════════════════════════════════════════════
    # Step 6: Database Ingestion
    # ══════════════════════════════════════════════════════════
    def ingest_databases(self):
        """Write all data to Neo4j and Milvus."""
        self._start_step("Step 6: Database Ingestion")

        from ..neo4j_writer import Neo4jKGWriter
        from ..milvus_writer import MilvusKGWriter

        # ── Neo4j ──
        neo4j_writer = Neo4jKGWriter()
        collab_count = 0
        try:
            if self.clear_db:
                neo4j_writer.clear_database()
            neo4j_writer.ensure_constraints()
            node_stats = neo4j_writer.ingest_nodes(self.nodes)
            edge_stats = neo4j_writer.ingest_edges(self.edges, self.nodes)
            # Derive COLLABORATES_WITH from co-authorship
            collab_count = neo4j_writer.derive_collaborations()
            neo4j_writer.print_summary()
        finally:
            neo4j_writer.close()

        # ── Milvus ──
        mv_writer = MilvusKGWriter()
        try:
            mv_writer.ensure_collections(recreate=self.clear_db)
            mv_errors = mv_writer.ingest_all(
                entity_vdb=self.entity_vdb,
                relationship_vdb=self.relationship_vdb,
                keywords_vdb=self.keywords_vdb,
                chunk_vdb=self.chunk_vdb,
            )
        finally:
            mv_writer.close()

        self._end_step("Step 6: Database Ingestion", {
            "Neo4j node errors": node_stats["errors"],
            "Neo4j edge errors": edge_stats["errors"],
            "Neo4j edge skipped": edge_stats["skipped"],
            "COLLABORATES_WITH derived": collab_count,
            "Milvus batch errors": sum(mv_errors.values()),
        })

    # ══════════════════════════════════════════════════════════
    # Full Pipeline
    # ══════════════════════════════════════════════════════════
    def run(self) -> Dict[str, Any]:
        """Execute the full KG construction pipeline.

        Returns:
            Summary statistics dict.
        """
        t0 = time.time()
        mode = "TEST" if self.test_mode else "PRODUCTION"
        logger.info(
            f"🚀 KG Pipeline starting ({mode} mode, max_papers={self.max_papers})")

        try:
            df_papers, df_dosen = self.load_sources()
            self._report_progress({"step": "Step 1: Source Loading",
                                  "status": "completed", "percentage": 10, "message": "Sources loaded."})

            self.build_backbone(df_papers, df_dosen)
            self._report_progress({"step": "Step 2: Backbone Construction",
                                  "status": "completed", "percentage": 20, "message": "Backbone built."})

            self.extract_entities()
            self._report_progress({"step": "Step 3: NER Extraction", "status": "completed",
                                  "percentage": 50, "message": "NER extraction complete."})

            self.resolve_entities()
            self._report_progress({"step": "Step 4: Entity Resolution",
                                  "status": "completed", "percentage": 60, "message": "Entities resolved."})

            self.curate_entities()
            self._report_progress({"step": "Step 5: LLM Curation", "status": "completed",
                                  "percentage": 80, "message": "Entities curated."})

            self.ingest_databases()
            self._report_progress({"step": "Step 6: Database Ingestion", "status": "completed",
                                  "percentage": 100, "message": "Database ingestion complete."})
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            self._report_progress(
                {"step": "Pipeline", "status": "error", "message": str(e), "percentage": 100})
            raise

        elapsed = time.time() - t0
        summary = {
            "mode": mode,
            "max_papers": self.max_papers,
            "llm_provider": self.llm_config.get("provider", "unknown"),
            "llm_model": self.llm_config.get("model", "unknown"),
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "entities_extracted": len(self.entity_store) if self.entity_store else 0,
            "alias_mappings": len(self.alias_map),
            "curated_entities": len(self.entity_vdb),
            "curated_relations": len(self.relationship_vdb),
            "duration_seconds": round(elapsed, 1),
        }

        logger.info(f"\n{'='*60}")
        logger.info(f"🏁 FULL PIPELINE COMPLETE in {elapsed:.1f}s")
        for k, v in summary.items():
            logger.info(f"  {k}: {v}")
        logger.info(f"{'='*60}\n")

        return summary


# ══════════════════════════════════════════════════════════════
# Convenience functions (for Airflow DAG or CLI)
# ══════════════════════════════════════════════════════════════

def run_full_pipeline(test_mode: bool = False, **kwargs) -> Dict[str, Any]:
    """Run the full KG construction pipeline.

    Args:
        test_mode: If True, limits to 5 papers.
        **kwargs: Additional kwargs passed to KGPipeline.

    Returns:
        Summary statistics dict.
    """
    pipeline = KGPipeline(test_mode=test_mode, **kwargs)
    return pipeline.run()


if __name__ == "__main__":
    # ── CLI Entry Point ──
    import argparse

    parser = argparse.ArgumentParser(
        description="Yunesa KG Construction Pipeline")
    parser.add_argument(
        "--test", action="store_true", help="Run in test mode (5 papers only)"
    )
    parser.add_argument(
        "--full", action="store_true", help="Run full pipeline (production)"
    )
    parser.add_argument(
        "--no-clear", action="store_true", help="Don't clear Neo4j before ingestion"
    )

    args = parser.parse_args()

    # Default to test mode if neither --test nor --full provided
    is_test = True if args.test or not args.full else False

    try:
        run_full_pipeline(test_mode=is_test, clear_db=not args.no_clear)
    except Exception as exc:
        logger.critical(f"FATAL: Pipeline failed: {type(exc).__name__}: {exc}")
        sys.exit(1)
