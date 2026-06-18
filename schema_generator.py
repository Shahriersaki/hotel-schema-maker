"""
Schema Generator — produces fully compliant JSON-LD schema markup for each
hotel page following schema.org Hotel type and Google's Rich Results guidelines.

References:
  - https://schema.org/Hotel
  - https://schema.org/LodgingBusiness
  - https://developers.google.com/search/docs/appearance/structured-data/hotel-lodging
"""

import json
import re
from datetime import datetime, timezone

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _schema_address(address: dict) -> dict:
    return {
        "@type": "PostalAddress",
        "streetAddress": address.get("streetAddress", ""),
        "addressLocality": address.get("addressLocality", ""),
        "addressRegion": address.get("addressRegion", ""),
        "postalCode": address.get("postalCode", ""),
        "addressCountry": address.get("addressCountry", "")
    }


def _schema_geo(geo: dict) -> dict:
    return {
        "@type": "GeoCoordinates",
        "latitude": geo.get("latitude", ""),
        "longitude": geo.get("longitude", "")
    }


def _schema_contact_point(telephone: str, email: str = "") -> dict:
    cp = {
        "@type": "ContactPoint",
        "contactType": "reservations",
        "telephone": telephone,
        "availableLanguage": "English"
    }
    if email:
        cp["email"] = email
    return cp


def _amenity_feature(name: str) -> dict:
    return {"@type": "LocationFeatureSpecification", "name": name, "value": True}


def _image_object(url: str, name: str = "") -> dict:
    obj = {"@type": "ImageObject", "url": url}
    if name:
        obj["name"] = name
    return obj


def _hotel_base(hotel_data: dict, page_url: str) -> dict:
    """Build the core Hotel schema shared across all pages."""
    address = hotel_data.get("address", {})
    geo = hotel_data.get("geo", {})
    amenities = hotel_data.get("amenities", [])
    checkin = hotel_data.get("checkinTime", "14:00")
    checkout = hotel_data.get("checkoutTime", "12:00")
    telephone = hotel_data.get("telephone", "")
    email = hotel_data.get("email", "")
    star_rating = hotel_data.get("starRating")
    price_range = hotel_data.get("priceRange", "")
    description = hotel_data.get("description", "")
    images = hotel_data.get("images", [])
    booking_url = hotel_data.get("bookingUrl", "")
    website_url = hotel_data.get("websiteUrl", page_url)

    schema = {
        "@context": "https://schema.org",
        "@type": "Hotel",
        "name": hotel_data.get("name", ""),
        "url": website_url,
        "address": _schema_address(address),
    }

    if geo.get("latitude") and geo.get("longitude"):
        schema["geo"] = _schema_geo(geo)

    if description:
        schema["description"] = description

    if telephone:
        schema["telephone"] = telephone
        schema["contactPoint"] = _schema_contact_point(telephone, email)

    if email:
        schema["email"] = email

    if amenities:
        schema["amenityFeature"] = [_amenity_feature(a) for a in amenities]

    if checkin:
        checkin_clean = checkin.lstrip("T")
        if not re.match(r"^\d{2}:\d{2}:\d{2}$", checkin_clean):
            checkin_clean = f"{checkin_clean}:00" if re.match(r"^\d{2}:\d{2}$", checkin_clean) else checkin_clean
        schema["checkinTime"] = f"T{checkin_clean}"
    if checkout:
        checkout_clean = checkout.lstrip("T")
        if not re.match(r"^\d{2}:\d{2}:\d{2}$", checkout_clean):
            checkout_clean = f"{checkout_clean}:00" if re.match(r"^\d{2}:\d{2}$", checkout_clean) else checkout_clean
        schema["checkoutTime"] = f"T{checkout_clean}"

    if star_rating:
        schema["starRating"] = {
            "@type": "Rating",
            "ratingValue": str(star_rating),
            "bestRating": "5"
        }

    if price_range:
        schema["priceRange"] = price_range

    if images:
        if len(images) == 1:
            schema["image"] = _image_object(images[0])
        else:
            schema["image"] = [_image_object(img) for img in images[:5]]

    if booking_url:
        schema["potentialAction"] = {
            "@type": "ReserveAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": booking_url
            }
        }

    return schema


