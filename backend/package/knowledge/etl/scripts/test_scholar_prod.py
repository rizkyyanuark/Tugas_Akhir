import os
import sys
import logging
import requests
from bs4 import BeautifulSoup

# Setup paths
sys.path.insert(0, "/app/package")
sys.path.insert(0, "backend/package")

# Try to load local .env if available
try:
    from dotenv import load_dotenv
    for p in [".env", "backend/.env", "../.env", "c:/Users/rizky/Documents/GitHub/Tugas_Akhir/.env"]:
        if os.path.exists(p):
            load_dotenv(p)
            break
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

logger = logging.getLogger("test_scholar_prod")

print("====================================================")
print("GOOGLE SCHOLAR PROD DIAGNOSTIC")
print("====================================================")

# 1. Inspect Environment Variables
print("\n--- 1. Checking Environment Variables ---")
vars_to_check = [
    "BD_USER_SERP", "BD_PASS_SERP", 
    "BD_USER_UNLOCKER", "BD_PASS_UNLOCKER", 
    "BD_SCRAPING_BROWSER_URL", "BRIGHT_DATA_HOST",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy"
]

for var in vars_to_check:
    val = os.environ.get(var)
    if val is None:
        print(f"  {var}: <NOT SET>")
    elif var in ["BD_PASS_SERP", "BD_PASS_UNLOCKER", "BD_SCRAPING_BROWSER_URL"]:
        # Obscure password/URLs
        print(f"  {var}: <SET> (length: {len(val)})")
    else:
        print(f"  {var}: {val}")

# 2. Inport configurations
print("\n--- 2. Loading Settings Facade ---")
try:
    from knowledge.etl.config import (
        BD_USER_UNLOCKER, BD_PASS_UNLOCKER, BRIGHT_DATA_HOST, 
        PROXY_URL, BD_SCRAPING_BROWSER_URL
    )
    print(f"  Loaded BD_USER_UNLOCKER: {bool(BD_USER_UNLOCKER)} (len: {len(BD_USER_UNLOCKER) if BD_USER_UNLOCKER else 0})")
    print(f"  Loaded BD_PASS_UNLOCKER: {bool(BD_PASS_UNLOCKER)}")
    print(f"  Loaded BD_SCRAPING_BROWSER_URL: {bool(BD_SCRAPING_BROWSER_URL)}")
    print(f"  Loaded PROXY_URL: {bool(PROXY_URL)}")
except Exception as e:
    print(f"  Error loading config: {e}")
    sys.exit(1)

# 3. Test Scraping Browser Connectivity
print("\n--- 3. Testing Scraping Browser Connection ---")
if BD_SCRAPING_BROWSER_URL:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        
        print("  Initializing Chrome remote driver (without env proxies)...")
        chrome_options = Options()
        
        # Temp bypass
        env_proxies = {}
        for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
            if key in os.environ:
                env_proxies[key] = os.environ[key]
                del os.environ[key]
                
        try:
            driver = webdriver.Remote(
                command_executor=BD_SCRAPING_BROWSER_URL,
                options=chrome_options
            )
            print("  SUCCESS: Connected to Scraping Browser!")
            driver.get("https://scholar.google.com/citations?user=nbtuM4IAAAAJ&hl=en")
            soup = BeautifulSoup(driver.page_source, "html.parser")
            rows = soup.find_all("tr", class_="gsc_a_tr")
            print(f"  Scraping Browser result: Found {len(rows)} paper rows.")
            driver.quit()
        finally:
            for key, val in env_proxies.items():
                os.environ[key] = val
    except Exception as e:
        print(f"  FAILED: Scraping Browser error: {e}")
else:
    print("  Skipped: BD_SCRAPING_BROWSER_URL is not set.")

