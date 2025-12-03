import os
import sys
import time
import pandas as pd
import numpy as np
import gspread
from dotenv import load_dotenv
from apify_client import ApifyClient

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
APIFY_TOKEN = os.getenv('APIFY_TOKEN')
if not APIFY_TOKEN:
    print("Error: APIFY_TOKEN not found in .env file")
    sys.exit(1)

# Default input configurations by preset.
LEAD_PRESETS = {
    "sme_software": {
        "contact_job_title": ["CEO", "Founder", "Co-Founder", "CTO", "Product Manager", "VP Engineering", "Head of Product"],
    "contact_location": ["united kingdom"],
        "company_industry": ["computer software", "internet", "information technology & services"],
        "size": ["1-10", "11-20", "21-50", "51-100", "101-200"],
        "email_status": ["validated"],
    },
    "real_estate_agents_uk": {
        "contact_job_title": ["Real Estate Agent", "Estate Agent", "Property Manager", "Real Estate Broker", "Real Estate Consultant", "Director of Real Estate"],
        "contact_location": ["united kingdom"],
        "company_industry": ["real estate", "commercial real estate"],
        "size": ["1-10", "11-20", "21-50", "51-100", "101-200"],
        "email_status": ["validated"],
    },
}

LEAD_PRESET = os.getenv("LEAD_PRESET", "sme_software")
INPUT_CONFIG = LEAD_PRESETS.get(LEAD_PRESET)

if not INPUT_CONFIG:
    print(f"Warning: preset '{LEAD_PRESET}' not found. Falling back to 'sme_software'.")
    INPUT_CONFIG = LEAD_PRESETS["sme_software"]

# Verification keywords (for 80% matching)
VERIFICATION_KEYWORDS_PRESETS = {
    "sme_software": ["software", "saas", "technology", "tech", "platform", "product", "engineering", "digital", "cloud", "data"],
    "real_estate_agents_uk": ["real estate", "property", "estate", "agent", "broker", "consultant", "residential", "commercial", "property management", "realtor"]
}

VERIFICATION_KEYWORDS = VERIFICATION_KEYWORDS_PRESETS.get(LEAD_PRESET, VERIFICATION_KEYWORDS_PRESETS["sme_software"])

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

def create_and_save_sheet(gc, leads, description):
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
        sheet_title = f"Leads: {description} - {timestamp_readable}"
        sh = gc.create(sheet_title)

        worksheet = sh.sheet1
        
        # Create DataFrame and sanitize
        df = pd.DataFrame(leads)
        values = sanitize_dataframe_for_sheets(df)
        
        worksheet.update(values)
        
        # --- Formatting ---
        print("Formatting sheet...")
        try:
            # Bold headers
            worksheet.format("A1:Z1", {"textFormat": {"bold": True}})
            # Freeze header row
            worksheet.freeze(rows=1)
        except Exception as e:
            print(f"Warning: Formatting failed (likely permissions or API limit): {e}")
        
        print(f"✅ Google Sheet created: {sh.url}")
        return {
            "spreadsheet_id": sh.id,
            "worksheet_title": worksheet.title,
            "spreadsheet_url": sh.url,
        }
        
    except Exception as e:
        print(f"❌ Error saving to Google Sheets: {e}")
        return None

def run_apify_actor(fetch_count):
    """
    Runs the Apify Leads Finder actor and returns the results.
    """
    print(f"\nStarting Apify actor run with fetch_count={fetch_count}...")
    
    # Initialize the ApifyClient with your API token
    client = ApifyClient(APIFY_TOKEN)
    
    # Prepare the actor input
    run_input = {
        **INPUT_CONFIG,
        "fetch_count": fetch_count,
        "file_name": f"leads_run_{int(time.time())}"
    }

    if "contact_location" in run_input:
        run_input["contact_location"] = [loc.lower() for loc in run_input["contact_location"]]
    
    print(f"Input configuration: {run_input}")
    
    # Run the actor and wait for it to finish
    try:
        run = client.actor("code_crafter/leads-finder").call(run_input=run_input)
        
        print(f"Actor run completed: {run['id']}")
        
        # Fetch results from the run's dataset
        results = []
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            results.append(item)
        
        print(f"Retrieved {len(results)} leads from Apify")
        return results
        
    except Exception as e:
        print(f"Error running Apify actor: {e}")
        sys.exit(1)

