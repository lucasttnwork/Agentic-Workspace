import os
import sys
import re
import time
import random
import pandas as pd
import numpy as np
import gspread
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
HEADLESS = False  # Set to True for headless mode
SCROLL_TIMEOUT = 3000  # ms
WAIT_TIMEOUT = 5000  # ms
MAX_WORKERS = 5 # Number of parallel threads for website enrichment

def setup_google_sheets():
    """
    Setup Google Sheets client using OAuth2.0 (user credentials).
    On first run, will open browser for authentication.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive.file'
    ]
    
    creds = None
    token_file = 'token.json'
    credentials_file = 'credentials.json'
    
    # Check for token/credentials in parent directory if not in current
    if not os.path.exists(token_file) and os.path.exists(f'../{token_file}'):
        token_file = f'../{token_file}'
    
    if not os.path.exists(credentials_file) and os.path.exists(f'../{credentials_file}'):
        credentials_file = f'../{credentials_file}'
        
    if not os.path.exists(credentials_file):
        print("Error: credentials.json not found.")
        print("Please download OAuth2.0 credentials from Google Cloud Console.")
        sys.exit(1)
    
    # Load existing token
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    
    # If no valid credentials, authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("No valid token found. Starting OAuth2.0 flow...")
            print("A browser window will open. Please authorize the application.")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save token for future use
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
        print(f"Token saved to {os.path.abspath(token_file)}")
    
    try:
        gc = gspread.authorize(creds)
        return gc
    except Exception as e:
        print(f"Error setting up Google Sheets: {e}")
        sys.exit(1)

def sanitize_dataframe_for_sheets(df):
    """
    Sanitizes DataFrame to ensure all values are JSON-compliant for Google Sheets API.
    """
    # First, replace NaN, inf, -inf in the DataFrame
    df_clean = df.replace([np.nan, np.inf, -np.inf], "")
    
    # Convert to list of lists
    values = [df_clean.columns.values.tolist()] + df_clean.values.tolist()
    
    # Additional sanitization pass
    sanitized_values = []
    for row in values:
        sanitized_row = []
        for val in row:
            if val is None:
                sanitized_row.append("")
            elif isinstance(val, float) and (pd.isna(val) or np.isnan(val)):
                sanitized_row.append("")
            elif isinstance(val, float) and (np.isinf(val) or np.isneginf(val)):
                sanitized_row.append("")
            else:
                sanitized_row.append(val)
        sanitized_values.append(sanitized_row)
    
    return sanitized_values

def create_and_save_sheet(gc, leads, search_query):
    """
    Creates a NEW Google Sheet and saves leads.
    """
    if not leads:
        print("No leads to save.")
        return

    # Always save to CSV first as backup
    from datetime import datetime
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"leads_{timestamp}.csv"
        df = pd.DataFrame(leads)
        
        # Sanitize data
        df = df.replace([np.nan, np.inf, -np.inf], "")
        
        df.to_csv(filename, index=False)
        print(f"✅ Backup saved to: {os.path.abspath(filename)}")
    except Exception as e:
        print(f"Error saving CSV backup: {e}")

    try:
        # Create new sheet
        timestamp_readable = datetime.now().strftime("%Y-%m-%d %H:%M")
        sheet_title = f"Leads: {search_query} - {timestamp_readable}"
        sh = gc.create(sheet_title)

        worksheet = sh.sheet1
        
        # Create DataFrame and sanitize
        df = pd.DataFrame(leads)
        values = sanitize_dataframe_for_sheets(df)
        
        worksheet.update(values)
        print(f"✅ Google Sheet created: {sh.url}")
        return sh.url
        
    except Exception as e:
        print(f"❌ Error saving to Google Sheets: {e}")
        return None

def enrich_single_lead(lead):
    """
    Worker function to enrich a single lead.
    Launches a new browser context/page for isolation.
    """
    url = lead.get("website")
    if not url:
        return lead

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True) # Always headless for workers
            page = browser.new_page()
            
            # print(f"  Visiting {url}...")
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            time.sleep(2) # Wait for dynamic content
            
            content = page.content()
            soup = BeautifulSoup(content, 'html.parser')
            text = soup.get_text()

            # Extract Emails
            emails = set(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text))
            valid_emails = [e for e in emails if not any(x in e.lower() for x in ['.png', '.jpg', '.jpeg', '.gif', 'example.com', 'yourdomain'])]
            
            # Extract Social Links
            social_domains = ['facebook.com', 'twitter.com', 'instagram.com', 'linkedin.com', 'youtube.com', 'tiktok.com']
            social_links = set()
            for link in soup.find_all('a', href=True):
                href = link['href']
                if any(domain in href for domain in social_domains):
                    social_links.add(href)
            
            lead["email"] = ", ".join(list(valid_emails)[:3])
            lead["social_links"] = ", ".join(list(social_links))
            
            browser.close()
            
        except Exception as e:
            # print(f"  Failed to enrich {url}: {e}")
            pass
            
    return lead

class GoogleMapsScraper:
    def __init__(self):
        pass

    def scrape(self, query, limit=10):
        print(f"Starting scrape for '{query}' (Limit: {limit})...")
        
        leads = []
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS)
            context = browser.new_context(viewport={'width': 1280, 'height': 800})
            page = context.new_page()
            
            # Go to Google Maps
            page.goto("https://www.google.com/maps", timeout=60000)
            
            # Handle cookie consent
            try:
                page.click("button[aria-label='Accept all']", timeout=3000)
            except:
                pass

            # Search
            page.fill("#searchboxinput", query)
            page.keyboard.press("Enter")
            
            # Wait for results to load
            page.wait_for_selector("div[role='feed']", timeout=10000)
            
            # Scroll to load more results
            feed_selector = "div[role='feed']"
            previously_counted = 0
            
            # Fix: Use double quotes for the JS string to avoid conflict with single quotes in selector
            scroll_script = f'document.querySelector("{feed_selector}").scrollTo(0, document.querySelector("{feed_selector}").scrollHeight)'
            
            while True:
                results = page.locator("div[role='article']").all()
                count = len(results)
                
                print(f"  Found {count} results so far...")
                
                if count >= limit:
                    break
                
                if count == previously_counted:
                    page.evaluate(scroll_script)
                    time.sleep(2)
                    
                    if "You've reached the end of the list" in page.content():
                        break
                else:
                    previously_counted = count
                    results[-1].scroll_into_view_if_needed()
                    time.sleep(1)

            # Extract Basic Info
            results = page.locator("div[role='article']").all()[:limit]
            print(f"Extracting basic info for {len(results)} leads...")
            
            for i, result in enumerate(results):
                try:
                    result.click()
                    time.sleep(1) 
                    
                    name = result.get_attribute("aria-label") or ""
                    
                    address = ""
                    try:
                        address = page.locator('button[data-item-id="address"]').get_attribute("aria-label").replace("Address: ", "")
                    except:
                        pass
                        
                    website = ""
                    try:
                        website = page.locator('a[data-item-id="authority"]').get_attribute("href")
                    except:
                        pass
                        
                    phone = ""
                    try:
                        phone = page.locator('button[data-item-id^="phone"]').get_attribute("aria-label").replace("Phone: ", "")
                    except:
                        pass

                    leads.append({
                        "title": name,
                        "address": address,
                        "website": website,
                        "phone": phone,
                        "category": query,
                        "description": "",
                        "email": "",
                        "social_links": ""
                    })
                    
                except Exception as e:
                    print(f"Error extracting lead {i}: {e}")
            
            browser.close()
            
        return leads

def main():
    # --- User Inputs ---
    SEARCH_QUERY = "marketing agencies in London"
    if len(sys.argv) > 1:
        SEARCH_QUERY = sys.argv[1]
        
    LIMIT = 10
    if len(sys.argv) > 2:
        LIMIT = int(sys.argv[2])

    print(f"--- Starting Scraper for '{SEARCH_QUERY}' (Limit: {LIMIT}) ---")
    
    # 1. Setup
    google_client = setup_google_sheets()
    
    # 2. Scrape Basic Info
    scraper = GoogleMapsScraper()
    leads = scraper.scrape(SEARCH_QUERY, limit=LIMIT)
    
    print(f"\nBasic scrape complete. Found {len(leads)} leads.")
    print(f"Starting enrichment with {MAX_WORKERS} parallel workers...")
    
    # 3. Enrich in Parallel
    enriched_leads = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_lead = {executor.submit(enrich_single_lead, lead): lead for lead in leads}
        
        for i, future in enumerate(as_completed(future_to_lead)):
            lead = future.result()
            enriched_leads.append(lead)
            print(f"  Enriched {i+1}/{len(leads)}: {lead['title']}")
            
    print(f"\nEnrichment complete.")
    
    # 4. Save
    if enriched_leads:
        create_and_save_sheet(google_client, enriched_leads, SEARCH_QUERY)
    else:
        print("No leads found.")

if __name__ == "__main__":
    main()
