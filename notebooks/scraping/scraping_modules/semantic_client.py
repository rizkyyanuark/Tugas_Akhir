import requests
import time
import re
import pandas as pd
from difflib import SequenceMatcher
from .config import SAVE_DIR

import sys
from pathlib import Path

try:
    from ta_backend_core.knowledge.etl.transform import cleaner
except ImportError as e:
    print(f"⚠️ Could not import ETL cleaner: {e}")
    cleaner = None

def _deep_clean_abstract(text):
    if not text: return ""
    import re
    cleaned = str(text).strip()
    # Hapus noise awalan seperti "Abstrak—", "Abstract:" walau ada spasi di awal
    cleaned = re.sub(r'^\s*(?i:abstract|abstrak)[\s\-—–:.]+[\s]*', '', cleaned)
    # Hapus blok "Kata Kunci - ..." yang nyangkut di akhir abstract
    cleaned = re.sub(r'(?i)\s*(?:kata\s+kunci|keywords?|key\s+words?|subject\s+terms?|index\s+terms?)[\s:\-—–\.].*$', '', cleaned, flags=re.DOTALL)
    
    return cleaner.clean_text(cleaned) if cleaner else cleaned.strip()

def _normalize_text(text):
    if not text or not isinstance(text, str): return ""
    return re.sub(r'[^a-z0-9]', '', text.lower())

# Free API key (or None)
API_KEY = "ZWTWpCL5EUX02DYSdts74tkVSEyToXQ6T5Vyak00"
BASE_URL = "https://api.semanticscholar.org/graph/v1"
HEADERS = {'x-api-key': API_KEY} if API_KEY else {}

class SemanticScholarClient:
    def __init__(self):
        self.headers = HEADERS
        self.base_url = BASE_URL
        # Proxies removed as requested for direct API usage
        self.proxies = None 

    def search_paper_id(self, title):
        """Search for a paper by title and return the first result's paperId if it matches closely."""
        if not title or len(str(title)) < 5: return None
        
        url = f"{self.base_url}/paper/search"
        params = {
            'query': title,
            'limit': 3,  # Fetch a few to find the best match
            'fields': 'paperId,title'
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json().get('data', [])
                for item in data:
                    returned_title = item.get('title', '')
                    if returned_title:
                        similarity = SequenceMatcher(None, _normalize_text(title), _normalize_text(returned_title)).ratio()
                        if similarity >= 0.85:  # Strict match threshold
                            # print(f"      [S2] Match found ({similarity:.2f}): {returned_title[:50]}...")
                            return item['paperId']
                if data:
                    print(f"      ⚠️ [S2] No strict match found. Best was '{data[0].get('title', '')[:50]}...'")
            elif response.status_code == 429:
                print("      ⚠️ Rate Limit (429). Sleeping 5s...")
                time.sleep(5)
        except Exception as e:
            print(f"      ⚠️ S2 Search Error: {e}")
        return None

    def get_paper_details(self, paper_id):
        """Get details (tldr, abstract, externalIds, url, publicationTypes) for a given paperId."""
        if not paper_id: return None
        
        url = f"{self.base_url}/paper/{paper_id}"
        # Fetch comprehensive metadata as requested by user
        params = {
            'fields': 'title,tldr,abstract,externalIds,url,openAccessPdf,publicationTypes,year,venue'
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("abstract"):
                    data["abstract"] = _deep_clean_abstract(data["abstract"])
                return data
            elif response.status_code == 429:
                time.sleep(5)
                # Retry once
                response = requests.get(url, headers=self.headers, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("abstract"):
                        data["abstract"] = _deep_clean_abstract(data["abstract"])
                    return data
        except: pass
        return None

def fetch_s2_details(doi=None, title=None):
    """Convenience function to fetch S2 details by DOI or Title."""
    client = SemanticScholarClient()
    paper_id = None
    
    if doi:
        url = f"{BASE_URL}/paper/DOI:{doi}"
        try:
            resp = requests.get(url, headers=HEADERS, params={'fields': 'paperId'}, timeout=10)
            if resp.status_code == 200:
                paper_id = resp.json().get('paperId')
        except: pass
        
    if not paper_id and title:
        paper_id = client.search_paper_id(title)
        
    if paper_id:
        return client.get_paper_details(paper_id)
        
    return None

def fetch_tldr(doi=None, title=None):
    """Legacy wrapper just for TLDR."""
    details = fetch_s2_details(doi=doi, title=title)
    if details and details.get('tldr'):
        return details['tldr'].get('text')
    return None

