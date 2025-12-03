import os
import sys
import json
import time
import argparse
import requests
import gspread
import base64
from datetime import datetime
from dotenv import load_dotenv
from apify_client import ApifyClient
from openai import OpenAI
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Load environment variables
load_dotenv()

# Configuration
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
USER_EMAIL = os.getenv("USER_EMAIL")
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"

# OpenRouter Configuration
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Using GPT-4o for reliable multimodal analysis
MODEL_NAME = "openai/gpt-4o" 

# Initialize Clients
if OPENROUTER_API_KEY:
    openai_client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )

def setup_sheets(sheet_name):
    """Setup Google Sheets connection using OAuth 2.0."""
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = None
    
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(f"Credentials file '{CREDENTIALS_FILE}' not found.")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    client = gspread.authorize(creds)
    
    try:
        sheet = client.open(sheet_name).sheet1
    except gspread.SpreadsheetNotFound:
        print(f"Spreadsheet '{sheet_name}' not found. Creating it...")
        sheet = client.create(sheet_name).sheet1
        # Create headers
        headers = ["Ad Archive ID", "Type", "Date Added", "Page Name", "Page URL", "Summary", "Rewritten Ad Copy", "Image Prompt", "Video Prompt"]
        sheet.append_row(headers)
        # Share with user email if provided
        if USER_EMAIL:
            try:
                sheet.spreadsheet.share(USER_EMAIL, perm_type='user', role='writer')
                print(f"Shared spreadsheet with {USER_EMAIL}")
            except Exception as e:
                print(f"Warning: Could not share spreadsheet: {e}")
                
    return sheet

def get_ads_from_apify(search_term, limit=20, dry_run=False):
    """Fetch ads from Apify or use mock data."""
    if dry_run:
        print("DRY RUN: Returning mock ads...")
        return [
            {
                "adArchiveID": "mock_text_1",
                "publisherPlatform": ["facebook"],
                "pageName": "Mock AI Agency",
                "pageProfileUri": "https://facebook.com/mockpage",
                "adCreativeBody": "Boost your business with AI automation. Save time and money.",
                "snapshot": {"page_like_count": 15000},
                "isActive": True
            }
        ]

    if not APIFY_TOKEN:
        raise ValueError("APIFY_TOKEN not found in environment variables.")

    client = ApifyClient(APIFY_TOKEN)
    
    # Construct the Facebook Ad Library URL
    # Country: GB, Ad Type: all, Active Status: all
    base_url = "https://www.facebook.com/ads/library/"
    params = f"?active_status=all&ad_type=all&country=GB&q={search_term}&sort_data[direction]=desc&sort_data[mode]=relevancy_monthly_grouped&media_type=all"
    search_url = base_url + params
    
    print(f"Generated Search URL: {search_url}")

    # Use limitPerSource instead of maxItems for more accurate limiting
    run_input = {
        "urls": [{"url": search_url}],
        "limitPerSource": limit
    }
    
    print(f"Starting Apify scraper for term: '{search_term}' in GB (limit: {limit})...")
    run = client.actor("curious_coder/facebook-ads-library-scraper").call(run_input=run_input)
    
    dataset_items = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        dataset_items.append(item)
        # Enforce limit manually to prevent over-scraping (backup)
        if len(dataset_items) >= limit:
            print(f"Reached limit of {limit} ads. Stopping...")
            break
    
    return dataset_items

