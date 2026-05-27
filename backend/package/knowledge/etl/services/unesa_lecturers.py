import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any, Set
from difflib import SequenceMatcher

import pandas as pd
import re

from ..config import (
    SINTA_DEPTS, ENABLE_SCIVAL, ID_COLUMN_TYPES,
)
from ..clients.pddikti_client import PddiktiClient
from ..clients.simcv_client import SimCVClient
from ..clients.sinta_client import SintaCrawler
from ..clients.scholar_client import ScholarVerificationClient
from ..clients.scival_client import SciValClient
from ..clients.parsers import PARSER_MAP
from ..utils.utils import (
    clean_lecturer_name, enforce_strict_ids, save_final_csv,
)
from ..utils.storage import read_dataframe_csv
from ..utils.identity import (
    clean_optional as _clean_optional,
    has_value as _has_value,
    merge_missing_fields as _merge_missing_fields,
)
from .lecturer_paths import (
    FINAL_CSV,
    ID_FIELDS,
    MERGED_CSV,
    SCRAPE_PDDIKTI_PATH,
    SCRAPE_WEB_PATH,
    filter_active_configs,
)
from .siakadu_identity import enrich_with_siakadu

logger = logging.getLogger(__name__)


def _looks_like_noisy_web_name(name: Any) -> bool:
    if not _has_value(name):
        return True
    return str(name).strip().lower().endswith("dosen")

# Step 1: University Web Scraping

def scrape_university_websites(prodi_filter: str | None = None) -> pd.DataFrame:
    """
    Scrape lecturer data from university department websites.
    """
    from ..clients.web_scraper import WebProdiScraper
    
    logger.info("[STEP 1] UNIVERSITY WEB SCRAPING")
    
    configs = filter_active_configs(prodi_filter)
    if prodi_filter:
        if not configs:
            logger.warning(f"No active config found for prodi filter: {prodi_filter}")
        else:
            logger.info(f"Filtering enabled: Only processing {prodi_filter}")

    scraper = WebProdiScraper(PARSER_MAP)
    all_records = scraper.scrape(configs)

    df_web = pd.DataFrame(all_records)
    
    # Save checkpoint
    save_final_csv(df_web, SCRAPE_WEB_PATH, label="Step 1: Web Scraping")
    logger.info(f"Success: Scraped {len(df_web)} records.")
    
    return df_web


# Step 2: PDDIKTI Collection

def fetch_pddikti_data(prodi_filter: str | None = None) -> pd.DataFrame:
    """
    Fetch lecturer data from the PDDIKTI API for enrichment purposes.
    """
    logger.info("[STEP 2] PDDIKTI DATA COLLECTION")
    
    configs = filter_active_configs(prodi_filter)
    if prodi_filter:
        if not configs:
            logger.warning(f"No active config found for prodi filter: {prodi_filter}")
        else:
            logger.info(f"Filtering enabled: Only processing {prodi_filter}")

    logger.info(f"Targeting {len(configs)} departments...")
    
    client = PddiktiClient()
    all_records = client.search_lecturers(configs)
    
    df_pddikti = pd.DataFrame(all_records)
    
    # Save checkpoint
    save_final_csv(df_pddikti, SCRAPE_PDDIKTI_PATH, label="Step 2: PDDIKTI")
    logger.info(f"Success: Fetched {len(df_pddikti)} records from PDDIKTI.")
    
    return df_pddikti


# Step 3: Smart Merge

def _find_source_match(
    norm_name: str, 
    nidn: str, 
    prodi_name: str, 
    reference_data: Dict[str, Any]
) -> Tuple[Optional[str], float]:
    """
    Find matching record in reference data using prioritized strategy.
    Strategy: Exact -> NIDN -> Substring -> Fuzzy.
    """
    # 1. Exact name match
    if norm_name in reference_data:
        return norm_name, 1.0

    # 2. NIDN-based match
    if nidn and str(nidn).strip().lower() not in ('nan', 'none', ''):
        clean_nidn = str(nidn).strip()
        for key, rec in reference_data.items():
            if rec.get('nidn') == clean_nidn:
                return key, 1.0

    # 3. Substring match (constrained by department)
    for key, rec in reference_data.items():
        if rec.get('prodi') == prodi_name:
            if key.startswith(norm_name) or norm_name.startswith(key):
                if min(len(key.split()), len(norm_name.split())) >= 3:
                    return key, 0.95

    # 4. Fuzzy match (Strict threshold)
    best_match, best_score = None, 0.0
    for key in reference_data:
        if not key or not norm_name or key[0] != norm_name[0]:
            continue
        score = SequenceMatcher(None, key, norm_name).ratio()
        if score > best_score:
            best_score, best_match = score, key

    return (best_match, best_score) if best_score >= 0.85 else (None, 0.0)


