"""
Transform: String Cleaner
=========================
Aggressively cleans string fields (Abstract, Keywords, Title, etc.) from dirty
web scraping artifacts (HTML tags, excess whitespace, zero-width spaces, newlines).
Also provides ID-safe column handling for Author IDs, DOI, etc.
Includes author name normalization (Scopus "Last, First" → "First Last").
"""
import pandas as pd
import numpy as np
import re
from pathlib import Path
from difflib import SequenceMatcher


def clean_text(text: str) -> str:
    """Apply aggressive regex cleaning to a single string."""
    if not isinstance(text, str) or pd.isna(text):
        return ""
        
    # Remove HTML tags (e.g. <br>, <i>)
    text = re.sub(r'<[^>]+>', ' ', text)
    # Remove zero-width characters and invisible unicode spaces
    text = re.sub(r'[\u200b\u200c\u200d\u2060\ufeff]', '', text)
    # Convert literal \n or \t strings back into actual spaces
    text = text.replace('\\n', ' ').replace('\\t', ' ').replace('\\r', ' ')
    # Replace actual newlines, carriage returns, and tabs with a single space
    text = re.sub(r'[\n\r\t]+', ' ', text)
    # Collapse multiple consecutive spaces into a single space
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def clean_id_value(val) -> str:
    """
    Clean a single ID value for consistency:
    - Strip '.0' suffix (from float casting by pandas)
    - Convert NaN/None/nan to empty string
    - Never cast to int/float — always return string
    """
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    s = str(val).strip()
    # Remove pandas float artifact (.0 suffix)
    if s.endswith(".0"):
        s = s[:-2]
    # Remove common garbage values
    if s.lower() in ("nan", "none", "null", "na", ""):
        return ""
    return s


# ─── Author Name Normalization ──────────────────────────────────

def _flip_author_name(name: str) -> str:
    """Convert Scopus 'Last, First Middle' → 'First Middle Last'.
    If no comma detected, returns the name as-is (already in natural order).
    """
    name = name.strip()
    if ',' in name:
        parts = name.split(',', 1)
        return f"{parts[1].strip()} {parts[0].strip()}"
    return name


def _normalize_name_for_matching(name: str) -> str:
    """Normalize name for fuzzy matching (removes titles, periods, commas)."""
    if not name:
        return ""
    name = str(name).strip().lower()
    # Remove Indonesian academic titles
    titles = [
        r'\bprof\.?\b', r'\bdr\.?\b', r'\bir\.?\b', r'\bdrs\.?\b',
        r'\bs\.?t\.?\b', r'\bs\.?kom\.?\b', r'\bs\.?pd\.?\b', r'\bs\.?si\.?\b',
        r'\bm\.?t\.?\b', r'\bm\.?kom\.?\b', r'\bm\.?pd\.?\b', r'\bm\.?si\.?\b',
        r'\bm\.?eng\.?\b', r'\bm\.?sc\.?\b', r'\bph\.?d\.?\b',
        r'\bm\.?m\.?\b', r'\bs\.?e\.?\b', r'\bm\.?a\.?\b',
        r',', r'\.',
    ]
    for t in titles:
        name = re.sub(t, ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


# Singleton lecturer map for cleaner
_cleaner_lecturer_map = None

def _load_cleaner_lecturer_map() -> dict:
    """Load lecturer data for the cleaner. Returns {norm_name: entry}."""
    global _cleaner_lecturer_map
    if _cleaner_lecturer_map is not None:
        return _cleaner_lecturer_map

    _cleaner_lecturer_map = {}
    
    csv_paths = [
        Path("/opt/airflow/notebooks/scraping/file_tabulars/dosen_infokom_final.csv"),
        Path(__file__).resolve().parent.parent.parent / "notebooks" / "scraping" / "file_tabulars" / "dosen_infokom_final.csv",
        Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "dosen_infokom_final.csv",
    ]
    
    for csv_path in csv_paths:
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path, dtype=str).fillna("")
                for _, row in df.iterrows():
                    nama = str(row.get('nama_dosen', '')).strip()
                    norm = str(row.get('nama_norm', '') or '').strip()
                    scopus_id = str(row.get('scopus_id', '')).strip().replace('.0', '')
                    scholar_id = str(row.get('scholar_id', '')).strip()
                    
                    if not nama or nama == 'nan':
                        continue
                    
                    entry = {
                        'scopus_id': scopus_id if scopus_id and scopus_id != 'nan' else '',
                        'scholar_id': scholar_id if scholar_id and scholar_id != 'nan' else '',
                        'nama_dosen': nama,
                        'nama_norm': norm if norm and norm != 'nan' else nama,
                    }
                    
                    # Index by multiple variants
                    norm_full = _normalize_name_for_matching(nama)
                    if norm_full:
                        _cleaner_lecturer_map[norm_full] = entry
                    if norm and norm != 'nan':
                        norm_clean = _normalize_name_for_matching(norm)
                        if norm_clean:
                            _cleaner_lecturer_map[norm_clean] = entry
                    
                    # Index by reversed name (Scopus convention)
                    parts = norm_full.split()
                    if len(parts) >= 2:
                        _cleaner_lecturer_map[f"{parts[-1]} {parts[0]}"] = entry
                        # Also support first-initial matching (e.g., "y yamasari" → "yuni yamasari")
                        for i, p in enumerate(parts):
                            if len(p) == 1:  # It's an initial
                                # This handles "Y Yamasari" → match to "Yuni Yamasari"
                                continue
                
                print(f"✅ Cleaner lecturer map loaded: {len(_cleaner_lecturer_map)} name variants")
                break
            except Exception as e:
                print(f"⚠️ Could not load lecturer CSV for cleaner: {e}")
    
    return _cleaner_lecturer_map


