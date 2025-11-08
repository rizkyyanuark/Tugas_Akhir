from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

proxies = {
    "server": "brd.superproxy.io:33335",
    "username": 'brd-customer-hl_68223b6e-zone-web_unlocker1',
    "password": 'n8buv1pplvv0'
}

pw = sync_playwright().start()
browser = pw.firefox.launch(
    headless=False,
    slow_mo=2000,  # Reduced from 5000 to 2000ms for better performance
    proxy=proxies
)

page = browser.new_page(
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Step 1: Navigate to the scholar profile page (LIST VIEW - bukan detail artikel)
# URL ini menampilkan daftar publikasi, bukan detail satu artikel
scholar_profile_url = "http://scholar.google.com/citations?view_op=view_citation&hl=en&user=lFCI_vsAAAAJ&cstart=20&sortby=pubdate&citation_for_view=lFCI_vsAAAAJ:ZeXyd9-uunAC"
print(f"[1] Navigating to scholar profile LIST: {scholar_profile_url}")
page.goto(scholar_profile_url)
page.wait_for_load_state("networkidle")
print(f"    Current URL: {page.url}")

# Step 2: Find and click the first journal article link (class="gsc_a_at")
print("\n[2] Looking for first journal article link (class='gsc_a_at')...")

# Debug: Check how many article links exist
article_links_count = page.locator('a.gsc_a_at').count()
print(f"    Found {article_links_count} article link(s) on page")

if article_links_count > 0:
    article_link = page.locator('a.gsc_a_at').first
    article_title = article_link.inner_text()
    article_href = article_link.get_attribute('href')
    print(f"    Article title: {article_title}")
    print(f"    Article href: {article_href}")

    # Click the article link
    print(f"\n[3] Clicking on article...")
    article_link.click()

    # Wait for navigation to complete
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)  # Extra wait to ensure page fully loads
    print(f"    Navigated to: {page.url}")

    # Step 3: Extract description from class="gsh_csp"
    print("\n[4] Extracting description (class='gsh_csp')...")
    html_content = page.content()
    soup = BeautifulSoup(html_content, 'html.parser')

    description_div = soup.find('div', class_='gsh_csp')

    if description_div:
        description_text = description_div.get_text(strip=True)
        print("\n" + "="*80)
        print("DESCRIPTION:")
        print("="*80)
        print(description_text)
        print("="*80)
    else:
        print("    ⚠️  Description div (class='gsh_csp') not found!")
        print("    Available classes on page:")
        # Debug: print semua div classes yang ada
        all_divs = soup.find_all('div', class_=True)
        unique_classes = set()
        for div in all_divs[:20]:  # Show first 20 unique classes
            if div.get('class'):
                unique_classes.update(div.get('class'))
        for cls in sorted(unique_classes):
            print(f"      - {cls}")

    # Take screenshot of the article page
    page.screenshot(path="article_page.png")
    print(f"\n[5] Screenshot saved: article_page.png")

else:
    print("    ⚠️  No article links found on the page!")
    print("    Taking screenshot of current page for debugging...")
    page.screenshot(path="profile_page_debug.png")
    print(f"    Screenshot saved: profile_page_debug.png")

browser.close()
print("\n✅ Done!")
