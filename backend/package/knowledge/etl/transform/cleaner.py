from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import numpy as np
import pandas as pd
from pathlib import Path
from difflib import SequenceMatcher

from ..config import PREFIX_TITLES

if TYPE_CHECKING:
    from knowledge.etl.load.supabase_loader import SupabaseLoader

logger = logging.getLogger(__name__)


_MOJIBAKE_MARKERS = (
    "Ã",
    "Â",
    "â€",
    "â€“",
    "â€”",
    "â€™",
    "â€œ",
    "â€",
    "â€¦",
)

_MOJIBAKE_REPLACEMENTS = {
    "â€“": "–",
    "â€”": "—",
    "â€˜": "‘",
    "â€™": "’",
    "â€œ": "“",
    "â€�": "”",
    "â€¦": "…",
    "â€¢": "•",
    "â„¢": "™",
    "Â°": "°",
    "Â±": "±",
    "Â": "",
    "Ã—": "×",
    "ÃƒÂ—": "×",
    "Ãƒâ€”": "×",
}


def _mojibake_score(text: str) -> int:
    """Estimate whether text still contains UTF-8/Windows-1252 mojibake."""
    return sum(text.count(marker) for marker in _MOJIBAKE_MARKERS)


def repair_mojibake(text: Any) -> str:
    """Repair common UTF-8 text decoded through Windows-1252/Latin-1."""
    if not isinstance(text, str):
        return ""

    fixed = text
    if _mojibake_score(fixed) == 0:
        return fixed

    for _ in range(3):
        before = fixed
        best = fixed
        best_score = _mojibake_score(fixed)

        for encoding in ("cp1252", "latin1"):
            try:
                candidate = fixed.encode(encoding).decode("utf-8")
            except UnicodeError:
                continue

            candidate_score = _mojibake_score(candidate)
            if candidate_score < best_score:
                best = candidate
                best_score = candidate_score

        fixed = best
        if fixed == before:
            break

    for bad, good in _MOJIBAKE_REPLACEMENTS.items():
        fixed = fixed.replace(bad, good)

    return fixed


def clean_text(text: Any) -> str:
    """Apply aggressive regex cleaning to a single string."""
    if not isinstance(text, str) or pd.isna(text):
        return ""
        
    import html
    # Tolak ukur awal: kembalikan entitas HTML (seperti &#x0D;, &amp;) ke bentuk aslinya
    text = html.unescape(text)
    text = repair_mojibake(text)
    
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


def clean_abstract_text(text: Any) -> str:
    """Apply deep noise removal specifically for abstracts (removes Abstrak-, trailing keywords)."""
    if not text or pd.isna(text):
        return ""
    
    c = str(text)
    # 1. Hapus noise awalan (Case insensitive)
    c = re.sub(r'^\s*(?i:abstract|abstrak)[\s\-—–:.]+[\s]*', '', c)
    # 2. Hapus keyword di ekor
    c = re.sub(r'(?i)\s*(?:kata\s+kunci|keywords?|key\s+words?|subject\s+terms?|index\s+terms?)[\s:\-—–\.].*$', '', c, flags=re.DOTALL)
    # 3. Clean general HTML/whitespaces
    return clean_text(c)


def clean_id_value(val: Any) -> str:
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


# --- Author Name Normalization ---