def _match_name_to_lecturer(author_name: str, threshold: float = 0.75) -> dict:
    """Match a single author name against known lecturers.
    
    Handles:
    - Exact match: "Yuni Yamasari" → match
    - Reversed names: "Yamasari, Yuni" → flipped → match
    - Abbreviated: "Y Yamasari" → fuzzy match to "Yuni Yamasari"
    - Partial: "Elly Matul Imah" vs "elly matul imah" → match
    
    Returns: {'name': str, 'scopus_id': str, 'scholar_id': str, 'matched': bool}
    """
    lec_map = _load_cleaner_lecturer_map()
    if not lec_map:
        return {'name': author_name, 'matched': False}
    
    # Flip if Scopus format
    flipped = _flip_author_name(author_name)
    norm = _normalize_name_for_matching(flipped)
    
    if not norm:
        return {'name': author_name, 'matched': False}
    
    # Strategy 1: Exact match
    if norm in lec_map:
        entry = lec_map[norm]
        return {'name': entry['nama_norm'], 'scopus_id': entry['scopus_id'],
                'scholar_id': entry['scholar_id'], 'matched': True}
    
    # Strategy 2: Containment (handles shortened vs full names)
    for lec_name, entry in lec_map.items():
        if norm in lec_name or lec_name in norm:
            # Avoid very short matches (e.g. "Ali" in "Alim")
            if len(norm) > 5 and len(lec_name) > 5:
                return {'name': entry['nama_norm'], 'scopus_id': entry['scopus_id'],
                        'scholar_id': entry['scholar_id'], 'matched': True}
    
    # Strategy 3: Initial matching with relaxed length (e.g., "RE Putra" -> "Ricky Eka Putra")
    norm_parts = norm.split()
    if len(norm_parts) >= 2:
        for lec_name, entry in lec_map.items():
            lec_parts = lec_name.split()
            if len(norm_parts) <= len(lec_parts):
                # Check first part alignment
                np0 = norm_parts[0]
                lp0 = lec_parts[0]
                
                f_match = False
                consumed_lec_parts = 0
                
                if np0 == lp0 or (len(np0) == 1 and lp0.startswith(np0)):
                    f_match = True
                    consumed_lec_parts = 1
                elif len(np0) >= 2 and len(np0) <= len(lec_parts) - 1:
                    # Try to see if 're' matches 'ricky' 'eka'
                    # Actually just check initials: r==r, e==e
                    sub_match = True
                    for i, char in enumerate(np0):
                        if i >= len(lec_parts) or not lec_parts[i].startswith(char):
                            sub_match = False
                            break
                    if sub_match:
                        f_match = True
                        consumed_lec_parts = len(np0)
                
                if f_match:
                    # Check last part alignment
                    nplast = norm_parts[-1]
                    lplast = lec_parts[-1]
                    l_match = (nplast == lplast) or (len(nplast) == 1 and lplast.startswith(nplast))
                    
                    if l_match:
                        # Success!
                        return {'name': entry['nama_norm'], 'scopus_id': entry['scopus_id'],
                                'scholar_id': entry['scholar_id'], 'matched': True}

    # Strategy 4: Fuzzy matching
    best_score = 0
    best_entry = None
    for lec_name, entry in lec_map.items():
        score = SequenceMatcher(None, norm, lec_name).ratio()
        if score > best_score:
            best_score = score
            best_entry = entry
    
    if best_entry and best_score >= threshold:
        return {'name': best_entry['nama_norm'], 'scopus_id': best_entry['scopus_id'],
                'scholar_id': best_entry['scholar_id'], 'matched': True}
    
    return {'name': flipped, 'matched': False}


