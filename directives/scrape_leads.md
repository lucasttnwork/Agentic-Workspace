# Directive: Scrape Leads

## Goal
Extract targeted B2B leads using the Apify Leads Finder actor (code_crafter/leads-finder). The system performs a test run with 30 leads to verify quality (≥80% match rate), then proceeds to full scraping and saves results to a formatted Google Sheet.

## Inputs
- **Job Titles**: Array of job titles to target (e.g., ["CEO", "Founder", "CTO", "Product Manager"])
- **Location**: Array of countries/regions (e.g., ["United Kingdom"])
- **Industry**: Array of industries (e.g., ["computer software", "saas", "internet"])
- **Company Size**: Array of size ranges (e.g., ["2-10", "11-20", "21-50", "51-100", "101-200"])
- **Limit**: Maximum number of leads to scrape (default: 100)
- **Verification Keywords**: Keywords to verify lead relevance (optional)

## Tools/Scripts
- **Execution Script**: `execution/scrape_leads.py`
- **Post-process AI assistant**: `execution/casualize_company_names.py`
- **Dependencies**: Listed in `requirements.txt` (requires `apifyclient`, `pandas`, `gspread`, `google-auth`, `requests`)
- **API**: Apify Leads Finder actor (code_crafter/leads-finder)

## Outputs
- **Google Sheet**: A new spreadsheet created for each run containing scraped leads.
    - **Person Columns**: Full Name, Job Title, Email, Mobile, Personal Email, LinkedIn, City, State, Country
    - **Company Columns**: Company Name, Domain, Website, Size, Industry, Revenue, Funding, Phone, Address
    - **Casual Name Column**: `casualized_company_name` (populated via GPT-4o-mini via OpenRouter)
    - **Formatting**: Bold headers, frozen top row
- **CSV Backup**: A local CSV file is also saved with timestamp

## Process Flow

### 1. Setup
- Ensure dependencies are installed: `pip install -r requirements.txt`
- Ensure Apify API token is configured in `.env` file
- Ensure Google Cloud credentials (`credentials.json`) are present

### 2. Verification Run (Test Run)
- The script first requests 30 leads from the Apify actor
- It checks if ≥80% of these leads match the criteria:
  - Has a valid email address
  - Job title contains relevant keywords
  - Industry matches SaaS/software/tech
  - Company size is within target range (small/medium)
- **Pass**: Proceeds to full scrape
- **Fail**: Stops and suggests parameter adjustments

### 3. Full Scrape
- If verification passes, script requests the full limit (e.g., 100 leads)
- Apify actor returns enriched data with:
  - Validated emails
  - Mobile numbers (for paid plans)
  - LinkedIn profiles
  - Complete company information (size, industry, revenue, funding)
  - Location data (city, state, country)

### 4. Save
- All data is compiled into a DataFrame
- A new Google Sheet is created in the user's Drive
- The sheet is formatted (bold headers, frozen rows)
- A shareable link is printed to the console
- CSV backup is saved locally

### 5. Casualização de nomes
- Após salvar a planilha, `execution/casualize_company_names.py` é executado automaticamente pelo `scrape_leads.py`.
- O script confirma/insere a coluna `casualized_company_name` (cria se necessário) e só considera linhas com o campo vazio.
- As entradas pendentes são enviadas ao modelo `gpt-4o-mini` via API OpenRouter (usando `OPENROUTER_API_KEY`) em paralelo, reduzindo a latência sem cache de resultados.
- Os resultados são aplicados em lote no Google Sheets, evitando múltiplas chamadas `update_cell` e eliminando reprocessamentos.
- O prompt agora reforça que a resposta deve manter o idioma original, remover apenas elementos formais (ex: “Ltd”, “Estate Agents”, “Group”), não corrigir nomes (ex: “Mulburries” permanece “Mulburries”) nem usar apelidos para nomes próprios (não trocar “William” por “Will”), e não inventar novas palavras ou traduzir o nome oficial — o objetivo é chegar a uma forma natural usada pelos fundadores/clientes (geralmente o primeiro nome ou variação familiarly reconhecida).

## Edge Cases & Learnings

### Apify Actor
- **Credits**: Actor costs ~$1.5 per 1000 leads. Monitor usage to avoid unexpected charges
- **Rate Limits**: Apify has rate limits. For large datasets (>10k leads), consider splitting into multiple runs
- **Email Quality**: Setting `email_status: ["validated"]` ensures higher quality emails but may reduce total results

### Data Quality
- **Verification Threshold**: 80% match rate ensures most leads are relevant without being too restrictive
- **Test Run Size**: 30 leads provides good statistical sample while minimizing costs
- **Keywords**: Broader keywords (e.g., "software", "technology") increase matches; narrow keywords (e.g., "saas platform") reduce false positives

### Google Sheets
- **Authentication**: OAuth2.0 requires browser authorization on first run
- **Formatting**: Requires `gspread` formatting permissions
- **Data Sanitization**: Actor output must be cleaned (NaN, inf values) before Sheets upload
- **Casual Name Column**: A automação pós-processo adiciona/atualiza a coluna `Nome Casual`, então removê-la manualmente pode levar a reprocessamentos.

## Required Credentials

### Apify API
- **File**: `.env`
- **Variable**: `APIFY_TOKEN`
- **Setup**: Get API token from https://console.apify.com/account/integrations

### Google Sheets (OAuth2.0)
- **File**: `credentials.json`
- **Location**: Project root
- **Setup**: Download from Google Cloud Console

### OpenRouter (GPT-4o-mini)
- **File**: `.env`
- **Variable**: `OPENROUTER_API_KEY`
- **Setup**: Configure um token válido com acesso ao modelo `gpt-4o-mini` via OpenRouter. É usado por `execution/casualize_company_names.py`.

## Usage Example

```bash
# Install dependencies (first time only)
pip install -r requirements.txt

# Run the scraper with default parameters (100 UK SaaS leads)
python execution/scrape_leads.py

# Or customize parameters in the script before running
# Edit the INPUT_CONFIG dictionary in scrape_leads.py
```

## Expected Output

**Test Run (30 leads):**
```
Starting test run with 30 leads...
Apify actor started: run_id_xxxxx
Waiting for actor to complete...
Actor completed successfully
Retrieved 30 leads
Verifying leads...
Verification Result: 26/30 (86.67%) match.
✅ Verification PASSED. Proceeding to full scrape.
```

**Full Run (100 leads):**
```
Starting full run with 100 leads...
Apify actor started: run_id_yyyyy
Waiting for actor to complete...
Actor completed successfully
Retrieved 100 leads
✅ Backup saved to: /path/to/leads_2025-12-02_17-15.csv
Formatting sheet...
✅ Google Sheet created: https://docs.google.com/spreadsheets/d/xxxxx
```
