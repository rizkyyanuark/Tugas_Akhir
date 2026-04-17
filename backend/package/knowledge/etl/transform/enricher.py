"""
Transform: Paper Enrichment (Micro-batch)
==========================================
Enriches papers with metadata from multiple APIs in priority order:
  Phase 1: Semantic Scholar (FREE) -> Abstract, DOI, TLDR
  Phase 2: OpenAlex (FREE) -> Keywords, Author IDs, DOI
  Phase 3: AI TLDR Generation (Groq Llama-3.1-8B) -> TLDR from abstract

Designed for Airflow micro-batch execution with idempotency.
"""
import time
import logging
import pandas as pd
from .cleaner import clean_abstract_text

from ..extract.semantic_scholar import extract_s2_metadata
from ..extract.openalex import extract_openalex_metadata

import os

try:
    from knowledge.etl.scraping.keyword_scraper import (
        search_scholar_proxy_query,
        scrape_publisher_page,
        search_scholar_proxy_query_html,
    )
except ImportError:
    # Fallback if scraping dependencies are missing
    search_scholar_proxy_query = None
    scrape_publisher_page = None
    search_scholar_proxy_query_html = None

logger = logging.getLogger(__name__)


# ─── Groq API Client ──────────────────────────────────────────

_groq_client = None

def _get_groq_client():
    global _groq_client
    if _groq_client is not None:
        return _groq_client
    
    try:
        from groq import Groq
        groq_api_key = os.environ.get("GROQ_API_KEY")
        
        # Fallback: Check Airflow Variables (highest priority)
        if not groq_api_key:
            try:
                from airflow.models import Variable
                groq_api_key = Variable.get("GROQ_API_KEY", default_var=None)
                if groq_api_key:
                    logger.info("      ✅ GROQ_API_KEY loaded from Airflow Variables.")
            except ImportError:
                pass  # Not running in Airflow
        
        if not groq_api_key:
            logger.warning("      ⚠️ GROQ_API_KEY is not set in environment, .env, or Airflow Variables.")
            return None
            
        _groq_client = Groq(api_key=groq_api_key)
        logger.info("      ✅ Groq API Client initialized successfully.")
        return _groq_client
    except Exception as e:
        logger.warning(f"      ⚠️ Failed to initialize Groq client: {e}")
        return None


def generate_tldr_via_ai(title: str, abstract: str) -> str:
    """
    Generate a 2-sentence TLDR from abstract using Groq API (llama-3.1-8b-instant).
    """
    if not abstract or len(abstract.strip()) < 30:
        return ""

    client = _get_groq_client()
    if client is None:
        return ""
    
    system_prompt = """You are an AI assistant specializing in strict academic data extraction.
Your Task: Read the following journal abstract and summarize it into EXACTLY 2 SENTENCES in ENGLISH that are very dense and specific.

ONTOLOGY SCHEMA RULES:
[Problem], [Task], [Field], [Method], [Model], [Innovation], [Dataset], [Tool], [Metric].

STRUCTURE (MANDATORY):
Sentence 1: Background & Approach (You MUST include Problem/Task, Field, and Method).
Sentence 2: Experiments & Results (You MUST explicitly write out the Metric, Tool, and Dataset used).

EXAMPLE 1 (Algorithm Research):
Abstract: "Penelitian mendeteksi hoaks pada Twitter menggunakan algoritma BERT. Kami menggunakan dataset ID-Hoax dan mencapai akurasi 95%."
Output: This research addresses hoof detection within the Twitter social media domain using the BERT algorithm. Experiments were conducted on the ID-Hoax dataset and achieved an accuracy of 95%.

EXAMPLE 2 (System/App Development):
Abstract: "Penelitian ini mengembangkan bot telegram di UNESA. Hasil menunjukkan bot mampu memberi respons realtime tanpa bug dengan kecepatan 1050 ms hingga 1680 ms."
Output: This study develops a Telegram bot system with webhook integration for sexual violence reporting services at Universitas Negeri Surabaya. Performance measurement results indicated a fast real-time response capability ranging from 1050 ms to 1680 ms without system bugs.

CRITICAL RULES:
- You are FORBIDDEN from outputting only 1 sentence. YOU MUST OUTPUT EXACTLY 2 SENTENCES.
- If there are numbers, percentages, or ms (milliseconds) in the abstract, you MUST include them in Sentence 2 as the [Metric].
- NO pronouns like "this method".
- THE OUTPUT MUST BE IN ENGLISH."""

    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"ORIGINAL ABSTRACT:\n{abstract}\n\nOUTPUT 2-SENTENCE TL;DR IN ENGLISH:"}
            ],
            temperature=1,
            max_tokens=256,
            stream=False
        )
        
        tldr = completion.choices[0].message.content.strip()
        time.sleep(3)  # Rate Limit Cooldown (30 RPM limit on free tier)
        return tldr if len(tldr) > 10 else ""
    except Exception as e:
        logger.warning(f"      ⚠️ TLDR generation error (Groq Llama-3.1-8B): {e}")
        return ""


