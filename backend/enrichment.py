"""
Enrichment module — searches for missing hotel data online using
DuckDuckGo Instant Answer API (free, no key required).
"""

import re
import json
import requests


DDGS_URL = "https://api.duckduckgo.com/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def _get_headers():
    return {
        "User-Agent": "HotelSchemaMaker/1.0 (contact: support@hotelschemamaker.com)"
    }


def geocode_address(address: str) -> dict | None:
    """
    Get lat/lon from address using OpenStreetMap Nominatim (free, no API key).
    Returns {"lat": float, "lon": float, "display_name": str} or None.
    """
    try:
        params = {
            "q": address,
            "format": "json",
            "limit": 1,
            "addressdetails": 1
        }
        resp = requests.get(
            NOMINATIM_URL,
            params=params,
            headers=_get_headers(),
            timeout=10
        )
        data = resp.json()
        if data:
            return {
                "lat": float(data[0]["lat"]),
                "lon": float(data[0]["lon"]),
                "display_name": data[0].get("display_name", address)
            }
    except Exception as e:
        print(f"[Enrichment] Geocode failed: {e}")
    return None


def search_hotel_info(hotel_name: str, location: str = "") -> dict:
    """
    Search DuckDuckGo for hotel info to fill gaps.
    Returns dict of found data.
    """
    found = {}
    query = f"{hotel_name} {location} hotel official website".strip()

    try:
        params = {
            "q": query,
            "format": "json",
            "no_redirect": 1,
            "no_html": 1,
            "skip_disambig": 1
        }
        resp = requests.get(
            DDGS_URL,
            params=params,
            headers=_get_headers(),
            timeout=10
        )
        data = resp.json()

        if data.get("AbstractURL"):
            found["website_url"] = data["AbstractURL"]
        if data.get("AbstractText"):
            found["description"] = data["AbstractText"][:500]

        # Extract phone numbers from abstract text
        abstract = data.get("AbstractText", "") + data.get("Abstract", "")
        phones = re.findall(r"[\+\d][\d\s\-\(\)]{7,15}\d", abstract)
        if phones:
            found["phone"] = phones[0]

        # Infobox data
        for item in data.get("Infobox", {}).get("content", []):
            label = item.get("label", "").lower()
            val = item.get("value", "")
            if "phone" in label and not found.get("phone"):
                found["phone"] = val
            elif "email" in label and not found.get("email"):
                found["email"] = val
            elif "website" in label and not found.get("website"):
                found["website_url"] = val

    except Exception as e:
        print(f"[Enrichment] DDG search failed: {e}")

    return found


def search_booking_links(hotel_name: str, location: str = "") -> dict:
    """
    Find booking links for popular platforms (Booking.com, TripAdvisor, etc.)
    Returns dict of platform -> URL.
    """
    booking_links = {}
    platforms = {
        "booking.com": f"https://www.booking.com/searchresults.html?ss={hotel_name}+{location}",
        "tripadvisor": f"https://www.tripadvisor.com/Search?q={hotel_name}+{location}",
    }

    # Format search-friendly URLs
    for platform, url_template in platforms.items():
        slug = re.sub(r"[^\w\s-]", "", (hotel_name + " " + location).lower())
        slug = re.sub(r"\s+", "+", slug.strip())
        booking_links[platform] = url_template

    return booking_links


def enrich_hotel_data(hotel_data: dict) -> dict:
    """
    Main enrichment function. Fills in missing fields using online sources.
    Returns enriched hotel_data dict with a 'enrichment_log' field.
    """
    enriched = dict(hotel_data)
    log = []

    hotel_name = enriched.get("name", "")
    address = enriched.get("address", {})
    full_address = " ".join(filter(None, [
        address.get("streetAddress", ""),
        address.get("addressLocality", ""),
        address.get("addressCountry", "")
    ]))

    # 1. Geocode if coordinates missing
    if not enriched.get("geo") and full_address:
        print(f"[Enrichment] Geocoding: {full_address}")
        coords = geocode_address(full_address)
        if coords:
            enriched["geo"] = {"latitude": coords["lat"], "longitude": coords["lon"]}
            log.append(f"✓ Geo coordinates found: {coords['lat']:.4f}, {coords['lon']:.4f}")
        else:
            log.append("✗ Could not geocode address automatically.")

    # 2. Search for additional hotel info if missing
    location = address.get("addressLocality", "")
    if not enriched.get("description") and hotel_name:
        print(f"[Enrichment] Searching for hotel description...")
        info = search_hotel_info(hotel_name, location)
        if info.get("description"):
            enriched["description"] = info["description"]
            log.append("✓ Description fetched from web search.")
        if info.get("phone") and not enriched.get("telephone"):
            enriched["telephone"] = info["phone"]
            log.append(f"✓ Phone number found: {info['phone']}")

    # 3. Add booking links if missing
    if not enriched.get("booking_links"):
        booking_links = search_booking_links(hotel_name, location)
        enriched["booking_links"] = booking_links
        log.append(f"✓ Generated booking search links for {len(booking_links)} platforms.")

    # 4. Default amenities if none provided
    if not enriched.get("amenities"):
        enriched["amenities"] = [
            "Free Wi-Fi", "24-hour front desk", "Room service",
            "Air conditioning", "Daily housekeeping"
        ]
        log.append("⚠ Default amenities applied (please verify and update).")

    # 5. Default check-in/out if missing
    if not enriched.get("checkinTime"):
        enriched["checkinTime"] = "14:00"
        log.append("⚠ Default check-in time set to 14:00.")
    if not enriched.get("checkoutTime"):
        enriched["checkoutTime"] = "12:00"
        log.append("⚠ Default check-out time set to 12:00.")

    enriched["enrichment_log"] = log
    return enriched
