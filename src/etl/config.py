import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Base Directory Setup
BASE_DIR = Path(__file__).resolve().parent.parent.parent
dotenv_path = BASE_DIR / ".env"
load_dotenv(dotenv_path)

DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# Initialize dirs
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# CREDENTIAL LOADING ORDER (lowest -> highest priority):
#   1. OS Environment Variables (.env file)
#   2. credentials_new.json fallback (fills gaps only)
#   3. Airflow UI Variables (ALWAYS WINS - highest priority)
# ============================================================

# --- Layer 1: OS Environment Variables ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
BD_PASS_SERP = os.environ.get("BD_PASS_SERP")
SCIVAL_EMAIL = os.environ.get("SCIVAL_EMAIL")
SCIVAL_PASS = os.environ.get("SCIVAL_PASS")

# --- Layer 2: credentials_new.json fallback (fills MISSING values only) ---
try:
    creds_path = BASE_DIR / "notebooks" / "scraping" / "credentials_new.json"
    if creds_path.exists():
        with open(creds_path, 'r') as f:
            creds = json.load(f)
        if not SUPABASE_URL: SUPABASE_URL = creds.get('supabase', {}).get('url') or creds.get('SUPABASE_URL')
        if not SUPABASE_KEY: SUPABASE_KEY = creds.get('supabase', {}).get('key') or creds.get('SUPABASE_KEY')
        if not SERPAPI_KEY: SERPAPI_KEY = creds.get('serpapi', {}).get('api_key') or creds.get('SERPAPI_KEY')
        if not BD_PASS_SERP:
            BD_PASS_SERP = creds.get('bright_data', {}).get('proxy_unlocker', {}).get('password') or creds.get('BD_PASS_SERP')
        if not SCIVAL_EMAIL: SCIVAL_EMAIL = creds.get('unesa', {}).get('email') or creds.get('SCIVAL_EMAIL')
        if not SCIVAL_PASS: SCIVAL_PASS = creds.get('unesa', {}).get('password') or creds.get('SCIVAL_PASS')
except Exception as e:
    print(f"Warning loading credentials JSON: {e}")

# --- Layer 3: Airflow UI Variables (HIGHEST PRIORITY - always overrides) ---
try:
    from airflow.models import Variable

    def _av(name, fallback):
        """Get Airflow Variable if it exists, otherwise keep fallback."""
        v = Variable.get(name, default_var=None)
        return v if v is not None else fallback

    SUPABASE_URL = _av('SUPABASE_URL', SUPABASE_URL)
    SUPABASE_KEY = _av('SUPABASE_KEY', SUPABASE_KEY)
    SERPAPI_KEY = _av('SERPAPI_KEY', SERPAPI_KEY)
    BD_PASS_SERP = _av('BD_PASS_SERP', BD_PASS_SERP)
    SCIVAL_EMAIL = _av('SCIVAL_EMAIL', SCIVAL_EMAIL)
    SCIVAL_PASS = _av('SCIVAL_PASS', SCIVAL_PASS)
except ImportError:
    pass  # Not running in Airflow environment

# --- Diagnostics ---
if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ WARNING: SUPABASE_URL or SUPABASE_KEY is missing.")
else:
    print(f"✅ Config: Loaded Credentials (Supabase: {SUPABASE_URL})")
