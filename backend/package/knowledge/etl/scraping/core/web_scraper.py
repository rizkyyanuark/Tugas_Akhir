# scraping_modules/web_scraper.py
"""Web Prodi Scraper — scrapes lecturer data from UNESA departmental websites."""

import time
import requests
import urllib3
from bs4 import BeautifulSoup
from knowledge.etl.scraping.config import HEADERS, STRICT_AFFILIATION

# Disable SSL Warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class WebProdiScraper:
    def __init__(self, parser_map):
        self.headers = HEADERS
        self.parser_map = parser_map

    def scrape(self, active_configs):
        results = []
        print("\n🌐 STARTING WEB SCRAPING...")
        
        for cfg in active_configs:
            code, name, url, keyword, parser_key = cfg
            print(f"   🌍 Scraping: {name} ({url})")
            
            # Auto-Retry Mechanism (3 Attempts)
            max_retries = 3
            success = False
            
            for attempt in range(max_retries):
                try:
                    # Increased timeout to 90s to accommodate slow FMIPA subdomains
                    r = requests.get(url, headers=self.headers, timeout=90, verify=False)
                    r.raise_for_status()
                    success = True
                    break # Success!
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"      ⚠️ Attempt {attempt+1} failed: {e}. Retrying in 5s...")
                        time.sleep(5)
                    else:
                        print(f"      ❌ Failed after {max_retries} attempts: {e}")

            if not success: continue

            try:
                soup = BeautifulSoup(r.text, 'html.parser')
                parser_func = self.parser_map.get(parser_key)
                
                if parser_func:
                    entries = parser_func(soup)
                    valid_count = 0
                    for e in entries:
                        if e.get('nama_norm') and len(e['nama_norm']) > 3:
                            e.update({
                                'prodi_code': code,
                                'prodi_name': name,
                                'source_url': url,
                                'source': 'WEB_PRODI',
                                'affiliation': STRICT_AFFILIATION
                            })
                            results.append(e)
                            valid_count += 1
                    print(f"      ✅ Parsed: {valid_count}")
                else:
                    print(f"      ⚠️ No parser found for key: {parser_key}")
                    
            except Exception as e:
                print(f"      ❌ Error parsing: {e}")
                
        return results
