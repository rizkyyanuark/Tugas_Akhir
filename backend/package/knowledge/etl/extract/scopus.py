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
    logger.info("      🐳 Fetching Scopus IDs from Supabase...")
    
    try:
        response = loader.client.table("lecturers").select("scopus_id").execute()
        ids: set[str] = set()
        for row in response.data:
            sid = str(row.get("scopus_id", "")).strip().replace(".0", "")
            if sid and sid.lower() not in ("nan", "none", "null"):
                ids.add(sid)

        target_ids = list(ids)
        logger.info(f"      ✅ Found {len(target_ids)} unique Scopus IDs.")
        return target_ids
    except Exception as e:
        logger.error(f"      ❌ Failed to fetch IDs from Supabase: {e}")
        return []


def extract_scopus_papers(limit_per_author: int = 500, test_target_id: str | None = None, cutoff_year: int | None = None):
    """
    Scrape papers from Scopus using ScopusPaperClient.
    Uses Batched Advanced Search for maximum speed and stability.
    """
    try:
        from knowledge.etl.scraping.scopus_client import ScopusPaperClient
    except ImportError as e:
        logger.error(f"❌ Failed to load ScopusClient: {e}")
        return []

    logger.info("\n📚 EXTRACT: SCOPUS SCRAPING (BATCH MODE)")

    target_ids = _fetch_target_scopus_ids(test_target_id)
    if not target_ids:
        logger.warning("⚠️ No Scopus IDs found to process.")
        return []

    # ── Batched Advanced Search Sessions ──
    # Increased batch size as Advanced Search can handle many IDs in one query string
    all_papers: list[dict] = []
    BATCH_SIZE = 50 

    for i in range(0, len(target_ids), BATCH_SIZE):
        batch = target_ids[i : i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(target_ids) + BATCH_SIZE - 1) // BATCH_SIZE

        logger.info(f"\n--- 🔄 Processing Batch [{batch_num}/{total_batches}] ({len(batch)} IDs) ---")

        client = ScopusPaperClient(SCIVAL_EMAIL, SCIVAL_PASS)
        client = _apply_docker_chromium_patch(client)

        try:
            # Pass cutoff_year to the optimized run_scraper
            papers = client.run_scraper(batch, cutoff_year=cutoff_year)
            if papers:
                all_papers.extend(papers)
                logger.info(f"      ✅ Batch total: {len(papers)} | Accumulated: {len(all_papers)}")
            else:
                logger.warning(f"      ⚠️ No papers found for this batch.")
        except Exception as e:
            logger.error(f"      ❌ Fatal runtime error on batch {batch_num}: {e}")
        finally:
            try:
                if hasattr(client, "driver") and client.driver:
                    client.driver.quit()
            except Exception:
                pass

        # Brief pause between browser sessions
        if batch_num < total_batches:
            time.sleep(3)

    # ── Save Results ──
    df_new = pd.DataFrame(all_papers) if all_papers else pd.DataFrame()
    raw_csv = RAW_DATA_DIR / "dosen_papers_scopus_raw.csv"

    if not df_new.empty:
        # Deduplicate results if multiple authors overlap on same papers
        if "eid" in df_new.columns:
            initial_count = len(df_new)
            df_new = df_new.drop_duplicates(subset=["eid"])
            if len(df_new) < initial_count:
                logger.info(f"      ✨ Deduplicated {initial_count - len(df_new)} overlapping papers.")

        df_new.to_csv(raw_csv, index=False)
        logger.info(f"\n✅ SUCCESS: Saved {len(df_new)} papers to {raw_csv}")
    else:
        pd.DataFrame().to_csv(raw_csv, index=False)
        logger.info("\n⚠️ No papers collected in this run.")

    return all_papers
