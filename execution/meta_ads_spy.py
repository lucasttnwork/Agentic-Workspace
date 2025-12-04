import os
import sys
import json
import time
import uuid
import argparse
import subprocess
import requests
import gspread
import base64
import shutil
from pathlib import Path
from urllib.parse import quote_plus
from datetime import datetime
from dotenv import load_dotenv
from apify_client import ApifyClient
from openai import OpenAI
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

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
MODEL_NAME = "amazon/nova-lite-v1"
VIDEO_MODEL_NAME = "google/gemini-2.5-flash"
VIDEO_MODEL_ALIASES = [
    VIDEO_MODEL_NAME,
    "google/gemini-2.5-pro",
]
DEFAULT_WORKERS = 5
MAX_WORKERS_LIMIT = 15
VIDEO_QUALITY_HIGH = "high"
VIDEO_QUALITY_MEDIUM = "medium"
VIDEO_QUALITY_FAST = "fast"
VIDEO_PRESETS = {
    VIDEO_QUALITY_HIGH: {
        "max_width": 1280,
        "max_height": 720,
        "fps": 24,
        "bitrate": "1500k",
        "maxrate": "1500k",
        "bufsize": "3000k",
        "duration": 60,
    },
    VIDEO_QUALITY_MEDIUM: {
        "max_width": 854,
        "max_height": 480,
        "fps": 24,
        "bitrate": "900k",
        "maxrate": "900k",
        "bufsize": "1800k",
        "duration": 60,
    },
}
FFMPEG_BINARY = None


@contextmanager
def time_block(label):
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        print(f"⏱️ {label}: {duration:.2f}s")

def resolve_ffmpeg_binary():
    env_override = os.getenv("FFMPEG_BINARY")
    candidates = [
        env_override,
        shutil.which("ffmpeg"),
        str(Path.home() / "bin/ffmpeg"),
    ]
    for path in candidates:
        if not path:
            continue
        expanded = os.path.expanduser(path)
        if Path(expanded).exists():
            return expanded
    return "ffmpeg"


class LLMAnalysisError(Exception):
    """Erro encapsulado ao chamar OpenRouter."""


FFMPEG_BINARY = resolve_ffmpeg_binary()
MAX_ANALYSIS_WORKERS = 5

# Initialize Clients
if OPENROUTER_API_KEY:
    openai_client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )

def setup_sheets(sheet_name):
    """Setup Google Sheets connection with two worksheets: Raw Data and Processed Data."""
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
        spreadsheet = client.open(sheet_name)
        raw_sheet = spreadsheet.worksheet("Raw Data")
        processed_sheet = spreadsheet.worksheet("Processed Data")
    except gspread.SpreadsheetNotFound:
        print(f"Spreadsheet '{sheet_name}' not found. Creating it...")
        spreadsheet = client.create(sheet_name)
        
        # Create Raw Data sheet
        raw_sheet = spreadsheet.sheet1
        raw_sheet.update_title("Raw Data")
        raw_headers = ["Ad Archive ID", "Page ID", "Page Name", "Page URL", "Page Likes", 
                       "Ad Text", "CTA Text", "Link URL", "Display Format", 
                       "Start Date", "End Date", "Is Active", "Platforms", "Full JSON"]
        raw_sheet.append_row(raw_headers)
        
        # Create Processed Data sheet
        processed_sheet = spreadsheet.add_worksheet(title="Processed Data", rows=1000, cols=18)
        processed_headers = [
            "ad_archive_id", "type", "date_added", "publish_date", "time_online",
            "page_name", "page_url", "platforms", "page_likes", "ad_likes", "ad_comments",
            "ad_text", "cta", "link_url", "display_format", "summary",
            "image_description", "video_description"
        ]
        processed_sheet.append_row(processed_headers)
        
        # Share with user email if provided
        if USER_EMAIL:
            try:
                spreadsheet.share(USER_EMAIL, perm_type='user', role='writer')
                print(f"Shared spreadsheet with {USER_EMAIL}")
            except Exception as e:
                print(f"Warning: Could not share spreadsheet: {e}")
    except gspread.WorksheetNotFound:
        # Spreadsheet exists but sheets don't
        print(f"Creating sheets in existing spreadsheet...")
        try:
            raw_sheet = spreadsheet.worksheet("Raw Data")
        except:
            raw_sheet = spreadsheet.add_worksheet(title="Raw Data", rows=1000, cols=15)
            raw_headers = ["Ad Archive ID", "Page ID", "Page Name", "Page URL", "Page Likes", 
                           "Ad Text", "CTA Text", "Link URL", "Display Format", 
                           "Start Date", "End Date", "Is Active", "Platforms", "Full JSON"]
            raw_sheet.append_row(raw_headers)
        
        try:
            processed_sheet = spreadsheet.worksheet("Processed Data")
        except:
            processed_sheet = spreadsheet.add_worksheet(title="Processed Data", rows=1000, cols=18)
            processed_headers = [
                "ad_archive_id", "type", "date_added", "publish_date", "time_online",
                "page_name", "page_url", "platforms", "page_likes", "ad_likes", "ad_comments",
                "ad_text", "cta", "link_url", "display_format", "summary",
                "image_description", "video_description"
            ]
            processed_sheet.append_row(processed_headers)
                
    return raw_sheet, processed_sheet

