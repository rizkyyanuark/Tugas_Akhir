"""
KG Pipeline Service: Top-Level Orchestrator
=============================================
Production-ready orchestrator for the full KG construction pipeline.
Same pattern as src/etl/services/unesa_papers.py:
  - Pure Python, no Airflow dependency
  - Callable from notebooks, Airflow DAGs, or CLI
  - Step-by-step with clear logging and statistics

Usage from notebook:
    from src.kg.services.kg_pipeline import KGPipeline
    pipeline = KGPipeline(test_mode=True)
    result = pipeline.run()

Usage from Airflow DAG:
    from src.kg.services.kg_pipeline import run_full_pipeline
    run_full_pipeline()
"""

import time
import logging
import sys
from datetime import datetime
from typing import Dict, Optional, Any

import pandas as pd

from ..config import (
    SUPABASE_URL, SUPABASE_KEY,
    MAX_PAPERS, LLM_BATCH_SIZE, LOG_DIR,
)

logger = logging.getLogger(__name__)


class KGPipeline:
    """Full KG construction pipeline orchestrator.

    Orchestrates the complete flow:
      1. Source Loading (Supabase → DataFrames)
      2. Backbone Construction (structural nodes/edges)
      3. NER Extraction (GLiNER + title regex + CSV)
      4. Entity Resolution (abbreviation + LLM synonym)
      5. LLM Curation (validation + enrichment)
      6. Database Ingestion (Neo4j + Weaviate)

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
    ):
        self.test_mode = test_mode
        self.max_papers = 5 if test_mode else (max_papers or MAX_PAPERS)
        self.clear_db = clear_db
        self.batch_size = batch_size

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

        # Timing
        self._timers = {}

        self._setup_logging()

    def _setup_logging(self):
        """Configure file + console logging for the pipeline."""
        kg_logger = logging.getLogger("src.kg")
        if not kg_logger.handlers:
            kg_logger.setLevel(logging.DEBUG)

            # File handler
            log_file = LOG_DIR / f'kg_pipeline_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
            fh = logging.FileHandler(str(log_file), encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            kg_logger.addHandler(fh)

            # Console handler
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(logging.INFO)
            ch.setFormatter(logging.Formatter("%(levelname)-8s | %(message)s"))
            kg_logger.addHandler(ch)

            # Suppress noisy libs
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            logging.getLogger("neo4j").setLevel(logging.WARNING)

    def _start_step(self, name: str):
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

        # Import here to avoid circular deps and allow notebook override
        sys.path.insert(0, str(
            __import__("pathlib").Path(__file__).resolve().parent.parent.parent.parent
            / "notebooks" / "scraping"
        ))
        from scraping_modules.supabase_client import SupabaseClient

        sb = SupabaseClient()
        logger.info("Fetching data from Supabase tables: 'papers' and 'lecturers'...")

        res_papers = sb.client.table("papers").select("*").execute()
        res_dosen = sb.client.table("lecturers").select("*").execute()

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

        self.nodes, self.edges, self.paper_abstracts, self.paper_titles = build_backbone(
            df_papers, df_dosen, max_papers=self.max_papers
        )

        self._end_step("Step 2: Backbone Construction", {
            "Total nodes": len(self.nodes),
            "Total edges": len(self.edges),
        })

    # ══════════════════════════════════════════════════════════
    # Step 3: NER Extraction
    # ══════════════════════════════════════════════════════════
    def extract_entities(self):
        """Run GLiNER NER + title regex + CSV keyword extraction."""
        self._start_step("Step 3: NER Extraction")

        from ..ner_extractor import EntityStore, extract_entities_from_paper

        self.entity_store = EntityStore()
        self.chunk_vdb = []
        total = len(self.paper_abstracts)

        for i, (pid, abstract) in enumerate(self.paper_abstracts.items()):
            title = self.paper_titles.get(pid, "")

            # Prefer TLDR text (English, clean). Fallback to abstract.
            paper_node = self.nodes.get(pid, {})
            tldr_text = abstract  # Use abstract as TLDR source

            # Build chunk for Weaviate
            full_text = f"{title}. {tldr_text}"
            self.chunk_vdb.append({
                "title": title,
                "content": full_text,
                "year": paper_node.get("year", ""),
                "paperUrl": paper_node.get("url", ""),
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
        from ..llm_client import GroqClient

        llm_client = GroqClient()
        entity_texts = self.entity_store.get_all_texts()

        self.alias_map = build_alias_map(
            entity_texts=entity_texts,
            paper_abstracts=self.paper_abstracts,
            paper_titles=self.paper_titles,
            llm_client=llm_client,
            batch_size=self.batch_size,
        )

        merged_count = apply_resolution(self.extracted_entities, self.alias_map)

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
        from ..llm_client import GroqClient

        llm_client = GroqClient()

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
        )

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
        """Write all data to Neo4j and Weaviate."""
        self._start_step("Step 6: Database Ingestion")

        from ..neo4j_writer import Neo4jKGWriter
        from ..weaviate_writer import WeaviateKGWriter

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

        # ── Weaviate ──
        wv_writer = WeaviateKGWriter()
        try:
            wv_writer.ensure_collections(recreate=self.clear_db)
            wv_errors = wv_writer.ingest_all(
                entity_vdb=self.entity_vdb,
                relationship_vdb=self.relationship_vdb,
                keywords_vdb=self.keywords_vdb,
                chunk_vdb=self.chunk_vdb,
            )
        finally:
            wv_writer.close()

        self._end_step("Step 6: Database Ingestion", {
            "Neo4j node errors": node_stats["errors"],
            "Neo4j edge errors": edge_stats["errors"],
            "Neo4j edge skipped": edge_stats["skipped"],
            "COLLABORATES_WITH derived": collab_count,
            "Weaviate batch errors": sum(wv_errors.values()),
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
        logger.info(f"🚀 KG Pipeline starting ({mode} mode, max_papers={self.max_papers})")

        df_papers, df_dosen = self.load_sources()
        self.build_backbone(df_papers, df_dosen)
        self.extract_entities()
        self.resolve_entities()
        self.curate_entities()
        self.ingest_databases()

        elapsed = time.time() - t0
        summary = {
            "mode": mode,
            "max_papers": self.max_papers,
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

    parser = argparse.ArgumentParser(description="UNESA KG Construction Pipeline")
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
