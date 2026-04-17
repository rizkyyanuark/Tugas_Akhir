# knowledge/etl/scraping/pipeline.py
"""
Pipeline Scraping Dosen Infokom UNESA v4
=========================================
Industry-grade modular pipeline for lecturer data acquisition.

Pipeline Flow:
    Step 1: run_web_step()            -> raw_web_data.csv       (Source of Truth)
    Step 2: run_pddikti_step()        -> raw_pddikti_data.csv   (Enrichment Source)
    Step 3: run_smart_merge()         -> dosen_infokom_merged.csv (Web-First + Dedup)
    Step 4: run_enrichment()          -> dosen_infokom_final.csv  (SimCV+Sinta+SciVal+Scholar)
    Step 5: run_post_processing()     -> dosen_infokom_final.csv  (Final Clean)
    Step 6: run_supabase_sync()       -> Supabase DB

Each step reads from the previous step's output and produces its own output.
All saves go through save_final_csv() for consistent ID enforcement + QUOTE_ALL.
"""
import pandas as pd
import re
from pathlib import Path
from .config import (
    SAVE_DIR, PRODI_WEB_CONFIG, TARGET_PRODI_NAMES,
    SINTA_DEPTS, HEADERS, ENABLE_SCIVAL, ID_COLUMN_TYPES,
    SCIVAL_EMAIL, SCIVAL_PASS,
)
from .pddikti_client import PddiktiClient
from .simcv_client import SimCVClient
from .sinta_client import SintaCrawler
from .scholar_client import ScholarVerificationClient
from .scival_client import SciValClient
from .parsers import PARSER_MAP
from .utils import (
    clean_name_expert, enforce_strict_types, save_final_csv, normalize_name,
)
from difflib import SequenceMatcher

# --- ACTIVE CONFIG ---
ACTIVE_CONFIGS = [
    cfg for cfg in PRODI_WEB_CONFIG if cfg[1] in TARGET_PRODI_NAMES
]

# --- FILE PATHS (Single Source of Truth) ---
RAW_WEB_CSV       = SAVE_DIR / "raw_web_data.csv"
RAW_PDDIKTI_CSV   = SAVE_DIR / "raw_pddikti_data.csv"
MERGED_CSV         = SAVE_DIR / "dosen_infokom_merged.csv"
FINAL_CSV          = SAVE_DIR / "dosen_infokom_final.csv"


# ================================================================
# STEP 1: WEB SCRAPING (Source of Truth)
# ================================================================
def run_web_step():
    """Scrape lecturer data from 10+ prodi websites. Source of Truth."""
    print("\n--- STEP 1: WEB SCRAPER ---")
    
    from .web_scraper import WebProdiScraper
    scraper = WebProdiScraper(PARSER_MAP)
    all_records = scraper.scrape(ACTIVE_CONFIGS)

    df = pd.DataFrame(all_records)
    save_final_csv(df, RAW_WEB_CSV, label="Step 1: Web Scraping")
    print(f"   Total Web records: {len(df)}")
    return RAW_WEB_CSV


# ================================================================
# STEP 2: PDDIKTI COLLECTION (Enrichment Source)
# ================================================================
def run_pddikti_step():
    """Fetch lecturer data from PDDIKTI API. Used for enrichment only."""
    print(f"\n--- STEP 2: PDDIKTI COLLECTION for {len(ACTIVE_CONFIGS)} Active Configs ---")
    
    client = PddiktiClient()
    all_records = client.search_lecturers(ACTIVE_CONFIGS)
    
    df = pd.DataFrame(all_records)
    save_final_csv(df, RAW_PDDIKTI_CSV, label="Step 2: PDDIKTI")
    print(f"   Total PDDIKTI records: {len(df)}")
    return RAW_PDDIKTI_CSV


# ================================================================
# STEP 3: SMART MERGE (Web-First, PDDIKTI Enrichment)
# ================================================================

