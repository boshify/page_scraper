from flask import Flask, request, jsonify
import cloudscraper
import trafilatura
import random
import os
import time
import re
from bs4 import BeautifulSoup, Comment
from urllib.parse import urljoin

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
# Soft responses (always HTTP 200 for n8n)
# ────────────────────────────────────────────────────────────────────────────────
def soft_fail(url, message, reason, http_status=None, extra=None):
    payload = {
        "ok": False,
        "reason": reason,   # INPUT | NETWORK | BLOCKED | TIMEOUT | EMPTY | EXTRACT_FAIL | UNSUPPORTED_MIME | UNKNOWN
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
# Fetch + basic parse
# ────────────────────────────────────────────────────────────────────────────────
def fetch_once(url, headers, timeout=8):
    """Single try (~8s) to fit under 10s n8n timeout."""
    scraper = cloudscraper.create_scraper()
    return scraper.get(url, headers=headers, timeout=timeout)

def clean_dom_full(html):
    """Light global cleaning (used for meta + fallback)."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
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

# ────────────────────────────────────────────────────────────────────────────────
# Outline strictly from <body>
# ────────────────────────────────────────────────────────────────────────────────
def looks_menuish(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 6:
        short_lines = sum(1 for ln in lines if len(ln) <= 20)
        if short_lines / max(1, len(lines)) >= 0.7:
            return True
    tokens = re.split(r"[,\|/·•]\s*", text)
    if len(tokens) >= 8:
        short_tokens = sum(1 for t in tokens if len(t.strip()) <= 12)
        if short_tokens / max(1, len(tokens)) >= 0.75:
            return True
    return False

def looks_boilerplate(text: str) -> bool:
    t = text.lower()
    blacklist = [
        "you are now leaving", "privacy policy", "terms of service",
        "article continues after advertisement", "cookie", "consent",
        "subscribe", "newsletter", "login", "sign up", "join now"
    ]
    return any(b in t for b in blacklist)

def extract_outline_from_body(body_root):
    """Group paragraphs under H2–H6 from <body> only; cap intro; skip menu-ish/boilerplate."""
    # Normalize lists/blockquote -> p
    for tag in body_root.find_all(["li", "blockquote"]):
        tag.name = "p"

    blocks = []
    for el in body_root.find_all(["h2","h3","h4","h5","h6","p"]):
        if el.name == "p":
            txt = el.get_text(" ", strip=True)
            if len(txt) >= 2 and not looks_menuish(txt) and not looks_boilerplate(txt):
                blocks.append({"tag": "p", "level": 0, "text": txt})
        else:
            txt = el.get_text(" ", strip=True)
            if txt:
                blocks.append({"tag": el.name, "level": int(el.name[1]), "text": txt})

    sections, current = [], None
    intro_used, INTRO_LIMIT = 0, 3
    seen = set()

    def add_para(s, p):
        key = p.strip()
        if key in seen:
            return
        seen.add(key)
        s["paragraphs"].append(p)

    def flush():
        nonlocal current
        if current:
            sections.append(current)
            current = None

    for b in blocks:
        if b["tag"] == "p":
            if not current:
                if intro_used >= INTRO_LIMIT:
                    continue
                current = {"level": 2, "title": "Introduction", "paragraphs": []}
            if current["title"] == "Introduction" and intro_used >= INTRO_LIMIT:
                continue
            add_para(current, b["text"])
            if current["title"] == "Introduction":
                intro_used += 1
        else:
            flush()
            current = {"level": b["level"], "title": b["text"], "paragraphs": []}
    flush()

    # Flat outline
    lines = []
    for s in sections:
        lines.append(f"H{s['level']}: {s['title']}")
        for p in s["paragraphs"]:
            lines.append(p)
        lines.append("")
    flat_outline = "\n".join(lines).strip()
    return sections, flat_outline

# ────────────────────────────────────────────────────────────────────────────────
# Stripped HTML from <body>: classic tags only, minimal attributes
# ────────────────────────────────────────────────────────────────────────────────
ALLOWED_TAGS = {
    # structure
    "div", "section", "article",
    # text blocks
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    # lists
    "ul", "ol", "li",
    # inline/semantics
    "a", "span", "strong", "em", "b", "i", "u", "small", "sup", "sub", "code",
    # media
    "img",
    # line breaks / rules
    "br", "hr",
}

def sanitize_attrs(tag):
    # remove all attributes by default
    tag.attrs = {}
    # selectively re-add allowed attrs per tag
    if tag.name == "a":
        href = tag.get("href") or ""
        # BeautifulSoup lost attrs after clearing; read from original? Use data we saved.
        # Instead: we pass original attrs via dict on the tag before clearing? Simpler: skip.
        # Workaround: we use .get("data-orig-href") if present (we'll stash it beforehand).
        orig = tag.get("data-orig-href")
        href = orig or href
        if href and href.lower().startswith(("http://", "https://", "#", "/")):
            tag.attrs["href"] = href
    elif tag.name == "img":
        src = tag.get("data-orig-src") or tag.get("src") or ""
        if src.lower().startswith(("http://", "https://", "data:image")):
            tag.attrs["src"] = src
        alt = tag.get("data-orig-alt") or tag.get("alt")
        if alt:
            tag.attrs["alt"] = alt

def strip_html_from_body(body_root) -> str:
    """Return inner HTML of <body> with only classic tags and minimal attributes."""
    # Clone a body-only soup so we can safely mutate
    body_clone = BeautifulSoup(str(body_root), "lxml").body or BeautifulSoup(str(body_root), "lxml")

    # Remove unwanted elements entirely
    for tag in body_clone(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    for c in body_clone.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()

    # Stash original href/src/alt before stripping attributes
    for a in body_clone.find_all("a"):
        if a.has_attr("href"):
            a.attrs["data-orig-href"] = a["href"]
    for img in body_clone.find_all("img"):
        if img.has_attr("src"):
            img.attrs["data-orig-src"] = img["src"]
        if img.has_attr("alt"):
            img.attrs["data-orig-alt"] = img["alt"]

    # Enforce tag whitelist:
    # - if tag not allowed, unwrap (keep children text)
    # - if allowed, drop all attrs then re-apply minimal allowed ones
    for el in list(body_clone.find_all(True)):
        if el.name not in ALLOWED_TAGS:
            el.unwrap()
        else:
            sanitize_attrs(el)

    # Remove any helper data-* we added
    for el in body_clone.find_all(True):
        for k in list(el.attrs.keys()):
            if k.startswith("data-"):
                del el.attrs[k]

    # Return inner HTML of <body> if present, else whole clone
    if getattr(body_clone, "name", None) == "body":
        return "".join(str(c) for c in body_clone.contents).strip()
    return str(body_clone)

# ────────────────────────────────────────────────────────────────────────────────
def clamp(s, n):
    if not s:
        return s
    return s if len(s) <= n else (s[:n] + "... [truncated]")

@app.route("/")
def home():
    return "Trafilatura scraper is running."

@app.route("/read", methods=["POST"])
def read_page():
    data = request.get_json(force=True, silent=True) or {}
    url = data.get("url")
    max_chars = int(data.get("max_chars", 5000))
    include_full_text = bool(data.get("include_full_text", True))  # legacy default
    return_html = bool(data.get("return_html", False))             # new optional param

    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return soft_fail(url, "Invalid or missing URL", reason="INPUT",
                         extra={"content": "", "length": 0})

    headers = {
        "User-Agent": get_random_user_agent(),
        "Referer": "https://www.google.com",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = fetch_once(url, headers=headers, timeout=8)
        if not resp:
            return soft_fail(url, "Network error", reason="NETWORK",
                             extra={"content": "", "length": 0})

        if resp.status_code in (401, 403, 429, 451):
            return soft_fail(url, "Crawlers are blocked", reason="BLOCKED",
                             http_status=resp.status_code,
                             extra={"content": "", "length": 0})

        if resp.status_code != 200:
            return soft_fail(url, f"Failed to load page (HTTP {resp.status_code})", reason="NETWORK",
                             http_status=resp.status_code,
                             extra={"content": "", "length": 0})

        ctype = resp.headers.get("Content-Type", "").lower()
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return soft_fail(url, "Unsupported MIME type", reason="UNSUPPORTED_MIME",
                             http_status=resp.status_code,
                             extra={"content": "", "length": 0, "content_type": ctype})

        html = resp.text or ""
        if len(html) < 500:
            return soft_fail(url, "Empty or suspicious page", reason="EMPTY",
                             http_status=resp.status_code,
                             extra={"content": "", "length": 0})

        soup_full = clean_dom_full(html)
        body = soup_full.body
        use_body_only = body is not None

        # Meta uses full soup (safe regardless)
        meta = get_meta(soup_full, url)

        # Main text: body-only if available, else fallback to full
        if use_body_only:
            body_html = str(body)
            main_text = trafilatura.extract(body_html) or ""
        else:
            main_text = trafilatura.extract(html) or ""

        main_text = (main_text or "").strip()

        # Outline: from body when present; else fallback
        if use_body_only:
            outline_sections, flat_outline = extract_outline_from_body(body)
        else:
            # fallback: build a pseudo-body soup for outline
            outline_sections, flat_outline = extract_outline_from_body(soup_full)

        if not main_text and not outline_sections:
            return soft_fail(url, "Could not extract readable content", reason="EXTRACT_FAIL",
                             extra={"content": "", "length": 0})

        result = {
            "url": url,
            "canonical": meta.get("canonical") or url,
            "title": meta.get("title"),
            "meta_description": meta.get("meta_description"),
            "h1": meta.get("h1"),
            "lang": meta.get("lang"),
            "robots": meta.get("robots"),
            "outline_sections": outline_sections[:200],
            "flat_outline": clamp(flat_outline, max_chars),
            "lengths": {
                "main_text": len(main_text or ""),
                "flat_outline": len(flat_outline or ""),
            },
        }

        # Legacy fields ALWAYS present (no duplicates elsewhere)
        if include_full_text:
            result["content"] = clamp(main_text, max_chars)
        else:
            # still keep 'content' for legacy callers, but keep it lightweight
            result["content"] = clamp(main_text[: min(max_chars, 800)], 800)
        result["length"] = len(main_text or "")

        # Optional stripped HTML (independent of everything else)
        if return_html:
            try:
                if use_body_only:
                    result["html"] = clamp(strip_html_from_body(body), max_chars)
                else:
                    # if no <body>, run stripper on the whole cleaned soup
                    result["html"] = clamp(strip_html_from_body(soup_full), max_chars)
            except Exception:
                # If HTML stripping fails, still return text successfully
                result["html"] = ""

        return soft_ok(result)

    except Exception as e:
        msg = (str(e) or "Unexpected error")
        low = msg.lower()
        if "timed out" in low or "timeout" in low:
            return soft_fail(url, "Timeout fetching page", reason="TIMEOUT",
                             extra={"content": "", "length": 0})
        if "captcha" in low or "cloudflare" in low:
            return soft_fail(url, "Crawlers are blocked", reason="BLOCKED",
                             extra={"content": "", "length": 0})
        return soft_fail(url, msg, reason="UNKNOWN",
                         extra={"content": "", "length": 0})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
