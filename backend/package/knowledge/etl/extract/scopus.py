"""
Extract: Scopus Papers via SciVal/Selenium
==========================================
Fetches paper metadata from Scopus export function.
Uses ScopusPaperClient with Selenium WebDriver for browser automation.

Architecture Note:
  Docker containers use /usr/bin/chromium with --no-sandbox.
  The Docker compatibility patch below auto-detects this environment.
"""
import os
import time
import logging
import pandas as pd
from pathlib import Path

from knowledge.etl.config import DATA_DIR, RAW_DATA_DIR, SCIVAL_EMAIL, SCIVAL_PASS
from knowledge.etl.scraping.config import CRAWLER_HEADLESS

logger = logging.getLogger(__name__)


def _apply_docker_chromium_patch(client_instance):
    """
    Monkey-patch the ScopusPaperClient's setup_driver() for Docker's
    system-installed Chromium (no webdriver-manager needed).

    Only applies when /usr/bin/chromium or /usr/bin/chromium-browser exists.
    Returns the same client instance (mutated in-place).
    """
    chrome_bin = None
    for path in ('/usr/bin/chromium', '/usr/bin/chromium-browser'):
        if os.path.exists(path):
            chrome_bin = path
            break

    if not chrome_bin:
        return client_instance

    logger.info("      🐳 Applying Docker Chromium Patch for session...")

    import types
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support.ui import WebDriverWait

    temp_dir = "/app/data/scopus_temp"
    os.makedirs(temp_dir, exist_ok=True)

    def _docker_setup_driver(self_client):
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

        self_client.driver = webdriver.Chrome(
            service=Service("/usr/bin/chromedriver"), options=options
        )
        try:
            self_client.driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": temp_dir,
            })
        except Exception as e:
            logger.warning(f"      ⚠️ CDP Page Download Error: {e}")

        self_client.wait = WebDriverWait(self_client.driver, 20)

    client_instance.setup_driver = types.MethodType(_docker_setup_driver, client_instance)

    # Override SAVE_DIR inside the scraping config for this process
    try:
        import knowledge.etl.scraping.config as scraping_cfg
        scraping_cfg.SAVE_DIR = Path(temp_dir)
    except Exception:
        pass

    return client_instance


def _fetch_target_scopus_ids(test_target_id: str | None = None) -> list[str]:
    """
    Fetch Scopus Author IDs from Supabase (Level 3 Architecture).
    Falls back to an empty list if Supabase is unreachable.
    """
    from knowledge.etl.load.supabase_loader import SupabaseLoader

    if test_target_id:
        logger.info(f"🧪 RUNNING IN TEST MODE FOR ID: {test_target_id}")
        return [test_target_id]

    loader = SupabaseLoader()
    logger.info("      🐳 Fetching Scopus IDs from Supabase instead of CSV...")
    response = loader.client.table("lecturers").select("scopus_id").execute()

    ids: set[str] = set()
    for row in response.data:
        sid = str(row.get("scopus_id", "")).strip().replace(".0", "")
        if sid and sid.lower() not in ("nan", "none", "null"):
            ids.add(sid)

    target_ids = list(ids)

    # --- TEST LIMIT ---
    # TODO: Remove this limit for production
    target_ids = target_ids[:1]
    logger.info(f"🧪 DEBUG: Limited to 1 ID for testing: {target_ids}")

    return target_ids


def extract_scopus_papers(limit_per_author: int = 500, test_target_id: str | None = None):
    """
    Scrape papers from Scopus using ScopusPaperClient.
    Saved to data/raw/dosen_papers_scopus_raw.csv.

    Uses batched isolated sessions (5 IDs per batch) to balance
    speed (fewer logins) and stability (fresh browser per batch).
    """
    try:
        from knowledge.etl.scraping.scopus_client import ScopusPaperClient
    except ImportError as e:
        logger.error(f"❌ Failed to load ScopusClient: {e}")
        return []

    logger.info("\n📚 EXTRACT: SCOPUS SCRAPING")

    target_ids = _fetch_target_scopus_ids(test_target_id)
    logger.info(f"🎯 Found {len(target_ids)} Scopus IDs to scrape.")
    if not target_ids:
        return []

    # ── Batched Isolated Sessions ──
    all_papers: list[dict] = []
    BATCH_SIZE = 5

    for i in range(0, len(target_ids), BATCH_SIZE):
        batch = target_ids[i : i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(target_ids) + BATCH_SIZE - 1) // BATCH_SIZE

        logger.info(f"\n--- 🔄 Processing Batch [{batch_num}/{total_batches}]: {batch} ---")

        # Fresh client & driver for EACH BATCH to prevent DevTools memory crashes
        client = ScopusPaperClient(SCIVAL_EMAIL, SCIVAL_PASS)
        client = _apply_docker_chromium_patch(client)

        try:
            papers = client.run_scraper(batch)
            if papers:
                all_papers.extend(papers)
                logger.info(f"      ✅ Total accumulated: {len(all_papers)}")
        except Exception as e:
            logger.error(f"      ❌ Fatal runtime error on batch {batch_num}: {e}")
        finally:
            try:
                if hasattr(client, "driver") and client.driver:
                    client.driver.quit()
            except Exception:
                pass

        # Short sleep to let the container OS recover ports
        if batch_num < total_batches:
            time.sleep(5)

    # ── Save Results ──
    df_new = pd.DataFrame(all_papers) if all_papers else pd.DataFrame()
    raw_csv = RAW_DATA_DIR / "dosen_papers_scopus_raw.csv"

    if not df_new.empty:
        df_new.to_csv(raw_csv, index=False)
        logger.info(f"\n✅ Saved {len(df_new)} new papers to {raw_csv}")
    else:
        pd.DataFrame().to_csv(raw_csv, index=False)
        logger.info("\n⚠️ No new papers scraped.")

    return all_papers
