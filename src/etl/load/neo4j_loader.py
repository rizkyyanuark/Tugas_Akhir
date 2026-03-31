"""
Load: Neo4j Graph Database Loader
=================================
Handles graph ingestion of academic papers, authors, and relation logic.
Fully idempotent using Cypher MERGE logic.
Shares identically generated `paper_id` with PostgreSQL.
"""
import pandas as pd
from neo4j import GraphDatabase
import logging

from ..config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from ..utils.hasher import generate_paper_id

logger = logging.getLogger(__name__)

class Neo4jLoader:
    """
    Production-grade Neo4j Loader.
    Implements bulk `UNWIND` operations for maximum insert speed and complete idempotency.
    """
    
    def __init__(self, uri=None, user=None, password=None):
        self.uri = uri or NEO4J_URI
        self.user = user or NEO4J_USER
        self.password = password or NEO4J_PASSWORD
        
        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self.driver.verify_connectivity()
            logger.info(f"✅ Neo4jLoader connected to {self.uri}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Neo4j at {self.uri}: {e}")
            raise

    def close(self):
        """Cleanly shutdown the driver."""
        self.driver.close()

    def upsert_papers_graph(self, df: pd.DataFrame, chunk_size: int = 500) -> int:
        """
        Upsert Papers as nodes, Authors as Nodes, and their relationships.
        Leverages hashing logic dynamically over the DataFrame before UNWIND.
        """
        records = []
        skipped = 0

        # Construct payload identical to Postgres parsing
        for _, row in df.iterrows():
            title = str(row.get('Title') or row.get('title') or '').strip()
            if not title or title.lower() in ('nan', 'none', ''):
                skipped += 1
                continue

            doi = str(row.get('DOI') or row.get('doi') or '').strip()
            
            # Parse Year safely
            year_val = row.get('Year') or row.get('year')
            year = None
            try:
                if year_val and not pd.isna(year_val):
                    year = int(float(str(year_val)))
            except (ValueError, TypeError):
                pass
            
            author_str = str(row.get('Authors') or row.get('authors') or '').strip()
            
            # Ensure deterministic ID parity
            paper_id = generate_paper_id(doi, title, year)
            
            records.append({
                "paper_id": paper_id,
                "title": title,
                "year": year,
                "authors": author_str
            })

        logger.info(f"🕸️ Bulk Upserting {len(records)} papers to Neo4j (chunk={chunk_size})...")
        
        total_upserted = 0
        with self.driver.session() as session:
            for i in range(0, len(records), chunk_size):
                chunk = records[i:i + chunk_size]
                try:
                    result = session.execute_write(self._merge_nodes_and_edges, chunk)
                    total_upserted += len(chunk)
                    logger.info(f"   ✅ Graph Batch {i // chunk_size + 1}: {len(chunk)} papers processed.")
                except Exception as e:
                    logger.error(f"   ❌ Graph Batch error at index {i}: {e}")
        
        logger.info(f"   ✅ Total: {total_upserted} upserted to Neo4j, {skipped} skipped (no title)")
        return total_upserted

    @staticmethod
    def _merge_nodes_and_edges(tx, records):
        """
        Idempotent Cypher Query using UNWIND.
        1. Guarantees paper node creation.
        2. Splits author string by ';' and iteratively creates/merges Author nodes.
        3. Creates the (Author)-[:AUTHORED_BY]->(Paper) relationship.
        """
        query = """
        UNWIND $batch AS row
        
        // --- 1. Paper Node ---
        MERGE (p:Paper {id: row.paper_id})
        SET p.title = row.title,
            p.published_year = row.year
            
        // --- 2. Author Nodes & Relationships ---
        // Need to bridge the specific context per paper row
        WITH p, row
        WHERE row.authors IS NOT NULL AND row.authors <> 'nan' AND row.authors <> ''
        
        UNWIND split(row.authors, ';') AS raw_author
        WITH p, trim(raw_author) AS auth_name WHERE auth_name <> ""
        
        // Merge the Author Node globally
        MERGE (a:Author {name: auth_name})
        
        // Merge the Relationship
        MERGE (a)-[:AUTHORED_BY]->(p)
        """
        tx.run(query, batch=records)
