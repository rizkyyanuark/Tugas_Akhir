# scraping_modules/keyword_scraper.py
"""
Multi-Source Keyword & Abstract Extraction Module
=================================================
Integrated from 'scraping scopus.ipynb' + API fallbacks.

Enrichment flow:
  1. SerpAPI Citation API → abstract, title, publisher link (structured)
  1b. BrightData Scholar Page → publisher/PDF link (proxy scraping)
  2. Publisher/PDF Page → keywords, abstract, DOI (proxy scraping)
  2b. CrossRef API → DOI fallback (free, title-based)
  2c. OpenAlex API → keyword/concept fallback (free)
  3. Semantic Scholar → TLDR

Proxy strategy (from notebook):
  - Session-based BrightData proxy for Scholar + publisher pages
  - Direct first for local/open-access journals
  - Proxy fallback for known protected sites
"""

import os
import re
import time
import json
import random
import requests
import urllib.parse
import urllib3
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .config import SERPAPI_KEY, BD_USER_UNLOCKER, BD_PASS_UNLOCKER, BD_USER_SERP, BD_PASS_SERP, BRIGHT_DATA_HOST

import sys
from pathlib import Path

import logging

logger = logging.getLogger(__name__)

try:
    from knowledge.etl.transform import cleaner
except ImportError as e:
    logger.error(f"Could not import ETL cleaner: {e}")
    cleaner = None

def _deep_clean_abstract(text):
    if not text: return ""
    import re
    cleaned = str(text).strip()
    # Hapus noise awalan seperti "Abstrak—", "Abstract:" walau ada spasi di awal
    cleaned = re.sub(r'^\s*(?i:abstract|abstrak)[\s\-—–:.]+[\s]*', '', cleaned)
    # Hapus blok "Kata Kunci - ..." yang nyangkut di akhir abstract
    cleaned = re.sub(r'(?i)\s*(?:kata\s+kunci|keywords?|key\s+words?|subject\s+terms?|index\s+terms?)[\s:\-—–\.].*$', '', cleaned, flags=re.DOTALL)
    
    return cleaner.clean_text(cleaned) if cleaner else cleaned.strip()

def _clean_keywords(text):
    if not text: return ""
    import re
    cleaned = re.sub(r'[;|]', ',', str(text))
    cleaned = re.sub(r',+', ',', cleaned)
    if cleaner:
        cleaned = cleaner.clean_text(cleaned).lower().strip(',')
    return ', '.join([k.strip() for k in cleaned.split(',') if k.strip()])


# ================================================================
# HTTP HELPERS (from notebook: request_hybrid_stealth)
# ================================================================

_UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]

# Sites that almost always need proxy to avoid paywall/block
_PROXY_DOMAINS = [
    "sciencedirect.com", "researchgate.net", "ieee.org",
    "springer.com", "wiley.com", "tandfonline.com",
    "sagepub.com", "acm.org", "nature.com",
]


def _needs_proxy(url):
    """Check if URL domain is known to need proxy."""
    return any(d in url.lower() for d in _PROXY_DOMAINS)


def _detect_anti_bot(resp):
    """
    Detect Cloudflare / anti-bot challenge from HTTP response.
    Returns (is_blocked: bool, reason: str).
    """
    if resp is None:
        return False, ""

    # 1. Cloudflare status codes + header
    if resp.status_code in (403, 503) and 'cf-ray' in resp.headers:
        return True, f"Cloudflare {resp.status_code}"

    # 2. Cloudflare challenge header
    if resp.headers.get('cf-mitigated', '').lower() == 'challenge':
        return True, "Cloudflare Challenge"

    # 3. HTML content signals (hanya jika bukan stream)
    try:
        text = resp.text[:2000].lower()
    except Exception:
        return False, ""

    _ANTI_BOT_SIGNALS = [
        ("just a moment",        "Cloudflare Interstitial"),
        ("checking your browser", "Cloudflare IUAM"),
        ("attention required",   "Cloudflare Block"),
        ("access denied",        "Access Denied"),
        ("please enable cookies", "Cookie Wall"),
        ("unusual traffic",      "Rate Limited"),
        ("captcha",              "CAPTCHA"),
        ("ray id",               "Cloudflare Ray"),
    ]
    for signal, reason in _ANTI_BOT_SIGNALS:
        if signal in text:
            return True, reason

    return False, ""


