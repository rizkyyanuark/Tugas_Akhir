# scraping_modules/scopus_client.py
"""Scopus Paper Client — automates Scopus export to scrape academic papers."""

import os
import re
import time
import pandas as pd
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from .config import SAVE_DIR

def _flip_author_name(name):
    """Convert 'Last, First Middle' → 'First Middle Last'."""
    name = name.strip()
    if ',' in name:
        parts = name.split(',', 1)
        return f"{parts[1].strip()} {parts[0].strip()}"
    return name

class ScopusPaperClient:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.driver = None
        self.wait = None

    def setup_driver(self):
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new") 
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        prefs = {"download.default_directory": str(SAVE_DIR)}
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        self.wait = WebDriverWait(self.driver, 20)


    def login(self):
        try:
            print("📍 Logging in...")
            self.driver.get("https://id.elsevier.com/as/authorization.oauth2?platSite=SVE%2FSciVal&ui_locales=en-US&scope=openid+profile+email+els_auth_info+els_analytics_info&response_type=code&redirect_uri=https%3A%2F%2Fwww.scival.com%2Fidp%2Fcode&prompt=login&client_id=SCIVAL")
            
            try: WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))).click()
            except: pass
            
            email_field = self.wait.until(EC.visibility_of_element_located((By.ID, "bdd-email")))
            email_field.clear(); email_field.send_keys(self.email)
            self.driver.find_element(By.ID, "bdd-elsPrimaryBtn").click()
            
            pw_field = self.wait.until(EC.visibility_of_element_located((By.ID, "bdd-password")))
            pw_field.send_keys(self.password)
            self.driver.find_element(By.ID, "bdd-elsPrimaryBtn").click()
            
            self.wait.until(EC.url_contains("scival.com"))
            print("✅ Login Successful")
            return True
        except Exception as e:
            print(f"❌ Login Failed: {e}")
            return False

    def parse_text_content(self, content, author_id_context, cutoff_year=None):
        """Parses Scopus Plain Text Export with optional date filtering."""
        raw_records = content.split("SOURCE: Scopus")
        parsed_data = []

        for raw_rec in raw_records:
            rec = raw_rec.strip()
            if not rec: continue
            if rec.startswith("Scopus") and "EXPORT DATE:" in rec and len(rec) < 100: continue

            lines = [l.strip() for l in rec.split('\n') if l.strip()]
            if not lines: continue
            
            data = {
                'Scopus_Author_ID': author_id_context,
                'Authors': None, 'Author IDs': None,
                'Title': None, 'Year': None, 'Journal': None,
                'Link': None, 'Abstract': None, 'Keywords': None, 
                'Document Type': None, 'DOI': None
            }
            
            # --- PARSE YEAR EARLY FOR FILTERING ---
            year_val = None
            for i, line in enumerate(lines[:20]):
                m = re.match(r'^\((\d{4})\)', line)
                if m:
                    year_val = int(m.group(1))
                    break
            
            if cutoff_year and year_val and year_val <= cutoff_year:
                continue # Skip old paper
            
            # ... continue parsing ...
            
            # 1. Parse Labeled Fields
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
                    # Handle names & IDs
                    raw_auths = line[18:].strip()
                    parts = raw_auths.split(';')
                    
                    ids_found = []
                    names_only = []
                    for p in parts:
                         # Extraction: Name (ID)
                         m = re.search(r'(.*?)\s*\(\d+\)', p.strip())
                         if m:
                             name = m.group(1).strip()
                             # Remove trailing comma if exists (Name, F. (ID)) -> Name, F.
                             if name.endswith(','): name = name[:-1]
                             
                             aid = re.search(r'\((\d+)\)', p.strip()).group(1)
                             
                             ids_found.append(aid)
                             names_only.append(name)
                         else:
                             # Fallback if no ID found
                             clean = p.strip()
                             if clean:
                                names_only.append(clean)
                    
                    # Flip names to natural order: "First Last"
                    data['Authors'] = "; ".join(_flip_author_name(n) for n in names_only)
                    if ids_found:
                        data['Author IDs'] = "; ".join(ids_found)

            # 2. Parse Positional Fields
            year_idx = -1
            for i, line in enumerate(lines[:20]):
                if re.match(r'^\(\d{4}\)', line):
                    year_idx = i
                    break
            
            if year_idx > 0:
                # Year & Journal
                src_line = lines[year_idx]
                yd = re.match(r'^\((\d{4})\)', src_line)
                if yd:
                    data['Year'] = yd.group(1)
                    parts = src_line[len(yd.group(0)):].strip().split(',')
                    if parts: data['Journal'] = parts[0].strip()
                
                # Title is usually the line before Year
                # Check previous lines
                prev_1 = lines[year_idx - 1]
                
                # Heuristic: Title shouldn't be the Author IDs line
                if re.match(r'^[\d; ]+$', prev_1):
                    # If prev_1 is just IDs, look back one more
                     if year_idx > 1: data['Title'] = lines[year_idx - 2]
                else:
                    data['Title'] = prev_1

            # Fallback for Authors if AUTHOR FULL NAMES missing
            if not data['Authors'] and lines:
                # Assuming first line is authors (in "Last, First" format)
                if not lines[0].startswith("EXPORT DATE"):
                    raw_names = lines[0].split(';')
                    data['Authors'] = "; ".join(_flip_author_name(n) for n in raw_names)

            parsed_data.append(data)
        return parsed_data

    def restart_driver(self):
        print("      🔄 Restarting Driver...")
        try: self.driver.quit()
        except: pass
        self.setup_driver()
        self.login()

    def run_scraper(self, target_ids, cutoff_year=None):
        if not self.driver: self.setup_driver()
        if not self.login(): return

        all_papers = []
        
        from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

        for idx, scopus_id in enumerate(target_ids):
            print(f"   [{idx+1}/{len(target_ids)}] Processing ID: {scopus_id} (Cutoff: >{cutoff_year})")
            
            # Proactive driver restart every 10 iterations to prevent memory leaks / connection resets
            if idx > 0 and idx % 10 == 0:
                print("      🔄 Proactive driver restart (memory clearance)...")
                self.restart_driver()
            
            # Small buffer between profiles
            time.sleep(2)
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    url = f"https://www.scopus.com/authid/detail.uri?authorId={scopus_id}"
                    # ... navigation ...
                    self.driver.get(url)
                    time.sleep(1) # Let the initial JS load
                    break # Success, proceed to scraping
                except (InvalidSessionIdException, WebDriverException) as e:
                    print(f"      ⚠️ Driver Error (Attempt {attempt+1}/{max_retries}): {e}")
                    self.restart_driver()
                except Exception as e:
                    print(f"      ⚠️ Unexpected Error navigating to {scopus_id}: {e}")
                    break
            else:
                print(f"      ❌ Failed to load profile for {scopus_id} after retries.")
                continue

            try:
                    # Wait for page
                    try: self.wait.until(EC.presence_of_element_located((By.ID, "auth_name")))
                    except: pass
                    
                    # A. Click "Export all"
                    try:
                        export_all_btn = WebDriverWait(self.driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='Export all']]"))
                        )
                        export_all_btn.click()
                    except:
                        print(f"      ⚠️ No 'Export all' button (0 docs?)")
                        continue
                    
                    # B. Click "Plain text"
                    try:
                        plain_text_btn = WebDriverWait(self.driver, 10).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='export-to-plainText']"))
                        )
                        plain_text_btn.click()
                    except Exception as e:
                        print(f"      ⚠️ 'Plain text' failed: {e}")
                        continue
                    
                    # C. Optimized Strict Field Selection (v3 - Bulk Scan)
                    try:
                        # 1. Define Lists (IDs)
                        required_ids = {
                            "field_group_authors", "field_group_titles", "field_group_year", 
                            "field_group_eid", "field_group_sourceTitle", "field_group_sourceDocumentType", 
                            "field_group_doi", "field_group_abstact", "field_group_authorKeywords"
                        }
                        
                        # 2. Get All Checkboxes in Modal
                        checkboxes = self.driver.find_elements(By.CSS_SELECTOR, "label[aria-controls] input[type='checkbox'], label.Checkbox-module__jE3jb input[type='checkbox']")
                        
                        for cb in checkboxes:
                            try:
                                cid = cb.get_attribute("id")
                                is_checked = cb.is_selected()
                                
                                # Logic:
                                # - If ID in Required -> Check it
                                # - If ID NOT in Required (and not empty) -> Uncheck it (Implicit Forbidden)
                                # - If ID is empty (Parent Group checkbox?), we might want to uncheck to clear mess, but required might be inside.
                                #   Actually, Scopus Parent Groups often don't have IDs or have different structure.
                                #   Safe bet: Only touch inputs with known IDs.
                                
                                if not cid: continue 

                                if cid in required_ids:
                                    if not is_checked:
                                        self.driver.execute_script("arguments[0].click();", cb)
                                else:
                                    # Forbidden (All non-required IDs)
                                    if is_checked:
                                        self.driver.execute_script("arguments[0].click();", cb)
                                        
                            except: pass

                        # 3. Double Check Specific Critical Fields (Retry)
                        # Sometimes dynamic loading or group logic interferes.
                        time.sleep(0.5)
                        for rid in required_ids:
                            try:
                                cb = self.driver.find_element(By.ID, rid)
                                if not cb.is_selected():
                                    # Try robust click again
                                    self.driver.execute_script("arguments[0].click();", cb)
                                    # If abstract, try header fallback
                                    if rid == "field_group_abstact" and not cb.is_selected():
                                        header = self.driver.find_element(By.CSS_SELECTOR, "label[aria-controls*='field_group_abstact']")
                                        self.driver.execute_script("arguments[0].click();", header)
                            except: pass # If missing, likely fine or already handled
                            
                    except Exception as e:
                        print(f"      ⚠️ Field selection failed: {e}")
                                

                    # D. Submit
                    driver = self.driver # Alias
                    start_count = len(list(SAVE_DIR.glob("scopus*.txt")))
                    
                    try:
                        driver.find_element(By.CSS_SELECTOR, "button[data-testid='submit-export-button']").click()
                        print("      ⬇️ Export Submitted")
                    except Exception as e:
                        print(f"      ❌ Submit failed: {e}")
                        continue

                    # E. Wait for file
                    txt_file = None
                    start_wait = time.time()
                    
                    # Directories to check
                    check_dirs = [Path("/opt/airflow/data/scopus_temp"), Path("/tmp/scopus_downloads"), SAVE_DIR]
                    
                    while time.time() - start_wait < 90:
                        all_found_files = []
                        for d in check_dirs:
                            if d.exists():
                                all_found_files.extend(list(d.glob("scopus*.txt")))
                                
                        files = sorted(all_found_files, key=os.path.getmtime, reverse=True)
                        if files:
                            # Check if valid (not empty, not crdownload)
                            f = files[0]
                            if f.stat().st_size > 0 and (time.time() - f.stat().st_mtime) < 30:
                                txt_file = f
                                break
                        time.sleep(2)
                    
                    if txt_file:
                        time.sleep(1) # Ensure write complete
                        with open(txt_file, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        recs = self.parse_text_content(content, scopus_id, cutoff_year)
                        print(f"      ✅ Extracted {len(recs)} papers.")
                        all_papers.extend(recs)
                        
                        try: txt_file.unlink() # Cleanup
                        except: pass
                    else:
                        print("      ❌ Download timed out.")
                        
            except Exception as e:
                print(f"      ❌ Error: {e}")
                    
        return all_papers

def deduplicate_papers(df):
    """
    Deduplicates papers using a multi-stage approach:
    1. Deduplicate by Scopus ID (if valid)
    2. Deduplicate by DOI (if valid)
    3. Deduplicate by Title (Normalized) + Year
    """
    if df.empty: return df
    
    initial_count = len(df)
    print(f"   🧹 Deduplicating {initial_count} records...")
    
    # helper to clean years
    def clean_year(y):
        if pd.isna(y): return None
        s = str(y).replace('.0', '').strip()
        return s if s.isdigit() and len(s)==4 else None

    # 1. Normalize Columns
    df['clean_year'] = df['Year'].apply(clean_year)
    df['clean_title'] = df['Title'].astype(str).str.lower().str.strip().str.replace(r'[^\w\s]', '', regex=True)
    df['clean_doi'] = df['DOI'].astype(str).str.lower().str.strip()
    df['clean_scopus_id'] = df.get('scopus_id', pd.Series([None]*len(df))).astype(str).str.replace(r'\.0', '', regex=True)
    
    # 2. Prioritize rows with more info (DOI, Abstract, Year)
    # We create a score: +1 for DOI, +1 for Abstract, +1 for Year
    df['completeness'] = (df['DOI'].notna().astype(int) + 
                          df['Abstract'].notna().astype(int) + 
                          df['Year'].notna().astype(int))
    
    df = df.sort_values(['completeness', 'Year'], ascending=[False, False])
    
    # 3. STAGE A: Deduplicate by Scopus ID (if available)
    # Filter out empty/nan scopus ids
    # (Actually, in scraping output we might not have 'scopus_id' column, we have 'Link'?)
    # The scraper uses 'Link' like https://www.scopus.com/inward/record.uri...
    # Let's use 'Link' if Scopus ID is missing.
    
    # STAGE A: Deduplicate by DOI
    # Only if DOI is valid (contains '10.') and not 'nan'
    start_count = len(df)
    mask_doi = df['clean_doi'].str.contains('10.', na=False) & (df['clean_doi'] != 'nan')
    
    # Split into DOI-ed and Non-DOI-ed
    df_doi = df[mask_doi].drop_duplicates(subset=['clean_doi'], keep='first')
    df_no_doi = df[~mask_doi]
    
    df = pd.concat([df_doi, df_no_doi])
    print(f"      - DOI Deduplication: Removed {start_count - len(df)} rows")
    
    # STAGE B: Deduplicate by Link (EID)
    # The 'Link' contains the unique EID for a Scopus paper
    start_count = len(df)
    if 'Link' in df.columns:
        # Extract EID if possible or just use the whole link
        df['clean_link'] = df['Link'].astype(str).str.lower().str.strip()
        df = df.drop_duplicates(subset=['clean_link'], keep='first')
        df = df.drop(columns=['clean_link'])
    print(f"      - Link (EID) Deduplication: Removed {start_count - len(df)} rows")
    
    # STAGE C: Deduplicate by Title + Year
    start_count = len(df)
    # If Year is missing, we just use Title? strict=True means we require Title+Year match.
    # But usually, if Title is unique enough, Year might be typo.
    # Let's be aggressive: Deduplicate by Title ONLY, seeing if it removes valid different papers.
    # Scientific titles are usually unique. Exception: "Introduction", "Editorial", "Preface".
    # Filter out generic titles? For now, assume Title+Year is safest.
    
    # Handle missing year: fill with 'unknown'
    df['clean_year'] = df['clean_year'].fillna('unknown')
    
    df = df.drop_duplicates(subset=['clean_title', 'clean_year'], keep='first')
    print(f"      - Title+Year Deduplication: Removed {start_count - len(df)} rows")
    
    # Cleanup
    drop_cols = ['clean_year', 'clean_title', 'clean_doi', 'clean_scopus_id', 'completeness']
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])
    
    final_count = len(df)
    print(f"   ✅ Final Count: {final_count} (Removed {initial_count - final_count} total)")
    return df

