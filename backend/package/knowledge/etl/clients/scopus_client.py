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
from ..utils.logging import log_error, log_event, log_warning

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

        prefs = {
            "download.default_directory": str(self.download_dir),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,
            "safebrowsing.disable_download_protection": True,
            "profile.default_content_settings.popups": 0,
        }
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        service = Service(executable_path=driver_path) if os.path.exists(driver_path) else Service()
        self.driver = webdriver.Chrome(service=service, options=options)
        try:
            self.driver.execute_cdp_cmd(
                "Page.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(self.download_dir)},
            )
        except Exception as e:
            log_warning(logger, "scopus.browser.download_config_failed", error=e)
        self.wait = WebDriverWait(self.driver, 30)

    def login(self) -> bool:
        """Performs login to Scival/Scopus."""
        try:
            log_event(logger, "scopus.login.start")
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
                log_event(logger, "scopus.login.cookie_accepted")
            except Exception:
                log_event(logger, "scopus.login.cookie_absent")
            
            # Input Email
            email_field = self.wait.until(EC.visibility_of_element_located((By.ID, "bdd-email")))
            email_field.clear()
            email_field.send_keys(self.email)
            self.driver.find_element(By.ID, "bdd-elsPrimaryBtn").click()
            log_event(logger, "scopus.login.email_submitted")
            
            # Input Password
            pw_field = self.wait.until(EC.visibility_of_element_located((By.ID, "bdd-password")))
            pw_field.send_keys(self.password)
            self.driver.find_element(By.ID, "bdd-elsPrimaryBtn").click()
            log_event(logger, "scopus.login.password_submitted")
            
            # Wait for redirect
            self.wait.until(EC.url_contains("scival.com"))
            log_event(logger, "scopus.login.success")
            return True
        except Exception as e:
            current_url = self.driver.current_url if self.driver else ""
            log_error(logger, "scopus.login.failed", exc=e, current_url=current_url)
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
        log_event(logger, "scopus.browser.restart")
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
        """Scrape Scopus papers from author profile pages.

        This intentionally uses the author detail page and its "Export all"
        action. Earlier versions used Scopus Advanced Search with AU-ID(...)
        queries, but that path is less stable in headless Docker sessions and
        commonly times out before the advanced search input appears.
        """
        if not self.driver:
            self.setup_driver()
        if not self.login():
            return []

        log_event(logger, "scopus.scrape.start", author_count=len(scopus_author_ids), strategy="author_profile_export")
        all_papers: List[Dict[str, Any]] = []
        
        try:
            for idx, scopus_id in enumerate(scopus_author_ids, 1):
                log_event(
                    logger,
                    "scopus.scrape.author_start",
                    index=idx,
                    total=len(scopus_author_ids),
                    scopus_id=scopus_id,
                )
                time.sleep(2)

                try:
                    self.driver.get(f"https://www.scopus.com/authid/detail.uri?authorId={scopus_id}")
                    time.sleep(1)
                except Exception as e:
                    log_warning(logger, "scopus.scrape.profile_navigation_failed", scopus_id=scopus_id, error=e)
                    continue

                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.ID, "auth_name"))
                    )
                except Exception:
                    log_event(logger, "scopus.scrape.profile_loaded_without_name", scopus_id=scopus_id)

                try:
                    export_all_btn = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='Export all']]"))
                    )
                    export_all_btn.click()
                except Exception as e:
                    log_warning(logger, "scopus.scrape.no_export_button", scopus_id=scopus_id, error=e)
                    continue

                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='export-to-plainText']"))
                    ).click()
                except Exception as e:
                    log_warning(logger, "scopus.scrape.export_format_failed", scopus_id=scopus_id, error=e)
                    continue

                self._select_required_export_fields()

                before_submit = time.time()
                try:
                    self.driver.find_element(By.CSS_SELECTOR, "button[data-testid='submit-export-button']").click()
                    log_event(logger, "scopus.scrape.export_submitted", scopus_id=scopus_id)
                except Exception as e:
                    log_warning(logger, "scopus.scrape.export_submit_failed", scopus_id=scopus_id, error=e)
                    continue

                txt_file = self._wait_for_download(start_after=before_submit, timeout_seconds=120)
                if not txt_file:
                    log_warning(logger, "scopus.scrape.download_timeout", scopus_id=scopus_id, timeout_seconds=120)
                    continue

                try:
                    content = txt_file.read_text(encoding="utf-8")
                    records = self.parse_text_content(content, scopus_id, cutoff_year)
                    log_event(logger, "scopus.scrape.author_done", scopus_id=scopus_id, rows=len(records))
                    all_papers.extend(records)
                finally:
                    try:
                        txt_file.unlink()
                    except Exception:
                        pass

            return all_papers
        except Exception as e:
            current_url = self.driver.current_url if self.driver else ""
            log_error(logger, "scopus.scrape.failed", exc=e, current_url=current_url)
            return all_papers
        finally:
            if self.driver:
                self.driver.quit()

    def _select_required_export_fields(self) -> None:
        required_field_ids = {
            "field_group_authors",
            "field_group_titles",
            "field_group_year",
            "field_group_eid",
            "field_group_sourceTitle",
            "field_group_sourceDocumentType",
            "field_group_doi",
            "field_group_abstact",
            "field_group_authorKeywords",
        }

        try:
            checkboxes = self.driver.find_elements(
                By.CSS_SELECTOR,
                "label[aria-controls] input[type='checkbox'], "
                "label.Checkbox-module__jE3jb input[type='checkbox'], "
                "label input[type='checkbox']",
            )
            for checkbox in checkboxes:
                try:
                    field_id = checkbox.get_attribute("id")
                    if not field_id:
                        continue
                    should_be_checked = field_id in required_field_ids
                    if should_be_checked != checkbox.is_selected():
                        self.driver.execute_script("arguments[0].click();", checkbox)
                except Exception:
                    continue

            time.sleep(0.5)
            for field_id in required_field_ids:
                try:
                    checkbox = self.driver.find_element(By.ID, field_id)
                    if not checkbox.is_selected():
                        self.driver.execute_script("arguments[0].click();", checkbox)
                except Exception:
                    continue
        except Exception as e:
            log_warning(logger, "scopus.scrape.field_selection_failed", error=e)

    def _wait_for_download(self, start_after: float, timeout_seconds: int = 120) -> Optional[Path]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            files = sorted(
                self.download_dir.glob("scopus*.txt"),
                key=os.path.getmtime,
                reverse=True,
            )
            for file_path in files:
                try:
                    if file_path.stat().st_size > 0 and file_path.stat().st_mtime >= start_after:
                        time.sleep(1)
                        return file_path
                except OSError:
                    continue
            time.sleep(2)

        return None


