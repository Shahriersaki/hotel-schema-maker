"""
Feed System Routes v2 — KB with priority, corrections, trends, multi-page patching.
All write routes require contributor or admin role.
"""

from flask import Blueprint, request, jsonify
from backend.auth import require_auth, can_write, require_admin
from backend.database import (
    create_kb_entry, get_kb_entries, get_kb_entries_prioritized,
    get_kb_entry, delete_kb_entry,
    create_correction, get_corrections, resolve_correction,
    get_latest_trend_snapshots, get_project, update_project,
    log_action
)
from backend.trend_checker import fetch_all_trends, build_trend_digest
from backend.regeneration_engine import (
    regenerate_corrected_schema, regenerate_all_schemas_with_kb,
    patch_multi_page_schemas, parse_instructions
)

feed_bp = Blueprint("feed", __name__)

VALID_ENTRY_TYPES = {
    "guideline":       "A schema.org or Google guideline, rule, or best practice",
    "validator_error": "An error found by Google Rich Results Test or schema.org validator",
    "deprecated":      "Properties to avoid (comma-separated list)",
    "required":        "Properties to add as required (comma-separated list)",
    "recommended":     "Properties to treat as recommended (comma-separated list)",
    "example":         "A reference JSON-LD example or snippet",
    "news":            "Latest structured data news/updates",
    "note":            "A general note or reminder",
}

SOURCE_PRIORITY_LABELS = {
    "google":           100,
    "google search central": 95,
    "schema.org":       90,
    "schema.org validator": 88,
    "user":             80,
    "manual":           75,
    "auto-suggested":   50,
}

# ─── Knowledge Base ───────────────────────────────────────────────────────────

@feed_bp.route("/kb", methods=["GET"])
@require_auth
def list_kb():
    user_id     = request.current_user["user_id"]
    entry_type  = request.args.get("type")
    prioritized = request.args.get("sorted", "true").lower() == "true"

    if prioritized:
        entries = get_kb_entries_prioritized(user_id, entry_type)
    else:
        entries = get_kb_entries(user_id, entry_type)

    return jsonify({
        "entries": entries,
        "count": len(entries),
        "valid_types": VALID_ENTRY_TYPES,
        "source_priority": SOURCE_PRIORITY_LABELS
    })


@feed_bp.route("/kb", methods=["POST"])
@require_auth
@can_write
def add_kb_entry():
    user_id  = request.current_user["user_id"]
    data     = request.get_json(silent=True) or {}
    etype    = (data.get("entry_type") or "note").strip()
    title    = (data.get("title") or "").strip()
    content  = (data.get("content") or "").strip()
    source   = (data.get("source") or "").strip()
    tags     = data.get("tags") or []

    if not title:
        return jsonify({"error": "title is required."}), 400
    if not content:
        return jsonify({"error": "content is required."}), 400
    if etype not in VALID_ENTRY_TYPES:
        return jsonify({"error": f"Invalid entry_type. Must be one of: {list(VALID_ENTRY_TYPES)}"}), 400

    entry = create_kb_entry(user_id, etype, title, content, source, tags)
    log_action(user_id, "add_kb_entry", "kb", str(entry["id"]), title,
               request.remote_addr)
    return jsonify({"message": "Knowledge base entry added.", "entry": entry}), 201


@feed_bp.route("/kb/<int:entry_id>", methods=["GET"])
@require_auth
def get_kb(entry_id):
    user_id = request.current_user["user_id"]
    entry = get_kb_entry(entry_id, user_id)
    if not entry:
        return jsonify({"error": "Entry not found."}), 404
    return jsonify({"entry": entry})


@feed_bp.route("/kb/<int:entry_id>", methods=["DELETE"])
@require_auth
@can_write
def delete_kb(entry_id):
    user_id = request.current_user["user_id"]
    success = delete_kb_entry(entry_id, user_id)
    if not success:
        return jsonify({"error": "Entry not found."}), 404
    log_action(user_id, "delete_kb_entry", "kb", str(entry_id), "", request.remote_addr)
    return jsonify({"message": "Entry removed from knowledge base."})


