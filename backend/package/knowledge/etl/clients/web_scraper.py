# knowledge/etl/scraping/web_scraper.py
"""
Web Prodi Scraper
==================
Scrapes lecturer data from UNESA departmental websites.

Each study program has its own public /page/dosen endpoint.
The scraper fetches the page, delegates to the appropriate parser,
and returns a flat list of lecturer dicts ready for downstream merge.

Configuration:
    - HEADERS, CRAWLER_MAX_RETRIES, CRAWLER_TIMEOUT from config.py
    - Parser functions from parsers.py   PARSER_MAP
"""

import time
import requests
import urllib3
from bs4 import BeautifulSoup

from .config import HEADERS, STRICT_AFFILIATION, CRAWLER_MAX_RETRIES, CRAWLER_TIMEOUT

# Disable SSL warnings   some UNESA subdomains have expired certs.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class WebProdiScraper:
    """Scrape lecturer profiles from UNESA prodi websites."""

    def __init__(self, parser_map: dict):
        self.headers = HEADERS
        self.parser_map = parser_map

    def scrape(self, active_configs: list[tuple]) -> list[dict]:
        """
        Scrape all configured study programs and return a unified list.

        Args:
            active_configs: List of (code, name, url, keyword, parser_key) tuples
                            from PRODI_WEB_CONFIG.

        Returns:
            List of lecturer dicts with keys: nama_dosen, nama_norm, prodi_code,
            prodi_name, source_url, source, affiliation, etc.
        """
        results: list[dict] = []
        print("\n--- STARTING WEB SCRAPING ---")

        for code, name, url, keyword, parser_key in active_configs:
            print(f"     Scraping: {name} ({url})")
            html = self._fetch_with_retry(url)
            if html is None:
                continue

            try:
                soup = BeautifulSoup(html, "html.parser")
                parser_func = self.parser_map.get(parser_key)

                if not parser_func:
                    print(f"         No parser registered for key: {parser_key}")
                    continue

                entries = parser_func(soup)
                valid_count = 0
                for entry in entries:
                    if entry.get("nama_norm") and len(entry["nama_norm"]) > 3:
                        entry.update({
                            "prodi_code": code,
                            "prodi_name": name,
                            "source_url": url,
                            "source": "WEB_PRODI",
                            "affiliation": STRICT_AFFILIATION,
                        })
                        results.append(entry)
                        valid_count += 1
                print(f"        Parsed: {valid_count}")

            except Exception as e:
                print(f"        Error parsing: {e}")

        return results

    def _fetch_with_retry(self, url: str) -> str | None:
        """Fetch URL content with configurable retry logic."""
        for attempt in range(CRAWLER_MAX_RETRIES):
            try:
                resp = requests.get(
                    url,
                    headers=self.headers,
                    timeout=CRAWLER_TIMEOUT,
                    verify=False,
                )
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                if attempt < CRAWLER_MAX_RETRIES - 1:
                    wait = 5 * (attempt + 1)  # Progressive backoff: 5s, 10s, 15s
                    print(f"         Attempt {attempt + 1} failed: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"        Failed after {CRAWLER_MAX_RETRIES} attempts: {e}")
        return None
