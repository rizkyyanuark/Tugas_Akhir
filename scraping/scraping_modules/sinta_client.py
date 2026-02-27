# scraping_modules/sinta_client.py
"""SINTA Crawler — crawls the SINTA website to extract Sinta IDs for lecturers."""

import time
import requests
from bs4 import BeautifulSoup
from .config import HEADERS, SINTA_DEPTS


class SintaCrawler:
    def __init__(self):
        self.base_headers = HEADERS.copy()
        self.base_headers["Referer"] = "https://sinta.kemdikbud.go.id/"

    def crawl_dept(self, prodi_name):
        url = SINTA_DEPTS.get(prodi_name)
        if not url or url == "IGNORE": return []
        
        profiles = []
        page = 1
        has_next = True
        print(f"   📂 Sinta Crawl: {prodi_name}")
        
        while has_next and page <= 5:
            try:
                target = f"{url}?page={page}"
                r = requests.get(target, headers=self.base_headers, timeout=10)
                if r.status_code != 200: break
                
                soup = BeautifulSoup(r.content, "html.parser")
                items = soup.find_all("div", class_="profile-name")
                
                if not items:
                    has_next = False
                    break
                    
                count = 0
                for item in items:
                    a = item.find("a")
                    if a:
                        name = a.get_text(strip=True)
                        link = a.get('href', '')
                        sid = link.split('/')[-1] if link else None
                        if sid and sid.isdigit():
                            profiles.append({
                                'name': name,
                                'sinta_id': str(sid),
                                'prodi': prodi_name
                            })
                            count += 1
                
                if count == 0: has_next = False
                page += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"      ❌ Error page {page}: {e}")
                has_next = False
        
        return profiles
