"""
Extract: Lecturers Profiles
===========================
Fetches lecturer data from Faculty Website and PDDikti API.
Provides the raw foundational data for the lecturer merging pipeline.
"""
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def extract_lecturers_web(target_configs, parser_map):
    """
    Scrape lecturer data from faculty websites.

    Uses WebProdiScraper from the consolidated scraping package.
    No more sys.path hacks — the Docker image has PYTHONPATH=/app/package.
    """
    try:
        from knowledge.etl.scraping.web_scraper import WebProdiScraper
    except ImportError as e:
        logger.error(f"❌ Failed to load WebProdiScraper: {e}")
        return []

    logger.info("\n🌐 EXTRACT: FACULTY WEB SCRAPING")
    scraper = WebProdiScraper(parser_map)
    all_records = scraper.scrape(target_configs)

    logger.info(f"📊 Total Web records extracted: {len(all_records)}")
    return all_records


def extract_lecturers_pddikti(target_configs):
    """
    Fetch lecturer data from PDDIKTI API.

    Uses PddiktiClient from the consolidated scraping package.
    """
    try:
        from knowledge.etl.scraping.pddikti_client import PddiktiClient
    except ImportError as e:
        logger.error(f"❌ Failed to load PddiktiClient: {e}")
        return []

    logger.info("\n📡 EXTRACT: PDDIKTI COLLECTION")
    client = PddiktiClient()
    all_records = client.search_lecturers(target_configs)

    logger.info(f"📊 Total PDDIKTI records extracted: {len(all_records)}")
    return all_records
