from __future__ import annotations

import json
import math
import logging
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional
from supabase import Client
from .supabase_auth import create_etl_supabase_client
from ..utils.utils import clean_identifier, enforce_strict_ids

logger = logging.getLogger(__name__)

class SupabaseClient:
    """
    Client for interacting with Supabase PostgreSQL database.
    Handles data cleaning, batch upserts, and relationships.
    """
    
    def __init__(self) -> None:
        self.client, self.key_role = create_etl_supabase_client(
            require_write=True,
            logger=logger,
        )

    def _clean_value(self, value: Any) -> Any:
        """
        Clean a single value for JSON/SQL compliance.
        Ensures no NaN or Infinity values enter the database.
        """
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

    def _clean_for_json(self, data: Any) -> Any:
        """Recursively clean dict/list for JSONB compliance."""
        if isinstance(data, dict):
            return {k: self._clean_for_json(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._clean_for_json(v) for v in data]
        elif isinstance(data, (float, np.floating)):
            if math.isnan(data) or math.isinf(data):
                return None
            return float(data)
        elif isinstance(data, (np.integer,)):
            return int(data)
        elif isinstance(data, (np.bool_,)):
            return bool(data)
        else:
            try:
                if pd.isna(data):
                    return None
            except (ValueError, TypeError):
                pass
            return data

    # --- Lecturers ---

    def upsert_lecturers(self, df_lecturers: pd.DataFrame) -> None:
        """
        Batch upserts lecturers into 'lecturers' table.
        Uses 'nip' as conflict resolution key.
        """
        if df_lecturers.empty:
            logger.info("No lecturers to upsert.")
            return

        # Enforce strict ID types
        df = enforce_strict_ids(df_lecturers.copy())
        
        records = []
        for _, row in df.iterrows():
            name = self._clean_value(row.get('nama_dosen'))
            nip = self._clean_value(row.get('nip'))
            
            if not name or not nip:
                continue

            records.append({
                "nama_dosen": name,
                "nama_norm": self._clean_value(row.get('nama_norm') or row.get('_norm_name')),
                "nip": nip,
                "nidn": self._clean_value(row.get('nidn')),
                "prodi": self._clean_value(row.get('prodi') or row.get('nama_prodi')),
                "scopus_id": self._clean_value(row.get('scopus_id')),
                "scholar_id": self._clean_value(row.get('scholar_id')),
                "sinta_id": self._clean_value(row.get('sinta_id')),
            })

        if not records:
            logger.warning("No valid lecturer records found after cleaning.")
            return

        chunk_size = 100
        total_count = 0
        logger.info(f"Upserting {len(records)} lecturers to Supabase...")
        
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            try:
                self.client.table("lecturers").upsert(
                    chunk, on_conflict="nip"
                ).execute()
                total_count += len(chunk)
            except Exception as e:
                logger.error(f"Batch error upserting lecturers at index {i}: {e}")
                raise RuntimeError("Failed to upsert lecturers to Supabase.") from e

        logger.info(f"Successfully upserted {total_count}/{len(records)} lecturers.")

    def get_lecturers_df(self) -> pd.DataFrame:
        """Fetches all lecturers from the 'lecturers' table."""
        logger.info("Fetching lecturers from Supabase...")
        try:
            res = self.client.table("lecturers").select("*").execute()
            if not res.data:
                logger.warning("No lecturers found in database.")
                return pd.DataFrame()
            
            df = pd.DataFrame(res.data)
            logger.info(f"Fetched {len(df)} lecturers.")
            return df
        except Exception as e:
            logger.error(f"Error fetching lecturers: {e}")
            return pd.DataFrame()

    def get_lecturer_id_map(self) -> Dict[str, str]:
        """Returns a mapping of {scopus_id: nip}."""
        try:
            res = self.client.table("lecturers").select("nip, scopus_id").execute()
            return {
                item['scopus_id']: item['nip']
                for item in res.data
                if item.get('scopus_id') and item.get('nip')
            }
        except Exception as e:
            logger.error(f"Error building lecturer ID map: {e}")
            return {}

    # --- Papers ---

    def upsert_papers(self, df_papers: pd.DataFrame | List[Dict[str, Any]]) -> None:
        """
        Upserts papers into 'papers' table using DOI as conflict key.
        """
        if df_papers is None or (hasattr(df_papers, 'empty') and df_papers.empty):
            logger.info("No papers to upsert.")
            return

        papers_list = df_papers.to_dict('records') if isinstance(df_papers, pd.DataFrame) else df_papers
        
        data_to_upsert = []
        for p in papers_list:
            doi = self._clean_value(p.get('DOI') or p.get('doi'))
            if not doi:
                continue

            row = {
                "title": self._clean_value(p.get('Title') or p.get('title')),
                "abstract": self._clean_value(p.get('Abstract') or p.get('abstract')),
                "year": self._parse_year(p.get('Year') or p.get('year')),
                "doi": doi,
                "author_ids": self._clean_value(p.get('Author IDs') or p.get('author_ids')),
                "authors": self._clean_value(p.get('Authors') or p.get('authors')),
                "journal": self._clean_value(p.get('Journal') or p.get('journal') or p.get('Source title')),
                "document_type": self._clean_value(p.get('Document Type') or p.get('document_type')),
                "keywords": self._clean_value(p.get('Keywords') or p.get('keywords')),
                "link": self._clean_value(p.get('Link') or p.get('link')),
                "tldr": self._clean_value(p.get('TLDR') or p.get('tldr')),
            }
            data_to_upsert.append(row)

        if not data_to_upsert:
            logger.info("No valid papers with DOI found for upsert.")
            return

        chunk_size = 100
        total_upserted = 0
        logger.info(f"Upserting {len(data_to_upsert)} papers by DOI...")
        
        for i in range(0, len(data_to_upsert), chunk_size):
            chunk = data_to_upsert[i:i + chunk_size]
            try:
                self.client.table("papers").upsert(
                    chunk, on_conflict="doi"
                ).execute()
                total_upserted += len(chunk)
            except Exception as e:
                logger.error(f"Paper batch error at index {i}: {e}")
                raise RuntimeError("Failed to upsert papers to Supabase.") from e

        logger.info(f"Successfully upserted {total_upserted} papers.")

    def _parse_year(self, year_val: Any) -> Optional[int]:
        """Helper to parse year safely."""
        try:
            if year_val and not pd.isna(year_val):
                return int(float(str(year_val)))
        except (ValueError, TypeError):
            pass
        return None

    def link_papers_to_lecturers(self, df_papers: pd.DataFrame | List[Dict[str, Any]]) -> None:
        """Links papers to lecturers in 'paper_lecturers' junction table."""
        if df_papers is None or (hasattr(df_papers, 'empty') and df_papers.empty):
            return

        papers_list = df_papers.to_dict('records') if isinstance(df_papers, pd.DataFrame) else df_papers
        lec_map = self.get_lecturer_id_map()
        
        # Fetch valid DOIs
        res = self.client.table("papers").select("doi").execute()
        valid_dois = {p['doi'] for p in res.data if p.get('doi')}
        
        links = []
        seen_links = set()
        
        for p in papers_list:
            doi = self._clean_value(p.get('DOI') or p.get('doi'))
            if not doi or doi not in valid_dois:
                continue

            author_ids_str = str(p.get('Author IDs') or p.get('author_ids') or '')
            if author_ids_str and author_ids_str.lower() != 'nan':
                ids = [clean_identifier(x) for x in author_ids_str.split(';') if x.strip()]
                for aid in ids:
                    if aid in lec_map:
                        nip = lec_map[aid]
                        if (doi, nip) not in seen_links:
                            links.append({"paper_doi": doi, "lecturer_nip": nip})
                            seen_links.add((doi, nip))
        
        if not links:
            logger.info("No new lecturer-paper links to insert.")
            return

        chunk_size = 1000
        total_links = 0
        logger.info(f"Inserting {len(links)} lecturer-paper links...")
        
        for i in range(0, len(links), chunk_size):
            chunk = links[i:i + chunk_size]
            try:
                self.client.table("paper_lecturers").upsert(
                    chunk, on_conflict="paper_doi, lecturer_nip", ignore_duplicates=True
                ).execute()
                total_links += len(chunk)
            except Exception as e:
                logger.error(f"Link batch error at index {i}: {e}")
                raise RuntimeError("Failed to upsert lecturer-paper links to Supabase.") from e
                
        logger.info(f"Successfully inserted {total_links} relationships.")

    def get_pending_enrichment_papers(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Returns papers missing TLDR enrichment."""
        res = self.client.table("papers").select(
            "doi, title"
        ).is_("tldr", "null").neq("doi", "null").limit(limit).execute()
        logger.info(f"Found {len(res.data)} papers pending enrichment.")
        return res.data

    def update_paper_enrichment(self, paper_doi: str, tldr: str) -> None:
        """Updates a paper's TLDR using DOI."""
        if not tldr:
            return
        try:
            self.client.table("papers").update({"tldr": str(tldr)}).eq("doi", paper_doi).execute()
        except Exception as e:
            logger.error(f"Failed to update enrichment for {paper_doi}: {e}")