def _get_headers(referer="https://scholar.google.com/"):
    return {
        "User-Agent": random.choice(_UA_LIST),
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _build_session_proxy(proxy_type="UNLOCKER"):
    """Build session-based proxy dict (matching notebook's pattern)."""
    if proxy_type == "SERP":
        bd_user = BD_USER_SERP
        bd_pass = BD_PASS_SERP
    else:
        bd_user = BD_USER_UNLOCKER
        bd_pass = BD_PASS_UNLOCKER

    if not bd_user or not bd_pass or not BRIGHT_DATA_HOST:
        return None
        
    session_id = str(random.randint(10000, 99999))
    proxy_auth = f"{bd_user}-session-{session_id}:{bd_pass}"
    return {
        "http": f"http://{proxy_auth}@{BRIGHT_DATA_HOST}",
        "https": f"http://{proxy_auth}@{BRIGHT_DATA_HOST}",
    }


def request_hybrid_stealth(url, use_proxy=True, stream=False,
                           referer="https://scholar.google.com/",
                           timeout=120):
    """
    HTTP GET matching notebook's request_hybrid_stealth.
    1. If use_proxy=True, try BrightData session proxy first (120s timeout)
    2. Fallback to direct request (15s timeout)
    """
    headers = _get_headers(referer)

    if use_proxy:
        # Determine route based on URL
        if "scholar.google" in url.lower():
            proxy_type = "SERP"
        else:
            proxy_type = "UNLOCKER"

        proxies = _build_session_proxy(proxy_type)
        if proxies:
            try:
                resp = requests.get(
                    url, proxies=proxies, headers=headers,
                    verify=False, timeout=timeout, stream=stream,
                    allow_redirects=True
                )
                if resp.status_code == 200:
                    if not stream:
                        is_blocked, reason = _detect_anti_bot(resp)
                        if is_blocked:
                            logger.warning(f"      ⛔ Proxy blocked ({reason}). Falling back to direct...")
                        else:
                            return resp
                    else:
                        return resp
                else:
                    logger.warning(f"      ⚠️ Proxy Status: {resp.status_code}. Falling back to direct...")
            except Exception as e:
                logger.error(f"      💥 Proxy Error: {e}. Falling back to direct...")

    # 2) Direct request (fallback)
    try:
        # Quick DNS/Connection Ping (Fail Fast for dead servers)
        try:
            requests.head(url, headers=headers, verify=False, timeout=3, allow_redirects=True)
        except requests.exceptions.ConnectionError:
            logger.warning(f"      ⛔ Koneksi Server Mati / DNS Error ({url[:40]}). Skip!")
            return None
        except requests.exceptions.Timeout:
            pass  # Lanjut saja jika cuma head timeout

        resp = requests.get(
            url, headers=headers, verify=False,
            timeout=15, stream=stream, allow_redirects=True
        )
        if resp.status_code == 200:
            return resp
    except Exception:
        pass
    return None


def request_smart(url, timeout=30, stream=False):
    """
    Smart HTTP GET with anti-bot detection + proxy fallback.
    Flow: known-proxy-domain? → direct request → detect Cloudflare → Web Unlocker
    """
    headers = _get_headers()

    # If it's a known protected site, go proxy first
    if _needs_proxy(url):
        resp = _request_with_proxy(url, headers, timeout, stream)
        if resp:
            return resp

    # Try direct first
    try:
        # Quick DNS ping (fail fast for dead servers)
        try:
            requests.head(url, headers=headers, verify=False, timeout=3, allow_redirects=True)
        except requests.exceptions.ConnectionError:
            logger.warning(f"      ⛔ Koneksi Server Mati / DNS Error ({url[:40]}). Skip!")
            return None
        except requests.exceptions.Timeout:
            pass

        resp = requests.get(
            url, headers=headers, verify=False,
            timeout=15, stream=stream,
            allow_redirects=True
        )
        # Check for anti-bot on success (Cloudflare can return 200 with challenge)
        if resp.status_code == 200:
            if not stream:
                is_blocked, reason = _detect_anti_bot(resp)
                if is_blocked:
                    logger.info(f"      🛡️ Anti-Bot Detected ({reason}). Escalating to Web Unlocker...")
                else:
                    return resp
            else:
                return resp
        # Check for anti-bot on 403/503 (Cloudflare block)
        elif resp.status_code in (403, 503):
            is_blocked, reason = _detect_anti_bot(resp)
            if is_blocked:
                logger.info(f"      🛡️ Anti-Bot Detected ({reason}). Escalating to Web Unlocker...")
            else:
                logger.warning(f"      ⚠️ HTTP {resp.status_code} (non-CF). Trying Web Unlocker...")
    except Exception:
        pass

    # Fallback to proxy (Web Unlocker) if available
    return _request_with_proxy(url, headers, timeout, stream)

def _request_with_proxy(url, headers, timeout=20, stream=False):
    """Make request through BrightData Web Unlocker proxy."""
    try:
        proxies = _build_session_proxy("UNLOCKER")
        if not proxies: return None
        resp = requests.get(
            url, headers=headers, proxies=proxies,
            verify=False, timeout=timeout, stream=stream,
            allow_redirects=True
        )
        if resp.status_code == 200:
            return resp
    except Exception:
        pass
    return None


# ================================================================
# SERPAPI CITATION RESOLVER
# ================================================================

def resolve_citation_serpapi(scholar_citation_url, api_key=None):
    """
    Use SerpAPI to get structured citation data from Scholar citation URL.

    Returns dict with:
        title, link (publisher), authors (full), abstract (description),
        journal, volume, pages, publisher, publication_date, doi,
        resources (PDF links)
    """
    api_key = api_key or SERPAPI_KEY

    # Parse author_id and citation_id from URL
    parsed = urllib.parse.urlparse(scholar_citation_url)
    params = urllib.parse.parse_qs(parsed.query)

    author_id = params.get("user", [None])[0]
    citation_for_view = params.get("citation_for_view", [None])[0]

    if not author_id or not citation_for_view:
        return None

    # citation_for_view IS the citation_id (e.g. "tzjThtIAAAAJ:u5HHmVD_uO8C")
    citation_id = citation_for_view

    try:
        resp = requests.get("https://serpapi.com/search.json", params={
            "engine": "google_scholar_author",
            "author_id": author_id,
            "view_op": "view_citation",
            "citation_id": citation_id,
            "api_key": api_key,
            "hl": "en",
        }, timeout=30)

        if resp.status_code != 200:
            logger.warning(f"      [SerpAPI] HTTP {resp.status_code}")
            return None

        data = resp.json()
        citation = data.get("citation", {})

        result = {
            "title": citation.get("title", ""),
            "link": citation.get("link", ""),
            "authors_full": citation.get("authors", ""),
            "abstract": citation.get("description", ""),
            "journal": citation.get("journal", ""),
            "volume": citation.get("volume", ""),
            "pages": citation.get("pages", ""),
            "publisher": citation.get("publisher", ""),
            "publication_date": citation.get("publication_date", ""),
            "resources": citation.get("resources", []),
        }

        # Try to extract DOI from publisher link
        if result["link"]:
            doi = extract_doi(result["link"])
            if doi:
                result["doi"] = doi

        return result

    except Exception as e:
        logger.error(f"      [SerpAPI] Error: {e}")
        return None


# ================================================================
# BRIGHTDATA SCHOLAR CITATION RESOLVER (from notebook)
# ================================================================

def find_best_links(html, base_url="https://scholar.google.com",
                    is_search_result=False):
    """Parse Scholar SERP page for PDF/HTML/main links (from notebook)."""
    soup = BeautifulSoup(html, 'html.parser')
    result = {
        "pdf_direct": None, "html_direct": None, "main_link": None,
        "snippet": None, "author_ids": []
    }

    if is_search_result:
        # Check first result container for snippet/abstract
        # gs_r = result row, gs_ri = result info
        first_res = soup.select_one('.gs_r.gs_or.gs_scl') or soup.find('div', class_='gs_r')
        if first_res:
            # Full Metadata Abstract snippet (user's suggestion)
            fma = first_res.select_one('.gs_fma_snp')
            if fma:
                result["snippet"] = fma.get_text(" ", strip=True)
            
            # Regular snippet (fallback)
            if not result["snippet"]:
                rs = first_res.select_one('.gs_rs')
                if rs:
                    result["snippet"] = rs.get_text(" ", strip=True)

            # Authors and their IDs from metadata line
            a_line = first_res.select_one('.gs_a')
            if a_line:
                for a in a_line.find_all('a', href=True):
                    href = a['href']
                    if 'user=' in href:
                        match = re.search(r'user=([^&]+)', href)
                        if match:
                            result["author_ids"].append(match.group(1))

        if not soup.find('div', class_='gs_r') and \
           not soup.find('div', class_='gs_ri'):
            return None

    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        text = a.get_text().strip().lower()
        if 'javascript' in href.lower():
            continue
        full_url = (href if href.startswith('http')
                    else urllib.parse.urljoin(base_url, href))

        if ((href.lower().endswith('.pdf') or '/download/' in href.lower()
             or '[pdf]' in text) and not result["pdf_direct"]):
            result["pdf_direct"] = full_url
        if (('view as html' in text or
            ('cache:' in href and 'scholar.google' in href))
            and not result["html_direct"]):
            result["html_direct"] = href
        if not result["main_link"]:
            parent = a.find_parent('h3', class_='gs_rt')
            if parent and 'scholar.google' not in full_url:
                result["main_link"] = full_url

    return result


def resolve_scholar_citation_proxy(url, max_retries=2):
    """
    Resolve Scholar citation page via BrightData proxy.
    Returns dict: {title_link, pdf_link, html_direct, title_text, snippet, author_ids, abstract}
    """
    logger.info(f"   [BrightData] Resolving Scholar Citation Page...")
    for attempt in range(max_retries):
        if attempt > 0:
            logger.info(f"      🔄 Retry {attempt+1}/{max_retries}...")
        resp = request_hybrid_stealth(url, use_proxy=True)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, 'html.parser')
        result = {
            "title_link": None, "pdf_link": None,
            "html_direct": None, "title_text": None,
            "snippet": None, "author_ids": [],
            "abstract": None
        }

        # 1. Extract metadata directly from the citation page (View Citation)
        # Usually pairs of .gsc_oci_field and .gsc_oci_value
        fields = soup.select('.gsc_oci_field')
        values = soup.select('.gsc_oci_value')
        for f, v in zip(fields, values):
            field_text = f.get_text().strip().lower()
            if 'abstract' in field_text or 'deskripsi' in field_text:
                result["abstract"] = v.get_text(" ", strip=True)
            elif 'authors' in field_text or 'penulis' in field_text:
                # Try to extract user IDs if links are present
                for a in v.find_all('a', href=True):
                    if 'user=' in a['href']:
                        match = re.search(r'user=([^&]+)', a['href'])
                        if match:
                            result["author_ids"].append(match.group(1))

        title_tag = soup.select_one('a.gsc_oci_title_link')
        if title_tag:
            result["title_text"] = title_tag.get_text().strip()

        # Priority 1: Direct PDF
        pdf_el = soup.select_one('.gsc_oci_title_ggi a')
        if pdf_el:
            result["pdf_link"] = pdf_el['href']
            logger.info(f"      📄 Found Direct PDF: {result['pdf_link'][:50]}...")
            # We don't return immediately anymore, we already have citation-page abstract if it was there

        # Priority 2: External publisher link
        if title_tag:
            title_link = title_tag['href']
            if "scholar.google" not in title_link:
                result["title_link"] = title_link
                logger.info(f"      ✅ External Publisher Link: {title_link[:40]}...")
                if result["pdf_link"] or result["title_link"]:
                    return result

        # Priority 3: Rescue via related articles
        related_url = None
        for a in soup.find_all('a', class_='gsc_oms_link'):
            if ('related:' in a.get('href', '') or
                    'Related articles' in a.get_text()):
                related_url = a['href']
                if related_url.startswith('/'):
                    related_url = "https://scholar.google.com" + related_url
                related_url = related_url.replace('&amp;', '&')
                break

        if related_url:
            rel_resp = request_hybrid_stealth(related_url, use_proxy=True)
            if rel_resp:
                rescue_links = find_best_links(
                    rel_resp.text, is_search_result=True)
                if rescue_links:
                    result["snippet"] = rescue_links.get("snippet")
                    # Merge author IDs
                    new_ids = rescue_links.get("author_ids", [])
                    result["author_ids"] = list(set(result["author_ids"] + new_ids))
                    
                    if rescue_links["pdf_direct"] or rescue_links["main_link"]:
                        if rescue_links["pdf_direct"]:
                            result["pdf_link"] = rescue_links["pdf_direct"]
                        else:
                            result["title_link"] = rescue_links["main_link"]
                        logger.info(f"      ✨ RESCUE SUCCESS!")
                        return result
                    
                    if result["snippet"] or result["abstract"]:
                        logger.info(f"      📝 Rescue found snippet/abstract fallback.")
                        return result

        # Priority 4: Try cluster page
        if not title_tag:
            # If no title tag but we have some abstract/snippet from citation page, return it
            if result["abstract"] or result["snippet"]:
                return result
            continue

        title_link = title_tag['href']
        if "scholar.google" in title_link:
            logger.warning(f"      ⚠️ Scholar internal link. Fetching cluster...")
            cluster_resp = request_hybrid_stealth(title_link, use_proxy=True)
            if cluster_resp:
                links = find_best_links(cluster_resp.text, is_search_result=True)
                if links:
                    result["snippet"] = links.get("snippet")
                    new_ids = links.get("author_ids", [])
                    result["author_ids"] = list(set(result["author_ids"] + new_ids))
                    
                    if links["pdf_direct"]:
                        result["pdf_link"] = links["pdf_direct"]
                        return result
                    if links["html_direct"]:
                        result["html_direct"] = links["html_direct"]
                        return result
                    
                    if result["snippet"]:
                        logger.info(f"      📝 Cluster found snippet fallback.")
                        return result

        if result["pdf_link"] or result["title_link"] or result["abstract"] or result["snippet"]:
            return result

    return None


