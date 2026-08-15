from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..clients.pddikti_client import PddiktiClient
from ..clients.web_scraper import WebProdiScraper

logger = logging.getLogger(__name__)


def extract_lecturers_web(target_configs: List[Dict[str, Any]], parser_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Scrape lecturer data from faculty websites using WebProdiScraper.

    Args:
        target_configs: List of configurations for target faculty/prodi pages.
        parser_map: Mapping of domains to parser functions.

    Returns:
        List of raw lecturer records extracted from web pages.
    """
    logger.info("Starting faculty web scraping...")
    
    try:
        scraper = WebProdiScraper(parser_map)
        all_records = scraper.scrape(target_configs)
        
        logger.info(f"Successfully extracted {len(all_records)} web records.")
        return all_records
    except Exception as e:
        logger.error(f"Failed to extract lecturers from web: {e}", exc_info=True)
        return []


def extract_lecturers_pddikti(target_configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Fetch lecturer data from PDDIKTI API using PddiktiClient.

    Args:
        target_configs: List of search configurations (prodi name, pt name, etc.)

    Returns:
        List of lecturer records from PDDIKTI.
    """
    logger.info("Starting PDDIKTI collection...")
    
    try:
        client = PddiktiClient()
        all_records = client.search_lecturers(target_configs)
        
        logger.info(f"Successfully extracted {len(all_records)} PDDIKTI records.")
        return all_records
    except Exception as e:
        logger.error(f"Failed to extract lecturers from PDDIKTI: {e}", exc_info=True)
        return []