def extract_metadata_via_llm(title: str, raw_text: str) -> dict:
    """
    Use Groq API to extract Abstract, Keywords, and DOI from raw website text.
    Used as an Agentic Fallback for tricky publisher pages.
    """
    import re, json
    res = {"abstract": "", "keywords": "", "doi": ""}
    if not raw_text or len(raw_text.strip()) < 100:
        return res

    client = _get_groq_client()
    if client is None:
        return res

    try:
        # Clean visible text to reduce tokens
        clean_text = re.sub(r'\s+', ' ', raw_text)[:5000]
        
        prompt = (
            f"Below is raw text from a publisher's website for an academic paper titled '{title}'.\n"
            "Extract the following fields in JSON format: 'abstract', 'keywords', 'doi'.\n"
            "If a field is not found, leave it as an empty string.\n\n"
            f"TEXT: {clean_text}\n\n"
            "Respond ONLY with the JSON object."
        )
        
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a data extraction agent. Extract paper metadata from raw text into JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_completion_tokens=2048,
            stream=False
        )
        
        output = completion.choices[0].message.content.strip()
        
        # Simple JSON extraction from response
        match = re.search(r'\{.*\}', output, re.DOTALL)
        if match:
            extracted = json.loads(match.group(0))
            if extracted.get("abstract"): res["abstract"] = extracted["abstract"]
            if extracted.get("keywords"): res["keywords"] = extracted["keywords"]
            if extracted.get("doi"): res["doi"] = extracted["doi"]
            logger.info(f"      ✨ Agentic AI Success: Extracted {len(res['abstract'])} chars of abstract.")
            
    except Exception as e:
        logger.warning(f"      ⚠️ Agentic Extraction error (Groq): {e}")
        
    return res


def generate_keywords_from_abstract(abstract_text: str) -> str:
    """
    Generate exactly 4-5 academic keywords from an abstract using Groq (llama-3.1-8b-instant).
    """
    if not abstract_text or len(abstract_text.strip()) < 30:
        return ""
        
    client = _get_groq_client()
    if client is None:
        return ""
    
    system_prompt = """You are an AI assistant specializing in academic data extraction.
Your Task: Read the following journal abstract and extract EXACTLY 4 to 5 highly relevant academic keywords.

STRICT RULES:
- Output ONLY the keywords separated by commas.
- Do NOT output any conversational text.
- Do NOT output bullet points or numbers.
- The keywords MUST be in the EXACT same language as the abstract."""

    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"ABSTRACT:\n{abstract_text}\n\nKEYWORDS:"}
            ],
            temperature=0.1,
            max_tokens=64,
            stream=False
        )
        
        kw = completion.choices[0].message.content.strip()
        # Clean trailing punctuation
        kw = kw.strip('"').strip("'").strip('.')
        time.sleep(3)  # Rate Limit Cooldown (30 RPM limit on free tier)
        return kw
    except Exception as e:
        logger.warning(f"      ⚠️ Keyword generation error (Groq Llama-3.1-8B): {e}")
        return ""


# ─── Scholar ID-Based Author Resolution (like old paper_pipeline.py) ────