def load_ads_from_csv(csv_path):
    """Load ads from a local CSV file and map to expected format."""
    import pandas as pd
    import numpy as np
    
    print(f"Loading ads from CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    df = df.replace({np.nan: None}) # Replace NaNs with None
    
    ads = []
    for _, row in df.iterrows():
        # Map CSV columns to the dictionary structure expected by the rest of the script
        ad = {
            "adArchiveID": row.get("ad_archive_id"),
            "pageName": row.get("page_name") or row.get("snapshot/page_name"),
            "pageProfileUri": row.get("snapshot/page_profile_uri"),
            "adCreativeBody": row.get("snapshot/body/text") or row.get("snapshot/body"),
            "snapshot": {
                "page_like_count": row.get("snapshot/page_like_count")
            },
            "video_sd_url": row.get("snapshot/videos/0/video_sd_url"),
            "video_hd_url": row.get("snapshot/videos/0/video_hd_url"),
            "originalImageUrl": row.get("snapshot/images/0/original_image_url") or row.get("snapshot/cards/0/original_image_url"),
            "imageUrl": row.get("snapshot/images/0/resized_image_url")
        }
        ads.append(ad)
        
    return ads

def filter_ads(ads, min_likes=0):
    """Filter ads based on page likes."""
    if min_likes == 0:
        return ads  # Skip filtering if min_likes is 0
        
    filtered = []
    for ad in ads:
        likes = ad.get("snapshot", {}).get("page_like_count", 0)
        if likes is None:
            likes = 0
        if int(likes) >= min_likes:
            filtered.append(ad)
    return filtered

def analyze_content(prompt, media_url=None, media_type="image"):
    """Generic analysis function using OpenRouter."""
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    
    if media_url:
        # media_url can be a http URL or a data URI
        messages[0]["content"].append({
            "type": "image_url", # OpenRouter often uses image_url for video data URIs too
            "image_url": {"url": media_url}
        })

    try:
        response = openai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            response_format={"type": "json_object"}
        )
        content = json.loads(response.choices[0].message.content)
        return content
    except Exception as e:
        print(f"Error in AI analysis: {e}")
        return {}

def analyze_text(text):
    prompt = f"""
    Analyze the following Facebook ad copy:
    "{text}"
    
    1. Provide a comprehensive summary of the ad's angle and offer.
    2. Rewrite the ad copy for a similar product but with a fresh perspective.
    
    Return as JSON: {{ "summary": "...", "rewritten_copy": "..." }}
    """
    result = analyze_content(prompt)
    return result.get("summary"), result.get("rewritten_copy")

def analyze_image(image_url, ad_text):
    # Download image to base64
    try:
        response = requests.get(image_url)
        response.raise_for_status()
        base64_image = base64.b64encode(response.content).decode('utf-8')
        data_uri = f"data:image/jpeg;base64,{base64_image}"
        
        prompt = f"""
        Analyze this ad image and the accompanying text: "{ad_text}"
        
        1. Describe the image in detail.
        2. Provide a summary of the ad.
        3. Rewrite the ad copy.
        4. Create a detailed image generation prompt to recreate a similar image.
        
        Return as JSON: {{ "summary": "...", "rewritten_copy": "...", "image_prompt": "..." }}
        """
        result = analyze_content(prompt, media_url=data_uri, media_type="image")
        return result.get("summary"), result.get("rewritten_copy"), result.get("image_prompt")
    except Exception as e:
        print(f"Error analyzing image: {e}")
        return "Error", "Error", "Error"

def analyze_video(video_url, ad_text):
    # Download video
    print(f"Downloading video from {video_url}...")
    video_path = f".tmp/temp_video_{int(time.time())}.mp4"
    os.makedirs(".tmp", exist_ok=True)
    
    try:
        with requests.get(video_url, stream=True) as r:
            r.raise_for_status()
            with open(video_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        # Read and encode
        with open(video_path, "rb") as video_file:
            base64_video = base64.b64encode(video_file.read()).decode('utf-8')
            
        data_uri = f"data:video/mp4;base64,{base64_video}"
        
        prompt = f"""
        Analyze this video and the text: "{ad_text}"
        
        1. Describe the video content, visual style, and audio (implied).
        2. Provide a summary of the ad.
        3. Rewrite the ad copy.
        4. Create a detailed video generation prompt.
        
        Return as JSON: {{ "summary": "...", "rewritten_copy": "...", "video_prompt": "..." }}
        """
        
        # Send as native video data URI
        result = analyze_content(prompt, media_url=data_uri, media_type="video")
        return result.get("summary"), result.get("rewritten_copy"), result.get("video_prompt")
        
    except Exception as e:
        print(f"Error analyzing video: {e}")
        return "Error", "Error", "Error"
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)