def search_scholar_proxy_query_html(title, max_retries=2):
    """
    Search Google Scholar via HTML parsing (Fallback for SERP API).
    """
    logger.info(f"   [BrightData] Searching Scholar (HTML) for: {title[:50]}...")
    url = f"https://scholar.google.com/scholar?hl=en&q={urllib.parse.quote(title)}"

    for attempt in range(max_retries):
        if attempt > 0:
            logger.info(f"      🔄 Retry {attempt+1}/{max_retries}...")
        resp = request_hybrid_stealth(url, use_proxy=True)
        if not resp:
            continue
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        first_res = soup.select_one('.gs_r.gs_or.gs_scl') or soup.find('div', class_='gs_r')
        if not first_res:
            continue
            
        result = {
            "title_link": None, "pdf_link": None, "html_direct": None,
            "cached_html": None,
            "snippet": None, "author_ids": [], "journal": None, "year": None,
            "title_text": None,
            "abstract": None
        }
        
        title_tag = first_res.select_one('.gs_rt a')
        if title_tag:
            result["title_text"] = title_tag.get_text(" ", strip=True)
            result["title_link"] = title_tag['href']

        a_line = first_res.select_one('.gs_a')
        if a_line:
            a_text = a_line.get_text(" ", strip=True)
            parts = [p.strip() for p in a_text.split('-')]
            if len(parts) >= 2:
                year_match = re.search(r'\b(19|20)\d{2}\b', a_text)
                if year_match: result["year"] = int(year_match.group(0))
                middle_part = parts[1]
                if ',' in middle_part and result["year"] and str(result["year"]) in middle_part.split(',')[-1]:
                    result["journal"] = ",".join(middle_part.split(',')[:-1]).strip()
                elif result["year"] and str(result["year"]) not in middle_part:
                    result["journal"] = middle_part
            for a in a_line.find_all('a', href=True):
                if 'user=' in a['href']:
                    match = re.search(r'user=([^&]+)', a['href'])
                    if match: result["author_ids"].append(match.group(1))

        fma = first_res.select_one('.gs_fma_snp')
        if fma:
            result["snippet"] = fma.get_text(" ", strip=True)
        else:
            rs = first_res.select_one('.gs_rs')
            if rs: result["snippet"] = rs.get_text(" ", strip=True)
        result["abstract"] = result["snippet"]

        ctg_links = first_res.select('.gs_ctg2')
        for ctg in ctg_links:
            parent = ctg.parent
            if parent and parent.name == 'a':
                href = parent['href']
                ctg_text = ctg.get_text(strip=True).upper()
                if '[PDF]' in ctg_text: result["pdf_link"] = href
                elif '[HTML]' in ctg_text: result["html_direct"] = href
            
        right_side = first_res.select('.gs_or_ggsm a')
        for a in right_side:
            if not result["pdf_link"] and ('pdf' in a.get_text().lower() or a['href'].endswith('.pdf')):
                result["pdf_link"] = a['href']
        
        for a in first_res.find_all('a', href=True):
            if 'scholar.googleusercontent.com/scholar' in a['href'] and 'cache:' in a['href']:
                result["cached_html"] = a['href']
                break
                
        logger.info(f"      ✅ Found HTML Search Result: {str(result.get('title_text', ''))[:40]}...")
        if result['pdf_link']: logger.info(f"      📄 PDF Link: {str(result['pdf_link'])[:50]}...")
        return result
    logger.warning("      ⚠️ No results found on Scholar Search (HTML).")
    return None

def search_scholar_proxy_query(title, max_retries=2):
    """
    Search Google Scholar using BrightData Web Unlocker (HTML).
    Redirects to HTML scraping as the direct SERP API often fails for Scholar.
    """
    return search_scholar_proxy_query_html(title, max_retries=max_retries)




def scrape_scholar_citation_page(url):
    """
    Directly scrapes a Google Scholar Citation Profile Page to get the abstract and publisher links.
    URL Format: https://scholar.google.com/citations?view_op=view_citation...
    """
    logger.info(f"   [Scholar Profile] Scraping citation page directly...")
    resp = request_hybrid_stealth(url, use_proxy=True)
    if not resp:
        return {}
        
    soup = BeautifulSoup(resp.text, 'html.parser')
    result = {
        "abstract": None,
        "publisher_link": None,
        "pdf_link": None
    }
    
    # Description / Abstract usually in .gsh_small or #gsc_oci_descr
    desc_field = soup.find('div', class_='gsh_small') or soup.find('div', class_='gsh_csp')
    if not desc_field:
        desc_container = soup.find(id='gsc_oci_descr')
        if desc_container:
            # Sometime the abstract is inside a div holding value
            desc_field = desc_container.find('div', class_='gsc_oci_value') or desc_container
            
    if desc_field:
        # Extract the text and remove "Description" prefix if present
        abs_text = desc_field.get_text(separator=' ', strip=True)
        if abs_text.lower().startswith('description'):
            abs_text = abs_text[11:].strip()
        result["abstract"] = abs_text
        
    # Find publisher link
    pub_link_el = soup.find('a', class_='gsc_oci_title_link')
    if pub_link_el:
        result["publisher_link"] = pub_link_el.get('href')
        
    # PDF link
    pdf_div = soup.find('div', id='gsc_oci_title_gg')
    if pdf_div:
        pdf_a = pdf_div.find('a')
        if pdf_a:
             result["pdf_link"] = pdf_a.get('href')
             
    return result


# ================================================================
# DOI EXTRACTION
# ================================================================

def extract_doi(url):
    """Extract DOI from a URL string."""
    if not url:
        return ""
    match = re.search(r'(10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+)', url)
    if match:
        doi = match.group(1)
        # Clean trailing junk
        doi = doi.split('&')[0].split('%')[0].rstrip('.')
        return doi
    return ""


# ================================================================
# PMC API HELPERS (from notebook)
# ================================================================

def get_pmc_id(url):
    """Extract PMC ID from URL."""
    match = re.search(r'(PMC\d+)', url, re.IGNORECASE)
    return match.group(1) if match else None


def fetch_pmc_api_keywords(pmc_id):
    """Fetch keywords from NCBI/PMC API via XML."""
    api_url = (f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
               f"efetch.fcgi?db=pmc&id={pmc_id}&retmode=xml")
    try:
        resp = requests.get(
            api_url, headers={"User-Agent": "ResearchScript/1.0"},
            timeout=30
        )
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            keywords = [kwd.text for kwd in root.findall(".//kwd")
                        if kwd.text]
            return keywords
    except Exception:
        pass
    return None


def _normalize_keywords(kw_str):
    """Normalize keyword string: clean whitespace, trim, deduplicate separators."""
    if not kw_str:
        return ""
    # Collapse all whitespace (tabs, newlines, multiple spaces) to single space
    cleaned = re.sub(r'\s+', ' ', kw_str).strip()
    # Split by comma or semicolon, clean each term  
    parts = [p.strip().rstrip('.') for p in re.split(r'[,;]', cleaned) if p.strip()]
    # Remove empty or very short terms
    parts = [p for p in parts if len(p) > 1]
    if not parts:
        return ""
    return ", ".join(parts)


def extract_keywords_from_html(html):
    """
    Extract keywords from HTML using multiple strategies.
    Returns normalized keywords string or empty string.
    """
    raw = _extract_keywords_impl(html)
    return _normalize_keywords(raw)


