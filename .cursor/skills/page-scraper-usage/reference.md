# Page Scraper Reference

## POST /read — Full API

### Request

```json
{
  "url": "https://example.com/article",
  "max_chars": 5000,
  "return_html": false,
  "clean_html": true,
  "is_sitemap": false,
  "fast_mode": true
}
```

### Parameters (detailed)

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `url` | string | — | Required. Must start with `http://` or `https://` |
| `max_chars` | int | 5000 | Truncates `flat_outline`, `html`, `tables[].markdown`, `tables[].html`. Truncated strings end with `... [truncated]` |
| `return_html` | bool | false | Adds `html` field to response |
| `clean_html` | bool | true | When true: stripped HTML (content tags only, attributes limited to href/src/alt). When false: raw `<body>` HTML |
| `clean_html` alias | — | — | `Clean HTML` also accepted |
| `is_sitemap` | bool | false | Sitemap mode: returns `{ok: true, urls: [...]}` only |
| `is_sitemap` alias | — | — | `Is Sitemap` also accepted |
| `fast_mode` | bool | true | `true`: ~4s fetch, 1 retry, ~8s hard limit. `false`: ~15s fetch, 3 retries, ~25s hard limit. Hard limit configurable via `READ_HARD_TIMEOUT_SECONDS` env var. |

### Sitemap Mode (`is_sitemap: true`)

- Works with XML sitemaps (`sitemap.xml`) — parses `<loc>` elements
- Works with HTML pages — extracts all `<a href>` (absolute URLs)
- Also accepts `text/xml` and `application/xml` content types
- Response: `{"ok": true, "urls": ["https://...", ...]}`

### Response (success)

```json
{
  "ok": true,
  "title": "...",
  "meta_description": "...",
  "url": "https://...",
  "canonical": "https://...",
  "robots": null,
  "lang": "en",
  "length": 1234,
  "lengths": {"main_text": 1234, "flat_outline": 1500},
  "h1": "...",
  "flat_outline": "# Introduction\n\n...",
  "schema_markup": ["{...}"],
  "tables": [{"markdown": "| A | B |\n|---|---|", "html": "<table>...", "caption": "..."}],
  "outline_sections": [{"title": "...", "level": "H2", "paragraphs": ["..."]}],
  "html": "..."
}
```

`html` only present when `return_html: true`.

### Response Field Details

| Field | Type | Description |
|-------|------|-------------|
| `ok` | bool | `true` on success |
| `title` | string\|null | `<title>` tag content |
| `meta_description` | string\|null | `<meta name="description">` content |
| `url` | string | The requested URL |
| `canonical` | string | Canonical URL from `<link rel="canonical">`, falls back to requested URL |
| `robots` | string\|null | `<meta name="robots">` content (e.g., `noindex, nofollow`) |
| `lang` | string\|null | `<html lang="...">` attribute |
| `h1` | string\|null | First `<h1>` text content |
| `length` | int | Character count of extracted main text |
| `lengths` | object | `{main_text: int, flat_outline: int}` — character counts before truncation |
| `flat_outline` | string | Markdown-formatted content with headings. Primary content field. Subject to `max_chars` truncation. |
| `outline_sections` | array | Structured sections: `[{title, level, paragraphs}]`. Max 200 sections. |
| `tables` | array | `[{markdown, html, caption}]`. Each field subject to `max_chars`. Max 20 tables. |
| `schema_markup` | array | Raw JSON-LD strings from `<script type="application/ld+json">` blocks |
| `html` | string\|null | Only when `return_html: true`. Cleaned or raw body HTML based on `clean_html`. |

### Content Focusing Algorithm

The scraper narrows down to the main content area before extraction:

1. Strips `<script>`, `<style>`, `<noscript>`, `<template>` tags
2. Removes HTML comments
3. Extracts exact `<body>` content
4. Drops chrome: `<header>`, `<footer>`, `<nav>`, `<aside>`, and elements with navigation/banner/sidebar/cookie/ad roles or class names
5. Selects content root: `<main>` > `<article>` > element with most `<p>` descendants
6. Extracts text via trafilatura (multiple passes with different precision settings), falls back to BeautifulSoup `get_text()`

### Outline Extraction

From the focused content area:
- Extracts `h1`-`h6`, `p`, `li`, `blockquote` elements
- Converts inline HTML to Markdown (links, bold, italic, code, images)
- Filters out menu-like content (many short lines) and boilerplate (cookie notices, subscribe prompts)
- Groups paragraphs under their nearest heading
- Orphan paragraphs before the first heading go into an "Introduction" section (max 3 paragraphs)

### Cleaned HTML (`clean_html: true`)

Allowed tags: `div`, `section`, `article`, `p`, `h1`-`h6`, `ul`, `ol`, `li`, `a`, `span`, `strong`, `em`, `b`, `i`, `u`, `small`, `sup`, `sub`, `code`, `img`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, `br`, `hr`.

Allowed attributes: `href` (on `a`), `src` and `alt` (on `img`). All other attributes are stripped.

