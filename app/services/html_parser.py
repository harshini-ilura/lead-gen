"""Phase 2 HTML helpers: internal-link discovery + HTML cleaning.

Deep contact/people parsing belongs to Phase 3 — this module only decides which
pages are worth crawling and trims pages down for storage.
"""
import re
from urllib.parse import urljoin, urlparse

import tldextract
from bs4 import BeautifulSoup

# Paths/anchors that tend to hold company contacts — crawled first.
_CONTACT_KEYWORDS = (
    "contact", "about", "team", "agents", "agent", "staff", "people",
    "our-team", "leadership", "management", "meet",
)
_KEYWORD_RE = re.compile("|".join(_CONTACT_KEYWORDS), re.IGNORECASE)

# Non-content extensions to skip when collecting links.
_SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|mp4|zip|docx?|xlsx?|css|js)$", re.IGNORECASE)


def _registrable_domain(host: str) -> str:
    ext = tldextract.extract(host)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain


def extract_internal_links(html: str, base_url: str, domain: str) -> list[str]:
    """Return de-duplicated same-domain links, contact-relevant ones first.

    `domain` is the company's registrable domain (e.g. ``dacha.ae``); links on
    other registrable domains (social, CDNs, portals) are dropped.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    scored: list[tuple[int, str]] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if _registrable_domain(parsed.netloc) != domain:
            continue
        if _SKIP_EXT.search(parsed.path):
            continue
        # Normalize: drop fragment + trailing slash.
        clean = parsed._replace(fragment="").geturl().rstrip("/")
        if clean in seen:
            continue
        seen.add(clean)
        anchor = a.get_text(" ", strip=True)
        priority = 0 if _KEYWORD_RE.search(parsed.path) or _KEYWORD_RE.search(anchor) else 1
        scored.append((priority, clean))

    scored.sort(key=lambda x: x[0])  # contact-relevant (0) before the rest (1)
    return [url for _, url in scored]


def clean_and_cap_html(html: str, max_bytes: int) -> str:
    """Strip scripts/styles/comments, collapse whitespace, truncate for storage."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = str(soup)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"[ \t\r\n]+", " ", text).strip()
    return text[:max_bytes]
