"""
Admin Routes — user management, audit log, system stats.
All routes require admin role.
"""

from flask import Blueprint, request, jsonify
from backend.auth import require_auth, require_admin
from backend.database import (
    get_all_users, update_user, change_password, get_audit_log,
    get_db_path, log_action, VALID_ROLES, db
)

admin_bp = Blueprint("admin", __name__)


def _db_stats() -> dict:
    """Quick counts from the DB."""
    try:
        stats = {}
        for table in ("users", "projects", "knowledge_base", "schema_corrections",
                      "trend_snapshots", "audit_log", "folders"):
            try:
                rows, _, _ = db.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                stats[table] = rows[0]["cnt"] if rows else 0
            except Exception:
                stats[table] = 0
        return stats
    except Exception:
        return {}


# ─── Dashboard Stats ──────────────────────────────────────────────────────────

@admin_bp.route("/stats", methods=["GET"])
@require_auth
@require_admin
def admin_stats():
    stats = _db_stats()
    return jsonify({"stats": stats})


# ─── User List ────────────────────────────────────────────────────────────────

@admin_bp.route("/users", methods=["GET"])
@require_auth
@require_admin
def list_users():
    users = get_all_users()
    safe  = [{k: v for k, v in u.items() if k != "password_hash"} for u in users]
    return jsonify({"users": safe, "count": len(safe)})


# ─── Update User ──────────────────────────────────────────────────────────────

@admin_bp.route("/users/<int:target_id>", methods=["PUT"])
@require_auth
@require_admin
def update_user_route(target_id):
    data    = request.get_json(silent=True) or {}
    updates = {}

    if "role" in data:
        if data["role"] not in VALID_ROLES:
            return jsonify({"error": f"Role must be one of: {VALID_ROLES}"}), 400
        if target_id == request.current_user["user_id"]:
            return jsonify({"error": "Cannot change your own role."}), 400
        updates["role"] = data["role"]

    if "is_active" in data:
        if target_id == request.current_user["user_id"] and not data["is_active"]:
            return jsonify({"error": "Cannot deactivate your own account."}), 400
        updates["is_active"] = 1 if data["is_active"] else 0

    if "name" in data:
        name = (data["name"] or "").strip()
        if name:
            updates["name"] = name

    if not updates:
        return jsonify({"error": "No valid fields to update."}), 400

    success = update_user(target_id, updates)
    if not success:
        return jsonify({"error": "User not found."}), 404

    log_action(request.current_user["user_id"], "admin_update_user",
               "user", str(target_id), str(updates), request.remote_addr)
    return jsonify({"message": "User updated.", "updates": updates})


# ─── Reset Password ───────────────────────────────────────────────────────────

@admin_bp.route("/users/<int:target_id>/reset-password", methods=["POST"])
@require_auth
@require_admin
def reset_password(target_id):
    data     = request.get_json(silent=True) or {}
    new_pass = data.get("new_password") or ""
    if len(new_pass) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    success = change_password(target_id, new_pass)
    if not success:
        return jsonify({"error": "User not found."}), 404

    log_action(request.current_user["user_id"], "admin_reset_password",
               "user", str(target_id), "", request.remote_addr)
    return jsonify({"message": "Password reset successfully."})


# ─── Audit Log ────────────────────────────────────────────────────────────────

@admin_bp.route("/audit-log", methods=["GET"])
@require_auth
@require_admin
def audit_log():
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
        if limit < 1:
            limit = 100
    except ValueError:
        limit = 100
    user_filter = request.args.get("user_id")
    try:
        user_id_val = int(user_filter) if user_filter else None
    except ValueError:
        user_id_val = None
    logs = get_audit_log(limit=limit, user_id=user_id_val)
    return jsonify({"logs": logs, "count": len(logs)})