def _find_pddikti_match(pddikti_norm, pddikti_nidn, pddikti_prodi, web_data):
    """
    Match a PDDIKTI record against Web data (strict).
    Strategy: exact -> NIDN -> substring -> fuzzy (>=0.85).
    Returns (match_key, score) or (None, 0).
    """
    # 1. Exact name match
    if pddikti_norm in web_data:
        return pddikti_norm, 1.0

    # 2. NIDN-based match (very reliable)
    if pddikti_nidn and str(pddikti_nidn).strip() and str(pddikti_nidn).strip() != 'nan':
        for k, rec in web_data.items():
            if rec.get('nidn') and str(rec['nidn']).strip() == str(pddikti_nidn).strip():
                return k, 1.0

    # 3. Substring match (same prodi only, min 3 tokens)
    for k, rec in web_data.items():
        if rec.get('prodi') != pddikti_prodi:
            continue
        if k.startswith(pddikti_norm) or pddikti_norm.startswith(k):
            shorter = min(len(k.split()), len(pddikti_norm.split()))
            if shorter >= 3:
                return k, 0.95

    # 4. Fuzzy match (strict: >=0.85)
    best_key = None
    best_s = 0
    for k in web_data:
        if not k or not pddikti_norm:
            continue
        if k[0] != pddikti_norm[0]:
            continue
        s = SequenceMatcher(None, k, pddikti_norm).ratio()
        if s > best_s:
            best_s = s
            best_key = k

    if best_s >= 0.85:
        return best_key, best_s

    return None, 0


def _enrich_from_pddikti(rec, pddikti_row):
    """Enrich a Web record with PDDIKTI data (NIDN, NIP, prodi)."""
    # NIDN from PDDIKTI (authoritative source)
    if pd.notna(pddikti_row.get('nidn')) and str(pddikti_row['nidn']).strip() not in ('', 'nan'):
        rec['nidn'] = str(pddikti_row['nidn']).strip()
    # NIP from PDDIKTI (if web doesn't have it)
    if pd.isna(rec.get('nip')) and pd.notna(pddikti_row.get('nip')):
        rec['nip'] = pddikti_row['nip']
    # Prodi from PDDIKTI (more accurate than web   e.g. Teknik Elektro vs Pend. Teknik Elektro)
    pddikti_prodi = pddikti_row.get('prodi_pddikti')
    if pd.notna(pddikti_prodi) and str(pddikti_prodi).strip():
        rec['prodi'] = _normalize_prodi_name(str(pddikti_prodi).strip())


# Mapping PDDIKTI prodi names (uppercase) to standardized display names
_PRODI_NAME_MAP = {
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
    # Campus variants (PDDIKTI sometimes includes campus location)
    'INFORMATIKA (KAMPUS KABUPATEN MAGETAN)': 'S2 Informatika',
    # S2 programs
    'PENDIDIKAN TEKNOLOGI INFORMASI (S2)': 'S2 Pendidikan Teknologi Informasi',
}

def _normalize_prodi_name(pddikti_prodi):
    """Convert PDDIKTI uppercase prodi to standardized display name."""
    upper = pddikti_prodi.upper().strip()
    if upper in _PRODI_NAME_MAP:
        return _PRODI_NAME_MAP[upper]
    # Fallback: Title case
    return pddikti_prodi.title()


# Known INFOKOM prodi names   only these are accepted for SimCV prodi update
_KNOWN_INFOKOM_PRODIS = {
    'S1 Teknik Informatika', 'S1 Sistem Informasi',
    'S1 Pendidikan Teknologi Informasi', 'S1 Teknik Elektro',
    'S1 Pendidikan Teknik Elektro', 'S1 Kecerdasan Artifisial',
    'S1 Sains Data', 'S1 Bisnis Digital',
    'D4 Manajemen Informatika',
    'S2 Informatika', 'S2 Pendidikan Teknologi Informasi',
}


