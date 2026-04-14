"""
Extract: Lecturers Profiles
===========================
Fetches lecturer data from Faculty Website and PDDikti API.
Provides the raw foundational data for the lecturer merging pipeline.
"""
import pandas as pd
from pathlib import Path

def extract_lecturers_web(target_configs, parser_map):
    """
    Scrape lecturer data from faculty websites.
    """
    try:
        import sys
        import os
        from pathlib import Path
        
        if os.path.exists("/app/notebooks/scraping"):
            scrape_dir = "/app/notebooks/scraping"
        else:
            scrape_dir = str(Path(__file__).resolve().parent.parent.parent.parent.parent.parent / "notebooks" / "scraping")
            
        if scrape_dir not in sys.path:
            sys.path.append(scrape_dir)
        from scraping_modules.web_scraper import WebProdiScraper
    except ImportError as e:
        print(f"❌ Failed to load WebProdiScraper: {e}")
        return []

    print("\n🌐 EXTRACT: FACULTY WEB SCRAPING")
    scraper = WebProdiScraper(parser_map)
    all_records = scraper.scrape(target_configs)
    
    print(f"📊 Total Web records extracted: {len(all_records)}")
    return all_records

def extract_lecturers_pddikti(target_configs):
    """
    Fetch lecturer data from PDDIKTI API.
    """
    try:
        import sys
        import os
        from pathlib import Path
        
        if os.path.exists("/app/notebooks/scraping"):
            scrape_dir = "/app/notebooks/scraping"
        else:
            scrape_dir = str(Path(__file__).resolve().parent.parent.parent.parent.parent.parent / "notebooks" / "scraping")
            
        if scrape_dir not in sys.path:
            sys.path.append(scrape_dir)
        from scraping_modules.pddikti_client import PddiktiClient
    except ImportError as e:
        print(f"❌ Failed to load PddiktiClient: {e}")
        return []

    print("\n📡 EXTRACT: PDDIKTI COLLECTION")
    client = PddiktiClient()
    all_records = client.search_lecturers(target_configs)
    
    print(f"📊 Total PDDIKTI records extracted: {len(all_records)}")
    return all_records
