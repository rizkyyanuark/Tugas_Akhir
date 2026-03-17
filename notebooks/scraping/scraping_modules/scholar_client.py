
import os
import re
import time
import random
import requests
import pandas as pd
from urllib.parse import urlparse, parse_qs
from difflib import SequenceMatcher
from bs4 import BeautifulSoup


class ScholarVerificationClient:
    """
    Lightweight requests-based client for:
    1. Verifying Google Scholar IDs (fetch profile, match name)
    2. Searching Google for scholar profile IDs by lecturer name
    
    Uses Bright Data proxy to avoid IP blocks.
    """
    
    def __init__(self):
        from .config import PROXY_URL, HEADERS
        self.proxies = None
        if PROXY_URL:
            self.proxies = {
                'http': PROXY_URL,
                'https': PROXY_URL
            }
        self.headers = {
            'User-Agent': HEADERS['User-Agent'],
            'Accept-Language': 'en-US,en;q=0.9',
        }
        self._request_count = 0
    
    def _get(self, url, timeout=30, max_retries=3):
        """Make a proxied GET request with rate limiting and retry."""
        self._request_count += 1
        if self._request_count % 5 == 0:
            time.sleep(random.uniform(2, 4))
        else:
            time.sleep(random.uniform(0.5, 1.5))
        
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(
                    url, 
                    headers=self.headers, 
                    proxies=self.proxies, 
                    timeout=timeout,
                    allow_redirects=True,
                    verify=False
                )
                return resp
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    wait = attempt * 3
                    time.sleep(wait)
                else:
                    print(f"      ⚠️ Request failed after {max_retries} attempts: {type(e).__name__}")
                    return None
    
    def _normalize_name(self, name):
        """Strip titles and normalize for comparison."""
        from .utils import clean_name_expert
        return clean_name_expert(str(name)).lower().strip()
    
    def verify_id(self, scholar_id, expected_name):
        if not scholar_id or len(str(scholar_id).strip()) < 5:
            return {'valid': False, 'profile_name': '', 'score': 0}
        
        url = f"https://scholar.google.com/citations?user={scholar_id}&hl=en"
        resp = self._get(url)
        
        if resp is None:
            return None
        
        if resp.status_code != 200:
            return {'valid': False, 'profile_name': '', 'score': 0}
        
        if 'sorry' in resp.url or 'robot' in resp.text.lower()[:500]:
            print(f"      ⚠️ Captcha detected for {scholar_id}, retrying in 10s...")
            time.sleep(10)
            resp = self._get(url)
            if resp is None or 'sorry' in resp.url:
                return None
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        name_elem = soup.find(id='gsc_prf_in')
        if not name_elem:
            return {'valid': False, 'profile_name': '', 'score': 0}
        
        profile_name = name_elem.text.strip()
        norm_expected = self._normalize_name(expected_name)
        norm_profile = self._normalize_name(profile_name)
        score = SequenceMatcher(None, norm_expected, norm_profile).ratio()
        
        affiliation = ''
        aff_elem = soup.find(class_='gsc_prf_ila')
        if aff_elem:
            affiliation = aff_elem.text.strip().lower()
        
        threshold = 0.70
        if 'unesa' in affiliation or 'negeri surabaya' in affiliation:
            threshold = 0.60
        
        is_valid = score >= threshold
        
        return {
            'valid': is_valid,
            'profile_name': profile_name,
            'affiliation': affiliation,
            'score': score
        }
    
    def search_google(self, name, max_candidates=5):
        query = f'{name} site:scholar.google.com'
        url = f"https://www.google.com/search?q={requests.utils.quote(query)}&num=10"
        
        resp = self._get(url)
        if resp is None or resp.status_code != 200:
            return self._search_scholar_direct(name, max_candidates)
        
        candidates = set()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/url?q=' in href:
                href = href.split('/url?q=')[1].split('&')[0]
            
            sid = self._extract_scholar_id(href)
            if sid:
                candidates.add(sid)
                if len(candidates) >= max_candidates:
                    break
        
        if not candidates:
            return self._search_scholar_direct(name, max_candidates)
        
        return list(candidates)
    
    def _search_scholar_direct(self, name, max_candidates=5):
        url = f"https://scholar.google.com/citations?view_op=search_authors&mauthors={requests.utils.quote(name)}&hl=en"
        
        resp = self._get(url)
        if resp is None or resp.status_code != 200:
            return []
        
        candidates = set()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        for link in soup.find_all('a', href=True):
            sid = self._extract_scholar_id(link['href'])
            if sid:
                candidates.add(sid)
                if len(candidates) >= max_candidates:
                    break
        
        return list(candidates)
    
    def _extract_scholar_id(self, url):
        if 'scholar.google' not in str(url) and 'citations' not in str(url):
            return None
        try:
            parsed = urlparse(str(url))
            params = parse_qs(parsed.query)
            user = params.get('user', [None])[0]
            if user and len(user) >= 8:
                return user
        except:
            pass
        
        match = re.search(r'user=([A-Za-z0-9_-]{8,})', str(url))
        if match:
            return match.group(1)
        return None