def _dedup_within_prodi(df):
    """
    Comprehensive deduplication within the same prodi.
    Strategies: fuzzy name (>=0.75), same scholar_id, same NIDN.
    Merges IDs from dropped record into kept record.
    """
    ID_COLS = ['nip', 'nidn', 'scholar_id', 'scopus_id', 'sinta_id']
    drop_indices = set()
    
    for prodi in df['prodi'].dropna().unique():
        prodi_mask = df['prodi'] == prodi
        prodi_df = df[prodi_mask]
        if len(prodi_df) < 2:
            continue
        
        norms = prodi_df['nama_norm'].tolist()
        indices = prodi_df.index.tolist()
        
        for i in range(len(norms)):
            if indices[i] in drop_indices:
                continue
            for j in range(i + 1, len(norms)):
                if indices[j] in drop_indices:
                    continue
                
                a = str(norms[i]).lower()
                b = str(norms[j]).lower()
                
                # Strategy 1: Fuzzy name similarity >= 0.75
                is_dup = SequenceMatcher(None, a, b).ratio() >= 0.75
                
                # Strategy 2: Same scholar_id = same person
                if not is_dup:
                    sid_i = df.at[indices[i], 'scholar_id'] if 'scholar_id' in df.columns else None
                    sid_j = df.at[indices[j], 'scholar_id'] if 'scholar_id' in df.columns else None
                    if pd.notna(sid_i) and pd.notna(sid_j) and sid_i == sid_j:
                        is_dup = True
                
                # Strategy 3: Same NIDN = same person
                if not is_dup:
                    nidn_i = df.at[indices[i], 'nidn'] if 'nidn' in df.columns else None
                    nidn_j = df.at[indices[j], 'nidn'] if 'nidn' in df.columns else None
                    if pd.notna(nidn_i) and pd.notna(nidn_j) and nidn_i == nidn_j:
                        is_dup = True
                
                if is_dup:
                    # Keep the row with more filled IDs
                    count_i = sum(1 for c in ID_COLS if c in df.columns and pd.notna(df.at[indices[i], c]))
                    count_j = sum(1 for c in ID_COLS if c in df.columns and pd.notna(df.at[indices[j], c]))
                    keep = indices[i] if count_i >= count_j else indices[j]
                    drop = indices[j] if keep == indices[i] else indices[i]
                    
                    # Absorb IDs from dropped into kept
                    for c in ID_COLS:
                        if c in df.columns and pd.isna(df.at[keep, c]) and pd.notna(df.at[drop, c]):
                            df.at[keep, c] = df.at[drop, c]
                    
                    # Keep longest name
                    if len(str(df.at[drop, 'nama_dosen'])) > len(str(df.at[keep, 'nama_dosen'])):
                        df.at[keep, 'nama_dosen'] = df.at[drop, 'nama_dosen']
                    
                    drop_indices.add(drop)
    
    if drop_indices:
        print(f"   Dedup: removed {len(drop_indices)} duplicate(s)")
        df = df.drop(index=list(drop_indices)).reset_index(drop=True)
    
    return df


