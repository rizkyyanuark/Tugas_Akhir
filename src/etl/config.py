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

# Supabase Credentials
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# API Keys
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
BD_PASS_SERP = os.environ.get("BD_PASS_SERP")

# For local development without env vars, trying credentials_new.json fallback
try:
    creds_path = BASE_DIR / "notebooks" / "scraping" / "credentials_new.json"
    if creds_path.exists():
        with open(creds_path, 'r') as f:
            creds = json.load(f)
            if not SUPABASE_URL: SUPABASE_URL = creds.get('SUPABASE_URL')
            if not SUPABASE_KEY: SUPABASE_KEY = creds.get('SUPABASE_KEY')
            if not SERPAPI_KEY: SERPAPI_KEY = creds.get('SERPAPI_KEY')
            if not BD_PASS_SERP: BD_PASS_SERP = creds.get('BD_PASS_SERP')
except Exception as e:
    print(f"Warning loading credentials JSON: {e}")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ WARNING: SUPABASE_URL or SUPABASE_KEY is missing.")
