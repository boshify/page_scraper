from flask import Flask, request, jsonify
import cloudscraper
import trafilatura
import random
import os
import re
import json
from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from urllib.parse import urljoin

# Robust decoding + mojibake repair
from charset_normalizer import from_bytes  # pip install charset-normalizer
from ftfy import fix_text                  # pip install ftfy

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
# Fetch + robust decode
# ────────────────────────────────────────────────────────────────────────────────
def fetch_once(url, headers, timeout=8):
    scraper = cloudscraper.create_scraper()
    return scraper.get(url, headers=headers, timeout=timeout)

def robust_decode(content_bytes: bytes, fallback_text: str = "") -> str:
    try:
        best = from_bytes(content_bytes).best()
        txt = str(best) if best is not None else (fallback_text or "")
    except Exception:
        txt = fallback_text or ""
    return fix_text(txt)

# ────────────────────────────────────────────────────────────────────────────────
# Body slicer: exact <body ...>...</body> from raw HTML
# ────────────────────────────────────────────────────────────────────────────────
BODY_OPEN_RE = re.compile(r"<body\b[^>]*>", re.IGNORECASE | re.DOTALL)
BODY_CLOSE_RE = re.compile(r"</body\s*>", re.IGNORECASE | re.DOTALL)

def slice_body_html(raw_html: str) -> str | None:
    m_open = BODY_OPEN_RE.search(raw_html)
    if not m_open:
        return None
    start = m_open.start()
    m_close = BODY_CLOSE_RE.search(raw_html, m_open.end())
    end = m_close.end() if m_close else len(raw_html)
    return raw_html[start:end]

# ────────────────────────────────────────────────────────────────────────────────
# Light cleaners and metadata
# ────────────────────────────────────────────────────────────────────────────────
def clean_dom_full(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    return soup

def fix_str(s):
    return fix_text(s) if isinstance(s, str) else s

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
        "title": fix_str(title),
        "meta_description": fix_str(meta_description),
        "canonical": canonical,
        "robots": robots,
        "lang": lang,
        "h1": fix_str(h1_text),
    }

# ────────────────────────────────────────────────────────────────────────────────
# Markdown helpers (HTML -> Markdown)
# ────────────────────────────────────────────────────────────────────────────────
def html_inline_to_md(node) -> str:
    if isinstance(node, NavigableString):
        return fix_text(str(node))
    if not isinstance(node, Tag):
        return ""
    name = node.name.lower()
    inner = "".join(html_inline_to_md(child) for child in node.children)
    if name == "a":
        href = (node.get("href") or "").strip()
        text = inner or fix_text(node.get_text(strip=True))
        return f"[{text}]({href})" if href else text
    if name in ("strong", "b"):
        return f"**{inner}**"
    if name in ("em", "i"):
        return f"*{inner}*"
    if name == "code":
        return f"`{inner}`"
    if name == "img":
        src = (node.get("src") or "").strip()
        alt = fix_text(node.get("alt") or "")
        return f"![{alt}]({src})" if src else ""
    return inner

def html_block_to_md(tag: Tag) -> str:
    name = tag.name.lower()
    if name == "blockquote":
        text = "".join(html_inline_to_md(c) for c in tag.children).strip()
        lines = [fix_text(ln) for ln in re.split(r"\r?\n+", text) if ln.strip()]
        return "\n".join(["> " + ln for ln in lines])
    if name == "li":
        text = "".join(html_inline_to_md(c) for c in tag.children).strip()
        if tag.find_parent("ol"):
            return f"1. {text}"
        return f"- {text}"
    text = "".join(html_inline_to_md(c) for c in tag.children).strip()
    return text

def heading_md(level_num: int, title: str) -> str:
    level_num = max(1, min(6, int(level_num)))
    return f'{"#" * level_num} {fix_text(title)}'.strip()

# ────────────────────────────────────────────────────────────────────────────────
# Content focusing (within <body>): pick main/article or best content container
# ────────────────────────────────────────────────────────────────────────────────
CHROME_ROLES = ['navigation', 'banner', 'contentinfo', 'complementary', 'search']
CHROME_KEYWORDS = [
    "nav","menu","breadcrumb","header","footer","sidebar","subscribe","newsletter",
    "cookie","consent","modal","popup","promo","ad-","ads","advert","banner",
    "share","social","signup","login"
]