def _extract_keywords_impl(html):
    """Internal: extract raw keywords from HTML (will be normalized by wrapper)."""
    if not html:
        return ""

    soup = BeautifulSoup(html, 'html.parser')

    # Strategy 0: EBSCO __NEXT_DATA__ (Next.js SSR)
    # The detailv2 page embeds subjects in __NEXT_DATA__ JSON
    next_data = soup.find('script', id='__NEXT_DATA__')
    if next_data and next_data.string:
        try:
            nd = json.loads(next_data.string)
            item_info = (nd.get('props', {})
                          .get('pageProps', {})
                          .get('data', {})
                          .get('item', {})
                          .get('itemInfo', {}))
            subjects = item_info.get('subjects', '')
            if subjects:
                # EBSCO uses ";" separator → normalize to ", "
                kws = [s.strip() for s in subjects.split(';')
                       if s.strip()]
                if kws:
                    return ", ".join(kws)
        except Exception:
            pass

    # Strategy 1: EBSCO / structured subject links (visible HTML)
    # Hanya match elemen label pendek, BUKAN kalimat abstract yang mengandung "subjects"
    for h in soup.find_all(['dt', 'div', 'span'],
                           string=re.compile(r'\bSubjects?\b|\bKeywords?\b', re.IGNORECASE)):
        # Pastikan ini label, bukan paragraf panjang
        label_text = h.get_text(strip=True)
        if len(label_text) > 30:
            continue
        sib = h.find_next_sibling(['dd', 'div', 'span'])
        if sib:
            found = [l.get_text(strip=True) for l in sib.find_all('a')
                     if len(l.get_text(strip=True)) > 2]
            if found:
                return ", ".join(found)

    # Strategy 2: IEEE xplGlobal metadata
    # IEEE has 3 keyword types: "IEEE Keywords", "INSPEC: *", "Author Keywords"
    # We ONLY want "Author Keywords" (from the paper's authors)
    for script in soup.find_all('script'):
        if script.string and 'xplGlobal' in script.string:
            match = re.search(
                r'xplGlobal.*?metadata\s*=\s*({.*?});',
                script.string, re.DOTALL
            )
            if match:
                try:
                    data = json.loads(match.group(1))
                    all_kw_sections = data.get('keywords', [])
                    
                    # Prioritas: Author Keywords saja
                    author_kw = []
                    all_kw = []
                    for section in all_kw_sections:
                        kw_type = section.get('type', '')
                        kwds = section.get('kwd', [])
                        if kwds:
                            all_kw.extend(kwds)
                            if 'Author' in kw_type:
                                author_kw.extend(kwds)
                    
                    # Pakai Author Keywords jika ada, jika tidak fallback semua
                    final_kw = author_kw if author_kw else all_kw
                    if final_kw:
                        return ", ".join(final_kw)
                except Exception:
                    pass

    # Strategy 3: IEEE Keywords section (Stats_keywords)
    kw_section = soup.find('div', class_='Stats_keywords') or \
                 soup.find('ul', class_='doc-keywords-list')
    if kw_section:
        kw_items = kw_section.find_all('a')
        if kw_items:
            found = [a.get_text(strip=True) for a in kw_items
                     if len(a.get_text(strip=True)) > 1]
            if found:
                return ", ".join(found)

    # Strategy 3b: Springer / Nature (c-article-subject-list)
    kw_list = soup.find('ul', class_='c-article-subject-list')
    if kw_list:
        found = [li.get_text(strip=True) for li in kw_list.find_all('li')
                 if len(li.get_text(strip=True)) > 1]
        if found:
            return ", ".join(found)
    # Also: h3 'Keywords' → next sibling ul (Springer, Nature)
    for h3 in soup.find_all(['h3', 'h4'], string=re.compile(r'^Keywords?$', re.IGNORECASE)):
        sib = h3.find_next_sibling(['ul', 'div'])
        if sib:
            items = [li.get_text(strip=True) for li in sib.find_all(['li', 'a', 'span'])
                     if len(li.get_text(strip=True)) > 1
                     and li.get_text(strip=True).lower() != 'keywords']
            if items:
                return ", ".join(items)

    # Strategy 4: ScienceDirect / Elsevier keyword containers
    for kw_class in ['keyword', 'keywords-section', 'Keywords']:
        kw_div = soup.find('div', class_=re.compile(kw_class, re.IGNORECASE))
        if kw_div:
            spans = kw_div.find_all('span', class_=re.compile(r'keyword'))
            if not spans:
                spans = kw_div.find_all(['a', 'span'])
            found = [s.get_text(strip=True) for s in spans
                     if len(s.get_text(strip=True)) > 1
                     and s.get_text(strip=True).lower() != 'keywords']
            if found:
                return ", ".join(found)

    # Strategy 5: Generic kwd-group (JATS / many publishers)
    kwd_group = soup.find('div', class_='kwd-group') or \
                soup.find('ul', class_='kwd-group')
    if kwd_group:
        kws = [k.get_text(strip=True) for k in
               kwd_group.find_all('span', class_='kwd-text')]
        if not kws:
            kws = [k.get_text(strip=True) for k in
                   kwd_group.find_all(['a', 'span'])
                   if len(k.get_text(strip=True)) > 1]
        if kws:
            return ", ".join(kws)

    # Strategy 7a: Raw-text search (handles PDF-converted HTML with fragmented spans)
    # PDF→HTML sering pecah teks ke banyak <span>, sehingga find_all(string=...) gagal
    raw_text = soup.get_text(" ", strip=True)
    raw_text = re.sub(r'\s+', ' ', raw_text)
    kw_pattern = re.compile(
        r'(?:Kata\s+Kunci|Keywords?|Key\s+Words?|Index\s+Terms?)'
        r'[\s:\-\.\u2014\u2013]+(.*?)(?:\.?\s+(?:Abstract|Abstrak|Pendahuluan|Introduction|I\.?\s*[A-Z]|1\.?\s*[A-Z])|\n|\r|\.|$)',
        re.IGNORECASE
    )
    m = kw_pattern.search(raw_text)
    if m:
        kw_text = m.group(1).strip().rstrip('.')
        # Validasi ketat: harus berupa daftar keyword, bukan potongan kalimat
        # dari PDF 2-kolom yang tercampur
        if len(kw_text) > 8 and len(kw_text) < 500:
            # Split by comma atau semicolon
            parts = [p.strip() for p in re.split(r'[,;]', kw_text) if p.strip()]
            if len(parts) >= 2:
                word_counts = [len(p.split()) for p in parts]
                avg_words = sum(word_counts) / len(parts)
                max_words = max(word_counts)
                # Keyword asli: rata-rata ≤4 kata/term, tidak ada term >6 kata
                # "in this study were 15 students with high" = 8 kata → DITOLAK
                # "e-LKPD, Transformasi Geometri, Translasi" = maks 2 kata → OK
                if avg_words <= 4 and max_words <= 6:
                    return kw_text

    # Strategy 7b: Keyword sections in HTML elements (original Strategy 7)
    # TIDAK match "subjects" karena terlalu umum dalam teks akademik
    for c in soup.find_all(
        string=lambda t: t and any(
            x in t.lower() for x in ["kata kunci", "keywords", "key words", "subject terms", "index terms"]
        )
    ):
        container = c.parent
        # Look at the text within the container and its siblings/parents
        for _ in range(3):
            txt = container.get_text(" ", strip=True)
            # Look for Keywords: A, B, C
            match = re.search(r'(?:kata kunci|keywords?|key words?|subject terms?|index terms?)[:\-\s\.\u2014]+(.*?)(?:\n|\r|\.|$|Abstract|Abstrak)', txt, re.IGNORECASE)
            if match:
                kw_text = match.group(1).strip()
                if len(kw_text) > 8:
                    # Validasi: harus keyword pendek, bukan potongan kalimat
                    parts = [p.strip() for p in re.split(r'[,;]', kw_text) if p.strip()]
                    if len(parts) >= 2:
                        word_counts = [len(p.split()) for p in parts]
                        avg_words = sum(word_counts) / len(parts)
                        max_words = max(word_counts)
                        if avg_words <= 4 and max_words <= 6:
                            return kw_text
            
            if container.parent:
                container = container.parent
            else:
                break

    # Strategy 8: Schema.org / LD+JSON
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                kws = data.get('keywords', [])
                if kws:
                    if isinstance(kws, list):
                        return ", ".join(kws)
                    return str(kws)
        except Exception:
            pass

    return ""


# ================================================================
# ABSTRACT EXTRACTION
# ================================================================

