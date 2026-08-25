# page_scraper
scrapes plain text of web pages

## /read endpoint

Send a JSON payload to `POST /read` with:

- `url` (required): the page to scrape.
- `max_chars` (optional): length limiter for returned strings (default `5000`).
- `return_html` (optional): include HTML in the response when `true`.
- `Clean HTML` (optional): when `true` (default), returned HTML is cleaned; when `false`, the original body HTML is returned unmodified. `clean_html` can also be used as a backwards-compatible key.
- `is_sitemap` (optional): when `true`, the endpoint returns **sitemap only** — a JSON object with a single list of URLs. No content extraction is performed. Works with XML sitemaps (e.g. `sitemap.xml`) and HTML pages (extracts all links). Response format: `{"ok": true, "urls": ["https://...", ...]}`.

## Authentication (API key)

Every endpoint except `/` (the health check) requires an API key. Requests without a
valid key are rejected with `401` and never reach the scraper.

### Railway setup

In your Railway service → **Variables**, add:

| Variable | Required | Description |
| --- | --- | --- |
| `API_KEYS` | yes | Comma-separated keys. Each entry is `key` or `label:key`, e.g. `n8n:sk_live_abc123,jonathan:sk_live_def456`. Labels are for logging only — they are not secret. |
| `API_KEY` | no | Single-key alias, merged with `API_KEYS`. |
| `REQUIRE_API_KEY` | no | Set to `false` to turn gating off entirely. Defaults to `true`. |

Key values must not contain a comma or a colon. Generate one with:

```bash
python3 -c "import secrets; print('sk_live_' + secrets.token_urlsafe(32))"
```

Changing the variable restarts the service, so a revoked key stops working within
seconds of removing it from `API_KEYS`.

**Fail-closed:** if `REQUIRE_API_KEY` is left on (the default) and `API_KEYS` is
empty, every request is rejected with `503 SERVER_MISCONFIGURED` — the service is
never accidentally public. Set `API_KEYS` before or at deploy time.

### Sending the key

Any one of these works (headers are preferred — query strings tend to end up in
proxy logs):

```bash
# Authorization header (recommended)
curl -X POST https://your-app.up.railway.app/read \
  -H "Authorization: Bearer sk_live_abc123" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# X-API-Key header
curl -X POST ... -H "X-API-Key: sk_live_abc123" ...

# JSON body field
curl -X POST ... -d '{"url": "https://example.com", "api_key": "sk_live_abc123"}'

# Query string
curl -X POST "https://your-app.up.railway.app/read?api_key=sk_live_abc123" ...
```

Accepted locations, in the order they are checked: `Authorization: Bearer <key>`
(a bare `Authorization: <key>` also works), the `X-API-Key` / `X-Auth-Token` /
`Api-Key` headers, the `api_key` / `apikey` query parameter, and the `api_key`,
`apiKey`, or `API Key` field in the JSON body.

### Error responses

| Status | `reason` | Meaning |
| --- | --- | --- |
| `401` | `MISSING_API_KEY` | No key supplied. |
| `401` | `INVALID_API_KEY` | Key not in `API_KEYS`. |
| `503` | `SERVER_MISCONFIGURED` | Gating on, but no keys configured on the server. |

Keys are compared with `hmac.compare_digest`, so an invalid key can't be recovered
by timing the response. Keys are never written to logs — each request logs only the
key's `label`, which also becomes the identity used by the abuse detector, so rate
limits and bans apply per key rather than per IP.