def get_ads_from_apify(search_term=None, url=None, limit=20, dry_run=False):
    """Fetch ads from Apify or use mock data."""
    if dry_run:
        print("DRY RUN: Returning mock ads...")
        return [
            {
                "ad_archive_id": "mock_text_1",
                "publisherPlatform": ["facebook"],
                "page_name": "Mock AI Agency",
                "page_profile_uri": "https://facebook.com/mockpage",
                "ad_creative_body": "Boost your business with AI automation. Save time and money.",
                "snapshot": {"page_like_count": 15000},
                "start_date": 1640995200,
                "isActive": True
            }
        ]

    if not APIFY_TOKEN:
        raise ValueError("APIFY_TOKEN not found in environment variables.")

    client = ApifyClient(APIFY_TOKEN)
    
    if url:
        search_url = url
        print(f"Using provided Ads Library URL: {search_url}")
    else:
        if not search_term:
            raise ValueError("A search term or URL must be provided.")
        base_url = "https://www.facebook.com/ads/library/"
        encoded_term = quote_plus(search_term)
        params = f"?active_status=active&ad_type=all&country=GB&q={encoded_term}&sort_data[direction]=desc&sort_data[mode]=relevancy_monthly_grouped&media_type=all"
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
        # Debug: Save first item to inspect field structure
        if len(dataset_items) == 1:
            os.makedirs(".tmp", exist_ok=True)
            with open(".tmp/sample_apify_item.json", "w") as f:
                json.dump(item, f, indent=2)
            print(f"📝 Saved sample item to .tmp/sample_apify_item.json for inspection")
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
        likes = (ad.get("snapshot") or {}).get("page_like_count", 0)
        if likes is None:
            likes = 0
        if int(likes) >= min_likes:
            filtered.append(ad)
    return filtered

