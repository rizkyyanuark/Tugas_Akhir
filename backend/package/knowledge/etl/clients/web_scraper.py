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
import logging
import requests
import urllib3
from bs4 import BeautifulSoup

from ..config import (
    HEADERS, STRICT_AFFILIATION, CRAWLER_MAX_RETRIES, CRAWLER_TIMEOUT,
    BD_USER_UNLOCKER, BD_PASS_UNLOCKER, BRIGHT_DATA_HOST
)

# Disable SSL warnings (some UNESA subdomains have expired certs).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


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
        logger.info("Starting web scraping pipeline")

        for code, name, url, keyword, parser_key in active_configs:
            logger.info("Scraping: %s (%s)", name, url)
            html = self._fetch_with_retry(url)
            if html is None:
                continue

            try:
                soup = BeautifulSoup(html, "html.parser")
                parser_func = self.parser_map.get(parser_key)

                if not parser_func:
                    logger.error("No parser registered for key: %s", parser_key)
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
                logger.info("Parsed %d records from %s", valid_count, name)

            except Exception as e:
                logger.error("Error parsing %s: %s", url, e)

        return results

    def _fetch_with_retry(self, url: str) -> str | None:
        """Fetch URL content with configurable retry logic, using BrightData proxy to bypass IP blocks."""
        proxies = None
        if BD_USER_UNLOCKER and BD_PASS_UNLOCKER:
            proxy_url = f"http://{BD_USER_UNLOCKER}:{BD_PASS_UNLOCKER}@{BRIGHT_DATA_HOST}"
            proxies = {
                "http": proxy_url,
                "https": proxy_url
            }

        for attempt in range(CRAWLER_MAX_RETRIES):
            try:
                resp = requests.get(
                    url,
                    headers=self.headers,
                    proxies=proxies,
                    timeout=CRAWLER_TIMEOUT,
                    verify=False,
                )
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                if attempt < CRAWLER_MAX_RETRIES - 1:
                    wait = 5 * (attempt + 1)  # Progressive backoff: 5s, 10s, 15s
                    logger.warning("Attempt %d failed: %s. Retrying in %ds...", attempt + 1, e, wait)
                    time.sleep(wait)
                else:
                    logger.error("Failed after %d attempts: %s", CRAWLER_MAX_RETRIES, e)
        return None
