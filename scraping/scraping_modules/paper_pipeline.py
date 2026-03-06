# scraping_modules/paper_pipeline.py
"""
Pipeline Scraping Paper Dosen Infokom UNESA
===========================================
Industry-grade modular pipeline for paper data acquisition.

Pipeline Flow:
    Step 1: run_scopus_scraping()      → dosen_papers_scopus.csv  (Scopus Export via Selenium)
    Step 2: run_scopus_processing()    → dosen_papers_scopus.csv  (Clean + Dedup + TLDR)
    Step 3: run_supabase_insert()      → Supabase DB (Upsert + Link)
    Step 4: run_scholar_scraping()     → dosen_papers_scholar_raw.csv (Scholar via SerpAPI)
    Step 5: run_scholar_enrichment()   → dosen_papers_scholar.csv (Keywords, Abstract, DOI, TLDR)

Each step reads from the previous step's output and produces its own output.
Notebook calls these functions directly — no logic in the notebook.
All credentials auto-loaded from config (credentials_new.json).
"""
import os
import re
import time
import random
import pandas as pd
from pathlib import Path
from difflib import SequenceMatcher

from .config import SAVE_DIR, SCIVAL_EMAIL, SCIVAL_PASS, SERPAPI_KEY

# --- FILE PATHS (Single Source of Truth) ---
DOSEN_CSV          = SAVE_DIR / "dosen_infokom_final.csv"
SCOPUS_CSV         = SAVE_DIR / "dosen_papers_scopus.csv"
SCOPUS_RAW_CSV     = SAVE_DIR / "dosen_papers_scopus_raw.csv"
SCHOLAR_RAW_CSV    = SAVE_DIR / "dosen_papers_scholar_raw.csv"
SCHOLAR_CSV        = SAVE_DIR / "dosen_papers_scholar.csv"


# ================================================================
# STEP 1: SCOPUS SCRAPING
# ================================================================
def run_scopus_scraping(email=None, password=None):
    """
    Scrape papers from Scopus for all lecturers with scopus_id.
    Uses ScopusPaperClient (Selenium) to download plain-text exports.
    Credentials auto-loaded from config if not provided.
    """
    email = email or SCIVAL_EMAIL
    password = password or SCIVAL_PASS
    from .scopus_client import ScopusPaperClient

    print("\n📚 STEP 1: SCOPUS SCRAPING")
    print("=" * 50)

    # 1. Load Target IDs
    if not DOSEN_CSV.exists():
        print(f"   ❌ '{DOSEN_CSV}' not found!")
        return

    df_dosen = pd.read_csv(DOSEN_CSV, dtype=str)
    target_ids = df_dosen['scopus_id'].dropna().unique().tolist()
    target_ids = [str(x).strip().replace('.0', '') for x in target_ids if x and str(x).strip() != 'nan']

    print(f"   🎯 Found {len(target_ids)} Scopus IDs to scrape.")

    # 2. Run Scraper
    client = ScopusPaperClient(email, password)
    papers = client.run_scraper(target_ids)

    # 3. Save Raw Data
    df_new = pd.DataFrame(papers) if papers else pd.DataFrame()
    
    if not df_new.empty:
        df_new.to_csv(SCOPUS_RAW_CSV, index=False)
        print(f"   ✅ Saved {len(df_new)} new papers to {SCOPUS_RAW_CSV}")
    else:
        # Create empty raw file to avoid errors in Step 2 if no new papers
        pd.DataFrame().to_csv(SCOPUS_RAW_CSV, index=False)
        print("   ⚠️ No new papers scraped.")

    return df_new