### Failure Reasons

| reason | Meaning | HTTP status in response |
|--------|---------|------------------------|
| INPUT | Invalid or missing URL | `null` |
| TIMEOUT | Fetch or processing exceeded time limit | `null` |
| NETWORK | Connection / fetch failure | Included if available |
| BLOCKED | 401/403/429/451/503 and Jina Reader fallback failed | Included |
| UNSUPPORTED_MIME | Non-HTML/XML content type | Included |
| EXTRACT_FAIL | No readable content extracted | `null` |
| EMPTY | Page returned empty or suspicious content | Included if available |
| BANNED | Abuse detection triggered | `null` (429 HTTP response) |
| GLOBAL_LIMIT | Server-wide rate limit | `null` (429 HTTP response) |

**Important**: All failure responses return HTTP 200 with `ok: false` — except rate limiting which returns HTTP 429. This is by design so n8n/automation workflows don't treat failures as errors.

### Internal Jina Reader Fallback

The scraper automatically falls back to `r.jina.ai` when:
- Direct fetch returns no response
- HTTP 401, 403, 429, 451, 503
- Soft block detected (Cloudflare, captcha, "enable JavaScript", "just a moment", etc.)
- HTML body < 200 chars (suspiciously short)

When the Jina Reader fallback succeeds, the response is formatted to match the standard response structure. The `flat_outline` will contain the reader's Markdown output.

---

## Abuse Detection

The service uses pattern-based abuse detection (not simple rate limiting):

### What Triggers It

| Signal | Threshold | Window |
|--------|-----------|--------|
| Same-domain concentration | 20+ hits to one domain AND 80%+ of all requests | 5 minutes |
| Extreme volume | 120+ requests/minute from one IP | 1 minute |
| Global limit | 200+ requests/minute across all IPs | 1 minute |

### Escalation

1. **First 2 violations**: Soft reject (429) with 5s retry-after
2. **Subsequent violations**: Escalating bans — 60s, 120s, 240s, 480s... up to 1 hour max
3. **Decay**: Violation count halves after 10 minutes of no new violations
4. **Reset**: Bans and violations cleared on service restart

### What Does NOT Trigger It

- High throughput to diverse domains (e.g., research workflow reading 50 different sites in a burst)
- Bursts of requests that stay under the absolute thresholds
- Normal automation patterns (n8n workflows, agent tool calls)

---

## Backup: Jina Reader (r.jina.ai)

**When to use**: Page scraper returns `ok: false` with TIMEOUT, BLOCKED, NETWORK, EXTRACT_FAIL, or EMPTY.

### Basic Usage

```http
GET https://r.jina.ai/{target_url}
```

Example: `GET https://r.jina.ai/https://example.com/article`

### Response Format

Returns plain text or Markdown. Common preamble format:
```
title: Article Title
url source: https://example.com/article

markdown content
---
# Article Title
...
```

### Query Parameters (common)

- `x-output-format`: `markdown`, `html`, `text`
- `x-wait-for`: selector to wait for (JS-heavy pages)
- `x-timeout`: seconds (default ~30)
- `tokenBudget`: max tokens
- `withGeneratedAlt`: image alt text generation

### Headers

- `Authorization: Bearer {JINA_API_KEY}` — higher rate limits
- `X-Return-Format`: response format preference

### Mapping to Page Scraper Format

```python
def parse_reader_response(text):
    title, source_url, content = None, None, text
    lines = text.splitlines()
    for line in lines[:10]:
        low = line.lower()
        if low.startswith("title:"):
            title = line.split(":", 1)[1].strip()
        elif "source" in low and "url" in low:
            source_url = line.split(":", 1)[1].strip()
    for i, line in enumerate(lines):
        if "markdown content" in line.lower():
            content = "\n".join(lines[i+1:]).strip()
            break
    return {"title": title, "url": source_url, "flat_outline": content}
```

---

## Backup: Other Options

### 1. Firecrawl / ScrapingBee

Paid APIs with JS rendering. Use when Jina Reader and page scraper both fail on JS-heavy or protected sites.

### 2. Trafilatura (local)

```python
import trafilatura
html = requests.get(url).text
text = trafilatura.extract(html, favor_precision=False)
```

### 3. Mozilla Readability

```python
from readability import Document
doc = Document(html)
title = doc.title()
content = doc.summary()
```

### 4. Playwright / Puppeteer

For sites that require full browser execution or bypass aggressive bot protection.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5000` | Server port |
| `READ_HARD_TIMEOUT_SECONDS` | `8` (fast) / `25` (slow) | Maximum wall-clock time per request |
| `RATE_LIMIT_GLOBAL_RPM` | `200` | Global requests per minute limit |
| `RATE_LIMIT_EXTREME_RPM` | `120` | Per-IP extreme volume threshold |
| `MIN_DOMAIN_DELAY_MS` | `0` | Minimum delay between requests to same domain (outbound) |
| `HONOR_ROBOTS_CRAWL_DELAY` | `false` | Respect robots.txt Crawl-delay directives |