@feed_bp.route("/kb/bulk", methods=["POST"])
@require_auth
@can_write
def add_bulk_kb():
    user_id     = request.current_user["user_id"]
    data        = request.get_json(silent=True) or {}
    entries_data = data.get("entries", [])

    if not entries_data or not isinstance(entries_data, list):
        return jsonify({"error": "entries must be a non-empty list."}), 400

    created, errors = [], []
    for i, ed in enumerate(entries_data):
        try:
            entry = create_kb_entry(
                user_id, ed.get("entry_type", "note"),
                ed.get("title", f"Entry {i+1}"),
                ed.get("content", ""),
                ed.get("source", ""), ed.get("tags", [])
            )
            created.append(entry)
        except Exception as e:
            errors.append({"index": i, "error": str(e)})

    log_action(user_id, "bulk_kb", "kb", "", f"Added {len(created)}", request.remote_addr)
    return jsonify({"message": f"Added {len(created)} entries.", "created": created, "errors": errors}), 201


# ─── Trends ───────────────────────────────────────────────────────────────────

@feed_bp.route("/trends", methods=["GET"])
@require_auth
def get_trends():
    force = request.args.get("force", "").lower() == "true"
    if force:
        # Only admin/contributor can force-refresh (costs bandwidth)
        if request.current_user.get("role", "viewer") not in ("admin", "contributor"):
            force = False
    try:
        trends = fetch_all_trends(force=force)
        return jsonify({"trends": trends, "from_cache": trends.get("from_cache", False)})
    except Exception as e:
        return jsonify({"error": f"Trend fetch failed: {e}"}), 500


@feed_bp.route("/trends/snapshots", methods=["GET"])
@require_auth
def get_trend_snapshots():
    snapshots = get_latest_trend_snapshots(limit=20)
    return jsonify({"snapshots": snapshots, "count": len(snapshots)})


@feed_bp.route("/trends/digest", methods=["GET"])
@require_auth
def get_digest():
    user_id = request.current_user["user_id"]
    digest  = build_trend_digest(user_id=user_id)
    return jsonify({"digest": digest})


# ─── Validate Paste ───────────────────────────────────────────────────────────

@feed_bp.route("/validate-paste", methods=["POST"])
@require_auth
def validate_paste():
    import json as _json
    user_id = request.current_user["user_id"]
    data  = request.get_json(silent=True) or {}
    paste = (data.get("paste") or "").strip()
    if not paste:
        return jsonify({"error": "paste is required."}), 400

    structured_errors = []
    try:
        parsed = _json.loads(paste)
        items  = parsed if isinstance(parsed, list) else parsed.get("errors", [])
        for item in items:
            if isinstance(item, dict):
                structured_errors.append({
                    "message":  item.get("message", str(item)),
                    "severity": item.get("severity", "ERROR"),
                    "type":     item.get("type", ""),
                    "path":     item.get("path", "")
                })
    except Exception:
        for ln in paste.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            sev = ("ERROR"   if any(w in ln.lower() for w in ["error","missing","invalid","required"])
                   else "WARNING" if "warn" in ln.lower()
                   else "INFO")
            structured_errors.append({"message": ln, "severity": sev, "type": "", "path": ""})

    # Auto-suggestions
    kb_suggestions = []
    err_text = " ".join(e["message"] for e in structured_errors).lower()

    SUGGESTIONS = [
        ("checkintime",  "checkinTime/checkoutTime ISO 8601 format",
         'checkinTime and checkoutTime must be T-prefixed: e.g. "T14:00:00"',
         "guideline"),
        ("starrating",   "starRating must be a Rating object",
         '{"@type":"Rating","ratingValue":"4","bestRating":"5"}', "guideline"),
        ("imageobject",  "image must be ImageObject",
         '{"@type":"ImageObject","url":"https://..."}', "guideline"),
        ("postaladdress","address must include @type PostalAddress",
         'address must have @type PostalAddress with streetAddress, addressLocality, addressCountry',
         "guideline"),
        ("geocoordinates","geo must be GeoCoordinates",
         '{"@type":"GeoCoordinates","latitude":0.0,"longitude":0.0}', "guideline"),
        ("contactpoint", "contactPoint must be ContactPoint type",
         '{"@type":"ContactPoint","contactType":"reservations","telephone":"+1-xxx"}', "guideline"),
        ("telephone",    "telephone should use E.164 format",
         'telephone must start with + followed by country code, e.g. +14155552671', "guideline"),
        ("amenityfeature","amenityFeature must use LocationFeatureSpecification",
         '{"@type":"LocationFeatureSpecification","name":"Free Wi-Fi","value":true}', "guideline"),
    ]

    seen = set()
    for keyword, title, content, etype in SUGGESTIONS:
        if keyword in err_text and title not in seen:
            seen.add(title)
            kb_suggestions.append({"entry_type": etype, "title": title, "content": content,
                                    "source": "Auto-suggested from paste"})

    # Also suggest auto-fix instructions
    auto_instructions = []
    if "checkintime" in err_text or "checkouttime" in err_text:
        auto_instructions.append("SET checkinTime T14:00:00")
        auto_instructions.append("SET checkoutTime T12:00:00")
    if "starrating" in err_text:
        auto_instructions.append('SET starRating {"@type":"Rating","ratingValue":"4","bestRating":"5"}')
    if "imageobject" in err_text or "image" in err_text:
        auto_instructions.append("# Image fix — replace URL with your actual image URL")
        auto_instructions.append('SET image {"@type":"ImageObject","url":"https://example.com/hotel.jpg"}')

    return jsonify({
        "structured_errors": structured_errors,
        "error_count":       len(structured_errors),
        "suggestions":       kb_suggestions,
        "auto_instructions": "\n".join(auto_instructions),
        "message": f"Parsed {len(structured_errors)} errors. {len(kb_suggestions)} KB entries suggested."
    })


