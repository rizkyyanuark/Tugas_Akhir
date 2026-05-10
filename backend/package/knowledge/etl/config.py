"""
ETL Configuration Module - Single Source of Truth
===================================================
All runtime configuration is resolved from ENVIRONMENT VARIABLES.
No YAML files, no config_manager, no Airflow Variables inside here.

Level 3 Architecture:
  Airflow DAG injects all secrets/settings as env vars via DockerOperator.
  The worker container reads them here via os.environ.get().

Maintenance Guide:
  ┌──────────────────────────────────────────────────────────────────────┐
  │  To add a new setting:                                               │
  │  1. Add os.environ.get("MY_KEY", "default") here                     │
  │  2. Map it in _worker_env() in the DAG file                          │
  │  3. Create the Airflow Variable in Admin → Variables                  │
  └──────────────────────────────────────────────────────────────────────┘
"""
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── Base Directories ──────────────────────────────────────────────────
# In Docker: /app/data (persistent volume mounted by Airflow)
# Locally:   <project_root>/data (auto-created)

_is_docker = (
    os.environ.get("DOCKER_ENVIRONMENT") == "true"
    or os.environ.get("RUNNING_IN_DOCKER") == "true"
    or Path("/app/data").exists()
)

if _is_docker:
    DATA_DIR = Path(os.environ.get("ETL_DATA_DIR", "/app/data"))
else:
    # Walk up from this file to find the project root (contains 'backend/')
    _current = Path(__file__).resolve().parent
    _project_root = _current
    while _current != _current.parent:
        if (_current / "backend").is_dir():
            _project_root = _current
            break
        _current = _current.parent
    DATA_DIR = Path(os.environ.get("ETL_DATA_DIR", str(_project_root / "data")))

RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# Legacy alias — services/unesa_lecturers.py and services/unesa_papers.py
# use SAVE_DIR as the base directory for pipeline CSV outputs.
# Points to DATA_DIR so all outputs land in the persistent volume.
SAVE_DIR = DATA_DIR

RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ─── Core Infrastructure ──────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ─── Scraping Credentials ─────────────────────────────────────────────
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
SCIVAL_EMAIL = os.environ.get("SCIVAL_EMAIL", "")
SCIVAL_PASS = os.environ.get("SCIVAL_PASS", "")

# ─── BrightData Proxy ─────────────────────────────────────────────────
BD_USER_SERP = os.environ.get("BD_USER_SERP", "")
BD_PASS_SERP = os.environ.get("BD_PASS_SERP", "")

# Web Unlocker Zone
BD_USER_UNLOCKER = os.environ.get("BD_USER_UNLOCKER", "")
BD_PASS_UNLOCKER = os.environ.get("BD_PASS_UNLOCKER", "")

# SERP API Token (used by Scholar scraping pipeline)
BRIGHTDATA_SERP_TOKEN = os.environ.get("BRIGHTDATA_SERP_TOKEN", "")

# Host
BRIGHT_DATA_HOST = os.environ.get("BRIGHT_DATA_HOST", "brd.superproxy.io:33335")

# ─── AI / LLM ─────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# ─── Notification ─────────────────────────────────────────────────────
NOTIFICATION_EMAIL = os.environ.get("NOTIFICATION_EMAIL", "")

# ─── Diagnostics ──────────────────────────────────────────────────────
if not SUPABASE_URL:
    logger.warning("⚠️ ETL Config: SUPABASE_URL is missing.")
else:
    logger.info(f"✅ ETL Config: Loaded (Supabase: {SUPABASE_URL[:30]}...)")
#                                                                       
#  CRAWLER SETTINGS
#                                                                       
# Tunable via environment for production overrides without code changes.

CRAWLER_MAX_RETRIES: int = int(os.environ.get("ETL_CRAWLER_MAX_RETRIES", "3"))
CRAWLER_TIMEOUT: int = int(os.environ.get("ETL_CRAWLER_TIMEOUT", "60"))
CRAWLER_HEADLESS: bool = os.environ.get("ETL_CRAWLER_HEADLESS", "true").lower() in ("true", "1", "yes")


#                                                                       
#  HTTP HEADERS
#                                                                       
# Shared across all HTTP-based scrapers (web_scraper, sinta, simcv, etc.)
# Override User-Agent via environment if sites start blocking the default.