def looks_chrome(el: Tag) -> bool:
    attrs = " ".join([el.get("id",""), " ".join(el.get("class", [])), el.get("role","")]).lower()
    if any(r in attrs for r in CHROME_ROLES):
        return True
    return any(k in attrs for k in CHROME_KEYWORDS)

def drop_chrome_blocks(root: Tag):
    # remove semantic chrome
    for t in root.find_all(["header","footer","nav","aside"]):
        t.decompose()
    # remove role/keyword chrome
    for el in list(root.find_all(True)):
        try:
            if looks_chrome(el) and len(el.get_text(strip=True)) < 8000:
                el.decompose()
        except Exception:
            continue

def choose_content_root(body_root: Tag) -> Tag:
    # 1) Prefer <main>
    main = body_root.find("main")
    if main:
        return main
    # 2) Else prefer <article>
    article = body_root.find("article")
    if article:
        return article
    # 3) Else pick element with most <p> descendants (good heuristic)
    best, best_p = body_root, 0
    for el in body_root.find_all(True):
        # Skip obvious chrome containers
        if el.name in ("header","footer","nav","aside"):
            continue
        if looks_chrome(el):
            continue
        pcount = len(el.find_all("p"))
        if pcount > best_p:
            best, best_p = el, pcount
    return best or body_root

def focus_body_html(body_html: str) -> str:
    """Body HTML → BeautifulSoup → drop chrome → choose content root → return focused HTML string."""
    soup = BeautifulSoup(body_html, "lxml")
    body = soup.body or soup
    drop_chrome_blocks(body)
    root = choose_content_root(body)
    # Return just the chosen root's inner HTML (not the whole body)
    return "".join(str(c) for c in root.contents) if root else str(body)

# ────────────────────────────────────────────────────────────────────────────────
# Outline from focused body -> sections + flat Markdown
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

def extract_outline_from_focused_body(focused_body_html: str):
    soup = BeautifulSoup(focused_body_html, "lxml")
    root = soup.body or soup
    allowed_blocks = ["h1","h2","h3","h4","h5","h6","p","li","blockquote"]

    blocks = []
    for el in root.find_all(allowed_blocks):
        name = el.name.lower()
        if name in ("p", "li", "blockquote"):
            md_line = html_block_to_md(el).strip()
            if len(md_line) >= 2 and not looks_menuish(md_line) and not looks_boilerplate(md_line):
                blocks.append({"tag": name, "text": md_line})
        else:
            title = fix_text(el.get_text(" ", strip=True))
            if title:
                level_num = int(name[1])
                blocks.append({"tag": f"h{level_num}", "level": level_num, "title": title})

    sections = []
    current = None
    intro_used, INTRO_LIMIT = 0, 3

    def flush():
        nonlocal current
        if current:
            sections.append(current)
            current = None

    for b in blocks:
        if b["tag"].startswith("h"):
            flush()
            lvl = b.get("level", 2)
            current = {"title": b["title"], "level": f"H{lvl}", "paragraphs": []}
        else:
            if not current:
                if intro_used >= INTRO_LIMIT:
                    continue
                current = {"title": "Introduction", "level": "H2", "paragraphs": []}
            current["paragraphs"].append(b["text"])
            if current["title"] == "Introduction":
                intro_used += 1

    flush()

    flat_markdown = sections_to_markdown(sections)
    return sections, flat_markdown


def sections_to_markdown(sections):
    md_lines = []
    for s in sections:
        n = int(s["level"][1]) if s.get("level") else 2
        md_lines.append(heading_md(n, s["title"]))
        for p in s.get("paragraphs", []):
            md_lines.append(p)
        md_lines.append("")
    return "\n".join(md_lines).strip()

# ────────────────────────────────────────────────────────────────────────────────
# Stripped HTML from focused body: classic tags, keep href/src/alt
# ────────────────────────────────────────────────────────────────────────────────
ALLOWED_TAGS = {
    "div","section","article",
    "p","h1","h2","h3","h4","h5","h6",
    "ul","ol","li",
    "a","span","strong","em","b","i","u","small","sup","sub","code",
    "img",
    "table","thead","tbody","tr","th","td",
    "br","hr",
}

