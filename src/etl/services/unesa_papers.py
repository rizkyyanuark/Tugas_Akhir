"""
Services: UNESA Papers ETL Domain Logic
=======================================
Pure Python orchestrators decoupled from Airflow context.
This isolates testing and execution, keeping Airflow DAG files lightweight.
"""
import pandas as pd
import os
import logging
from pathlib import Path

from ..config import RAW_DATA_DIR, PROCESSED_DATA_DIR

# Hardcoded fallback until we formally inject this path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

logger = logging.getLogger(__name__)

def run_scholars_extraction(test_mode: bool = False) -> str:
    """Extract raw papers from Google Scholar via SerpAPI."""
    from ..extract.scholar import extract_scholar_papers

    dosen_csv = PROJECT_ROOT / "data" / "raw" / "dosen_infokom_final.csv"
    if not dosen_csv.exists():
        dosen_csv = PROJECT_ROOT / "notebooks" / "scraping" / "file_tabulars" / "dosen_infokom_final.csv"

    df_dosen = pd.read_csv(dosen_csv, dtype=str)
    targets = []
    for _, r in df_dosen.iterrows():
        sid = str(r.get("scholar_id", "")).strip().replace('.0', '')
        if sid not in ("", "nan", "NaN"):
            targets.append({"id": sid, "name": r["nama_dosen"]})

    if test_mode:
        logger.info("🧪 TEST MODE: Limiting to 1 author.")
        targets = targets[:1]
        
    df = extract_scholar_papers(targets, limit_per_author=5 if test_mode else 100)
    output_path = str(RAW_DATA_DIR / "scholar_papers_raw.csv")
    return output_path

def run_scopus_extraction() -> str:
    """Extract raw papers from Scopus via SciVal/Selenium."""
    from ..extract.scopus import extract_scopus_papers
    
    # Run the full scraper for all Scopus IDs
    papers = extract_scopus_papers()
    
    output_path = str(RAW_DATA_DIR / "dosen_papers_scopus_raw.csv")
    return output_path

def run_merge(scholar_path: str, scopus_path: str) -> str:
    """Merge and remove duplicate papers across isolated sources."""
    from ..transform.deduplicator import deduplicate_papers
    
    df_combined = pd.DataFrame()
    
    for path, source_name in [(scholar_path, "Scholar"), (scopus_path, "Scopus")]:
        if path and os.path.exists(path):
            try:
                df = pd.read_csv(path, dtype=str).fillna("")
                df_combined = pd.concat([df_combined, df], ignore_index=True)
            except pd.errors.EmptyDataError:
                logger.warning(f"⚠️ Warning: {source_name} file is empty ({path})")
        else:
            logger.warning(f"⚠️ Warning: {source_name} path is None or missing.")

    if df_combined.empty:
        logger.warning("⚠️ Both sources are empty. Returning empty output.")
        df_clean = pd.DataFrame()
    else:
        df_clean = deduplicate_papers(df_combined)

    output_path = str(PROCESSED_DATA_DIR / "unesa_papers_deduped.csv")
    df_clean.to_csv(output_path, index=False)
    logger.info(f"✅ Saved {len(df_clean)} deduplicated cross-source papers -> {output_path}")
    return output_path

def run_enrichment(merged_csv_path: str, test_mode: bool = False) -> str:
    """Enrich papers with Semantic Scholar + OpenAlex metadata."""
    from ..transform.enricher import enrich_paper_batch

    df = pd.read_csv(merged_csv_path, dtype=str).fillna("")

    if test_mode and len(df) > 5:
        logger.info(f"🧪 TEST MODE: Limiting enrichment from {len(df)} to 5 papers.")
        df = df.head(5)
    else:
        logger.info(f"📊 Enriching {len(df)} papers...")

    BATCH_SIZE = 200
    for start in range(0, len(df), BATCH_SIZE):
        df = enrich_paper_batch(df, batch_size=BATCH_SIZE, start_idx=start, allow_paid_proxy=True)

    output_path = str(PROCESSED_DATA_DIR / "unesa_papers_enriched.csv")
    df.to_csv(output_path, index=False)
    logger.info(f"✅ Saved {len(df)} enriched papers -> {output_path}")
    return output_path

def run_transform(enriched_csv_path: str) -> str:
    """Scrub HTML, whitespace, and Unicode artifacts."""
    from ..transform.cleaner import clean_papers_batch

    df = pd.read_csv(enriched_csv_path, dtype=str).fillna("")
    df_clean = clean_papers_batch(df)

    output_path = str(PROCESSED_DATA_DIR / "unesa_papers_cleaned.csv")
    df_clean.to_csv(output_path, index=False)
    logger.info(f"✅ Saved {len(df_clean)} cleaned papers -> {output_path}")
    return output_path

def run_database_commit(cleaned_csv_path: str):
    """UPSERT papers securely to Supabase (PostgreSQL) and Neo4j."""
    from ..load.supabase_loader import SupabaseLoader
    from ..load.neo4j_loader import Neo4jLoader

    df = pd.read_csv(cleaned_csv_path, dtype=str).fillna("")
    
    # 1. UPSERT to PostgreSQL (Master Ledger)
    postgres_loader = SupabaseLoader()
    papers_count = postgres_loader.upsert_papers(df)
    links_count = postgres_loader.link_papers_to_lecturers(df)
    
    logger.info(f"✅ [PostgreSQL] Loaded {papers_count} papers and {links_count} links.")
    
    # 2. UPSERT to Neo4j (Graph Index) USING EXACT SAME HASH
    try:
        neo4j_loader = Neo4jLoader()
        graph_count = neo4j_loader.upsert_papers_graph(df)
        neo4j_loader.close()
        logger.info(f"✅ [Neo4j] Loaded {graph_count} papers into Graph DB.")
    except Exception as e:
        logger.error(f"❌ [Neo4j] Ingestion failed! Postgres changes persisted. Error: {e}")
        # Re-raise to let Airflow mark the task as Failed
        raise e