class ScholarPaperClient:
    """
    Bright Data proxy-based client for fetching papers from Google Scholar.
    Uses requests + BeautifulSoup (no Selenium).
    
    NOTE: Requires active Bright Data account with credit.
    For temporary alternative, use SerpApi directly in notebook.
    """
    
    def __init__(self):
        from .config import PROXY_URL, HEADERS
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        self.proxies = None
        if PROXY_URL:
            self.proxies = {
                'http': PROXY_URL,
                'https': PROXY_URL
            }
        self.headers = {
            'User-Agent': HEADERS['User-Agent'],
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        self._request_count = 0

    def _get(self, url, timeout=30, max_retries=3):
        """Make a proxied GET request with rate limiting and retry."""
        self._request_count += 1
        if self._request_count % 5 == 0:
            time.sleep(random.uniform(3, 5))
        else:
            time.sleep(random.uniform(1, 2))
        
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(
                    url, 
                    headers=self.headers, 
                    proxies=self.proxies, 
                    timeout=timeout,
                    verify=False
                )
                if resp.status_code == 200:
                    return resp
                elif resp.status_code == 429:
                    print(f"      ⚠️ Rate limited (429). Sleeping 20s...")
                    time.sleep(20)
                else:
                    print(f"      ⚠️ Status {resp.status_code} for {url}")
            except Exception as e:
                print(f"      ⚠️ Request error: {e}")
                
            time.sleep(attempt * 3)
            
        return None
    
    def get_papers(self, scholar_id, limit=200):
        """Fetch papers from a Scholar profile page using pagination."""
        all_papers = []
        cstart = 0
        pagesize = 100
        
        while len(all_papers) < limit:
            url = f"https://scholar.google.com/citations?user={scholar_id}&hl=en&cstart={cstart}&pagesize={pagesize}"
            print(f"   🔍 Fetching: {url}")
            
            resp = self._get(url)
            if not resp:
                print("      ❌ Failed to fetch page.")
                break
                
            if "sorry" in resp.url or "captcha" in resp.text.lower():
                print("      ⚠️ Google Scholar Captcha detected!")
                return all_papers

            soup = BeautifulSoup(resp.text, 'html.parser')
            new_papers = self.parse_soup(soup, scholar_id)
            
            if not new_papers:
                break
                
            all_papers.extend(new_papers)
            
            if len(new_papers) < pagesize:
                break
                
            cstart += pagesize
            time.sleep(random.uniform(2, 4))
            
        return all_papers[:limit]
    
    def parse_soup(self, soup, scholar_id):
        """Parse BeautifulSoup of a Scholar profile page into paper dicts."""
        papers = []
        rows = soup.find_all("tr", class_="gsc_a_tr")
        
        for row in rows:
            try:
                title_link = row.find("a", class_="gsc_a_at")
                title = title_link.text.strip() if title_link else ""
                link = "https://scholar.google.com" + title_link["href"] if title_link else ""
                
                divs = row.find_all("div", class_="gs_gray")
                authors = divs[0].text.strip() if len(divs) > 0 else ""
                journal = divs[1].text.strip() if len(divs) > 1 else ""
                
                year_cell = row.find("td", class_="gsc_a_y")
                year = year_cell.text.strip() if year_cell else ""
                
                cited_cell = row.find("td", class_="gsc_a_c")
                citations = cited_cell.find("a").text.strip() if cited_cell and cited_cell.find("a") else "0"
                if not citations.isdigit(): citations = "0"

                papers.append({
                    "scholar_id": scholar_id,
                    "title": title,
                    "authors": authors,
                    "journal": journal,
                    "year": year,
                    "citations": int(citations),
                    "link": link,
                    "source": "scholar"
                })
            except Exception as e:
                pass
                
        return papers

    def run_scraper(self, scholars_list, limit_per_author=100):
        """Scrape papers for a list of scholars."""
        all_data = []
        print(f"🚀 Starting Proxy Scraper for {len(scholars_list)} authors...")
        
        for idx, item in enumerate(scholars_list):
            sid = item.get('id')
            name = item.get('name')
            
            print(f"[{idx+1}/{len(scholars_list)}] Processing {name} ({sid})...")
            papers = self.get_papers(sid, limit=limit_per_author)
            
            for p in papers: p['dosen'] = name
            
            print(f"      ✅ Found {len(papers)} papers.")
            all_data.extend(papers)
        
        return all_data