# ================================================================
# STEP 2: SCOPUS PROCESSING (Clean + Dedup + TLDR Enrichment)
# ================================================================
def run_scopus_processing(input_raw=None, output_master=None):
    """
    Process Scopus data: Merge raw with master, Clean, Deduplicate, Enrich with TLDR.
    """
    from .scopus_client import process_scopus_data

    print("\n🔧 STEP 2: SCOPUS PROCESSING")
    print("=" * 50)

    raw_file = Path(input_raw) if input_raw else SCOPUS_RAW_CSV
    master_file = Path(output_master) if output_master else SCOPUS_CSV

    # 1. Load Raw (New) Data
    if not raw_file.exists():
        print(f"   ❌ Raw file not found: {raw_file}. Run Step 1 first.")
        return
    df_raw = pd.read_csv(raw_file, dtype=str).fillna("")

    # 2. Load Master (Existing) Data
    if master_file.exists():
        print(f"   📂 Loading Master Database: {master_file}")
        df_master = pd.read_csv(master_file, dtype=str).fillna("")
    else:
        print("   📂 No Master Database found. Starting fresh.")
        df_master = pd.DataFrame()

    # 3. Merge
    print(f"   🔄 Merging: New ({len(df_raw)}) + Master ({len(df_master)})")
    df_combined = pd.concat([df_master, df_raw], ignore_index=True)

    if df_combined.empty:
        print("   ⚠️ No data to process.")
        return

    # 4. Process (Clean -> Dedup -> Enrich -> Filter)
    print("   🚀 Starting Processing Pipeline...")
    df_final = process_scopus_data(df_combined)

    # 5. Save Final
    df_final.to_csv(master_file, index=False)
    print(f"   ✅ Saved {len(df_final)} clean & enriched papers to {master_file}")
    
    # Optional: Delete raw file after successful processing to prevent re-merging
    try:
        raw_file.unlink()
        print(f"   🧹 Cleaned up raw file: {raw_file.name}")
    except:
        pass

    return df_final


# ================================================================
# STEP 3: SUPABASE INSERT (Upsert + Link to Lecturers)
# ================================================================
def run_supabase_insert():
    """
    Upsert papers to Supabase and link them to lecturers via Author IDs.
    """
    from .supabase_client import SupabaseClient

    print("\n🚀 STEP 3: SUPABASE INSERT")
    print("=" * 50)

    csv_path = SCOPUS_CSV
    if not csv_path.exists():
        print(f"   ❌ File not found: {csv_path}")
        return

    print("   📂 Loading Cleaned Papers...")
    df = pd.read_csv(csv_path, dtype=str)
    print(f"   📝 Total Rows: {len(df)}")

    try:
        client = SupabaseClient()

        # 1. Upsert Papers
        print("\n   🚀 Upserting Papers to Supabase...")
        client.upsert_papers(df)

        # 2. Link Papers to Lecturers
        print("\n   🔗 Linking Papers to Lecturers...")
        client.link_papers_to_lecturers(df)

        print("\n   ✅ Insertion & Linking Complete!")

    except Exception as e:
        print(f"   ❌ Database Error: {e}")


# ================================================================
# STEP 4: GOOGLE SCHOLAR SCRAPING (via SerpAPI)
# ================================================================

def _normalize_text(text):
    """Normalize text for consistent comparison."""
    if pd.isna(text): return ""
    return str(text).lower().strip().replace(' ', '')


def _is_similar(title1, title2, threshold=0.90):
    """Check if two titles are similar using SequenceMatcher."""
    t1 = _normalize_text(title1)
    t2 = _normalize_text(title2)
    if not t1 or not t2: return False
    if t1 == t2 or t1 in t2 or t2 in t1: return True
    return SequenceMatcher(None, t1, t2).ratio() >= threshold