def run_smart_merge():
    """
    WEB-FIRST Smart Merge.
    - Web data = source of truth (base records)
    - PDDIKTI data = enrichment only (NIDN, NIP)
    - PDDIKTI-only records are EXCLUDED
    - Includes comprehensive deduplication
    """
    print("\n--- STEP 3: SMART MERGE ---")
    print("   (WEB-FIRST)...")
    try:
        df_web = pd.read_csv(RAW_WEB_CSV, dtype=ID_COLUMN_TYPES)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        print("   Web Data missing/empty. Run Step 1 first.")
        return None
        
    try:
        df_pddikti = pd.read_csv(RAW_PDDIKTI_CSV, dtype=ID_COLUMN_TYPES)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        print("   PDDIKTI Data empty. Proceeding without PDDIKTI enrichment.")
        df_pddikti = pd.DataFrame(columns=['nama_norm', 'nidn', 'prodi_name', 'nip'])
        
    # A. PRE-LOAD EXISTING IDS (Persistence/Resume)
    existing_ids = {}
    if FINAL_CSV.exists():
        try:
            df_existing = pd.read_csv(FINAL_CSV, dtype=ID_COLUMN_TYPES)
            for _, row in df_existing.iterrows():
                norm = str(row['nama_norm']).strip().lower()
                if norm:
                    # Collect all useful IDs to preserve them
                    existing_ids[norm] = {
                        'scholar_id': row.get('scholar_id') if pd.notna(row.get('scholar_id')) else None,
                        'scopus_id': row.get('scopus_id') if pd.notna(row.get('scopus_id')) else None,
                        'sinta_id': row.get('sinta_id') if pd.notna(row.get('sinta_id')) else None,
                        'nip': row.get('nip') if pd.notna(row.get('nip')) else None,
                        'nidn': row.get('nidn') if pd.notna(row.get('nidn')) else None,
                    }
            print(f"   (INFO) Loaded persistence data for {len(existing_ids)} lecturers from {FINAL_CSV.name}")
        except Exception as e:
            print(f"   Could not load existing FINAL_CSV for persistence: {e}")

    # B. BASE: Web Data (source of truth)
    web_data = {}
    for _, row in df_web.iterrows():
        key = str(row['nama_norm']).strip().lower()
        if not key or key == 'nan':
            continue
            
        # Initialize record
        rec = {
            'nama_dosen': row['nama_dosen'],
            'nama_norm': row['nama_norm'],
            'nip': row['nip'] if pd.notna(row.get('nip')) else None,
            'nidn': str(row['nidn']) if pd.notna(row.get('nidn')) else None,
            'prodi': row.get('prodi_name'),
            'affiliation': 'UNIVERSITAS NEGERI SURABAYA',
            'scholar_id': row['scholar_id'] if pd.notna(row.get('scholar_id')) else None,
            'scopus_id': None,
            'sinta_id': None,
            'source': 'WEB',
        }
        
        # Merge persistence data if available
        if key in existing_ids:
            p = existing_ids[key]
            for field in ['scholar_id', 'scopus_id', 'sinta_id', 'nip', 'nidn']:
                if pd.isna(rec.get(field)) and p.get(field):
                    rec[field] = p[field]
                    if 'RESUME' not in rec['source']:
                        rec['source'] += '+RESUME'
        
        web_data[key] = rec
    print(f"   (STATS) Web Base Records: {len(web_data)}")
        
    # C. ENRICH with PDDIKTI (strict match)
    print("   Matching PDDIKTI -> Web (exact -> NIDN -> substring -> fuzzy >=0.85)...")
    count_enriched = 0
    count_skipped = 0
    
    for _, pddikti_row in df_pddikti.iterrows():
        pddikti_norm = str(pddikti_row['nama_norm']).strip().lower()
        if not pddikti_norm or pddikti_norm == 'nan':
            continue
        
        pddikti_nidn = pddikti_row.get('nidn')
        pddikti_prodi = pddikti_row.get('prodi_name')
        
        match_key, score = _find_pddikti_match(pddikti_norm, pddikti_nidn, pddikti_prodi, web_data)
        
        if match_key:
            rec = web_data[match_key]
            _enrich_from_pddikti(rec, pddikti_row)
            if '+PDDIKTI' not in rec['source']:
                rec['source'] += '+PDDIKTI'
            count_enriched += 1
        else:
            count_skipped += 1
            
    # C. Build DataFrame
    df_merged = pd.DataFrame(web_data.values())
    cols = ['nama_dosen', 'nama_norm', 'nip', 'nidn', 'prodi', 'scholar_id', 'scopus_id', 'sinta_id', 'source']
    valid_cols = [c for c in cols if c in df_merged.columns]
    df_merged = df_merged[valid_cols]
    
    # D. Comprehensive deduplication
    print("   Running deduplication...")
    df_merged = _dedup_within_prodi(df_merged)
    
    # E. Save
    save_final_csv(df_merged, MERGED_CSV, label="Step 3: Smart Merge")
    print(f"   PDDIKTI Enriched: {count_enriched} | Skipped: {count_skipped}")
    print(f"   Final Merged: {len(df_merged)} records")
    return MERGED_CSV


