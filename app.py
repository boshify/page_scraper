from flask import Flask, request, jsonify
import cloudscraper
import trafilatura
import random
import os
import time
from bs4 import BeautifulSoup, Comment
from urllib.parse import urljoin

# ────────────────────────────────────────────────────────────────────────────────
# App setup
# ────────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:92.0) Gecko/20100101 Firefox/92.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.101 Safari/537.36",
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

# ────────────────────────────────────────────────────────────────────────────────
# Soft result helpers (keep HTTP 200 for n8n)
# ────────────────────────────────────────────────────────────────────────────────
def soft_fail(url, message, reason, http_status=None, extra=None):
    """
    Always HTTP 200. n8n can branch on $.json.ok === true/false without throwing.
    reason: BLOCKED | EMPTY | EXTRACT_FAIL | TIMEOUT | NETWORK | INPUT | UNKNOWN | UNSUPPORTED_MIME
    """
    payload = {
        "ok": False,
        "reason": reason,
        "message": message,
        "http_status": http_status,
        "url": url,
    }
    if extra:
        payload.update(extra)
    return jsonify(payload), 200

def soft_ok(data):
    data = data or {}
    data["ok"] = True
    return jsonify(data), 200

# ────────────────────────────────────────────────────────────────────────────────
# Fetch + parsing utilities
# ────────────────────────────────────────────────────────────────────────────────
def fetch_with_retries(url, headers, tries=2, timeout=12):
    scraper = cloudscraper.create_scraper()
    last_exc = None
    for i in range(tries):
        try:
            resp = scraper.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return resp
            # Bail early if clearly blocked/rate-limited/geo-blocked
            if resp.status_code in (401, 403, 429, 451):
                return resp
            time.sleep(0.5 + i * 0.6)
        except Exception as e:
            last_exc = e
            time.sleep(0.5 + i * 0.6)
    if last_exc:
        raise last_exc
    return None

def clean_dom(html):
    soup = BeautifulSoup(html, "lxml")
    # Remove noise
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    for tag in soup.find_all(["nav", "header", "footer", "aside"]):
        tag.decompose()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    return soup

def get_meta(soup, url):
    title = (soup.title.string.strip() if soup.title and soup.title.string else None)

    md = soup.find("meta", attrs={"name": "description"})
    meta_description = md["content"].strip() if md and md.get("content") else None

    link = soup.find("link", rel=lambda x: x and "canonical" in x)
    canonical = urljoin(url, link["href"]) if link and link.get("href") else url

    robots = None
    mr = soup.find("meta", attrs={"name": "robots"})
    if mr and mr.get("content"):
        robots = mr["content"].strip()

    lang = soup.html.get("lang").strip() if soup.html and soup.html.get("lang") else None

    h1_el = soup.find("h1")
    h1_text = h1_el.get_text(strip=True) if h1_el else None

    return {
        "title": title,
        "meta_description": meta_description,
        "canonical": canonical,
        "robots": robots,
        "lang": lang,
        "h1": h1_text,
    }

def extract_outline(soup):
    """
    Build sections from H2–H6 and paragraphs.
    Intro paragraphs (before the first heading) are grouped under 'Introduction' (H2).
    Returns: (sections_list, flat_outline_string)
    """
    body = soup.body or soup

    # Normalize lists/blockquote to paragraphs (to mimic your Apps Script)
    for tag in body.find_all(["li", "blockquote"]):
        tag.name = "p"

    blocks = []
    for el in body.find_all(["h2", "h3", "h4", "h5", "h6", "p"]):
        if el.name == "p":
            txt = el.get_text(" ", strip=True)
            if len(txt) >= 2:
                blocks.append({"tag": "p", "level": 0, "text": txt})
        else:
            txt = el.get_text(" ", strip=True)
            if txt:
                blocks.append({"tag": el.name, "level": int(el.name[1]), "text": txt})

    sections = []
    current = None

    def flush():
        nonlocal current
        if current:
            sections.append(current)
            current = None

    for b in blocks:
        if b["tag"] == "p":
            if not current:
                current = {"level": 2, "title": "Introduction", "paragraphs": []}
            current["paragraphs"].append(b["text"])
        else:
            flush()
            current = {"level": b["level"], "title": b["text"], "paragraphs": []}

    flush()

    # Flat outline string
    lines = []
    for s in sections:
        lines.append(f"H{s['level']}: {s['title']}")
        for p in s["paragraphs"]:
            lines.append(p)
        lines.append("")
    flat_outline = "\n".join(lines).strip()
    return sections, flat_outline

