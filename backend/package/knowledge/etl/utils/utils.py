from __future__ import annotations

import re
import math
import logging
import csv
import unicodedata
from typing import List, Tuple, Optional, Dict, Any, Union, Set
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
import numpy as np

from ..config import PREFIX_TITLES
from .storage import path_name, write_dataframe_csv

logger = logging.getLogger(__name__)

def clean_lecturer_name(name: Union[str, float]) -> str:
    """
    Intelligent Name Cleaner for lecturers.
    
    Logic:
    1. Suffix Removal: Splits by the first comma (,) and takes the first part.
    2. Prefix Removal: Iteratively removes known academic titles from the front.
    
    Args:
        name: The raw name string or potential NaN.
        
    Returns:
        str: A cleaned, stripped name string.
    """
    if not name or pd.isna(name):
        return ""
    
    name_str = str(name).strip('"\'').strip()
    
    # Logic 1: Suffix Removal (Degrees like M.Kom, Ph.D)
    if ',' in name_str:
        name_str = name_str.split(',')[0].strip()
        
    # Logic 2: Prefix Removal (Titles like Prof, Dr)
    tokens = name_str.split()
    while tokens:
        first_word = tokens[0]
        # Clean word for comparison (remove dots and lowercase)
        check_word = first_word.replace('.', '').lower()
        
        if check_word in PREFIX_TITLES:
            tokens.pop(0) 
        else:
            break 
            
    return " ".join(tokens).strip()