# ─── Corrections ──────────────────────────────────────────────────────────────

@feed_bp.route("/projects/<int:project_id>/corrections", methods=["GET"])
@require_auth
def list_corrections(project_id):
    user_id     = request.current_user["user_id"]
    corrections = get_corrections(project_id, user_id)
    return jsonify({"corrections": corrections, "count": len(corrections)})


@feed_bp.route("/projects/<int:project_id>/corrections", methods=["POST"])
@require_auth
@can_write
def submit_correction(project_id):
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    data             = request.get_json(silent=True) or {}
    page_url         = (data.get("page_url") or "").strip()
    original_schema  = data.get("original_schema") or []
    validator_errors = data.get("validator_errors") or []
    instructions     = (data.get("instructions") or "").strip()

    if not page_url:
        return jsonify({"error": "page_url is required."}), 400
    if not original_schema:
        # Try to use existing schemas from the project
        existing = project.get("schemas_generated", {}).get(page_url, {})
        original_schema = existing.get("schemas", [])
    if not original_schema:
        return jsonify({"error": "original_schema is required (or run schema generation first)."}), 400
    if not validator_errors and not instructions:
        return jsonify({"error": "Provide validator_errors, instructions, or both."}), 400

    if isinstance(validator_errors, str):
        validator_errors = [e.strip() for e in validator_errors.splitlines() if e.strip()]

    correction = create_correction(project_id, user_id, page_url,
                                   original_schema, validator_errors, instructions)
    log_action(user_id, "submit_correction", "correction", str(correction["id"]),
               page_url, request.remote_addr)
    return jsonify({"message": "Correction submitted. Run /fix to apply.", "correction": correction}), 201


@feed_bp.route("/projects/<int:project_id>/corrections/<int:corr_id>/fix", methods=["POST"])
@require_auth
@can_write
def fix_correction(project_id, corr_id):
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    corrections = get_corrections(project_id, user_id)
    correction  = next((c for c in corrections if c["id"] == corr_id), None)
    if not correction:
        return jsonify({"error": "Correction not found."}), 404
    if correction["status"] == "resolved":
        return jsonify({"error": "Correction already resolved.", "correction": correction}), 400

    pages    = project.get("pages_found", [])
    page     = next((p for p in pages if p["url"] == correction["page_url"]),
                    {"url": correction["page_url"], "page_type": "other", "title": ""})
    hotel_data = {**project["hotel_data"], "websiteUrl": project["website_url"]}

    orig = correction["original_schema"]
    if isinstance(orig, dict):
        orig = [orig]

    try:
        result = regenerate_corrected_schema(
            original_schemas=orig,
            validator_errors=correction["validator_errors"],
            instructions=correction["instructions"],
            hotel_data=hotel_data,
            page=page,
            user_id=user_id
        )
        resolve_correction(corr_id, user_id, result["corrected_schemas"])

        # Update saved schemas
        schemas_gen = project.get("schemas_generated", {})
        if correction["page_url"] in schemas_gen:
            pd = schemas_gen[correction["page_url"]]
            pd["schemas"]         = result["corrected_schemas"]
            pd["json_ld_html"]    = result["json_ld_html"]
            pd["corrected"]       = True
            pd["correction_fixes"] = result["all_fixes"]
            update_project(project_id, user_id, {"schemas_generated": schemas_gen})

        log_action(user_id, "fix_correction", "correction", str(corr_id),
                   f"{len(result['all_fixes'])} fixes", request.remote_addr)
        return jsonify({"message": "Schema corrected and saved.", "result": result})
    except Exception as e:
        return jsonify({"error": f"Correction failed: {e}"}), 500


