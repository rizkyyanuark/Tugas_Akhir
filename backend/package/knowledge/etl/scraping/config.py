# knowledge/etl/scraping/config.py
import os
import json
from pathlib import Path

# --- GLOBAL PATHS ---
# Base dir for scraping-related data
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent.parent # Points to root/
_docker_data = Path("/app/data")
if _docker_data.exists():
    SAVE_DIR = _docker_data
else:
    SAVE_DIR = BASE_DIR / "data" / "file_tabulars"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# Path to legacy credentials file for backward compatibility
CREDENTIALS_FILE = BASE_DIR / "notebooks" / "scraping" / "credentials_new.json"

# --- DEFAULT HEADERS ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# --- FEATURE FLAGS ---
ENABLE_SCIVAL = True

# --- CREDENTIALS LOADING ---
# Priority: OS Env (.env) -> JSON File -> Airflow Variables (if available)

def _get_env_or_json(key, json_path=None, json_key=None, default=""):
    """Helper to get config value from Env or fallback to JSON."""
    val = os.environ.get(key, "").strip()
    if val:
        return val
    
    if json_path and json_path.exists():
        try:
            with open(json_path, 'r') as f:
                config_data = json.load(f)
                if json_key:
                    # Handle nested keys like 'bright_data.proxy_unlocker.user'
                    keys = json_key.split('.')
                    temp = config_data
                    for k in keys:
                        temp = temp.get(k, {})
                    if isinstance(temp, str):
                        return temp.strip()
        except Exception:
            pass
    return default

# SciVal
SCIVAL_EMAIL = _get_env_or_json("SCIVAL_EMAIL", CREDENTIALS_FILE, "unesa.email")
SCIVAL_PASS = _get_env_or_json("SCIVAL_PASS", CREDENTIALS_FILE, "unesa.password")

# Supabase
SUPABASE_URL = _get_env_or_json("SUPABASE_URL", CREDENTIALS_FILE, "supabase.url")
SUPABASE_KEY = _get_env_or_json("SUPABASE_KEY", CREDENTIALS_FILE, "supabase.key")

# SerpAPI
SERPAPI_KEY = _get_env_or_json("SERPAPI_KEY", CREDENTIALS_FILE, "serpapi.api_key")

# Bright Data / Proxies
BRIGHT_DATA_HOST = os.environ.get("BRIGHT_DATA_HOST", "brd.superproxy.io:33335")
BD_USER_UNLOCKER = _get_env_or_json("BD_USER_UNLOCKER", CREDENTIALS_FILE, "bright_data.proxy_unlocker.user")
BD_PASS_UNLOCKER = _get_env_or_json("BD_PASS_UNLOCKER", CREDENTIALS_FILE, "bright_data.proxy_unlocker.password")
BD_USER_SERP = _get_env_or_json("BD_USER_SERP", CREDENTIALS_FILE, "bright_data.proxy_serp.user")
BD_PASS_SERP = _get_env_or_json("BD_PASS_SERP", CREDENTIALS_FILE, "bright_data.proxy_serp.password")

# --- Airflow Variables Override (Highest Priority) ---
try:
    from airflow.models import Variable
    def _av(name, current_val):
        v = Variable.get(name, default_var=None)
        return v.strip() if v is not None else current_val

    SUPABASE_URL = _av('SUPABASE_URL', SUPABASE_URL)
    SUPABASE_KEY = _av('SUPABASE_KEY', SUPABASE_KEY)
    SERPAPI_KEY = _av('SERPAPI_KEY', SERPAPI_KEY)
    BD_PASS_SERP = _av('BD_PASS_SERP', BD_PASS_SERP)
    BD_USER_UNLOCKER = _av('BD_USER_UNLOCKER', BD_USER_UNLOCKER)
    BD_PASS_UNLOCKER = _av('BD_PASS_UNLOCKER', BD_PASS_UNLOCKER)
    SCIVAL_EMAIL = _av('SCIVAL_EMAIL', SCIVAL_EMAIL)
    SCIVAL_PASS = _av('SCIVAL_PASS', SCIVAL_PASS)
except ImportError:
    pass

# --- PRODI CONFIGURATION ---
PRODI_WEB_CONFIG = [
    ("55202", "S1 Teknik Informatika", "https://ti.ft.unesa.ac.id/page/dosen", "Teknik Informatika", "table"),
    ("57201", "S1 Sistem Informasi", "https://si.ft.unesa.ac.id/page/dosen", "Sistem Informasi", "table"),
    ("83207", "S1 Pendidikan Teknologi Informasi", "https://pendidikan-ti.ft.unesa.ac.id/page/dosen", "Pendidikan Teknologi Informasi", "pendti"),
    ("20201", "S1 Teknik Elektro", "https://teknikelektro.ft.unesa.ac.id/page/dosen", "Teknik Elektro", "te"),
    ("55283", "S1 Kecerdasan Artifisial", "https://ai.fmipa.unesa.ac.id/page/dosen-s1-kecerdasan-artifisial", "Kecerdasan Artifisial", "simcv"),
    ("49202", "S1 Sains Data", "https://datascience.fmipa.unesa.ac.id//page/dosen", "Sains Data", "sains"),
    ("61209", "S1 Bisnis Digital", "https://bisnisdigital.feb.unesa.ac.id/page/dosen", "Bisnis Digital", "bisdig"),
    ("57301", "D4 Manajemen Informatika", "https://terapan-ti.vokasi.unesa.ac.id/page/dosen", "Manajemen Informatika", "simcv"),
    ("55100", "S2 Informatika", "https://s2if.ft.unesa.ac.id/page/dosen", "Informatika", "s2if"),
    ("83215", "S2 Pendidikan Teknologi Informasi", "https://s2tp.pasca.unesa.ac.id/page/dosen", "Pendidikan Teknologi Informasi", "s2pti"),
]

TARGET_PRODI_NAMES = {cfg[1] for cfg in PRODI_WEB_CONFIG}

# --- SINTA CONFIG ---
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

# --- COLUMN TYPES ---
ID_COLUMN_TYPES = {
    'nip': str,
    'nidn': str,
    'scholar_id': str,
    'scopus_id': str,
    'sinta_id': str
}
