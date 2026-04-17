import hashlib
import re

def generate_paper_id(doi: str, title: str, year: int) -> str:
    """
    Generate a Deterministic Hash (MD5) for a paper.
    If DOI exists, hash the DOI. Else, hash Title + Year.
    This guarantees that PostgreSQL and Neo4j use the exact same UUID 
    for the exact same paper, preventing diverge states.
    """
    if doi and str(doi).strip() not in ('nan', 'none', ''):
        unik = f"doi:{str(doi).strip().lower()}"
    else:
        clean_title = re.sub(r'[^a-zA-Z0-9]', '', str(title).lower())
        unik = f"title:{clean_title}_year:{str(year).strip() if year else 'None'}"
        
    return hashlib.md5(unik.encode('utf-8')).hexdigest()