def flip_author_name(name: str) -> str:
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
    if not name or pd.isna(name):
        return ""
    
    # 1. Basic cleanup
    name_str = str(name).strip('"\'').strip()
    
    # 2. Suffix Removal (Degrees like M.Kom, Ph.D)
    if ',' in name_str:
        name_str = name_str.split(',')[0].strip()
        
    # 3. Prefix Removal (Titles like Prof, Dr)
    tokens = name_str.split()
    while tokens:
        first_word = tokens[0]
        check_word = first_word.replace('.', '').lower()
        if check_word in PREFIX_TITLES:
            tokens.pop(0) 
        else:
            break 
    
    name = " ".join(tokens).strip().lower()
    
    # 4. Standardize Noise
    name = re.sub(r"[''`]", '', name)
    name = re.sub(r'[.,;()\[\]]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name

def is_abbreviation_match(serp_name: str, dosen_name: str) -> bool:
    """
    Advanced abbreviation matching logic (e.g., 'EM Imah' -> 'Elly Matul Imah').
    Ported from unesa_papers.py for centralization.
    """
    if not serp_name or not dosen_name:
        return False
        
    serp_name = serp_name.lower().strip()
    dosen_name = dosen_name.lower().strip()
    
    if serp_name == dosen_name: return True
    if serp_name.replace(' ', '') == dosen_name.replace(' ', ''): return True
    if SequenceMatcher(None, serp_name, dosen_name).ratio() > 0.85: return True
    
    s_tokens = serp_name.split()
    d_tokens = dosen_name.split()
    if not s_tokens or not d_tokens: return False
    
    def get_signature(tokens):
        sig = ''
        for t in tokens:
            if len(t) <= 3: sig += t
            else: sig += t[0]
        return sig
    
    s_sig_sorted = ''.join(sorted(get_signature(s_tokens)))
    d_sig_sorted = ''.join(sorted(get_signature(d_tokens)))
    
    if s_sig_sorted == d_sig_sorted:
        last_s = s_tokens[-1]
        last_d = d_tokens[-1]
        if len(last_s) > 2 and len(last_d) > 2:
            last_ratio = SequenceMatcher(None, last_s, last_d).ratio()
            if last_ratio < 0.5 and not last_s.startswith(last_d) and not last_d.startswith(last_s):
                pass
            else: return True
        else: return True
        
    serp_surname = s_tokens[-1]
    dosen_surname = d_tokens[-1]
    
    surname_ok = False
    if serp_surname == dosen_surname:
        surname_ok = True
    elif len(serp_surname) <= 2 or len(dosen_surname) <= 2:
        longer = serp_surname if len(serp_surname) > len(dosen_surname) else dosen_surname
        shorter = dosen_surname if len(serp_surname) > len(dosen_surname) else serp_surname
        if longer.startswith(shorter):
            if len(shorter) == 1:
                if s_tokens[0][0] == d_tokens[0][0] and len(s_tokens) >= 2 and len(d_tokens) >= 2 and len(longer) <= 4:
                    surname_ok = True
            else:
                surname_ok = True
    elif len(serp_surname) > 3 and serp_surname in d_tokens:
        if s_tokens[0][0] == d_tokens[0][0]:
            surname_ok = True
    
    if not surname_ok: return False
        
    serp_initials = [t[0] for t in s_tokens[:-1]]
    
    if serp_surname == dosen_surname:
        dosen_pre_surname = d_tokens[:-1]
    elif serp_surname in d_tokens:
        idx = d_tokens.index(serp_surname)
        dosen_pre_surname = d_tokens[:idx] + d_tokens[idx+1:]
    else:
        dosen_pre_surname = d_tokens[:-1]
    
    dosen_initials = [t[0] for t in dosen_pre_surname]
    
    di_copy = list(dosen_initials)
    all_found = True
    for si in serp_initials:
        if si in di_copy:
            di_copy.remove(si)
        else:
            all_found = False
            break
    
    return all_found


# --- Dual-Indexed Lecturer Database ---
# Two singletons:
#   _lec_by_name:  {normalized_name: entry}  → for name-based matching
#   _lec_by_sid:   {scholar_id: entry}       → for ID-based matching
_lec_by_name: Dict[str, Dict[str, str]] | None = None
_lec_by_sid: Dict[str, Dict[str, str]] | None = None


def _load_lecturer_db() -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, str]]]:
    """Load lecturer data into dual-indexed maps. Fetches from Supabase DB."""
    global _lec_by_name, _lec_by_sid
    if _lec_by_name is not None:
        return _lec_by_name, _lec_by_sid

    _lec_by_name = {}
    _lec_by_sid = {}
    
    from knowledge.etl.load.supabase_loader import SupabaseLoader
    try:
        loader = SupabaseLoader()
        response = loader.client.table("lecturers").select("nama_dosen, nama_norm, scopus_id, scholar_id").execute()
        
        for row in response.data:
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
            
            # --- Index 1: By normalized name ---
            clean_norm = _normalize_name_for_matching(norm) if (norm and norm != 'nan') else _normalize_name_for_matching(nama)
            if clean_norm:
                _lec_by_name[clean_norm] = entry
            
            # --- Index 2 & 3: By IDs ---
            if scholar_id and scholar_id != 'nan':
                _lec_by_sid[scholar_id] = entry
            if scopus_id and scopus_id != 'nan':
                _lec_by_sid[scopus_id] = entry
                
        logger.info(f"Lecturer DB loaded from Supabase: {len(_lec_by_name)} names, {len(_lec_by_sid)} IDs")
    except Exception as e:
        logger.warning(f"Could not load lecturer DB from Supabase: {e}")
    
    return _lec_by_name, _lec_by_sid


# Legacy alias for backward compatibility
def _load_cleaner_lecturer_map() -> dict:
    name_map, _ = _load_lecturer_db()
    return name_map


def _match_name_to_lecturer(author_name: str, threshold: float = 0.75) -> Dict[str, Any]:
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
    
    flipped = flip_author_name(author_name)
    norm = _normalize_name_for_matching(flipped)
    
    if not norm:
        return {'name': author_name, 'matched': False}
    
    # Strategy 1: Exact match ONLY
    if norm in lec_map:
        entry = lec_map[norm]
        return {'name': entry['nama_norm'], 'scopus_id': entry['scopus_id'],
                'scholar_id': entry['scholar_id'], 'matched': True}
    
    # Strategy 2: Abbreviation matching
    for db_norm, entry in lec_map.items():
        if is_abbreviation_match(norm, db_norm):
            return {
                'name': entry['nama_norm'], 
                'scopus_id': entry['scopus_id'],
                'scholar_id': entry['scholar_id'], 
                'matched': True
            }

    return {'name': flipped, 'matched': False}


def _normalize_authors_and_ids(authors_str: str, author_ids_str: str, 
                                paper_scholar_id: str = "", paper_dosen: str = "") -> Tuple[str, str]:
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
            abbr_norm = _normalize_name_for_matching(flip_author_name(raw_name))
            
            if owner_norm and abbr_norm:
                if is_abbreviation_match(abbr_norm, owner_norm):
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
    logger.info(f"Starting data cleaning for {len(df)} records...")
    
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
                logger.info(f"Column {col}: cleaned {after_empty - before_empty} trash entries into empty strings.")

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
        logger.info("Normalizing author names and enriching Author IDs...")
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
        
        logger.info(f"Normalized {matched_count}/{total_authors} authors to canonical lecturer names")

    logger.info("Data cleaning complete.")
    return df