def _resolve_authors_by_scholar_id(
    authors_str: str, 
    paper_scholar_id: str,
    paper_dosen: str = "",
    title: str = "",
    existing_author_ids: list = None
) -> tuple:
    """
    OLD SYSTEM APPROACH: Resolve authors using Scholar IDs (not names).
    
    How it works (mirrors paper_pipeline.py):
      1. Use the paper's scholar_id column to identify the PROFILE OWNER
      2. If a title is provided, query Google Scholar via Proxy to extract real author IDs
      3. For each name, check if it matches the profile owner via initials, then look across ALL lecturers.
      4. Output: (full_names_str, ids_str)
    """
    from .cleaner import _load_lecturer_db, _normalize_name_for_matching, _flip_author_name
    import re, sys
    from pathlib import Path
    
    lec_by_name, lec_by_sid = _load_lecturer_db()
    
    # Use existing IDs found in Phase 2.5 (no more redundant proxy searches!)
    proxy_ids = existing_author_ids if existing_author_ids else []

    # --- Identify the profile owner via scholar_id ---
    owner_entry = None
    paper_sid = str(paper_scholar_id).strip() if paper_scholar_id else ""
    if paper_sid and paper_sid not in ('', 'nan', 'None') and paper_sid in lec_by_sid:
        owner_entry = lec_by_sid[paper_sid]
    
    # --- Parse author names ---
    raw_str = str(authors_str)
    if ';' in raw_str:
        raw_names = [n.strip() for n in raw_str.split(';') if n.strip()]
    else:
        raw_names = [n.strip() for n in raw_str.split(',') if n.strip()]
    
    if not raw_names:
        return authors_str, ""
    
    final_names = []
    
    # Only keep unique IDs
    raw_final_ids = []
    for raw_name in raw_names:
        if not raw_name:
            continue
        
        matched = None
        abbr_norm = _normalize_name_for_matching(_flip_author_name(raw_name))
        
        if abbr_norm:
            abbr_parts = abbr_norm.split()
            
            # --- Priority 1: Check against profile owner (scholar_id match) ---
            if owner_entry and len(abbr_parts) >= 2:
                owner_norm = _normalize_name_for_matching(owner_entry['nama_norm'])
                if owner_norm:
                    if abbr_norm == owner_norm:
                        matched = owner_entry
                    else:
                        owner_parts = owner_norm.split()
                        if len(owner_parts) >= 2:
                            abbr_last = abbr_parts[-1]
                            abbr_inits = "".join(abbr_parts[:-1]).replace(".", "")
                            owner_inits = "".join([p[0] for p in owner_parts[:-1]])
                            if owner_parts[-1] == abbr_last and owner_inits.startswith(abbr_inits):
                                matched = owner_entry
            
            # --- Priority 2: Check against ALL lecturers (by initials) ---
            if not matched and len(abbr_parts) >= 2:
                abbr_last = abbr_parts[-1]
                abbr_inits = "".join(abbr_parts[:-1]).replace(".", "")
                
                for lec_name, entry in lec_by_name.items():
                    lec_parts = lec_name.split()
                    if len(lec_parts) >= 2:
                        lec_inits = "".join([p[0] for p in lec_parts[:-1]])
                        if lec_parts[-1] == abbr_last and lec_inits.startswith(abbr_inits):
                            matched = entry
                            break
            
            # --- Priority 3: Direct exact name match ---
            if not matched:
                if abbr_norm in lec_by_name:
                    matched = lec_by_name[abbr_norm]

        # --- Collect result ---
        if matched:
            final_names.append(matched['nama_norm'])
            lid = matched.get('scholar_id') or matched.get('scopus_id') or ''
            if lid and lid not in raw_final_ids:
                raw_final_ids.append(lid)
        else:
            final_names.append(raw_name)  # NEVER drop unmatched names!
            
    # Priority 4: Ensure proxy_ids are matched properly or skip them
    # We only inject proxy_ids if they exactly match the number of names, or if we confidently can align them.
    # To avoid the "1 Name but 3 IDs" bug, we skip blind injection.
    if len(proxy_ids) == len(final_names) and len(raw_final_ids) < len(final_names):
        for pid in proxy_ids:
            if pid not in raw_final_ids:
                raw_final_ids.append(pid)

    return "; ".join(final_names), "; ".join(raw_final_ids)


# ─── Main Enrichment ────────────────────────────────────────────