def main():
    parser = argparse.ArgumentParser(description="Meta Ads Spy Tool")
    parser.add_argument("search_term", help="Term to search for")
    parser.add_argument("--limit", type=int, default=20, help="Number of ads to scrape")
    parser.add_argument("--min-likes", type=int, default=0, help="Minimum page likes filter (0 = no filter)")
    parser.add_argument("--sheet-name", default="Meta Ads Spy Results", help="Google Sheet Name")
    parser.add_argument("--dry-run", action="store_true", help="Use mock data instead of scraping")
    parser.add_argument("--from-csv", help="Load ads from a local CSV file instead of scraping")
    
    args = parser.parse_args()
    
    print(f"Starting Meta Ads Spy for '{args.search_term}'...")
    
    # 1. Scrape or Load
    try:
        if args.from_csv:
            ads = load_ads_from_csv(args.from_csv)
            # If loading from CSV, we might want to slice to limit if requested, 
            # though usually we process all. Let's respect limit if it's small.
            if args.limit and len(ads) > args.limit:
                 ads = ads[:args.limit]
        else:
            ads = get_ads_from_apify(args.search_term, args.limit, args.dry_run)
    except Exception as e:
        print(f"Error getting ads: {e}")
        return

    print(f"Found {len(ads)} ads. Filtering...")
    
    # 2. Filter
    filtered_ads = filter_ads(ads, args.min_likes)
    print(f"Filtered down to {len(filtered_ads)} ads (Min Likes: {args.min_likes}).")
    
    # 3. Setup Sheets
    try:
        sheet = setup_sheets(args.sheet_name)
    except Exception as e:
        print(f"Error setting up Google Sheets: {e}")
        return

    # 4. Process
    for ad in filtered_ads:
        ad_id = ad.get("adArchiveID")
        page_name = ad.get("pageName")
        page_url = ad.get("pageProfileUri")
        ad_text = ad.get("adCreativeBody", "")
        
        # Determine Type
        ad_type = "Text"
        video_url = ad.get("video_sd_url") or ad.get("video_hd_url")
        image_url = ad.get("originalImageUrl") or ad.get("imageUrl")
        
        if video_url:
            ad_type = "Video"
        elif image_url:
            ad_type = "Image"
            
        print(f"Processing Ad {ad_id} ({ad_type})...")
        
        summary = ""
        rewritten = ""
        image_prompt = ""
        video_prompt = ""
        
        try:
            if ad_type == "Video":
                if OPENROUTER_API_KEY and video_url:
                    summary, rewritten, video_prompt = analyze_video(video_url, ad_text)
                else:
                    summary = "Skipped (No Key or URL)"
            elif ad_type == "Image":
                if OPENROUTER_API_KEY and image_url:
                    summary, rewritten, image_prompt = analyze_image(image_url, ad_text)
                else:
                    summary = "Skipped (No Key or URL)"
            else:
                if OPENROUTER_API_KEY:
                    summary, rewritten = analyze_text(ad_text)
                else:
                    summary = "Skipped (No Key)"
                    
            # 5. Save
            row = [
                ad_id,
                ad_type,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                page_name,
                page_url,
                summary,
                rewritten,
                image_prompt,
                video_prompt
            ]
            sheet.append_row(row)
            print(f"Saved Ad {ad_id} to sheet.")
            
        except Exception as e:
            print(f"Error processing Ad {ad_id}: {e}")
            continue

    print(f"\n{'='*60}")
    print("✅ Done!")
    print(f"{'='*60}")
    print(f"📊 Google Sheet URL: {sheet.spreadsheet.url}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
