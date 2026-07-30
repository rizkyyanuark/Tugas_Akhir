from __future__ import annotations

import json
import logging
import math
import os
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional
import psycopg

from ..transform.enricher import normalize_document_type, normalize_venue_name
from ..utils.utils import clean_identifier, enforce_strict_ids

logger = logging.getLogger(__name__)


def get_postgres_connection_string() -> str:
    host = os.getenv("POSTGRES_HOST") or os.getenv("PGHOST") or "postgres-prod"
    port = os.getenv("POSTGRES_PORT") or os.getenv("PGPORT") or "5432"
    db = os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE") or "tugas_akhir"
    user = os.getenv("POSTGRES_USER") or os.getenv("PGUSER") or "postgres"
    password = os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD") or "71509325"
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


class PostgresClient:
    """
    Client for interacting with Self-Hosted PostgreSQL database (postgres-prod).
    Handles data cleaning and batch upserts for the 2-table schema (lecturers, papers).
    """

    def __init__(self, conn_str: str | None = None) -> None:
        self.conn_str = conn_str or get_postgres_connection_string()

    def _get_connection(self) -> psycopg.Connection:
        return psycopg.connect(self.conn_str)

    def _clean_value(self, value: Any) -> Any:
        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except (ValueError, TypeError):
            pass

        if isinstance(value, (np.integer,)):
            return int(value)

        if isinstance(value, (np.bool_,)):
            return bool(value)

        if isinstance(value, (float, np.floating)):
            if math.isnan(value) or math.isinf(value):
                return None
            return float(value)

        if isinstance(value, str):
            return clean_identifier(value)

        return value

    def _parse_year(self, year_val: Any) -> Optional[int]:
        try:
            if year_val and not pd.isna(year_val):
                return int(float(str(year_val)))
        except (ValueError, TypeError):
            pass
        return None

    # --- Lecturers ---

    def upsert_lecturers(self, df_lecturers: pd.DataFrame) -> None:
        """
        Batch upserts lecturers into 'lecturers' table.
        Uses 'nip' as conflict resolution key.
        """
        if df_lecturers.empty:
            logger.info("No lecturers to upsert.")
            return

        df = enforce_strict_ids(df_lecturers.copy())
        records = []
        for _, row in df.iterrows():
            name = self._clean_value(row.get('nama_dosen'))
            nip = self._clean_value(row.get('nip'))

            if not name or not nip:
                continue

            records.append((
                nip,
                name,
                self._clean_value(row.get('nama_norm') or row.get('_norm_name')),
                self._clean_value(row.get('nidn')),
                self._clean_value(row.get('prodi') or row.get('nama_prodi')),
                self._clean_value(row.get('scopus_id')),
                self._clean_value(row.get('scholar_id')),
                self._clean_value(row.get('sinta_id')),
                self._clean_value(row.get('is_active', True)),
            ))

        if not records:
            logger.warning("No valid lecturer records found after cleaning.")
            return

        logger.info(f"Upserting {len(records)} lecturers to Self-Hosted PostgreSQL...")
        sql = """
            INSERT INTO lecturers (
                nip, nama_dosen, nama_norm, nidn, prodi,
                scopus_id, scholar_id, sinta_id, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (nip) DO UPDATE SET
                nama_dosen = EXCLUDED.nama_dosen,
                nama_norm = EXCLUDED.nama_norm,
                nidn = EXCLUDED.nidn,
                prodi = EXCLUDED.prodi,
                scopus_id = EXCLUDED.scopus_id,
                scholar_id = EXCLUDED.scholar_id,
                sinta_id = EXCLUDED.sinta_id,
                is_active = EXCLUDED.is_active,
                updated_at = CURRENT_TIMESTAMP;
        """

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                for r in records:
                    cur.execute(sql, r)
                conn.commit()

        logger.info(f"Successfully upserted {len(records)} lecturers to PostgreSQL.")

    def get_lecturers_df(self) -> pd.DataFrame:
        """Fetches all lecturers from the 'lecturers' table."""
        logger.info("Fetching lecturers from Self-Hosted PostgreSQL...")
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT nip, nama_dosen, nama_norm, nidn, prodi, scopus_id, scholar_id, sinta_id, is_active FROM lecturers;")
                    rows = cur.fetchall()
                    cols = [desc[0] for desc in cur.description]
                    return pd.DataFrame(rows, columns=cols)
        except Exception as e:
            logger.error(f"Error fetching lecturers from PostgreSQL: {e}")
            return pd.DataFrame()

    def get_lecturer_id_map(self) -> Dict[str, str]:
        """Returns a mapping of {scopus_id: nip}."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT scopus_id, nip FROM lecturers WHERE scopus_id IS NOT NULL AND nip IS NOT NULL;")
                    return {row[0]: row[1] for row in cur.fetchall() if row[0] and row[1]}
        except Exception as e:
            logger.error(f"Error building lecturer ID map from PostgreSQL: {e}")
            return {}

    # --- Papers ---

    def upsert_papers(self, df_papers: pd.DataFrame | List[Dict[str, Any]]) -> None:
        """
        Upserts papers into 'papers' table using paper_id or doi as conflict key.
        """
        if df_papers is None or (hasattr(df_papers, 'empty') and df_papers.empty):
            logger.info("No papers to upsert.")
            return

        papers_list = df_papers.to_dict('records') if isinstance(df_papers, pd.DataFrame) else df_papers

        records = []
        for p in papers_list:
            paper_id = self._clean_value(p.get('paper_id') or p.get('id'))
            doi = self._clean_value(p.get('DOI') or p.get('doi'))
            title = self._clean_value(p.get('Title') or p.get('title'))

            if not paper_id and doi:
                import hashlib
                paper_id = hashlib.md5(doi.lower().encode('utf-8')).hexdigest()

            if not paper_id and title:
                import hashlib
                paper_id = hashlib.md5(title.lower().encode('utf-8')).hexdigest()

            if not paper_id or not title:
                continue

            records.append((
                paper_id,
                doi,
                title,
                self._clean_value(p.get('Abstract') or p.get('abstract')),
                self._parse_year(p.get('Year') or p.get('year')),
                self._clean_value(normalize_venue_name(p.get('Journal') or p.get('journal') or p.get('Source title'))),
                normalize_document_type(p.get('Document Type') or p.get('document_type')),
                self._clean_value(p.get('Authors') or p.get('authors')),
                self._clean_value(p.get('Author IDs') or p.get('author_ids')),
                self._clean_value(p.get('Keywords') or p.get('keywords')),
                self._clean_value(p.get('Link') or p.get('link')),
                self._clean_value(p.get('TLDR') or p.get('tldr')),
            ))

        if not records:
            logger.info("No valid papers found for upsert.")
            return

        logger.info(f"Upserting {len(records)} papers to Self-Hosted PostgreSQL...")
        sql = """
            INSERT INTO papers (
                paper_id, doi, title, abstract, year, journal,
                document_type, authors, author_ids, keywords, link, tldr
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (paper_id) DO UPDATE SET
                doi = EXCLUDED.doi,
                title = EXCLUDED.title,
                abstract = EXCLUDED.abstract,
                year = EXCLUDED.year,
                journal = EXCLUDED.journal,
                document_type = EXCLUDED.document_type,
                authors = EXCLUDED.authors,
                author_ids = EXCLUDED.author_ids,
                keywords = EXCLUDED.keywords,
                link = EXCLUDED.link,
                tldr = EXCLUDED.tldr,
                updated_at = CURRENT_TIMESTAMP;
        """

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                count = 0
                for r in records:
                    cur.execute(sql, r)
                    count += 1
                    if count % 1000 == 0:
                        conn.commit()
                conn.commit()

        logger.info(f"Successfully upserted {len(records)} papers to PostgreSQL.")

    def link_papers_to_lecturers(self, df_papers: pd.DataFrame | List[Dict[str, Any]]) -> None:
        """
        No-op for 2-table SQL schema.
        Relationships are represented directly in author_ids and built in Neo4j.
        """
        logger.info("link_papers_to_lecturers: Using 2-table model. Relationships derived from author_ids directly into Neo4j.")

    def get_pending_enrichment_papers(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Returns papers missing TLDR enrichment."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT paper_id, doi, title FROM papers WHERE tldr IS NULL AND doi IS NOT NULL LIMIT %s;", (limit,))
                    rows = cur.fetchall()
                    return [{"paper_id": r[0], "doi": r[1], "title": r[2]} for r in rows]
        except Exception as e:
            logger.error(f"Error fetching pending enrichment papers: {e}")
            return []

    def update_paper_enrichment(self, paper_doi: str, tldr: str) -> None:
        """Updates a paper's TLDR using DOI or paper_id."""
        if not tldr or not paper_doi:
            return
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE papers SET tldr = %s, updated_at = CURRENT_TIMESTAMP WHERE doi = %s OR paper_id = %s;", (str(tldr), paper_doi, paper_doi))
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to update enrichment for {paper_doi}: {e}")
