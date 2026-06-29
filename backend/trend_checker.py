"""
Trend Checker — fetches the latest schema.org and Google Structured Data
guidelines to keep schema generation current.

Sources checked:
  1. schema.org/Hotel — property list
  2. Google Search Central structured data docs (lodging)
  3. schema.org release notes (changelog)
  4. User-fed knowledge base entries (highest priority)
"""

import re
import json
import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from backend.database import (
    save_trend_snapshot, get_latest_trend_snapshots, get_kb_entries
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
TIMEOUT = 12


# ─── Individual Source Fetchers ───────────────────────────────────────────────

def _fetch_schema_org_hotel() -> dict:
    """Scrape schema.org/Hotel for current property list."""
    url = "https://schema.org/Hotel"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(resp.text, "lxml")

        properties = []
        # schema.org renders property tables with class 'prop-table'
        for row in soup.select("table.definition-table tr"):
            prop_cell = row.select_one("th.prop-nam a")
            desc_cell = row.select_one("td.prop-desc")
            if prop_cell:
                prop = {
                    "name": prop_cell.get_text(strip=True),
                    "description": desc_cell.get_text(strip=True)[:200] if desc_cell else ""
                }
                properties.append(prop)

        # Also grab inherited LodgingBusiness props
        inherited_url = "https://schema.org/LodgingBusiness"
        resp2 = requests.get(inherited_url, headers=HEADERS, timeout=TIMEOUT)
        soup2 = BeautifulSoup(resp2.text, "lxml")
        for row in soup2.select("table.definition-table tr"):
            prop_cell = row.select_one("th.prop-nam a")
            desc_cell = row.select_one("td.prop-desc")
            if prop_cell:
                name = prop_cell.get_text(strip=True)
                if not any(p["name"] == name for p in properties):
                    properties.append({
                        "name": name,
                        "description": desc_cell.get_text(strip=True)[:200] if desc_cell else "",
                        "inherited_from": "LodgingBusiness"
                    })

        return {
            "source": "schema.org/Hotel",
            "url": url,
            "property_count": len(properties),
            "properties": properties[:80],  # cap at 80
            "fetched_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"source": "schema.org/Hotel", "error": str(e), "properties": []}


def _fetch_google_hotel_docs() -> dict:
    """Scrape Google's hotel structured data documentation."""
    url = "https://developers.google.com/search/docs/appearance/structured-data/hotel-lodging"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(resp.text, "lxml")

        # Extract required / recommended properties
        required = []
        recommended = []

        for section in soup.find_all(["h2", "h3"]):
            text = section.get_text(strip=True).lower()
            parent = section.find_next_sibling()
            if not parent:
                continue

            if "required" in text:
                for li in parent.find_all("li")[:20]:
                    item = li.get_text(strip=True)
                    if item and len(item) < 200:
                        required.append(item)
            elif "recommended" in text:
                for li in parent.find_all("li")[:20]:
                    item = li.get_text(strip=True)
                    if item and len(item) < 200:
                        recommended.append(item)

        # Extract any structured data type definitions
        code_blocks = []
        for pre in soup.find_all("pre")[:3]:
            code_blocks.append(pre.get_text()[:800])

        return {
            "source": "Google Search Central",
            "url": url,
            "required_properties": required,
            "recommended_properties": recommended,
            "example_snippets": code_blocks,
            "fetched_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"source": "Google Search Central", "error": str(e),
                "required_properties": [], "recommended_properties": []}


def _fetch_schema_org_changelog() -> dict:
    """Fetch schema.org release notes to detect recent Hotel-related changes."""
    url = "https://schema.org/docs/releases.html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(resp.text, "lxml")

        entries = []
        for section in soup.find_all(["h2", "h3"])[:15]:
            version_text = section.get_text(strip=True)
            content_el = section.find_next_sibling()
            content = ""
            if content_el:
                content = content_el.get_text(strip=True)[:400]

            # Only include if Hotel/LodgingBusiness mentioned
            combined = (version_text + " " + content).lower()
            hotel_related = any(kw in combined for kw in
                                ["hotel", "lodging", "accommodation", "checkin", "checkout"])
            entries.append({
                "version": version_text,
                "content": content,
                "hotel_related": hotel_related
            })

        hotel_entries = [e for e in entries if e["hotel_related"]]
        return {
            "source": "schema.org changelog",
            "url": url,
            "total_releases_checked": len(entries),
            "hotel_related_changes": hotel_entries[:5],
            "fetched_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"source": "schema.org changelog", "error": str(e), "hotel_related_changes": []}


def _fetch_google_rich_results_types() -> dict:
    """Fetch list of supported rich result types from Google."""
    url = "https://developers.google.com/search/docs/appearance/structured-data/search-gallery"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(resp.text, "lxml")

        types = []
        for link in soup.select("a[href*='structured-data']"):
            name = link.get_text(strip=True)
            href = link.get("href", "")
            if name and len(name) < 60 and href:
                types.append({"name": name, "url": href})

        return {
            "source": "Google Rich Results Gallery",
            "url": url,
            "supported_types": types[:40],
            "fetched_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"source": "Google Rich Results Gallery", "error": str(e), "supported_types": []}


# ─── Trend Aggregator ─────────────────────────────────────────────────────────

def fetch_all_trends(force: bool = False) -> dict:
    """
    Fetch all trend sources. Results are cached for 24 hours unless force=True.
    Returns aggregated dict with all source data.
    """
    # Check cache
    if not force:
        snapshots = get_latest_trend_snapshots(limit=1)
        if snapshots:
            fetched = datetime.fromisoformat(snapshots[0]["fetched_at"])
            age = datetime.now(timezone.utc) - fetched.replace(tzinfo=timezone.utc) if fetched.tzinfo is None else datetime.now(timezone.utc) - fetched
            if age < timedelta(hours=24):
                # Return cached
                all_snaps = get_latest_trend_snapshots(limit=20)
                return _aggregate_snapshots(all_snaps)

    print("[Trends] Fetching latest from schema.org and Google…")
    results = {}

    # Fetch each source
    hotel_props = _fetch_schema_org_hotel()
    results["schema_org_hotel"] = hotel_props
    save_trend_snapshot(
        "schema.org/Hotel",
        f"Found {hotel_props.get('property_count', 0)} properties",
        hotel_props
    )

    google_docs = _fetch_google_hotel_docs()
    results["google_docs"] = google_docs
    save_trend_snapshot(
        "Google Search Central",
        f"Required: {len(google_docs.get('required_properties', []))}, "
        f"Recommended: {len(google_docs.get('recommended_properties', []))}",
        google_docs
    )

    changelog = _fetch_schema_org_changelog()
    results["changelog"] = changelog
    save_trend_snapshot(
        "schema.org changelog",
        f"{len(changelog.get('hotel_related_changes', []))} hotel-related changes found",
        changelog
    )

    rich_results = _fetch_google_rich_results_types()
    results["rich_results"] = rich_results
    save_trend_snapshot(
        "Google Rich Results Gallery",
        f"{len(rich_results.get('supported_types', []))} rich result types indexed",
        rich_results
    )

    results["fetched_at"] = datetime.now(timezone.utc).isoformat()
    results["cache_valid_until"] = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    print("[Trends] Done fetching all sources.")
    return results


def _aggregate_snapshots(snapshots: list) -> dict:
    """Reconstruct trends dict from cached DB snapshots."""
    result = {}
    for snap in snapshots:
        key = snap["source"].lower().replace(" ", "_").replace("/", "_").replace(".", "")
        result[key] = snap["raw_data"]
    result["from_cache"] = True
    if snapshots:
        result["fetched_at"] = snapshots[0]["fetched_at"]
    return result


# ─── Trend Digest for Schema Generator ────────────────────────────────────────

def build_trend_digest(user_id: int = None) -> dict:
    """
    Build a concise digest that the schema generator can use to:
    - Know which properties are currently required/recommended
    - Apply any user-fed corrections or guideline updates
    - Warn about deprecated properties

    Priority: user-fed KB entries > fetched trends > built-in defaults
    Returns both decoupled 'trends_only' & 'fed_only' sub-digests and flat merged keys.
    """
    trends_only = {
        "required_properties": [
            "name", "address", "geo", "telephone", "checkinTime", "checkoutTime"
        ],
        "recommended_properties": [
            "description", "starRating", "amenityFeature", "image",
            "priceRange", "url", "email", "contactPoint"
        ],
        "deprecated_properties": [],
        "example_schemas": [],
        "notes": []
    }

    fed_only = {
        "required_properties": [],
        "recommended_properties": [],
        "deprecated_properties": [],
        "example_schemas": [],
        "user_guidelines": [],
        "corrections_applied": [],
        "notes": []
    }

    # Layer 1: Fetched trends (non-blocking — use cached if available)
    try:
        snapshots = get_latest_trend_snapshots(limit=10)
        for snap in snapshots:
            raw = snap.get("raw_data", {})
            if snap["source"] == "Google Search Central":
                req = raw.get("required_properties", [])
                rec = raw.get("recommended_properties", [])
                if req:
                    trends_only["notes"].append(
                        f"Google requires: {', '.join(req[:5])}"
                    )
                    for r in req:
                        if r not in trends_only["required_properties"]:
                            trends_only["required_properties"].append(r)
                if rec:
                    trends_only["notes"].append(
                        f"Google recommends: {', '.join(rec[:5])}"
                    )
                    for r in rec:
                        if r not in trends_only["recommended_properties"]:
                            trends_only["recommended_properties"].append(r)
            elif snap["source"] == "schema.org changelog":
                changes = raw.get("hotel_related_changes", [])
                for change in changes[:2]:
                    trends_only["notes"].append(
                        f"schema.org update [{change.get('version','?')}]: "
                        f"{change.get('content','')[:100]}"
                    )
    except Exception as e:
        trends_only["notes"].append(f"[Trend fetch warning: {e}]")

    # Layer 2: User-fed knowledge base (highest priority)
    if user_id:
        try:
            from backend.database import get_kb_entries_prioritized
            kb_entries = get_kb_entries_prioritized(user_id)
            for entry in kb_entries:
                etype = entry.get("entry_type", "")
                content = entry.get("content", "")
                title = entry.get("title", "")

                if etype == "guideline":
                    fed_only["user_guidelines"].append({
                        "title": title,
                        "content": content[:500],
                        "source": entry.get("source", "")
                    })
                elif etype == "validator_error":
                    fed_only["corrections_applied"].append({
                        "title": title,
                        "error": content[:300]
                    })
                elif etype == "deprecated":
                    props = [p.strip() for p in content.split(",") if p.strip()]
                    fed_only["deprecated_properties"].extend(props)
                elif etype == "required":
                    props = [p.strip() for p in content.split(",") if p.strip()]
                    for p in props:
                        if p not in fed_only["required_properties"]:
                            fed_only["required_properties"].append(p)
                elif etype == "recommended":
                    props = [p.strip() for p in content.split(",") if p.strip()]
                    for p in props:
                        if p not in fed_only["recommended_properties"]:
                            fed_only["recommended_properties"].append(p)
                elif etype == "example":
                    try:
                        parsed = json.loads(content)
                        def unpack_examples(obj):
                            if isinstance(obj, list):
                                for item in obj:
                                    unpack_examples(item)
                            elif isinstance(obj, dict):
                                if "@graph" in obj and isinstance(obj["@graph"], list):
                                    for item in obj["@graph"]:
                                        unpack_examples(item)
                                elif "@type" in obj:
                                    fed_only["example_schemas"].append(obj)
                        unpack_examples(parsed)
                    except Exception:
                        pass
                elif etype == "news":
                    fed_only["notes"].append(f"★ Update: {title} — {content[:150]}")

            if kb_entries:
                fed_only["notes"].insert(0,
                    f"✓ Applied {len(kb_entries)} user-fed knowledge base entries"
                )
        except Exception as e:
            fed_only["notes"].append(f"[KB load warning: {e}]")

    # Combine for flat backward compatibility
    digest = {
        "required_properties": list(set(trends_only["required_properties"] + fed_only["required_properties"])),
        "recommended_properties": list(set(trends_only["recommended_properties"] + fed_only["recommended_properties"])),
        "deprecated_properties": list(set(trends_only["deprecated_properties"] + fed_only["deprecated_properties"])),
        "example_schemas": trends_only["example_schemas"] + fed_only["example_schemas"],
        "notes": trends_only["notes"] + fed_only["notes"],
        "user_guidelines": fed_only["user_guidelines"],
        "corrections_applied": fed_only["corrections_applied"],
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "trends_only": trends_only,
        "fed_only": fed_only
    }
    return digest


def get_compliance_warnings(schema_dict: dict, digest: dict) -> list:
    """
    Compare a schema object against the current digest.
    Returns list of warning strings.
    """
    warnings = []

    schema_keys = set(schema_dict.keys()) - {"@context", "@type", "@id"}

    # Check required props
    for prop in digest.get("required_properties", []):
        # Map common names to schema keys
        key_map = {
            "name": "name", "address": "address", "geo": "geo",
            "telephone": "telephone", "checkinTime": "checkinTime",
            "checkoutTime": "checkoutTime"
        }
        schema_key = key_map.get(prop, prop)
        if schema_key not in schema_dict or not schema_dict[schema_key]:
            warnings.append(f"MISSING REQUIRED: '{prop}' is required by current guidelines.")

    # Check deprecated
    for prop in digest.get("deprecated_properties", []):
        if prop in schema_dict:
            warnings.append(f"DEPRECATED: '{prop}' is marked deprecated in fed guidelines.")

    # Check user-fed corrections
    for correction in digest.get("corrections_applied", []):
        error_text = correction.get("error", "").lower()
        for key in schema_keys:
            if key.lower() in error_text:
                warnings.append(
                    f"KNOWN ISSUE: '{key}' has a known validator error — {correction['title']}"
                )

    return warnings
