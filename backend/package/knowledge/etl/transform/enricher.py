from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import pandas as pd

from knowledge.etl.config import (
    GROQ_FAST_MODEL,
    GROQ_TLDR_MAX_SOURCE_CHARS,
    GROQ_TLDR_MODEL,
    GROQ_TLDR_OVERWRITE_EXISTING,
    GROQ_TLDR_SLEEP_SECONDS,
)
from knowledge.etl.transform.cleaner import clean_abstract_text, clean_text
from knowledge.etl.extract.semantic_scholar import extract_s2_metadata
from knowledge.etl.extract.openalex import extract_openalex_metadata

if TYPE_CHECKING:
    from groq import Groq

try:
    from knowledge.etl.clients.keyword_scraper import (
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

_groq_client: Optional[Groq] = None


def _get_groq_client() -> Optional[Groq]:
    """Initialize and return the Groq API client."""
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
                    logger.info("GROQ_API_KEY loaded from Airflow Variables.")
            except (ImportError, Exception):
                pass  # Not running in Airflow or variable not found
        
        if not groq_api_key:
            logger.warning("GROQ_API_KEY is not set in environment or Airflow Variables.")
            return None
            
        _groq_client = Groq(api_key=groq_api_key)
        logger.info("Groq API Client initialized successfully.")
        return _groq_client
    except Exception as e:
        logger.warning(f"Failed to initialize Groq client: {e}")
        return None


def _compact_for_tldr(text: str, max_chars: int = GROQ_TLDR_MAX_SOURCE_CHARS) -> str:
    """Keep enough source context for entities while controlling token spend."""
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= max_chars:
        return compact

    head_chars = max(900, int(max_chars * 0.65))
    tail_chars = max_chars - head_chars
    return f"{compact[:head_chars].strip()} ... {compact[-tail_chars:].strip()}"


def _sanitize_tldr_output(output: str) -> str:
    tldr = re.sub(r"\s+", " ", str(output or "")).strip()
    tldr = re.sub(r"^(TLDR|TL;DR)\s*[:\-]\s*", "", tldr, flags=re.I)
    tldr = tldr.strip("`\"' ")
    if "\n" in tldr:
        tldr = tldr.splitlines()[0].strip()
    return tldr


def _sentence_count(text: str) -> int:
    clean = re.sub(r"\b(e\.g|i\.e|et al|vs)\.", lambda m: m.group(0).replace(".", ""), text, flags=re.I)
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", clean) if part.strip()]
    return max(1, len(parts)) if text.strip() else 0


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\S+\b", text))


def _is_valid_tldr(text: str) -> bool:
    if not text or len(text) < 20:
        return False
    if "{" in text or "}" in text or "[" in text or "]" in text:
        return False
    return _sentence_count(text) == 1 and _word_count(text) <= 55


def _truncate_tldr(text: str, max_words: int = 55) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text if text.endswith((".", "!", "?")) else f"{text}."
    truncated = " ".join(words[:max_words]).rstrip(" ,;:")
    return truncated if truncated.endswith((".", "!", "?")) else f"{truncated}."


def generate_tldr_via_ai(title: str, abstract: str) -> str:
    """Generate a KG-oriented one-sentence TLDR using Groq."""
    if not abstract or len(abstract.strip()) < 30:
        return ""

    client = _get_groq_client()
    if client is None:
        return ""

    source_title = _compact_for_tldr(title, 300)
    source_abstract = _compact_for_tldr(abstract)
    system_prompt = (
        "Generate an English KG-oriented TLDR for academic knowledge graph construction. "
        "Output exactly one natural-language sentence, max 55 words, no JSON. "
        "Preserve only facts from the title/abstract. Prioritize ontology entities: "
        "Problem/Task, Field/Domain, Method, Model, Dataset/Data Source, Metric/Result, Tool, Innovation. "
        "When present, include data modality or application domain such as medical image analysis, text mining, "
        "education, social media, or software engineering. Prefer this compact pattern: "
        "'This paper addresses <task/problem> in <domain> using <dataset/source> and <method/model>, achieving <metric/result>.' "
        "If results name a best-performing model variant, include the exact variant. "
        "Keep technical names and metric values exact; avoid vague claims."
    )

    user_prompt = f"Title: {source_title}\nAbstract: {source_abstract}\nTLDR:"

    last_tldr = ""
    for attempt in range(1, 3):
        try:
            completion = client.chat.completions.create(
                model=GROQ_TLDR_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                top_p=1,
                max_tokens=120,
                stream=False,
            )

            tldr = _sanitize_tldr_output(completion.choices[0].message.content)
            last_tldr = tldr
            if _is_valid_tldr(tldr):
                if GROQ_TLDR_SLEEP_SECONDS > 0:
                    time.sleep(GROQ_TLDR_SLEEP_SECONDS)
                return tldr

            user_prompt = (
                f"Title: {source_title}\nAbstract: {source_abstract}\n"
                "Rewrite the TLDR as exactly one English sentence with at most 55 words. TLDR:"
            )
            logger.debug("Retrying Groq TLDR generation; invalid output on attempt %s.", attempt)
        except Exception as e:
            logger.warning("TLDR generation error with Groq model %s: %s", GROQ_TLDR_MODEL, e)
            return ""

    return _truncate_tldr(last_tldr) if last_tldr else ""


def extract_metadata_via_llm(title: str, raw_text: str) -> Dict[str, str]:
    """
    Use Groq API to extract Abstract, Keywords, and DOI from raw website text.
    Used as an Agentic Fallback for tricky publisher pages.
    """
    import json
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
            model=GROQ_FAST_MODEL,
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
            logger.info(f"Agentic AI extraction successful: {len(res['abstract'])} characters of abstract retrieved.")
            
    except Exception as e:
        logger.warning(f"Agentic Extraction error (Groq): {e}")
        
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
            model=GROQ_FAST_MODEL,
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
        logger.warning(f"Keyword generation error (Groq Llama-3.1-8B): {e}")
        return ""


# ─── Scholar ID-Based Author Resolution (like old paper_pipeline.py) ────

def resolve_academic_authors(
    authors_str: str,
    paper_scholar_id: str,
    existing_author_ids: List[str] | Optional[List[str]] = None
) -> Tuple[str, str]:
    """
    Resolve and link author names to the internal lecturer database.
    
    This function:
    1. Normalizes author names.
    2. Matches against the profile owner (scholar_id).
    3. Fuzzy matches remaining authors against the global lecturer database.
    4. Merges provided author IDs (e.g. from APIs) into the result.
    
    Args:
        authors_str: Raw semicolon or comma separated author string.
        paper_scholar_id: The Google Scholar ID of the profile owner.
        existing_author_ids: List of known author IDs from external APIs.
        
    Returns:
        Tuple of (resolved_full_names_str, resolved_author_ids_str).
    """
    from knowledge.etl.transform.cleaner import (
        _load_lecturer_db, 
        _normalize_name_for_matching, 
        _flip_author_name,
        is_abbreviation_match
    )
    
    lec_by_name, lec_by_sid = _load_lecturer_db()
    proxy_ids = existing_author_ids if existing_author_ids else []

    # --- Identify the profile owner ---
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
    final_ids = []
    
    for raw_name in raw_names:
        if not raw_name:
            continue
        
        matched_entry = None
        current_name_norm = _normalize_name_for_matching(_flip_author_name(raw_name))
        
        if current_name_norm:
            # 1. Check against profile owner
            if owner_entry:
                owner_norm = owner_entry['nama_norm']
                if is_abbreviation_match(current_name_norm, owner_norm):
                    matched_entry = owner_entry
            
            # 2. Check against ALL lecturers if not matched
            if not matched_entry:
                for lec_name_norm, entry in lec_by_name.items():
                    if is_abbreviation_match(current_name_norm, lec_name_norm):
                        matched_entry = entry
                        break
            
            # 3. Direct exact name match fallback
            if not matched_entry and current_name_norm in lec_by_name:
                matched_entry = lec_by_name[current_name_norm]

        if matched_entry:
            final_names.append(matched_entry['nama_norm'])
            lid = matched_entry.get('scholar_id') or matched_entry.get('scopus_id') or ''
            if lid and lid not in final_ids:
                final_ids.append(lid)
        else:
            final_names.append(raw_name)
            
    # Inject external proxy IDs safely
    if len(proxy_ids) == len(final_names) and len(final_ids) < len(final_names):
        for pid in proxy_ids:
            if pid not in final_ids:
                final_ids.append(pid)

    return "; ".join(final_names), "; ".join(final_ids)


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
        logger.info("   All papers already enriched!")
        return df

    batch_indices = pending_indices[start_idx:start_idx + batch_size]
    total = len(batch_indices)

    logger.info(f"ENRICHMENT: Processing batch of {total} papers (indices {start_idx} to {start_idx + total})")

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

        logger.info(f"[{count}/{total}] {title[:60]}...")
        
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
            logger.debug(f"Title '{title[:30]}...' not found in Semantic Scholar.")
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
            logger.debug(f"Title '{title[:30]}...' not found in OpenAlex.")

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
                        logger.info(f"Scholar-Web (Proxy): {bd['title_link'][:40]}...")
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
                    logger.info("BD fallback performed successfully.")
                else:
                    logger.info("No data found in BrightData Scholar.")
            except Exception as e:
                logger.warning(f"BD Fallback error: {e}")

        # ── Phase 3: KG-oriented TLDR Generation (Groq) ──
        should_generate_tldr = (
            abstract
            and len(abstract) > 30
            and (GROQ_TLDR_OVERWRITE_EXISTING or not tldr)
        )
        if should_generate_tldr:
            logger.info("   [Phase 3] KG TLDR generation (Groq %s)...", GROQ_TLDR_MODEL)
            ai_tldr = generate_tldr_via_ai(title, abstract)
            if ai_tldr:
                tldr = ai_tldr
                stats["tldr_local"] += 1
                logger.info("Generated KG TLDR: %s...", tldr[:60])

        # ── Phase 3.5: AI Keyword Generation Fallback ──
        if not keywords and abstract and len(abstract) > 30:
            logger.info(f"   [Phase 3.5] AI Keyword Generation (Groq)...")
            ai_keywords = generate_keywords_from_abstract(abstract)
            if ai_keywords:
                keywords = ai_keywords
                logger.info(f"Generated AI Keywords: {keywords}")

        # ── Phase 4: Scholar ID-Based Author Resolution (using data from Phase 2.5) ──
        paper_sid = str(row.get("scholar_id", "")).strip()
        paper_dosen = str(row.get("dosen", "")).strip()
        
        logger.info(f"   [Phase 4] Author Resolution (ID Matching)...")
        resolved_authors, resolved_ids = resolve_academic_authors(
            authors, paper_sid,
            existing_author_ids=collected_author_ids
        )
        
        if resolved_authors != authors or resolved_ids != author_ids:
            authors = resolved_authors
            author_ids = resolved_ids
            stats["auth_resolved"] += 1
        else:
            logger.debug("Author resolution resulted in no changes.")

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
        logger.info(f"Progress: [{count}/{total}] ETA: {eta:.1f} min")

    logger.info(f"ENRICHMENT BATCH COMPLETED - {total} papers processed")
    logger.info(f"Summary Statistics:")
    logger.info(f"  - Semantic Scholar hits : {stats['s2']}/{total}")
    logger.info(f"  - OpenAlex hits         : {stats['oa']}/{total}")
    logger.info(f"  - Abstracts retrieved   : {stats['abs']}/{total}")
    logger.info(f"  - Keywords retrieved    : {stats['kw']}/{total}")
    logger.info(f"  - DOI matches           : {stats['doi']}/{total}")
    logger.info(f"  - TLDRs generated       : {stats['tldr']}/{total} (AI-based: {stats['tldr_local']})")
    logger.info(f"  - Authors resolved      : {stats['auth_resolved']}/{total}")

    return df