# ─── Multi-Page Patch ─────────────────────────────────────────────────────────

@feed_bp.route("/projects/<int:project_id>/patch-pages", methods=["POST"])
@require_auth
@can_write
def patch_pages(project_id):
    """
    Apply instruction DSL to multiple pages at once.

    Body:
      instructions  – DSL string
      page_urls     – optional list of URLs to target (empty = all)
      target_type   – optional @type filter (e.g. "Hotel")
    """
    user_id  = request.current_user["user_id"]
    project  = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    data         = request.get_json(silent=True) or {}
    instructions = (data.get("instructions") or "").strip()
    page_urls    = data.get("page_urls") or []
    target_type  = data.get("target_type") or None

    if not instructions:
        return jsonify({"error": "instructions is required."}), 400

    schemas_gen = project.get("schemas_generated", {})
    if not schemas_gen:
        return jsonify({"error": "No schemas generated yet. Run schema generation first."}), 400

    ops = parse_instructions(instructions)
    updated_schemas, summary = patch_multi_page_schemas(schemas_gen, page_urls, ops, target_type)
    update_project(project_id, user_id, {"schemas_generated": updated_schemas})

    patched_count = sum(1 for v in summary.values() if v.get("status") == "patched")
    log_action(user_id, "patch_pages", "project", str(project_id),
               f"{patched_count} pages patched", request.remote_addr)
    return jsonify({
        "message":       f"Patched {patched_count} pages.",
        "summary":       summary,
        "ops_applied":   len([o for o in ops if o.get("op") not in ("note",)]),
        "schemas":       updated_schemas
    })


# ─── Parse Instructions Preview ───────────────────────────────────────────────

@feed_bp.route("/parse-instructions", methods=["POST"])
@require_auth
def preview_instructions():
    """Parse an instruction string and return structured ops (dry-run)."""
    data         = request.get_json(silent=True) or {}
    instructions = (data.get("instructions") or "").strip()
    if not instructions:
        return jsonify({"error": "instructions is required."}), 400

    ops = parse_instructions(instructions)
    return jsonify({
        "ops":       ops,
        "op_count":  len(ops),
        "notes":     [o["text"] for o in ops if o.get("op") == "note"],
        "warnings":  [o["message"] for o in ops if o.get("op") == "warn"],
    })


# ─── Regenerate All ───────────────────────────────────────────────────────────

@feed_bp.route("/projects/<int:project_id>/regenerate", methods=["POST"])
@require_auth
@can_write
def regenerate_project(project_id):
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    pages = project.get("pages_found", [])
    if not pages:
        return jsonify({"error": "No pages found. Run crawl first."}), 400

    hotel_data = {**project["hotel_data"], "websiteUrl": project["website_url"]}
    try:
        schemas = regenerate_all_schemas_with_kb(hotel_data, pages, user_id)
        update_project(project_id, user_id, {"schemas_generated": schemas})
        log_action(user_id, "regenerate_all", "project", str(project_id),
                   f"{len(schemas)} pages", request.remote_addr)
        return jsonify({
            "message":    f"Regenerated schemas for {len(schemas)} pages using KB + trends.",
            "schemas":    schemas,
            "page_count": len(schemas)
        })
    except Exception as e:
        return jsonify({"error": f"Regeneration failed: {e}"}), 500


