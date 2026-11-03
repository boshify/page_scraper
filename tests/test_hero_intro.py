"""Hero/intro recovery in focus_body_html (choose_content_root narrowing)."""
import pathlib

import pytest
from bs4 import BeautifulSoup

import app

FIX = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def run(html):
    """Run the same steps /read does: body slice -> focus -> text + outline."""
    body = app.slice_body_html(html) or html
    focused = app.focus_body_html(body)
    text = app.extract_main_text(focused, full_html=html)
    sections, md = app.extract_outline_from_focused_body(focused)
    return focused, text, sections, md


def root_only_html(body_html):
    """The pre-fix behaviour: inner HTML of the chosen root only."""
    soup = BeautifulSoup(body_html, "lxml")
    body = soup.body or soup
    app.drop_chrome_blocks(body)
    root = app.choose_content_root(body)
    return "".join(str(c) for c in root.contents)


# -- Real Jordan Insurance pages (no <main>/<article>; hero is outside the chosen root)

JORDAN = [
    ("jordan_medicare.html", "Medicare Insurance Agent in Charlotte, NC",
     "Medicare enrollment help in Charlotte, NC starts with your Medicare eligibility dates"),
    ("jordan_homeowners.html", "Home Insurance in Charlotte, NC",
     "Homeowners insurance protects your home, belongings and personal liability"),
]


@pytest.mark.parametrize("fixture,title,intro", JORDAN)
def test_jordan_hero_intro_is_kept(fixture, title, intro):
    html = load(fixture)
    # baseline: the bug. The old root-only extraction lost the intro.
    assert intro not in app.extract_main_text(root_only_html(app.slice_body_html(html)), full_html=html)
    focused, text, sections, md = run(html)
    assert intro in text
    assert intro in focused
    assert title in md


@pytest.mark.parametrize("fixture,title,intro", JORDAN)
def test_jordan_chrome_stays_out(fixture, title, intro):
    focused, text, sections, md = run(load(fixture))
    everything = focused + text + md
    for junk in [
        "Privacy Policy", "Terms of Service", "Subscribe", "All rights reserved",
        "ookie", "w-nav-menu", "footer-list", "navbar", "<nav", "<footer", "<script",
        "application/ld+json", "@context",
    ]:
        assert junk not in everything, junk


@pytest.mark.parametrize("fixture,title,intro", JORDAN)
def test_jordan_nothing_lost(fixture, title, intro):
    """Every line the old extraction produced is still present."""
    html = load(fixture)
    old_text = app.extract_main_text(root_only_html(app.slice_body_html(html)), full_html=html)
    new_text = run(html)[1]
    for line in old_text.splitlines():
        assert line.strip() in new_text


# -- Pages that already work must not change

@pytest.mark.parametrize("fixture", [
    "wikipedia_web_scraping.html",  # <main> holds h1 + everything
    "nhs_flu.html",                 # <main>/<article> + cookie banner markup
    "mozilla_firefox.html",         # <main>/<article> + consent UI
    "example.html",                 # tiny body-only page
])
def test_working_pages_unchanged(fixture):
    body = app.slice_body_html(load(fixture))
    assert app.focus_body_html(body) == root_only_html(body)


def test_main_holding_everything_no_duplicates():
    html = """<html><body>
    <nav><a href=/>Home</a><a href=/a>About</a></nav>
    <main><h1>Whole Page</h1><p>Intro paragraph that is long enough to be real content here.</p>
    <h2>Part</h2><p>Another long paragraph of the body text for this section of the page.</p></main>
    <footer><p>Footer text Privacy Policy</p></footer></body></html>"""
    focused, text, sections, md = run(html)
    assert md.count("Whole Page") == 1
    assert text.count("Intro paragraph") == 1
    assert "Footer text" not in text and "Home" not in text


# -- Synthetic layouts

