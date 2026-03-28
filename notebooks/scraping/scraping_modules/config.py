# scraping_modules/config.py
import os
import sys
import json
from pathlib import Path

# --- GLOBAL PATHS ---
# Base dir is scraping/, calculated relative to this file
BASE_DIR = Path(__file__).resolve().parent.parent
SAVE_DIR = BASE_DIR / "file_tabulars"
SAVE_DIR.mkdir(parents=True, exist_ok=True)
CREDENTIALS_FILE = BASE_DIR / "credentials_new.json"

# --- DEFAULT HEADERS ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# --- FEATURE FLAGS ---
ENABLE_SCIVAL = True

# --- CREDENTIALS LOADING ---
# Load from OS Env first, then JSON, then OVERRIDE with Airflow Variables
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SCIVAL_EMAIL = os.environ.get("SCIVAL_EMAIL", "")
SCIVAL_PASS = os.environ.get("SCIVAL_PASS", "")
PROXY_URL = None
BRIGHT_DATA_HOST = ""
BD_USER_UNLOCKER = os.environ.get("BD_USER_UNLOCKER", "")
BD_PASS_UNLOCKER = os.environ.get("BD_PASS_UNLOCKER", "")
BD_USER_SERP = os.environ.get("BD_USER_SERP", "")
BD_PASS_SERP = os.environ.get("BD_PASS_SERP", "")
DECODO_AUTH = ""
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

try:
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE, 'r') as f:
            config = json.load(f)
            
            # SciVal
            unesa = config.get('unesa', {})
            if not SCIVAL_EMAIL: SCIVAL_EMAIL = unesa.get('email', '')
            if not SCIVAL_PASS: SCIVAL_PASS = unesa.get('password', '')
            
            # Decodo
            decodo = config.get('decodo', {})
            if not DECODO_AUTH: DECODO_AUTH = decodo.get('auth', '')

            # SerpAPI
            serpapi = config.get('serpapi', {})
            if not SERPAPI_KEY: SERPAPI_KEY = serpapi.get('api_key', '')

            # Bright Data (Assume Proxy Unlocker + SERP are often similar)
            bd_unlocker = config.get('bright_data', {}).get('proxy_unlocker', {})
            bd_serp = config.get('bright_data', {}).get('proxy_serp', {})
            
            BRIGHT_DATA_HOST = bd_unlocker.get('host', 'brd.superproxy.io:33335')
            if not BD_USER_UNLOCKER: BD_USER_UNLOCKER = bd_unlocker.get('user', '')
            if not BD_PASS_UNLOCKER: BD_PASS_UNLOCKER = bd_unlocker.get('password', '')
            if not BD_USER_SERP: BD_USER_SERP = bd_serp.get('user', '')
            if not BD_PASS_SERP: BD_PASS_SERP = bd_serp.get('password', '')

            # Also ensure Unlocker credentials flow securely
            if not BD_USER_UNLOCKER: BD_USER_UNLOCKER = bd_unlocker.get('user', '')
            if not BD_PASS_UNLOCKER: BD_PASS_UNLOCKER = bd_unlocker.get('password', '')
            
            # Supabase
            sb = config.get('supabase', {})
            if not SUPABASE_URL: SUPABASE_URL = sb.get('url', '').strip()
            if not SUPABASE_KEY: SUPABASE_KEY = sb.get('key', '').strip()
except Exception as e:
    pass

# --- Airflow Variables Override (Highest Priority) ---
try:
    from airflow.models import Variable
    def _av(name, fallback):
        v = Variable.get(name, default_var=None)
        return v if v is not None else fallback

    SUPABASE_URL = _av('SUPABASE_URL', SUPABASE_URL).strip() if _av('SUPABASE_URL', SUPABASE_URL) else ""
    SUPABASE_KEY = _av('SUPABASE_KEY', SUPABASE_KEY).strip() if _av('SUPABASE_KEY', SUPABASE_KEY) else ""
    SERPAPI_KEY = _av('SERPAPI_KEY', SERPAPI_KEY)
    BD_PASS_SERP = _av('BD_PASS_SERP', BD_PASS_SERP)
    SCIVAL_EMAIL = _av('SCIVAL_EMAIL', SCIVAL_EMAIL)
    SCIVAL_PASS = _av('SCIVAL_PASS', SCIVAL_PASS)
except ImportError:
    pass

# Diagnostics
if BD_USER_UNLOCKER and BD_USER_SERP:
    print(f"✅ Config: Loaded Dual-Proxy Credentials (Unlocker + SERP)")
