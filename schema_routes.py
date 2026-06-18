"""
Schema API routes — project management + schema generation endpoints.
"""

from flask import Blueprint, request, jsonify
from backend.auth import require_auth, can_write
from backend.database import (
    create_project, get_projects_by_user, get_project,
    update_project, delete_project
)
from backend.crawler import crawl_website, enrich_page_data
from backend.enrichment import enrich_hotel_data
from backend.schema_generator import generate_all_schemas

schema_bp = Blueprint("schema", __name__)


# ─── Project CRUD ─────────────────────────────────────────────────────────────

@schema_bp.route("/projects", methods=["GET"])
@require_auth
def list_projects():
    user_id = request.current_user["user_id"]
    projects = get_projects_by_user(user_id)
    return jsonify({"projects": projects})


@schema_bp.route("/projects", methods=["POST"])
@require_auth
@can_write
def create_new_project():
    user_id = request.current_user["user_id"]
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    website_url = (data.get("website_url") or "").strip()
    hotel_data = data.get("hotel_data") or {}

    if not name:
        return jsonify({"error": "Project name is required."}), 400
    if not website_url:
        return jsonify({"error": "Website URL is required."}), 400
    if not hotel_data.get("name"):
        return jsonify({"error": "Hotel name is required in hotel_data."}), 400

    project = create_project(user_id, name, website_url, hotel_data)
    return jsonify({"project": project}), 201


@schema_bp.route("/projects/<int:project_id>", methods=["GET"])
@require_auth
def get_single_project(project_id):
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404
    return jsonify({"project": project})


@schema_bp.route("/projects/<int:project_id>", methods=["PUT"])
@require_auth
@can_write
def update_existing_project(project_id):
    user_id = request.current_user["user_id"]
    data = request.get_json(silent=True) or {}

    allowed_fields = ["name", "website_url", "hotel_data"]
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return jsonify({"error": "No valid fields to update."}), 400

    success = update_project(project_id, user_id, updates)
    if not success:
        return jsonify({"error": "Project not found."}), 404
    return jsonify({"message": "Project updated."})


@schema_bp.route("/projects/<int:project_id>", methods=["DELETE"])
@require_auth
@can_write
def delete_existing_project(project_id):
    user_id = request.current_user["user_id"]
    success = delete_project(project_id, user_id)
    if not success:
        return jsonify({"error": "Project not found."}), 404
    return jsonify({"message": "Project deleted."})


# ─── Crawl Endpoint ───────────────────────────────────────────────────────────

@schema_bp.route("/projects/<int:project_id>/crawl", methods=["POST"])
@require_auth
@can_write
def crawl_project(project_id):
    """Crawl the hotel website and detect all pages."""
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    website_url = project["website_url"]
    max_pages = request.get_json(silent=True, force=True).get("max_pages", 50) if request.data else 50

    try:
        pages = crawl_website(website_url, max_pages=max_pages)
        pages = enrich_page_data(pages, project["hotel_data"])

        update_project(project_id, user_id, {"pages_found": pages})

        return jsonify({
            "message": f"Crawl complete. Found {len(pages)} pages.",
            "pages": pages,
            "page_count": len(pages)
        })
    except Exception as e:
        return jsonify({"error": f"Crawl failed: {str(e)}"}), 500


# ─── Enrichment Endpoint ──────────────────────────────────────────────────────

@schema_bp.route("/projects/<int:project_id>/enrich", methods=["POST"])
@require_auth
@can_write
def enrich_project(project_id):
    """Enrich hotel data with missing fields from online sources."""
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    try:
        enriched = enrich_hotel_data(project["hotel_data"])
        update_project(project_id, user_id, {"hotel_data": enriched})
        return jsonify({
            "message": "Hotel data enriched.",
            "hotel_data": enriched,
            "enrichment_log": enriched.get("enrichment_log", [])
        })
    except Exception as e:
        return jsonify({"error": f"Enrichment failed: {str(e)}"}), 500


# ─── Schema Generation Endpoint ───────────────────────────────────────────────

