# knowledge/etl/scraping/sinta_client.py
"""
SINTA Crawler
==============
Crawls the SINTA (Science and Technology Index) website to extract
Sinta IDs for lecturers, grouped by department.

Uses paginated author listing pages from sinta.kemdiktisaintek.go.id.
"""

import time
import requests
from bs4 import BeautifulSoup

from .config import HEADERS, SINTA_DEPTS, CRAWLER_TIMEOUT


class SintaCrawler:
    """Extract Sinta IDs from SINTA department author pages."""

    MAX_PAGES = 5  # Safety cap to avoid infinite pagination

    def __init__(self):
        self.base_headers = HEADERS.copy()
        self.base_headers["Referer"] = "https://sinta.kemdikbud.go.id/"

    def crawl_dept(self, prodi_name: str) -> list[dict]:
        """
        Crawl all pages of a department's SINTA author listing.

        Args:
            prodi_name: Study program name (must match key in SINTA_DEPTS).

        Returns:
            List of dicts with keys: name, sinta_id, prodi.
        """
        url = SINTA_DEPTS.get(prodi_name)
        if not url or url == "IGNORE":
            return []

        profiles: list[dict] = []
        print(f"     Sinta Crawl: {prodi_name}")

        for page in range(1, self.MAX_PAGES + 1):
            try:
                target = f"{url}?page={page}"
                resp = requests.get(target, headers=self.base_headers, timeout=CRAWLER_TIMEOUT)
                if resp.status_code != 200:
                    break

                soup = BeautifulSoup(resp.content, "html.parser")
                items = soup.find_all("div", class_="profile-name")

                if not items:
                    break

                count = 0
                for item in items:
                    a_tag = item.find("a")
                    if not a_tag:
                        continue
                    name = a_tag.get_text(strip=True)
                    link = a_tag.get("href", "")
                    sid = link.split("/")[-1] if link else None
                    if sid and sid.isdigit():
                        profiles.append({
                            "name": name,
                            "sinta_id": str(sid),
                            "prodi": prodi_name,
                        })
                        count += 1

                if count == 0:
                    break
                time.sleep(0.5)

            except Exception as e:
                print(f"        Error page {page}: {e}")
                break

        return profiles