else:
    print("ℹ️ Config: Dual-Proxy credentials missing or incomplete.")

if SUPABASE_URL and SUPABASE_KEY:
    print(f"✅ Config: Loaded Credentials (Supabase: {SUPABASE_URL})")
else:
    print("ℹ️ Config: Supabase credentials missing/incomplete.")

# --- PRODI CONFIGURATION ---
# Schema: (kode, display_name, url, pddikti_keyword, parser_type)
PRODI_WEB_CONFIG = [
    # FAKULTAS TEKNIK / INFOKOM RELEVANT
    ("55202", "S1 Teknik Informatika", "https://ti.ft.unesa.ac.id/page/dosen", "Teknik Informatika", "table"),
    ("57201", "S1 Sistem Informasi", "https://si.ft.unesa.ac.id/page/dosen", "Sistem Informasi", "table"),
    ("83207", "S1 Pendidikan Teknologi Informasi", "https://pendidikan-ti.ft.unesa.ac.id/page/dosen", "Pendidikan Teknologi Informasi", "pendti"),
    ("20201", "S1 Teknik Elektro", "https://teknikelektro.ft.unesa.ac.id/page/dosen", "Teknik Elektro", "te"),
    ("55283", "S1 Kecerdasan Artifisial", "https://ai.fmipa.unesa.ac.id/page/dosen-s1-kecerdasan-artifisial", "Kecerdasan Artifisial", "simcv"),
    ("49202", "S1 Sains Data", "https://datascience.fmipa.unesa.ac.id//page/dosen", "Sains Data", "sains"),
    ("61209", "S1 Bisnis Digital", "https://bisnisdigital.feb.unesa.ac.id/page/dosen", "Bisnis Digital", "bisdig"),
    ("57301", "D4 Manajemen Informatika", "https://terapan-ti.vokasi.unesa.ac.id/page/dosen", "Manajemen Informatika", "simcv"),
    # JENJANG S2
    ("55100", "S2 Informatika", "https://s2if.ft.unesa.ac.id/page/dosen", "Informatika", "s2if"),
    ("83215", "S2 Pendidikan Teknologi Informasi", "https://s2tp.pasca.unesa.ac.id/page/dosen", "Pendidikan Teknologi Informasi", "s2pti"),
]

# TARGET PRODI NAMES (Scope Control)
TARGET_PRODI_NAMES = {
    cfg[1] for cfg in PRODI_WEB_CONFIG # Default: Target ALL in config
}

# --- SECTION: SINTA CONFIG ---
SINTA_DEPTS = {
    "S1 Teknik Informatika": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/EEE0451E-BD6B-4742-9DDC-37443E9727D8",
    "S1 Sistem Informasi": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/F4017FD4-886E-439F-99D5-058257BCD267",
    "S1 Pendidikan Teknologi Informasi": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/3D55C562-55DC-4630-9E8A-B85ADDBD8095",
    "S1 Teknik Elektro": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/D07FD88A-19E6-4E4D-9068-950E10F52E7D",
    "S1 Kecerdasan Artifisial": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/C4A6FE46-5A60-487F-BBEF-7532B2CD4AB3",
    "S1 Sains Data": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/B56D9BB7-704D-45F0-A2A7-58F53B8AE40B",
    "S1 Bisnis Digital": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/75C862EC-7303-4397-A9A4-297036464C36",
    "D4 Manajemen Informatika": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/A5BFB6F6-E36A-429A-A7CC-6E7E85A590ED",
    "S2 Informatika": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/9710C241-0910-44C9-A7DD-22C249778B97",
    "S2 Pendidikan Teknologi Informasi": "https://sinta.kemdiktisaintek.go.id/departments/authors/499/CB1154B4-10BA-4712-B916-36051BA7C32F/E1D6EE47-FA34-4CAA-AFD6-80ED1B9C03FF",
}

STRICT_AFFILIATION = "UNIVERSITAS NEGERI SURABAYA"
PREFIX_TITLES = {
    'prof', 'dr', 'drs', 'dra', 'ir', 'h', 'hj', 
    'apt', 'ns', 'bd', 'kh', 'r', 'ra', 'tb', 'en',
    'rr', 'rm', 'andes'
}

# --- COLUMN TYPES ENFORCEMENT ---
# Use this in pd.read_csv(..., dtype=ID_COLUMN_TYPES)
ID_COLUMN_TYPES = {
    'nip': str,
    'nidn': str,
    'scholar_id': str,
    'scopus_id': str,
    'sinta_id': str
}
