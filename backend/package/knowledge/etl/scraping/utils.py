# scraping_modules/utils.py
import re
import math
import pandas as pd
import numpy as np
import unicodedata
from difflib import SequenceMatcher
from knowledge.etl.scraping.config import PREFIX_TITLES

def clean_name_expert(name):
    """
    Intelligent Name Cleaner (Logic over Hardcoding).
    1. Suffix Removal: Split by first comma (,) -> Take the first part.
    2. Prefix Removal: Iteratively remove known PREFIX titles from the front.
    """
    if not name or pd.isna(name): return ""
    name = str(name).strip('"\'')
    
    # LOGIC 1: Suffix Removal
    if ',' in name:
        name = name.split(',')[0].strip()
        
    # LOGIC 2: Prefix Removal
    tokens = name.split()
    while tokens:
        first_word = tokens[0]
        check_word = first_word.replace('.', '').lower()
        
        if check_word in PREFIX_TITLES:
            tokens.pop(0) 
        else:
            break 
            
    return " ".join(tokens).strip()

def normalize_name(name):
    """
    Normalization for MATCHING (Cleaned -> Lowercased).
    """
    if not name: return ""
    
    # 1. Clean first
    name = clean_name_expert(name)
    
    # 2. Lowercase & Standardize Noise
    name = name.lower().strip()
    name = re.sub(r"[''`]", '', name)
    name = re.sub(r'[.,;()\[\]]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    
    # 3. ASCII Normalization
    try:
        name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    except: pass
            
    return name

def fuzzy_match_name(name_a, name_b, threshold=0.85):
    """
    Robust Fuzzy Matching Logic.
    """
    norm_a = normalize_name(name_a)
    norm_b = normalize_name(name_b)
    
    if not norm_a or not norm_b: return False, 0.0, "empty"
    if norm_a == norm_b: return True, 1.0, "exact"
    
    # Substring check
    if len(norm_a) > 5 and len(norm_b) > 5:
        if norm_a in norm_b or norm_b in norm_a: return True, 1.0, "contain"
    
    # Sequence Matcher
    seq_ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
    if seq_ratio >= threshold: return True, seq_ratio, "sequence"
    
    # Token Set Ratio
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    union = tokens_a | tokens_b
    token_ratio = len(tokens_a & tokens_b) / len(union) if union else 0
    if token_ratio >= threshold: return True, token_ratio, "token_set"
    
    # Sorted Token Match
    sorted_a = ' '.join(sorted(norm_a.split()))
    sorted_b = ' '.join(sorted(norm_b.split()))
    sorted_ratio = SequenceMatcher(None, sorted_a, sorted_b).ratio()
    if sorted_ratio >= threshold: return True, sorted_ratio, "sorted"
    
    best_score = max(seq_ratio, token_ratio, sorted_ratio)
    return False, best_score, "none"

def extract_ids_from_links(links):
    """
    Extracts Scholar, Scopus, Sinta, and NIP from a list of <a> tags.
    """
    scholar = scopus = sinta = nip = None
    for a in links:
        h = a.get('href', '')
        if 'scholar.google' in h:
            m = re.search(r'user=([A-Za-z0-9_-]+)', h)
            if m: scholar = m.group(1)
        if 'scopus.com/authid' in h:
            m = re.search(r'authorId=(\d+)', h)
            if m: scopus = m.group(1)
        if 'sinta.kemdikbud' in h or 'sinta.kemdiktisaintek' in h:
            m = re.search(r'/authors/(?:detail\?id=|profile/)(\d+)', h)
            if m: sinta = m.group(1)
        m_nip = re.search(r'cv\.unesa\.ac\.id/detail/(\d+)', h)
        if m_nip: nip = m_nip.group(1)
    return scholar, scopus, sinta, nip

def make_entry(nama_raw, nip=None, nidn=None, scholar=None, scopus=None, sinta=None):
    """
    Creates a standardized dictionary entry for a lecturer.
    All IDs are immediately cleaned to TEXT or None via clean_identifier.
    """
    if not nama_raw: return {}
    
    # 1. Pre-clean scholar (may have = prefix from CSV)
    if scholar:
        scholar = str(scholar).lstrip('=').replace('"', '').replace("'", "")
    
    # 2. Clean Name
    nama_clean_val = str(nama_raw).replace('"', '').replace("'", "").strip()
    
    # 3. Generate Norm
    nama_norm = clean_name_expert(nama_clean_val)
    
    return {
        'nama_dosen': nama_clean_val,   
        'nama_norm': nama_norm,           
        'nama_original': nama_clean_val, 
        'nip': clean_identifier(nip),
        'nidn': clean_identifier(nidn),
        'scholar_id': clean_identifier(scholar),
        'scopus_id': clean_identifier(scopus),
        'sinta_id': clean_identifier(sinta),
    }


def clean_identifier(text):
    """
    Cleans ID values to clean TEXT string or None.
    Handles: float NaN, numpy types, string 'None'/'nan'/'check', 
    .0 suffix, inf/-inf. Returns str or None, NEVER float.
    """
    # 1. Handle None/NaN/NaT types directly
    if text is None:
        return None
    
    # Handle numpy/pandas NA types
    try:
        if pd.isna(text):
            return None
    except (ValueError, TypeError):
        pass
    
    # Handle numpy numeric types (int64, float64, etc.)
    if isinstance(text, (np.integer,)):
        return str(int(text))
    if isinstance(text, (float, np.floating)):
        if math.isnan(text) or math.isinf(text):
            return None
        # Convert float to int-string if it's a whole number (e.g. 57201351214.0)
        if text == int(text):
            return str(int(text))
        return str(text)
    
    # 2. Convert to string and clean
    t = str(text).strip()
    
    # 3. Check for known garbage values
    if t.lower() in ('nan', 'none', 'null', '', 'nat', 'check', 'inf', '-inf'):
        return None
    
    # 4. Remove .0 suffix for IDs like "57201351214.0"
    if re.match(r'^\d+\.0$', t):
        t = t[:-2]
    
    # 5. Final empty check
    if not t:
        return None
    
    return t


def enforce_strict_types(df, id_columns=None):
    """
    Holistic cleaning for DataFrame. Converts ALL ID columns to clean
    TEXT strings or None. Call this before ANY DB operation or CSV save.
    """
    if id_columns is None:
        id_columns = ['nip', 'nidn', 'scholar_id', 'scopus_id', 'sinta_id']
    
    for col in id_columns:
        if col in df.columns:
            # 1. Convert to object to avoid pandas dtype issues
            df[col] = df[col].astype(object)
            
            # 2. Apply clean_identifier to every value
            df[col] = df[col].apply(clean_identifier)
            
            # 3. Belt-and-suspenders: replace any leftover NaN
            df[col] = df[col].where(df[col].notna(), None)
            
    return df


def save_final_csv(df, path, label=""):
    """
    Unified CSV save with automatic ID enforcement and QUOTE_ALL.
    Single source of truth for all pipeline saves — ensures every CSV
    output is clean, consistent, and ready for downstream consumption.
    
    Args:
        df: DataFrame to save
        path: Path to save to
        label: Optional label for the print message
        
    Returns:
        Cleaned DataFrame (after enforce_strict_types)
    """
    import csv
    
    # 1. Enforce strict types on all ID columns
    df = enforce_strict_types(df)
    
    # 2. Save with QUOTE_ALL for clean text representation
    df.to_csv(path, index=False, quoting=csv.QUOTE_ALL)
    
    msg = f"Saved: {path.name} ({len(df)} records)"
    if label:
        msg = f"{label} | {msg}"
    print(f"   💾 {msg}")
    
    return df