def strip_html_from_focused_body(focused_body_html: str) -> str:
    soup = BeautifulSoup(focused_body_html, "lxml")
    root = soup.body or soup

    for tag in root(["script","style","noscript","template","svg"]):
        tag.decompose()
    for c in root.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()

    for el in list(root.find_all(True)):
        name = el.name.lower()
        if name not in ALLOWED_TAGS:
            el.unwrap()
            continue
        if name in {"table","thead","tbody","tr"}:
            el.attrs = {}
            continue
        if name == "a":
            href = (el.get("href") or "").strip()
            el.attrs = {}
            if href.lower().startswith(("http://","https://","#","/")):
                el.attrs["href"] = href
        elif name == "img":
            src = (el.get("src") or "").strip()
            alt = fix_text(el.get("alt") or "")
            el.attrs = {}
            if src.lower().startswith(("http://","https://","data:image")):
                el.attrs["src"] = src
            if alt:
                el.attrs["alt"] = alt
        elif name in {"th","td"}:
            el.attrs = {}
        else:
            el.attrs = {}

    if getattr(root, "name", None) == "body":
        return "".join(str(c) for c in root.contents).strip()
    return str(root)

# ────────────────────────────────────────────────────────────────────────────────
def clamp(s, n):
    if not s:
        return s
    return s if len(s) <= n else (s[:n] + "... [truncated]")


def cell_to_text(cell: Tag) -> str:
    """Convert a table cell (th/td) to inline Markdown-ish text."""
    return "".join(html_inline_to_md(c) for c in cell.children).strip()


def table_to_markdown(table: Tag) -> str:
    rows = []
    headers = None

    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        texts = [cell_to_text(c) for c in cells]
        if headers is None and any(c.name == "th" for c in cells):
            headers = texts
        else:
            rows.append(texts)

    if not headers and rows:
        headers = [f"Col {i+1}" for i in range(len(rows[0]))]

    if not headers:
        return ""

    col_count = max(len(headers), max((len(r) for r in rows), default=0))
    headers = headers + [""] * (col_count - len(headers))
    normalized_rows = []
    for r in rows:
        normalized_rows.append(r + [""] * (col_count - len(r)))

    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for r in normalized_rows:
        lines.append("| " + " | ".join(r) + " |")

    caption_el = table.find("caption")
    caption = fix_text(caption_el.get_text(" ", strip=True)) if caption_el else None
    md = "\n".join(lines)
    return (caption + "\n" + md).strip() if caption else md


def extract_tables_from_focused_body(focused_body_html: str, max_tables: int = 20):
    """Extract tables as Markdown strings and cleaned HTML."""
    soup = BeautifulSoup(focused_body_html, "lxml")
    tables = []
    for idx, table in enumerate(soup.find_all("table")):
        if idx >= max_tables:
            break
        md = table_to_markdown(table)
        cleaned_html = strip_html_from_focused_body(str(table))
        tables.append({
            "markdown": md,
            "html": cleaned_html,
            "caption": fix_text(table.find("caption").get_text(" ", strip=True)) if table.find("caption") else None,
        })
    return tables


