import sys
from pathlib import Path
import os

# Set up paths
PROJECT_ROOT = Path(r"c:\Users\rizky_11yf1be\Desktop\Tugas_Akhir")
sys.path.append(str(PROJECT_ROOT))

from notebooks.scraping.scraping_modules.keyword_scraper import search_scholar_proxy_query

def test_optimization():
    print("🚀 Testing Holistic Optimization...")
    
    # Test 1: Verify search_scholar_proxy_query redirects to HTML
    title = "Implementasi Algoritma C5. 0 Pada Klasifikasi Status Gizi Balita Menggunakan Metode E-Gizi"
    print(f"\n🔍 Searching for: {title[:50]}...")
    
    res = search_scholar_proxy_query(title)
    
    if res:
        print("\n✅ SEARCH SUCCESS")
        print(f"   Title  : {res.get('title_text')}")
        print(f"   Year   : {res.get('year')}")
        print(f"   Authors: {res.get('author_ids')}")
        print(f"   Link   : {res.get('title_link')}")
        
        if res.get('author_ids'):
            print("   ✨ PASS: Author IDs found! This will prevent the double-proxy search.")
        else:
            print("   ⚠️ WARN: No Author IDs found. Check if the authors have Scholar profiles.")
            
    else:
        print("\n❌ SEARCH FAILED or No Results.")

if __name__ == "__main__":
    test_optimization()