def analyze_content(prompt, media_url=None, media_type="image", model_name=None, raise_on_failure=False):
    """Generic analysis function using OpenRouter."""
    model_to_use = model_name or MODEL_NAME
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    
    if media_url:
        if media_type == "image":
            media_payload = {"type": "image_url", "image_url": {"url": media_url}}
        elif media_type == "video":
            media_payload = {"type": "video_url", "video_url": {"url": media_url}}
        else:
            media_payload = None
        if media_payload:
            messages[0]["content"].append(media_payload)

    response = None
    try:
        with time_block(f"OpenRouter call ({model_to_use})"):
            response = openai_client.chat.completions.create(
                model=model_to_use,
                messages=messages,
                response_format={"type": "json_object"}
            )
        if not hasattr(response, "choices") or not response.choices:
            print("LLM returned no choices. Treating as empty response.")
            return {}
        content_str = response.choices[0].message.content
        if not content_str or content_str.strip() == "":
            print(f"Warning: Empty response from AI model")
            return {}
        
        # Strip markdown code blocks if present (Amazon Nova often wraps JSON in ```json ... ```)
        content_str = content_str.strip()
        if content_str.startswith("```"):
            first_newline = content_str.find("\n")
            last_backticks = content_str.rfind("```")
            if first_newline != -1 and last_backticks != -1:
                content_str = content_str[first_newline + 1:last_backticks].strip()
        content_str = content_str.replace("\\'", "'")

        content = json.loads(content_str, strict=False)
        return content
    except json.JSONDecodeError as e:
        print(f"Error parsing AI response as JSON: {e}")
        raw_message = getattr(response.choices[0].message, "content", "No response") if response else "No response"
        print(f"Raw response: {raw_message}")
        if raise_on_failure:
            raise LLMAnalysisError(f"JSON decode failure: {e}")
        return {"raw_response": raw_message}
    except Exception as e:
        print(f"Error in AI analysis: {e}")
        if raise_on_failure:
            raise LLMAnalysisError(str(e))
        return {}


def download_media(url, suffix=None):
    """Download media to a temporary file."""
    os.makedirs(".tmp", exist_ok=True)
    parsed = url.split("?")[0]
    inferred_ext = Path(parsed).suffix or suffix or ".tmp"
    temp_name = f"{uuid.uuid4()}{inferred_ext}"
    temp_path = Path(".tmp") / temp_name
    try:
        with time_block(f"download media ({url})"):
            response = requests.get(url, timeout=30)
        response.raise_for_status()
        temp_path.write_bytes(response.content)
        return temp_path
    except Exception as exc:
        print(f"Error downloading media {url}: {exc}")
        if temp_path.exists():
            temp_path.unlink()
        return None


def convert_with_ffmpeg(input_path, output_path, extra_args=None):
    args = [FFMPEG_BINARY, "-y", "-i", str(input_path)]
    if extra_args:
        args.extend(extra_args)
    args.append(str(output_path))
    try:
        with time_block("ffmpeg conversion"):
            subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print(f"{FFMPEG_BINARY} binary not found. Please install ffmpeg or set FFMPEG_BINARY.")
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg conversion failed: {exc}")
        if exc.stderr:
            print(exc.stderr.decode('utf-8', errors='ignore'))
    return False


def encode_to_data_uri(file_path, mime_type):
    try:
        with time_block("encode to data URI"):
            data = file_path.read_bytes()
            encoded = base64.b64encode(data).decode('utf-8')
        return f"data:{mime_type};base64,{encoded}"
    except Exception as exc:
        print(f"Error encoding file {file_path} to data URI: {exc}")
        return None


def prepare_image_for_llm(image_url):
    downloaded = download_media(image_url, suffix=".png")
    if not downloaded:
        return None
    converted = downloaded.with_suffix(".converted.png")
    success = convert_with_ffmpeg(downloaded, converted)
    if not success:
        if downloaded.exists() and downloaded.suffix.lower() in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
            converted = downloaded
        else:
            downloaded.unlink(missing_ok=True)
            return None
    data_uri = encode_to_data_uri(converted, "image/png")
    downloaded.unlink(missing_ok=True)
    if converted != downloaded and converted.exists():
        converted.unlink(missing_ok=True)
    return data_uri