def normalize_name(name: str) -> str:
    """
    Normalization for string matching (Cleaned -> Lowercased -> ASCII).
    
    Args:
        name: The cleaned name string.
        
    Returns:
        A normalized string suitable for comparison.
    """
    if not name:
        return ""
    
    # 1. Basic cleanup
    name = clean_lecturer_name(name)
    
    # 2. Lowercase & Standardize Noise
    name = name.lower().strip()
    name = re.sub(r"[''`]", '', name)
    name = re.sub(r'[.,;()\[\]]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    
    # 3. ASCII Normalization (Remove diacritics)
    try:
        name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    except Exception:
        # Fallback if normalization fails
        pass
            
    return name

def fuzzy_match_name(name_a: str, name_b: str, threshold: float = 0.85) -> Tuple[bool, float, str]:
    """
    Robust fuzzy matching logic between two names.
    
    Args:
        name_a: First name to compare.
        name_b: Second name to compare.
        threshold: Similarity threshold (0.0 to 1.0).
        
    Returns:
        A tuple of (is_match, score, match_type).
    """
    norm_a = normalize_name(name_a)
    norm_b = normalize_name(name_b)
    
    if not norm_a or not norm_b:
        return False, 0.0, "empty"
    
    if norm_a == norm_b:
        return True, 1.0, "exact"
    
    # Substring check for longer names
    if len(norm_a) > 5 and len(norm_b) > 5:
        if norm_a in norm_b or norm_b in norm_a:
            return True, 1.0, "contain"
    
    # Sequence Matcher (Levenshtein-like)
    seq_ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
    if seq_ratio >= threshold:
        return True, seq_ratio, "sequence"
    
    # Token Set Ratio (Jaccard similarity on words)
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    union = tokens_a | tokens_b
    token_ratio = len(tokens_a & tokens_b) / len(union) if union else 0
    if token_ratio >= threshold:
        return True, token_ratio, "token_set"
    
    # Sorted Token Match (Handles reversed names)
    sorted_a = ' '.join(sorted(norm_a.split()))
    sorted_b = ' '.join(sorted(norm_b.split()))
    sorted_ratio = SequenceMatcher(None, sorted_a, sorted_b).ratio()
    if sorted_ratio >= threshold:
        return True, sorted_ratio, "sorted"
    
    best_score = max(seq_ratio, token_ratio, sorted_ratio)
    return False, best_score, "none"

def extract_ids_from_links(links: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extracts identification strings from a list of link dictionaries (e.g., from BeautifulSoup).
    
    Args:
        links: List of dictionaries containing at least an 'href' key.
        
    Returns:
        tuple[str | None, str | None, str | None, str | None]: (scholar_id, scopus_id, sinta_id, nip).
    """
    scholar: Optional[str] = None
    scopus: Optional[str] = None
    sinta: Optional[str] = None
    nip: Optional[str] = None
    
    for a in links:
        href = a.get('href', '')
        if 'scholar.google' in href:
            match = re.search(r'user=([A-Za-z0-9_-]+)', href)
            if match:
                scholar = match.group(1)
        
        if 'scopus.com/authid' in href:
            match = re.search(r'authorId=(\d+)', href)
            if match:
                scopus = match.group(1)
                
        if 'sinta.kemdikbud' in href or 'sinta.kemdiktisaintek' in href:
            match = re.search(r'/authors/(?:detail\?id=|profile/)(\d+)', href)
            if match:
                sinta = match.group(1)
                
        match_nip = re.search(r'cv\.unesa\.ac\.id/detail/(\d+)', href)
        if match_nip:
            nip = match_nip.group(1)
            
    return scholar, scopus, sinta, nip

def make_lecturer_entry(
    name_raw: str, 
    nip: Optional[str] = None, 
    nidn: Optional[str] = None, 
    scholar: Optional[str] = None, 
    scopus: Optional[str] = None, 
    sinta: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a standardized dictionary entry for a lecturer.
    
    Args:
        name_raw: The raw name.
        nip, nidn, scholar, scopus, sinta: Various identification IDs.
        
    Returns:
        A dictionary with standardized keys and cleaned values.
    """
    if not name_raw:
        return {}
    
    # 1. Pre-clean scholar (may have = prefix from Excel/CSV auto-formatting)
    if scholar:
        scholar = str(scholar).lstrip('=').replace('"', '').replace("'", "")
    
    # 2. Clean Name
    name_val = str(name_raw).replace('"', '').replace("'", "").strip()
    
    # 3. Generate Normalized Name
    name_norm = clean_lecturer_name(name_val)
    
    return {
        'nama_dosen': name_val,   
        'nama_norm': name_norm,           
        'nama_original': name_val, 
        'nip': clean_identifier(nip),
        'nidn': clean_identifier(nidn),
        'scholar_id': clean_identifier(scholar),
        'scopus_id': clean_identifier(scopus),
        'sinta_id': clean_identifier(sinta),
    }

def clean_identifier(text: Any) -> Optional[str]:
    """
    Cleans identification values into standardized strings or None.
    
    Handles:
    - Null-like values (NaN, None, empty strings, garbage strings like 'check').
    - Numeric values (floats with .0 suffix, large integers).
    - Scientific notation or infinity.
    
    Args:
        text: Any input that should represent an ID.
        
    Returns:
        A cleaned string or None.
    """
    if text is None:
        return None
    
    # Handle pandas/numpy NA types
    try:
        if pd.isna(text):
            return None
    except (ValueError, TypeError):
        pass
    
    # Handle numpy numeric types
    if isinstance(text, (np.integer,)):
        return str(int(text))
    
    if isinstance(text, (float, np.floating)):
        if math.isnan(text) or math.isinf(text):
            return None
        # Convert float to int-string if it's a whole number
        if text == int(text):
            return str(int(text))
        return str(text)
    
    # Convert to string and strip whitespace
    val = str(text).strip()
    
    # Check for known garbage values
    if val.lower() in ('nan', 'none', 'null', '', 'nat', 'check', 'inf', '-inf'):
        return None
    
    # Remove .0 suffix often added by Excel or pandas CSV reading
    if re.match(r'^\d+\.0$', val):
        val = val[:-2]
    
    if not val:
        return None
    
    return val

def enforce_strict_ids(df: pd.DataFrame, id_columns: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Ensures all specified ID columns in a DataFrame are cleaned strings or None.
    
    Args:
        df: The DataFrame to process.
        id_columns: List of columns to clean. Defaults to standard lecturer IDs.
        
    Returns:
        The modified DataFrame.
    """
    if id_columns is None:
        id_columns = ['nip', 'nidn', 'scholar_id', 'scopus_id', 'sinta_id']
    
    for col in id_columns:
        if col in df.columns:
            # Convert to object to avoid pandas dtype constraints during processing
            df[col] = df[col].astype(object)
            df[col] = df[col].apply(clean_identifier)
            # Ensure consistent missing value representation
            df[col] = df[col].where(df[col].notna(), None)
            
    return df

def save_final_csv(df: pd.DataFrame, path: Union[str, Path], label: str = "") -> pd.DataFrame:
    """
    Unified method to save DataFrames to CSV with strict ID enforcement.
    
    Args:
        df: The DataFrame to save.
        path: Target file path.
        label: Contextual label for logging.
        
    Returns:
        The cleaned DataFrame that was saved.
    """
    # 1. Enforce strict types on all ID columns
    df = enforce_strict_ids(df)
    
    # 2. Save with QUOTE_ALL to prevent parsing issues with special characters in text
    write_dataframe_csv(df, path, index=False, quoting=csv.QUOTE_ALL)
    
    records_count = len(df)
    log_msg = f"Saved: {path_name(path)} ({records_count} records)"
    if label:
        logger.info(f"{label}: {log_msg}")
    else:
        logger.info(log_msg)
    
    return df