# 4. Test Web Unlocker and SERP API Proxies
print("\n--- 4. Testing Web Unlocker Proxy ---")
if BD_USER_UNLOCKER and BD_PASS_UNLOCKER and BRIGHT_DATA_HOST:
    unlocker_proxy = f"http://{BD_USER_UNLOCKER}:{BD_PASS_UNLOCKER}@{BRIGHT_DATA_HOST}"
    proxies = {
        "http": unlocker_proxy,
        "https": unlocker_proxy
    }
    target_url = "https://scholar.google.com/citations?user=nbtuM4IAAAAJ&hl=en"
    
    # Test A: With Custom User-Agent and Headers
    print("  Test A: Web Unlocker with Custom User-Agent and Headers...")
    custom_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
    }
    try:
        resp = requests.get(target_url, proxies=proxies, headers=custom_headers, verify=False, timeout=30)
        print(f"    Status Code: {resp.status_code}")
        print(f"    Final URL: {resp.url}")
        is_captcha = "sorry" in resp.url or any(x in resp.text.lower()[:2000] for x in ["unusual traffic", "g-recaptcha", "google.com/sorry/"])
        if is_captcha:
            print("    Result: CAPTCHA / Block detected!")
        else:
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.find_all("tr", class_="gsc_a_tr")
            print(f"    Result: Found {len(rows)} paper rows.")
    except Exception as e:
        print(f"    Error in Test A: {e}")
        
    # Test B: Without Custom User-Agent
    print("  Test B: Web Unlocker WITHOUT Custom User-Agent...")
    try:
        resp = requests.get(target_url, proxies=proxies, verify=False, timeout=30)
        print(f"    Status Code: {resp.status_code}")
        print(f"    Final URL: {resp.url}")
        is_captcha = "sorry" in resp.url or any(x in resp.text.lower()[:2000] for x in ["unusual traffic", "g-recaptcha", "google.com/sorry/"])
        if is_captcha:
            print("    Result: CAPTCHA / Block detected!")
        else:
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.find_all("tr", class_="gsc_a_tr")
            print(f"    Result: Found {len(rows)} paper rows.")
    except Exception as e:
        print(f"    Error in Test B: {e}")
else:
    print("  Skipped: Web Unlocker credentials not available.")

print("\n--- 5. Testing SERP API Proxy ---")
if PROXY_URL:
    proxies_serp = {
        "http": PROXY_URL,
        "https": PROXY_URL
    }
    target_url = "https://scholar.google.com/citations?user=nbtuM4IAAAAJ&hl=en"
    
    # Test C: With Custom User-Agent and Headers
    print("  Test C: SERP API Proxy with Custom User-Agent and Headers...")
    custom_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
    }
    try:
        resp = requests.get(target_url, proxies=proxies_serp, headers=custom_headers, verify=False, timeout=30)
        print(f"    Status Code: {resp.status_code}")
        print(f"    Final URL: {resp.url}")
        is_captcha = "sorry" in resp.url or any(x in resp.text.lower()[:2000] for x in ["unusual traffic", "g-recaptcha", "google.com/sorry/"])
        if is_captcha:
            print("    Result: CAPTCHA / Block detected!")
        else:
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.find_all("tr", class_="gsc_a_tr")
            print(f"    Result: Found {len(rows)} paper rows.")
    except Exception as e:
        print(f"    Error in Test C: {e}")
        
    # Test D: Without Custom User-Agent
    print("  Test D: SERP API Proxy WITHOUT Custom User-Agent...")
    try:
        resp = requests.get(target_url, proxies=proxies_serp, verify=False, timeout=30)
        print(f"    Status Code: {resp.status_code}")
        print(f"    Final URL: {resp.url}")
        is_captcha = "sorry" in resp.url or any(x in resp.text.lower()[:2000] for x in ["unusual traffic", "g-recaptcha", "google.com/sorry/"])
        if is_captcha:
            print("    Result: CAPTCHA / Block detected!")
        else:
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.find_all("tr", class_="gsc_a_tr")
            print(f"    Result: Found {len(rows)} paper rows.")
    except Exception as e:
        print(f"    Error in Test D: {e}")
else:
    print("  Skipped: SERP API proxy URL not available.")

print("\n====================================================")
print("DIAGNOSTIC COMPLETE")
print("====================================================")