def prepare_video_for_llm(video_url, preset, preset_name=None):
    label = f"prepare video ({preset_name})" if preset_name else "prepare video"
    with time_block(label):
        downloaded = download_media(video_url, suffix=".mp4")
        if not downloaded:
            return None
        converted = downloaded.with_suffix(".converted.mp4")
        scale_filter = (
            f"scale='min({preset['max_width']},iw)':'min({preset['max_height']},ih)':"
            "force_original_aspect_ratio=decrease"
        )
        args = [
            "-t",
            str(preset["duration"]),
            "-vf",
            scale_filter,
            "-r",
            str(preset["fps"]),
            "-c:v",
            "libx264",
            "-b:v",
            preset["bitrate"],
            "-maxrate",
            preset["maxrate"],
            "-bufsize",
            preset["bufsize"],
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
        ]
        success = convert_with_ffmpeg(downloaded, converted, extra_args=args)
        if not success:
            if downloaded.exists() and downloaded.suffix.lower() == ".mp4":
                converted = downloaded
            else:
                downloaded.unlink(missing_ok=True)
                return None
        data_uri = encode_to_data_uri(converted, "video/mp4")
        downloaded.unlink(missing_ok=True)
        if converted != downloaded:
            converted.unlink(missing_ok=True)
        return data_uri
    if not downloaded:
        return None
    converted = downloaded.with_suffix(".converted.mp4")
    args = [
        "-t",
        "60",
        "-vf",
        "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease",
        "-r",
        "24",
        "-c:v",
        "libx264",
        "-b:v",
        "1500k",
        "-maxrate",
        "1500k",
        "-bufsize",
        "3000k",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
    ]
    success = convert_with_ffmpeg(downloaded, converted, extra_args=args)
    if not success:
        if downloaded.exists() and downloaded.suffix.lower() == ".mp4":
            converted = downloaded
        else:
            downloaded.unlink(missing_ok=True)
            return None
    data_uri = encode_to_data_uri(converted, "video/mp4")
    downloaded.unlink(missing_ok=True)
    if converted != downloaded:
        converted.unlink(missing_ok=True)
    return data_uri

def coalesce_value(value, default="N/A"):
    """Return a string-friendly default when values are missing or structured."""
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return default
    return value

def first_present(result, *keys):
    """Return first truthy value among the provided keys."""
    for key in keys:
        value = result.get(key)
        if value not in (None, ""):
            return value
    return None


def analyze_text(text):
    prompt = f"""
    Analyze the following Facebook ad copy:
    "{text}"
    
    1. Provide a comprehensive summary of the ad's angle and offer.
    
    Return as JSON: {{ "summary": "..." }}
    """
    result = analyze_content(prompt)
    return first_present(result, "summary", "raw_response")

def analyze_image(image_url, ad_text):
    data_uri = prepare_image_for_llm(image_url)
    if not data_uri:
        print(f"Skipping AI image analysis for URL: {image_url}")
        return "Error", "Error"

    prompt = f"""
    Analyze this ad image and the accompanying text: "{ad_text}"
    
    1. Describe the image in detail.
    2. Provide a summary of the ad.
    3. Create a detailed description of the image that highlights its standout elements.

    Return as JSON: {{ "summary": "...", "image_description": "..." }}
    """
    result = analyze_content(prompt, media_url=data_uri, media_type="image")
    return (
        first_present(result, "summary", "raw_response"),
        first_present(result, "image_description", "raw_response"),
    )