@feed_bp.route("/projects/<int:project_id>/fix-page-error", methods=["POST"])
@require_auth
@can_write
def fix_page_error(project_id):
    """
    On-the-spot resolver with deep page scraping:
    1. Crawls the page URL to extract images, logo, emails, phones, social profiles,
       booking links, FAQs, and other structured information.
    2. Translates the pasted validator error text into fix instructions.
    3. Regenerates the schema with those fixes.
    4. Saves it back to the project.
    """
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    data       = request.get_json(silent=True) or {}
    page_url   = (data.get("page_url") or "").strip()
    error_text = (data.get("error_text") or "").strip()

    if not page_url:
        return jsonify({"error": "page_url is required."}), 400
    if not error_text:
        return jsonify({"error": "error_text is required."}), 400

    schemas_gen = project.get("schemas_generated", {})
    existing = schemas_gen.get(page_url, {})
    if not existing:
        return jsonify({"error": "Generate schemas first before submitting corrections."}), 400

    # ── Deep page scraper ─────────────────────────────────────────────────────
    scraped = {
        "images": [],
        "logo": "",
        "emails": [],
        "phones": [],
        "social_profiles": [],
        "booking_urls": [],
        "faq_items": [],
        "page_title": "",
        "meta_description": "",
        "og_image": "",
        "canonical_url": "",
    }
    try:
        import requests as _requests
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        import re as _re

        resp = _requests.get(page_url, headers={"User-Agent": "HotelSchemaMaker/2.0"}, timeout=12)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")

            # --- Title ---
            title_tag = soup.find("title")
            if title_tag:
                scraped["page_title"] = title_tag.get_text(strip=True)

            # --- Meta description ---
            meta_desc = soup.find("meta", attrs={"name": _re.compile(r"description", _re.I)})
            if meta_desc and meta_desc.get("content"):
                scraped["meta_description"] = meta_desc["content"]

            # --- Canonical URL ---
            canon = soup.find("link", rel="canonical")
            if canon and canon.get("href"):
                scraped["canonical_url"] = canon["href"]

            # --- OG Image ---
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                scraped["og_image"] = og_img["content"]

            # --- Images (all <img> tags) ---
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src")
                if src:
                    absolute_url = urljoin(page_url, src)
                    alt = img.get("alt", "")
                    scraped["images"].append({"url": absolute_url, "alt": alt})

            # --- Logo detection ---
            # Check for <img> with logo in class/id/alt/src
            logo_candidates = []
            for img in soup.find_all("img"):
                attrs_text = " ".join([
                    img.get("class", [""])[0] if isinstance(img.get("class"), list) else str(img.get("class", "")),
                    img.get("id", ""),
                    img.get("alt", ""),
                    img.get("src", ""),
                ]).lower()
                if "logo" in attrs_text:
                    src = img.get("src") or img.get("data-src")
                    if src:
                        logo_candidates.append(urljoin(page_url, src))
            # Also check <link rel="icon"> or <link rel="shortcut icon">
            for link in soup.find_all("link", rel=_re.compile(r"icon", _re.I)):
                href = link.get("href")
                if href:
                    logo_candidates.append(urljoin(page_url, href))
            if logo_candidates:
                scraped["logo"] = logo_candidates[0]

            # --- Email addresses ---
            full_text = soup.get_text()
            email_pattern = _re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
            scraped["emails"] = list(set(email_pattern.findall(full_text)))[:5]
            # Also check mailto: links
            for a_tag in soup.find_all("a", href=_re.compile(r"^mailto:", _re.I)):
                email = a_tag["href"].replace("mailto:", "").split("?")[0].strip()
                if email and email not in scraped["emails"]:
                    scraped["emails"].append(email)

            # --- Phone numbers ---
            phone_pattern = _re.compile(r"(\+?\d[\d\s\-().]{7,}\d)")
            scraped["phones"] = list(set(phone_pattern.findall(full_text)))[:5]
            # Also check tel: links
            for a_tag in soup.find_all("a", href=_re.compile(r"^tel:", _re.I)):
                phone = a_tag["href"].replace("tel:", "").strip()
                if phone and phone not in scraped["phones"]:
                    scraped["phones"].append(phone)

            # --- Social profile links ---
            social_domains = [
                "facebook.com", "instagram.com", "twitter.com", "x.com",
                "linkedin.com", "youtube.com", "tiktok.com", "pinterest.com",
                "tripadvisor.com",
            ]
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                for domain in social_domains:
                    if domain in href.lower():
                        full = urljoin(page_url, href)
                        if full not in scraped["social_profiles"]:
                            scraped["social_profiles"].append(full)

            # --- Booking / Reservation URLs ---
            booking_keywords = ["book", "reserv", "reserve", "booking", "book-now",
                                "book-room", "check-availability"]
            for a_tag in soup.find_all("a", href=True):
                href_text = (a_tag.get("href", "") + " " + a_tag.get_text()).lower()
                if any(kw in href_text for kw in booking_keywords):
                    full = urljoin(page_url, a_tag["href"])
                    if full not in scraped["booking_urls"]:
                        scraped["booking_urls"].append(full)

            # --- FAQ content ---
            faq_sections = soup.find_all(["details", "div", "section"],
                                          class_=_re.compile(r"faq|accordion|question", _re.I))
            for faq in faq_sections[:10]:
                q_el = faq.find(["summary", "h2", "h3", "h4", "dt", "button"])
                a_el = faq.find(["p", "dd", "div"])
                if q_el and a_el:
                    scraped["faq_items"].append({
                        "question": q_el.get_text(strip=True)[:300],
                        "answer": a_el.get_text(strip=True)[:500]
                    })

    except Exception as e:
        print(f"[On-the-spot fix] Failed to crawl page: {e}")

    # ── Build correction instructions from error text + scraped data ──────────
    instructions = []
    error_lower = error_text.lower()
    hotel_data = project["hotel_data"]

    # Image / Logo fixes
    if "image" in error_lower or "logo" in error_lower or "photo" in error_lower:
        best_img = scraped["og_image"] or (scraped["images"][0]["url"] if scraped["images"] else "")
        if best_img:
            import json as _json
            instructions.append(f'SET image {_json.dumps({"@type": "ImageObject", "url": best_img})}')
            if "images" not in hotel_data or not hotel_data.get("images"):
                hotel_data["images"] = [best_img]
                update_project(project_id, user_id, {"hotel_data": hotel_data})

    if "logo" in error_lower:
        logo_url = scraped["logo"] or scraped["og_image"] or ""
        if logo_url:
            import json as _json
            instructions.append(f'SET logo {_json.dumps({"@type": "ImageObject", "url": logo_url})}')

    # Telephone fix
    if "telephone" in error_lower or "phone" in error_lower or "contact" in error_lower:
        phone = scraped["phones"][0] if scraped["phones"] else hotel_data.get("telephone", "")
        if phone:
            instructions.append(f'SET telephone {phone.strip()}')
            instructions.append(
                f'SET contactPoint {{"@type":"ContactPoint","contactType":"reservations","telephone":"{phone.strip()}"}}'
            )

    # Email fix
    if "email" in error_lower:
        email = scraped["emails"][0] if scraped["emails"] else hotel_data.get("email", "")
        if email:
            instructions.append(f'SET email {email}')

    # Social / sameAs fix
    if "sameas" in error_lower or "social" in error_lower or "profile" in error_lower:
        if scraped["social_profiles"]:
            import json as _json
            instructions.append(f'SET sameAs {_json.dumps(scraped["social_profiles"][:5])}')

    # Check-in / check-out time
    if "checkintime" in error_lower:
        instructions.append("SET checkinTime T14:00:00")
    if "checkouttime" in error_lower:
        instructions.append("SET checkoutTime T12:00:00")

    # Star rating
    if "starrating" in error_lower or "rating" in error_lower:
        star = hotel_data.get("starRating", "4")
        instructions.append(f'SET starRating {{"@type":"Rating","ratingValue":"{star}","bestRating":"5"}}')

    # Address fix
    if "address" in error_lower:
        addr = hotel_data.get("address", {})
        import json as _json
        addr_dict = {
            "@type": "PostalAddress",
            "streetAddress": addr.get("streetAddress", ""),
            "addressLocality": addr.get("addressLocality", ""),
            "addressRegion": addr.get("addressRegion", ""),
            "postalCode": addr.get("postalCode", ""),
            "addressCountry": addr.get("addressCountry", "")
        }
        instructions.append(f"SET address {_json.dumps(addr_dict)}")

    # Geo fix
    if "geo" in error_lower or "latitude" in error_lower or "longitude" in error_lower:
        geo = hotel_data.get("geo", {})
        if geo.get("latitude") and geo.get("longitude"):
            instructions.append(
                f'SET geo {{"@type":"GeoCoordinates","latitude":{geo["latitude"]},"longitude":{geo["longitude"]}}}'
            )

    # URL fix
    if "url" in error_lower and "url" not in [i.split()[1] for i in instructions if len(i.split()) > 1]:
        url = scraped["canonical_url"] or page_url
        instructions.append(f"SET url {url}")

    # Booking / potential action
    if "booking" in error_lower or "reserve" in error_lower or "potentialaction" in error_lower:
        booking = (scraped["booking_urls"][0] if scraped["booking_urls"]
                   else hotel_data.get("bookingUrl", ""))
        if booking:
            instructions.append(
                f'SET potentialAction {{"@type":"ReserveAction","target":{{"@type":"EntryPoint","urlTemplate":"{booking}"}}}}'
            )

    # Description fix
    if "description" in error_lower:
        desc = scraped["meta_description"] or hotel_data.get("description", "")
        if desc:
            instructions.append(f'SET description "{desc[:500]}"')

    # Name fix
    if "name" in error_lower and "checkintime" not in error_lower:
        name = hotel_data.get("name", scraped["page_title"])
        if name:
            instructions.append(f'SET name "{name}"')

    # FAQ page schema fix
    if "faq" in error_lower and scraped["faq_items"]:
        import json as _json
        faq_entries = []
        for item in scraped["faq_items"][:10]:
            faq_entries.append({
                "@type": "Question",
                "name": item["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": item["answer"]
                }
            })
        instructions.append(f'SET mainEntity {_json.dumps(faq_entries)}')

    # Price range fix
    if "pricerange" in error_lower or "price" in error_lower:
        price = hotel_data.get("priceRange", "$$$")
        instructions.append(f'SET priceRange {price}')

    # Amenity fix
    if "amenity" in error_lower or "amenityfeature" in error_lower:
        amenities = hotel_data.get("amenities", [])
        if amenities:
            import json as _json
            features = [{"@type": "LocationFeatureSpecification", "name": a, "value": True}
                        for a in amenities[:10]]
            instructions.append(f"SET amenityFeature {_json.dumps(features)}")

    val_errors = [error_text]
    instruction_str = "\n".join(instructions)

    pages = project.get("pages_found", [])
    page = next((p for p in pages if p["url"] == page_url),
                {"url": page_url, "page_type": "other", "title": ""})

    correction = create_correction(project_id, user_id, page_url,
                                   existing.get("schemas", []), val_errors, instruction_str)

    result = regenerate_corrected_schema(
        original_schemas=existing.get("schemas", []),
        validator_errors=val_errors,
        instructions=instruction_str,
        hotel_data={**project["hotel_data"], "websiteUrl": project["website_url"]},
        page=page,
        user_id=user_id
    )

    resolve_correction(correction["id"], user_id, result["corrected_schemas"])

    schemas_gen[page_url]["schemas"] = result["corrected_schemas"]
    schemas_gen[page_url]["json_ld_html"] = result["json_ld_html"]
    schemas_gen[page_url]["corrected"] = True
    schemas_gen[page_url]["correction_fixes"] = result["all_fixes"]
    update_project(project_id, user_id, {"schemas_generated": schemas_gen})

    log_action(user_id, "fix_page_error", "correction", str(correction["id"]),
               f"{page_url} resolved", request.remote_addr)

    return jsonify({
        "message": "Schema auto-corrected and updated successfully!",
        "result": result,
        "scraped_data": {
            "images_found": len(scraped["images"]),
            "logo": scraped["logo"],
            "emails": scraped["emails"],
            "phones": scraped["phones"],
            "social_profiles": scraped["social_profiles"],
            "booking_urls": scraped["booking_urls"],
            "faq_items_found": len(scraped["faq_items"]),
        },
        "instructions_applied": instructions
    })