# ─── Page-Type Schema Builders ────────────────────────────────────────────────

def _schema_home(hotel_data: dict, page: dict) -> list[dict]:
    """Home page: Hotel + WebSite + BreadcrumbList."""
    schemas = []

    # 1. Hotel schema
    hotel_schema = _hotel_base(hotel_data, page["url"])
    hotel_schema["@id"] = f"{page['url']}#hotel"
    schemas.append(hotel_schema)

    # 2. WebSite schema with SearchAction
    website_schema = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": f"{page['url']}#website",
        "name": hotel_data.get("name", ""),
        "url": page["url"],
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{page['url']}/search?q={{search_term_string}}"
            },
            "query-input": "required name=search_term_string"
        }
    }
    schemas.append(website_schema)

    # 3. Organization schema
    telephone = hotel_data.get("telephone", "")
    org_schema = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": hotel_data.get("name", ""),
        "url": page["url"],
        "logo": {
            "@type": "ImageObject",
            "url": hotel_data.get("logoUrl", f"{page['url']}/logo.png")
        }
    }
    if telephone:
        org_schema["telephone"] = telephone
    if hotel_data.get("email"):
        org_schema["email"] = hotel_data["email"]
    schemas.append(org_schema)

    return schemas


def _schema_rooms(hotel_data: dict, page: dict) -> list[dict]:
    """Rooms page: Hotel + Accommodation offers."""
    schemas = []

    hotel_schema = _hotel_base(hotel_data, page["url"])
    hotel_schema["@id"] = f"{page['url']}#hotel"

    # Add room offers if data provided
    room_types = hotel_data.get("roomTypes", [])
    if room_types:
        offers = []
        for room in room_types:
            offer = {
                "@type": "Offer",
                "name": room.get("name", "Guest Room"),
                "description": room.get("description", ""),
                "url": hotel_data.get("bookingUrl", page["url"])
            }
            if room.get("price"):
                offer["price"] = str(room["price"])
                offer["priceCurrency"] = hotel_data.get("currency", "USD")
            offers.append(offer)
        hotel_schema["offers"] = offers if len(offers) > 1 else offers[0]

    schemas.append(hotel_schema)

    # BreadcrumbList
    schemas.append(_schema_breadcrumb([
        (hotel_data.get("name", "Home"), hotel_data.get("websiteUrl", "")),
        ("Rooms & Suites", page["url"])
    ]))
    return schemas


def _schema_dining(hotel_data: dict, page: dict) -> list[dict]:
    """Dining page: FoodEstablishment + Hotel mention."""
    schemas = []

    hotel_name = hotel_data.get("name", "")
    address = hotel_data.get("address", {})
    telephone = hotel_data.get("telephone", "")
    geo = hotel_data.get("geo", {})

    dining_schema = {
        "@context": "https://schema.org",
        "@type": "FoodEstablishment",
        "name": f"{hotel_name} Restaurant",
        "url": page["url"],
        "address": _schema_address(address),
        "parentOrganization": {
            "@type": "Hotel",
            "name": hotel_name,
            "url": hotel_data.get("websiteUrl", "")
        },
        "servesCuisine": hotel_data.get("cuisineType", "International"),
        "priceRange": hotel_data.get("priceRange", "$$"),
    }

    if telephone:
        dining_schema["telephone"] = telephone
    if geo.get("latitude"):
        dining_schema["geo"] = _schema_geo(geo)

    hours = hotel_data.get("diningHours", {})
    if hours:
        dining_schema["openingHoursSpecification"] = [
            {
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                "opens": hours.get("opens", "07:00"),
                "closes": hours.get("closes", "22:00")
            }
        ]

    schemas.append(dining_schema)
    schemas.append(_schema_breadcrumb([
        (hotel_name, hotel_data.get("websiteUrl", "")),
        ("Dining", page["url"])
    ]))
    return schemas


