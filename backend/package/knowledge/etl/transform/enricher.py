from __future__ import annotations

import logging
import json
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
from knowledge.etl.transform.ieee_keywords import generate_ieee_keywords
from knowledge.etl.extract.semantic_scholar import extract_s2_metadata
from knowledge.etl.extract.openalex import extract_openalex_metadata
from knowledge.etl.utils.logging import log_event, log_warning

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

REQUIRED_ENRICHMENT_FIELDS = ("Abstract", "Keywords", "Author IDs", "TLDR")


def normalize_document_type(value: Any) -> str:
    """Canonicalize publication document type for downstream KG/database use."""
    doc_type = clean_text(value).lower()
    doc_type = re.sub(r"[-_/]+", " ", doc_type)
    doc_type = re.sub(r"\s+", " ", doc_type).strip()
    compact = re.sub(r"[^a-z0-9]+", "", doc_type)

    if not doc_type or compact in {"", "nan", "none", "null", "na"}:
        return "article"

    if "conference" in doc_type or "conference" in compact or "proceedings" in doc_type:
        return "conference paper"

    article_aliases = {
        "artikel",
        "article",
        "articles",
        "journal",
        "journal article",
        "journal articles",
        "journalarticle",
        "journalarticles",
        "research article",
        "research articles",
        "original article",
        "original articles",
    }
    if doc_type in article_aliases or compact in article_aliases:
        return "article"

    return doc_type


def _has_enrichment_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in {"nan", "none", "null", "na"}


def missing_required_enrichment_fields(
    *,
    abstract: Any = "",
    keywords: Any = "",
    author_ids: Any = "",
    tldr: Any = "",
) -> list[str]:
    """Return missing fields required before a paper can be loaded to KG tables."""
    values = {
        "Abstract": abstract,
        "Keywords": keywords,
        "Author IDs": author_ids,
        "TLDR": tldr,
    }
    return [field for field, value in values.items() if not _has_enrichment_value(value)]


def enrichment_status_from_fields(
    *,
    abstract: Any = "",
    keywords: Any = "",
    author_ids: Any = "",
    tldr: Any = "",
) -> str:
    return "complete" if not missing_required_enrichment_fields(
        abstract=abstract,
        keywords=keywords,
        author_ids=author_ids,
        tldr=tldr,
    ) else "partial"


def _first_source_for(source_contributions: dict[str, list[str]], field: str) -> str:
    field_l = field.lower()
    for source, contributions in source_contributions.items():
        for contribution in contributions:
            if contribution.lower().startswith(field_l):
                return source
    return ""