# ================================================================
# STEP 4: ENRICHMENT (SimCV + Sinta + SciVal + Scholar)
# ================================================================


# SimCV namasatker format: "Teknik Informatika S1" -> "S1 Teknik Informatika"
def _normalize_simcv_prodi(namasatker):
    """Convert SimCV namasatker to standardized prodi name."""
    if not namasatker or str(namasatker).strip() in ('', 'None', 'nan'):
        return None
    s = str(namasatker).strip()
    # Extract jenjang suffix (S1, S2, S3, D3, D4)
    m = re.match(r'^(.+?)\s+(S[123]|D[34])$', s)
    if m:
        name_part = m.group(1).strip()
        jenjang = m.group(2).strip()
        return f"{jenjang} {name_part}"
    return s


def _run_simcv(df):
    """Enrich NIP/NIDN, nama_dosen, and prodi from SimCV API."""
    print("\n   [4a] Enriching NIP/NIDN + nama_dosen + prodi from SimCV...")
    
    client = SimCVClient()
    count = 0
    skipped = 0
    searched = 0
    
    for idx, row in df.iterrows():
        # Search ALL records (SimCV provides clean nama_dosen and prodi)
        
        searched += 1
        queries = [row['nama_norm'], row['nama_dosen']]
        best_cand = None
        best_s = 0
        
        for q in set([x for x in queries if pd.notna(x) and len(str(x)) > 3]):
            res = client.search(q)
            for r in res:
                cv_raw = str(r.get('namalengkap', ''))
                cv_norm = clean_name_expert(cv_raw).lower()
                our_norm = str(row['nama_norm']).lower()
                
                s = SequenceMatcher(None, our_norm, cv_norm).ratio()
                if s > 0.85 and s > best_s:
                    best_s = s
                    best_cand = r
            if best_s > 0.95:
                break
        
        if best_cand:
            updated = False
            # Enrich NIP
            if pd.isna(row['nip']) and best_cand.get('nip'):
                nip_val = str(best_cand.get('nip')).strip()
                if nip_val and nip_val != 'None':
                    df.at[idx, 'nip'] = nip_val
                    updated = True
            # Enrich NIDN
            if pd.isna(row['nidn']) and best_cand.get('nidn'):
                nidn_val = str(best_cand.get('nidn')).strip()
                if nidn_val and nidn_val != 'None':
                    df.at[idx, 'nidn'] = nidn_val
                    updated = True
            # Always update nama_dosen from SimCV (cleaner source)
            cv_fullname = str(best_cand.get('namalengkap', '')).strip()
            if cv_fullname and cv_fullname != 'None' and len(cv_fullname) > 3:
                df.at[idx, 'nama_dosen'] = cv_fullname
                updated = True
            # Always update prodi from SimCV (authoritative source)
            cv_prodi = _normalize_simcv_prodi(best_cand.get('namasatker'))
            if cv_prodi:
                df.at[idx, 'prodi'] = cv_prodi
                updated = True
            if updated:
                count += 1
    
    print(f"      Searched: {searched}, Skipped: {skipped}, Enriched: {count}")
    return df


def _run_sinta(df):
    """Enrich Sinta IDs from SINTA website."""
    print("\n   [4b] Enriching Sinta IDs...")
    
    crawler = SintaCrawler()
    cache = []
    
    active_prodis = df['prodi'].unique()
    for p in active_prodis:
        if pd.isna(p):
            continue
        cache.extend(crawler.crawl_dept(p))
    
    print(f"      Cached {len(cache)} Sinta Profiles.")
    
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
    
    print(f"      Enriched: {count} Sinta IDs")
    return df