def extract_abstract_from_html(html):
    """
    Extract abstract from publisher HTML page.
    Returns abstract string or empty string.
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, 'html.parser')

    # Strategy 0: EBSCO __NEXT_DATA__ (Next.js SSR embedded abstract)
    next_data = soup.find('script', id='__NEXT_DATA__')
    if next_data and next_data.string:
        try:
            nd = json.loads(next_data.string)
            ab = (nd.get('props', {})
                    .get('pageProps', {})
                    .get('data', {})
                    .get('item', {})
                    .get('itemInfo', {})
                    .get('ab', ''))
            if ab and len(ab) > 50:
                return ab.strip()
        except Exception:
            pass

    # Strategy 1: Meta tags (most publishers)
    for tag_name in ['description', 'citation_abstract', 'DC.description',
                     'dc.description', 'og:description']:
        attr = 'name' if not tag_name.startswith('og:') else 'property'
        meta = soup.find('meta', attrs={attr: tag_name})
        if meta and meta.get('content'):
            content = meta['content'].strip()
            if len(content) > 50:  # Avoid short meta descriptions
                return content

    # Strategy 2: Dedicated abstract containers
    selectors = [
        'div.abstract', 'section.abstract', 'div#abstract',
        'div[class*="abstract"]', 'p.abstract',
        'div.Abstract', 'section#abstractSection',
        'div.paper-abstract', 'div.article-abstract',
        'jats\\:p',  # JATS XML inline
        '.abstract-text', '.abstract-content',
        'div[data-auto=\"itemAbstract-value\"]', # EBSCO
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(" ", strip=True)
            if len(text) > 50:
                # Remove "Abstract" prefix
                text = re.sub(r'^(?:Abstract|ABSTRACT|Abstrak)[:\s]*',
                              '', text, count=1).strip()
                return text

    # Strategy 3: Look for "Abstract" heading then grab next paragraph
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'strong', 'b', 'p', 'span'],
                                  string=re.compile(r'^(?:Abstract|Abstrak|ABSTRACT)[:\s]*$',
                                                    re.IGNORECASE)):
        next_el = heading.find_next(['p', 'div', 'section', 'span'])
        if next_el:
            text = next_el.get_text(" ", strip=True)
            if len(text) > 50:
                return text

    # Strategy 4: Fallback find "Abstract" in full text (for flat PDF/HTML)
    full_text = soup.get_text(" ", strip=True)
    # Search for Abstrak followed by Abstract (often dual language) or alone
    match = re.search(r'(?:Abstrak|Abstract|ABSTRACT)[:\s\.\u2014]+(.*?)(?:\n\n|\r\n\r\n|Keywords?|Kata Kunci|Index Terms?|Introduction|Pendahuluan|$)', full_text, re.DOTALL | re.IGNORECASE)
    if match:
        abs_text = match.group(1).strip()
        if len(abs_text) > 80:
            # Clean up newlines/extra whitespace common in PDF conversions
            abs_text = re.sub(r'\s+', ' ', abs_text)
            return abs_text

    return ""


# ================================================================
# PDF HANDLING
# ================================================================

def pdf_to_html_memory(pdf_bytes):
    """Convert PDF bytes to HTML string using PyMuPDF (first 3 pages)."""
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = min(3, len(doc))
        return "".join([doc.load_page(i).get_text("html")
                        for i in range(pages)])
    except Exception:
        return ""


# ================================================================
# INTERSTITIAL / PDF DEEP-LINK (from notebook)
# ================================================================

def find_best_pdf_link_scored(html, base_url):
    """
    Score and find the best PDF download link on an interstitial page
    (from notebook: find_best_pdf_link_scored).
    """
    soup = BeautifulSoup(html, 'html.parser')
    candidates = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text(" ", strip=True).lower()
        score = 0
        # Optimized Scoring for ResearchGate & General
        if 'download full-text pdf' in text:
            score += 10  # RG Exact
        if 'download' in text:
            score += 3
        if 'pdf' in text:
            score += 3
        if 'pdf' in href.lower():
            score += 5
        if 'full-text' in text:
            score += 2

        if 'interactive' in href:
            score -= 10
        if 'citation' in text:
            score -= 5

        if score > 5:
            full_url = (href if href.startswith('http')
                        else urllib.parse.urljoin(base_url, href))
            candidates.append((score, full_url))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return None


# ================================================================
# RESEARCHGATE HELPER (from notebook)
# ================================================================

def convert_rg_pdf_to_abstract_url(pdf_url):
    """
    Convert RG PDF link to Abstract Page Link (from notebook).
    Ex: .../publication/123_Title/links/... -> .../publication/123_Title
    """
    try:
        if "researchgate.net" in pdf_url and "publication" in pdf_url:
            match = re.search(r'(publication/\d+_[^/]+)', pdf_url)
            if match:
                return "https://www.researchgate.net/" + match.group(1)
    except Exception:
        pass
    return None


# ================================================================
# EBSCO DETAILV2 HELPER
# ================================================================

def _try_ebsco_detailv2(openurl_url, html_text):
    """
    When we land on openurl.ebsco.com/openurl (empty pageProps),
    construct the detailv2 URL from __NEXT_DATA__ query params
    and fetch that page for subjects/keywords.

    Returns: keyword string or None
    """
    try:
        # Parse __NEXT_DATA__ from the /openurl page to get query params
        soup = BeautifulSoup(html_text, 'html.parser')
        next_data_tag = soup.find('script', id='__NEXT_DATA__')
        if not next_data_tag or not next_data_tag.string:
            return None

        nd = json.loads(next_data_tag.string)
        query = nd.get('query', {})
        ebsco_id = query.get('id', '')  # e.g. "ebsco:gcd:156824631"

        if not ebsco_id:
            return None

        # The detailv2 URL needs the article ID in the path
        # Format: /EPDB:{db}:{num}:{suffix}/detailv2?sid=...&id=...
        # We can construct a simpler detailv2 request
        params = urllib.parse.urlencode({
            'sid': query.get('sid', 'ebsco:plink:scholar'),
            'id': ebsco_id,
            'crl': query.get('crl', 'c'),
            'link_origin': 'scholar.google.com',
        })

        # Try detailv2 with the parsed article ID parts
        parts = ebsco_id.split(':')  # ['ebsco', 'gcd', '156824631']
        if len(parts) >= 3:
            db = parts[1]     # 'gcd'
            an = parts[2]     # '156824631'
            # Construct detailv2 URL
            detail_url = (
                f"https://openurl.ebsco.com/"
                f"EPDB%3A{db}%3A11%3A{an}/detailv2?{params}"
            )
            logger.info(f"     📚 Trying EBSCO detailv2: {detail_url[:80]}...")
            resp = request_hybrid_stealth(
                detail_url, use_proxy=False, timeout=30)
            if resp and resp.status_code == 200:
                detail_text = resp.content.decode('utf-8', errors='ignore')
                kws = extract_keywords_from_html(detail_text)
                if kws:
                    return kws
    except Exception as e:
        logger.error(f"     ⚠️ EBSCO detailv2 error: {e}")
    return None


# ================================================================
# KEYWORD SCRAPER (from user snippet)
# ================================================================

import xml.etree.ElementTree as ET

def get_pmc_id(url):
    match = re.search(r'(PMC\d+)', url, re.IGNORECASE)
    return match.group(1) if match else None

def fetch_pmc_api_keywords(pmc_id):
    api_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmc_id}&retmode=xml"
    try:
        headers = {"User-Agent": "ResearchScript/1.0"}
        resp = requests.get(api_url, headers=headers, timeout=30)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            keywords = [kwd.text for kwd in root.findall(".//kwd") if kwd.text]
            return keywords
    except: pass
    return None

def extract_keywords_robust(html):
    if not html: return None
    soup = BeautifulSoup(html, 'html.parser')
    # 0. EBSCO
    for h in soup.find_all(['dt', 'div', 'span'], string=re.compile(r'Subject|Keyword', re.IGNORECASE)):
        sib = h.find_next_sibling(['dd', 'div', 'span'])
        if sib:
            found = [l.get_text(strip=True) for l in sib.find_all('a') if len(l.get_text(strip=True)) > 2]
            if found: return ", ".join(found)
    # 1. IEEE
    for script in soup.find_all('script'):
        if script.string and 'xplGlobal' in script.string:
            match = re.search(r'xplGlobal.*?metadata\s*=\s*({.*?});', script.string, re.DOTALL)
            if match:
                try: 
                    data = json.loads(match.group(1))
                    kw = [k for s in data.get('keywords', []) if s.get('type') == 'Author Keywords' and 'kwd' in s for k in s['kwd']]
                    if kw: return ", ".join(kw)
                except: pass
    # 2. Meta
    for k in ['keywords', 'citation_keywords', 'dc.subject', 'prism.keyword']:
        # We also need to get abstract if called from scrape_publisher_page, but this robust function is just for keywords.
        meta = soup.find('meta', attrs={'name': k}) or soup.find('meta', attrs={'name': k.lower()})
        if meta and meta.get('content'): return f"[Meta] {meta['content']}"
    # 2.5 Raw-text search (handles PDF-converted HTML with fragmented spans)
    raw_text = soup.get_text(" ", strip=True)
    raw_text = re.sub(r'\s+', ' ', raw_text)
    kw_pattern = re.compile(
        r'(?:Kata\s+Kunci|Keywords?|Key\s+Words?|Index\s+Terms?)'
        r'[\s:\-\.\u2014\u2013]+(.*?)(?:\.?\s+(?:Abstract|Abstrak|Pendahuluan|Introduction|I\.?\s*[A-Z]|1\.?\s*[A-Z])|\n|\r|\.|$)',
        re.IGNORECASE
    )
    m = kw_pattern.search(raw_text)
    if m:
        kw_text = m.group(1).strip().rstrip('.')
        if len(kw_text) > 8 and len(kw_text) < 500:
            parts = [p.strip() for p in re.split(r'[,;]', kw_text) if p.strip()]
            if len(parts) >= 2:
                word_counts = [len(p.split()) for p in parts]
                if sum(word_counts) / len(parts) <= 4 and max(word_counts) <= 6:
                    return kw_text

    # 3. Text container search
    for c in soup.find_all(
        string=lambda t: t and any(
            x in t.lower() for x in ["kata kunci", "keywords", "key words", "subject terms", "index terms"]
        )
    ):
        container = c.parent
        for _ in range(3):
            txt = re.sub(r'\s+', ' ', container.get_text(" ", strip=True))
            # Extract only the keywords part (support em-dash \u2014, en-dash \u2013, and flexible endings like "I. PENDAHULUAN")
            match = re.search(
                r'(?:kata kunci|keywords?|key words?|subject terms?|index terms?)'
                r'[\s:\-\.\u2014\u2013]+(.*?)(?:\.?\s+(?:Abstract|Abstrak|Pendahuluan|Introduction|I\.?\s*[A-Z]|1\.?\s*[A-Z])|\n|\r|\.|$)',
                txt, re.IGNORECASE
            )
            if match:
                kw_text = match.group(1).strip()
                if len(kw_text) > 8 and "," in kw_text or len(kw_text.split()) > 1:
                    return kw_text
            
            if container.parent: container = container.parent
            else: break
    return None

def scrape_keywords_from_url(link):
    doi = extract_doi(link)
    if doi and "doi.org" not in link and "scholar.google" not in link:
        logger.info(f"     ✨ DOI detected ({doi}). Redirecting...")
        link = f"https://doi.org/{doi}"
    
    pmc_id = get_pmc_id(link)
    if pmc_id:
        kws = fetch_pmc_api_keywords(pmc_id)
        if kws: return f"🎉 KEYWORDS (PMC API): {', '.join(kws)}"

    if "ieeexplore.ieee.org" in link and ".pdf" in link:
        # Convert direct PDF links like /ielx7/.../1234567.pdf back into /document/1234567/
        match = re.search(r'([0-9]{7,8})\.pdf', link)
        if match: 
            bn = match.group(1)
            link = f"https://ieeexplore.ieee.org/document/{bn}/"
            logger.info(f"     🔄 Converted IEEE PDF link to Document HTML: {link}")

    try:
        from urllib.parse import urlparse
        domain = urlparse(link).netloc.lower()
        needs_proxy = any(d in domain for d in ["sciencedirect", "researchgate", "ieee", "springer", "wiley", "tandfonline", "sagepub", "acm", "nature"])
        
        if needs_proxy:
            logger.info(f"     🛡️ Protected domain detected ({domain}). Using Stealth Proxy.")
            resp = request_hybrid_stealth(link, use_proxy=True, stream=True)
        else:
            logger.info(f"     🌐 Local/Open domain detected ({domain}). Trying Direct Connection...")
            resp = request_hybrid_stealth(link, use_proxy=False, stream=True)
            if not resp or resp.status_code in [403, 401, 429]:
                logger.warning(f"     ⚠️ Direct connection failed/blocked. Falling back to Stealth Proxy...")
                resp = request_hybrid_stealth(link, use_proxy=True, stream=True)
                
        if resp and resp.status_code == 200:
            final_url = resp.url
            if "pdf" in resp.headers.get('Content-Type', '').lower():
                logger.info("     📄 PDF. Parsing...")
                html = pdf_to_html_memory(resp.content)
                if html:
                    kws = extract_keywords_robust(html)
                    if kws: return f"🎉 KEYWORDS (PDF): {kws}"
            else:
                logger.info(f"     🌐 HTML (Publisher/Interstitial). Parsing...")
                text = resp.content.decode('utf-8', errors='ignore')
                kws = extract_keywords_robust(text)
                if kws: return f"🎉 KEYWORDS (Web): {kws}"
                
                # FALLBACK FOR INTERSTITIALS (RG, Unesa, etc.)
                deep = find_best_pdf_link_scored(text, final_url)
                if deep:
                    logger.info(f"       🔍 Interstitial detected. Deep PDF Found: {deep[:50]}...")
                    if deep == link or deep in link: 
                        logger.warning("       ❌ Loop detected (Deep link is same as current).")
                        return None
                        
                    resp_d = request_hybrid_stealth(deep, use_proxy=True, stream=True)
                    if resp_d and "pdf" in resp_d.headers.get('Content-Type', '').lower():
                        html_d = pdf_to_html_memory(resp_d.content)
                        if html_d:
                            kws_d = extract_keywords_robust(html_d)
                            if kws_d: return f"🎉 KEYWORDS (Deep PDF): {kws_d}"
    except Exception as e:
        logger.error(f"     ❌ Error: {e}")
    return None



# ================================================================
# PUBLISHER PAGE SCRAPER (enhanced from notebook)
# ================================================================

def scrape_publisher_page(url, force_proxy=True):
    """
    Visit publisher page and extract keywords, abstract, DOI.
    Enhanced with: PMC API, IEEE PDF→stamp, OJS meta tags,
    interstitial deep-link, PDF parsing.

    Returns dict: {keywords, abstract, doi, doc_type}
    """
    result = {"abstract": "", "keywords": "", "doi": "", "doc_type": "", "raw_content": ""}

    if not url:
        return result

    # --- Pre-processing ---
    doi = extract_doi(url)
    if doi:
        result["doi"] = doi

    if doi and "doi.org" not in url and "scholar.google" not in url:
        url = f"https://doi.org/{doi}"

    # PMC API check
    pmc_id = get_pmc_id(url)
    if pmc_id:
        kws = fetch_pmc_api_keywords(pmc_id)
        if kws:
            result["keywords"] = ", ".join(kws)
            logger.info(f"      [PMC] Keywords: {result['keywords'][:60]}...")

    # IEEE PDF → stamp URL conversion
    if "ieeexplore.ieee.org" in url and url.endswith(".pdf"):
        bn = os.path.basename(url).replace(".pdf", "")
        if bn.isdigit():
            url = f"https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber={bn}"

    # OJS PDF Viewer to Direct Download conversion
    # example: https://ejournal.unesa.ac.id/index.php/jinacs/article/view/56670/44521
    # want:    https://ejournal.unesa.ac.id/index.php/jinacs/article/download/56670/44521
    if "/article/view/" in url:
        parts = url.split("/article/view/")
        if len(parts) == 2:
            base, ids = parts[0], parts[1]
            if len(ids.strip('/').split('/')) >= 2:
                url = f"{base}/article/download/{ids}"
                logger.info(f"      [Publisher] 🔄 Converted OJS Viewer link to Direct Download: {url}")

    try:
        if force_proxy:
            resp = request_hybrid_stealth(url, use_proxy=True, stream=True)
        else:
            resp = request_smart(url, stream=True)
        if not resp:
            logger.error(f"      [Publisher] ❌ Tidak bisa akses URL")
            return result

        content_type = resp.headers.get('Content-Type', '').lower()
        final_url = resp.url

        if not result["doi"]:
            result["doi"] = extract_doi(final_url)

        if "pdf" in content_type:
            # Direct PDF
            logger.info(f"      [Publisher] 📄 PDF langsung. Parsing...")
            html = pdf_to_html_memory(resp.content)
            if html:
                if not result["keywords"]:
                    # Menggunakan extract_keywords_robust karena ini bisa mencari "Kata Kunci - ..." dalam plain text PDF
                    result["keywords"] = extract_keywords_robust(html)
                if not result["abstract"]:
                    result["abstract"] = extract_abstract_from_html(html)
                if result["keywords"]:
                    logger.info(f"      [Publisher] ✅ Keywords dari PDF: {result['keywords'][:60]}...")
                else:
                    logger.warning(f"      [Publisher] ❌ Keywords tidak ditemukan di PDF")
        else:
            # HTML page
            text = resp.content.decode('utf-8', errors='ignore')
            
            # Store raw text for AI parsing fallback
            result["raw_content"] = text[:8000] # Limit to avoid bloat
            
            # Strategy A: HTML body parsing PERTAMA (extract_keywords_from_html)
            # Ini menangkap Author Keywords asli dari Springer, IEEE, Elsevier dll.
            if not result["keywords"]:
                result["keywords"] = extract_keywords_from_html(text)
                if result["keywords"]:
                    logger.info(f"      [Publisher] ✅ Keywords dari HTML: {result['keywords'][:60]}...")
                
                # Strategy B: Meta tags (citation_keywords / DC.subject)
                if not result["keywords"]:
                    is_major_publisher = any(p in final_url for p in [
                        'springer.com', 'elsevier.com', 'sciencedirect.com',
                        'wiley.com', 'ieee.org', 'nature.com', 'sagepub.com',
                        'tandfonline.com', 'mdpi.com', 'frontiersin.org'
                    ])
                    if not is_major_publisher:
                        soup_meta = BeautifulSoup(text, 'html.parser')
                        meta_kws = []
                    for meta in soup_meta.find_all('meta', attrs={'name': 'citation_keywords'}):
                        content = meta.get('content', '').strip()
                        if content:
                            meta_kws.append(content)
                    if not meta_kws:
                        for meta in soup_meta.find_all('meta', attrs={'name': re.compile(r'^DC\.subject', re.IGNORECASE)}):
                            content = meta.get('content', '').strip()
                            if content:
                                meta_kws.append(content)
                    if meta_kws:
                        result["keywords"] = _normalize_keywords(", ".join(meta_kws))
                        logger.info(f"      [Publisher] ✅ Keywords dari meta tags: {result['keywords'][:60]}...")
            
            if not result["abstract"]:
                result["abstract"] = extract_abstract_from_html(text)

            if not result["doi"]:
                result["doi"] = _extract_doi_from_meta(text)

            # --- Extract Doc Type (OJS Sections / Meta) ---
            if not result.get("doc_type"):
                soup_doc = BeautifulSoup(text, 'html.parser')
                # 1. Check meta tags
                for meta_name in ['DC.Type.articleType', 'citation_article_type', 'DC.type']:
                    meta = soup_doc.find('meta', attrs={'name': re.compile(f'^{meta_name}$', re.IGNORECASE)})
                    if meta and meta.get('content') and meta['content'].strip():
                        result["doc_type"] = meta['content'].strip()
                        logger.info(f"      [Publisher] ✅ Doc Type dari meta tags: {result['doc_type']}")
                        break
                # 2. Check OJS sub_item sections for "Section"
                if not result.get("doc_type"):
                    for section in soup_doc.find_all('section', class_='sub_item'):
                        h2 = section.find(['h2', 'span'], class_='label')
                        if h2 and "Section" in h2.get_text(strip=True):
                            val_div = section.find('div', class_='value')
                            if val_div and val_div.get_text(strip=True):
                                result["doc_type"] = val_div.get_text(strip=True).strip()
                                logger.info(f"      [Publisher] ✅ Doc Type dari HTML: {result['doc_type']}")
                                break

            # Strategy C: Deep PDF link fallback (Meta tags or Scored Links)
            if not result["keywords"]:
                deep = None
                
                # C.1 Check meta citation_pdf_url first (Standard OJS/Highwire Press)
                soup_doc = BeautifulSoup(text, 'html.parser')
                meta_pdf = soup_doc.find('meta', attrs={'name': 'citation_pdf_url'})
                if meta_pdf and meta_pdf.get('content'):
                    deep = meta_pdf['content'].strip()
                
                # C.2 Fallback to scored visible links
                if not deep:
                    deep = find_best_pdf_link_scored(text, final_url)
                    
                if deep and deep != url and deep not in url:
                    logger.info(f"      [Publisher] 🔍 Deep PDF ditemukan: "
                          f"{deep[:60]}...")
                    resp_d = request_smart(deep, stream=True)
                    if (resp_d and
                            "pdf" in resp_d.headers.get(
                                'Content-Type', '').lower()):
                        html_d = pdf_to_html_memory(resp_d.content)
                        if html_d:
                            kws = extract_keywords_from_html(html_d)
                            if kws:
                                result["keywords"] = kws
                                logger.info(f"      [Publisher] ✅ Keywords "
                                      f"(Deep PDF): {kws[:60]}...")
                            if not result["abstract"]:
                                abs_d = extract_abstract_from_html(html_d)
                                if abs_d:
                                    result["abstract"] = abs_d
                    else:
                        logger.warning(f"      [Publisher] ❌ Deep PDF gagal diakses")
                else:
                    logger.warning(f"      [Publisher] ❌ Keywords tidak ditemukan di HTML, tidak ada PDF link")

    except Exception as e:
        logger.error(f"      [Publisher] Error: {e}")

    # --- APPLY DEEP CLEANING ---
    if result.get("abstract"):
        result["abstract"] = _deep_clean_abstract(result["abstract"])
    if result.get("keywords"):
        result["keywords"] = _clean_keywords(result["keywords"])

    return result


def _extract_doi_from_meta(html):
    """Extract DOI from HTML meta tags."""
    soup = BeautifulSoup(html, 'html.parser')
    for tag_name in ['citation_doi', 'DC.identifier', 'dc.identifier',
                     'prism.doi', 'DOI', 'doi']:
        meta = soup.find('meta', attrs={'name': tag_name})
        if meta and meta.get('content'):
            content = meta['content'].strip()
            if content.startswith('10.'):
                return content
            doi = extract_doi(content)
            if doi:
                return doi
    # Also check property attribute (some use property instead of name)
    for tag_name in ['citation_doi']:
        meta = soup.find('meta', attrs={'property': tag_name})
        if meta and meta.get('content'):
            content = meta['content'].strip()
            if content.startswith('10.'):
                return content
    return ""


# ================================================================
# CROSSREF API (Free - DOI + Keywords)
# ================================================================

def _crossref_lookup(title):
    """
    Look up a paper by title in CrossRef API.
    Returns dict: {doi, keywords, matched_title} or empty dict.
    Free API, no key needed. Rate-limited to polite usage.
    """
    if not title:
        return {}

    try:
        resp = requests.get(
            "https://api.crossref.org/works",
            params={"query.title": title[:200], "rows": 1,
                    "select": "DOI,title,subject,container-title"},
            headers={"User-Agent":
                     "TugasAkhir/1.0 (mailto:research@unesa.ac.id)"},
            timeout=15,
        )
        if resp.status_code != 200:
            return {}

        items = resp.json().get("message", {}).get("items", [])
        if not items:
            return {}

        item = items[0]
        result = {}

        doi = item.get("DOI", "")
        if doi:
            result["doi"] = doi

        # Return the matched title for validation
        cr_titles = item.get("title", [])
        if cr_titles:
            result["matched_title"] = cr_titles[0]

        subjects = item.get("subject", [])
        if subjects:
            result["keywords"] = ", ".join(subjects)

        return result

    except Exception:
        return {}



# ================================================================
# OPENALEX API (Free - Keywords/Concepts)
# ================================================================

def _openalex_lookup(doi="", title=""):
    """
    Look up a paper in OpenAlex API for keywords/concepts.
    Returns dict: {keywords} or empty dict.
    """
    try:
        if doi:
            url = f"https://api.openalex.org/works/doi:{doi}"
        elif title:
            url = (f"https://api.openalex.org/works?"
                   f"search={requests.utils.quote(title[:150])}&per-page=3")
        else:
            return {}

        resp = requests.get(url, headers={
            "User-Agent": "TugasAkhir/1.0 (mailto:research@unesa.ac.id)"
        }, timeout=15)

        if resp.status_code != 200:
            return {}

        data = resp.json()

        # Handle search results vs direct lookup
        if "results" in data:
            items = data.get("results", [])
            if not items:
                return {}
            
            # VALIDATE: cek kemiripan judul untuk mencegah salah paper
            if title:
                import re
                from difflib import SequenceMatcher
                def _norm(t):
                    if not t: return ""
                    return re.sub(r'[^a-z0-9]', '', t.lower())
                
                best_match = None
                best_score = 0
                for item in items[:3]:  # Cek top-3 hasil
                    returned_title = item.get("title", "")
                    score = SequenceMatcher(None, _norm(title), _norm(returned_title)).ratio()
                    if score > best_score:
                        best_score = score
                        best_match = item
                
                if best_score < 0.75:
                    logger.warning(f"      ⚠️ [OpenAlex] Hasil tidak cocok (similarity={best_score:.2f}). Skip.")
                    return {}
                data = best_match
            else:
                data = items[0]

        result = {}

        # Get keywords from multiple sources
        keywords = []

        # Primary: paper keywords
        kw_list = data.get("keywords", [])
        for kw in kw_list:
            if isinstance(kw, dict):
                keywords.append(kw.get("display_name", ""))
            else:
                keywords.append(str(kw))

        # Secondary: concepts/topics
        if not keywords:
            for concept in data.get("concepts", [])[:8]:
                score = concept.get("score", 0)
                if score and score > 0.3:
                    keywords.append(concept.get("display_name", ""))

        if not keywords:
            for topic in data.get("topics", [])[:5]:
                keywords.append(topic.get("display_name", ""))

        if keywords:
            result["keywords"] = ", ".join([k for k in keywords if k])

        # Extract authors
        author_names = []
        for authorship in data.get("authorships", []):
            author = authorship.get("author", {})
            auth_name = author.get("display_name", "")
            if auth_name:
                author_names.append(auth_name)
        
        if author_names:
            result["author_names"] = author_names

        # Extract document type
        raw_type = data.get("type", "")
        if raw_type:
            # Map OpenAlex type to Title Case (e.g., 'article' -> 'Article')
            result["doc_type"] = raw_type.replace("-", " ").title()

        # Extract DOI
        extracted_doi = data.get("doi", "")
        if extracted_doi:
            result["doi"] = extracted_doi.replace("https://doi.org/", "")
            
        # Reconstruct Abstract if provided as inverted index
        inverted_index = data.get("abstract_inverted_index", {})
        if inverted_index:
            try:
                max_idx = max([max(positions) for positions in inverted_index.values()])
                words = [""] * (max_idx + 1)
                for word, positions in inverted_index.items():
                    for pos in positions:
                        words[pos] = word
                result["abstract"] = " ".join(words)
            except Exception:
                pass

        # Extract Open Access PDF link
        best_oa = data.get("best_oa_location", {})
        if best_oa:
            pdf_url = best_oa.get("pdf_url", "")
            if pdf_url:
                result["oa_pdf_url"] = pdf_url
            # Also get landing page URL from best OA location
            landing = best_oa.get("landing_page_url", "")
            if landing:
                result["oa_landing_url"] = landing
        
        # Fallback: open_access.oa_url
        oa_obj = data.get("open_access", {})
        if oa_obj:
            oa_url = oa_obj.get("oa_url", "")
            if oa_url and "oa_pdf_url" not in result and "oa_landing_url" not in result:
                result["oa_landing_url"] = oa_url

        # --- APPLY DEEP CLEANING ---
        if result.get("abstract"):
            result["abstract"] = _deep_clean_abstract(result["abstract"])
        if result.get("keywords"):
            result["keywords"] = _clean_keywords(result["keywords"])

        return result

    except Exception:
        return {}


# ================================================================
# SEMANTIC SCHOLAR TLDR
# ================================================================

def fetch_tldr(doi="", title=""):
    """
    Fetch TLDR from Semantic Scholar API by DOI or title.
    Returns TLDR string or empty string.
    """
    if not doi and not title:
        return ""

    try:
        if doi:
            url = (f"https://api.semanticscholar.org/graph/v1/paper/"
                   f"DOI:{doi}?fields=tldr")
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                tldr = data.get("tldr", {})
                if tldr and tldr.get("text"):
                    return tldr["text"]

        if title:
            # Search by title
            url = ("https://api.semanticscholar.org/graph/v1/"
                   "paper/search")
            resp = requests.get(url, params={
                "query": title[:200], "limit": 1, "fields": "tldr"
            }, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                papers = data.get("data", [])
                if papers:
                    tldr = papers[0].get("tldr", {})
                    if tldr and tldr.get("text"):
                        return tldr["text"]
    except Exception:
        pass

    return ""


# ================================================================
# MAIN ENRICHMENT FUNCTION
# ================================================================

def enrich_single_paper(scholar_citation_url, api_key=None):
    """
    Enrich a single paper from its Scholar citation URL.

    Integrated flow (notebook + API):
    1.  SerpAPI Citation → abstract, title, publisher link
    1b. BrightData Scholar Page → publisher/PDF link (fallback)
    2a. Publisher Page (proxy) → keywords, abstract, DOI
    2b. CrossRef → DOI fallback
    2c. OpenAlex → keyword fallback
    3.  Semantic Scholar → TLDR

    Returns dict: {abstract, keywords, doi, tldr}
    """
    result = {"abstract": "", "keywords": "", "doi": "", "tldr": ""}

    publisher_url = ""
    pdf_url = ""
    title = ""

    # --- Phase 1: SerpAPI Citation (structured data) ---
    logger.info(f"   [SerpAPI] Resolving citation...")
    citation = resolve_citation_serpapi(scholar_citation_url, api_key)

    if citation:
        result["abstract"] = citation.get("abstract", "")
        result["doi"] = citation.get("doi", "")
        publisher_url = citation.get("link", "")
        title = citation.get("title", "")

        if publisher_url:
            logger.info(f"   [SerpAPI] Publisher: {publisher_url[:60]}...")
        if result["abstract"]:
            logger.info(f"   [SerpAPI] Abstract: {result['abstract'][:60]}...")
        if result["doi"]:
            logger.info(f"   [SerpAPI] DOI: {result['doi']}")

    # --- Phase 1b: BrightData Scholar Page (proxy, from notebook) ---
    # If SerpAPI didn't give publisher link, resolve via proxy
    if not publisher_url and scholar_citation_url:
        resolved = resolve_scholar_citation_proxy(scholar_citation_url)
        if resolved:
            publisher_url = resolved.get("title_link") or ""
            pdf_url = resolved.get("pdf_link") or ""
            if not title and resolved.get("title_text"):
                title = resolved["title_text"]
            if publisher_url:
                logger.info(f"   [BrightData] Publisher: {publisher_url[:60]}...")
            if pdf_url:
                logger.info(f"   [BrightData] PDF: {pdf_url[:60]}...")

    # --- Phase 2a: Publisher/PDF Page Scraping (proxy) ---
    # Prefer PDF link (keywords from text), then publisher link
    target_url = pdf_url or publisher_url
    if target_url:
        logger.info(f"   [Publisher] Scraping for keywords/DOI...")
        pub_data = scrape_publisher_page(target_url, force_proxy=True)

        # Keywords from publisher
        if pub_data["keywords"]:
            result["keywords"] = pub_data["keywords"]
            logger.info(f"   [Publisher] Keywords: "
                  f"{result['keywords'][:60]}...")

        # Fallback abstract from publisher if SerpAPI didn't have it
        if not result["abstract"] and pub_data["abstract"]:
            result["abstract"] = pub_data["abstract"]
            logger.info(f"   [Publisher] Abstract (fallback): "
                  f"{result['abstract'][:60]}...")

        # Fallback DOI
        if not result["doi"] and pub_data["doi"]:
            result["doi"] = pub_data["doi"]
            logger.info(f"   [Publisher] DOI: {result['doi']}")

    # If we only have PDF link, also scrape publisher for more data
    if pdf_url and publisher_url and publisher_url != pdf_url:
        if not result["keywords"] or not result["doi"]:
            logger.info(f"   [Publisher] Also trying publisher page...")
            pub2 = scrape_publisher_page(publisher_url, force_proxy=True)
            if not result["keywords"] and pub2["keywords"]:
                result["keywords"] = pub2["keywords"]
                logger.info(f"   [Publisher] Keywords (pub): "
                      f"{result['keywords'][:60]}...")
            if not result["doi"] and pub2["doi"]:
                result["doi"] = pub2["doi"]

    # --- Phase 2b: CrossRef API (DOI + keyword fallback) ---
    if not result["doi"] or not result["keywords"]:
        if title:
            logger.info(f"   [CrossRef] Looking up by title...")
            cr = _crossref_lookup(title)
            if cr.get("doi") and not result["doi"]:
                result["doi"] = cr["doi"]
                logger.info(f"   [CrossRef] DOI: {result['doi']}")
            if cr.get("keywords") and not result["keywords"]:
                result["keywords"] = cr["keywords"]
                logger.info(f"   [CrossRef] Keywords: "
                      f"{result['keywords'][:60]}...")

    # --- Phase 2c: OpenAlex API (keyword fallback) ---
    if not result["keywords"]:
        logger.info(f"   [OpenAlex] Looking up keywords...")
        oa = _openalex_lookup(doi=result["doi"], title=title)
        if oa.get("keywords"):
            result["keywords"] = oa["keywords"]
            logger.info(f"   [OpenAlex] Keywords: "
                  f"{result['keywords'][:60]}...")

    # --- Phase 3: TLDR ---
    if result["doi"] or title:
        tldr = fetch_tldr(doi=result["doi"], title=title)
        if tldr:
            result["tldr"] = tldr
            logger.info(f"   [S2] TLDR: {result['tldr'][:60]}...")

    return result