def _schema_gallery(hotel_data: dict, page: dict) -> list[dict]:
    """Gallery page: ImageGallery."""
    hotel_name = hotel_data.get("name", "")
    images = hotel_data.get("images", [])

    gallery_schema = {
        "@context": "https://schema.org",
        "@type": "ImageGallery",
        "name": f"{hotel_name} — Photo Gallery",
        "url": page["url"],
        "about": {
            "@type": "Hotel",
            "name": hotel_name,
            "url": hotel_data.get("websiteUrl", "")
        }
    }

    if images:
        gallery_schema["image"] = [_image_object(img, f"{hotel_name} photo") for img in images[:10]]

    breadcrumb = _schema_breadcrumb([
        (hotel_name, hotel_data.get("websiteUrl", "")),
        ("Gallery", page["url"])
    ])
    return [gallery_schema, breadcrumb]


def _schema_attractions(hotel_data: dict, page: dict) -> list[dict]:
    """Local Attractions page: ItemList of TouristAttraction."""
    hotel_name = hotel_data.get("name", "")
    attractions = hotel_data.get("localAttractions", [])

    schemas = []

    if attractions:
        items = []
        for i, attr in enumerate(attractions, 1):
            item = {
                "@type": "ListItem",
                "position": i,
                "item": {
                    "@type": "TouristAttraction",
                    "name": attr.get("name", f"Attraction {i}"),
                    "description": attr.get("description", ""),
                    "url": attr.get("url", "")
                }
            }
            if attr.get("distance"):
                item["item"]["distance"] = {
                    "@type": "QuantitativeValue",
                    "value": attr["distance"],
                    "unitCode": "KMT"
                }
            items.append(item)

        schemas.append({
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": f"Local Attractions near {hotel_name}",
            "url": page["url"],
            "numberOfItems": len(items),
            "itemListElement": items
        })
    else:
        # Generic tourist attraction page without item data
        schemas.append({
            "@context": "https://schema.org",
            "@type": "WebPage",
            "@id": page["url"],
            "name": f"Local Attractions near {hotel_name}",
            "url": page["url"],
            "description": f"Discover local attractions and activities near {hotel_name}.",
            "about": {"@type": "Hotel", "name": hotel_name}
        })

    schemas.append(_schema_breadcrumb([
        (hotel_name, hotel_data.get("websiteUrl", "")),
        ("Local Attractions", page["url"])
    ]))
    return schemas


def _schema_offers(hotel_data: dict, page: dict) -> list[dict]:
    """Offers/Deals page: Offer + Hotel."""
    hotel_name = hotel_data.get("name", "")
    offers_data = hotel_data.get("specialOffers", [])
    booking_url = hotel_data.get("bookingUrl", page["url"])

    schemas = []

    if offers_data:
        for offer in offers_data:
            offer_schema = {
                "@context": "https://schema.org",
                "@type": "Offer",
                "name": offer.get("name", "Special Offer"),
                "description": offer.get("description", ""),
                "url": booking_url,
                "seller": {"@type": "Hotel", "name": hotel_name},
                "availability": "https://schema.org/InStock"
            }
            if offer.get("price"):
                offer_schema["price"] = str(offer["price"])
                offer_schema["priceCurrency"] = hotel_data.get("currency", "USD")
            if offer.get("validThrough"):
                offer_schema["priceValidUntil"] = offer["validThrough"]
            schemas.append(offer_schema)
    else:
        # Fallback: WebPage schema
        schemas.append({
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": f"Special Offers — {hotel_name}",
            "url": page["url"],
            "description": f"Explore exclusive deals and packages at {hotel_name}.",
            "about": {"@type": "Hotel", "name": hotel_name}
        })

    schemas.append(_schema_breadcrumb([
        (hotel_name, hotel_data.get("websiteUrl", "")),
        ("Offers & Deals", page["url"])
    ]))
    return schemas


def _schema_blog_article(hotel_data: dict, page: dict) -> list[dict]:
    """Blog/News page: Blog or BlogPosting."""
    hotel_name = hotel_data.get("name", "")

    blog_schema = {
        "@context": "https://schema.org",
        "@type": "Blog",
        "name": f"{hotel_name} Blog",
        "url": page["url"],
        "description": f"News, stories, and updates from {hotel_name}.",
        "publisher": {
            "@type": "Organization",
            "name": hotel_name,
            "url": hotel_data.get("websiteUrl", ""),
            "logo": {
                "@type": "ImageObject",
                "url": hotel_data.get("logoUrl", "")
            }
        }
    }
    breadcrumb = _schema_breadcrumb([
        (hotel_name, hotel_data.get("websiteUrl", "")),
        ("Blog", page["url"])
    ])
    return [blog_schema, breadcrumb]