def _run_scival(df):
    """Enrich Scopus IDs via SciVal automation."""
    if not ENABLE_SCIVAL:
        print("\n   [4c] SciVal: DISABLED in config. Skipping.")
        return df
    
    print("\n[4a] SimCV Automation...")
    client = SciValClient()
    df_updated = client.run_automation(df)
    
    if df_updated is not None:
        return df_updated
    return df


def _run_scholar(df, sample_size=None):
    """
    Verify/Search Google Scholar IDs via Bright Data in parallel.
    """
    print("\n   [4d] Scholar Verification & Search (Parallel / Bright Data)...")
    
    if 'scholar_id' not in df.columns:
        df['scholar_id'] = None
    
    client = ScholarVerificationClient()
    if not client.proxies:
        print("      Skipping Scholar Step (No Proxy Configured)")
        return df
    
    # 1. Identify rows needing processing
    # Filter out lecturers who already have a valid scholar_id (Resume logic)
    to_process = []
    
    indices = df.index.tolist()
    if sample_size and sample_size < len(indices):
        indices = indices[:sample_size]
        
    for idx in indices:
        row = df.loc[idx]
        sid = str(row.get('scholar_id', '')).strip() if pd.notna(row.get('scholar_id')) else ''
        name = str(row['nama_norm']) if pd.notna(row['nama_norm']) else str(row['nama_dosen'])
        
        # If no ID, we need to search
        if not sid or sid.lower() == 'nan' or len(sid) < 5:
            to_process.append({'index': idx, 'name': name, 'id': None})
        else:
            # We HAVE an ID, but we should verify it if it hasn't been verified this run
            # For efficiency, if it came from +RESUME in Step 3, we TRUST it.
            source = str(row.get('source', ''))
            if 'RESUME' in source or 'SCHOLAR' in source:
                continue # Skip already verified IDs
            else:
                to_process.append({'index': idx, 'name': name, 'id': sid})

    if not to_process:
        print("      No lecturers need Scholar processing/verification.")
        return df

    print(f"      (EXEC) Processing {len(to_process)} lecturers in parallel...")
    
    # 2. Execute Batch
    results = client.verify_batch(to_process)
    
    # 3. Apply Results
    new_found = 0
    verified = 0
    invalidated = 0
    
    for res in results:
        idx = res['index']
        if res['valid'] and res['id']:
            if df.at[idx, 'scholar_id'] != res['id']:
                new_found += 1
            else:
                verified += 1
            df.at[idx, 'scholar_id'] = res['id']
            # Add marker
            source = str(df.at[idx, 'source'])
            if 'SCHOLAR' not in source:
                df.at[idx, 'source'] = source + '+SCHOLAR'
        else:
            if pd.notna(df.at[idx, 'scholar_id']):
                invalidated += 1
            df.at[idx, 'scholar_id'] = None

    print(f"      (DONE) Results: {new_found} New, {verified} Verified, {invalidated} Invalidated")
    return df