def _provenance_payload(
    *,
    source_contributions: dict[str, list[str]],
    missing_fields: list[str],
) -> str:
    payload = {
        "field_sources": {
            "abstract": _first_source_for(source_contributions, "Abstract"),
            "keywords": _first_source_for(source_contributions, "Keywords"),
            "doi": _first_source_for(source_contributions, "DOI"),
            "document_type": _first_source_for(source_contributions, "DocType"),
            "tldr": _first_source_for(source_contributions, "TLDR"),
            "authors": _first_source_for(source_contributions, "Authors"),
            "author_ids": _first_source_for(source_contributions, "Author IDs"),
        },
        "sources": {
            source: values
            for source, values in source_contributions.items()
            if values
        },
        "missing_required_fields": missing_fields,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ─── Groq API Client ──────────────────────────────────────────

_groq_client: Optional[Groq] = None
_groq_disabled = False


def _read_secret_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return ""


def _is_groq_auth_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "401" in message or "invalid_api_key" in message or "invalid api key" in message


def _disable_groq_for_run(reason: str) -> None:
    global _groq_client, _groq_disabled
    _groq_client = None
    _groq_disabled = True
    log_warning(logger, "groq.disabled", reason=reason)


def _get_groq_client() -> Optional[Groq]:
    """Initialize and return the Groq API client."""
    global _groq_client
    if _groq_disabled:
        return None
    if _groq_client is not None:
        return _groq_client
    
    try:
        from groq import Groq
        groq_api_key = _read_secret_env(
            "GROQ_API_KEY",
            "AIRFLOW_VAR_GROQ_API_KEY",
            "AIRFLOW_VAR_GROQ_API_KEY_SECRET",
        )
        
        # Fallback: Check Airflow Variables (highest priority)
        if not groq_api_key:
            try:
                from airflow.models import Variable
                groq_api_key = Variable.get("GROQ_API_KEY", default_var=None)
                if groq_api_key:
                    log_event(logger, "groq.key_loaded", source="airflow_variable")
            except (ImportError, Exception):
                pass  # Not running in Airflow or variable not found
        
        if not groq_api_key:
            log_warning(logger, "groq.key_missing", action="skip_llm_generation")
            return None
            
        _groq_client = Groq(api_key=groq_api_key)
        log_event(logger, "groq.client_ready")
        return _groq_client
    except Exception as e:
        log_warning(logger, "groq.client_init_failed", error=e)
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
        "If the source is Indonesian, write the TLDR in English while preserving exact technical names, "
        "dataset names, model names, institution/system names, and metric values. "
        "Translate ordinary Indonesian task, domain, and result phrases into English. "
        "When present, include data modality or application domain such as medical image analysis, text mining, "
        "education, social media, or software engineering. Prefer this compact pattern: "
        "'This paper addresses <task/problem> in <domain> using <dataset/source> and <method/model>, achieving <metric/result>.' "
        "Use 'achieving' only when a concrete metric or stated result exists. "
        "If multiple model variants are tested, use the variant tied to the main or best result when stated. "
        "Do not replace specific variants with generic method families. "
        "Keep technical names and metric values exact; avoid vague claims such as optimal, effective, or efficient "
        "unless the source states them with evidence."
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
            logger.debug("groq.tldr.retry | reason=invalid_output | attempt=%s", attempt)
        except Exception as e:
            if _is_groq_auth_error(e):
                _disable_groq_for_run("invalid GROQ_API_KEY received by worker container")
            else:
                log_warning(logger, "groq.tldr.failed", model=GROQ_TLDR_MODEL, error=e)
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
            log_event(
                logger,
                "groq.metadata_extract.done",
                abstract_chars=len(res["abstract"]),
                has_keywords=bool(res["keywords"]),
                has_doi=bool(res["doi"]),
            )
            
    except Exception as e:
            if _is_groq_auth_error(e):
                _disable_groq_for_run("invalid GROQ_API_KEY received by worker container")
            else:
                log_warning(logger, "groq.metadata_extract.failed", error=e)
        
    return res


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
        flip_author_name,
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
        current_name_norm = _normalize_name_for_matching(flip_author_name(raw_name))
        
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


def _scrape_metadata_links(
    links: list[tuple[str, str, bool]],
    *,
    row_index: int,
    phase: str,
    title: str,
    abstract: str,
    keywords: str,
    doi: str,
    doc_type: str,
) -> tuple[str, str, str, str, list[str]]:
    """Scrape publisher/PDF/DOI links for missing paper metadata."""
    contributions: list[str] = []
    if not scrape_publisher_page or not links:
        return abstract, keywords, doi, doc_type, contributions

    seen_urls: set[str] = set()
    for link_type, url, force_proxy in links:
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        log_event(
            logger,
            "paper.enrich_row.publisher_fetch",
            index=row_index,
            phase=phase,
            link_type=link_type,
            proxy=force_proxy,
            url=url[:120],
        )
        scrape_result = scrape_publisher_page(url, force_proxy=force_proxy)
        if not scrape_result:
            continue

        if (not scrape_result.get("keywords") or not scrape_result.get("abstract")) and scrape_result.get("raw_content"):
            log_event(logger, "paper.enrich_row.llm_extract", index=row_index, phase=phase)
            llm_res = extract_metadata_via_llm(title, scrape_result["raw_content"])
            if llm_res.get("abstract") and not scrape_result.get("abstract"):
                scrape_result["abstract"] = llm_res["abstract"]
            if llm_res.get("keywords") and not scrape_result.get("keywords"):
                scrape_result["keywords"] = llm_res["keywords"]
            if llm_res.get("doi") and not scrape_result.get("doi"):
                scrape_result["doi"] = llm_res["doi"]

        if scrape_result.get("keywords") and not keywords:
            keywords = scrape_result["keywords"]
            contributions.append(f"Keywords({link_type})")
        if scrape_result.get("abstract") and not abstract:
            abstract = clean_abstract_text(scrape_result["abstract"])
            contributions.append(f"Abstract({link_type})")
        if scrape_result.get("doi") and not doi:
            doi = scrape_result["doi"]
            contributions.append(f"DOI({link_type})")
        if scrape_result.get("doc_type") and not doc_type:
            doc_type = scrape_result["doc_type"]
            contributions.append(f"DocType({link_type})")

        if keywords and abstract:
            break

    return abstract, keywords, doi, doc_type, contributions


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
    for col in [
        "Abstract",
        "Keywords",
        "DOI",
        "TLDR",
        "Document Type",
        "Authors",
        "Author IDs",
        "enriched",
        "enrichment_status",
        "missing_required_fields",
        "metadata_provenance",
        "abstract_source",
        "keywords_source",
        "doi_source",
        "document_type_source",
        "tldr_source",
        "author_ids_source",
    ]:
        if col not in df.columns:
            df[col] = ""

    # A paper is complete only when all required KG enrichment inputs exist.
    # The legacy boolean column is kept for compatibility with old artifacts.
    def _row_complete(row: pd.Series) -> bool:
        missing = missing_required_enrichment_fields(
            abstract=row.get("Abstract", ""),
            keywords=row.get("Keywords", ""),
            author_ids=row.get("Author IDs", ""),
            tldr=row.get("TLDR", ""),
        )
        status = str(row.get("enrichment_status", "")).strip().lower()
        return not missing and status != "failed_permanent"

    mask = ~df.apply(_row_complete, axis=1)
    pending_indices = df[mask].index.tolist()

    if start_idx >= len(pending_indices):
        log_event(logger, "paper.enrich_batch.no_pending_rows")
        return df

    batch_indices = pending_indices[start_idx:start_idx + batch_size]
    total = len(batch_indices)

    log_event(
        logger,
        "paper.enrich_batch.start",
        batch_size=total,
        start_idx=start_idx,
        end_idx=start_idx + total,
    )

    stats = {"s2": 0, "oa": 0, "abs": 0, "kw": 0, "doi": 0, "tldr": 0, "tldr_local": 0, "auth_resolved": 0}
    t_start = time.time()

    for count, i in enumerate(batch_indices, 1):
        row = df.loc[i]
        title = clean_text(row.get("Title", ""))
        abstract = clean_abstract_text(row.get("Abstract", ""))
        keywords = clean_text(row.get("Keywords", ""))
        doi = clean_text(row.get("DOI", ""))
        tldr = clean_text(row.get("TLDR", ""))
        doc_type = clean_text(row.get("Document Type", ""))
        journal = clean_text(row.get("Journal", ""))
        year = clean_text(row.get("Year", ""))
        authors = clean_text(row.get("Authors", ""))
        author_ids = str(row.get("Author IDs", "")).strip()

        log_event(logger, "paper.enrich_row.start", index=count, total=total, title=title[:80])
        
        # Track author IDs collected throughout different phases for final resolution
        collected_author_ids = []

        time.sleep(0.5)  # Rate limiting

        pdf_link = ""
        oa_keywords_fallback = ""
        source_contributions = {
            "input": [],
            "s2": [],
            "s2_web": [],
            "oa": [],
            "oa_web": [],
            "bd": [],
            "groq": [],
            "ieee": [],
            "resolver": [],
        }
        if abstract:
            source_contributions["input"].append("Abstract")
        if keywords:
            source_contributions["input"].append("Keywords")
        if doi:
            source_contributions["input"].append("DOI")
        if doc_type:
            source_contributions["input"].append("DocType")
        if tldr:
            source_contributions["input"].append("TLDR")
        if authors:
            source_contributions["input"].append("Authors")
        if author_ids:
            source_contributions["input"].append("Author IDs")

        # ── Phase 1: Semantic Scholar ──
        log_event(logger, "paper.enrich_row.phase", index=count, phase="semantic_scholar")
        s2 = extract_s2_metadata(doi=doi if doi else None, title=title)
        if s2:
            stats["s2"] += 1
            if not tldr and s2.get('tldr'):
                tldr = str(s2['tldr'].get('text', '')) if isinstance(s2['tldr'], dict) else str(s2['tldr'])
                if tldr:
                    source_contributions["s2"].append("TLDR")
            if not abstract and s2.get('abstract'):
                abstract = clean_abstract_text(s2['abstract'])
                source_contributions["s2"].append("Abstract")
            if not doi and s2.get('externalIds', {}).get('DOI'):
                doi = s2['externalIds']['DOI']
                source_contributions["s2"].append("DOI")
            if not year and s2.get('year'):
                year = str(s2['year'])
                source_contributions["s2"].append("Year")
            if not journal and s2.get('venue'):
                journal = str(s2['venue'])
                source_contributions["s2"].append("Journal")
            if not doc_type and s2.get('publicationTypes'):
                doc_type = ", ".join(s2['publicationTypes'])
                source_contributions["s2"].append("DocType")
            if s2.get("openAccessPdf") and s2["openAccessPdf"].get("url"):
                pdf_link = s2["openAccessPdf"]["url"]
                source_contributions["s2"].append("PDF-Link")
                
            # Collect S2 author IDs
            if s2.get('authors'):
                for auth in s2['authors']:
                    if auth.get('authorId'): collected_author_ids.append(auth['authorId'])
        else:
            logger.debug("semantic_scholar.no_match | title=%s", title[:80])

        if (not keywords or not abstract) and (pdf_link or doi):
            links: list[tuple[str, str, bool]] = []
            if pdf_link:
                links.append(("S2-PDF", pdf_link, False))
            if doi:
                links.append(("DOI", f"https://doi.org/{doi}", False))
            abstract, keywords, doi, doc_type, contributions = _scrape_metadata_links(
                links,
                row_index=count,
                phase="semantic_scholar_web",
                title=title,
                abstract=abstract,
                keywords=keywords,
                doi=doi,
                doc_type=doc_type,
            )
            source_contributions["s2_web"].extend(contributions)

        log_event(logger, "paper.enrich_row.phase", index=count, phase="openalex")
        oa = extract_openalex_metadata(doi=doi if doi else None, title=title)
        if oa:
            stats["oa"] += 1
            if oa.get('keywords'):
                oa_keywords_fallback = oa['keywords']
            if not doc_type and oa.get('doc_type'):
                doc_type = oa['doc_type']
                source_contributions["oa"].append("DocType")
            if not year and oa.get('publication_year'):
                year = str(oa['publication_year'])
                source_contributions["oa"].append("Year")
            if not doi and oa.get('doi'):
                doi = oa['doi']
                source_contributions["oa"].append("DOI")
            if not abstract and oa.get('abstract'):
                abstract = clean_abstract_text(oa['abstract'])
                source_contributions["oa"].append("Abstract")
            loc = oa.get('primary_location') or {}
            if not journal and loc.get('source'):
                journal = str(loc['source'].get('display_name', ''))
                if journal:
                    source_contributions["oa"].append("Journal")
            if not authors and oa.get("author_names"):
                authors = "; ".join(name for name in oa["author_names"] if name)
                if authors:
                    source_contributions["oa"].append("Authors")
                
            # Collect OpenAlex author IDs
            for aid in oa.get("author_ids_openalex") or []:
                aid = str(aid).split("/")[-1]
                if aid and aid not in collected_author_ids:
                    collected_author_ids.append(aid)

            if not keywords:
                links = []
                if oa.get("oa_pdf_url"):
                    links.append(("OA-PDF", oa["oa_pdf_url"], False))
                if oa.get("oa_landing_url"):
                    links.append(("OA-Landing", oa["oa_landing_url"], False))
                if doi:
                    links.append(("DOI", f"https://doi.org/{doi}", False))
                abstract, keywords, doi, doc_type, contributions = _scrape_metadata_links(
                    links,
                    row_index=count,
                    phase="openalex_web",
                    title=title,
                    abstract=abstract,
                    keywords=keywords,
                    doi=doi,
                    doc_type=doc_type,
                )
                source_contributions["oa_web"].extend(contributions)

            if not keywords and oa_keywords_fallback:
                keywords = oa_keywords_fallback
                source_contributions["oa"].append("Keywords(OpenAlex concepts)")
        else:
            logger.debug("openalex.no_match | title=%s", title[:80])

        # ── Phase 2.5: BrightData Google Scholar (PAID) ──
        if allow_paid_proxy and search_scholar_proxy_query and (not abstract or not keywords or not doi):
            missing_fields = ",".join(
                field for field, value in (("Abstract", abstract), ("Keywords", keywords), ("DOI", doi)) if not value
            )
            log_event(logger, "paper.enrich_row.phase", index=count, phase="brightdata_scholar", missing=missing_fields)
            try:
                bd = search_scholar_proxy_query(title)
                if bd:
                    if not keywords and bd.get("keywords"):
                        keywords = bd["keywords"]
                        source_contributions["bd"].append("Keywords")
                    if not year and bd.get("year"):
                        year = str(bd["year"])
                        source_contributions["bd"].append("Year")
                    if not journal and bd.get("journal"):
                        journal = str(bd["journal"])
                        source_contributions["bd"].append("Journal")
                    
                    # Collect Scholar IDs
                    if bd.get("author_ids"):
                        for aid in bd["author_ids"]:
                            if aid not in collected_author_ids: collected_author_ids.append(aid)
                    
                    # Scholar -> Web scraping fallback (paid proxy only when needed)
                    scholar_links = []
                    if bd.get("title_link"):
                        scholar_links.append(("Scholar-Pub", bd["title_link"], True))
                    if bd.get("pdf_link"):
                        scholar_links.append(("Scholar-PDF", bd["pdf_link"], True))
                    if bd.get("html_direct"):
                        scholar_links.append(("Scholar-HTML", bd["html_direct"], True))
                    if bd.get("cached_html"):
                        scholar_links.append(("Scholar-Cache", bd["cached_html"], True))
                    if (not keywords or not abstract) and scholar_links:
                        abstract, keywords, doi, doc_type, contributions = _scrape_metadata_links(
                            scholar_links,
                            row_index=count,
                            phase="brightdata_web",
                            title=title,
                            abstract=abstract,
                            keywords=keywords,
                            doi=doi,
                            doc_type=doc_type,
                        )
                        source_contributions["bd"].extend(contributions)
                    
                    if not abstract and bd.get("snippet"):
                        abstract = clean_abstract_text(bd["snippet"])
                        source_contributions["bd"].append("Abstract(snippet)")
                    log_event(
                        logger,
                        "paper.enrich_row.brightdata_done",
                        index=count,
                        contributions=",".join(source_contributions["bd"]) or "none",
                    )
                else:
                    log_event(logger, "paper.enrich_row.brightdata_empty", index=count)
            except Exception as e:
                log_warning(logger, "paper.enrich_row.brightdata_failed", index=count, error=e)
        else:
            logger.debug("brightdata.skipped | index=%s | reason=metadata_complete_or_disabled", count)

        # ── Phase 3: KG-oriented TLDR Generation (Groq) ──
        should_generate_tldr = (
            abstract
            and len(abstract) > 30
            and (GROQ_TLDR_OVERWRITE_EXISTING or not tldr)
        )
        if should_generate_tldr:
            log_event(logger, "paper.enrich_row.phase", index=count, phase="groq_tldr", model=GROQ_TLDR_MODEL)
            ai_tldr = generate_tldr_via_ai(title, abstract)
            if ai_tldr:
                tldr = ai_tldr
                source_contributions["groq"].append("TLDR")
                stats["tldr_local"] += 1
                log_event(logger, "paper.enrich_row.tldr_done", index=count, words=_word_count(tldr))

        # ── Phase 3.5: IEEE-Controlled Keyword Fallback ──
        if not keywords and abstract and len(abstract) > 30:
            log_event(logger, "paper.enrich_row.phase", index=count, phase="ieee_keywords")
            keyword_basis = tldr if tldr and len(tldr) > 30 else abstract
            controlled_keywords = generate_ieee_keywords(
                title=title,
                abstract=keyword_basis,
                min_keywords=3,
                max_keywords=3,
            )
            if controlled_keywords:
                keywords = controlled_keywords
                source_contributions["ieee"].append("Keywords")
                log_event(logger, "paper.enrich_row.keywords_done", index=count, keywords=keywords)

        # ── Phase 4: Scholar ID-Based Author Resolution (using data from Phase 2.5) ──
        paper_sid = str(row.get("scholar_id", "")).strip()
        paper_dosen = str(row.get("dosen", "")).strip()
        
        log_event(logger, "paper.enrich_row.phase", index=count, phase="author_resolution")
        resolved_authors, resolved_ids = resolve_academic_authors(
            authors, paper_sid,
            existing_author_ids=collected_author_ids
        )
        
        if resolved_authors != authors or resolved_ids != author_ids:
            authors = resolved_authors
            author_ids = resolved_ids
            source_contributions["resolver"].extend(["Authors", "Author IDs"])
            stats["auth_resolved"] += 1
        else:
            logger.debug("author_resolution.no_change | index=%s", count)

        # ── Fallback defaults ──
        if not doc_type:
            doc_type = "article"
            source_contributions["input"].append("DocType(default)")
        doc_type = normalize_document_type(doc_type)
        missing_required = missing_required_enrichment_fields(
            abstract=abstract,
            keywords=keywords,
            author_ids=author_ids,
            tldr=tldr,
        )
        enrichment_status = "complete" if not missing_required else "partial"
        provenance = _provenance_payload(
            source_contributions=source_contributions,
            missing_fields=missing_required,
        )

        # ── Update DataFrame ──
        df.at[i, "Title"] = title
        df.at[i, "Abstract"] = abstract
        df.at[i, "Keywords"] = keywords
        df.at[i, "DOI"] = doi
        df.at[i, "TLDR"] = tldr
        df.at[i, "Document Type"] = doc_type
        df.at[i, "Journal"] = journal
        df.at[i, "Year"] = year
        df.at[i, "Authors"] = authors
        df.at[i, "Author IDs"] = author_ids
        df.at[i, "enrichment_status"] = enrichment_status
        df.at[i, "missing_required_fields"] = "; ".join(missing_required)
        df.at[i, "metadata_provenance"] = provenance
        df.at[i, "abstract_source"] = _first_source_for(source_contributions, "Abstract")
        df.at[i, "keywords_source"] = _first_source_for(source_contributions, "Keywords")
        df.at[i, "doi_source"] = _first_source_for(source_contributions, "DOI")
        df.at[i, "document_type_source"] = _first_source_for(source_contributions, "DocType")
        df.at[i, "tldr_source"] = _first_source_for(source_contributions, "TLDR")
        df.at[i, "author_ids_source"] = _first_source_for(source_contributions, "Author IDs")
        df.at[i, "enriched"] = "True" if enrichment_status == "complete" else "False"

        # Stats
        if abstract: stats["abs"] += 1
        if keywords: stats["kw"] += 1
        if doi: stats["doi"] += 1
        if tldr: stats["tldr"] += 1

        elapsed = time.time() - t_start
        avg = elapsed / count
        eta = ((total - count) * avg) / 60
        log_event(
            logger,
            "paper.enrich_row.done",
            index=count,
            total=total,
            status=enrichment_status,
            missing=",".join(missing_required) or "none",
            eta_minutes=f"{eta:.1f}",
        )

    log_event(
        logger,
        "paper.enrich_batch.done",
        rows=total,
        semantic_scholar_hits=stats["s2"],
        openalex_hits=stats["oa"],
        abstracts=stats["abs"],
        keywords=stats["kw"],
        dois=stats["doi"],
        tldrs=stats["tldr"],
        tldrs_groq=stats["tldr_local"],
        authors_resolved=stats["auth_resolved"],
    )

    return df
