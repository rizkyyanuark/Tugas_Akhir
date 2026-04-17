# knowledge/etl/scraping/supabase_client.py
import json
import math
import numpy as np
import pandas as pd
from datetime import datetime
from supabase import create_client, Client
from .config import SUPABASE_URL, SUPABASE_KEY
from .utils import clean_identifier, enforce_strict_types


class SupabaseClient:
    def __init__(self):
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("  Supabase URL or Key missing in config.py!")
            
        # --- DOCKER/SUPABASE-PY PATCH ---
        # supabase-py > 2.0 strictly validates the key via regex matching JWTs.
        # However, some modern Supabase keys use the `sb_publishable_...` format.
        # We temporarily disable the regex check during initialization.
        import re
        import supabase._sync.client as sc
        original_match = re.match
        
        def mock_match(pattern, string, flags=0):
            # If it's the JWT regex check coming from supabase client, bypass it
            if isinstance(string, str) and string.startswith("sb_publishable_"):
                return True # Pretend it matches
            return original_match(pattern, string, flags)
            
        re.match = mock_match
        try:
            self.client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        finally:
            re.match = original_match # Restore
            
        print(f"  Supabase Client Connected to {SUPABASE_URL}")

    #     Cleaning Helpers                                             

    def _clean_value(self, value):
        """
        Clean a single value for JSON/SQL compliance.
        Returns: str, int, float, bool, None, dict, or list   NEVER NaN/inf.
        """
        if value is None:
            return None

        # pandas/numpy NA
        try:
            if pd.isna(value):
                return None
        except (ValueError, TypeError):
            pass

        # numpy int   python int
        if isinstance(value, (np.integer,)):
            return int(value)

        # numpy bool   python bool
        if isinstance(value, (np.bool_,)):
            return bool(value)

        # float / numpy float   check nan/inf
        if isinstance(value, (float, np.floating)):
            if math.isnan(value) or math.isinf(value):
                return None
            return float(value)

        # string cleanup
        if isinstance(value, str):
            return clean_identifier(value)

        return value

    def _clean_for_json(self, data):
        """Recursively clean dict/list for JSONB compliance (no NaN/inf)."""
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

    #     Lecturers                                                    

    def upsert_lecturers(self, df_dosen):
        """
        Upserts lecturers into 'lecturers' table.
        Uses (norm_name, prodi) as conflict resolution key.
        All IDs must already be clean TEXT or None (via enforce_strict_types).
        """
        # Pre-clean entire DataFrame
        df_dosen = enforce_strict_types(df_dosen.copy())

        count = 0
        errors = 0
        total = len(df_dosen)
        print(f"  Upserting {total} lecturers to Supabase...")

        for _, row in df_dosen.iterrows():
            name = self._clean_value(row.get('nama_dosen'))
            norm_name = self._clean_value(row.get('nama_norm') or row.get('_norm_name'))
            prodi = self._clean_value(row.get('prodi') or row.get('nama_prodi'))

            if not name:
                continue

            data = {
                "nama_dosen": name,
                "nama_norm": norm_name,
                "nip": self._clean_value(row.get('nip')),
                "nidn": self._clean_value(row.get('nidn')),
                "prodi": prodi,
                "scopus_id": self._clean_value(row.get('scopus_id')),
                "scholar_id": self._clean_value(row.get('scholar_id')),
                "sinta_id": self._clean_value(row.get('sinta_id')),
            }

            # Validate: json-safe check
            try:
                json.dumps(data)
            except (TypeError, ValueError) as je:
                print(f"      JSON Error for {name}: {je}")
                errors += 1
                continue

            try:
                self.client.table("lecturers").upsert(
                    data, on_conflict="nip"
                ).execute()
                count += 1
            except Exception as e:
                print(f"      Error upserting {name}: {e}")
                errors += 1

        print(f"  Upserted {count}/{total} lecturers. ({errors} errors)")

    #     Lecturer Map                                                 

    def get_lecturer_id_map(self):
        """Returns a dict {scopus_id: lecturer_nip} for linking papers."""
        # Note: We now link via mapping Scopus ID -> NIP (because Author IDs in paper are Scopus IDs)
        # But wait, the papers have "Author IDs" (Scopus IDs). We need to map Scopus ID -> NIP.
        # The lecturers table has 'scopus_id' and 'nip'.
        res = self.client.table("lecturers").select("nip, scopus_id").execute()
        return {
            item['scopus_id']: item['nip']
            for item in res.data
            if item.get('scopus_id') and item.get('nip')
        }

    #     Papers                                                       

    def upsert_papers(self, df_papers, source='scopus'):
        """
        Upserts papers into 'papers' table.
        Handles both Scopus CSV export columns and parsed plain-text columns.
        Splits upsert strategy: 
          - with 'scopus_id' -> upsert on scopus_id
          - no 'scopus_id' but 'doi' -> upsert on doi
        NOTE: Does NOT link to lecturer directly (use link_papers_to_lecturers).
        """
        if df_papers is None or (hasattr(df_papers, 'empty') and df_papers.empty):
            print("   No papers to upsert.")
            return

        # Convert DataFrame to list of dicts
        if hasattr(df_papers, 'to_dict'):
            papers_list = df_papers.to_dict('records')
        else:
            papers_list = df_papers

        data_to_upsert = []
        skipped = 0

        for p in papers_list:
            # Paper Scopus ID (Unique Key)
            # Try 'scopus_id' -> 'ScopusID' -> 'EID' (common in Scopus export)
            p_scopus_id = clean_identifier(
                p.get('scopus_id') or p.get('ScopusID') or p.get('Scopus_ID') or p.get('EID')
            )
            
            # Clean DOI
            doi = self._clean_value(p.get('DOI') or p.get('doi'))
            if doi and doi.lower() in ('nan', 'none', ''):
                doi = None

            # Skip if NO ID and NO DOI (cannot identify paper)
            if not p_scopus_id and not doi:
                skipped += 1
                continue

            # Title
            title = self._clean_value(p.get('Title') or p.get('title'))

            # Abstract
            abstract = self._clean_value(p.get('Abstract') or p.get('abstract'))

            # Year
            year = None
            year_val = p.get('Year') or p.get('year')
            try:
                if year_val and not pd.isna(year_val):
                    year = int(float(str(year_val)))
            except (ValueError, TypeError):
                year = None

            # TLDR & Keywords (from Semantic Scholar enrichment)
            tldr = self._clean_value(p.get('TLDR') or p.get('tldr'))
            keywords = self._clean_value(p.get('Keywords') or p.get('keywords'))

            # Author IDs (for cross-referencing)
            auth_ids = self._clean_value(p.get('Author IDs') or p.get('author_ids'))

            row = {
                "title": title,
                "abstract": abstract,
                "year": year,
                "doi": doi,
                # REMOVED: scopus_paper_id, source, lecturer_id, owner_scopus_id
                "author_ids": auth_ids,
                "authors": self._clean_value(p.get('Authors') or p.get('authors')),
                "journal": self._clean_value(p.get('Journal') or p.get('journal') or p.get('Source title')),
                "document_type": self._clean_value(p.get('Document Type') or p.get('document_type')),
                "keywords": keywords,
                "link": self._clean_value(p.get('Link') or p.get('link')),
                "tldr": tldr,
            }

            data_to_upsert.append(row)

        if not data_to_upsert:
            print(f"   No valid papers to upsert (skipped {skipped}).")
            return

        # Filter valid papers with DOI
        valid_papers = [r for r in data_to_upsert if r.get('doi')]
        skipped_no_doi = len(data_to_upsert) - len(valid_papers)

        if not valid_papers:
            print(f"   No papers with DOI found (skipped {skipped_no_doi} without DOI).")
            return

        total_upserted = 0
        chunk_size = 100

        print(f"  Upserting {len(valid_papers)} papers (by DOI)...")
        for i in range(0, len(valid_papers), chunk_size):
            chunk = valid_papers[i:i + chunk_size]
            try:
                self.client.table("papers").upsert(
                    chunk, on_conflict="doi"
                ).execute()
                total_upserted += len(chunk)
                print(f"     Batch {i // chunk_size + 1}: {len(chunk)} papers")
            except Exception as e:
                print(f"     Batch error at {i}: {e}")

        print(f"  Total: {total_upserted} papers upserted. ({skipped + skipped_no_doi} skipped)")


    def link_papers_to_lecturers(self, df_papers):
        """
        Populate 'paper_lecturers' junction table.
        Uses 'owner_scopus_id' (or 'Scopus_Author_ID') in paper records 
        to link to 'lecturers.scopus_id'.
        """
        if df_papers is None or (hasattr(df_papers, 'empty') and df_papers.empty):
            return

        # Convert DataFrame to list of dicts
        if hasattr(df_papers, 'to_dict'):
            papers_list = df_papers.to_dict('records')
        else:
            papers_list = df_papers

        print(f"  Linking {len(papers_list)} paper records to lecturers...")
        lec_map = self.get_lecturer_id_map() # {scopus_id: nip}
        
        # We need paper_dois. 
        # Strategy: Query map of {doi: doi} from DB for existence check?
        # Actually logic below uses DOI to link.
        
        # Fetch existing DOIs to ensure we only link valid papers
        res = self.client.table("papers").select("doi").execute()
        valid_dois = {p['doi'] for p in res.data if p.get('doi')}
        
        links = set() # Set of (paper_doi, lecturer_nip)
        
        for p in papers_list:
            # 1. Identify Lecturers (Multi-author support)
            
            target_lecturer_nips = set()
            
            # Check Author IDs column (Map Scopus Author ID -> Lecturer NIP)
            author_ids_str = str(p.get('Author IDs') or p.get('author_ids') or '')
            if author_ids_str and author_ids_str.lower() != 'nan':
                ids = [clean_identifier(x) for x in author_ids_str.split(';') if x.strip()]
                for aid in ids:
                    if aid in lec_map:
                        target_lecturer_nips.add(lec_map[aid])
            
            if not target_lecturer_nips:
                continue

            # 2. Identify Paper (DOI)
            doi = self._clean_value(p.get('DOI') or p.get('doi'))
            if not doi or doi not in valid_dois:
                continue

            # 3. Add to Links
            for nip in target_lecturer_nips:
                links.add((doi, nip))
        
        if not links:
            print("      No new links to insert.")
            return

        print(f"     Found {len(links)} lecturer-paper links. Inserting...")
        # Dictionary for mapping
        link_data = [{"paper_doi": doi, "lecturer_nip": nip} for doi, nip in links]
        
        # Batch insert
        chunk_size = 1000
        total_links = 0
        for i in range(0, len(link_data), chunk_size):
            chunk = link_data[i:i + chunk_size]
            try:
                self.client.table("paper_lecturers").upsert(
                    chunk, on_conflict="paper_doi, lecturer_nip", ignore_duplicates=True
                ).execute()
                total_links += len(chunk)
                print(f"     Linked batch {i//chunk_size + 1}")
            except Exception as e:
                print(f"        Link batch error: {e}")
                
        print(f"     Linked {total_links} relationships.")

    #     Enrichment                                                   

    def get_pending_enrichment_papers(self, limit=100):
        """Returns papers that haven't been enriched yet (no TLDR)."""
        # Only need DOI and Title for S2 search
        # Note: We use DOI as the primary key now.
        res = self.client.table("papers").select(
            "doi, title"
        ).is_("tldr", "null").neq("doi", "null").limit(limit).execute()
        print(f"  Found {len(res.data)} papers pending enrichment.")
        return res.data

    def update_paper_enrichment(self, paper_doi, tldr):
        """
        Updates a paper with TLDR using DOI.
        """
        if not tldr:
            return

        try:
            self.client.table("papers").update({"tldr": str(tldr)}).eq("doi", paper_doi).execute()
        except Exception as e:
            print(f"     Failed to update enrichment for {paper_doi}: {e}")
