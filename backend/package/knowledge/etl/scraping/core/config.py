import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# --- PATHS ---
# Root of the project (assumes this file is in backend/package/knowledge/etl/scraping/core/config.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
PROJECT_ROOT = BASE_DIR

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
SAVE_DIR = DATA_DIR / "file_tabulars"
SAVES_DIR = PROJECT_ROOT / "saves"

# Ensure directories exist
SAVE_DIR.mkdir(parents=True, exist_ok=True)
SAVES_DIR.mkdir(parents=True, exist_ok=True)

# --- SCRAPING SETTINGS ---
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
SCIVAL_EMAIL = os.getenv("SCIVAL_EMAIL", "")
SCIVAL_PASS = os.getenv("SCIVAL_PASS", "")

# --- SUPABASE ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# --- BRIGHT DATA ---
BRIGHT_DATA_HOST = os.getenv("BRIGHT_DATA_HOST", "brd.superproxy.io:33335")
BD_USER_UNLOCKER = os.getenv("BD_USER_UNLOCKER", "")
BD_PASS_UNLOCKER = os.getenv("BD_PASS_UNLOCKER", "")
BD_USER_SERP = os.getenv("BD_USER_SERP", "")
BD_PASS_SERP = os.getenv("BD_PASS_SERP", "")

# --- HEADERS ---
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
