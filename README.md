# page_scraper
scrapes plain text of web pages

## /read endpoint

Send a JSON payload to `POST /read` with:

- `url` (required): the page to scrape.
- `max_chars` (optional): length limiter for returned strings (default `5000`).
- `return_html` (optional): include HTML in the response when `true`.
- `Clean HTML` (optional): when `true` (default), returned HTML is cleaned; when `false`, the original body HTML is returned unmodified. `clean_html` can also be used as a backwards-compatible key.
- `is_sitemap` (optional): when `true`, the endpoint returns **sitemap only** — a JSON object with a single list of URLs. No content extraction is performed. Works with XML sitemaps (e.g. `sitemap.xml`) and HTML pages (extracts all links). Response format: `{"ok": true, "urls": ["https://...", ...]}`.