def enrich_paper_batch(
    df: pd.DataFrame,
    batch_size: int = 50,
    start_idx: int = 0,
    allow_paid_proxy: bool = False,
) -> pd.DataFrame:
    """
    Enrich a batch of papers with metadata from free APIs + local TLDR.
    Only processes papers that haven't been enriched yet.

    Args:
        df: DataFrame of papers with at least 'Title' column.
        batch_size: Number of papers to process in this batch.
        start_idx: Starting index for this batch.

    Returns:
        Enriched DataFrame (same length, updated in-place).
    """
    # Ensure columns exist
    for col in ["Abstract", "Keywords", "DOI", "TLDR", "Document Type", "Authors", "Author IDs", "enriched"]:
        if col not in df.columns:
            df[col] = ""

    # Filter un-enriched papers
    mask = df["enriched"].astype(str).str.lower() != "true"
    pending_indices = df[mask].index.tolist()

    if start_idx >= len(pending_indices):
        logger.info("   ✅ All papers already enriched!")
        return df

    batch_indices = pending_indices[start_idx:start_idx + batch_size]
    total = len(batch_indices)

    logger.info(f"\n🔧 ENRICH: Processing batch of {total} papers (idx {start_idx}-{start_idx + total})")
    logger.info("=" * 60)

    stats = {"s2": 0, "oa": 0, "abs": 0, "kw": 0, "doi": 0, "tldr": 0, "tldr_local": 0, "auth_resolved": 0}
    t_start = time.time()

    for count, i in enumerate(batch_indices, 1):
        row = df.loc[i]
        title = str(row.get("Title", "")).strip()
        abstract = str(row.get("Abstract", "")).strip()
        keywords = str(row.get("Keywords", "")).strip()
        doi = str(row.get("DOI", "")).strip()
        tldr = str(row.get("TLDR", "")).strip()
        doc_type = str(row.get("Document Type", "")).strip()
        journal = str(row.get("Journal", "")).strip()
        year = str(row.get("Year", "")).strip()
        authors = str(row.get("Authors", "")).strip()
        author_ids = str(row.get("Author IDs", "")).strip()

        logger.info(f"\n[{count}/{total}] {title[:60]}...")
        
        # Track author IDs collected throughout different phases for final resolution
        collected_author_ids = []

        time.sleep(0.5)  # Rate limiting

        # ── Phase 1: Semantic Scholar ──
        logger.info(f"   [Phase 1] Semantic Scholar...")
        s2 = extract_s2_metadata(doi=doi if doi else None, title=title)
        if s2:
            stats["s2"] += 1
            if not tldr and s2.get('tldr'):
                tldr = str(s2['tldr'].get('text', '')) if isinstance(s2['tldr'], dict) else str(s2['tldr'])
            if not abstract and s2.get('abstract'):
                abstract = clean_abstract_text(s2['abstract'])
            if not doi and s2.get('externalIds', {}).get('DOI'):
                doi = s2['externalIds']['DOI']
            if not year and s2.get('year'):
                year = str(s2['year'])
            if not journal and s2.get('venue'):
                journal = str(s2['venue'])
            if not doc_type and s2.get('publicationTypes'):
                doc_type = ", ".join(s2['publicationTypes'])
                
            # Collect S2 author IDs
            if s2.get('authors'):
                for auth in s2['authors']:
                    if auth.get('authorId'): collected_author_ids.append(auth['authorId'])
        else:
            logger.info(f"      -> MISS: Not found in S2")
        logger.info(f"   [Phase 2] OpenAlex...")
        oa = extract_openalex_metadata(doi=doi if doi else None, title=title)
        if oa:
            stats["oa"] += 1
            if not keywords and oa.get('keywords'):
                keywords = oa['keywords']
            if not doc_type and oa.get('doc_type'):
                doc_type = oa['doc_type']
            if not year and oa.get('publication_year'):
                year = str(oa['publication_year'])
            if not doi and oa.get('doi'):
                doi = oa['doi']
            if not abstract and oa.get('abstract'):
                abstract = clean_abstract_text(oa['abstract'])
            loc = oa.get('primary_location') or {}
            if not journal and loc.get('source'):
                journal = str(loc['source'].get('display_name', ''))
                
            # Collect OpenAlex author IDs
            if oa.get('authorships'):
                for auth in oa['authorships']:
                    if auth.get('author', {}).get('id'):
                        aid = auth['author']['id'].split('/')[-1]
                        if aid not in collected_author_ids: collected_author_ids.append(aid)
        else:
            logger.info(f"      -> MISS: Not found in OpenAlex")

        # ── Phase 2.5: BrightData Google Scholar (PAID) ──
        if allow_paid_proxy and search_scholar_proxy_query and (not abstract or not keywords or not doi):
            logger.info(f"   [Phase 2.5] BrightData Scholar (PAID Proxy)...")
            try:
                bd = search_scholar_proxy_query(title)
                if bd:
                    if not keywords and bd.get("keywords"): keywords = bd["keywords"]
                    if not year and bd.get("year"): year = str(bd["year"])
                    if not journal and bd.get("journal"): journal = str(bd["journal"])
                    
                    # Collect Scholar IDs
                    if bd.get("author_ids"):
                        for aid in bd["author_ids"]:
                            if aid not in collected_author_ids: collected_author_ids.append(aid)
                    
                    # Scholar -> Web scraping fallback (Proxy)
                    if (not keywords or not abstract) and bd.get("title_link"):
                        logger.info(f"      -> Scholar-Web (Proxy): {bd['title_link'][:40]}...")
                        scrape_res = scrape_publisher_page(bd["title_link"], force_proxy=True)
                        if scrape_res:
                            if scrape_res.get("keywords") and not keywords: keywords = scrape_res["keywords"]
                            if scrape_res.get("abstract") and not abstract: abstract = clean_abstract_text(scrape_res["abstract"])
                            if scrape_res.get("doi") and not doi: doi = scrape_res["doi"]
                            
                            # Agentic AI Fallback (LLM-based)
                            if (not abstract or not keywords) and scrape_res.get("raw_content"):
                                logger.info(f"   [Phase 2.6] Agentic AI Fallback (Qwen-Extract)...")
                                ai_res = extract_metadata_via_llm(title, scrape_res["raw_content"])
                                if not abstract and ai_res.get("abstract"): abstract = clean_abstract_text(ai_res["abstract"])
                                if not keywords and ai_res.get("keywords"): keywords = ai_res["keywords"]
                    
                    if not abstract and bd.get("snippet"): abstract = clean_abstract_text(bd["snippet"])
                    logger.info(f"      -> ✓ BD fallback performed")
                else:
                    logger.info(f"      -> MISS: Not found in BD Scholar")
            except Exception as e:
                logger.warning(f"      ⚠️ BD Fallback error: {e}")

        # ── Phase 3: AI TLDR Generation (Groq Llama-3.1-8B) ──
        if not tldr and abstract and len(abstract) > 30:
            logger.info(f"   [Phase 3] AI SciTLDR (Groq Llama-3.1-8B)...")
            ai_tldr = generate_tldr_via_ai(title, abstract)
            if ai_tldr:
                tldr = ai_tldr
                stats["tldr_local"] += 1
                logger.info(f"      ✨ Generated: {tldr[:60]}...")

        # ── Phase 3.5: AI Keyword Generation Fallback ──
        if not keywords and abstract and len(abstract) > 30:
            logger.info(f"   [Phase 3.5] AI Keyword Generation (Groq)...")
            ai_keywords = generate_keywords_from_abstract(abstract)
            if ai_keywords:
                keywords = ai_keywords
                logger.info(f"      ✨ Generated Keywords: {keywords}")

        # ── Phase 4: Scholar ID-Based Author Resolution (using data from Phase 2.5) ──
        paper_sid = str(row.get("scholar_id", "")).strip()
        paper_dosen = str(row.get("dosen", "")).strip()
        
        logger.info(f"   [Phase 4] Author Resolution (ID Matching)...")
        resolved_authors, resolved_ids = _resolve_authors_by_scholar_id(
            authors, paper_sid, paper_dosen, title=title,
            existing_author_ids=collected_author_ids
        )
        
        if resolved_authors != authors or resolved_ids != author_ids:
            authors = resolved_authors
            author_ids = resolved_ids
            stats["auth_resolved"] += 1
            logger.info(f"      ✅ Resolved: {authors} | IDs: {author_ids}")
        else:
            logger.info(f"      ⚠️ No updates made to authors or IDs")

        # ── Fallback defaults ──
        if not doc_type:
            doc_type = "Artikel"

        # ── Update DataFrame ──
        df.at[i, "Abstract"] = abstract
        df.at[i, "Keywords"] = keywords
        df.at[i, "DOI"] = doi
        df.at[i, "TLDR"] = tldr
        df.at[i, "Document Type"] = doc_type
        df.at[i, "Journal"] = journal
        df.at[i, "Year"] = year
        df.at[i, "Authors"] = authors
        df.at[i, "Author IDs"] = author_ids
        df.at[i, "enriched"] = "True"

        # Stats
        if abstract: stats["abs"] += 1
        if keywords: stats["kw"] += 1
        if doi: stats["doi"] += 1
        if tldr: stats["tldr"] += 1

        elapsed = time.time() - t_start
        avg = elapsed / count
        eta = ((total - count) * avg) / 60
        logger.info(f"   ✅ [{count}/{total}] ETA: {eta:.1f} min")

    # Final report
    logger.info(f"\n{'=' * 60}")
    logger.info(f"ENRICHMENT BATCH DONE - {total} papers processed")
    logger.info(f"   S2 hits        : {stats['s2']}/{total}")
    logger.info(f"   OA hits        : {stats['oa']}/{total}")
    logger.info(f"   Abstract       : {stats['abs']}/{total}")
    logger.info(f"   Keywords       : {stats['kw']}/{total}")
    logger.info(f"   DOI            : {stats['doi']}/{total}")
    logger.info(f"   TLDR (total)   : {stats['tldr']}/{total}")
    logger.info(f"   TLDR (AI)      : {stats['tldr_local']}/{total}")
    logger.info(f"   Authors resolved: {stats['auth_resolved']}/{total}")
    logger.info(f"{'=' * 60}")

    return df
