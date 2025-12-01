# Directive: Scrape Leads

## Goal
Scrape business leads from Google Maps using a custom Python script with Playwright. The script searches for businesses, extracts their details (including visiting their websites for emails and social links), and saves the results to a Google Sheet.

## Inputs
- **Search Query**: The specific search term (e.g., "marketing agencies in London")
- **Limit**: Maximum number of leads to scrape (default: 10)

## Tools/Scripts
- **Execution Script**: `execution/scrape_leads.py`
- **Dependencies**: Listed in `execution/requirements.txt` (requires `playwright`)

## Outputs
- **Google Sheet**: A **new** spreadsheet created for each run containing scraped leads (Name, Address, Phone, Website, Email, Social Links).
- **CSV Backup**: A local CSV file is also saved.

## Process Flow

### 1. Setup
- Ensure dependencies are installed: `pip install -r execution/requirements.txt`
- Ensure Playwright browsers are installed: `playwright install chromium`
- Ensure Google Cloud credentials (`credentials.json`) are present.

### 2. Execution
- Run the script: `python execution/scrape_leads.py "search query" [limit]`
- The script launches a browser (headless or visible).
- It searches Google Maps for the query.
- It scrolls to load results up to the limit.

### 3. Enrichment
- For each result with a website, the script visits the website.
- It scans the homepage for email addresses and social media links.

### 4. Save
- All data is compiled into a DataFrame.
- A new Google Sheet is created in the user's Drive.
- The data is uploaded to the sheet.
- A shareable link is printed to the console.

## Edge Cases & Learnings

### Scraping Reliability
- **Google Maps DOM**: The script relies on specific CSS selectors. If Google changes their layout, the script may need updates.
- **Rate Limiting**: Google may block IP addresses if scraping is too aggressive. The script uses random delays, but be cautious with very large limits.
- **Website Blocking**: Some business websites may block automated access. The script handles these errors gracefully.

### Google Sheets
- **Authentication**: OAuth2.0 requires browser authorization on first run.
- **Token Expiry**: `token.json` auto-refreshes.

## Required Credentials

### Google Sheets (OAuth2.0)
- **File**: `credentials.json`
- **Location**: Project root or parent directory.
- **Setup**: Download from Google Cloud Console.

## Usage Example

```bash
# Install dependencies (first time only)
pip install -r execution/requirements.txt
playwright install chromium

# Run the scraper
python execution/scrape_leads.py "dental clinics in London" 20
```