@schema_bp.route("/projects/<int:project_id>/generate", methods=["POST"])
@require_auth
@can_write
def generate_schemas(project_id):
    """Generate JSON-LD schemas for all discovered pages."""
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    pages = project.get("pages_found", [])
    if not pages:
        return jsonify({
            "error": "No pages found. Run the crawl first.",
            "hint": "POST /api/schema/projects/{id}/crawl"
        }), 400

    pages_selected = [p for p in pages if p.get("selected", True)]
    if not pages_selected:
        return jsonify({
            "error": "No selected pages found. Please select at least one page to generate schemas for."
        }), 400

    try:
        hotel_data = project["hotel_data"]
        hotel_data["websiteUrl"] = project["website_url"]
        schemas = generate_all_schemas(hotel_data, pages_selected, user_id=user_id)
        update_project(project_id, user_id, {"schemas_generated": schemas})

        return jsonify({
            "message": f"Schemas generated for {len(schemas)} pages.",
            "schemas": schemas,
            "page_count": len(schemas)
        })
    except Exception as e:
        return jsonify({"error": f"Schema generation failed: {str(e)}"}), 500


# ─── Get Single Page Schema ───────────────────────────────────────────────────

@schema_bp.route("/projects/<int:project_id>/schemas", methods=["GET"])
@require_auth
def get_project_schemas(project_id):
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    schemas = project.get("schemas_generated", {})
    return jsonify({
        "schemas": schemas,
        "count": len(schemas)
    })


# ─── Full Pipeline: Crawl → Enrich → Generate ────────────────────────────────

@schema_bp.route("/projects/<int:project_id>/run-all", methods=["POST"])
@require_auth
@can_write
def run_full_pipeline(project_id):
    """Run the complete pipeline: crawl + enrich + generate schemas."""
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    results = {}
    hotel_data = dict(project["hotel_data"])  # working copy

    # Step 1: Crawl
    try:
        pages = crawl_website(project["website_url"], max_pages=50)
        pages = enrich_page_data(pages, project["hotel_data"])
        update_project(project_id, user_id, {"pages_found": pages})
        results["crawl"] = {"status": "success", "pages_found": len(pages)}
    except Exception as e:
        results["crawl"] = {"status": "error", "message": str(e)}
        return jsonify({"error": "Pipeline failed at crawl step.", "results": results}), 500

    # Step 2: Enrich
    try:
        hotel_data = enrich_hotel_data(hotel_data)
        update_project(project_id, user_id, {"hotel_data": hotel_data})
        results["enrich"] = {
            "status": "success",
            "log": hotel_data.get("enrichment_log", [])
        }
    except Exception as e:
        results["enrich"] = {"status": "error", "message": str(e)}

    # Step 3: Generate schemas
    try:
        hotel_data["websiteUrl"] = project["website_url"]
        schemas = generate_all_schemas(hotel_data, pages, user_id=user_id)
        update_project(project_id, user_id, {"schemas_generated": schemas})
        results["schema"] = {"status": "success", "schemas_generated": len(schemas)}
    except Exception as e:
        results["schema"] = {"status": "error", "message": str(e)}
        return jsonify({"error": "Pipeline failed at schema step.", "results": results}), 500

    # Reload updated project
    project = get_project(project_id, user_id)

    return jsonify({
        "message": "Full pipeline completed successfully.",
        "results": results,
        "project": project
    })


@schema_bp.route("/projects/<int:project_id>/pages", methods=["POST"])
@require_auth
@can_write
def set_project_pages(project_id):
    """Manually set or add custom pages for a project."""
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    data = request.get_json(silent=True) or {}
    pages = data.get("pages", [])

    cleaned_pages = []
    for p in pages:
        if isinstance(p, dict) and "url" in p:
            cleaned_pages.append({
                "url": p["url"],
                "page_type": p.get("page_type", "other"),
                "title": p.get("title", ""),
                "og_image": p.get("og_image", ""),
                "og_title": p.get("og_title", ""),
                "og_description": p.get("og_description", ""),
                "description": p.get("description", ""),
                "headings": p.get("headings", []),
                "status_code": p.get("status_code", 200),
                "depth": p.get("depth", 0),
                "selected": p.get("selected", True)
            })
        elif isinstance(p, str):
            cleaned_pages.append({
                "url": p.strip(),
                "page_type": "other",
                "title": "",
                "og_image": "",
                "og_title": "",
                "og_description": "",
                "description": "",
                "headings": [],
                "status_code": 200,
                "depth": 0,
                "selected": True
            })

    # Deduplicate by URL
    seen = set()
    deduped = []
    for cp in cleaned_pages:
        if cp["url"] not in seen:
            seen.add(cp["url"])
            deduped.append(cp)

    update_project(project_id, user_id, {"pages_found": deduped})
    return jsonify({
        "message": f"Project pages updated manually. Total pages: {len(deduped)}.",
        "pages": deduped
    })