HEADERS: dict = {
    "User-Agent": os.environ.get(
        "ETL_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
}


#                                                                       
#  PROXY URL (computed)
#                                                                       
# Constructed from BrightData credentials. Evaluates to empty string
# if credentials are not set, which disables proxy usage gracefully.

def _build_proxy_url() -> str:
    """Build BrightData proxy URL from credentials, or return empty string."""
    if BD_USER_SERP and BD_PASS_SERP and BRIGHT_DATA_HOST:
        return f"http://{BD_USER_SERP}:{BD_PASS_SERP}@{BRIGHT_DATA_HOST}"
    return ""

PROXY_URL: str = _build_proxy_url()


#                                                                       
#  FEATURE FLAGS
#                                                                       

ENABLE_SCIVAL: bool = os.environ.get("ETL_ENABLE_SCIVAL", "true").lower() in ("true", "1", "yes")


#                                                                       
#  PRODI WEB CONFIG
#                                                                       
# Each tuple: (kode_prodi, nama_prodi, url, keyword, parser_key)
#
# To add a new study program:
#   1. Append a new tuple here.
#   2. Register the parser_key in parsers.py   PARSER_MAP.
#   3. Add the SINTA department URL to SINTA_DEPTS below.

PRODI_WEB_CONFIG: list[tuple] = [
    ("55202", "S1 Teknik Informatika",            "https://ti.ft.unesa.ac.id/page/dosen",                              "Teknik Informatika",            "table"),
    ("57201", "S1 Sistem Informasi",              "https://si.ft.unesa.ac.id/page/dosen",                              "Sistem Informasi",              "table"),
    ("83207", "S1 Pendidikan Teknologi Informasi", "https://pendidikan-ti.ft.unesa.ac.id/page/dosen",                   "Pendidikan Teknologi Informasi", "pendti"),
    ("20201", "S1 Teknik Elektro",                "https://teknikelektro.ft.unesa.ac.id/page/dosen",                    "Teknik Elektro",                "te"),
    ("55283", "S1 Kecerdasan Artifisial",         "https://ai.fmipa.unesa.ac.id/page/dosen-s1-kecerdasan-artifisial",   "Kecerdasan Artifisial",         "simcv"),
    ("49202", "S1 Sains Data",                    "https://datascience.fmipa.unesa.ac.id//page/dosen",                  "Sains Data",                    "sains"),
    ("61209", "S1 Bisnis Digital",                "https://bisnisdigital.feb.unesa.ac.id/page/dosen",                   "Bisnis Digital",                "bisdig"),
    ("57301", "D4 Manajemen Informatika",         "https://terapan-ti.vokasi.unesa.ac.id/page/dosen",                   "Manajemen Informatika",         "simcv"),
    ("55100", "S2 Informatika",                   "https://s2if.ft.unesa.ac.id/page/dosen",                             "Informatika",                   "s2if"),
    ("83215", "S2 Pendidikan Teknologi Informasi", "https://s2tp.pasca.unesa.ac.id/page/dosen",                          "Pendidikan Teknologi Informasi", "s2pti"),
]

TARGET_PRODI_NAMES: set[str] = {cfg[1] for cfg in PRODI_WEB_CONFIG}


#                                                                       
#  SINTA DEPARTMENT CONFIG
#                                                                       
# SINTA department author listing URLs.
# To add: copy the URL from sinta.kemdiktisaintek.go.id   Departments   Authors.

SINTA_DEPTS: dict[str, str] = {
    "S1 Teknik Informatika":            "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/EEE0451E-BD6B-4742-9DDC-37443E9727D8",
    "S1 Sistem Informasi":              "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/F4017FD4-886E-439F-99D5-058257BCD267",
    "S1 Pendidikan Teknologi Informasi": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/3D55C562-55DC-4630-9E8A-B85ADDBD8095",
    "S1 Teknik Elektro":                "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/D07FD88A-19E6-4E4D-9068-950E10F52E7D",
    "S1 Kecerdasan Artifisial":         "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/C4A6FE46-5A60-487F-BBEF-7532B2CD4AB3",
    "S1 Sains Data":                    "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/B56D9BB7-704D-45F0-A2A7-58F53B8AE40B",
    "S1 Bisnis Digital":                "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/75C862EC-7303-4397-A9A4-297036464C36",
    "D4 Manajemen Informatika":         "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/A5BFB6F6-E36A-429A-A7CC-6E7E85A590ED",
    "S2 Informatika":                   "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/9710C241-0910-44C9-A7DD-22C249778B97",
    "S2 Pendidikan Teknologi Informasi": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/E1D6EE47-FA34-4CAA-AFD6-80ED1B9C03FF",
}


#                                                                       
#  DATA CLEANING CONSTANTS
#                                                                       

STRICT_AFFILIATION: str = "UNIVERSITAS NEGERI SURABAYA"

# Academic title prefixes to strip during name normalization.
PREFIX_TITLES: frozenset[str] = frozenset({
    "prof", "dr", "drs", "dra", "ir", "h", "hj",
    "apt", "ns", "bd", "kh", "r", "ra", "tb",
    "en", "rr", "rm", "andes",
})

# Column type enforcement for ID columns   ensures clean text, never float.
ID_COLUMN_TYPES: dict[str, type] = {
    "nip": str,
    "nidn": str,
    "scholar_id": str,
    "scopus_id": str,
    "sinta_id": str,
}