def run_enrichment(scholar_sample=None):
    """
    Combined enrichment pipeline: SimCV -> Sinta -> SciVal -> Scholar.
    Reads from merged CSV, enriches progressively, saves to final CSV.
    
    Args:
        scholar_sample: If set, only process this many Scholar records (saves API credits)
    """
    print("\n" + "=" * 60)
    print("\n--- STEP 4: ENRICHMENT PIPELINE ---")
    print("=" * 60)
    
    try:
        df = pd.read_csv(MERGED_CSV, dtype=ID_COLUMN_TYPES)
    except FileNotFoundError:
        print("   Merged file not found. Run Step 3 first.")
        return None
    
    print(f"     Input: {len(df)} records from {MERGED_CSV.name}")
    
    # 4a. SimCV (NIP/NIDN)
    df = _run_simcv(df)
    save_final_csv(df, FINAL_CSV, label="After SimCV")
    
    # 4b. Sinta (Sinta IDs)
    df = _run_sinta(df)
    save_final_csv(df, FINAL_CSV, label="After Sinta")
    
    # 4c. SciVal (Scopus IDs)
    df = _run_scival(df)
    save_final_csv(df, FINAL_CSV, label="After SciVal")
    
    # 4d. Scholar (Google Scholar IDs)
    df = _run_scholar(df, sample_size=scholar_sample)
    save_final_csv(df, FINAL_CSV, label="After Scholar")
    
    print(f"\n   Enrichment Complete: {len(df)} records")
    return FINAL_CSV


# ================================================================
# STEP 5: POST-PROCESSING (Final Clean + Dedup)
# ================================================================
def run_post_processing():
    """
    Final pipeline step before Supabase sync.
    - Re-runs deduplication (catches any dups introduced by enrichment)
    - Enforces strict types on all ID columns
    - Saves with QUOTE_ALL for clean text
    """
    print("\n--- STEP 2: PDDIKTI API ---")
    print("POST-PROCESSING...")
    
    try:
        df = pd.read_csv(FINAL_CSV, dtype=ID_COLUMN_TYPES)
    except FileNotFoundError:
        print("   Final file not found. Run Step 4 first.")
        return None
    
    print(f"   Input: {len(df)} records")
    
    # 1. Final deduplication
    df = _dedup_within_prodi(df)
    
    # 2. Drop any remaining exact duplicates
    before = len(df)
    df = df.drop_duplicates(subset=['nama_norm'], keep='first')
    if len(df) < before:
        print(f"   Removed {before - len(df)} exact duplicate(s)")
    
    # 3. Save (enforce_strict_types + QUOTE_ALL handled by save_final_csv)
    df = save_final_csv(df, FINAL_CSV, label="Post-Processing")
    
    # 4. Summary statistics
    id_cols = ['nip', 'nidn', 'scholar_id', 'scopus_id', 'sinta_id']
    print(f"\n   FINAL DATASET: {len(df)} records")
    for col in id_cols:
        if col in df.columns:
            filled = df[col].notna().sum()
            pct = (filled / len(df) * 100) if len(df) > 0 else 0
            print(f"      {col}: {filled}/{len(df)} ({pct:.1f}%)")
    
    return FINAL_CSV


# ================================================================
# STEP 6: SUPABASE SYNC
# ================================================================
def run_supabase_sync():
    """
    Upload final data to Supabase. Last step of the pipeline.
    Reads from FINAL_CSV, validates IDs, and upserts to 'lecturers' table.
    """
    from .supabase_client import SupabaseClient
    
    print("\n--- STEP 6: SUPABASE SYNC ---")
    print("SYNCHRONIZATION")
    print("=" * 50)
    
    try:
        df = pd.read_csv(FINAL_CSV, dtype=str)  # Always read as string for DB ops
    except FileNotFoundError:
        print("   Final file not found. Run previous steps first.")
        return None
    
    df = enforce_strict_types(df)
    print(f"     Loaded {len(df)} rows from {FINAL_CSV.name}")
    
    # Sanity check: no .0 suffixes
    id_cols = ['nip', 'nidn', 'scholar_id', 'scopus_id', 'sinta_id']
    for col in id_cols:
        if col in df.columns:
            has_dot = df[col].dropna().str.contains(r'\.0$', regex=True).any()
            if has_dot:
                print(f"      {col} still has .0 suffix! Data quality issue.")
    
    # Upsert
    supabase = SupabaseClient()
    supabase.upsert_lecturers(df)
    
    print(f"\n     Done! {len(df)} lecturers synced to Supabase.")
    return len(df)