def _normalize_prodi_name(pddikti_prodi: str) -> str:
    """Standardize departmental names from PDDIKTI to University format."""
    PRODI_MAP = {
        'TEKNIK INFORMATIKA': 'S1 Teknik Informatika',
        'SISTEM INFORMASI': 'S1 Sistem Informasi',
        'PENDIDIKAN TEKNOLOGI INFORMASI': 'S1 Pendidikan Teknologi Informasi',
        'TEKNIK ELEKTRO': 'S1 Teknik Elektro',
        'PENDIDIKAN TEKNIK ELEKTRO': 'S1 Pendidikan Teknik Elektro',
        'KECERDASAN ARTIFISIAL': 'S1 Kecerdasan Artifisial',
        'SAINS DATA': 'S1 Sains Data',
        'BISNIS DIGITAL': 'S1 Bisnis Digital',
        'MANAJEMEN INFORMATIKA': 'D4 Manajemen Informatika',
        'INFORMATIKA': 'S2 Informatika',
        'PENDIDIKAN TEKNOLOGI INFORMASI (S2)': 'S2 Pendidikan Teknologi Informasi',
    }
    upper_name = str(pddikti_prodi).upper().strip()
    return PRODI_MAP.get(upper_name, upper_name.title())


def _deduplicate_lecturers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Professional deduplication within the same department.
    Merges IDs and preserves the most complete records.
    """
    drop_indices: Set[int] = set()
    
    for prodi in df['prodi'].dropna().unique():
        prodi_df = df[df['prodi'] == prodi]
        if len(prodi_df) < 2:
            continue
        
        indices = prodi_df.index.tolist()
        names = prodi_df['nama_norm'].tolist()
        
        for i in range(len(names)):
            idx_i = indices[i]
            if idx_i in drop_indices:
                continue
            for j in range(i + 1, len(names)):
                idx_j = indices[j]
                if idx_j in drop_indices:
                    continue
                
                # Deduplication logic (Name Similarity or ID overlap)
                is_dup = SequenceMatcher(None, str(names[i]), str(names[j])).ratio() >= 0.75
                
                if not is_dup:
                    # Check for ID overlap if names aren't similar enough
                    for col in ['scholar_id', 'nidn']:
                        val_i, val_j = df.at[idx_i, col], df.at[idx_j, col]
                        if _has_value(val_i) and _has_value(val_j) and str(val_i) == str(val_j):
                            is_dup = True
                            break
                
                if is_dup:
                    # Keep the record with more data
                    score_i = sum(1 for c in ID_FIELDS if _has_value(df.at[idx_i, c]))
                    score_j = sum(1 for c in ID_FIELDS if _has_value(df.at[idx_j, c]))
                    keep, drop = (idx_i, idx_j) if score_i >= score_j else (idx_j, idx_i)
                    
                    # Merge data before dropping
                    for c in ID_FIELDS:
                        if not _has_value(df.at[keep, c]) and _has_value(df.at[drop, c]):
                            df.at[keep, c] = df.at[drop, c]
                    
                    drop_indices.add(drop)
                    
    return df.drop(index=list(drop_indices))


def run_smart_merge(df_web: pd.DataFrame, df_pddikti: pd.DataFrame) -> Path:
    """
    Merge web-scraped data with PDDIKTI enrichment.
    """
    logger.info("SMART MERGE: Starting merge process")
    
    web_data: Dict[str, Any] = {}
    
    # A. Load Web Data as Base
    duplicate_web_rows = 0
    for _, row in df_web.iterrows():
        key = str(row['nama_norm']).strip().lower()
        if not key or key == 'nan':
            continue

        incoming = {
            'nama_dosen': _clean_optional(row.get('nama_dosen')),
            'nama_norm': _clean_optional(row.get('nama_norm')),
            'nip': _clean_optional(row.get('nip')),
            'nidn': _clean_optional(row.get('nidn')),
            'prodi': _clean_optional(row.get('prodi_name')),
            'affiliation': 'UNIVERSITAS NEGERI SURABAYA',
            'scholar_id': _clean_optional(row.get('scholar_id')),
            'scopus_id': None,
            'sinta_id': None,
            'source': 'WEB',
        }

        if key in web_data:
            duplicate_web_rows += 1
            rec = web_data[key]
            _merge_missing_fields(rec, incoming, ID_FIELDS)
            _merge_missing_fields(rec, incoming, ['nama_dosen', 'nama_norm', 'prodi', 'affiliation'])

            if (
                _looks_like_noisy_web_name(rec.get('nama_dosen'))
                and _has_value(incoming.get('nama_dosen'))
                and not _looks_like_noisy_web_name(incoming.get('nama_dosen'))
            ):
                rec['nama_dosen'] = incoming['nama_dosen']

            continue

        web_data[key] = incoming
    
    logger.info(f"Web Base Records: {len(web_data)}")
    logger.info(
        "Merged %s duplicate web rows by nama_norm while preserving non-empty identifiers.",
        duplicate_web_rows,
    )
        
    # B. Enrich with PDDIKTI
    count_enriched = 0
    count_skipped = 0
    
    for _, p_row in df_pddikti.iterrows():
        p_norm = str(p_row['nama_norm']).strip().lower()
        if not p_norm or p_norm == 'nan':
            continue
        
        p_nidn = p_row.get('nidn')
        p_prodi = p_row.get('prodi_name')
        
        match_key, _ = _find_source_match(p_norm, p_nidn, p_prodi, web_data)
        
        if match_key:
            rec = web_data[match_key]
            # Update missing fields
            for field in ['nip', 'nidn', 'scholar_id']:
                if not _has_value(rec.get(field)) and _has_value(p_row.get(field)):
                    rec[field] = _clean_optional(p_row.get(field))

            if _looks_like_noisy_web_name(rec.get('nama_dosen')) and _has_value(p_row.get('nama_dosen')):
                rec['nama_dosen'] = _clean_optional(p_row.get('nama_dosen'))
            
            if '+PDDIKTI' not in rec['source']:
                rec['source'] += '+PDDIKTI'
            count_enriched += 1
        else:
            count_skipped += 1
            
    # C. Build DataFrame
    df_merged = pd.DataFrame(web_data.values())
    df_merged = _deduplicate_lecturers(df_merged)
    
    # D. Save
    save_final_csv(df_merged, MERGED_CSV, label="Step 3: Smart Merge")
    logger.info(f"PDDIKTI Enriched: {count_enriched} | Skipped: {count_skipped}")
    logger.info(f"Final Merged: {len(df_merged)} records")
    
    return MERGED_CSV


# Step 4: Enrichment

def _normalize_simcv_prodi(namasatker: Any) -> Optional[str]:
    """Convert SimCV namasatker to standardized prodi name."""
    if not namasatker or str(namasatker).strip() in ('', 'None', 'nan'):
        return None
    s = str(namasatker).strip()
    m = re.match(r'^(.+?)\s+(S[123]|D[34])$', s)
    if m:
        name_part = m.group(1).strip()
        jenjang = m.group(2).strip()
        return f"{jenjang} {name_part}"
    return s


def _run_simcv(df: pd.DataFrame) -> pd.DataFrame:
    """Enrich data from SimCV API."""
    logger.info("Enriching from SimCV...")
    
    client = SimCVClient()
    count = 0
    
    for idx, row in df.iterrows():
        queries = [row['nama_norm'], row['nama_dosen']]
        best_cand = None
        best_s = 0
        
        for q in set([x for x in queries if pd.notna(x) and len(str(x)) > 3]):
            res = client.search(q)
            for r in res:
                cv_raw = str(r.get('namalengkap', ''))
                cv_norm = clean_lecturer_name(cv_raw).lower()
                our_norm = str(row['nama_norm']).lower()
                
                s = SequenceMatcher(None, our_norm, cv_norm).ratio()
                if s > 0.85 and s > best_s:
                    best_s = s
                    best_cand = r
            if best_s > 0.95:
                break
        
        if best_cand:
            updated = False
            if not _has_value(row.get('nip')) and best_cand.get('nip'):
                df.at[idx, 'nip'] = str(best_cand.get('nip')).strip()
                updated = True
            if not _has_value(row.get('nidn')) and best_cand.get('nidn'):
                df.at[idx, 'nidn'] = str(best_cand.get('nidn')).strip()
                updated = True
            
            fullname = str(best_cand.get('namalengkap', '')).strip()
            if len(fullname) > 3:
                df.at[idx, 'nama_dosen'] = fullname
                updated = True
                
            cv_prodi = _normalize_simcv_prodi(best_cand.get('namasatker'))
            if cv_prodi:
                df.at[idx, 'prodi'] = cv_prodi
                updated = True
                
            if updated:
                count += 1
    
    logger.info(f"SimCV Enriched: {count} records")
    return df


def _run_sinta(df: pd.DataFrame) -> pd.DataFrame:
    """Enrich Sinta IDs."""
    logger.info("Enriching Sinta IDs...")
    
    crawler = SintaCrawler()
    cache: List[Dict[str, Any]] = []
    
    for p in df['prodi'].unique():
        if pd.notna(p):
            cache.extend(crawler.crawl_dept(str(p)))
    
    count = 0
    for idx, row in df.iterrows():
        if pd.notna(row.get('sinta_id')):
            continue
        
        t_name = str(row['nama_norm']).lower()
        for item in cache:
            if t_name == str(item['name']).lower():
                df.at[idx, 'sinta_id'] = item['sinta_id']
                count += 1
                break
    
    logger.info(f"Sinta Enriched: {count} IDs")
    return df


def _run_scival(df: pd.DataFrame) -> pd.DataFrame:
    """Enrich Scopus IDs via SciVal."""
    if not ENABLE_SCIVAL:
        logger.info("[4c] SciVal: DISABLED. Skipping.")
        return df
    
    logger.info("SciVal Automation...")
    client = SciValClient()
    df_updated = client.run_automation(df)
    
    return df_updated if df_updated is not None else df


def _run_scholar(df: pd.DataFrame, sample_size: Optional[int] = None) -> pd.DataFrame:
    """Verify/Search Google Scholar IDs."""
    logger.info("Scholar Verification and Search...")
    
    if 'scholar_id' not in df.columns:
        df['scholar_id'] = None
    
    client = ScholarVerificationClient()
    if not client.proxies:
        logger.warning("Skipping Scholar (No Proxy Configured)")
        return df
    
    to_process = []
    indices = df.index.tolist()
    if sample_size and sample_size < len(indices):
        indices = indices[:sample_size]
        
    for idx in indices:
        row = df.loc[idx]
        sid = str(row.get('scholar_id', '')).strip() if pd.notna(row.get('scholar_id')) else ''
        name = str(row['nama_norm']) if pd.notna(row['nama_norm']) else str(row['nama_dosen'])
        
        if not sid or sid.lower() == 'nan' or len(sid) < 5:
            to_process.append({'index': idx, 'name': name, 'id': None})
        else:
            source = str(row.get('source', ''))
            if 'RESUME' not in source and 'SCHOLAR' not in source:
                to_process.append({'index': idx, 'name': name, 'id': sid})

    if not to_process:
        return df

    results = client.verify_batch(to_process)
    
    for res in results:
        idx = res['index']
        if res['valid'] and res['id']:
            df.at[idx, 'scholar_id'] = res['id']
            source = str(df.at[idx, 'source'])
            if 'SCHOLAR' not in source:
                df.at[idx, 'source'] = source + '+SCHOLAR'
        else:
            df.at[idx, 'scholar_id'] = None

    return df


def run_enrichment(scholar_sample: Optional[int] = None) -> Optional[Path]:
    """Combined enrichment pipeline."""
    logger.info("--- STEP 4: ENRICHMENT PIPELINE ---")
    
    try:
        df = read_dataframe_csv(MERGED_CSV, dtype=ID_COLUMN_TYPES)
    except FileNotFoundError:
        logger.error("Merged file not found. Run Step 3 first.")
        return None
    
    df = enrich_with_siakadu(df)
    df = _run_simcv(df)
    df = _run_sinta(df)
    df = _run_scival(df)
    df = _run_scholar(df, sample_size=scholar_sample)
    
    save_final_csv(df, FINAL_CSV, label="Step 4: Enrichment Complete")
    return FINAL_CSV


# Step 5: Post-Processing

def run_post_processing() -> Optional[Path]:
    """Final pipeline cleanup."""
    logger.info("--- STEP 5: POST-PROCESSING ---")
    
    try:
        df = read_dataframe_csv(FINAL_CSV, dtype=ID_COLUMN_TYPES)
    except FileNotFoundError:
        logger.error("Final file not found. Run Step 4 first.")
        return None
    
    df = _deduplicate_lecturers(df)
    df = df.drop_duplicates(subset=['nama_norm'], keep='first')
    
    # Final save handles enforce_strict_ids
    save_final_csv(df, FINAL_CSV, label="Step 5: Post-Processing Complete")
    
    logger.info(f"Final dataset: {len(df)} records")
    return FINAL_CSV


# Step 6: Supabase Sync

def run_supabase_sync() -> int:
    """Sync final data to Supabase."""
    from ..clients.supabase_client import SupabaseClient
    
    logger.info("SUPABASE SYNC: Starting sync process")
    
    try:
        df = read_dataframe_csv(FINAL_CSV, dtype=str)
    except FileNotFoundError:
        logger.error("Final file not found. Run previous steps first.")
        return 0
    
    df = enforce_strict_ids(df)
    supabase = SupabaseClient()
    supabase.upsert_lecturers(df)
    
    logger.info(f"Done: {len(df)} lecturers synced to Supabase.")
    return len(df)