def _normalize_authors_and_ids(authors_str: str, author_ids_str: str) -> tuple:
    """
    Normalize the Authors + Author IDs columns for a single paper row.
    
    For EACH author name:
    1. Flip reversed names ("Last, First" → "First Last")
    2. Match against known UNESA lecturers
    3. If matched → use canonical nama_norm + populate scopus_id/scholar_id
    
    Returns: (normalized_authors: str, enriched_author_ids: str)
    """
    if not authors_str or str(authors_str).lower() in ('nan', 'none', ''):
        return authors_str, author_ids_str
    
    # Parse existing author IDs (semicolon-separated)
    existing_ids = []
    if author_ids_str and str(author_ids_str).lower() not in ('nan', 'none', ''):
        existing_ids = [aid.strip().replace('.0', '') for aid in str(author_ids_str).replace(',', ';').split(';') if aid.strip()]
    
    # Parse author names
    raw_names = [n.strip() for n in str(authors_str).replace(',', ';').split(';') if n.strip()]
    
    # BUT: Scopus uses "Last, First" format with commas INSIDE names
    # Re-parse considering that pattern: "Yamasari, Y.; Imah, E.M."
    if ';' in str(authors_str):
        raw_names = [n.strip() for n in str(authors_str).split(';') if n.strip()]
    
    new_names = []
    new_ids = []
    
    for idx, name in enumerate(raw_names):
        if not name:
            continue
        
        match = _match_name_to_lecturer(name)
        
        if match['matched']:
            # 1. Canonical names (No abbreviation, full name!)
            if match['name'] not in new_names:
                new_names.append(match['name'])
            
            # 2. Robust ID Assignment
            # Priority: Scholar ID (per user request) -> Scopus ID -> Anything else.
            # We explicitly skip using the 'idx' to index 'existing_ids' because
            # raw data often has mismatched counts (e.g. 6 authors, 1 ID).
            lecturer_id = match.get('scholar_id') or match.get('scopus_id')
            
            if lecturer_id and lecturer_id not in new_ids:
                new_ids.append(lecturer_id)
        else:
            # User specifically wants: "hanya dosen infokom saja yang d matching"
            # So we intentionally DO NOT append unmatched authors or their IDs.
            pass

    # Safety fallback: if no lecturers matched (e.g. edge case in name parsing),
    # we don't want an empty string. Fallback to original raw names.
    if not new_names:
        new_names = [n.strip() for n in raw_names if n.strip()]
        new_ids = existing_ids

    # Final string formatting
    final_authors = "; ".join(new_names)
    final_ids = "; ".join(new_ids)
    
    return final_authors, final_ids


def clean_papers_batch(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans all text-heavy columns in the papers dataframe.
    Also applies ID-safe cleaning to Author IDs and DOI.
    Includes author name normalization and multi-ID enrichment.
    """
    print(f"🧹 Starting data cleaning for {len(df)} records...")
    
    dirty_columns = ['Title', 'Abstract', 'Keywords', 'Journal', 'TLDR']
    
    for col in dirty_columns:
        if col in df.columns:
            # Count how many had leading/trailing spaces or multiple spaces
            before_empty = (df[col].astype(str).str.strip() == '').sum()
            
            df[col] = df[col].apply(clean_text)
            
            # Post-clean: fix empty lists looking like '[]' or 'None'
            df[col] = df[col].replace({'None': '', '[]': '', 'nan': '', 'NaN': ''})
            
            after_empty = (df[col] == '').sum()
            if after_empty > before_empty:
                print(f"   🧼 Column {col}: cleaned {after_empty - before_empty} trash entries into empty strings.")

    # Specific formatting rules:
    # 1. Keywords: lowercase, remove trailing commas
    if 'Keywords' in df.columns:
        df['Keywords'] = df['Keywords'].str.lower().str.strip(',')
        # Remove consecutive commas (e.g., "AI,, Machine Learning")
        df['Keywords'] = df['Keywords'].apply(lambda x: re.sub(r',+', ',', str(x)).strip(','))

    # 2. ID-safe columns: strip .0, convert nan to empty
    id_columns = ['Author IDs', 'author_ids', 'DOI', 'doi', 'scopus_id', 'scholar_id', 'sinta_id']
    for col in id_columns:
        if col in df.columns:
            df[col] = df[col].apply(clean_id_value)

    # 3. AUTHORS NORMALIZATION: Flip names + match to lecturers + enrich IDs
    if 'Authors' in df.columns:
        print("👩‍🏫 Normalizing author names & enriching Author IDs...")
        matched_count = 0
        total_authors = 0
        
        for idx, row in df.iterrows():
            authors_str = str(row.get('Authors', '')).strip()
            author_ids_str = str(row.get('Author IDs', '')).strip()
            
            if not authors_str or authors_str.lower() in ('nan', 'none', ''):
                continue
            
            new_authors, new_ids = _normalize_authors_and_ids(authors_str, author_ids_str)
            
            df.at[idx, 'Authors'] = new_authors
            if 'Author IDs' in df.columns:
                df.at[idx, 'Author IDs'] = new_ids
            
            # Count matches  
            old_names = [n.strip() for n in str(authors_str).split(';') if n.strip()]
            new_names = [n.strip() for n in str(new_authors).split(';') if n.strip()]
            total_authors += len(old_names)
            for old, new in zip(old_names, new_names):
                if old != new:
                    matched_count += 1
        
        print(f"   ✅ Normalized {matched_count}/{total_authors} author names to canonical lecturer names")

    print("✅ Data cleaning complete. No more messy whitespaces/newlines.")
    return df