def process_scopus_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and deduplicate Scopus paper records into the canonical paper schema."""
    if df is None or df.empty:
        return pd.DataFrame()

    from knowledge.etl.transform.cleaner import clean_papers_batch
    from knowledge.etl.transform.deduplicator import deduplicate_papers

    processed = df.copy().fillna("")
    required_columns = [
        "Authors",
        "Author IDs",
        "Title",
        "Year",
        "Journal",
        "Link",
        "Abstract",
        "Keywords",
        "Document Type",
        "DOI",
        "TLDR",
        "source",
    ]
    for column in required_columns:
        if column not in processed.columns:
            processed[column] = ""

    processed = processed[processed["Title"].astype(str).str.strip().ne("")].copy()
    if processed.empty:
        log_warning(logger, "scopus.process.no_titled_rows")
        return processed

    processed["source"] = processed["source"].replace("", "scopus")
    processed = clean_papers_batch(processed)

    doi_norm = processed["DOI"].astype(str).str.strip().str.lower()
    valid_doi_mask = ~doi_norm.isin(["", "nan", "none", "null"])
    with_doi = processed[valid_doi_mask].copy()
    without_doi = processed[~valid_doi_mask].copy()
    if not with_doi.empty:
        with_doi["_doi_norm"] = with_doi["DOI"].astype(str).str.strip().str.lower()
        with_doi = with_doi.drop_duplicates(subset="_doi_norm", keep="first")
        with_doi = with_doi.drop(columns=["_doi_norm"], errors="ignore")

    processed = pd.concat([with_doi, without_doi], ignore_index=True)
    processed = deduplicate_papers(processed)

    ordered_columns = [
        "Authors",
        "Author IDs",
        "Title",
        "Year",
        "Journal",
        "Link",
        "Abstract",
        "Keywords",
        "Document Type",
        "DOI",
        "TLDR",
        "source",
    ]
    passthrough_columns = [c for c in processed.columns if c not in ordered_columns]
    return processed[ordered_columns + passthrough_columns]