def process_scopus_data(df):
    """
    Orchestrates the cleaning, deduplication, and enrichment of Scopus data.
    1. Deduplicates papers
    2. Flips author names (First Last)
    3. Enriches with TLDR from Semantic Scholar
    4. Filters to specific columns
    """
    if df.empty: return df

    # 1. Deduplicate
    df = deduplicate_papers(df)

    # 2. Clean Authors (Flip Name)
    print("🧹 Cleaning Author Names...")
    if 'Authors' in df.columns:
        df['Authors'] = df['Authors'].apply(
            lambda x: "; ".join([_flip_author_name(n) for n in str(x).split(';')]) if pd.notna(x) else x
        )

    # 3. Enrichment (TLDR)
    print("✨ Enriching with TLDR (Semantic Scholar)...")
    try:
        from .semantic_client import SemanticScholarClient
        s2_client = SemanticScholarClient()
        
        if 'TLDR' not in df.columns:
            df['TLDR'] = None
            
        total = len(df)
        modified_count = 0
        
        for idx, row in df.iterrows():
            # Skip if TLDR exists
            if pd.notna(row.get('TLDR')) and str(row.get('TLDR')).strip() != '':
                continue
                
            title = str(row.get('Title', ''))
            
            # Robust extraction
            try:
                pid = s2_client.search_paper_id(title)
                if pid:
                    details = s2_client.get_paper_details(pid) # Returns dict or None
                    if details:
                        tldr_obj = details.get('tldr')
                        if tldr_obj:
                            tldr_text = tldr_obj.get('text')
                            if tldr_text:
                                df.at[idx, 'TLDR'] = tldr_text
                                modified_count += 1
            except Exception as e:
                print(f"   ⚠️ Enrichment error for '{title[:20]}': {e}")
                
            # Rate limit handling is inside client, but adding small buffer here just in case
            if idx % 10 == 0: time.sleep(0.5)
            
        print(f"   ✅ Enriched {modified_count} papers with TLDR")
        
    except ImportError:
        print("   ⚠️ SemanticScholarClient not found, skipping enrichment.")
    except Exception as e:
        print(f"   ❌ Enrichment failed: {e}")

    # 4. Filter Columns
    print("✨ Filtering Columns...")
    target_cols = [
        'Authors', 'Author IDs', 'Title', 'Year', 'Journal', 
        'Link', 'Abstract', 'Keywords', 'Document Type', 'DOI', 'TLDR'
    ]
    existing_cols = [c for c in target_cols if c in df.columns]
    df_final = df[existing_cols].copy()
    
    return df_final