def clamp(s, n):
    if not s:
        return s
    return s if len(s) <= n else (s[:n] + "... [truncated]")

# ────────────────────────────────────────────────────────────────────────────────
# Routes
# ────────────────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return "Trafilatura scraper is running."

@app.route("/read", methods=["POST"])
def read_page():
    data = request.get_json(force=True, silent=True) or {}
    url = data.get("url")
    max_chars = int(data.get("max_chars", 5000))
    include_full_text = bool(data.get("include_full_text", False))

    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return soft_fail(url, "Invalid or missing URL", reason="INPUT")

    headers = {
        "User-Agent": get_random_user_agent(),
        "Referer": "https://www.google.com",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = fetch_with_retries(url, headers=headers, tries=2, timeout=12)
        if not resp:
            return soft_fail(url, "Network error", reason="NETWORK")

        # Friendly blocked mapping
        if resp.status_code in (401, 403, 429, 451):
            return soft_fail(url, "Crawlers are blocked", reason="BLOCKED", http_status=resp.status_code)

        if resp.status_code != 200:
            return soft_fail(url, f"Failed to load page (HTTP {resp.status_code})", reason="NETWORK", http_status=resp.status_code)

        # Some sites return non-HTML; bail early
        ctype = resp.headers.get("Content-Type", "").lower()
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return soft_fail(url, "Unsupported MIME type", reason="UNSUPPORTED_MIME", http_status=resp.status_code, extra={"content_type": ctype})

        html = resp.text or ""
        if len(html) < 500:
            return soft_fail(url, "Empty or suspicious page", reason="EMPTY", http_status=resp.status_code)

        # Parse once, reuse for meta + outline
        soup = clean_dom(html)
        meta = get_meta(soup, url)

        # Main readable text
        main_text = trafilatura.extract(html) or ""
        main_text = main_text.strip()

        # Heading outline
        outline_sections, flat_outline = extract_outline(soup)

        if not main_text and not outline_sections:
            return soft_fail(url, "Could not extract readable content", reason="EXTRACT_FAIL")

        result = {
            "url": url,
            "canonical": meta.get("canonical") or url,
            "title": meta.get("title"),
            "meta_description": meta.get("meta_description"),
            "h1": meta.get("h1"),
            "lang": meta.get("lang"),
            "robots": meta.get("robots"),
            "outline_sections": outline_sections[:200],  # keep response light
            "flat_outline": clamp(flat_outline, max_chars),
            "lengths": {
                "main_text": len(main_text or ""),
                "flat_outline": len(flat_outline or ""),
            },
        }

        if include_full_text:
            result["content"] = clamp(main_text, max_chars)
        else:
            # Provide a small teaser for lightweight flows
            result["content_preview"] = clamp(main_text[: min(max_chars, 800)], 800)

        return soft_ok(result)

    except Exception as e:
        msg = (str(e) or "Unexpected error")
        low = msg.lower()
        if "timed out" in low or "timeout" in low:
            return soft_fail(url, "Timeout fetching page", reason="TIMEOUT")
        if "captcha" in low or "cloudflare" in low:
            return soft_fail(url, "Crawlers are blocked", reason="BLOCKED")
        return soft_fail(url, msg, reason="UNKNOWN")

# ────────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
