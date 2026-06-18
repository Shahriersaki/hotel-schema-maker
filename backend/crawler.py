"""
Crawler module — discovers all pages of a hotel website.
Uses requests + BeautifulSoup with polite crawling behavior.
"""

import re
import time
import requests
from urllib.parse import urljoin, urlparse, urldefrag
from bs4 import BeautifulSoup


# Page-type detection keywords
PAGE_PATTERNS = {
    "home":          ["home", "index", "welcome", "main"],
    "rooms":         ["room", "suite", "accommodation", "bedroom", "stay", "lodge", "cabin"],
    "dining":        ["dining", "restaurant", "food", "bar", "cafe", "breakfast", "menu", "eat"],
    "gallery":       ["gallery", "photo", "image", "picture", "media", "virtual-tour"],
    "attractions":   ["attraction", "activity", "explore", "nearby", "things-to-do", "around",
                      "local", "excursion", "tour", "experience"],
    "offers":        ["offer", "deal", "package", "promotion", "special", "discount", "rate"],
    "blog":          ["blog", "news", "article", "post", "update", "press"],
    "contact":       ["contact", "reach-us", "find-us", "location", "directions", "map"],
    "about":         ["about", "our-story", "history", "team", "who-we-are"],
    "spa":           ["spa", "wellness", "beauty", "treatment", "massage", "relax"],
    "events":        ["event", "wedding", "conference", "meeting", "function", "venue"],
    "faq":           ["faq", "frequently", "question", "help"],
    "policies":      ["policy", "policies", "terms", "privacy", "cancellation", "checkout"],
}


def get_default_headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    return url.rstrip("/")


def is_same_domain(base_url: str, candidate: str) -> bool:
    base_host = urlparse(base_url).netloc.lower().lstrip("www.")
    cand_host = urlparse(candidate).netloc.lower().lstrip("www.")
    return base_host == cand_host or cand_host == ""


def is_crawlable(url: str) -> bool:
    """Filter out non-page URLs."""
    skip_extensions = (
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar",
        ".mp4", ".mp3", ".avi", ".mov", ".css", ".js", ".json",
        ".xml", ".txt", ".woff", ".woff2", ".ttf", ".eot"
    )
    skip_fragments = ["#", "mailto:", "tel:", "javascript:", "whatsapp:"]

    parsed = urlparse(url)
    path_lower = parsed.path.lower()

    if any(url.startswith(f) for f in skip_fragments):
        return False
    if any(path_lower.endswith(ext) for ext in skip_extensions):
        return False
    if parsed.scheme not in ("http", "https", ""):
        return False
    return True


def detect_page_type(url: str, title: str = "", headings: list = None) -> str:
    """Classify a page by its URL path, title, and headings."""
    headings = headings or []
    text = (url + " " + title + " " + " ".join(headings)).lower()

    # Home page detection
    parsed = urlparse(url)
    if not parsed.path or parsed.path in ("/", "/index", "/home", "/index.html"):
        return "home"

    scores = {}
    for page_type, keywords in PAGE_PATTERNS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score:
            scores[page_type] = score

    if scores:
        return max(scores, key=scores.get)

    return "other"


def fetch_page(url: str, session: requests.Session, timeout: int = 15) -> tuple[str | None, int]:
    """Fetch a URL, return (html_content, status_code)."""
    try:
        resp = session.get(url, headers=get_default_headers(), timeout=timeout,
                           allow_redirects=True)
        if "text/html" not in resp.headers.get("Content-Type", ""):
            return None, resp.status_code
        return resp.text, resp.status_code
    except requests.RequestException:
        return None, 0


def extract_links(html: str, base_url: str) -> list[str]:
    """Extract all internal href links from HTML."""
    soup = BeautifulSoup(html, "lxml")
    links = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href:
            continue
        full_url = urljoin(base_url, href)
        full_url = normalize_url(full_url)
        if is_crawlable(full_url) and is_same_domain(base_url, full_url):
            links.add(full_url)
    return list(links)


def extract_page_meta(html: str) -> dict:
    """Extract title, description, headings from HTML."""
    soup = BeautifulSoup(html, "lxml")
    title = ""
    description = ""
    headings = []

    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    meta_desc = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
    if meta_desc:
        description = meta_desc.get("content", "")

    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = tag.get_text(strip=True)
        if text:
            headings.append(text)

    # Also extract any OG data
    og_title = soup.find("meta", property="og:title")
    og_desc = soup.find("meta", property="og:description")
    og_image = soup.find("meta", property="og:image")

    return {
        "title": title,
        "description": description,
        "headings": headings[:10],
        "og_title": og_title["content"] if og_title else "",
        "og_description": og_desc["content"] if og_desc else "",
        "og_image": og_image["content"] if og_image else "",
    }


def crawl_website(start_url: str, max_pages: int = 60, delay: float = 0.5) -> list[dict]:
    """
    BFS crawl of a hotel website. Returns list of discovered page dicts.

    Each page dict contains:
    - url, page_type, title, description, headings, og_image, status_code, depth
    """
    start_url = normalize_url(start_url)
    if not start_url.startswith("http"):
        start_url = "https://" + start_url

    visited = set()
    queue = [(start_url, 0)]  # (url, depth)
    pages = []

    session = requests.Session()
    session.max_redirects = 5

    print(f"[Crawler] Starting crawl of: {start_url}")

    while queue and len(pages) < max_pages:
        url, depth = queue.pop(0)
        norm_url = normalize_url(url)

        if norm_url in visited:
            continue
        visited.add(norm_url)

        if depth > 4:  # max crawl depth
            continue

        html, status = fetch_page(url, session)
        if not html or status not in (200, 301, 302):
            continue

        meta = extract_page_meta(html)
        page_type = detect_page_type(url, meta["title"], meta["headings"])

        page = {
            "url": norm_url,
            "page_type": page_type,
            "title": meta["title"],
            "description": meta["description"],
            "headings": meta["headings"],
            "og_image": meta["og_image"],
            "og_title": meta["og_title"],
            "og_description": meta["og_description"],
            "status_code": status,
            "depth": depth
        }
        pages.append(page)
        print(f"[Crawler] [{page_type:12}] {norm_url[:80]}")

        # Discover new links
        new_links = extract_links(html, norm_url)
        for link in new_links:
            if normalize_url(link) not in visited:
                queue.append((link, depth + 1))

        time.sleep(delay)

    print(f"[Crawler] Done — found {len(pages)} pages.")
    return pages


def enrich_page_data(pages: list[dict], hotel_data: dict) -> list[dict]:
    """
    Post-process pages: deduplicate page types, attach hotel context,
    ensure home page is first.
    """
    # Ensure home page exists
    home_pages = [p for p in pages if p["page_type"] == "home"]
    if not home_pages and pages:
        pages[0]["page_type"] = "home"

    # Sort: home first, then by type, then URL
    type_order = {
        "home": 0, "rooms": 1, "dining": 2, "spa": 3, "gallery": 4,
        "attractions": 5, "offers": 6, "events": 7, "blog": 8,
        "about": 9, "contact": 10, "faq": 11, "policies": 12, "other": 99
    }
    pages.sort(key=lambda p: (type_order.get(p["page_type"], 99), p["url"]))

    return pages
