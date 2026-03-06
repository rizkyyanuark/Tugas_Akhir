# scraping_modules/scival_client.py
import re
import time
import os
import pandas as pd
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from .config import SAVE_DIR, SCIVAL_EMAIL, SCIVAL_PASS
from .utils import normalize_name, fuzzy_match_name

class SciValClient:
    def __init__(self):
        self.email = SCIVAL_EMAIL
        self.password = SCIVAL_PASS
        self.save_dir = SAVE_DIR

    def find_best_match(self, target, candidates, threshold=0.8):
        best = None
        best_score = 0
        method = "none"
        for cand in candidates:
            match, score, m = fuzzy_match_name(target, cand, threshold)
            if match and score > best_score:
                best_score = score
                best = cand
                method = m
        return best, best_score, method

    def run_automation(self, df_main):
        if not self.email or not self.password:
            print("❌ SciVal Error: Credentials missing in config/json.")
            return None

        print("\n🤖 STARTING SCIVAL AUTOMATION (Elsevier OAuth)...")
        missing_count = (df_main['scopus_id'].isna() | (df_main['scopus_id'].astype(str).str.strip() == '')).sum()
        print(f"   Missing Scopus IDs to find: {missing_count}")
        
        driver = None
        try:
            # B. SETUP HEADLESS CHROME
            opts = Options()
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--window-size=1920,1080") 
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            
            prefs = {
                "download.default_directory": str(self.save_dir.absolute()),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True
            }
            opts.add_experimental_option("prefs", prefs)
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=opts)
            driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                "behavior": "allow", "downloadPath": str(self.save_dir.absolute())
            })
            
            # C. LOGIN
            print("   📍 Logging into SciVal...")
            driver.get("https://id.elsevier.com/as/authorization.oauth2?platSite=SVE%2FSciVal&ui_locales=en-US&scope=openid+profile+email+els_auth_info+els_analytics_info&response_type=code&redirect_uri=https%3A%2F%2Fwww.scival.com%2Fidp%2Fcode&prompt=login&client_id=SCIVAL")
            
            try: WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))).click()
            except: pass
            
            try:
                email_field = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.ID, "bdd-email")))
                email_field.clear(); email_field.send_keys(self.email)
                driver.find_element(By.ID, "bdd-elsPrimaryBtn").click()
            except Exception as e: print(f"   ⚠️ Email Step Error: {e}")
                
            try:
                pw_field = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.ID, "bdd-password")))
                pw_field.send_keys(self.password)
                driver.find_element(By.ID, "bdd-elsPrimaryBtn").click()
                print("   ✅ Credentials Submitted")
            except Exception as e:
                print(f"   ❌ Login Failed: {e}")
                raise e
                
            WebDriverWait(driver, 60).until(EC.url_contains("scival.com"))
            print("   ✅ Login Success!")
            
            # D. NAVIGATE & DOWNLOAD
            print("   📍 Navigating to UNESA Author List...")
            driver.get("https://www.scival.com/overview/authors?uri=Institution%2F707254")
            time.sleep(5)
            
            print("   ⬇️ Triggering CSV Download...")
            try:
                btn = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.showDownloadFullListOfAuthors")))
                btn.click()
                time.sleep(2)
                
                try: driver.find_element(By.XPATH, "//label[contains(text(), 'CSV')]").click()
                except: pass
                time.sleep(1)
                
                try: driver.find_element(By.XPATH, "//button[contains(text(), 'Download list')]").click()
                except: print("   ⚠️ Could not click 'Download list'")
                
            except Exception as e:
                print(f"   ⚠️ Download UI Failed: {e}")
            
            # E. WAIT FOR FILE
            print("   ⏳ Waiting for file...")
            download_file = None
            start_time = time.time()
            while time.time() - start_time < 90:
                files = sorted(self.save_dir.glob("All_Authors*.csv"), key=os.path.getmtime, reverse=True)
                if not files: files = sorted(self.save_dir.glob("*.csv"), key=os.path.getmtime, reverse=True)
                
                if files:
                    newest = files[0]
                    if newest.stat().st_mtime > start_time - 15:
                        if not str(newest).endswith(".crdownload"):
                            download_file = newest
                            break
                time.sleep(2)
                
            if download_file:
                print(f"   ✅ Downloaded: {download_file.name}")
                return self.process_scival_csv(download_file, df_main)
            else:
                print("   ❌ Error: Download timeout.")
                return None

        except Exception as e:
            print(f"   ❌ Automation Error: {e}")
            return None
        finally:
            if driver: driver.quit()

    def process_scival_csv(self, csv_path, df_main):
        print("   🔄 Processing SciVal Data...")
        
        # 1. Skip Metadata
        header_idx = 0
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()
            for i, line in enumerate(lines[:30]):
                if "Name" in line and ("Scopus" in line or "Author ID" in line):
                    header_idx = i
                    break
        
        df_scival = pd.read_csv(csv_path, skiprows=header_idx, dtype=str)
        
        col_name = next((c for c in df_scival.columns if 'Name' in c), None)
        col_id = next((c for c in df_scival.columns if 'Scopus' in c and ('ID' in c or 'Author' in c) and 'link' not in c.lower()), None)
        
        if not col_name or not col_id:
            print("   ❌ Error: Columns not found in SciVal CSV.")
            return None

        # Build Lookup
        scival_map = {}
        scival_norms = []
        
        for _, s_row in df_scival.iterrows():
            raw_name = str(s_row[col_name]).strip('"').strip()
            sid = str(s_row[col_id])
            
            if pd.notna(raw_name) and pd.notna(sid):
                # Reverse "Last, First"
                if ',' in raw_name:
                    parts = raw_name.split(',', 1)
                    if len(parts) == 2:
                        raw_name = f"{parts[1].strip()} {parts[0].strip()}"
                        
                norm_nm = normalize_name(raw_name)
                # FIX: Handle Float String (e.g. "5720...0.0" -> "5720...0")
                sid_str = str(sid).strip()
                if sid_str.endswith('.0'):
                    sid_str = sid_str[:-2]
                clean_sid = re.sub(r'[^0-9]', '', sid_str)
                
                if clean_sid:
                    scival_map[norm_nm] = clean_sid
                    scival_norms.append(norm_nm)
                    
        print(f"   📊 Built lookup: {len(scival_map)} names")
        
        # Match
        count_new = 0
        count_corr = 0
        
        for idx, row in df_main.iterrows():
            norm = str(row['nama_norm']) if pd.notna(row['nama_norm']) else normalize_name(row['nama_dosen'])
            if not norm or norm == 'nan': continue
            
            found_sid = None
            match_info = ""
            
            # 1. Exact
            if norm in scival_map:
                found_sid = scival_map[norm]
                match_info = "EXACT"
            
            # 2. Fuzzy
            if not found_sid:
                best, score, m = self.find_best_match(norm, scival_norms, threshold=0.85)
                if best:
                    found_sid = scival_map[best]
                    match_info = f"FUZZY ({score:.2f})"
            
            if found_sid:
                curr_sid = str(row.get('scopus_id', '')).replace('.0','').strip()
                if curr_sid == 'nan' or not curr_sid:
                    df_main.at[idx, 'scopus_id'] = found_sid
                    count_new += 1
                    print(f"      ✅ {match_info}: {row['nama_dosen']} -> {found_sid}")
                elif curr_sid != found_sid:
                    df_main.at[idx, 'scopus_id'] = found_sid
                    count_corr += 1
                    print(f"      🔄 CORRECTED: {row['nama_dosen']} ({curr_sid} -> {found_sid})")

        print(f"   ✅ Stats: {count_new} New, {count_corr} Corrected.")
        return df_main