def _serpapi_fetch_author(api_key, scholar_id, start=0, num=100):
    """
    Fetch one page of Google Scholar Author articles via SerpAPI.
    Returns (articles_list, has_next_page).
    """
    import requests

    params = {
        "engine": "google_scholar_author",
        "author_id": scholar_id,
        "api_key": api_key,
        "hl": "en",
        "start": start,
        "num": num,
        "sort": "pubdate",
    }

    try:
        resp = requests.get(
            "https://serpapi.com/search.json",
            params=params, timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            articles = data.get("articles", [])
            has_next = "next" in data.get("serpapi_pagination", {})
            return articles, has_next
        else:
            error = resp.json().get("error", resp.text[:200])
            print(f"      ⚠️ SerpAPI HTTP {resp.status_code}: {error}")
            return [], False
    except Exception as e:
        print(f"      ⚠️ SerpAPI Error: {e}")
        return [], False


def run_scholar_scraping(api_key=None, limit_per_author=300):
    """
    Scrape papers from Google Scholar via SerpAPI (google_scholar_author engine).
    Saves raw data to dosen_papers_scholar_raw.csv.
    Cross-deduplicates against existing Scopus papers.

    Output columns (consistent with Scopus CSV):
        Authors, Author IDs, Title, Year, Journal, Link,
        Abstract, Keywords, Document Type, DOI, TLDR,
        scholar_id, dosen, source
    """
    api_key = api_key or SERPAPI_KEY
    if not api_key:
        print("   ❌ SERPAPI_KEY not configured! Add to credentials_new.json.")
        return

    print("\n📖 STEP 4: GOOGLE SCHOLAR SCRAPING (SerpAPI)")
    print("=" * 50)

    # --- 1. Load Dosen Data ---
    if not DOSEN_CSV.exists():
        print(f"   ❌ '{DOSEN_CSV}' not found!")
        return

    df_dosen = pd.read_csv(DOSEN_CSV, dtype=str)
    targets = [
        {"id": str(r["scholar_id"]).strip(), "name": r["nama_dosen"]}
        for _, r in df_dosen.iterrows()
        if str(r.get("scholar_id", "")).strip() not in ("", "nan", "NaN")
    ]
    print(f"   🎯 {len(targets)} dosen with Scholar ID.\n")

    # --- 2. Scrape All via SerpAPI ---
    all_papers = []
    total_api_calls = 0

    for i, t in enumerate(targets):
        print(f"[{i+1}/{len(targets)}] {t['name']} ({t['id']})...")
        start = 0
        author_papers = []

        while len(author_papers) < limit_per_author:
            print(f"      📡 SerpAPI page start={start}...")
            articles, has_next = _serpapi_fetch_author(
                api_key, t["id"], start=start, num=100
            )
            total_api_calls += 1

            if not articles:
                break

            for art in articles:
                author_papers.append({
                    # --- Scopus-consistent columns ---
                    "Authors": art.get("authors", ""),
                    "Author IDs": "",          # enriched in Step 5
                    "Title": art.get("title", ""),
                    "Year": str(art.get("year", "")),
                    "Journal": art.get("publication", ""),
                    "Link": art.get("link", ""),
                    "Abstract": "",             # enriched in Step 5
                    "Keywords": "",             # enriched in Step 5
                    "Document Type": "",        # enriched in Step 5
                    "DOI": "",                  # enriched in Step 5
                    "TLDR": "",                 # enriched in Step 5
                    # --- Scholar metadata ---
                    "citation_id": art.get("citation_id", ""),
                    "scholar_id": t["id"],
                    "dosen": t["name"],
                    "source": "scholar",
                })

            if not has_next or len(articles) < 100:
                break  # Last page

            start += 100
            time.sleep(0.3)  # Polite delay

        print(f"      ✅ {len(author_papers)} papers")
        all_papers.extend(author_papers)
        time.sleep(0.2)

    print(f"\n   📊 Total scraped: {len(all_papers)} papers ({total_api_calls} API calls)")

    if not all_papers:
        print("   ⚠️ No papers found.")
        return

    # --- 3. Internal Deduplication ---
    df_scholar = pd.DataFrame(all_papers)
    before = len(df_scholar)
    df_scholar = df_scholar.drop_duplicates(subset=["Title"], keep="first")
    print(f"   🧹 Internal dedup: {before} → {len(df_scholar)} (dropped {before - len(df_scholar)})")

    # --- 4. Cross-Deduplication with Scopus ---
    if SCOPUS_CSV.exists():
        df_scopus = pd.read_csv(SCOPUS_CSV)
        scopus_titles = df_scopus["Title"].dropna().tolist()
        scopus_set = {_normalize_text(t) for t in scopus_titles}

        keep_mask = []
        drop_count = 0
        for _, row in df_scholar.iterrows():
            title = row["Title"]
            n_title = _normalize_text(title)

            if n_title in scopus_set:
                keep_mask.append(False); drop_count += 1; continue

            dup = False
            for st in scopus_titles:
                if _is_similar(title, st):
                    dup = True; break
            keep_mask.append(not dup)
            if dup: drop_count += 1

        df_scholar = df_scholar[keep_mask].reset_index(drop=True)
        print(f"   🗑️ Scopus dedup: dropped {drop_count}, remaining {len(df_scholar)}")

    # --- 5. Save Raw ---
    df_scholar.to_csv(SCHOLAR_RAW_CSV, index=False)
    print(f"\n   ✅ Saved {len(df_scholar)} unique Scholar papers → {SCHOLAR_RAW_CSV}")

    return df_scholar


# ================================================================
# STEP 5: SCHOLAR ENRICHMENT (Keywords, Abstract, DOI, TLDR)
# ================================================================

def run_scholar_enrichment(input_csv=None, output_csv=None):
    """
    Enrich Scholar papers with Keywords, Abstract, DOI, TLDR, and Author IDs.

    New Prioritized Flow (3-Phase Cascading Extraction):
        0. Data Cleaning: Capitalize each word in Title.
        1. Semantic Scholar API: Try to get Abstract, DOI, TLDR, DocType, and PDF/Pub links (Fast & Free).
        2. Google Scholar Search: Always run to extract `author_ids` and fallback metadata (Proxy: 1 call).
        3. Web/PDF Deep Scraping: ONLY run if `keywords` or `abstract` are missing.

    Input:  dosen_papers_scholar_raw.csv (from Step 4)
    Output: dosen_papers_scholar.csv (enriched)
    """
    from .keyword_scraper import (
        scrape_publisher_page,
        search_scholar_proxy_query,
        extract_doi,
        _crossref_lookup,
    )
    from .semantic_client import fetch_s2_details
    from difflib import SequenceMatcher

    input_file = Path(input_csv) if input_csv else SCHOLAR_RAW_CSV
    output_file = Path(output_csv) if output_csv else SCHOLAR_CSV
    
    # Load Dosen mapping
    dosen_csv_path = Path(__file__).parent.parent / "file_tabulars" / "dosen_infokom_final.csv"
    dosen_map = {}
    if dosen_csv_path.exists():
        try:
            df_dosen = pd.read_csv(dosen_csv_path)
            for _, r in df_dosen.iterrows():
                sid = str(r.get("scholar_id", "")).strip()
                n_norm = str(r.get("nama_norm", "")).strip()
                if sid and n_norm:
                    dosen_map[sid] = n_norm
        except Exception as e:
            print(f"   ⚠️ Could not load dosen CSV: {e}")

    print("\n🔬 STEP 5: SCHOLAR ENRICHMENT (S2 → Google Scholar → Deep Scraping)")
    print("=" * 70)

    if not input_file.exists():
        print(f"   ❌ '{input_file}' not found! Run Step 4 first.")
        return

    df = pd.read_csv(input_file, dtype=str).fillna("")
    total = len(df)
    print(f"   📋 Loaded {total} papers from {input_file.name}")

    # Make sure new columns exist
    for col in ["Abstract", "Keywords", "DOI", "TLDR", "Document_Type", "Journal", "Year", "Author_Ids"]:
        if col not in df.columns:
            df[col] = ""

    # --- Stats ---
    success_kw = 0
    success_abs = 0
    success_doi = 0
    success_tldr = 0
    success_auth = 0
    crossref_hits = 0

    for i, row in df.iterrows():
        # --- 0. Data Cleaning (Title Capitalization) ---
        raw_title = str(row.get("Title", "")).strip()
        title = raw_title.title()
        if title != raw_title:
            df.at[i, "Title"] = title
            
        abstract = str(row.get("Abstract", "")).strip()
        keywords = str(row.get("Keywords", "")).strip()
        doi = str(row.get("DOI", "")).strip()
        tldr = str(row.get("TLDR", "")).strip()
        doc_type = str(row.get("Document_Type", "")).strip()
        journal = str(row.get("Journal", "")).strip()
        year = str(row.get("Year", "")).strip()
        author_ids = str(row.get("Author_Ids", "")).strip()
        
        link = str(row.get("Link", "")).strip()
        pdf_link = None
        publisher_link = link if link else None

        print(f"\n[{i+1}/{total}] {title[:70]}...")
        time.sleep(1) # Gentle base pacing

        # ==========================================================
        # PHASE 1: SEMANTIC SCHOLAR + PUBLISHER SCRAPING
        # ==========================================================
        # S2 memberi: DOI, Abstract, TLDR, DocType, Open Access PDF
        # S2 TIDAK memberi: Keywords & publisher_link (url nya = S2 page)
        # Jadi: jika DOI/PDF ada → langsung scrape publisher untuk Keywords
        print(f"   ⏳ [Phase 1] Semantic Scholar API...")
        s2_data = fetch_s2_details(doi=doi if doi else None, title=title)
        
        if s2_data:
            if not tldr and s2_data.get('tldr'): 
                tldr = s2_data['tldr'].get('text', '')
                print(f"      ✅ [S2] TLDR: {tldr[:60]}...")
            if not abstract and s2_data.get('abstract'):
                abstract = s2_data['abstract']
                print(f"      ✅ [S2] Abstract: {abstract[:60]}...")
            if not doi and s2_data.get('externalIds', {}).get('DOI'):
                doi = s2_data['externalIds']['DOI']
                print(f"      ✅ [S2] DOI: {doi}")
            if not doc_type and s2_data.get("publicationTypes"):
                doc_type = ", ".join(s2_data["publicationTypes"])
                print(f"      ✅ [S2] DocType: {doc_type}")
                
            if s2_data.get('openAccessPdf') and s2_data['openAccessPdf'].get('url'):
                pdf_link = s2_data['openAccessPdf']['url']
            # NOTE: s2_data.get('url') = halaman S2, BUKAN publisher. Tidak disimpan.
        else:
            print(f"      ❌ [S2] Data tidak ditemukan.")

        # --- Phase 1 Scraping: Langsung ambil Keywords dari publisher ---
        if not keywords and (pdf_link or doi):
            print(f"      ⏳ [S2→Scrape] Mencoba ambil Keywords dari publisher...")
            scrape_links = []
            # DOI dulu (publisher HTML = terstruktur), PDF terakhir (2-kolom campur teks)
            if doi: scrape_links.append(("DOI", f"https://doi.org/{doi}"))
            if pdf_link: scrape_links.append(("PDF", pdf_link))
            
            seen_urls = set()
            for link_type, scrape_url in scrape_links:
                if scrape_url in seen_urls: continue
                seen_urls.add(scrape_url)
                print(f"         >> Scraping {link_type} ({scrape_url[:60]}...)")
                scrape_result = scrape_publisher_page(scrape_url, force_proxy=False)
                
                if scrape_result.get("keywords") and not keywords:
                    keywords = scrape_result["keywords"]
                    print(f"         ✅ Keywords (Author): {keywords[:60]}...")
                if scrape_result.get("abstract") and not abstract:
                    abstract = scrape_result["abstract"]
                    print(f"         ✅ Abstract: {'Ada (' + str(len(abstract)) + ' chars)'}")
                if scrape_result.get("doi") and not doi:
                    doi = scrape_result["doi"]
                    print(f"         ✅ DOI: {doi}")
                if keywords and abstract:
                    break

        # ==========================================================
        # PHASE 2: OPENALEX API (Author IDs, DOI, Abstract)
        # ==========================================================
        # OpenAlex bisa punya Abstract & DOI yang S2 tidak punya.
        # Keywords OpenAlex = Concepts (generated), BUKAN dari penulis.
        # Simpan sebagai fallback, pakai hanya jika publisher scraping gagal.
        oa_keywords_fallback = ""
        if not author_ids or not keywords or not doc_type or not abstract or not doi:
            print(f"   ⏳ [Phase 2] OpenAlex API Lookup (Author IDs, DOI, Abstract)...")
            from .keyword_scraper import _openalex_lookup
            oa_doi_before = doi  # Simpan DOI sebelum OpenAlex
            oa_data = _openalex_lookup(doi=doi if doi else None, title=title)
            if oa_data:
                extracted_ids = oa_data.get('author_ids', [])
                if extracted_ids and not author_ids:
                    author_ids = ";".join(extracted_ids)
                    print(f"      ✅ [OpenAlex] Author IDs: {author_ids}")
                
                # Keywords DISIMPAN DULU, tidak langsung dipakai
                extracted_kw = oa_data.get('keywords', '')
                if extracted_kw:
                    oa_keywords_fallback = extracted_kw
                    print(f"      📋 [OpenAlex] Keywords (Concepts) disimpan sebagai fallback")
                    
                extracted_type = oa_data.get('doc_type', '')
                if extracted_type and not doc_type:
                    doc_type = extracted_type
                    print(f"      ✅ [OpenAlex] DocType: {doc_type}")
                    
                extracted_doi = oa_data.get('doi', '')
                if extracted_doi and not doi:
                    doi = extracted_doi
                    print(f"      ✅ [OpenAlex] DOI: {doi}")
                    
                extracted_abs = oa_data.get('abstract', '')
                if extracted_abs and not abstract:
                    abstract = extracted_abs
                    print(f"      ✅ [OpenAlex] Abstract: {'Ada (' + str(len(abstract)) + ' chars)'}")
                
                # --- Scraping via OpenAlex links: PDF → Landing → DOI ---
                if not keywords:
                    oa_scrape_links = []
                    # Prioritas 1: Direct PDF dari OpenAlex
                    oa_pdf = oa_data.get('oa_pdf_url', '')
                    if oa_pdf:
                        oa_scrape_links.append(("OA-PDF", oa_pdf))
                    # Prioritas 2: Landing page dari OpenAlex  
                    oa_landing = oa_data.get('oa_landing_url', '')
                    if oa_landing:
                        oa_scrape_links.append(("OA-Landing", oa_landing))
                    # Prioritas 3: DOI redirect (jika baru dari OpenAlex)
                    if doi and doi != oa_doi_before:
                        oa_scrape_links.append(("DOI", f"https://doi.org/{doi}"))
                    
                    # Dedupe
                    seen = set()
                    for ltype, lurl in oa_scrape_links:
                        if lurl in seen: continue
                        seen.add(lurl)
                        print(f"      ⏳ [OpenAlex→Scrape] {ltype} ({lurl[:60]}...)")
                        scrape_result = scrape_publisher_page(lurl, force_proxy=False)
                        if scrape_result.get("keywords") and not keywords:
                            keywords = scrape_result["keywords"]
                            print(f"         ✅ Keywords (Author): {keywords[:60]}...")
                        if scrape_result.get("abstract") and not abstract:
                            abstract = scrape_result["abstract"]
                            print(f"         ✅ Abstract: {'Ada (' + str(len(abstract)) + ' chars)'}")
                        if keywords:
                            break
            else:
                print(f"      ❌ [OpenAlex] Data tidak ditemukan.")
        else:
            print(f"   ⏭️ [Phase 2] Dilewati (Author IDs, Keywords, DOI lengkap).")

        # --- Fallback: Pakai keywords OpenAlex jika scraping gagal ---
        if not keywords and oa_keywords_fallback:
            keywords = oa_keywords_fallback
            print(f"   📋 [Fallback] Pakai OpenAlex Concepts: {keywords[:60]}...")

        # ==========================================================
        # PHASE 4: GOOGLE SCHOLAR SEARCH (Strict Fallback Lengkap)
        # ==========================================================
        if not author_ids or not abstract or not keywords or not doi:
            print(f"   ⏳ [Phase 4] Google Scholar Search (Strict Fallback Lengkap)...")
            sh_data = search_scholar_proxy_query(title)
            if sh_data:
                extracted_ids = sh_data.get('author_ids', [])
                if extracted_ids and not author_ids:
                    mapped_ids = []
                    for eid in extracted_ids:
                        if eid in dosen_map:
                            mapped_ids.append(f"{dosen_map[eid]} ({eid})")
                    if mapped_ids:
                        author_ids = ";".join(mapped_ids)
                        print(f"      ✅ [Scholar] Mapped Author IDs: {author_ids}")
                    else:
                        print(f"      ❌ [Scholar] Author IDs tercantum tapi tidak match di dosen_infokom_final.csv.")
                
                # Simpan snippet sebagai fallback (jangan set abstract dulu)
                snippet_fallback = sh_data.get('snippet', '')
                
                curr_kw = sh_data.get('keywords', '')
                if not keywords and curr_kw:
                    keywords = curr_kw
                    print(f"      ✅ [Scholar] Keywords Fallback: {keywords[:60]}...")
                
                # --- Scrape Scholar's publisher/PDF/cached links ---
                # Urutan: Publisher & PDF dulu (aman, tanpa proxy),
                # Google Cache terakhir (risiko blocking, pakai proxy)
                sch_links = []
                if sh_data.get('title_link'):
                    sch_links.append(("Scholar-Publisher", sh_data['title_link'], False))
                if sh_data.get('pdf_link'):
                    sch_links.append(("Scholar-PDF", sh_data['pdf_link'], False))
                if sh_data.get('html_direct'):
                    sch_links.append(("Scholar-HTML", sh_data['html_direct'], False))
                # Cache terakhir, pakai proxy agar IP tidak diblokir Google
                if sh_data.get('cached_html'):
                    sch_links.append(("Scholar-Cache", sh_data['cached_html'], True))
                
                if sch_links and (not keywords or not abstract):
                    seen_urls = set()
                    for ltype, lurl, use_proxy in sch_links:
                        if lurl in seen_urls: continue
                        seen_urls.add(lurl)
                        print(f"      ⏳ [{ltype}] Scraping ({lurl[:55]}...)")
                        scrape_result = scrape_publisher_page(lurl, force_proxy=use_proxy)
                        if scrape_result.get("keywords") and not keywords:
                            keywords = scrape_result["keywords"]
                            print(f"         ✅ Keywords: {keywords[:60]}...")
                        if scrape_result.get("abstract") and not abstract:
                            abstract = scrape_result["abstract"]
                            print(f"         ✅ Abstract: Ada ({len(abstract)} chars)")
                        if scrape_result.get("doi") and not doi:
                            doi = scrape_result["doi"]
                            print(f"         ✅ DOI: {doi}")
                        if keywords and abstract:
                            break
                
                # Fallback: pakai snippet jika abstract masih kosong
                if not abstract and snippet_fallback:
                    abstract = snippet_fallback
                    print(f"      📋 [Scholar] Abstract (snippet fallback): {abstract[:60]}...")
                
                if not journal and sh_data.get('journal'): journal = sh_data['journal']
                if not year and sh_data.get('year'): year = str(sh_data['year'])
        else:
            print(f"   ⏭️ [Phase 4] Dilewati (Semua data kunci lengkap).")

        # --- Update DataFrame ---
        df.at[i, "Abstract"] = abstract
        df.at[i, "Keywords"] = keywords
        df.at[i, "DOI"] = doi
        df.at[i, "TLDR"] = tldr
        df.at[i, "Document_Type"] = doc_type
        df.at[i, "Journal"] = journal
        df.at[i, "Year"] = year
        df.at[i, "Author_Ids"] = author_ids

        # Stats
        if abstract: success_abs += 1
        if keywords: success_kw += 1
        if doi: success_doi += 1
        if tldr: success_tldr += 1
        if author_ids: success_auth += 1

        # Progress save every 5 papers
        if (i + 1) % 5 == 0:
            df.to_csv(output_file, index=False)
            print(f"\n   💾 Progress saved ({i+1}/{total})")

    # --- Final Save ---
    cols_to_save = [c for c in df.columns if c != "citation_id"]
    df[cols_to_save].to_csv(output_file, index=False)

    print(f"\n{'=' * 70}")
    print(f"🏁 ENRICHMENT COMPLETE")
    print(f"   - Papers Processed : {total}")
    print(f"   - Hits (Author IDs): {success_auth} ({success_auth/total:.0%})")
    print(f"   - Hits (Keywords)  : {success_kw} ({success_kw/total:.0%})")
    print(f"   - Hits (Abstract)  : {success_abs} ({success_abs/total:.0%})")
    print(f"   - Hits (DOI)       : {success_doi} ({success_doi/total:.0%})")
    print(f"   - Hits (TLDR)      : {success_tldr} ({success_tldr/total:.0%})")
    print(f"   - CrossRef Fallback: {crossref_hits} papers resolved (FREE)")


