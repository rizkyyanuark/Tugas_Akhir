from __future__ import annotations

import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests
import urllib3
from bs4 import BeautifulSoup

from ..config import HEADERS, PROXY_URL, BD_SCRAPING_BROWSER_URL, BD_USER_UNLOCKER, BD_PASS_UNLOCKER, BRIGHT_DATA_HOST
from .utils import clean_name_expert

# Disable SSL warnings for proxy usage
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class ScholarClient:
    """
    Consolidated Google Scholar Client for:
    1. Verifying Scholar IDs (profile name matching)
    2. Searching for Scholar IDs by name
    3. Fetching papers from a Scholar profile
    
    Uses Bright Data proxy to avoid IP blocks and rate limits.
    """

    def __init__(self, proxy_url: Optional[str] = None) -> None:
        # Use Web Unlocker if available, or fallback to the provided proxy/PROXY_URL
        selected_proxy = proxy_url
        if not selected_proxy or selected_proxy == PROXY_URL:
            if BD_USER_UNLOCKER and BD_PASS_UNLOCKER and BRIGHT_DATA_HOST:
                selected_proxy = f"http://{BD_USER_UNLOCKER}:{BD_PASS_UNLOCKER}@{BRIGHT_DATA_HOST}"
            else:
                selected_proxy = PROXY_URL or proxy_url

        self.proxies = None
        if selected_proxy:
            self.proxies = {
                "http": selected_proxy,
                "https": selected_proxy
            }
        
        self.headers = {
            "User-Agent": HEADERS.get("User-Agent", "Mozilla/5.0"),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        if self.proxies:
            self.session.proxies.update(self.proxies)
            
        self._request_count = 0

    def _get(self, url: str, timeout: int = 45, max_retries: int = 3) -> Optional[requests.Response]:
        """Make a proxied GET request with retry and shared session."""
        self._request_count += 1
        
        # Periodic longer sleep to avoid aggressive detection
        if self._request_count % 10 == 0:
            time.sleep(random.uniform(2.0, 5.0))
        
        for attempt in range(1, max_retries + 1):
            try:
                # Small jitter
                time.sleep(random.uniform(0.1, 0.5))
                
                resp = self.session.get(
                    url,
                    timeout=timeout,
                    allow_redirects=True,
                    verify=False
                )
                
                if resp.status_code == 429:
                    wait = 5 * attempt
                    logger.warning(f"Google Rate Limit (429). Retrying in {wait}s... URL: {url[:60]}")
                    time.sleep(wait)
                    continue
                
                if resp.status_code != 200:
                    logger.debug(f"Non-200 status {resp.status_code} for {url[:60]}")
                    
                # Check for captchas in the response text
                if "sorry" in resp.url or "robot" in resp.text.lower()[:1000]:
                    logger.warning(f"Captcha/Block detected for {url[:60]}. Retrying after sleep...")
                    time.sleep(10 * attempt)
                    continue
                    
                return resp
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    wait = attempt * 5
                    logger.debug(f"Request failed (attempt {attempt}): {e}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    logger.error(f"Request failed after {max_retries} attempts: {url[:60]} - {type(e).__name__}")
                    
        return None

    def _normalize_name(self, name: str) -> str:
        """Strip titles and normalize for comparison using internal utility."""
        return clean_name_expert(str(name)).lower().strip()

    def _extract_scholar_id(self, url: str) -> Optional[str]:
        """Extract Google Scholar ID from various URL formats."""
        url_str = str(url)
        if "scholar.google" not in url_str and "citations" not in url_str:
            return None
            
        try:
            parsed = urlparse(url_str)
            params = parse_qs(parsed.query)
            user = params.get("user", [None])[0]
            if user and len(user) >= 8:
                return user
        except Exception:
            pass
            
        # Regex fallback
        match = re.search(r"user=([A-Za-z0-9_-]{8,})", url_str)
        if match:
            return match.group(1)
        return None

    # --- Verification & Search Methods ---

    def verify_id(self, scholar_id: str, expected_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a scholar profile and verify if it matches the expected name.
        """
        if not scholar_id or len(str(scholar_id).strip()) < 5:
            return {"valid": False, "profile_name": "", "score": 0}
            
        url = f"https://scholar.google.com/citations?user={scholar_id}&hl=en"
        resp = self._get(url)
        
        if resp is None or resp.status_code != 200:
            return None
            
        soup = BeautifulSoup(resp.text, "html.parser")
        name_elem = soup.find(id="gsc_prf_in")
        if not name_elem:
            return {"valid": False, "profile_name": "", "score": 0}
            
        profile_name = name_elem.get_text().strip()
        norm_expected = self._normalize_name(expected_name)
        norm_profile = self._normalize_name(profile_name)
        score = SequenceMatcher(None, norm_expected, norm_profile).ratio()
        
        # Check affiliation for extra verification signal
        affiliation = ""
        aff_elem = soup.find(class_="gsc_prf_ila")
        if not aff_elem:
            # Try alternate affiliation element
            aff_elem = soup.select_one(".gsc_prf_il")
            
        if aff_elem:
            affiliation = aff_elem.get_text().strip().lower()
            
        # Dynamic threshold based on affiliation match
        threshold = 0.70
        if "unesa" in affiliation or "negeri surabaya" in affiliation:
            threshold = 0.60
            
        is_valid = score >= threshold
        
        return {
            "valid": is_valid,
            "profile_name": profile_name,
            "affiliation": affiliation,
            "score": score
        }

    def search_by_name(self, name: str, max_candidates: int = 5) -> List[str]:
        """
        Search for scholar profile IDs by name using Google Search and Scholar Search.
        """
        # Try Google Search first (often more robust)
        query = f"{name} site:scholar.google.com"
        url = f"https://www.google.com/search?q={requests.utils.quote(query)}&num=10"
        
        candidates: Set[str] = set()
        
        resp = self._get(url)
        if resp and resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.find_all("a", href=True):
                href = link["href"]
                # Google search result redirects
                if "/url?q=" in href:
                    href = href.split("/url?q=")[1].split("&")[0]
                
                sid = self._extract_scholar_id(href)
                if sid:
                    candidates.add(sid)
                    if len(candidates) >= max_candidates:
                        break
                        
        # Fallback/Supplemental search on Scholar direct
        if len(candidates) < max_candidates:
            scholar_url = f"https://scholar.google.com/citations?view_op=search_authors&mauthors={requests.utils.quote(name)}&hl=en"
            s_resp = self._get(scholar_url)
            if s_resp and s_resp.status_code == 200:
                s_soup = BeautifulSoup(s_resp.text, "html.parser")
                for link in s_soup.find_all("a", href=True):
                    sid = self._extract_scholar_id(link["href"])
                    if sid:
                        candidates.add(sid)
                        if len(candidates) >= max_candidates:
                            break
                            
        return list(candidates)

    def process_verification_batch(self, tasks: List[Dict[str, Any]], max_workers: int = 5) -> List[Dict[str, Any]]:
        """
        Process a list of verification/search tasks in parallel.
        Tasks list format: [{'index': idx, 'name': str, 'id': str}, ...]
        Returns: [{'index': idx, 'valid': bool, 'id': str}, ...]
        """
        results = []
        logger.info(f"Starting Parallel Scholar Verification ({max_workers} threads) for {len(tasks)} tasks.")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {}
            
            for task in tasks:
                name = task["name"]
                sid = task.get("id")
                future = executor.submit(self._process_single_lecturer, name, sid)
                future_to_task[future] = task
            
            done_count = 0
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                idx = task["index"]
                name = task["name"]
                try:
                    res_sid = future.result()
                    results.append({
                        "index": idx,
                        "valid": bool(res_sid),
                        "id": res_sid
                    })
                except Exception as exc:
                    logger.error(f"Task for {name} generated an exception: {exc}")
                    results.append({
                        "index": idx,
                        "valid": False,
                        "id": None
                    })
                
                done_count += 1
                if done_count % 10 == 0:
                    logger.info(f"Verification Progress: {done_count}/{len(tasks)} processed")
                    
        return results

    def _process_single_lecturer(self, name: str, sid: Optional[str]) -> Optional[str]:
        """Internal logic for a single lecturer: verify existing or search for new."""
        # 1. Verify existing ID if provided
        if sid and str(sid).lower() != "nan" and len(str(sid)) > 5:
            res = self.verify_id(sid, name)
            if res and res["valid"]:
                return sid
        
        # 2. Search for candidates and verify them
        candidates = self.search_by_name(name)
        for cand_id in candidates:
            # Don't re-verify the same ID we just checked
            if cand_id == sid:
                continue
            res = self.verify_id(cand_id, name)
            if res and res["valid"]:
                return cand_id
                
        return None

    # --- Paper Extraction Methods ---

    def get_papers(self, scholar_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch papers from a Scholar profile page. Uses BrightData Scraping Browser if available, fallback to HTTP pagination."""
        if BD_SCRAPING_BROWSER_URL:
            logger.info("Using BrightData Scraping Browser for Google Scholar scraping.")
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.common.by import By
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                
                chrome_options = Options()
                # Bypass environment proxies for Selenium remote connection
                import os
                env_proxies = {}
                for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
                    if key in os.environ:
                        env_proxies[key] = os.environ[key]
                        del os.environ[key]

                try:
                    driver = webdriver.Remote(
                        command_executor=BD_SCRAPING_BROWSER_URL,
                        options=chrome_options
                    )
                finally:
                    # Restore environment proxies
                    for key, val in env_proxies.items():
                        os.environ[key] = val
                
                all_papers: List[Dict[str, Any]] = []
                try:
                    url = f"https://scholar.google.com/citations?user={scholar_id}&hl=en"
                    logger.debug(f"Scraping Browser: Navigating to {url}")
                    driver.get(url)
                    
                    click_count = 0
                    while True:
                        soup = BeautifulSoup(driver.page_source, "html.parser")
                        papers = self._parse_profile_papers(soup, scholar_id)
                        
                        if len(papers) >= limit:
                            all_papers = papers[:limit]
                            break
                        
                        try:
                            button = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.ID, "gsc_bpf_more"))
                            )
                            if button.get_attribute("disabled"):
                                all_papers = papers
                                break
                            
                            click_count += 1
                            logger.debug(f"Scraping Browser: Clicking 'Show more' (click {click_count})...")
                            driver.execute_script("arguments[0].click();", button)
                            time.sleep(2.0)
                        except Exception:
                            all_papers = papers
                            break
                finally:
                    driver.quit()
                    
                if all_papers:
                    logger.info(f"Successfully fetched {len(all_papers)} papers using Scraping Browser.")
                    return all_papers
                else:
                    logger.warning("Scraping Browser returned 0 papers. Falling back to HTTP pagination.")
            except Exception as e:
                logger.error(f"BrightData Scraping Browser failed: {e}. Falling back to HTTP pagination.")
                # fall through to legacy logic below

        all_papers: List[Dict[str, Any]] = []
        seen_links = set()
        cstart = 0
        pagesize = 100
        
        while len(all_papers) < limit:
            url = f"https://scholar.google.com/citations?user={scholar_id}&hl=en&cstart={cstart}&pagesize={pagesize}"
            logger.debug(f"Fetching papers: {url}")
            
            resp = self._get(url)
            if not resp:
                break
                
            soup = BeautifulSoup(resp.text, "html.parser")
            new_papers = self._parse_profile_papers(soup, scholar_id)
            
            if not new_papers:
                break
                
            has_new = False
            for p in new_papers:
                link = p.get("link")
                if link and link not in seen_links:
                    seen_links.add(link)
                    all_papers.append(p)
                    has_new = True
            
            # If no new papers were found, we have reached the end of the profile
            if not has_new:
                break
                
            cstart += len(new_papers)
            time.sleep(random.uniform(2.0, 4.0))
            
        return all_papers[:limit]

    def _parse_profile_papers(self, soup: BeautifulSoup, scholar_id: str) -> List[Dict[str, Any]]:
        """Parse the table of papers from a Scholar profile page."""
        papers = []
        rows = soup.find_all("tr", class_="gsc_a_tr")
        
        for row in rows:
            try:
                title_link = row.find("a", class_="gsc_a_at")
                if not title_link:
                    continue
                    
                title = title_link.get_text().strip()
                link = "https://scholar.google.com" + title_link["href"]
                
                divs = row.find_all("div", class_="gs_gray")
                authors = divs[0].get_text().strip() if len(divs) > 0 else ""
                journal = divs[1].get_text().strip() if len(divs) > 1 else ""
                
                year_cell = row.find("td", class_="gsc_a_y")
                year = year_cell.get_text().strip() if year_cell else ""
                
                cited_cell = row.find("td", class_="gsc_a_c")
                citations_text = cited_cell.find("a").get_text().strip() if cited_cell and cited_cell.find("a") else "0"
                
                # Handle cases like "12*" or non-digit chars
                citations_match = re.search(r"(\d+)", citations_text)
                citations = int(citations_match.group(1)) if citations_match else 0

                papers.append({
                    "scholar_id": scholar_id,
                    "title": title,
                    "authors": authors,
                    "journal": journal,
                    "year": year,
                    "citations": citations,
                    "link": link,
                    "source": "scholar"
                })
            except Exception as e:
                logger.debug(f"Error parsing paper row: {e}")
                continue
                
        return papers

    def scrape_papers_for_scholars(self, scholars_list: List[Dict[str, Any]], limit_per_author: int = 100) -> List[Dict[str, Any]]:
        """
        Sequential scraper for a list of scholars (sequential to respect rate limits even with proxy).
        """
        all_data = []
        total = len(scholars_list)
        logger.info(f"Starting Paper Scraper for {total} authors (limit: {limit_per_author}).")
        
        for idx, item in enumerate(scholars_list):
            sid = item.get("id")
            name = item.get("name")
            
            if not sid:
                continue
                
            logger.info(f"[{idx+1}/{total}] Scraping papers for {name} ({sid})...")
            papers = self.get_papers(sid, limit=limit_per_author)
            
            for p in papers:
                p["dosen"] = name
                
            logger.info(f"      Found {len(papers)} papers.")
            all_data.extend(papers)
            
        return all_data


class ScholarVerificationClient(ScholarClient):
    """
    Backward-compatible verification client used by the lecturers ETL service.

    The consolidated ScholarClient exposes `process_verification_batch()`, while
    older pipeline code still calls `verify_batch()`. Keeping this adapter in
    the client module prevents import-time failures across DAG tasks.
    """

    def verify_batch(
        self,
        tasks: List[Dict[str, Any]],
        max_workers: int = 5,
    ) -> List[Dict[str, Any]]:
        return self.process_verification_batch(tasks, max_workers=max_workers)