def analyze_video(video_url, ad_text, preview_image_url=None, quality=VIDEO_QUALITY_HIGH):
    fast_mode = quality == VIDEO_QUALITY_FAST
    with time_block(f"analyze video ({quality})"):
        if fast_mode:
            if preview_image_url:
                print("Fast video mode: analyzing preview image only.")
                summary, image_description = analyze_image(preview_image_url, ad_text)
                return summary, image_description
            print("Fast video mode: no preview available, falling back to text.")
            summary = analyze_text(ad_text)
            return summary, "Preview unavailable, fast mode"

        preset = VIDEO_PRESETS.get(quality, VIDEO_PRESETS[VIDEO_QUALITY_HIGH])
        data_uri = prepare_video_for_llm(video_url, preset, preset_name=quality)

    last_error = None
    if data_uri:
        prompt = f"""
        Analyze this video and the text: "{ad_text}"
        
        1. Describe the video content, visual style, and (implied) audio.
        2. Provide a summary of the ad.
        3. Create a detailed video description that could seed a storyboarding tool.
        
        Return as JSON: {{ "summary": "...", "video_description": "..." }}
        """
        for model in VIDEO_MODEL_ALIASES:
            try:
                result = analyze_content(
                    prompt,
                    media_url=data_uri,
                    media_type="video",
                    model_name=model,
                    raise_on_failure=True,
                )
                return (
                    first_present(result, "summary", "raw_response"),
                    first_present(result, "video_description", "raw_response"),
                )
            except LLMAnalysisError as exc:
                print(f"Video analysis with {model} failed: {exc}")
                last_error = exc
        if last_error:
            print("Todas as tentativas de modelo de vídeo falharam. Caindo para preview/texto.")

    if preview_image_url:
        data_uri = prepare_image_for_llm(preview_image_url)
        if data_uri:
            prompt = f"""
            Analyze this video preview image along with the ad text: "{ad_text}"
            
            1. Describe the visual style and any implied narrative.
            2. Provide a summary of the ad.
            3. Produce a video description to guide a storyboard.
            
            Return as JSON: {{ "summary": "...", "video_description": "..." }}
            """
            result = analyze_content(prompt, media_url=data_uri, media_type="image")
            return (
                result.get("summary"),
                result.get("video_description"),
            )

    prompt = f"""
    Analyze this video ad text: "{ad_text}"
    
    1. Summarize the angle and offer.
    2. Provide a short note explaining that video preview was unavailable.
    
    Return as JSON: {{ "summary": "...", "video_description": "Video preview not provided." }}
    """
    result = analyze_content(prompt)
    video_description = result.get("video_description") or "Video preview not provided."
    return (
        result.get("summary"),
        video_description,
    )


def append_rows_if_any(sheet, rows, label):
    """Batch append rows to a worksheet if we have any."""
    if not rows:
        print(f"No rows to write to {label}.")
        return

    try:
        sheet.append_rows(rows, value_input_option="USER_ENTERED")
        print(f"Appended {len(rows)} rows to {label}.")
    except Exception as exc:
        print(f"Error writing batch to {label}: {exc}")

def process_analysis_job(job):
    """Run the targeted analysis for a single ad inside a worker thread."""
    ad_id = job["ad_id"]
    ad_type = job["ad_type"]
    ad_text = job["ad_text"]
    image_url = job["image_url"]
    video_url = job["video_url"]
    video_preview_url = job.get("video_preview_url")
    summary = "N/A"
    image_description = "N/A"
    video_description = "N/A"

    if job.get("dry_run"):
        print(f"[Dry run] Skipping AI for Ad {ad_id}")
        return {
            "summary": "Dry run summary",
            "image_description": "Dry run image description",
            "video_description": "Dry run video description",
        }

    if not OPENROUTER_API_KEY:
        reason = "Skipped (No Key)"
        print(f"{reason} for Ad {ad_id}")
        return {
            "summary": reason,
            "image_description": reason,
            "video_description": reason,
        }

    try:
        if ad_type == "Video":
            if video_url:
                summary, video_description = analyze_video(
                    video_url, ad_text, video_preview_url, quality=job.get("video_quality", VIDEO_QUALITY_HIGH)
                )
            else:
                summary = "Skipped (No Video URL)"
        elif ad_type == "Image":
            if image_url:
                summary, image_description = analyze_image(image_url, ad_text)
            else:
                summary = "Skipped (No Image URL)"
        else:
            summary = analyze_text(ad_text)
    except Exception as exc:
        print(f"Worker error processing Ad {ad_id}: {exc}")

    return {
        "summary": coalesce_value(summary),
        "image_description": coalesce_value(image_description),
        "video_description": coalesce_value(video_description),
    }


def run_analysis_jobs(job_contexts, max_workers):
    if not job_contexts:
        return {}

    results = {}
    workers = min(max_workers, len(job_contexts))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_job = {executor.submit(process_analysis_job, job): job for job in job_contexts}
        for future in as_completed(future_to_job):
            job = future_to_job[future]
            ad_id = job["ad_id"]
            try:
                results[ad_id] = future.result()
            except Exception as exc:
                print(f"Unexpected error for Ad {ad_id}: {exc}")
                results[ad_id] = {
                    "summary": "Error",
                    "image_description": "Error",
                    "video_description": "Error",
                }
    return results

