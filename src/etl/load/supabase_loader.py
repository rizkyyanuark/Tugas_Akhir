"""
Load: Supabase PostgreSQL Loader
=================================
Handles batch UPSERT of papers and lecturers to Supabase.
Implements idempotency via ON CONFLICT DO UPDATE.
"""
import math
import json
import pandas as pd
import numpy as np
from supabase import create_client, Client

from ..config import SUPABASE_URL, SUPABASE_KEY


class SupabaseLoader:
    """
    Production-grade Supabase loader with:
    - Batch UPSERT (idempotent, no duplicates)
    - Chunked inserts (100 rows at a time to avoid timeouts)
    - JSON-safe value cleaning (no NaN/Inf)
    - Junction table linking (paper_lecturers)
    """

    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = url or SUPABASE_URL
        self.key = key or SUPABASE_KEY
        if not self.url or not self.key:
            raise ValueError("❌ SUPABASE_URL or SUPABASE_KEY missing!")
        self.client: Client = create_client(self.url, self.key)
        print(f"✅ SupabaseLoader connected to {self.url}")

    # ─── Value Cleaning ──────────────────────────────────────────────

    @staticmethod
    def _clean_value(value):
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
            return v if v and v.lower() not in ('nan', 'none') else None
        return value

    # ─── Lecturers ───────────────────────────────────────────────────

    def upsert_lecturers(self, df: pd.DataFrame) -> int:
        """
        Upsert lecturers to 'lecturers' table using NIP as conflict key.

        Returns:
            Number of successfully upserted rows.
        """
        count = 0
        total = len(df)
        print(f"\n👨‍🏫 Upserting {total} lecturers...")

        for _, row in df.iterrows():
            name = self._clean_value(row.get('nama_dosen'))
            if not name:
                continue

            data = {
                "nama_dosen": name,
                "nama_norm": self._clean_value(row.get('nama_norm')),
                "nip": self._clean_value(row.get('nip')),
                "nidn": self._clean_value(row.get('nidn')),
                "prodi": self._clean_value(row.get('prodi')),
                "scopus_id": self._clean_value(row.get('scopus_id')),
                "scholar_id": self._clean_value(row.get('scholar_id')),
                "sinta_id": self._clean_value(row.get('sinta_id')),
            }

            try:
                json.dumps(data)  # Validate JSON safety
                self.client.table("lecturers").upsert(
                    data, on_conflict="nip"
                ).execute()
                count += 1
            except Exception as e:
                print(f"   ⚠️ Error upserting {name}: {e}")

        print(f"   ✅ Upserted {count}/{total} lecturers")
        return count

    # ─── Papers ──────────────────────────────────────────────────────

    def upsert_papers(self, df: pd.DataFrame, chunk_size: int = 100) -> int:
        """
        Batch upsert papers to 'papers' table using DOI as conflict key.
        Papers without DOI are skipped (cannot guarantee uniqueness).

        Returns:
            Number of successfully upserted rows.
        """
        records = []
        skipped = 0

        for _, row in df.iterrows():
            doi = self._clean_value(row.get('DOI') or row.get('doi'))
            if not doi:
                skipped += 1
                continue

            title = self._clean_value(row.get('Title') or row.get('title'))
            year_val = row.get('Year') or row.get('year')
            year = None
            try:
                if year_val and not pd.isna(year_val):
                    year = int(float(str(year_val)))
            except (ValueError, TypeError):
                pass

            records.append({
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

        if not records:
            print(f"   ⚠️ No valid papers with DOI (skipped {skipped})")
            return 0

        total_upserted = 0
        print(f"\n📄 Upserting {len(records)} papers (chunk={chunk_size})...")

        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            try:
                self.client.table("papers").upsert(
                    chunk, on_conflict="doi"
                ).execute()
                total_upserted += len(chunk)
                print(f"   ✅ Batch {i // chunk_size + 1}: {len(chunk)} papers")
            except Exception as e:
                print(f"   ❌ Batch error at {i}: {e}")

        print(f"   ✅ Total: {total_upserted} upserted, {skipped} skipped (no DOI)")
        return total_upserted

    # ─── Junction Table ──────────────────────────────────────────────

    def link_papers_to_lecturers(self, df: pd.DataFrame) -> int:
        """
        Populate paper_lecturers junction table.
        Maps Author IDs (Scholar/Scopus IDs) to lecturer NIPs.

        Returns:
            Number of links created.
        """
        # Get lecturer mapping: {scopus_id/scholar_id -> nip}
        res = self.client.table("lecturers").select("nip, scopus_id, scholar_id").execute()
        id_to_nip = {}
        for item in res.data:
            if item.get('scopus_id') and item.get('nip'):
                id_to_nip[item['scopus_id']] = item['nip']
            if item.get('scholar_id') and item.get('nip'):
                id_to_nip[item['scholar_id']] = item['nip']

        # Get valid DOIs in DB
        res = self.client.table("papers").select("doi").execute()
        valid_dois = {p['doi'] for p in res.data if p.get('doi')}

        links = set()
        for _, row in df.iterrows():
            doi = self._clean_value(row.get('DOI') or row.get('doi'))
            if not doi or doi not in valid_dois:
                continue

            author_ids = str(row.get('Author IDs') or row.get('author_ids') or '')
            if not author_ids or author_ids.lower() == 'nan':
                continue

            for aid in author_ids.replace(',', ';').split(';'):
                aid = aid.strip()
                if aid in id_to_nip:
                    links.add((doi, id_to_nip[aid]))

        if not links:
            print("   ⚠️ No lecturer-paper links to insert.")
            return 0

        link_data = [{"paper_doi": d, "lecturer_nip": n} for d, n in links]
        total = 0

        print(f"\n🔗 Linking {len(link_data)} paper-lecturer relationships...")
        for i in range(0, len(link_data), 500):
            chunk = link_data[i:i + 500]
            try:
                self.client.table("paper_lecturers").upsert(
                    chunk, on_conflict="paper_doi,lecturer_nip",
                    ignore_duplicates=True
                ).execute()
                total += len(chunk)
            except Exception as e:
                print(f"   ❌ Link batch error: {e}")

        print(f"   ✅ Linked {total} relationships")
        return total