def _schema_contact(hotel_data: dict, page: dict) -> list[dict]:
    """Contact page: Hotel + ContactPage."""
    schemas = []

    hotel_schema = _hotel_base(hotel_data, page["url"])
    hotel_schema["@type"] = ["Hotel", "LocalBusiness"]
    hotel_schema["@id"] = f"{page['url']}#hotel"

    contact_page = {
        "@context": "https://schema.org",
        "@type": "ContactPage",
        "name": f"Contact {hotel_data.get('name', '')}",
        "url": page["url"],
        "about": {"@type": "Hotel", "name": hotel_data.get("name", "")}
    }

    schemas.append(hotel_schema)
    schemas.append(contact_page)
    schemas.append(_schema_breadcrumb([
        (hotel_data.get("name", ""), hotel_data.get("websiteUrl", "")),
        ("Contact", page["url"])
    ]))
    return schemas


def _schema_about(hotel_data: dict, page: dict) -> list[dict]:
    """About page: AboutPage + Hotel."""
    hotel_name = hotel_data.get("name", "")

    about_page = {
        "@context": "https://schema.org",
        "@type": "AboutPage",
        "name": f"About {hotel_name}",
        "url": page["url"],
        "description": hotel_data.get("description", f"Learn about {hotel_name}."),
        "about": {
            "@type": "Hotel",
            "name": hotel_name,
            "url": hotel_data.get("websiteUrl", ""),
            "foundingDate": hotel_data.get("foundingYear", "")
        }
    }
    breadcrumb = _schema_breadcrumb([
        (hotel_name, hotel_data.get("websiteUrl", "")),
        ("About Us", page["url"])
    ])
    return [about_page, breadcrumb]


def _schema_spa(hotel_data: dict, page: dict) -> list[dict]:
    """Spa page: HealthAndBeautyBusiness."""
    hotel_name = hotel_data.get("name", "")
    address = hotel_data.get("address", {})

    spa_schema = {
        "@context": "https://schema.org",
        "@type": "HealthAndBeautyBusiness",
        "name": f"{hotel_name} Spa & Wellness",
        "url": page["url"],
        "address": _schema_address(address),
        "parentOrganization": {
            "@type": "Hotel",
            "name": hotel_name
        }
    }
    if hotel_data.get("telephone"):
        spa_schema["telephone"] = hotel_data["telephone"]

    breadcrumb = _schema_breadcrumb([
        (hotel_name, hotel_data.get("websiteUrl", "")),
        ("Spa & Wellness", page["url"])
    ])
    return [spa_schema, breadcrumb]


def _schema_events(hotel_data: dict, page: dict) -> list[dict]:
    """Events/Weddings page: EventVenue."""
    hotel_name = hotel_data.get("name", "")
    address = hotel_data.get("address", {})
    geo = hotel_data.get("geo", {})

    venue_schema = {
        "@context": "https://schema.org",
        "@type": "EventVenue",
        "name": f"{hotel_name} Event Spaces",
        "url": page["url"],
        "address": _schema_address(address),
    }
    if geo.get("latitude"):
        venue_schema["geo"] = _schema_geo(geo)
    if hotel_data.get("telephone"):
        venue_schema["telephone"] = hotel_data["telephone"]

    breadcrumb = _schema_breadcrumb([
        (hotel_name, hotel_data.get("websiteUrl", "")),
        ("Events & Weddings", page["url"])
    ])
    return [venue_schema, breadcrumb]


def _schema_faq(hotel_data: dict, page: dict) -> list[dict]:
    """FAQ page: FAQPage."""
    hotel_name = hotel_data.get("name", "")
    faqs = hotel_data.get("faqs", [])

    if not faqs:
        checkin = hotel_data.get("checkinTime", "14:00")
        checkout = hotel_data.get("checkoutTime", "12:00")
        faqs = [
            {
                "q": "What time is check-in?",
                "a": f"Check-in is from {checkin}."
            },
            {
                "q": "What time is check-out?",
                "a": f"Check-out is by {checkout}."
            },
            {
                "q": "Do you offer free Wi-Fi?",
                "a": "Yes, complimentary Wi-Fi is available throughout the property."
            }
        ]

    faq_schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "name": f"FAQ — {hotel_name}",
        "url": page["url"],
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["q"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": item["a"]
                }
            }
            for item in faqs
        ]
    }
    breadcrumb = _schema_breadcrumb([
        (hotel_name, hotel_data.get("websiteUrl", "")),
        ("FAQ", page["url"])
    ])
    return [faq_schema, breadcrumb]