def main():
    parser = argparse.ArgumentParser(description="Meta Ads Spy Tool")
    parser.add_argument("search_term", nargs="?", default=None, help="Term to search for")
    parser.add_argument("--limit", type=int, default=20, help="Number of ads to scrape")
    parser.add_argument("--min-likes", type=int, default=0, help="Minimum page likes filter (0 = no filter)")
    parser.add_argument("--sheet-name", default="Meta Ads Spy Results", help="Google Sheet Name")
    parser.add_argument("--dry-run", action="store_true", help="Use mock data instead of scraping")
    parser.add_argument("--from-csv", help="Load ads from a local CSV file instead of scraping")
    parser.add_argument("--url", help="Direct Facebook Ads Library URL (useful after manual search)")
    parser.add_argument(
        "--video-quality",
        choices=[VIDEO_QUALITY_HIGH, VIDEO_QUALITY_MEDIUM, VIDEO_QUALITY_FAST],
        default=VIDEO_QUALITY_MEDIUM,
        help="Preset for video compression/analysis (fast=preview only). Medium é o padrão recomendado.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Max number of concurrent AI analysis workers",
    )
    
    args = parser.parse_args()
    
    if not args.search_term and not args.url:
        parser.error("Provide either a search term or --url.")
    source_label = args.search_term or "custom URL"
    worker_count = max(1, min(args.workers, MAX_WORKERS_LIMIT))
    print(f"Starting Meta Ads Spy for '{source_label}' (video_quality={args.video_quality}, workers={worker_count})...")
    start_time = time.perf_counter()
    
    # 1. Scrape or Load
    try:
        if args.from_csv:
            ads = load_ads_from_csv(args.from_csv)
            if args.limit and len(ads) > args.limit:
                 ads = ads[:args.limit]
        else:
            ads = get_ads_from_apify(args.search_term, args.url, args.limit, args.dry_run)
    except Exception as e:
        print(f"Error getting ads: {e}")
        return

    print(f"Found {len(ads)} ads. Filtering...")
    
    # 2. Filter
    filtered_ads = filter_ads(ads, args.min_likes)
    print(f"Filtered down to {len(filtered_ads)} ads (Min Likes: {args.min_likes}).")
    
    # 3. Setup Sheets
    try:
        raw_sheet, processed_sheet = setup_sheets(args.sheet_name)
    except Exception as e:
        print(f"Error setting up Google Sheets: {e}")
        return

    raw_rows = []
    job_contexts = []
    for ad in filtered_ads:
        ad_id = ad.get("ad_archive_id")
        raw_snapshot = ad.get("snapshot")
        if raw_snapshot is None:
            print(f"Ad {ad_id} snapshot is None")
        elif not isinstance(raw_snapshot, dict):
            print(f"Ad {ad_id} snapshot unexpected type {type(raw_snapshot).__name__}")
        snapshot = dict(raw_snapshot) if isinstance(raw_snapshot, dict) else {}
        page_name = ad.get("page_name") or snapshot.get("page_name")
        page_url = snapshot.get("page_profile_uri") or ad.get("page_url") or "N/A"
        body = snapshot.get("body")
        body_text = body.get("text") if isinstance(body, dict) else None
        ad_text = (
            snapshot.get("ad_creative_body")
            or body_text
            or ad.get("ad_creative_body")
            or "N/A"
        )
        platforms_data = ad.get("publisher_platform") or ad.get("publisherPlatform") or []
        if isinstance(platforms_data, str):
            platforms_data = [platforms_data]
        platforms_str = ", ".join(platforms_data) if platforms_data else "N/A"

        page_likes = snapshot.get("page_like_count")
        if page_likes is None:
            page_likes = snapshot.get("page_likes")
        ad_likes = snapshot.get("likes")
        if ad_likes is None:
            ad_likes = snapshot.get("ad_like_count")
        ad_comments = snapshot.get("comments")
        if ad_comments is None:
            ad_comments = snapshot.get("comment_count")
        cta_text = (
            snapshot.get("cta_text")
            or snapshot.get("cta", {}).get("text")
            or "N/A"
        )
        link_url = (
            snapshot.get("link_url")
            or snapshot.get("linkURL")
            or snapshot.get("destination_url")
            or "N/A"
        )
        display_format = (
            snapshot.get("display_format")
            or snapshot.get("format")
            or snapshot.get("ad_format")
            or "N/A"
        )

        videos = snapshot.get("videos", [])
        video_url = None
        video_preview_url = None
        if videos:
            video_url = videos[0].get("video_sd_url") or videos[0].get("video_hd_url")
            video_preview_url = videos[0].get("video_preview_image_url")

        images = snapshot.get("images", [])
        image_url = None
        if images:
            image_url = images[0].get("original_image_url") or images[0].get("resized_image_url")

        start_date_val = ad.get("start_date") or ad.get("adDeliveryStartDate")
        publish_date = "N/A"
        time_online = "N/A"
        if start_date_val:
            try:
                if isinstance(start_date_val, (int, float)):
                    start_dt = datetime.fromtimestamp(start_date_val)
                else:
                    start_date_str = str(start_date_val).split('T')[0]
                    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
                publish_date = start_dt.strftime("%Y-%m-%d")
                delta = datetime.now() - start_dt
                time_online = f"{delta.days} days"
            except Exception as exc:
                print(f"Error parsing date {start_date_val}: {exc}")

        ad_type = "Text"
        if video_url:
            ad_type = "Video"
        elif image_url:
            ad_type = "Image"

        raw_row = [
            ad_id,
            ad.get("page_id"),
            page_name,
            page_url,
            coalesce_value(page_likes),
            ad_text,
            coalesce_value(cta_text),
            link_url,
            display_format,
            ad.get("start_date"),
            ad.get("end_date"),
            ad.get("is_active"),
            platforms_str,
            json.dumps(ad)
        ]
        raw_rows.append(raw_row)

        job_contexts.append({
            "ad_id": ad_id,
            "ad_type": ad_type,
            "ad_text": ad_text,
            "image_url": image_url,
            "video_url": video_url,
            "video_preview_url": video_preview_url,
            "page_name": page_name,
            "page_url": page_url,
            "platforms_str": platforms_str,
            "page_likes": page_likes,
            "ad_likes": ad_likes,
            "ad_comments": ad_comments,
            "cta_text": cta_text,
            "link_url": link_url,
            "display_format": display_format,
            "publish_date": publish_date,
            "time_online": time_online,
            "dry_run": args.dry_run,
            "video_quality": args.video_quality,
        })

    append_rows_if_any(raw_sheet, raw_rows, "Raw Data")

    if job_contexts:
        analysis_results = run_analysis_jobs(job_contexts, worker_count)
    else:
        analysis_results = {}
    processed_rows = []
    for context in job_contexts:
        ad_id = context["ad_id"]
        result = analysis_results.get(ad_id, {})
        row = [
            ad_id,
            context["ad_type"],
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            context["publish_date"],
            context["time_online"],
            context["page_name"],
            context["page_url"],
            context["platforms_str"],
            coalesce_value(context["page_likes"]),
            coalesce_value(context["ad_likes"]),
            coalesce_value(context["ad_comments"]),
            coalesce_value(context["ad_text"]),
            coalesce_value(context["cta_text"]),
            context["link_url"],
            context["display_format"],
            coalesce_value(result.get("summary")),
            coalesce_value(result.get("image_description")),
            coalesce_value(result.get("video_description")),
        ]
        processed_rows.append(row)
        print(f"Prepared processed row for Ad {ad_id}")

    append_rows_if_any(processed_sheet, processed_rows, "Processed Data")

    duration = time.perf_counter() - start_time
    print(f"\n{'='*60}")
    print("✅ Done!")
    print(f"Total runtime: {duration:.1f}s")
    print(f"{'='*60}")
    print(f"📊 Google Sheet URL: {processed_sheet.spreadsheet.url}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