SCHEMA_LD_JSON_RE = re.compile(r"<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
SCHEMA_TAG_RE = re.compile(r"<schema[^>]*>(.*?)</schema>", re.IGNORECASE | re.DOTALL)


def find_schema_type(data):
    if isinstance(data, dict):
        schema_type = data.get("@type")
        if isinstance(schema_type, list) and schema_type:
            return str(schema_type[0])
        if isinstance(schema_type, str):
            return schema_type
        for val in data.values():
            found = find_schema_type(val)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = find_schema_type(item)
            if found:
                return found
    return None


def extract_schema_markup(raw_html: str):
    schema_blocks = []
    for m in SCHEMA_LD_JSON_RE.finditer(raw_html):
        schema_raw = m.group(1)
        schema_type = None
        try:
            data = json.loads(schema_raw.strip())
            schema_type = find_schema_type(data)
        except Exception:
            schema_type = None
        schema_blocks.append({"raw": schema_raw, "type": schema_type})

    for m in SCHEMA_TAG_RE.finditer(raw_html):
        schema_blocks.append({"raw": m.group(1), "type": "schema"})

    return schema_blocks


def schema_sections_from_markup(schema_blocks):
    sections = []
    for block in schema_blocks:
        raw = block.get("raw")
        if not raw:
            continue
        title_type = block.get("type")
        title = f"Schema: {title_type}" if title_type else "Schema Markup"
        sections.append({
            "title": title,
            "level": "H2",
            "paragraphs": [raw],
        })
    return sections

@app.route("/")
def home():
    return "Trafilatura scraper is running."

@app.route("/read", methods=["POST"])
def read_page():
    data = request.get_json(force=True, silent=True) or {}
    url = data.get("url")
    max_chars = int(data.get("max_chars", 5000))
    return_html = bool(data.get("return_html", False))  # optional param

    clean_html_raw = data.get("Clean HTML")
    if clean_html_raw is None:
        clean_html_raw = data.get("clean_html", True)
    if isinstance(clean_html_raw, str):
        clean_html = clean_html_raw.strip().lower() not in {"false", "0", "no", "off"}
    else:
        clean_html = bool(clean_html_raw)

    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return soft_fail(url, "Invalid or missing URL", reason="INPUT", extra={"length": 0})

    headers = {
        "User-Agent": get_random_user_agent(),
        "Referer": "https://www.google.com",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = fetch_once(url, headers=headers, timeout=8)
        if not resp:
            return soft_fail(url, "Network error", reason="NETWORK", extra={"length": 0})

        if resp.status_code in (401, 403, 429, 451):
            return soft_fail(url, "Crawlers are blocked", reason="BLOCKED",
                             http_status=resp.status_code, extra={"length": 0})

        if resp.status_code != 200:
            return soft_fail(url, f"Failed to load page (HTTP {resp.status_code})", reason="NETWORK",
                             http_status=resp.status_code, extra={"length": 0})

        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return soft_fail(url, "Unsupported MIME type", reason="UNSUPPORTED_MIME",
                             http_status=resp.status_code, extra={"length": 0, "content_type": ctype})

        html = robust_decode(resp.content, fallback_text=resp.text or "")
        schema_blocks = extract_schema_markup(html)
        if len(html) < 500:
            return soft_fail(url, "Empty or suspicious page", reason="EMPTY",
                             http_status=resp.status_code, extra={"length": 0})

        body_slice = slice_body_html(html)  # exact body
        soup_full = clean_dom_full(html)

        if body_slice is not None:
            # Focus the body to main/article or best content container
            focused_body_html = focus_body_html(body_slice)
            body_html_for_output = body_slice
            main_text = trafilatura.extract(focused_body_html) or ""
            sections, flat_md = extract_outline_from_focused_body(focused_body_html)
            tables = extract_tables_from_focused_body(focused_body_html)
        else:
            # Fallback: no <body> found — focus from cleaned full soup
            fallback_html = str(soup_full)
            body_html_for_output = fallback_html
            focused_body_html = focus_body_html(fallback_html)
            main_text = trafilatura.extract(focused_body_html) or ""
            sections, flat_md = extract_outline_from_focused_body(focused_body_html)
            tables = extract_tables_from_focused_body(focused_body_html)

        main_text = fix_text((main_text or "").strip())
        meta = get_meta(soup_full, url)

        if schema_blocks:
            schema_sections = schema_sections_from_markup(schema_blocks)
            sections.extend(schema_sections)
            flat_md = sections_to_markdown(sections)

        if not main_text and not sections:
            return soft_fail(url, "Could not extract readable content", reason="EXTRACT_FAIL",
                             extra={"length": 0})

        # Build response in the required order
        result = {}
        result["title"] = meta.get("title")
        result["meta_description"] = meta.get("meta_description")
        result["url"] = url
        result["canonical"] = meta.get("canonical") or url
        result["robots"] = meta.get("robots")
        result["lang"] = meta.get("lang")
        result["length"] = len(main_text or "")
        result["lengths"] = {
            "main_text": len(main_text or ""),
            "flat_outline": len(flat_md or ""),
        }
        result["h1"] = meta.get("h1")
        result["flat_outline"] = clamp(flat_md, max_chars)
        result["schema_markup"] = [block["raw"] for block in schema_blocks if block.get("raw")]
        result["tables"] = [
            {
                "markdown": clamp(t.get("markdown"), max_chars),
                "html": clamp(t.get("html"), max_chars),
                "caption": t.get("caption"),
            }
            for t in tables
        ]

        if return_html:
            if clean_html:
                result["html"] = clamp(strip_html_from_focused_body(focused_body_html), max_chars)
            else:
                result["html"] = clamp(body_html_for_output, max_chars)

        result["outline_sections"] = sections[:200]

        return soft_ok(result)

    except Exception as e:
        msg = (str(e) or "Unexpected error")
        low = msg.lower()
        if "timed out" in low or "timeout" in low:
            return soft_fail(url, "Timeout fetching page", reason="TIMEOUT", extra={"length": 0})
        if "captcha" in low or "cloudflare" in low:
            return soft_fail(url, "Crawlers are blocked", reason="BLOCKED", extra={"length": 0})
        return soft_fail(url, msg, reason="UNKNOWN", extra={"length": 0})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