def _schema_generic(hotel_data: dict, page: dict) -> list[dict]:
    """Fallback: generic WebPage schema."""
    hotel_name = hotel_data.get("name", "")
    page_schema = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": page.get("title") or page["url"],
        "url": page["url"],
        "description": page.get("description", ""),
        "isPartOf": {
            "@type": "WebSite",
            "name": hotel_name,
            "url": hotel_data.get("websiteUrl", "")
        }
    }
    breadcrumb = _schema_breadcrumb([
        (hotel_name, hotel_data.get("websiteUrl", "")),
        (page.get("title", "Page"), page["url"])
    ])
    return [page_schema, breadcrumb]


def _schema_breadcrumb(items: list[tuple]) -> dict:
    """Build BreadcrumbList schema from list of (name, url) tuples."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": name,
                "item": url
            }
            for i, (name, url) in enumerate(items) if url
        ]
    }


# ─── Main Generator ───────────────────────────────────────────────────────────

PAGE_TYPE_HANDLERS = {
    "home":        _schema_home,
    "rooms":       _schema_rooms,
    "dining":      _schema_dining,
    "gallery":     _schema_gallery,
    "attractions": _schema_attractions,
    "offers":      _schema_offers,
    "blog":        _schema_blog_article,
    "contact":     _schema_contact,
    "about":       _schema_about,
    "spa":         _schema_spa,
    "events":      _schema_events,
    "faq":         _schema_faq,
}


def generate_schema_for_page(hotel_data: dict, page: dict) -> dict:
    """
    Generate JSON-LD schema for a single page.
    Returns {"page_url": str, "page_type": str, "schemas": list, "json_ld_html": str}
    """
    page_type = page.get("page_type", "other")
    handler = PAGE_TYPE_HANDLERS.get(page_type, _schema_generic)
    schemas = handler(hotel_data, page)

    # Produce <script> tags for each schema
    script_tags = []
    for schema in schemas:
        json_str = json.dumps(schema, indent=2, ensure_ascii=False)
        script_tags.append(
            f'<script type="application/ld+json">\n{json_str}\n</script>'
        )

    return {
        "page_url": page["url"],
        "page_type": page_type,
        "page_title": page.get("title", ""),
        "schemas": schemas,
        "json_ld_html": "\n\n".join(script_tags),
        "schema_count": len(schemas),
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


from typing import Any

def _to_primitive(val) -> Any:
    if isinstance(val, list):
        if not val:
            return ""
        return _to_primitive(val[0])
    if isinstance(val, dict):
        for k in ["url", "ratingValue", "value", "name", "text", "streetAddress", "telephone"]:
            if k in val and val[k]:
                return val[k]
        non_at = [k for k in val.keys() if not k.startswith("@")]
        if non_at:
            return val[non_at[0]]
        return ""
    return val


def _get_guideline_target_keys(ops: list[dict]) -> set[str]:
    keys = set()
    if not ops:
        return keys
    for op in ops:
        verb = op.get("op")
        if verb in ("add", "rename"):
            if op.get("key"):
                keys.add(op.get("key"))
            if verb == "rename" and op.get("to"):
                keys.add(op.get("to"))
        elif verb in ("set", "unset", "append", "merge", "copy", "move"):
            path = op.get("path") or op.get("to") or op.get("key") or op.get("from")
            if path:
                keys.add(path.split(".")[0])
        elif verb == "if":
            keys.update(_get_guideline_target_keys(op.get("then", [])))
    return keys


def _to_dict(val, ex_val: dict, source_data: dict, allowed_extra_keys: set = None) -> dict:
    if isinstance(val, dict):
        return val
    prim = _to_primitive(val)
    res = {}
    if "@type" in ex_val:
        res["@type"] = ex_val["@type"]
    if "@id" in ex_val:
        res["@id"] = ex_val["@id"]
        
    non_at_keys = [k for k in ex_val.keys() if k not in ["@context", "@type", "@id"]]
    target_key = None
    if "url" in non_at_keys:
        target_key = "url"
    elif "ratingValue" in non_at_keys:
        target_key = "ratingValue"
    elif "value" in non_at_keys:
        target_key = "value"
    elif "name" in non_at_keys:
        target_key = "name"
    elif "text" in non_at_keys:
        target_key = "text"
    elif len(non_at_keys) == 1:
        target_key = non_at_keys[0]
        
    if target_key:
        res[target_key] = prim
        
    return align_with_example_structure(res, ex_val, source_data, allowed_extra_keys)


def align_with_example_structure(schema: dict, example: dict, source_data: dict, allowed_extra_keys: set = None) -> dict:
    """
    Recursively aligns a generated schema dictionary with the structure of an example schema.
    No dummy/placeholder information is taken from the example.
    """
    if not isinstance(schema, dict) or not isinstance(example, dict):
        return schema

    aligned = {}
    
    # 1. Preserve JSON-LD context keys
    for k in ["@context", "@type", "@id"]:
        if k in schema:
            aligned[k] = schema[k]
        elif k in example:
            aligned[k] = example[k]

    # 2. Conform to example layout
    for key, ex_val in example.items():
        if key in ["@context", "@type", "@id"]:
            continue

        val = schema.get(key)
        
        # If missing in schema, look in source_data (hotel_data)
        if val is None:
            if key in source_data:
                val = source_data[key]
            elif key == "image":
                val = source_data.get("images") or source_data.get("image")
            elif key == "logo":
                val = source_data.get("logoUrl") or source_data.get("logo")
                if not val and "websiteUrl" in source_data:
                    val = f"{source_data['websiteUrl'].rstrip('/')}/logo.png"
            elif key == "sameAs":
                val = source_data.get("sameAs") or source_data.get("social_profiles") or source_data.get("socials")
            elif key == "url":
                val = source_data.get("websiteUrl") or source_data.get("url")
            elif key == "email":
                val = source_data.get("email") or source_data.get("emails")
            elif key == "telephone":
                val = source_data.get("telephone") or source_data.get("phones")
            elif key == "streetAddress" and "address" in source_data:
                val = source_data["address"].get("streetAddress")
            elif key == "addressLocality" and "address" in source_data:
                val = source_data["address"].get("addressLocality")
            elif key == "addressRegion" and "address" in source_data:
                val = source_data["address"].get("addressRegion")
            elif key == "postalCode" and "address" in source_data:
                val = source_data["address"].get("postalCode")
            elif key == "addressCountry" and "address" in source_data:
                val = source_data["address"].get("addressCountry")
            elif key == "latitude" and "geo" in source_data:
                val = source_data["geo"].get("latitude")
            elif key == "longitude" and "geo" in source_data:
                val = source_data["geo"].get("longitude")

        # Now handle formatting matching ex_val structure
        if val is not None:
            if isinstance(ex_val, list):
                val_list = val if isinstance(val, list) else [val]
                ex_item = ex_val[0] if len(ex_val) > 0 else {}
                
                aligned_list = []
                for item in val_list:
                    if isinstance(ex_item, dict):
                        aligned_list.append(_to_dict(item, ex_item, source_data, allowed_extra_keys))
                    else:
                        aligned_list.append(_to_primitive(item))
                aligned[key] = aligned_list
                
            elif isinstance(ex_val, dict):
                aligned[key] = _to_dict(val, ex_val, source_data, allowed_extra_keys)
                
            else:
                aligned[key] = _to_primitive(val)
        else:
            if isinstance(ex_val, dict) and "@type" in ex_val:
                populated = align_with_example_structure({}, ex_val, source_data, allowed_extra_keys)
                if len(populated) > 1:
                    aligned[key] = populated

    # 3. Add other keys from schema that aren't in example ONLY if they are explicitly allowed
    if allowed_extra_keys:
        for key, val in schema.items():
            if key not in aligned and key in allowed_extra_keys:
                aligned[key] = val

    return aligned


def generate_all_schemas(hotel_data: dict, pages: list[dict], user_id: int = None) -> dict:
    """
    Generate schemas for all pages.
    Optionally enriched with trend digest when user_id is provided.
    Returns dict keyed by page URL.
    """
    # Build trend digest once (non-blocking — uses cache)
    trend_notes = []
    deprecated_props = []
    example_schemas = []
    required_props = []
    guideline_ops = []
    try:
        from backend.trend_checker import build_trend_digest
        digest = build_trend_digest(user_id=user_id)
        trend_notes = digest.get("notes", [])
        deprecated_props = digest.get("deprecated_properties", [])
        example_schemas = digest.get("example_schemas", [])
        required_props = digest.get("required_properties", [])

        # Parse guideline instructions
        user_guidelines = digest.get("user_guidelines", [])
        for gl in user_guidelines:
            content = gl.get("content", "")
            if content.strip():
                try:
                    from backend.regeneration_engine import parse_instructions
                    ops = parse_instructions(content)
                    guideline_ops.extend(ops)
                except Exception as e:
                    print(f"[Schema] Guideline parse skip: {e}")

        if trend_notes:
            print(f"[Schema] Trend digest applied: {len(trend_notes)} notes")
    except Exception as e:
        print(f"[Schema] Trend digest skipped: {e}")

    all_schemas = {}
    for page in pages:
        result = generate_schema_for_page(hotel_data, page)
        result["trend_notes"] = trend_notes

        # 1. Apply required properties if missing and present in hotel_data
        if required_props:
            for schema in result.get("schemas", []):
                for prop in required_props:
                    if prop not in schema or not schema[prop]:
                        val = None
                        if prop in hotel_data:
                            val = hotel_data[prop]
                        elif prop == "streetAddress" and "address" in hotel_data:
                            val = hotel_data["address"].get("streetAddress")
                        elif prop == "addressLocality" and "address" in hotel_data:
                            val = hotel_data["address"].get("addressLocality")
                        elif prop == "addressRegion" and "address" in hotel_data:
                            val = hotel_data["address"].get("addressRegion")
                        elif prop == "postalCode" and "address" in hotel_data:
                            val = hotel_data["address"].get("postalCode")
                        elif prop == "addressCountry" and "address" in hotel_data:
                            val = hotel_data["address"].get("addressCountry")
                        elif prop == "latitude" and "geo" in hotel_data:
                            val = hotel_data["geo"].get("latitude")
                        elif prop == "longitude" and "geo" in hotel_data:
                            val = hotel_data["geo"].get("longitude")
                        
                        if val is not None:
                            schema[prop] = val

        # 2. Apply guideline ops if any
        if guideline_ops:
            try:
                from backend.regeneration_engine import apply_operations
                schemas = result.get("schemas", [])
                patched_schemas, warnings = apply_operations(schemas, guideline_ops)
                result["schemas"] = patched_schemas
                if warnings:
                    result["guideline_warnings"] = warnings
            except Exception as e:
                print(f"[Schema] Guideline apply skip: {e}")

                if matched_example:
                    allowed_extra = _get_guideline_target_keys(guideline_ops)
                    aligned_schema = align_with_example_structure(
                        schema, matched_example, hotel_data, allowed_extra_keys=allowed_extra
                    )
                    aligned_schemas.append(aligned_schema)
                else:
                    aligned_schemas.append(schema)
            result["schemas"] = aligned_schemas

        # 4. Auto-strip deprecated properties at generation time
        if deprecated_props:
            all_stripped = []
            for schema in result.get("schemas", []):
                stripped = [k for k in list(schema.keys()) if k in deprecated_props]
                for k in stripped:
                    del schema[k]
                all_stripped.extend(stripped)
            if all_stripped:
                result["deprecated_stripped"] = list(set(all_stripped))

        # Re-emit HTML with final schemas
        script_tags = [
            f'<script type="application/ld+json">\n{json.dumps(s, indent=2, ensure_ascii=False)}\n</script>'
            for s in result["schemas"]
        ]
        result["json_ld_html"] = "\n\n".join(script_tags)

        all_schemas[page["url"]] = result
        print(f"[Schema] Generated {result['schema_count']} schema(s) for [{page.get('page_type')}] {page['url'][:70]}")

    return all_schemas