HERO_OUTSIDE_MAIN = """<html><head><title>T</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Service","name":"JSONLD-NAME"}</script>
</head><body>
<div id="onetrust-banner-sdk"><p>We use cookies to improve your experience. Accept all cookies.</p></div>
<div class="cookie-notice"><p>This site uses cookies. Manage preferences.</p></div>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header"><nav><ul><li><a href="/">Home</a></li><li><a href="/x">Services</a></li></ul></nav></header>
<section class="hero"><h1>Hero Headline Here</h1>
<p>This is the hero intro paragraph that describes the whole page in a couple of sentences.</p></section>
<div class="modal" role="dialog"><p>Join our newsletter modal text that must not appear anywhere.</p></div>
<div style="display:none"><p>Hidden promo paragraph that is not visible to anyone ever.</p></div>
<main><h2>First Section</h2><p>Body paragraph one with enough words to count as real page content here.</p>
<p>Body paragraph two with enough words to count as real page content here too.</p></main>
<footer><p>Footer legal text. Privacy Policy. Terms of Service.</p></footer>
<script>var x = "SCRIPT-TEXT";</script>
</body></html>"""


def test_hero_outside_main_is_kept_and_chrome_stays_out():
    focused, text, sections, md = run(HERO_OUTSIDE_MAIN)
    assert "Hero Headline Here" in md
    assert "hero intro paragraph" in text
    assert "Body paragraph one" in text
    for junk in ["cookies", "Manage preferences", "Skip to content", "Services", "newsletter",
                 "Hidden promo", "Footer legal", "JSONLD-NAME", "SCRIPT-TEXT", "@context"]:
        assert junk not in focused + text + md, junk


def test_hero_comes_before_body():
    focused = run(HERO_OUTSIDE_MAIN)[0]
    assert focused.index("Hero Headline") < focused.index("First Section")


def test_hero_outside_article_without_main():
    html = """<html><body><div class="top"><h1>Page Title</h1>
    <p>Standfirst paragraph that introduces the article with a good amount of text.</p></div>
    <article><h2>Heading</h2><p>Article paragraph with enough text to be content for sure.</p></article>
    </body></html>"""
    focused, text, sections, md = run(html)
    assert "Standfirst paragraph" in text
    assert "Page Title" in md


def test_hero_text_in_plain_div():
    html = """<html><body><section class="intro"><h1>Plain Div Hero</h1>
    <div>Introductory copy that sits in a bare div rather than a paragraph tag at all, long enough.</div></section>
    <main><h2>Body</h2><p>Body paragraph one with enough words to count as real page content.</p></main>
    </body></html>"""
    assert "Introductory copy" in run(html)[0]


def test_root_with_h1_is_not_touched():
    html = """<html><body><div class="logo-area"><h1>Site Logo</h1><p>Tagline text that is fairly long indeed.</p></div>
    <main><h1>Real Title</h1><p>Body paragraph one with enough words to count as real page content.</p></main>
    </body></html>"""
    focused, text, sections, md = run(html)
    assert "Site Logo" not in focused
    assert "Real Title" in md


def test_no_h1_outside_means_no_lead():
    html = """<html><body><p>Some stray strap line outside of main that is long enough to be text.</p>
    <main><h2>Body</h2><p>Body paragraph one with enough words to count as real page content.</p></main>
    </body></html>"""
    assert "stray strap line" not in run(html)[0]


def test_logo_h1_inside_link_is_not_a_hero():
    html = """<html><body><a href="/"><h1>Brand Logo</h1></a><p>Welcome strip text that is long enough to count.</p>
    <main><h2>Body</h2><p>Body paragraph one with enough words to count as real page content.</p></main>
    </body></html>"""
    focused = run(html)[0]
    assert "Brand Logo" not in focused and "Welcome strip" not in focused


def test_lead_is_bounded():
    paras = "".join(f"<p>Paragraph number {i} " + "word " * 40 + "</p>" for i in range(200))
    html = f"<html><body><h1>T</h1>{paras}<main><h2>Body</h2><p>{'body ' * 30}</p></main></body></html>"
    assert len(app.focus_body_html(app.slice_body_html(html))) < 40000


def test_heuristic_root_path_gets_hero_too():
    """No <main>/<article>: root is the densest <p> container."""
    html = """<html><body><div class="wrap"><section class="hero"><h1>Heuristic Hero</h1>
    <p>Hero intro text that is outside the densest paragraph container on this page.</p></section>
    <section class="content"><p>One long paragraph of content for the page body here.</p>
    <p>Two long paragraph of content for the page body here.</p>
    <p>Three long paragraph of content for the page body here.</p></section></div></body></html>"""
    focused, text, sections, md = run(html)
    assert "Hero intro text" in text and "Heuristic Hero" in md
