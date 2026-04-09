"""
Extract: Scopus Papers via SciVal/Selenium
==========================================
Fetches paper metadata from Scopus export function.
Requires `scopus_client.py` and Selenium webdriver.
"""
import pandas as pd
from pathlib import Path
from ta_backend_core.knowledge.etl.config import DATA_DIR, RAW_DATA_DIR, SCIVAL_EMAIL, SCIVAL_PASS

def extract_scopus_papers(limit_per_author=500, test_target_id=None):
    """
    Scrape papers from Scopus using ScopusPaperClient.
    Saved to data/raw/dosen_papers_scopus_raw.csv.
    """
    try:
        # Import dynamically to avoid selenium dependency loading if not used
        import sys
        sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent / "notebooks" / "scraping"))
        from scraping_modules.scopus_client import ScopusPaperClient
    except ImportError as e:
        print(f"❌ Failed to load ScopusClient: {e}")
        return []

    print("\n📚 EXTRACT: SCOPUS SCRAPING")
    
    # [LEVEL 3 ARCHITECTURE] Read targets directly from Supabase Database
    # This prevents FileNotFoundError and reduces dependency on data mounts.
    from ta_backend_core.knowledge.etl.load.supabase_loader import SupabaseLoader
    loader = SupabaseLoader()
    print("      🐳 Fetching Scopus IDs from Supabase instead of CSV...")
    
    response = loader.client.table("lecturers").select("scopus_id").execute()
    
    target_ids = []
    if test_target_id:
        target_ids = [test_target_id]
        print(f"🧪 RUNNING IN TEST MODE FOR ID: {test_target_id}")
    else:
        for r in response.data:
            sid = str(r.get("scopus_id", "")).strip().replace('.0', '')
            if sid and sid.lower() not in ("nan", "none", "null"):
                target_ids.append(sid)
                
        # Deduplicate
        target_ids = list(set(target_ids))
        
        # --- TEST LIMIT ---
        # Limit to 1 ID for testing to match user's previous manual override
        target_ids = target_ids[:1] 
        print(f"🧪 DEBUG: Limited to 1 ID for testing: {target_ids}")

    print(f"🎯 Found {len(target_ids)} Scopus IDs to scrape.")

    if not target_ids:
        return []

    # --- DOCKER COMPATIBILITY PATCH FUNCTION ---
    import os
    def apply_docker_patch(client_instance):
        if not (os.path.exists('/usr/bin/chromium') or os.path.exists('/usr/bin/chromium-browser')):
            return client_instance
            
        print("      🐳 Applying Docker Chromium Patch for session...")
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.support.ui import WebDriverWait

        def _docker_setup_driver(self_client):
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

            chrome_bin = '/usr/bin/chromium' if os.path.exists('/usr/bin/chromium') else '/usr/bin/chromium-browser'
            options.binary_location = chrome_bin

            temp_dir = "/app/data/scopus_temp"
            prefs = {
                "download.default_directory": temp_dir,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": False,
                "safebrowsing.disable_download_protection": True,
                "profile.default_content_settings.popups": 0
            }
            os.makedirs(temp_dir, exist_ok=True)
            options.add_experimental_option("prefs", prefs)
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)

            chromedriver_path = '/usr/bin/chromedriver'
            self_client.driver = webdriver.Chrome(service=Service(chromedriver_path), options=options)
            
            try:
                self_client.driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                    "behavior": "allow",
                    "downloadPath": temp_dir
                })
            except Exception as e:
                print(f"      ⚠️ CDP Page Download Error: {e}")
                
            self_client.wait = WebDriverWait(self_client.driver, 20)

        import types
        client_instance.setup_driver = types.MethodType(_docker_setup_driver, client_instance)
        try:
            import scraping_modules.config as sm_config
            sm_config.SAVE_DIR = Path("/app/data/scopus_temp")
        except Exception:
            pass
            
        return client_instance

    # --- BATCHED ISOLATED SESSIONS ---
    # We process in small batches (e.g. 5 IDs) to balance speed (less logins) 
    # and stability (restarting browser before memory/port crashes).
    all_papers = []
    BATCH_SIZE = 5
    
    for i in range(0, len(target_ids), BATCH_SIZE):
        batch = target_ids[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(target_ids) + BATCH_SIZE - 1) // BATCH_SIZE
        
        print(f"\n--- 🔄 Processing Batch [{batch_num}/{total_batches}]: {batch} ---")
        
        # Fresh client & driver for EACH BATCH to prevent DevTools memory crashes
        client = ScopusPaperClient(SCIVAL_EMAIL, SCIVAL_PASS)
        client = apply_docker_patch(client)
        
        try:
            # SciVal login happens once per batch
            papers = client.run_scraper(batch)
            if papers:
                all_papers.extend(papers)
                print(f"      ✅ Total accumulated: {len(all_papers)}")
        except Exception as e:
            print(f"      ❌ Fatal runtime error on batch {batch_num}: {e}")
        finally:
            try:
                if hasattr(client, 'driver') and client.driver:
                    client.driver.quit()
            except:
                pass
            
        # Short sleep to let the container OS recover ports
        import time
        if batch_num < total_batches:
            time.sleep(5)

    df_new = pd.DataFrame(all_papers) if all_papers else pd.DataFrame()
    raw_csv = RAW_DATA_DIR / "dosen_papers_scopus_raw.csv"
    
    if not df_new.empty:
        df_new.to_csv(raw_csv, index=False)
        print(f"\n✅ Saved {len(df_new)} new papers to {raw_csv}")
    else:
        pd.DataFrame().to_csv(raw_csv, index=False)
        print("\n⚠️ No new papers scraped.")

    return all_papers
