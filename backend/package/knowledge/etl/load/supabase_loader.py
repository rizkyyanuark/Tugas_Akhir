from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import numpy as np
import pandas as pd
from supabase import Client

from knowledge.etl.clients.supabase_auth import create_etl_supabase_client
from knowledge.etl.utils.logging import log_error, log_event, log_warning

if TYPE_CHECKING:
    from pandas import DataFrame

logger = logging.getLogger(__name__)


class SupabaseLoader:
    """
    Production-grade Supabase loader with:
    - Batch UPSERT (idempotent, no duplicates)
    - Chunked inserts (100 rows at a time to avoid timeouts)
    - JSON-safe value cleaning (no NaN/Inf)
    - Junction table linking (paper_lecturers)
    """

    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        self.client, self.key_role = create_etl_supabase_client(
            url=url,
            key=key,
            require_write=True,
            logger=logger,
        )

    # --- Value Cleaning ---

    @staticmethod
    def _clean_value(value: Any) -> Any:
        """Clean a single value for JSON/SQL compliance."""
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
            v = value.strip()
            if not v or v.lower() in ('nan', 'none', 'null'):
                return None
            # Strip '.0' suffix from ID-like values (NIP, NIDN, Scopus IDs)
            if v.endswith('.0') and v[:-2].isdigit():
                v = v[:-2]
            return v
        return value

    # --- Lecturers ---

    def upsert_lecturers(self, df: pd.DataFrame) -> int:
        """
        Upsert lecturers to 'lecturers' table using NIP as Primary Key (conflict key).
        """
        count = 0
        total = len(df)
        log_event(logger, "supabase.lecturers.upsert_start", rows=total)

        # Prepare records
        records = []
        for _, row in df.iterrows():
            nip = self._clean_value(row.get('nip'))
            name = self._clean_value(row.get('nama_dosen'))
            
            # Wajib punya NIP & Nama
            if not nip or not name:
                continue

            records.append({
                "nip": nip,
                "nama_dosen": name,
                "nama_norm": self._clean_value(row.get('nama_norm')),
                "nidn": self._clean_value(row.get('nidn')),
                "prodi": self._clean_value(row.get('prodi')),
                "scopus_id": self._clean_value(row.get('scopus_id')),
                "scholar_id": self._clean_value(row.get('scholar_id')),
                "sinta_id": self._clean_value(row.get('sinta_id')),
            })

        log_event(logger, "supabase.lecturers.validated", valid_rows=len(records), input_rows=total)
        
        # Batch insert
        for i in range(0, len(records), 100):
            chunk = records[i:i + 100]
            try:
                # Validate JSON safety first
                json.dumps(chunk)  
                self.client.table("lecturers").upsert(
                    chunk, on_conflict="nip"
                ).execute()
                count += len(chunk)
            except Exception as e:
                log_error(logger, "supabase.lecturers.batch_failed", exc=e, offset=i, batch_size=len(chunk))
                raise RuntimeError("Failed to upsert lecturers to Supabase.") from e

        log_event(logger, "supabase.lecturers.upsert_done", upserted=count, input_rows=total)
        return count

    # --- Papers ---

    def upsert_papers(self, df: pd.DataFrame, chunk_size: int = 100) -> int:
        """
        Batch upsert papers to 'papers' table using deterministic `paper_id` as PK.
        Papers missing DOI are now gracefully handled via Title+Year hashes.
        """
        from knowledge.etl.utils.hasher import generate_paper_id
        records: List[Dict[str, Any]] = []
        skipped = 0

        for _, row in df.iterrows():
            title = self._clean_value(row.get('Title') or row.get('title'))
            if not title:
                skipped += 1
                continue

            doi = self._clean_value(row.get('DOI') or row.get('doi'))
            
            year_val = row.get('Year') or row.get('year')
            year = None
            try:
                if year_val and not pd.isna(year_val):
                    year = int(float(str(year_val)))
            except (ValueError, TypeError):
                pass

            # Generate Deterministic ID
            paper_id = generate_paper_id(doi, title, year)

            records.append({
                "paper_id": paper_id,
                "doi": doi,
                "title": title,
                "abstract": self._clean_value(row.get('Abstract') or row.get('abstract')),
                "year": year,
                "journal": self._clean_value(row.get('Journal') or row.get('journal')),
                "document_type": self._clean_value(row.get('Document Type') or row.get('document_type')),
                "authors": self._clean_value(row.get('Authors') or row.get('authors')),
                "author_ids": self._clean_value(row.get('Author IDs') or row.get('author_ids')),
                "keywords": self._clean_value(row.get('Keywords') or row.get('keywords')),
                "link": self._clean_value(row.get('Link') or row.get('link')),
                "tldr": self._clean_value(row.get('TLDR') or row.get('tldr')),
            })

        log_event(logger, "supabase.papers.upsert_start", rows=len(records), skipped_no_title=skipped, chunk_size=chunk_size)

        total_upserted = 0
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            try:
                self.client.table("papers").upsert(
                    chunk, on_conflict="paper_id"
                ).execute()
                total_upserted += len(chunk)
                log_event(
                    logger,
                    "supabase.papers.batch_done",
                    batch=i // chunk_size + 1,
                    rows=len(chunk),
                )
            except Exception as e:
                log_error(logger, "supabase.papers.batch_failed", exc=e, offset=i, batch_size=len(chunk))
                raise RuntimeError("Failed to upsert papers to Supabase.") from e

        log_event(logger, "supabase.papers.upsert_done", upserted=total_upserted, skipped_no_title=skipped)
        return total_upserted

    # --- Junction Table ---

    def link_papers_to_lecturers(self, df: pd.DataFrame) -> int:
        """
        Populate paper_lecturers junction table. (M:M relasi menggunakan paper_id dan nip).
        """
        from knowledge.etl.utils.hasher import generate_paper_id
        
        # 1. Get lecturer mapping: lookup NIP using scopus_id & scholar_id
        res = self.client.table("lecturers").select("nip, scopus_id, scholar_id").execute()
        id_to_nip = {}
        for item in res.data:
            nip = item.get('nip')
            if not nip: continue
            if item.get('scopus_id'):
                id_to_nip[item['scopus_id']] = nip
            if item.get('scholar_id'):
                id_to_nip[item['scholar_id']] = nip

        links = set()
        
        # 2. Extract links locally from DataFrame
        for _, row in df.iterrows():
            title = self._clean_value(row.get('Title') or row.get('title'))
            if not title: continue
                
            doi = self._clean_value(row.get('DOI') or row.get('doi'))
            year_val = row.get('Year') or row.get('year')
            year = None
            try:
                if year_val and not pd.isna(year_val): year = int(float(str(year_val)))
            except: pass
            
            # Recreate the exact same paper_id hash
            paper_id = generate_paper_id(doi, title, year)
            
            author_ids = str(row.get('Author IDs') or row.get('author_ids') or '')
            if not author_ids or author_ids.lower() in ('nan', 'none', ''):
                continue

            for aid in author_ids.replace(',', ';').split(';'):
                aid = str(aid).strip().replace('.0', '')
                if aid in id_to_nip:
                    links.add((paper_id, id_to_nip[aid]))

        if not links:
            log_warning(logger, "supabase.paper_links.empty", action="skip")
            return 0

        # 3. Batch Upsert to Junction Table
        link_data = [{"paper_id": p, "nip": n} for p, n in links]
        total = 0

        log_event(logger, "supabase.paper_links.upsert_start", rows=len(link_data), conflict_key="paper_id,nip")
        for i in range(0, len(link_data), 500):
            chunk = link_data[i:i + 500]
            try:
                self.client.table("paper_lecturers").upsert(
                    chunk, on_conflict="paper_id,nip",
                    ignore_duplicates=True
                ).execute()
                total += len(chunk)
            except Exception as e:
                log_error(logger, "supabase.paper_links.batch_failed", exc=e, batch_size=len(chunk))
                raise RuntimeError("Failed to upsert paper-lecturer links to Supabase.") from e

        log_event(logger, "supabase.paper_links.upsert_done", rows=total)
        return total
