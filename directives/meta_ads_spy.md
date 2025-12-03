# Meta Ads Spy Directive

## Goal
Spy on competitors' Facebook ads to gather intelligence, generate repurposing ideas, and create AI-ready assets (prompts).

## Inputs
- **Search Term**: The keyword to search for in the Facebook Ad Library.
- **Min Page Likes**: Minimum number of likes a page must have to be included (default: 10,000).
- **Google Sheet Name**: The name of the Google Sheet to save results to.

## Tools & APIs
- **Apify**: `Facebook Ad Library Scraper` (Actor ID: `curious_coder/facebook-ads-library-scraper`). Uses `urls` parameter with constructed URL.
- **OpenRouter**: `google/gemini-flash-1.5-8b` (native video support).
- **Google Sheets**: For storing the final output (OAuth 2.0).

## Workflow Steps

1.  **Scrape Ads**
    - Construct Facebook Ad Library URL with search term and country (GB).
    - Use Apify to scrape ads using the constructed URL.
    - **Note**: If running in `dry-run` mode, use a mock dataset.

2.  **Filter Ads**
    - Filter out ads from pages with fewer than **Min Page Likes**.

3.  **Process Ads (Routing)**
    - Iterate through the filtered ads and categorize them:
        - **Video**: If `video_sd_url` or `video_hd_url` exists.
        - **Image**: If `original_image_url` exists (and not video).
        - **Text**: Fallback if neither video nor image.

4.  **Analyze & Enrich**
    - **Text Ads**:
        - Use OpenRouter (Gemini Flash 8B) to summarize the ad and rewrite the copy.
    - **Image Ads**:
        - Use OpenRouter (Gemini Flash 8B) to analyze the image (Base64).
        - Generate: Summary, Rewritten Copy, Image Prompt.
    - **Video Ads**:
        - Download the video (temp).
        - Convert to Base64 Data URI.
        - Send to OpenRouter (Gemini Flash 8B) as native video input.
        - Generate: Summary, Rewritten Copy, Video Prompt.

5.  **Save to Google Sheets**
    - Append a row for each ad with the following columns:
        - `Ad Archive ID`
        - `Type` (Text/Image/Video)
        - `Date Added`
        - `Page Name`
        - `Page URL`
        - `Summary`
        - `Rewritten Ad Copy`
        - `Image Prompt` (if applicable)
        - `Video Prompt` (if applicable)

## Output
- A populated Google Sheet with the analyzed ad data.
