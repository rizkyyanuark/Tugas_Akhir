# knowledge/etl/scraping/scival_client.py
"""
SciVal Client
==============
Automates SciVal (Elsevier) to find Scopus Author IDs for lecturers
who are missing this identifier. Uses Selenium for OAuth login flow.
"""

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

from .config import SAVE_DIR, SCIVAL_EMAIL, SCIVAL_PASS, CRAWLER_HEADLESS
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
            print("  SciVal Error: Credentials missing in config/json.")
            return None

        print("\n--- STARTING SCIVAL AUTOMATION ---")
        
        # A. RESUME LOGIC: Check for existing fresh file
        print("     Checking for existing SciVal export in save directory...")
        existing_files = sorted(self.save_dir.glob("All_Authors*.csv"), key=os.path.getmtime, reverse=True)
        if existing_files:
            newest = existing_files[0]
            # If file is less than 24 hours old, reuse it
            if time.time() - newest.stat().st_mtime < 86400:
                print(f"     Found fresh SciVal export: {newest.name} ({time.ctime(newest.stat().st_mtime)})")
                print("     Skipping Selenium automation.")
                return self.process_scival_csv(newest, df_main)
            else:
                print(f"      Found old export ({newest.name}), will download fresh one.")
        else:
            print("     No existing SciVal export found.")

        missing_count = (df_main['scopus_id'].isna() | (df_main['scopus_id'].astype(str).str.strip() == '')).sum()
        print(f"   Missing Scopus IDs to find: {missing_count}")
        
        driver = None
        try:
            # B. SETUP HEADLESS CHROME
            print("     Initializing Chrome Driver...")
            opts = Options()
            if CRAWLER_HEADLESS:
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
            
            # Use explicit CHROMEDRIVER_PATH if available (fixes Docker v146/v114 mismatch)
            chromedriver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
            if os.path.exists(chromedriver_path):
                service = Service(chromedriver_path)
            else:
                print("        Installing/Updating ChromeDriver...")
                service = Service(ChromeDriverManager().install())
            
            driver = webdriver.Chrome(service=service, options=opts)
            driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                "behavior": "allow", "downloadPath": str(self.save_dir.absolute())
            })
            
            # C. LOGIN
            print("     Logging into SciVal...")
            driver.get("https://id.elsevier.com/as/authorization.oauth2?platSite=SVE%2FSciVal&ui_locales=en-US&scope=openid+profile+email+els_auth_info+els_analytics_info&response_type=code&redirect_uri=https%3A%2F%2Fwww.scival.com%2Fidp%2Fcode&prompt=login&client_id=SCIVAL")
            
            try: 
                WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))).click()
                print("      (OK) Cookie banner accepted")
            except: pass
            
            try:
                print("         Entering Email...")
                email_field = WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.ID, "bdd-email")))
                email_field.clear(); email_field.send_keys(self.email)
                driver.find_element(By.ID, "bdd-elsPrimaryBtn").click()
            except Exception as e: print(f"      Email Step Error: {e}")
                
            try:
                print("         Entering Password...")
                pw_field = WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.ID, "bdd-password")))
                pw_field.send_keys(self.password)
                driver.find_element(By.ID, "bdd-elsPrimaryBtn").click()
                print("     Credentials Submitted")
            except Exception as e:
                print(f"     Login Failed (Check credentials or CAPTCHA): {e}")
                raise e
                
            print("     Waiting for redirect to SciVal dashboard...")
            WebDriverWait(driver, 60).until(EC.url_contains("scival.com"))
            print("   (OK) Login Success!")
            
            # D. NAVIGATE & DOWNLOAD
            print("     Navigating to Author Overview...")
            driver.get("https://www.scival.com/overview/authors?uri=Institution%2F707254")
            time.sleep(5)
            
            print("      Triggering CSV Download...")
            try:
                print("      Clicking download toggle...")
                btn = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.showDownloadFullListOfAuthors")))
                btn.click()
                time.sleep(3)
                
                print("      Selecting CSV format...")
                try: driver.find_element(By.XPATH, "//label[contains(text(), 'CSV')]").click()
                except: pass
                time.sleep(2)
                
                print("      Executing 'Download list' button...")
                try: driver.find_element(By.XPATH, "//button[contains(text(), 'Download list')]").click()
                except: print("      Could not click 'Download list'")
                
            except Exception as e:
                print(f"      Download UI Interaction Failed: {e}")
            
            # E. WAIT FOR FILE
            print("     Waiting for file to appear in save directory...")
            download_file = None
            start_time = time.time()
            while time.time() - start_time < 120:
                files = sorted(self.save_dir.glob("All_Authors*.csv"), key=os.path.getmtime, reverse=True)
                if files:
                    newest = files[0]
                    # Ensure it's the one we just (tried to) download
                    if newest.stat().st_mtime > start_time - 10:
                        if not str(newest).endswith(".crdownload"):
                            download_file = newest
                            break
                time.sleep(3)
                
            if download_file:
                print(f"   (OK) Download Successful: {download_file.name}")
                return self.process_scival_csv(download_file, df_main)
            else:
                print("     Error: Download timeout (No file appeared within 120s).")
                return None

        except Exception as e:
            print(f"     Automation Error: {e}")
            return None
        finally:
            if driver: driver.quit()

    def generate_initials_variant(self, full_name_norm):
        """
        Converts 'ibnu febry kurniawan' to 'i f kurniawan'
        to gracefully match SciVal's 'Kurniawan, I. F.' formatting logic.
        """
        tokens = full_name_norm.split()
        if len(tokens) < 2:
            return full_name_norm
        last_name = tokens[-1]
        initials = " ".join([t[0] for t in tokens[:-1] if t])
        return f"{initials} {last_name}"

    def process_scival_csv(self, csv_path, df_main):
        print("     Processing SciVal Data...")
        
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
            print("     Error: Columns not found in SciVal CSV.")
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
                    
        print(f"     Built lookup: {len(scival_map)} names")
        
        # Match
        count_new = 0
        count_corr = 0
        
        for idx, row in df_main.iterrows():
            norm = str(row['nama_norm']) if pd.notna(row['nama_norm']) else normalize_name(row['nama_dosen'])
            if not norm or norm == 'nan': continue
            
            found_sid = None
            match_info = ""
            
            # 1. Exact Full Name
            if norm in scival_map:
                found_sid = scival_map[norm]
                match_info = "EXACT"
            
            # 2. Exact Initials Variant
            initials_norm = self.generate_initials_variant(norm)
            if not found_sid and initials_norm in scival_map:
                found_sid = scival_map[initials_norm]
                match_info = "INITIALS_EXACT"

            # 3. Fuzzy Full Name
            if not found_sid:
                best, score, m = self.find_best_match(norm, scival_norms, threshold=0.85)
                if best:
                    found_sid = scival_map[best]
                    match_info = f"FUZZY ({score:.2f})"
                    
            # 4. Fuzzy Initials Variant
            if not found_sid:
                best, score, m = self.find_best_match(initials_norm, scival_norms, threshold=0.85)
                if best:
                    found_sid = scival_map[best]
                    match_info = f"INITIALS_FUZZY ({score:.2f})"
            
            if found_sid:
                curr_sid = str(row.get('scopus_id', '')).replace('.0','').strip()
                if curr_sid == 'nan' or not curr_sid:
                    df_main.at[idx, 'scopus_id'] = found_sid
                    count_new += 1
                    print(f"      (OK) {match_info}: {row['nama_dosen']} -> {found_sid}")
                elif curr_sid != found_sid:
                    df_main.at[idx, 'scopus_id'] = found_sid
                    count_corr += 1
                    print(f"        CORRECTED: {row['nama_dosen']} ({curr_sid} -> {found_sid})")

        print(f"   (OK) Stats: {count_new} New, {count_corr} Corrected.")
        return df_main
