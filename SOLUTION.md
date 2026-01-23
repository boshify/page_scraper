# Page Scraper - Corruption Issue Fixed

## Problem
The GTO Wizard Blog page (https://blog.gtowizard.com/the-science-of-poker-performance/) was being scraped with severe encoding corruption, showing nearly 30,000 replacement characters instead of readable content.

## Root Cause
The issue was caused by **missing Brotli decompression support**. The server was returning Brotli-compressed responses (`Content-Encoding: br`), but the `brotli` Python package was not installed. This caused the compressed binary data to be treated as UTF-8 text, resulting in massive corruption.

## Solution
Installed the `brotli` package to enable proper decompression of Brotli-compressed HTTP responses:

```bash
pip install brotli
```

## Changes Made

### 1. Added brotli to requirements.txt
```
Flask
cloudscraper
trafilatura
beautifulsoup4
lxml
charset-normalizer
ftfy
brotli  # <-- Added
```

### 2. Minor code improvements in app.py
- Changed to use `resp.text` directly instead of always using `robust_decode()` for better handling of properly encoded responses
- Kept `robust_decode()` as a fallback for edge cases

## Test Results

All 3 target pages now scrape successfully:

### ✓ GTO Wizard Blog
- URL: https://blog.gtowizard.com/the-science-of-poker-performance/
- Status: SUCCESS
- Title: "The Science of Poker Performance | GTO Wizard"
- Content: 18,761 characters
- Sections: 200
- Encoding: Perfect (0 replacement characters)

### ✓ Teal HQ Blog
- URL: https://www.tealhq.com/post/how-to-get-your-resume-past-ai
- Status: SUCCESS
- Title: "5 Tips To Get Your Resume Past AI 'Robots'"
- Content: 9,514 characters
- Sections: 14
- Encoding: Perfect

### ✓ Jonathan Boshoff About
- URL: https://jonathanboshoff.com/about-me/
- Status: SUCCESS
- Title: "About Jonathan Boshoff"
- Content: 4,321 characters
- Sections: 16
- Encoding: Perfect

## Technical Details

The issue occurred because:
1. Cloudflare (used by GTO Wizard) serves content with Brotli compression
2. The `cloudscraper` library depends on the `brotli` package for decompression
3. Without `brotli`, the raw compressed bytes were interpreted as UTF-8, causing corruption
4. Installing `brotli` allows `requests`/`cloudscraper` to automatically decompress responses

## Deployment
To deploy this fix:
```bash
pip install -r requirements.txt
```

The fix is backward compatible and improves scraping for all sites that use Brotli compression.
