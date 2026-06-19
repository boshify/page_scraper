# Page Scraper Examples

## Basic Article Scrape

```json
POST https://read.aiseoengine.studio/read
Content-Type: application/json

{
  "url": "https://blog.example.com/post/how-to-scrape"
}
```

Response (key fields):
```json
{
  "ok": true,
  "title": "How to Scrape Web Pages",
  "h1": "How to Scrape Web Pages",
  "flat_outline": "# How to Scrape Web Pages\n\nWeb scraping is the process of...",
  "length": 3421,
  "lengths": {"main_text": 3421, "flat_outline": 4102}
}
```

## Longer Content (increase max_chars)

```json
{
  "url": "https://example.com/long-article",
  "max_chars": 15000
}
```

Check `lengths.flat_outline` vs `max_chars` to know if content was truncated.

## Sitemap URL Extraction

```json
{
  "url": "https://example.com/sitemap.xml",
  "is_sitemap": true
}
```

Response:
```json
{"ok": true, "urls": ["https://example.com/page1", "https://example.com/page2"]}
```

Also works with HTML pages — returns all `<a href>` URLs:
```json
{
  "url": "https://example.com/resources",
  "is_sitemap": true
}
```

## HTML Output (cleaned)

```json
{
  "url": "https://example.com/article",
  "return_html": true,
  "clean_html": true
}
```

Returns stripped HTML with only content tags and href/src/alt attributes.

## Raw Body HTML

```json
{
  "url": "https://example.com/article",
  "return_html": true,
  "clean_html": false
}
```

Returns the full `<body>` HTML as-is.

## Slow / Complex Sites

```json
{
  "url": "https://heavy-js-site.com/article",
  "fast_mode": false
}
```

Gives ~15s fetch timeout, 3 retries, ~25s hard limit.

## SEO Analysis

```json
{
  "url": "https://competitor.com/target-page",
  "max_chars": 15000,
  "return_html": true,
  "clean_html": true
}
```

Use the response for:
- `title`, `meta_description`, `h1`, `canonical`, `robots`, `lang` — on-page SEO signals
- `schema_markup` — structured data (FAQ, Product, Article, etc.)
- `flat_outline` — content structure and heading hierarchy
- `tables` — comparison tables, pricing, specifications
- `html` — tag-level structure analysis

---

## Handling Failures

### Check `ok` field first

```python
response = requests.post("https://read.aiseoengine.studio/read", json={"url": target_url})
data = response.json()

if data["ok"]:
    content = data["flat_outline"]
    tables = data["tables"]
else:
    reason = data["reason"]
    # Route to fallback based on reason
```

### Fallback Decision Tree

```python
if data["reason"] == "INPUT":
    # Bad URL — fix it, don't retry
    pass
elif data["reason"] == "UNSUPPORTED_MIME":
    # Not an HTML page (PDF, image, etc.) — handle differently
    pass
elif data["reason"] in ("TIMEOUT", "NETWORK", "BLOCKED", "EXTRACT_FAIL", "EMPTY"):
    # Try Jina Reader as backup
    jina_resp = requests.get(f"https://r.jina.ai/{target_url}", timeout=30)
    if jina_resp.status_code == 200:
        content = jina_resp.text
elif data["reason"] in ("BANNED", "GLOBAL_LIMIT"):
    # Rate limited — wait and retry
    retry_after = data.get("retry_after", 5)
    time.sleep(retry_after)
```

---

## n8n / Automation Patterns

### Basic HTTP Request Tool Setup

- **Method**: POST
- **URL**: `https://read.aiseoengine.studio/read`
- **Headers**: `Content-Type: application/json`
- **Body**: `{"url": "{{ $fromAI('url') }}"}`
- **Timeout**: 60000 (60s — gives room for the scraper's internal timeouts)

### With Jina Fallback (IF node)

1. **HTTP Request** → POST to page scraper
2. **IF node** → Check `{{ $json.ok }}` is `true`
3. **True branch** → Use `{{ $json.flat_outline }}` for content
4. **False branch** → GET `https://r.jina.ai/{{ $json.url }}` as fallback

### Recommended Settings for n8n

Keep `fast_mode: true` (default) to stay well under n8n's HTTP timeout. The scraper's 8s hard limit ensures fast failures rather than hanging.

---

## Backup: Jina Reader (cURL)

When scraper fails:

```bash
curl "https://r.jina.ai/https://example.com/article"
```

With API key:

```bash
curl -H "Authorization: Bearer $JINA_TOKEN" "https://r.jina.ai/https://example.com/article"
```

## Backup: Jina Reader (Python)

```python
import requests

def fallback_jina(url: str) -> dict:
    reader_url = f"https://r.jina.ai/{url}"
    r = requests.get(reader_url, timeout=30)
    if r.status_code != 200:
        return {"ok": False, "reason": "JINA_FAILED"}
    text = r.text
    lines = text.splitlines()
    title, source_url, content = None, None, text
    for line in lines[:10]:
        low = line.lower()
        if low.startswith("title:"):
            title = line.split(":", 1)[1].strip()
        elif "url source" in low or "source url" in low:
            source_url = line.split(":", 1)[1].strip()
    for i, line in enumerate(lines):
        if "markdown content" in line.lower():
            content = "\n".join(lines[i+1:]).strip()
            break
    return {
        "ok": True,
        "title": title,
        "url": source_url or url,
        "flat_outline": content,
        "length": len(content),
    }
```
