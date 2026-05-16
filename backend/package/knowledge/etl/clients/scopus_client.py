from __future__ import annotations

import os
import re
import time
import logging
import pandas as pd
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

from ..config import CRAWLER_HEADLESS, DATA_DIR
from ..transform.cleaner import flip_author_name

logger = logging.getLogger(__name__)


class ScopusClient:
    """
    Client for automating Scopus paper exports using Selenium.
    """
    
    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None
        self.download_dir = Path(
            os.getenv("ETL_SCOPUS_DOWNLOAD_DIR", str(DATA_DIR / "downloads" / "scopus"))
        )
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def setup_driver(self) -> None:
        """Configures and initializes the Selenium WebDriver."""
        options = webdriver.ChromeOptions()
        if CRAWLER_HEADLESS:
            options.add_argument("--headless=new")
        
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Binary paths for Docker or local environments
        chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
        driver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
        
        if os.path.exists(chrome_bin):
            options.binary_location = chrome_bin

        prefs = {"download.default_directory": str(self.download_dir)}
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        service = Service(executable_path=driver_path) if os.path.exists(driver_path) else Service()
        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(self.driver, 30)

    def login(self) -> bool:
        """Performs login to Scival/Scopus."""
        try:
            logger.info("Logging into Scopus via SciVal...")
            login_url = (
                "https://id.elsevier.com/as/authorization.oauth2?"
                "platSite=SVE%2FSciVal&ui_locales=en-US&scope=openid+profile+email+"
                "els_auth_info+els_analytics_info&response_type=code&"
                "redirect_uri=https%3A%2F%2Fwww.scival.com%2Fidp%2Fcode&prompt=login&client_id=SCIVAL"
            )
            self.driver.get(login_url)
            
            # Dismiss cookies if present
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
                ).click()
            except Exception:
                pass
            
            # Input Email
            email_field = self.wait.until(EC.visibility_of_element_located((By.ID, "bdd-email")))
            email_field.clear()
            email_field.send_keys(self.email)
            self.driver.find_element(By.ID, "bdd-elsPrimaryBtn").click()
            
            # Input Password
            pw_field = self.wait.until(EC.visibility_of_element_located((By.ID, "bdd-password")))
            pw_field.send_keys(self.password)
            self.driver.find_element(By.ID, "bdd-elsPrimaryBtn").click()
            
            # Wait for redirect
            self.wait.until(EC.url_contains("scival.com"))
            logger.info("Login Successful.")
            return True
        except Exception as e:
            logger.error(f"Login Failed: {e}")
            return False

    def parse_text_content(
        self, 
        content: str, 
        author_id_context: str, 
        cutoff_year: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Parses Scopus Plain Text Export format."""
        raw_records = content.split("SOURCE: Scopus")
        parsed_data: List[Dict[str, Any]] = []

        for raw_rec in raw_records:
            rec = raw_rec.strip()
            if not rec:
                continue
            if rec.startswith("Scopus") and "EXPORT DATE:" in rec and len(rec) < 100:
                continue

            lines = [l.strip() for l in rec.split('\n') if l.strip()]
            if not lines:
                continue
            
            data: Dict[str, Any] = {
                'Scopus_Author_ID': author_id_context,
                'Authors': None, 'Author IDs': None,
                'Title': None, 'Year': None, 'Journal': None,
                'Link': None, 'Abstract': None, 'Keywords': None, 
                'Document Type': None, 'DOI': None
            }
            
            # Heuristic for Year
            year_val: Optional[int] = None
            for line in lines[:20]:
                m = re.match(r'^\((\d{4})\)', line)
                if m:
                    year_val = int(m.group(1))
                    break
            
            if cutoff_year and year_val and year_val <= cutoff_year:
                continue 
            
            # Parse Labeled Fields
            for line in lines:
                if line.startswith("ABSTRACT:"): 
                    data['Abstract'] = line[9:].strip()
                elif line.startswith("AUTHOR KEYWORDS:"): 
                    data['Keywords'] = line[16:].strip()
                elif line.startswith("DOCUMENT TYPE:"): 
                    data['Document Type'] = line[14:].strip()
                elif line.startswith("DOI:"): 
                    data['DOI'] = line[4:].strip()
                elif line.startswith("https://www.scopus.com/inward/record.uri"): 
                    data['Link'] = line.strip()
                elif line.startswith("AUTHOR FULL NAMES:"):
                    raw_auths = line[18:].strip()
                    parts = raw_auths.split(';')
                    ids_found = []
                    names_only = []
                    for p in parts:
                         m = re.search(r'(.*?)\s*\(\d+\)', p.strip())
                         if m:
                             name = m.group(1).strip().rstrip(',')
                             aid_match = re.search(r'\((\d+)\)', p.strip())
                             if aid_match:
                                aid = aid_match.group(1)
                                ids_found.append(aid)
                             names_only.append(name)
                         else:
                             clean = p.strip()
                             if clean:
                                names_only.append(clean)
                    
                    data['Authors'] = "; ".join(flip_author_name(n) for n in names_only)
                    if ids_found:
                        data['Author IDs'] = "; ".join(ids_found)
                        data['Scopus_Author_ID'] = ids_found[0]

            # Parse Positional Fields (Heuristics)
            year_idx = -1
            for i, line in enumerate(lines[:20]):
                if re.match(r'^\(\d{4}\)', line):
                    year_idx = i
                    break
            
            if year_idx > 0:
                src_line = lines[year_idx]
                yd = re.match(r'^\((\d{4})\)', src_line)
                if yd:
                    data['Year'] = yd.group(1)
                    parts = src_line[len(yd.group(0)):].strip().split(',')
                    if parts:
                        data['Journal'] = parts[0].strip()
                
                # Title usually precedes Year
                prev_1 = lines[year_idx - 1]
                if re.match(r'^[\d; ]+$', prev_1):
                     if year_idx > 1:
                        data['Title'] = lines[year_idx - 2]
                else:
                    data['Title'] = prev_1

            if not data['Authors'] and lines:
                if not lines[0].startswith("EXPORT DATE"):
                    raw_names = lines[0].split(';')
                    data['Authors'] = "; ".join(flip_author_name(n) for n in raw_names)

            parsed_data.append(data)
        return parsed_data

    def restart_driver(self) -> None:
        """Restarts the browser session."""
        logger.info("Restarting browser driver...")
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self.setup_driver()


class ScopusPaperClient(ScopusClient):
    """
    Subclass specifically for the paper export workflow.
    """
    
    def run_scraper(self, scopus_author_ids: List[str], cutoff_year: Optional[int] = None) -> List[Dict[str, Any]]:
        """Runs the bulk export scraper for a list of author IDs."""
        if not self.driver:
            self.setup_driver()
        if not self.login():
            return []

        logger.info(f"Processing batch of {len(scopus_author_ids)} IDs (Cutoff Year: {cutoff_year})")
        
        try:
            id_query = " OR ".join([f"AU-ID({sid})" for sid in scopus_author_ids])
            query = f"({id_query})"
            if cutoff_year:
                query += f" AND PUBYEAR > {cutoff_year}"

            self.driver.get("https://www.scopus.com/search/form.uri?display=advanced")
            time.sleep(2)
            
            search_box = self.wait.until(EC.visibility_of_element_located((By.ID, "searchView")))
            search_box.clear()
            search_box.send_keys(query)
            self.driver.find_element(By.ID, "advSearch").click()
            
            # Wait for results
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".results-header, #resultsHeader, #selectAllCheck")))
            
            # Select all
            try:
                select_all = self.wait.until(EC.element_to_be_clickable((By.ID, "selectAllCheck")))
                if not select_all.is_selected():
                    self.driver.execute_script("arguments[0].click();", select_all)
            except Exception:
                select_all = self.driver.find_element(By.CSS_SELECTOR, "label[for='selectAllCheck'], input[name='selectAllCheck']")
                self.driver.execute_script("arguments[0].click();", select_all)

            # Click Export
            self.wait.until(EC.element_to_be_clickable((By.ID, "export_results"))).click()
            
            # Click Plain text
            self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='export-to-plainText']"))).click()
            
            # Field selection
            required_field_ids = {
                "field_group_authors", "field_group_titles", "field_group_year", 
                "field_group_eid", "field_group_sourceTitle", "field_group_sourceDocumentType", 
                "field_group_doi", "field_group_abstact", "field_group_authorKeywords"
            }
            
            checkboxes = self.driver.find_elements(By.CSS_SELECTOR, "label input[type='checkbox']")
            for cb in checkboxes:
                try:
                    cid = cb.get_attribute("id")
                    if not cid:
                        continue
                    if cid in required_field_ids:
                        if not cb.is_selected():
                            self.driver.execute_script("arguments[0].click();", cb)
                    else:
                        if cb.is_selected():
                            self.driver.execute_script("arguments[0].click();", cb)
                except Exception:
                    pass

            # Submit Export
            self.driver.find_element(By.CSS_SELECTOR, "button[data-testid='submit-export-button']").click()
            logger.info("Export request submitted. Waiting for download...")

            # Wait for file download
            txt_file: Optional[Path] = None
            start_wait = time.time()
            
            while time.time() - start_wait < 300:
                files = sorted(list(self.download_dir.glob("scopus*.txt")), key=os.path.getmtime, reverse=True)
                if files:
                    latest = files[0]
                    # Check if file is still being written
                    if latest.stat().st_size > 0 and (time.time() - latest.stat().st_mtime) < 30:
                        txt_file = latest
                        break
                time.sleep(3)
            
            if txt_file:
                content = txt_file.read_text(encoding='utf-8')
                records = self.parse_text_content(content, "BATCH_MODE", cutoff_year)
                logger.info(f"Extracted {len(records)} papers from batch export.")
                try:
                    txt_file.unlink()
                except Exception:
                    pass
                return records
            else:
                logger.error("Download timed out.")
                return []

        except Exception as e:
            logger.error(f"Scraper Runtime Error: {e}")
            return []
        finally:
            if self.driver:
                self.driver.quit()
