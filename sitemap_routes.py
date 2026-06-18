"""
Sitemap API routes — generate and download XML sitemaps.
"""

from flask import Blueprint, request, jsonify, Response
from backend.auth import require_auth
from backend.database import get_project, update_project
from backend.sitemap_generator import generate_xml_sitemap, sitemap_stats

sitemap_bp = Blueprint("sitemap", __name__)


@sitemap_bp.route("/projects/<int:project_id>/generate", methods=["POST"])
@require_auth
def generate_sitemap(project_id):
    """Generate XML sitemap for all discovered pages in a project."""
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

    # Only include selected pages in sitemap
    pages = [p for p in pages if p.get("selected", True)]
    if not pages:
        return jsonify({
            "error": "No selected pages. Please select at least one page."
        }), 400

    try:
        xml = generate_xml_sitemap(pages, project["website_url"])
        stats = sitemap_stats(xml)
        update_project(project_id, user_id, {"sitemap_xml": xml})

        return jsonify({
            "message": "Sitemap generated.",
            "sitemap_xml": xml,
            "stats": stats
        })
    except Exception as e:
        return jsonify({"error": f"Sitemap generation failed: {str(e)}"}), 500


@sitemap_bp.route("/projects/<int:project_id>/download", methods=["GET"])
@require_auth
def download_sitemap(project_id):
    """Download the sitemap as an XML file."""
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    sitemap_xml = project.get("sitemap_xml", "")
    if not sitemap_xml:
        return jsonify({
            "error": "No sitemap generated yet.",
            "hint": "POST /api/sitemap/projects/{id}/generate"
        }), 400

    return Response(
        sitemap_xml,
        mimetype="application/xml",
        headers={
            "Content-Disposition": f"attachment; filename=sitemap.xml",
            "Content-Type": "application/xml; charset=UTF-8"
        }
    )


@sitemap_bp.route("/projects/<int:project_id>/preview", methods=["GET"])
@require_auth
def preview_sitemap(project_id):
    """Preview the sitemap XML in the browser."""
    user_id = request.current_user["user_id"]
    project = get_project(project_id, user_id)
    if not project:
        return jsonify({"error": "Project not found."}), 404

    sitemap_xml = project.get("sitemap_xml", "")
    if not sitemap_xml:
        return jsonify({"error": "No sitemap yet. Run /generate first."}), 400

    return Response(sitemap_xml, mimetype="application/xml")
