from __future__ import annotations

import hashlib
import re
from typing import Optional

def generate_paper_id(doi: Optional[str], title: str, year: Optional[int]) -> str:
    """
    Generate a deterministic MD5 hash for a paper to serve as a unique identifier.
    
    Priority Logic:
    1. If DOI exists and is valid, hash the normalized DOI.
    2. Otherwise, hash a combination of the normalized Title and Year.
    
    This ensures consistency across different data sources (PostgreSQL, Neo4j, Milvus)
    and prevents duplicate entries for the same publication.
    
    Args:
        doi: Digital Object Identifier string.
        title: Title of the paper.
        year: Publication year.
        
    Returns:
        A 32-character hexadecimal MD5 hash string.
    """
    if doi and str(doi).strip().lower() not in ('nan', 'none', '', 'null'):
        # Normalize DOI to lowercase and strip whitespace
        normalized_doi = str(doi).strip().lower()
        unique_string = f"doi:{normalized_doi}"
    else:
        # Clean title: alphanumeric only, lowercase
        clean_title = re.sub(r'[^a-z0-9]', '', str(title).lower())
        year_str = str(year).strip() if year is not None else 'unknown'
        unique_string = f"title:{clean_title}_year:{year_str}"
        
    return hashlib.md5(unique_string.encode('utf-8')).hexdigest()
