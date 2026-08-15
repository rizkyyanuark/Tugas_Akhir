from __future__ import annotations

import logging
import os
import time
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from ..clients.scopus_client import ScopusPaperClient
from ..config import (CRAWLER_HEADLESS, RAW_DATA_DIR, SCIVAL_EMAIL,
                      SCIVAL_PASS)
from ..load.supabase_loader import SupabaseLoader
from ..utils.storage import write_dataframe_csv

logger = logging.getLogger(__name__)


def _apply_docker_chromium_patch(client_instance: ScopusPaperClient) -> ScopusPaperClient:
    """
    Monkey-patch the ScopusPaperClient's setup_driver() for Docker's
    system-installed Chromium (no webdriver-manager needed).

    Only applies when /usr/bin/chromium or /usr/bin/chromium-browser exists.
    """
    chrome_bin = None
    for path in ("/usr/bin/chromium", "/usr/bin/chromium-browser"):
        if os.path.exists(path):
            chrome_bin = path
            break

    if not chrome_bin:
        return client_instance

    logger.info("Applying Docker Chromium patch for Selenium session...")

    temp_dir = "/app/data/scopus_temp"
    os.makedirs(temp_dir, exist_ok=True)

    def _docker_setup_driver(self_client: ScopusPaperClient) -> None:
        options = webdriver.ChromeOptions()
        if CRAWLER_HEADLESS:
            options.add_argument("--headless=new")
        
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        options.binary_location = chrome_bin
        
        options.add_experimental_option("prefs", {
            "download.default_directory": temp_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,
            "safebrowsing.disable_download_protection": True,
            "profile.default_content_settings.popups": 0,
        })
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # In Docker, we assume chromedriver is at /usr/bin/chromedriver
        self_client.driver = webdriver.Chrome(
            service=Service("/usr/bin/chromedriver"),
            options=options
        )
        
        try:
            self_client.driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": temp_dir,
            })
        except Exception as e:
            logger.warning(f"CDP Page Download Error: {e}")

        self_client.wait = WebDriverWait(self_client.driver, 30)

    # Bind the new setup_driver method to the client instance
    client_instance.setup_driver = types.MethodType(_docker_setup_driver, client_instance)

    return client_instance


def _fetch_target_scopus_ids(test_target_id: Optional[str] = None) -> List[str]:
    """
    Fetch Scopus Author IDs from Supabase.
    """
    if test_target_id:
        logger.info(f"Running in test mode for Scopus ID: {test_target_id}")
        return [test_target_id]

    loader = SupabaseLoader()
    logger.info("Fetching target Scopus IDs from Supabase...")
    
    try:
        response = loader.client.table("lecturers").select("scopus_id").execute()
        ids: Set[str] = set()
        for row in response.data:
            sid = str(row.get("scopus_id", "")).strip().replace(".0", "")
            if sid and sid.lower() not in ("nan", "none", "null"):
                ids.add(sid)

        target_ids = sorted(list(ids))
        logger.info(f"Found {len(target_ids)} unique Scopus IDs to process.")
        return target_ids
    except Exception as e:
        logger.error(f"Failed to fetch IDs from Supabase: {e}")
        return []


def extract_scopus_papers(
    limit_per_author: int = 500,
    test_target_id: Optional[str] = None,
    cutoff_year: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Scrape papers from Scopus using ScopusPaperClient.
    Uses Batched Advanced Search for efficiency.
    """
    logger.info("Extracting Scopus papers in batch mode...")

    target_ids = _fetch_target_scopus_ids(test_target_id)
    if not target_ids:
        logger.warning("No Scopus IDs available for extraction.")
        return []

    all_papers: List[Dict[str, Any]] = []
    batch_size = 50 

    total_ids = len(target_ids)
    for i in range(0, total_ids, batch_size):
        batch = target_ids[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_ids + batch_size - 1) // batch_size

        logger.info(f"Processing Batch [{batch_num}/{total_batches}] ({len(batch)} IDs)...")

        client = ScopusPaperClient(SCIVAL_EMAIL, SCIVAL_PASS)
        client = _apply_docker_chromium_patch(client)

        try:
            papers = client.run_scraper(batch, cutoff_year=cutoff_year)
            if papers:
                all_papers.extend(papers)
                logger.info(f"Batch {batch_num} complete. Added {len(papers)} papers. Total: {len(all_papers)}")
            else:
                logger.warning(f"Batch {batch_num} returned no papers.")
        except Exception as e:
            logger.error(f"Fatal error during batch {batch_num}: {e}", exc_info=True)
        finally:
            try:
                if hasattr(client, "driver") and client.driver:
                    client.driver.quit()
            except Exception as e:
                logger.debug(f"Error closing driver: {e}")

        # Rate limiting sleep between browser sessions
        if i + batch_size < total_ids:
            time.sleep(5)

    # Final Save and Deduplication
    if not all_papers:
        logger.warning("No papers collected across all batches.")
        return []

    df = pd.DataFrame(all_papers)
    
    # Deduplicate by EID (Scopus unique identifier)
    if "eid" in df.columns:
        initial_len = len(df)
        df = df.drop_duplicates(subset=["eid"])
        if len(df) < initial_len:
            logger.info(f"Removed {initial_len - len(df)} duplicate papers by EID.")

    output_path = RAW_DATA_DIR / "dosen_papers_scopus_raw.csv"
    try:
        write_dataframe_csv(df, output_path, index=False)
        logger.info(f"Successfully saved {len(df)} papers to {output_path}")
    except Exception as e:
        logger.error(f"Failed to save results to {output_path}: {e}")

    return df.to_dict("records")
