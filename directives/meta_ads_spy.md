# Meta Ads Spy Directive

## Goal
Spy on competitors' Facebook ads to gather intelligence, generate repurposing ideas, and create AI-ready assets (prompts).

## Inputs
- **Search Term**: The keyword to search for in the Facebook Ad Library.
- **Active Only**: Ensure only currently active ads are scraped.
- **Min Page Likes**: Minimum number of likes a page must have to be included (default: 10,000).
- **Google Sheet Name**: The name of the Google Sheet to save results to.

## Tools & APIs
- **Apify**: `Facebook Ad Library Scraper` (Actor ID: `curious_coder/facebook-ads-library-scraper`). Uses `urls` parameter with constructed URL (active_status=active).
- **OpenRouter**: `amazon/nova-lite-v1` (Amazon Nova 2 Lite, multimodal, cost-effective).
- **Google Sheets**: For storing the final output (OAuth 2.0).

## Workflow Steps

1.  **Scrape Ads**
    - Construct Facebook Ad Library URL with search term, country (GB), and `active_status=active`.
    - Use Apify to scrape ads using the constructed URL.
    - **Note**: If running in `dry-run` mode, use a mock dataset.
    - **Manual override**: Prefer copiar a URL completa do Facebook Ads Library após filtrar por resultados relevantes e passar para o script via `--url`.

2.  **Filter Ads**
    - Filter out ads from pages with fewer than **Min Page Likes**.

3.  **Process Ads (Routing)**
    - Iterate through the filtered ads and categorize them:
        - **Video**: If `video_sd_url` or `video_hd_url` exists.
        - **Image**: If `original_image_url` exists (and not video).
        - **Text**: Fallback if neither video nor image.

4.  **Analyze & Enrich**
    - **Text Ads**:
        - Use OpenRouter (Amazon Nova 2 Lite) to summarize the ad and capture its angle.
    - **Image Ads**:
        - Use OpenRouter (Amazon Nova 2 Lite) to analyze the image (Base64/URL).
        - Generate: Summary and Image Prompt.
        - Validate that the format is one of `gif`, `jpeg`, `png`, or `webp`; otherwise fall back to text analysis.
    - **Video Ads**:
        - Download the video (temp).
        - Convert to Base64 Data URI.
        - Send to OpenRouter (Amazon Nova 2 Lite) as native video input.
        - Generate: Summary and Video Prompt.
    - **OpenRouter Response Handling**
        - Amazon Nova often wraps JSON in ```json``` code blocks; strip the fences before parsing.
        - Treat empty responses gracefully; re-run or mark as skipped rather than crashing.

5.  **Save to Google Sheets**
    - Create or reuse a spreadsheet with two worksheets to preserve both the raw scrape and the cleaned output.
        - **Raw Data**: Flattened JSON with columns such as `Ad Archive ID`, `Page ID`, `Page Name`, `Page URL`, `Page Likes`, `Ad Text`, `CTA Text`, `Link URL`, `Display Format`, `Start Date`, `End Date`, `Is Active`, `Platforms`, `Full JSON`.
        - **Processed Data**: Cleaned, human-friendly columns:
            1. `Ad Archive ID`
            2. `Type` (Text/Image/Video)
            3. `Date Added`
            4. `Publish Date`
            5. `Time Online`
            6. `Page Name`
            7. `Page URL`
            8. `Platforms`
            9. `Page Likes`
            10. `Ad Likes`
            11. `Ad Comments`
            12. `Ad Text`
            13. `CTA`
            14. `Link URL`
            15. `Display Format`
            16. `Summary`
            17. `Image Prompt`
            18. `Video Prompt`

- Facebook Ad Library API rarely exposes ad-level likes/comments; the exported columns default to page-level counts and may show `N/A` for most ads.
- Amazon Nova 2 Lite only accepts `gif`, `jpeg`, `png`, and `webp` images; unsupported formats fall back to text-only analysis rather than failing the run.
- When calling Nova via OpenRouter, video uploads are not supported in the same way as the AWS Converse API, so the script should rely on the video's preview image (if available) or revert to text-only synthesis when no preview exists.
- **Video model**: o script usa `google/gemini-2.5-flash` via OpenRouter, que aceita vídeos base64 (especialmente recomendável para arquivos locais). Como alternativa, tentamos `google/gemini-2.5-pro` antes de reverter ao preview/imagens/texto. Garanta que os vídeos estejam em um dos formatos suportados (`mp4`, `mpeg`, `mov`, `webm`) e sejam convertidos para Data URI antes do envio.
- **URL manual**: o parâmetro `--url` aceita uma URL do Facebook Ads Library (depois de confirmar manualmente o resultado da busca). Quando presente, a busca automática é pulada e o mesmo limite de 20 anúncios continua sendo aplicado.
- **ffmpeg**: o script detecta `ffmpeg` no PATH, em `~/bin/ffmpeg` ou via `FFMPEG_BINARY`. Defina essa variável se você instalou o binário em outro lugar para garantir que as conversões multimodais sejam executadas.
- Publish dates may come from either `startDate` or `adDeliveryStartDate` and in UNIX timestamps or ISO strings; the script normalizes both.
- Keeping both `Raw Data` and `Processed Data` sheets lets you troubleshoot issues without re-running Apify and re-process entries if needed.
- **Flags de execução**
  - `--video-quality`: define os presets `high` (720p, vídeo completo), `medium` (480p + bitrate reduzido – padrão recomendado) ou `fast` (usa apenas o preview). Use `medium` como default para equilibrar velocidade e fidelidade.
  - `--workers`: controla o número de threads que analisam anúncios simultaneamente (default 5, máximo 15). Aumentar ajuda com paralelismo, mas pode expor limites de rate ou de chave.

## Output
- A populated Google Sheet with both `Raw Data` and `Processed Data` worksheets containing the analyzed ad intelligence.
