"""
Sitemap Generator — produces a valid XML sitemap (Sitemap Protocol 0.9)
covering all discovered hotel pages, following Google's sitemap guidelines.

Reference: https://www.sitemaps.org/protocol.html
"""

from datetime import datetime, timezone
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


# Page type priority and change frequency mapping
PAGE_CONFIG = {
    "home":        {"priority": "1.0", "changefreq": "weekly"},
    "rooms":       {"priority": "0.9", "changefreq": "weekly"},
    "offers":      {"priority": "0.9", "changefreq": "daily"},
    "dining":      {"priority": "0.8", "changefreq": "monthly"},
    "spa":         {"priority": "0.8", "changefreq": "monthly"},
    "events":      {"priority": "0.8", "changefreq": "weekly"},
    "gallery":     {"priority": "0.7", "changefreq": "monthly"},
    "attractions": {"priority": "0.7", "changefreq": "monthly"},
    "about":       {"priority": "0.6", "changefreq": "yearly"},
    "blog":        {"priority": "0.7", "changefreq": "weekly"},
    "contact":     {"priority": "0.6", "changefreq": "yearly"},
    "faq":         {"priority": "0.6", "changefreq": "monthly"},
    "policies":    {"priority": "0.4", "changefreq": "yearly"},
    "other":       {"priority": "0.5", "changefreq": "monthly"},
}

SITEMAP_XMLNS = "http://www.sitemaps.org/schemas/sitemap/0.9"
IMAGE_XMLNS = "http://www.google.com/schemas/sitemap-image/1.1"


def _url_entry(url: str, page_type: str, lastmod: str, image_url: str = "") -> ET.Element:
    """Build a <url> element for the sitemap."""
    config = PAGE_CONFIG.get(page_type, PAGE_CONFIG["other"])

    url_el = ET.Element("url")

    loc = ET.SubElement(url_el, "loc")
    loc.text = url

    lastmod_el = ET.SubElement(url_el, "lastmod")
    lastmod_el.text = lastmod

    changefreq_el = ET.SubElement(url_el, "changefreq")
    changefreq_el.text = config["changefreq"]

    priority_el = ET.SubElement(url_el, "priority")
    priority_el.text = config["priority"]

    # Image extension for pages with images
    if image_url:
        img_el = ET.SubElement(url_el, "image:image")
        img_loc = ET.SubElement(img_el, "image:loc")
        img_loc.text = image_url

    return url_el


def generate_xml_sitemap(pages: list[dict], website_url: str) -> str:
    """
    Generate a complete XML sitemap from discovered pages.
    Returns the XML string.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Register namespaces
    ET.register_namespace("", SITEMAP_XMLNS)
    ET.register_namespace("image", IMAGE_XMLNS)

    # Root element
    root = ET.Element("urlset")
    root.set("xmlns", SITEMAP_XMLNS)
    root.set("xmlns:image", IMAGE_XMLNS)

    # Deduplicate URLs
    seen_urls = set()

    for page in pages:
        url = page.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        page_type = page.get("page_type", "other")
        image_url = page.get("og_image", "")

        url_entry = _url_entry(url, page_type, today, image_url)
        root.append(url_entry)

    # Produce formatted XML string
    _indent_xml(root)
    tree = ET.ElementTree(root)
    import io
    buf = io.BytesIO()
    tree.write(buf, encoding="UTF-8", xml_declaration=True)
    xml_bytes = buf.getvalue()
    return xml_bytes.decode("utf-8")


def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    """Pretty-print XML by adding indentation."""
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent


def generate_sitemap_index(sitemap_urls: list[str]) -> str:
    """
    Generate a sitemap index file (for large sites with multiple sitemaps).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ET.register_namespace("", "http://www.sitemaps.org/schemas/sitemap/0.9")

    root = ET.Element("sitemapindex")
    root.set("xmlns", "http://www.sitemaps.org/schemas/sitemap/0.9")

    for sitemap_url in sitemap_urls:
        sitemap_el = ET.SubElement(root, "sitemap")
        loc = ET.SubElement(sitemap_el, "loc")
        loc.text = sitemap_url
        lastmod = ET.SubElement(sitemap_el, "lastmod")
        lastmod.text = today

    _indent_xml(root)
    tree = ET.ElementTree(root)
    import io
    buf = io.BytesIO()
    tree.write(buf, encoding="UTF-8", xml_declaration=True)
    return buf.getvalue().decode("utf-8")


def sitemap_stats(xml_str: str) -> dict:
    """Parse sitemap XML and return statistics."""
    try:
        root = ET.fromstring(xml_str)
        ns = {"sm": SITEMAP_XMLNS}
        urls = root.findall("sm:url", ns) or root.findall("url")
        return {
            "total_urls": len(urls),
            "has_images": any(u.find("image:image") is not None for u in urls),
        }
    except Exception:
        return {"total_urls": 0, "has_images": False}
