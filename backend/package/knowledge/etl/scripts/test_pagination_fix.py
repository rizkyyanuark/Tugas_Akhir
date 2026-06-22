"""Test script to verify Google Scholar pagination fix on production.

Tests that the Scraping Browser approach correctly clicks "Show more"
and retrieves more than 20 papers for a scholar with many publications.

Test scholar: Yuni Yamasari (hn5jrnAAAAAJ) — has 60+ papers.
"""
import os
import sys
import logging
import time

# Adjust paths to load packages properly
sys.path.insert(0, "/app/package")
sys.path.insert(0, "backend/package")
sys.stdout.reconfigure(encoding='utf-8')

# Try loading .env from multiple typical paths
try:
    from dotenv import load_dotenv
    for p in [".env", "backend/.env", "../.env", "/app/.env"]:
        if os.path.exists(p):
            load_dotenv(p)
            print(f"Loaded .env from {p}")
            break
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

from knowledge.etl.clients.scholar_client import ScholarClient

print("=" * 60)
print("GOOGLE SCHOLAR PAGINATION FIX — VERIFICATION TEST")
print("=" * 60)

scholar_id = "hn5jrnAAAAAJ"  # Yuni Yamasari — 60+ papers
print(f"\nTest Scholar ID: {scholar_id}")
print(f"Expected: > 20 papers (should have 60+)")

client = ScholarClient()
print(f"\nStarting paper fetch (limit=200)...")
start = time.time()

papers = client.get_papers(scholar_id, limit=200)
elapsed = time.time() - start

status = client.last_fetch_status
print(f"\n{'=' * 60}")
print(f"RESULTS:")
print(f"  Papers fetched: {len(papers)}")
print(f"  Time elapsed: {elapsed:.1f}s")
print(f"  Method: {status.get('method', 'unknown') if status else 'unknown'}")
print(f"  Complete: {status.get('complete', 'unknown') if status else 'unknown'}")
print(f"  Reason: {status.get('reason', 'unknown') if status else 'unknown'}")
print(f"  Click count: {status.get('click_count', 'N/A') if status else 'N/A'}")

if len(papers) > 20:
    print(f"\n✅ SUCCESS: Retrieved {len(papers)} papers (> 20)")
else:
    print(f"\n❌ FAIL: Only {len(papers)} papers retrieved (expected > 20)")

# Print first and last few paper titles
if papers:
    print(f"\nFirst 3 papers:")
    for p in papers[:3]:
        print(f"  - {p['title'][:80]}")
    print(f"\nLast 3 papers:")
    for p in papers[-3:]:
        print(f"  - {p['title'][:80]}")

print(f"\n{'=' * 60}")
print("TEST COMPLETE")
print(f"{'=' * 60}")