def transform_leads(apify_results):
    """
    Transforms Apify actor output into our standard format.
    """
    transformed = []
    
    for item in apify_results:
        # Create full name
        first_name = item.get('first_name', '')
        last_name = item.get('last_name', '')
        full_name = item.get('full_name', f"{first_name} {last_name}".strip())
        
        # Build transformed lead
        lead = {
            # Person info
            "full_name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "job_title": item.get('job_title', ''),
            "headline": item.get('headline', ''),
            "seniority_level": item.get('seniority_level', ''),
            "functional_level": item.get('functional_level', ''),
            
            # Contact info
            "email": item.get('email', ''),
            "mobile_number": item.get('mobile_number', ''),
            "personal_email": item.get('personal_email', ''),
            "linkedin": item.get('linkedin', ''),
            
            # Location
            "city": item.get('city', ''),
            "state": item.get('state', ''),
            "country": item.get('country', ''),
            
            # Company info
            "company_name": item.get('company_name', ''),
            "company_domain": item.get('company_domain', ''),
            "company_website": item.get('company_website', ''),
            "company_linkedin": item.get('company_linkedin', ''),
            "company_size": item.get('company_size', ''),
            "industry": item.get('industry', ''),
            "company_description": item.get('company_description', ''),
            "company_annual_revenue": item.get('company_annual_revenue', ''),
            "company_total_funding": item.get('company_total_funding', ''),
            "company_founded_year": item.get('company_founded_year', ''),
            "company_phone": item.get('company_phone', ''),
            "company_full_address": item.get('company_full_address', ''),
        }
        
        transformed.append(lead)
    
    return transformed

def verify_leads(leads, keywords):
    """
    Verifies if the scraped leads match the criteria.
    Returns pass rate and whether it passes the 80% threshold.
    """
    if not leads:
        return 0, False

    valid_count = 0
    total_count = len(leads)
    
    print(f"\nVerifying {total_count} leads against criteria...")

    for lead in leads:
        # Check if lead has email
        has_email = bool(lead.get("email", "").strip())
        
        # Check if job title or industry contains keywords
        text_to_check = (
            str(lead.get("job_title", "")) + " " + 
            str(lead.get("headline", "")) + " " +
            str(lead.get("industry", "")) + " " +
            str(lead.get("company_description", ""))
        ).lower()
        
        has_keywords = any(keyword.lower() in text_to_check for keyword in keywords)
        
        # Check if company size is in target range
        company_size = str(lead.get("company_size", ""))
        is_target_size = any(size in company_size for size in INPUT_CONFIG["size"])
        
        # Lead is valid if it has email AND (has keywords OR is target size)
        is_valid = has_email and (has_keywords or is_target_size)
        
        if is_valid:
            valid_count += 1

    pass_rate = (valid_count / total_count) * 100 if total_count > 0 else 0
    print(f"Verification Result: {valid_count}/{total_count} ({pass_rate:.2f}%) match.")
    
    return pass_rate, pass_rate >= 80

def main():
    print("=" * 60)
    print("LEADS SCRAPER - Apify Leads Finder Integration")
    print("=" * 60)
    
    # Configuration
    TEST_LIMIT = 30
    FULL_LIMIT = 100
    
    # 1. Setup
    print("\n[1/4] Setting up Google Sheets authentication...")
    google_client = setup_google_sheets()
    print("✅ Google Sheets ready")
    
    # 2. Test Run (Verification)
    print(f"\n[2/4] Running TEST run with {TEST_LIMIT} leads...")
    test_results = run_apify_actor(fetch_count=TEST_LIMIT)
    
    if not test_results:
        print("❌ No results from test run. Exiting.")
        sys.exit(1)
    
    test_leads = transform_leads(test_results)
    
    # Verify test leads
    pass_rate, passed = verify_leads(test_leads, VERIFICATION_KEYWORDS)
    
    if not passed:
        print(f"\n❌ VERIFICATION FAILED. Match rate {pass_rate:.2f}% < 80%.")
        print("The leads found do not sufficiently match the criteria.")
        print("\nSuggestions:")
        print("- Try adjusting job titles in INPUT_CONFIG")
        print("- Try different company industries")
        print("- Review company size ranges")
        sys.exit(0)
    
    print(f"\n✅ VERIFICATION PASSED ({pass_rate:.2f}% match rate)")
    
    # 3. Full Run
    print(f"\n[3/4] Running FULL scrape with {FULL_LIMIT} leads...")
    full_results = run_apify_actor(fetch_count=FULL_LIMIT)
    
    if not full_results:
        print("❌ No results from full run. Exiting.")
        sys.exit(1)
    
    final_leads = transform_leads(full_results)
    print(f"✅ Retrieved and transformed {len(final_leads)} leads")
    
    # 4. Save to Google Sheets
    print(f"\n[4/4] Saving leads to Google Sheets...")
    sheet_metadata = create_and_save_sheet(
        google_client, 
        final_leads, 
        f"UK SaaS Small/Medium - {len(final_leads)} leads"
    )

    if sheet_metadata:
        from execution.casualize_company_names import casualize_sheet

        casualize_sheet(
            google_client,
            sheet_metadata["spreadsheet_id"],
            sheet_metadata["worksheet_title"],
            lead_preset=LEAD_PRESET
        )
    
    print("\n" + "=" * 60)
    print("SCRAPING COMPLETE!")
    print("=" * 60)

if __name__ == "__main__":
    main()
