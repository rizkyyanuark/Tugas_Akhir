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
        
    import html
    # Tolak ukur awal: kembalikan entitas HTML (seperti &#x0D;, &amp;) ke bentuk aslinya
    text = html.unescape(text)
    
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


def clean_abstract_text(text: str) -> str:
    """Apply deep noise removal specifically for abstracts (removes Abstrak-, trailing keywords)."""
    if not text: return ""
    c = str(text)
    # 1. Hapus noise awalan
    c = re.sub(r'^\s*(?i:abstract|abstrak)[\s\-—–:.]+[\s]*', '', c)
    # 2. Hapus keyword di ekor
    c = re.sub(r'(?i)\s*(?:kata\s+kunci|keywords?|key\s+words?|subject\s+terms?|index\s+terms?)[\s:\-—–\.].*$', '', c, flags=re.DOTALL)
    # 3. Clean general HTML/whitespaces
    return clean_text(c)


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


# ─── Dual-Indexed Lecturer Database ──────────────────────────────
# Two singletons:
#   _lec_by_name:  {normalized_name: entry}  → for name-based matching
#   _lec_by_sid:   {scholar_id: entry}       → for ID-based matching
_lec_by_name = None
_lec_by_sid = None

def _load_lecturer_db():
    """Load lecturer data into dual-indexed maps. Called once (singleton)."""
    global _lec_by_name, _lec_by_sid
    if _lec_by_name is not None:
        return _lec_by_name, _lec_by_sid

    _lec_by_name = {}
    _lec_by_sid = {}
    
    csv_paths = [
        Path("/opt/airflow/notebooks/scraping/file_tabulars/dosen_infokom_final.csv"),
        Path(__file__).resolve().parent.parent.parent.parent / "notebooks" / "scraping" / "file_tabulars" / "dosen_infokom_final.csv",
        Path(__file__).resolve().parent.parent.parent.parent / "data" / "raw" / "dosen_infokom_final.csv",
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
                    
                    # --- Index 1: By normalized name (for name-based matching) ---
                    clean_norm = _normalize_name_for_matching(norm) if (norm and norm != 'nan') else _normalize_name_for_matching(nama)
                    if clean_norm:
                        _lec_by_name[clean_norm] = entry
                    
                    # --- Index 2: By scholar_id (for ID-based matching) ---
                    if scholar_id and scholar_id != 'nan':
                        _lec_by_sid[scholar_id] = entry
                    
                    # --- Index 3: By scopus_id ---
                    if scopus_id and scopus_id != 'nan':
                        _lec_by_sid[scopus_id] = entry
                
                print(f"✅ Lecturer DB loaded: {len(_lec_by_name)} names, {len(_lec_by_sid)} IDs")
                break
            except Exception as e:
                print(f"⚠️ Could not load lecturer CSV: {e}")
    
    return _lec_by_name, _lec_by_sid


# Legacy alias for backward compatibility
def _load_cleaner_lecturer_map() -> dict:
    name_map, _ = _load_lecturer_db()
    return name_map


def _match_name_to_lecturer(author_name: str, threshold: float = 0.75) -> dict:
    """Match a single author name against known lecturers.
    
    Priority order:
      1. Exact normalized name match ONLY.
         Fuzzy matching has been DISABLED due to false positives
         (e.g. MW Aditya -> Aditya C.H.) per user request.
    
    Returns: {'name': str, 'scopus_id': str, 'scholar_id': str, 'matched': bool}
    """
    lec_map, _ = _load_lecturer_db()
    if not lec_map:
        return {'name': author_name, 'matched': False}
    
    flipped = _flip_author_name(author_name)
    norm = _normalize_name_for_matching(flipped)
    
    if not norm:
        return {'name': author_name, 'matched': False}
    
    # Strategy 1: Exact match ONLY
    if norm in lec_map:
        entry = lec_map[norm]
        return {'name': entry['nama_norm'], 'scopus_id': entry['scopus_id'],
                'scholar_id': entry['scholar_id'], 'matched': True}
    
    # Strategy 2: Initial + Surname matching (e.g. "rdi puspitasari" -> "ratih dian i p")
    abbr_parts = norm.split()
    if len(abbr_parts) >= 2:
        abbr_last = abbr_parts[-1]
        abbr_inits = "".join(abbr_parts[:-1]).replace(".", "")
        
        # Cari kecocokan di seluruh database dosen
        for db_norm, entry in lec_map.items():
            db_parts = db_norm.split()
            if len(db_parts) >= 2:
                db_last = db_parts[-1]
                # Ambil huruf pertama dari setiap kata (kecuali kata terakhir) sebagai inisial
                db_inits = "".join([p[0] for p in db_parts[:-1]])
                
                # Check last name: exact match or abbreviation (e.g. "p" vs "puspitasari")
                last_name_match = (
                    (db_last == abbr_last) or 
                    (len(db_last) == 1 and abbr_last.startswith(db_last)) or
                    (len(abbr_last) == 1 and db_last.startswith(abbr_last))
                )
                
                if last_name_match and (db_inits.startswith(abbr_inits) or abbr_inits.startswith(db_inits)):
                    return {'name': entry['nama_norm'], 'scopus_id': entry['scopus_id'],
                            'scholar_id': entry['scholar_id'], 'matched': True}

    return {'name': flipped, 'matched': False}


def _normalize_authors_and_ids(authors_str: str, author_ids_str: str, 
                                paper_scholar_id: str = "", paper_dosen: str = "") -> tuple:
    """
    Hybrid Author Matching System.
    
    Converts abbreviated Scholar names ("EM Imah, A Prapanca") into full names
    ("Elly Matul Imah, Aditya Prapanca") and populates Author IDs.
    DISCARDS any author that does not match the database.
    
    Returns: (normalized_authors: str, enriched_author_ids: str) joined by commas.
    """
    if not authors_str or str(authors_str).lower() in ('nan', 'none', ''):
        return authors_str, author_ids_str
    
    lec_by_name, lec_by_sid = _load_lecturer_db()
    
    # --- Parse author names (handle both comma and semicolon separators) ---
    raw_authors_str = str(authors_str)
    # Remove the trailing '...' if Scholar truncated it
    raw_authors_str = re.sub(r'\.\.\.$', '', raw_authors_str).strip()
    
    if ';' in raw_authors_str:
        raw_names = [n.strip() for n in raw_authors_str.split(';') if n.strip()]
    else:
        raw_names = [n.strip() for n in raw_authors_str.split(',') if n.strip()]
    
    # --- Priority 1: Identify the "owner" dosen via scholar_id ---
    owner_entry = None
    paper_sid = str(paper_scholar_id).strip() if paper_scholar_id else ""
    if paper_sid and paper_sid not in ('', 'nan', 'None') and paper_sid in lec_by_sid:
        owner_entry = lec_by_sid[paper_sid]
    
    # --- Process each author name ---
    final_names = []
    final_ids = []
    
    # FORCE INJECT PROFILE OWNER FIRST
    # Google Scholar explicitly truncates long author lists with "...", which often cuts off
    # the actual profile owner we scraped this from! By injecting them forcefully, we guarantee 
    # they are not randomly lost.
    if owner_entry:
        owner_name = owner_entry.get('nama_norm', '')
        owner_id = owner_entry.get('scholar_id') or owner_entry.get('scopus_id') or ''
        if owner_name:
            final_names.append(owner_name)
        if owner_id:
            final_ids.append(owner_id)
            
    for raw_name in raw_names:
        if not raw_name or raw_name == '...':
            continue
        
        matched_entry = None
        
        # Priority 1: If this abbreviated name matches the profile owner's initials,
        # directly assign the owner (we KNOW they authored this paper since it's on their profile)
        if owner_entry:
            owner_norm = _normalize_name_for_matching(owner_entry['nama_norm'])
            abbr_norm = _normalize_name_for_matching(_flip_author_name(raw_name))
            
            if owner_norm and abbr_norm:
                # Check if abbreviated name matches owner via initials
                abbr_parts = abbr_norm.split()
                owner_parts = owner_norm.split()
                
                if abbr_norm == owner_norm:
                    matched_entry = owner_entry
                elif len(abbr_parts) >= 2 and len(owner_parts) >= 2:
                    abbr_last = abbr_parts[-1]
                    abbr_inits = "".join(abbr_parts[:-1]).replace(".", "")
                    owner_inits = "".join([p[0] for p in owner_parts[:-1]])
                    
                    last_name_match_owner = (
                        (owner_parts[-1] == abbr_last) or 
                        (len(owner_parts[-1]) == 1 and abbr_last.startswith(owner_parts[-1])) or
                        (len(abbr_last) == 1 and owner_parts[-1].startswith(abbr_last))
                    )
                    
                    if last_name_match_owner and (owner_inits.startswith(abbr_inits) or abbr_inits.startswith(owner_inits)):
                        matched_entry = owner_entry
        
        # Priority 2: General name-based matching against ALL lecturers
        if not matched_entry:
            result = _match_name_to_lecturer(raw_name)
            if result['matched']:
                matched_entry = {
                    'nama_norm': result['name'],
                    'scholar_id': result.get('scholar_id', ''),
                    'scopus_id': result.get('scopus_id', ''),
                }
        
        # --- Append result ONLY if matched (Discard non-Infokom authors) ---
        if matched_entry:
            full_name = matched_entry['nama_norm']
            lecturer_id = matched_entry.get('scholar_id') or matched_entry.get('scopus_id') or ''
            
            if full_name and full_name not in final_names:
                final_names.append(full_name)
            # Selalu masukkan ID meskipun kosong agar sejalan dengan urutan nama (opsional)
            # Namun kita cukup mengisi ID valid atau kosong. Scholar kadang tidak butuh sejajar per nama.
            if lecturer_id and lecturer_id not in final_ids:
                final_ids.append(lecturer_id)
        else:
            # DISCARD: Do not append unmatched raw authors
            pass
    
    return ", ".join(final_names), ", ".join(final_ids)


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
    # 0. Abstract: Deep Clean Noise (Abstrak—, trailing Keywords)
    if 'Abstract' in df.columns:
        df['Abstract'] = df['Abstract'].apply(clean_abstract_text)

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
            paper_sid = str(row.get('scholar_id', '')).strip()
            paper_dosen = str(row.get('dosen', '')).strip()
            
            if not authors_str or authors_str.lower() in ('nan', 'none', ''):
                continue
            
            new_authors, new_ids = _normalize_authors_and_ids(
                authors_str, author_ids_str,
                paper_scholar_id=paper_sid, paper_dosen=paper_dosen
            )
            
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

