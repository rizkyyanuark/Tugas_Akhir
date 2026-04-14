# knowledge/etl/scraping/paper_pipeline.py
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


def _serpapi_fetch_author(api_key, scholar_id, start=0, num=100, max_retries=2):
    """
    Fetch one page of Google Scholar Author articles via SerpAPI.
    Returns (articles_list, has_next_page).

    Includes automatic retry logic for flaky Free Plan responses:
      - Retry 1: same params, wait 3s
      - Retry 2: remove sort=pubdate (fallback), wait 3s
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

    for attempt in range(max_retries + 1):
        try:
            # On last retry, try without sort=pubdate as fallback
            current_params = dict(params)
            if attempt == max_retries and "sort" in current_params:
                current_params.pop("sort")

            resp = requests.get(
                "https://serpapi.com/search.json",
                params=current_params, timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                articles = data.get("articles", [])
                has_next = "next" in data.get("serpapi_pagination", {})

                # If articles found OR this is the last attempt, return
                if articles or attempt == max_retries:
                    if attempt > 0 and articles:
                        print(f"      🔄 Retry {attempt} berhasil ({len(articles)} articles)")
                    return articles, has_next

                # Empty result on non-last attempt → retry
                print(f"      ⚠️ SerpAPI return kosong (attempt {attempt+1}), retry in 3s...")
                time.sleep(3)
            else:
                error = resp.json().get("error", resp.text[:200])
                print(f"      ⚠️ SerpAPI HTTP {resp.status_code}: {error}")
                if attempt < max_retries:
                    time.sleep(3)
                else:
                    return [], False
        except Exception as e:
            print(f"      ⚠️ SerpAPI Error: {e}")
            if attempt < max_retries:
                time.sleep(3)
            else:
                return [], False

    return [], False


def run_scholar_scraping(api_key=None, limit_per_author=500, test_target_id=None):
    """
    Scrape papers from Google Scholar via SerpAPI (google_scholar_author engine).

    3-Phase Architecture:
        Phase 1 — Pure Scrape: Fetch all papers from SerpAPI, no filtering.
                  Auto-saves every 10 dosen for resume capability.
        Phase 2 — Batch Dedup: Remove duplicates vs Scopus + cross-dosen.
                  Uses exact match (O(1) set) + fuzzy match (SequenceMatcher).
        Phase 3 — Batch Author Match: Match author names to dosen list.
                  Produces final Authors + Author IDs columns.

    Output: dosen_papers_scholar.csv
    """
    api_key = api_key or SERPAPI_KEY
    if not api_key:
        print("   ❌ SERPAPI_KEY not configured! Add to credentials_new.json.")
        return

    print("\n📖 STEP 4: GOOGLE SCHOLAR SCRAPING (3-Phase: Scrape → Dedup → Match)")
    print("=" * 70)

    from difflib import SequenceMatcher
    import requests

    if not DOSEN_CSV.exists():
        print(f"   ❌ '{DOSEN_CSV}' not found!")
        return

    # --- Load Dosen Data ---
    df_dosen = pd.read_csv(DOSEN_CSV, dtype=str)
    targets = []
    dosen_list_for_matching = []

    def clean_name(name):
        name = str(name).lower()
        name = re.sub(r'\(.*?\)', '', name) 
        name = re.sub(r'\b(dr|prof|ir|drs|hz|hj|s\.?kom|m\.?kom|s\.?t|m\.?t|ph\.?d|s\.?pd|m\.?pd|m\.?si)\b\.?', '', name)
        name = re.sub(r'[^a-z\s]', '', name)
        name = re.sub(r'\bal\s+', 'al', name)
        return ' '.join(name.split())

    for _, r in df_dosen.iterrows():
        sid = str(r.get("scholar_id", "")).strip().replace('.0', '')
        if sid not in ("", "nan", "NaN"):
            targets.append({"id": sid, "name": r["nama_dosen"]})
            raw_nama_norm = str(r.get('nama_norm', '')).strip()
            if raw_nama_norm and raw_nama_norm != 'nan':
                dosen_list_for_matching.append({
                    'name_clean': clean_name(raw_nama_norm),
                    'name_raw': raw_nama_norm,
                    'id': sid
                })
                
    if test_target_id:
        targets = [t for t in targets if t['id'] == test_target_id]
        print(f"   🧪 RUNNING IN TEST MODE FOR ID: {test_target_id}")
    else:
        print(f"   🎯 {len(targets)} dosen with Scholar ID.\n")

    # ==================================================================
    # PHASE 1: PURE SCRAPE — Fetch all papers, no filtering
    # ==================================================================
    print("\n" + "=" * 50)
    print("📡 PHASE 1: PURE SCRAPE (No Filter, Auto-Save)")
    print("=" * 50)

    # Temp file for incremental save / resume
    SCHOLAR_TEMP_CSV = SAVE_DIR / "dosen_papers_scholar_temp.csv"

    # Check for existing temp file (resume support)
    scraped_ids = set()
    all_raw_papers = []
    if SCHOLAR_TEMP_CSV.exists() and not test_target_id:
        try:
            df_temp = pd.read_csv(SCHOLAR_TEMP_CSV, dtype=str).fillna("")
            all_raw_papers = df_temp.to_dict('records')
            scraped_ids = set(df_temp['scholar_id'].unique())
            print(f"   🔄 [RESUME] Loaded {len(all_raw_papers)} papers from temp file.")
            print(f"      Already scraped: {len(scraped_ids)} dosen IDs.")
        except Exception:
            pass

    total_api_calls = 0
    newly_scraped = 0

    for i, t in enumerate(targets):
        # Skip if already scraped (resume)
        if t['id'] in scraped_ids:
            print(f"[{i+1}/{len(targets)}] {t['name']} ({t['id']})... ⏭️ [Resume]")
            continue

        print(f"[{i+1}/{len(targets)}] {t['name']} ({t['id']})...")
        start = 0
        author_count = 0

        while author_count < limit_per_author:
            articles, has_next = _serpapi_fetch_author(api_key, t["id"], start=start, num=100)
            total_api_calls += 1

            if not articles:
                break

            for art in articles:
                all_raw_papers.append({
                    "Title": art.get('title', ''),
                    "Year": str(art.get("year", "")),
                    "Journal": art.get("publication", ""),
                    "Link": art.get("link", ""),
                    "Authors_raw": art.get("authors", ""),
                    "citation_id": art.get("citation_id", ""),
                    "scholar_id": t["id"],
                    "dosen": t["name"],
                    "source": "scholar",
                })
                author_count += 1

            if not has_next or len(articles) < 100:
                break 

            start += 100
            time.sleep(0.3)

        print(f"      📄 {author_count} papers fetched.")
        newly_scraped += 1

        # Auto-save after each dosen (for resume safety)
        if not test_target_id:
            pd.DataFrame(all_raw_papers).to_csv(SCHOLAR_TEMP_CSV, index=False)
            print(f"      💾 [Auto-Save] {len(all_raw_papers)} papers saved to temp.")

        time.sleep(1)

    # Final save of temp
    if not test_target_id and newly_scraped > 0:
        pd.DataFrame(all_raw_papers).to_csv(SCHOLAR_TEMP_CSV, index=False)
        print(f"\n   💾 Phase 1 Complete: {len(all_raw_papers)} total raw papers ({total_api_calls} API calls)")

    if not all_raw_papers:
        print("   ⚠️ No papers found.")
        return

    df_raw = pd.DataFrame(all_raw_papers)

    # ==================================================================
    # PHASE 2: BATCH DEDUP — Remove duplicates in one pass
    # ==================================================================
    print("\n" + "=" * 50)
    print("🔍 PHASE 2: BATCH DEDUP (Scopus + Cross-Dosen)")
    print("=" * 50)

    def _normalize_text(text):
        if pd.isna(text): return ""
        return str(text).lower().strip().replace(' ', '')

    def _is_similar(title1, title2, threshold=0.90):
        t1 = _normalize_text(title1)
        t2 = _normalize_text(title2)
        if not t1 or not t2: return False
        if t1 == t2 or t1 in t2 or t2 in t1: return True
        return SequenceMatcher(None, t1, t2).ratio() >= threshold

    # 2a. Load Scopus titles for cross-source dedup
    scopus_titles_norm = set()
    if SCOPUS_CSV.exists():
        try:
            df_scopus = pd.read_csv(SCOPUS_CSV)
            for t in df_scopus['Title'].dropna():
                scopus_titles_norm.add(_normalize_text(t))
            print(f"   📚 Loaded {len(scopus_titles_norm)} Scopus titles for dedup.")
        except Exception:
            pass

    # 2b. Normalize all raw titles
    df_raw['_title_norm'] = df_raw['Title'].apply(_normalize_text)

    total_before = len(df_raw)

    # 2c. Exact dedup: remove entries where normalized title is in Scopus
    scopus_mask = df_raw['_title_norm'].isin(scopus_titles_norm)
    scopus_dup_count = scopus_mask.sum()
    df_raw = df_raw[~scopus_mask].reset_index(drop=True)
    print(f"   🔄 Scopus exact dedup: {scopus_dup_count} papers removed.")

    # 2d. Cross-dosen exact dedup (keep first occurrence)
    before_cross = len(df_raw)
    df_raw = df_raw.drop_duplicates(subset='_title_norm', keep='first').reset_index(drop=True)
    cross_exact_dup = before_cross - len(df_raw)
    print(f"   🔄 Cross-dosen exact dedup: {cross_exact_dup} papers removed.")

    # 2e. Fuzzy dedup — trigram Jaccard similarity + inverted index
    #     Avoids O(N²) by only comparing titles sharing many 3-char substrings.
    #     Benchmarked: 32s on 5640 papers (vs 90+ min brute-force).
    print(f"   🔄 Fuzzy dedup on {len(df_raw)} remaining papers...")
    
    from collections import defaultdict
    
    def _trigrams(text):
        """Extract set of 3-character substrings from normalized text."""
        s = _normalize_text(text)
        if len(s) < 3: return set()
        return set(s[i:i+3] for i in range(len(s)-2))
    
    # Inverted index: trigram → set of paper indices
    trigram_index = defaultdict(set)
    trigram_cache = {}  # idx → trigram set (avoid recompute)
    fuzzy_dup_indices = set()
    comparisons = 0
    
    for idx, row in df_raw.iterrows():
        norm = row['_title_norm']
        raw = row['Title']
        
        if not norm or len(norm) < 10:
            continue
        
        tg = _trigrams(raw)
        if not tg:
            continue
        
        # Find candidates: count shared trigrams per seen paper
        candidate_counts = defaultdict(int)
        for t in tg:
            for cand_idx in trigram_index.get(t, set()):
                if cand_idx not in fuzzy_dup_indices:
                    candidate_counts[cand_idx] += 1
        
        # Only check papers sharing >= 50% of trigrams (cheap pre-filter)
        min_shared = len(tg) * 0.5
        is_dup = False
        for cand_idx, shared_count in candidate_counts.items():
            if shared_count >= min_shared:
                comparisons += 1
                cand_tg = trigram_cache[cand_idx]
                jaccard = len(tg & cand_tg) / len(tg | cand_tg)
                if jaccard >= 0.80:
                    is_dup = True
                    break
        
        if is_dup:
            fuzzy_dup_indices.add(idx)
        else:
            # Register in inverted index
            trigram_cache[idx] = tg
            for t in tg:
                trigram_index[t].add(idx)
        
        # Progress log
        if idx > 0 and idx % 1000 == 0:
            print(f"      ... processed {idx}/{len(df_raw)} ({len(fuzzy_dup_indices)} fuzzy dups, {comparisons:,} comparisons)")

    df_raw = df_raw.drop(index=fuzzy_dup_indices).reset_index(drop=True)
    print(f"   🔄 Fuzzy dedup: {len(fuzzy_dup_indices)} papers removed.")

    total_after = len(df_raw)
    total_removed = total_before - total_after
    print(f"\n   📊 Dedup Summary: {total_before} → {total_after} ({total_removed} duplicates removed)")

    # Cleanup temp column
    df_raw = df_raw.drop(columns=['_title_norm'])

    # ==================================================================
    # PHASE 3: BATCH AUTHOR MATCH — Match names to dosen list
    # ==================================================================
    print("\n" + "=" * 50)
    print("👥 PHASE 3: BATCH AUTHOR MATCH")
    print("=" * 50)

    # --- Author Matching Logic (same as before) ---
    def is_abbreviation_match(serp_name, dosen_name):
        if serp_name == dosen_name: return True
        if serp_name.replace(' ', '') == dosen_name.replace(' ', ''): return True
        if SequenceMatcher(None, serp_name, dosen_name).ratio() > 0.85: return True
        
        s_tokens = serp_name.split()
        d_tokens = dosen_name.split()
        if not s_tokens or not d_tokens: return False
        
        def get_signature(tokens):
            sig = ''
            for t in tokens:
                if len(t) <= 3: sig += t
                else: sig += t[0]
            return sig
        
        s_sig_sorted = ''.join(sorted(get_signature(s_tokens)))
        d_sig_sorted = ''.join(sorted(get_signature(d_tokens)))
        if s_sig_sorted == d_sig_sorted:
            last_s = s_tokens[-1]; last_d = d_tokens[-1]
            if len(last_s) > 2 and len(last_d) > 2:
                last_ratio = SequenceMatcher(None, last_s, last_d).ratio()
                if last_ratio < 0.5 and not last_s.startswith(last_d) and not last_d.startswith(last_s):
                    pass
                else: return True
            else: return True
            
        serp_surname = s_tokens[-1]
        dosen_surname = d_tokens[-1]
        
        surname_ok = False
        if serp_surname == dosen_surname:
            surname_ok = True
        elif len(serp_surname) <= 2 or len(dosen_surname) <= 2:
            longer = serp_surname if len(serp_surname) > len(dosen_surname) else dosen_surname
            shorter = dosen_surname if len(serp_surname) > len(dosen_surname) else serp_surname
            if longer.startswith(shorter):
                if len(shorter) == 1:
                    if s_tokens[0][0] == d_tokens[0][0] and len(s_tokens) >= 2 and len(d_tokens) >= 2 and len(longer) <= 4:
                        surname_ok = True
                else:
                    surname_ok = True
        elif len(serp_surname) > 3 and serp_surname in d_tokens:
            if s_tokens[0][0] == d_tokens[0][0]:
                surname_ok = True
        
        if not surname_ok: return False
            
        serp_initials = [t[0] for t in s_tokens[:-1]]
        
        if serp_surname == dosen_surname:
            dosen_pre_surname = d_tokens[:-1]
        elif serp_surname in d_tokens:
            idx = d_tokens.index(serp_surname)
            dosen_pre_surname = d_tokens[:idx] + d_tokens[idx+1:]
        else:
            dosen_pre_surname = d_tokens[:-1]
        
        dosen_initials = [t[0] for t in dosen_pre_surname]
        
        di_copy = list(dosen_initials)
        all_found = True
        for si in serp_initials:
            if si in di_copy:
                di_copy.remove(si)
            else:
                all_found = False; break
        
        if all_found: return True
        return False

    def process_authors(raw_authors_str, current_target_id):
        if not raw_authors_str or pd.isna(raw_authors_str): 
            target_name = [d['name_raw'] for d in dosen_list_for_matching if d['id'] == current_target_id]
            t_name = target_name[0] if target_name else ''
            return t_name, current_target_id
            
        ids = [current_target_id] 
        author_parts = re.split(r',| and | \& ', str(raw_authors_str))
        replaced_author_names = []
        for part in author_parts:
            part = part.strip()
            part_clean = clean_name(part)
            if not part_clean: continue
            for d in dosen_list_for_matching:
                if is_abbreviation_match(part_clean, d['name_clean']):
                    ids.append(d['id']) 
                    replaced_author_names.append(d['name_raw']) 
                    break

        unique_ids = []
        for i in ids:
            if i not in unique_ids: unique_ids.append(i)
            
        if current_target_id in unique_ids:
            unique_ids.remove(current_target_id)
            unique_ids.insert(0, current_target_id)
            
        target_name = [d['name_raw'] for d in dosen_list_for_matching if d['id'] == current_target_id]
        if target_name and target_name[0] not in replaced_author_names:
            replaced_author_names.insert(0, target_name[0])
            
        unique_names = []
        for r in replaced_author_names:
            if r not in unique_names: unique_names.append(r)
            
        final_ids = ';'.join(unique_ids)
        final_authors_str = ', '.join(unique_names) 
        return final_authors_str, final_ids

    # --- Run batch matching ---
    authors_col = []
    author_ids_col = []
    matched_count = 0

    for idx, row in df_raw.iterrows():
        raw_authors = row.get("Authors_raw", "")
        scholar_id = row.get("scholar_id", "")
        processed_authors, matched_ids = process_authors(raw_authors, scholar_id)
        authors_col.append(processed_authors)
        author_ids_col.append(matched_ids)
        
        # Count papers with >1 matched dosen ID
        if ';' in matched_ids:
            matched_count += 1

    df_raw['Authors'] = authors_col
    df_raw['Author IDs'] = author_ids_col

    print(f"   ✅ Matched {matched_count} papers with multiple dosen co-authors.")

    # --- Finalize schema ---
    for col in ["Abstract", "Keywords", "Document Type", "DOI", "TLDR"]:
        if col not in df_raw.columns:
            df_raw[col] = ""

    # Reorder columns to match expected schema
    final_columns = [
        "Authors", "Author IDs", "Title", "Year", "Journal", "Link",
        "Abstract", "Keywords", "Document Type", "DOI", "TLDR",
        "citation_id", "scholar_id", "dosen", "source"
    ]
    # Keep only columns that exist
    final_columns = [c for c in final_columns if c in df_raw.columns]
    df_final = df_raw[final_columns]

    # ==================================================================
    # OUTPUT & SAVE
    # ==================================================================
    if test_target_id:
        pd.set_option('display.max_columns', None)
        pd.set_option('display.max_colwidth', 80)
        print(f"\n🧪 TEST MODE OUTPUT (NOT SAVING)")
        print(df_final[['Authors', 'Author IDs', 'Title']].head(15))
        return df_final

    df_final.to_csv(SCHOLAR_CSV, index=False)
    print(f"\n   ✅ Saved {len(df_final)} unique Scholar papers -> {SCHOLAR_CSV}")

    # Cleanup temp file after successful save
    if SCHOLAR_TEMP_CSV.exists():
        try:
            SCHOLAR_TEMP_CSV.unlink()
            print(f"   🧹 Cleaned up temp file: {SCHOLAR_TEMP_CSV.name}")
        except:
            pass

    return df_final




# ================================================================
# STEP 5: SCHOLAR ENRICHMENT (Keywords, Abstract, DOI, TLDR)
# ================================================================

def run_scholar_enrichment(input_csv=None, output_csv=None, test_limit=None):
    """
    Enrich papers with Keywords, Abstract, DOI, TLDR, and Author IDs.
    Supports RESUMABLE scraping: skip papers that are already fully enriched.

    Optimized Flow (FREE APIs first, paid last):
        Phase 1 - Semantic Scholar API (FREE): Abstract, DOI, TLDR, DocType, PDF link
        Phase 1->Web - Publisher Scraping (FREE): Keywords from PDF/DOI links
        Phase 2 - OpenAlex API (FREE): Keywords, Author IDs, DOI, Abstract
        Phase 2->Web - OpenAlex Links Scraping (FREE): Keywords fallback
        Phase 3 - BrightData Scholar Search (PAID -> ONLY if data incomplete)

    Input:  dosen_papers_scholar.csv
    Output: dosen_papers_scholar.csv (in-place update)

    Args:
        test_limit: int or None. Jika diisi, hanya proses N paper pertama
                    yang BELUM di-enrich. Berguna untuk testing pipeline.
    """
    from .keyword_scraper import (
        scrape_publisher_page,
        search_scholar_proxy_query,
        extract_doi,
        _crossref_lookup,
    )
    from .semantic_client import fetch_s2_details

    input_file = Path(input_csv) if input_csv else SCHOLAR_CSV
    output_file = Path(output_csv) if output_csv else SCHOLAR_CSV

    # Load Dosen mapping
    dosen_csv_path = Path(__file__).parent.parent / "file_tabulars" / "dosen_infokom_final.csv"
    dosen_map = {}           # Scholar ID -> Nama Norm
    dosen_name_to_id = {}    # Nama Norm (lower) -> Scholar ID

    if dosen_csv_path.exists():
        try:
            df_dosen = pd.read_csv(dosen_csv_path)
            for _, r in df_dosen.iterrows():
                sid = str(r.get("scholar_id", "")).strip()
                n_norm = str(r.get("nama_norm", "")).strip()
                if sid and n_norm:
                    dosen_map[sid] = n_norm
                    dosen_name_to_id[n_norm.lower()] = sid
        except Exception as e:
            print(f"   WARNING: Could not load dosen CSV: {e}")

    print("\n" + "=" * 70)
    print("SCHOLAR ENRICHMENT PIPELINE")
    print("   Flow: Semantic Scholar (FREE) -> OpenAlex (FREE) -> BrightData (PAID)")
    print("=" * 70)

    if not input_file.exists():
        print(f"   ERROR: '{input_file}' not found! Run Scholar Scraping first.")
        return

    df = pd.read_csv(input_file, dtype=str).fillna("")
    total = len(df)

    # Make sure new columns exist
    for col in ["Abstract", "Keywords", "DOI", "TLDR", "Document Type", "Author IDs", "Scraped_By_Pipeline"]:
        if col not in df.columns:
            df[col] = ""

    # Count already-processed
    already_done = df[df["Scraped_By_Pipeline"].str.lower() == "true"].shape[0]
    remaining = total - already_done

    print(f"   Total papers       : {total}")
    print(f"   Already enriched   : {already_done}")
    print(f"   Remaining          : {remaining}")
    if test_limit:
        print(f"   TEST MODE          : Hanya proses {test_limit} paper")
    print()

    # --- Stats ---
    stats = {"kw": 0, "abs": 0, "doi": 0, "tldr": 0, "auth": 0,
             "s2_hit": 0, "oa_hit": 0, "bd_hit": 0, "bd_skip": 0}
    processed_count = 0
    import time as _time
    t_start = _time.time()

    for i, row in df.iterrows():
        # --- Test limit check ---
        if test_limit and processed_count >= test_limit:
            print(f"\n TEST LIMIT tercapai ({test_limit} paper). Berhenti.")
            break

        # --- 0. Data Cleaning (Title Capitalization) ---
        raw_title = str(row.get("Title", "")).strip()
        title = raw_title.title()
        if title != raw_title:
            df.at[i, "Title"] = title

        abstract = str(row.get("Abstract", "")).strip()
        keywords = str(row.get("Keywords", "")).strip()
        doi = str(row.get("DOI", "")).strip()
        tldr = str(row.get("TLDR", "")).strip()
        doc_type = str(row.get("Document Type", "")).strip()
        journal = str(row.get("Journal", "")).strip()
        year = str(row.get("Year", "")).strip()
        author_ids = str(row.get("Author IDs", "")).strip()
        scholar_id_col = str(row.get("scholar_id", "")).strip()
        if not author_ids and scholar_id_col and scholar_id_col != "nan":
            author_ids = scholar_id_col

        scraped_flag = str(row.get("Scraped_By_Pipeline", "")).strip()

        link = str(row.get("Link", "")).strip()
        pdf_link = None

        # --- RESUME LOGIC ---
        if scraped_flag.lower() == "true":
            continue

        processed_count += 1
        elapsed = _time.time() - t_start
        avg_per_paper = elapsed / processed_count if processed_count > 1 else 0

        print(f"\n{'=' * 70}")
        print(f"[{processed_count}/{test_limit or remaining}] {title[:65]}")
        print(f"   Status Awal: "
              f"Abstract={'Y' if abstract else 'N'}  "
              f"Keywords={'Y' if keywords else 'N'}  "
              f"DOI={'Y' if doi else 'N'}  "
              f"TLDR={'Y' if tldr else 'N'}")

        time.sleep(1)  # Gentle base pacing

        # Track what each source contributed
        sources = {"s2": [], "oa": [], "web": [], "bd": []}

        # ==========================================================
        # PHASE 1: SEMANTIC SCHOLAR API (FREE)
        # ==========================================================
        print(f"   [Phase 1] Semantic Scholar API...")
        s2_data = fetch_s2_details(doi=doi if doi else None, title=title)

        if s2_data:
            stats["s2_hit"] += 1
            if not tldr and s2_data.get('tldr'):
                tldr = str(s2_data['tldr'].get('text', '')) if s2_data['tldr'] else ''
                if tldr: sources["s2"].append("TLDR")
            if not abstract and s2_data.get('abstract'):
                abstract = str(s2_data['abstract']) if s2_data['abstract'] else ''
                if abstract: sources["s2"].append("Abstract")
            if not doi and s2_data.get('externalIds', {}).get('DOI'):
                doi = s2_data['externalIds']['DOI']
                sources["s2"].append("DOI")
            if not year and s2_data.get('year'):
                year = str(s2_data['year'])
                sources["s2"].append("Year")
            if not journal and s2_data.get('venue'):
                journal = str(s2_data['venue'])
                sources["s2"].append("Journal")
            if not doc_type and s2_data.get("publicationTypes"):
                doc_type = ", ".join(s2_data["publicationTypes"])
                sources["s2"].append("DocType")
            if s2_data.get('openAccessPdf') and s2_data['openAccessPdf'].get('url'):
                pdf_link = s2_data['openAccessPdf']['url']
                sources["s2"].append("PDF-Link")

            s2_summary = ", ".join(sources["s2"]) if sources["s2"] else "Tidak ada data baru"
            print(f"      -> {'OK' if sources['s2'] else 'MISS'} S2: {s2_summary}")
        else:
            print(f"      -> MISS: Tidak ditemukan di S2")

        # --- Phase 1 -> Web: Publisher Scraping (dari S2 links) ---
        if not keywords and (pdf_link or doi):
            print(f"   [Phase 1->Web] Scrape Publisher...")
            scrape_links = []
            if pdf_link: scrape_links.append(("PDF", pdf_link))
            if doi: scrape_links.append(("DOI", f"https://doi.org/{doi}"))

            seen_urls = set()
            for link_type, scrape_url in scrape_links:
                if scrape_url in seen_urls: continue
                seen_urls.add(scrape_url)
                print(f"      -> {link_type}: {scrape_url[:50]}...")
                scrape_result = scrape_publisher_page(scrape_url, force_proxy=False)

                if scrape_result.get("keywords") and not keywords:
                    keywords = scrape_result["keywords"]
                    sources["web"].append(f"Keywords({link_type})")
                if scrape_result.get("abstract") and not abstract:
                    abstract = scrape_result["abstract"]
                    sources["web"].append(f"Abstract({link_type})")
                if scrape_result.get("doi") and not doi:
                    doi = scrape_result["doi"]
                    sources["web"].append(f"DOI({link_type})")
                if scrape_result.get("doc_type") and not doc_type:
                    doc_type = scrape_result["doc_type"]
                    sources["web"].append(f"DocType({link_type})")

                if keywords and abstract:
                    break

            web_summary = ", ".join(sources["web"]) if sources["web"] else "Tidak ada data baru"
            print(f"      -> {'OK' if sources['web'] else 'MISS'} Web: {web_summary}")

        # ==========================================================
        # PHASE 2: OPENALEX API (FREE)
        # ==========================================================
        oa_keywords_fallback = ""
        print(f"   [Phase 2] OpenAlex API...")
        from .keyword_scraper import _openalex_lookup
        oa_doi_before = doi
        oa_data = _openalex_lookup(doi=doi if doi else None, title=title)
        if oa_data:
            stats["oa_hit"] += 1
            extracted_names = oa_data.get('author_names', [])
            if extracted_names:
                mapped_ids = []
                for name in extracted_names:
                    matched_id = dosen_name_to_id.get(name.lower().strip())
                    if matched_id:
                        mapped_ids.append(matched_id)

                if mapped_ids:
                    existing_ids = set([x.strip() for x in author_ids.replace(',', ';').split(';')]) if author_ids else set()
                    new_ids = set(mapped_ids)
                    combined_ids = existing_ids.union(new_ids)
                    new_author_ids_str = ";".join(combined_ids)
                    if new_author_ids_str and new_author_ids_str != author_ids:
                        author_ids = new_author_ids_str
                        sources["oa"].append("AuthorIDs")

            extracted_kw = oa_data.get('keywords', '')
            if extracted_kw:
                oa_keywords_fallback = extracted_kw
                if not keywords:
                    sources["oa"].append("Keywords(AI)")

            if not doc_type and oa_data.get('doc_type', ''):
                doc_type = oa_data['doc_type']
                sources["oa"].append("DocType")
            if not year and oa_data.get('publication_year'):
                year = str(oa_data['publication_year'])
                sources["oa"].append("Year")
            host_venue = oa_data.get('host_venue') or oa_data.get('primary_location', {})
            if not journal and host_venue.get('source'):
                journal = str(host_venue['source'].get('display_name', ''))
                if journal: sources["oa"].append("Journal")
            if not doi and oa_data.get('doi', ''):
                doi = oa_data['doi']
                sources["oa"].append("DOI")
            if not abstract and oa_data.get('abstract', ''):
                abstract = oa_data['abstract']
                sources["oa"].append("Abstract")

            # --- Phase 2 -> Web: OpenAlex Links Scraping ---
            if not keywords:
                oa_scrape_links = []
                oa_pdf = oa_data.get('oa_pdf_url', '')
                if oa_pdf: oa_scrape_links.append(("OA-PDF", oa_pdf))
                oa_landing = oa_data.get('oa_landing_url', '')
                if oa_landing: oa_scrape_links.append(("OA-Landing", oa_landing))
                if doi and doi != oa_doi_before:
                    oa_scrape_links.append(("DOI", f"https://doi.org/{doi}"))

                if oa_scrape_links:
                    seen = set()
                    for ltype, lurl in oa_scrape_links:
                        if lurl in seen: continue
                        seen.add(lurl)
                        print(f"      -> OA-Web {ltype}: {lurl[:40]}...")
                        scrape_result = scrape_publisher_page(lurl, force_proxy=False)
                        if scrape_result.get("keywords") and not keywords:
                            keywords = scrape_result["keywords"]
                            sources["oa"].append(f"Keywords({ltype})")
                        if scrape_result.get("abstract") and not abstract:
                            abstract = scrape_result["abstract"]
                            sources["oa"].append(f"Abstract({ltype})")
                        if keywords:
                            break

            oa_summary = ", ".join(sources["oa"]) if sources["oa"] else "Tidak ada data baru"
            print(f"      -> {'OK' if sources['oa'] else 'MISS'} OA: {oa_summary}")
        else:
            print(f"      -> MISS: Tidak ditemukan di OpenAlex")

        # --- Fallback: OpenAlex AI Concepts as Keywords ---
        if not keywords and oa_keywords_fallback:
            keywords = oa_keywords_fallback
            print(f"   [Fallback] Menggunakan OpenAlex Concepts (AI) sebagai Keywords")

        # ==========================================================
        # PHASE 3: BRIGHTDATA GOOGLE SCHOLAR (PAID - ONLY IF NEEDED)
        # ==========================================================
        if not abstract or not keywords or not doi:
            stats["bd_hit"] += 1
            missing = []
            if not abstract: missing.append("Abstract")
            if not keywords: missing.append("Keywords")
            if not doi: missing.append("DOI")
            print(f"   [Phase 3] BrightData Scholar (missing: {', '.join(missing)})...")

            sh_data = search_scholar_proxy_query(title)
            if sh_data:
                extracted_ids = sh_data.get('author_ids', [])
                if extracted_ids:
                    mapped_ids = [eid for eid in extracted_ids if eid in dosen_map]
                    if mapped_ids:
                        existing_ids = set([x.strip() for x in author_ids.replace(',', ';').split(';')]) if author_ids else set()
                        combined_ids = existing_ids.union(set(mapped_ids))
                        new_str = ";".join(combined_ids)
                        if new_str and new_str != author_ids:
                            author_ids = new_str
                            sources["bd"].append("AuthorIDs")

                snippet_fallback = sh_data.get('snippet', '')
                if not keywords and sh_data.get('keywords', ''):
                    keywords = sh_data['keywords']
                    sources["bd"].append("Keywords")
                if not year and sh_data.get('year'):
                    year = str(sh_data['year'])
                    sources["bd"].append("Year")
                if not journal and sh_data.get('journal'):
                    journal = str(sh_data['journal'])
                    sources["bd"].append("Journal")

                # Scholar -> Web scraping
                sch_links = []
                if sh_data.get('title_link'): sch_links.append(("Pub", sh_data['title_link'], False))
                if sh_data.get('pdf_link'): sch_links.append(("PDF", sh_data['pdf_link'], False))
                if sh_data.get('html_direct'): sch_links.append(("HTML", sh_data['html_direct'], False))
                if sh_data.get('cached_html'): sch_links.append(("Cache", sh_data['cached_html'], True))

                if sch_links and (not keywords or not abstract):
                    seen_urls = set()
                    for ltype, lurl, use_proxy in sch_links:
                        if lurl in seen_urls: continue
                        seen_urls.add(lurl)
                        print(f"      -> Scholar-Web {ltype}: {lurl[:30]}...")
                        scrape_result = scrape_publisher_page(lurl, force_proxy=use_proxy)
                        if scrape_result.get("keywords") and not keywords:
                            keywords = scrape_result["keywords"]
                            sources["bd"].append(f"Keywords({ltype})")
                        if scrape_result.get("abstract") and not abstract:
                            abstract = scrape_result["abstract"]
                            sources["bd"].append(f"Abstract({ltype})")
                        if scrape_result.get("doi") and not doi:
                            doi = scrape_result["doi"]
                            sources["bd"].append(f"DOI({ltype})")
                        if scrape_result.get("doc_type") and not doc_type:
                            doc_type = scrape_result["doc_type"]
                        if keywords and abstract:
                            break

                if not abstract and snippet_fallback:
                    abstract = snippet_fallback
                    sources["bd"].append("Abstract(snippet)")
                if not journal and sh_data.get('journal'): journal = sh_data['journal']
                if not year and sh_data.get('year'): year = str(sh_data['year'])

                bd_summary = ", ".join(sources["bd"]) if sources["bd"] else "Tidak ada data baru"
                print(f"      -> {'OK' if sources['bd'] else 'MISS'} BD: {bd_summary}")
            else:
                print(f"      -> MISS: Tidak ditemukan di Scholar Search")
        else:
            stats["bd_skip"] += 1
            print(f"   [Phase 3] BrightData DILEWATI (data lengkap, hemat credit)")

        # --- Final Fallbacks ---
        if not doc_type:
            doc_type = "Artikel"

        if not author_ids:
            import re as _re
            link_match = _re.search(r'user=([A-Za-z0-9_-]+)', link)
            if link_match:
                author_ids = link_match.group(1)
            else:
                authors_str = str(row.get("Authors", "")).strip()
                if authors_str and dosen_name_to_id:
                    for dosen_name, sid in dosen_name_to_id.items():
                        if dosen_name.lower() in authors_str.lower():
                            author_ids = sid
                            break

        # --- Per-paper Summary ---
        all_sources = []
        for src, items in sources.items():
            if items:
                label = {"s2": "S2", "oa": "OA", "web": "Web", "bd": "BD"}[src]
                all_sources.append(f"{label}({', '.join(items)})")

        print(f"   HASIL: "
              f"Abstract={'Y' if abstract else 'N'}  "
              f"Keywords={'Y' if keywords else 'N'}  "
              f"DOI={'Y' if doi else 'N'}  "
              f"TLDR={'Y' if tldr else 'N'}")
        if all_sources:
            print(f"   Sumber: {' -> '.join(all_sources)}")

        # --- Update DataFrame ---
        df.at[i, "Abstract"] = abstract
        df.at[i, "Keywords"] = keywords
        df.at[i, "DOI"] = doi
        df.at[i, "TLDR"] = tldr
        df.at[i, "Document Type"] = doc_type
        df.at[i, "Journal"] = journal
        df.at[i, "Year"] = year
        df.at[i, "Author IDs"] = author_ids
        df.at[i, "Scraped_By_Pipeline"] = "True"
        if pdf_link:
            df.at[i, "Link"] = pdf_link

        # Stats
        if abstract: stats["abs"] += 1
        if keywords: stats["kw"] += 1
        if doi: stats["doi"] += 1
        if tldr: stats["tldr"] += 1
        if author_ids: stats["auth"] += 1

        # Progress save setiap 1 paper selesai
        df.to_csv(output_file, index=False)
        if avg_per_paper > 0:
            eta_min = (((test_limit or remaining) - processed_count) * avg_per_paper) / 60
            print(f"   SAVED ({processed_count}/{test_limit or remaining}) | ETA: {eta_min:.0f} menit")
        else:
            print(f"   SAVED ({processed_count}/{test_limit or remaining})")

    # --- Final Save ---
    cols_to_save = [c for c in df.columns if c != "citation_id"]
    df[cols_to_save].to_csv(output_file, index=False)

    elapsed_total = (_time.time() - t_start) / 60
    n = processed_count or 1  # avoid div by zero

    print(f"\n{'=' * 70}")
    print(f"ENRICHMENT SELESAI - {processed_count} paper diproses ({elapsed_total:.1f} menit)")
    print(f"{'=' * 70}")
    print(f"   COVERAGE RATE:")
    print(f"      Author IDs : {stats['auth']}/{n} ({stats['auth']/n:.0%})")
    print(f"      Keywords   : {stats['kw']}/{n} ({stats['kw']/n:.0%})")
    print(f"      Abstract   : {stats['abs']}/{n} ({stats['abs']/n:.0%})")
    print(f"      DOI        : {stats['doi']}/{n} ({stats['doi']/n:.0%})")
    print(f"      TLDR       : {stats['tldr']}/{n} ({stats['tldr']/n:.0%})")
    print(f"   API HIT RATE:")
    print(f"      Semantic Scholar : {stats['s2_hit']}/{n} ({stats['s2_hit']/n:.0%})")
    print(f"      OpenAlex         : {stats['oa_hit']}/{n} ({stats['oa_hit']/n:.0%})")
    print(f"      BrightData ($$)  : {stats['bd_hit']}/{n} calls | {stats['bd_skip']} skipped")
    print(f"{'=' * 70}")

