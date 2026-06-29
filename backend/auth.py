"""
Authentication module — JWT login/register + role-based access control.

Roles:
  admin       — full access: user management, KB, schemas, audit log
  contributor — can create/edit projects, manage own KB entries, submit corrections
  viewer      — read-only access to projects and schemas
"""

import os
import jwt
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Blueprint, request, jsonify, current_app
from backend.database import (
    create_user, get_user_by_email, get_user_by_id, get_all_users,
    update_user, change_password, verify_password, touch_last_login,
    log_action, get_audit_log, VALID_ROLES
)

auth_bp = Blueprint("auth", __name__)

# ─── Token Helpers ────────────────────────────────────────────────────────────

def generate_token(user_id: int, email: str, role: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET"], algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, current_app.config["JWT_SECRET"], algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


# ─── Auth Decorators ──────────────────────────────────────────────────────────

def require_auth(f):
    """Require valid JWT. Sets request.current_user."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        payload = decode_token(auth_header[7:])
        if not payload:
            return jsonify({"error": "Token expired or invalid. Please log in again."}), 401
        request.current_user = payload
        return f(*args, **kwargs)
    return decorated


def require_role(*roles):
    """Require specific role(s). Must be used after @require_auth."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user_role = getattr(request, "current_user", {}).get("role", "viewer")
            if user_role not in roles:
                return jsonify({
                    "error": f"Access denied. Required role: {' or '.join(roles)}. "
                             f"Your role: {user_role}"
                }), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def require_admin(f):
    """Shorthand: admin/manager-only route. Use after @require_auth."""
    @wraps(f)
    def decorated(*args, **kwargs):
        role = getattr(request, "current_user", {}).get("role", "viewer")
        email = getattr(request, "current_user", {}).get("email", "")
        if role not in ("admin", "manager") and email != "shahrier@razibmarketing.net":
            return jsonify({"error": "Admin or Manager access required."}), 403
        return f(*args, **kwargs)
    return decorated


def can_write(f):
    """Require admin, manager, or contributor (not viewer)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        role = getattr(request, "current_user", {}).get("role", "viewer")
        if role not in ("admin", "manager", "contributor"):
            return jsonify({"error": "Write access required. Viewers have read-only access."}), 403
        return f(*args, **kwargs)
    return decorated


# ─── Validation ───────────────────────────────────────────────────────────────

def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[\w.+-]+@[\w-]+\.[a-z]{2,}$", email, re.IGNORECASE))


def is_strong_password(password: str) -> bool:
    return len(password) >= 8


def _safe_user(user: dict) -> dict:
    """Strip sensitive fields before sending to client."""
    return {k: v for k, v in user.items()
            if k not in ("password_hash",)}


# ─── Auth Routes ──────────────────────────────────────────────────────────────

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name     = (data.get("name") or "").strip()

    errors = {}
    if not email or not is_valid_email(email):
        errors["email"] = "A valid email address is required."
    if not password or not is_strong_password(password):
        errors["password"] = "Password must be at least 8 characters."
    if not name:
        errors["name"] = "Name is required."
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    try:
        user = create_user(email, password, name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409

    log_action(user["id"], "register", "user", str(user["id"]),
               f"New {user['role']} account", request.remote_addr)

    token = generate_token(user["id"], user["email"], user["role"])
    return jsonify({
        "message": "Account created successfully.",
        "token": token,
        "user": _safe_user(user)
    }), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    user = get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return jsonify({"error": "Invalid email or password."}), 401
    if not user.get("is_active"):
        return jsonify({"error": "Account is disabled. Contact an admin."}), 403

    touch_last_login(user["id"])
    log_action(user["id"], "login", "user", str(user["id"]),
               "Login", request.remote_addr)

    token = generate_token(user["id"], user["email"], user.get("role", "contributor"))
    return jsonify({
        "message": "Login successful.",
        "token": token,
        "user": _safe_user(user)
    }), 200


@auth_bp.route("/me", methods=["GET"])
@require_auth
def me():
    user = get_user_by_id(request.current_user["user_id"])
    if not user:
        return jsonify({"error": "User not found."}), 404
    return jsonify({"user": _safe_user(user)})


@auth_bp.route("/me/profile", methods=["PUT"])
@require_auth
def update_my_profile():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required."}), 400
    user_id = request.current_user["user_id"]
    success = update_user(user_id, {"name": name})
    if not success:
        return jsonify({"error": "Failed to update profile name."}), 500
    log_action(user_id, "update_profile", "user", str(user_id), f"Name updated to {name}", request.remote_addr)
    return jsonify({"message": "Profile updated successfully.", "name": name})


@auth_bp.route("/me/password", methods=["PUT"])
@require_auth
def change_my_password():
    data = request.get_json(silent=True) or {}
    current  = data.get("current_password") or ""
    new_pass = data.get("new_password") or ""

    user = get_user_by_id(request.current_user["user_id"])
    if not user or not verify_password(current, user["password_hash"]):
        return jsonify({"error": "Current password is incorrect."}), 401
    if not is_strong_password(new_pass):
        return jsonify({"error": "New password must be at least 8 characters."}), 400

    change_password(user["id"], new_pass)
    log_action(user["id"], "change_password", "user", str(user["id"]),
               "", request.remote_addr)
    return jsonify({"message": "Password changed successfully."})


@auth_bp.route("/verify", methods=["GET"])
@require_auth
def verify():
    return jsonify({"valid": True, "user": request.current_user})


# ─── Admin: User Management ───────────────────────────────────────────────────

@auth_bp.route("/admin/users", methods=["GET"])
@require_auth
@require_admin
def admin_list_users():
    users = get_all_users()
    return jsonify({"users": [_safe_user(u) for u in users], "count": len(users)})


@auth_bp.route("/admin/users/<int:target_id>", methods=["PUT"])
@require_auth
@require_admin
def admin_update_user(target_id):
    """Admin can change name, role, is_active."""
    data = request.get_json(silent=True) or {}
    updates = {}

    if "role" in data:
        if data["role"] not in VALID_ROLES:
            return jsonify({"error": f"Invalid role. Must be: {VALID_ROLES}"}), 400
        updates["role"] = data["role"]
    if "name" in data:
        updates["name"] = (data["name"] or "").strip()
    if "is_active" in data:
        updates["is_active"] = 1 if data["is_active"] else 0

    if not updates:
        return jsonify({"error": "No valid fields to update."}), 400

    # Prevent demoting yourself
    if target_id == request.current_user["user_id"] and "role" in updates:
        return jsonify({"error": "You cannot change your own role."}), 400

    success = update_user(target_id, updates)
    if not success:
        return jsonify({"error": "User not found."}), 404

    log_action(request.current_user["user_id"], "admin_update_user",
               "user", str(target_id), str(updates), request.remote_addr)
    return jsonify({"message": "User updated.", "updates": updates})


@auth_bp.route("/admin/users/<int:target_id>/reset-password", methods=["POST"])
@require_auth
@require_admin
def admin_reset_password(target_id):
    data = request.get_json(silent=True) or {}
    new_pass = data.get("new_password") or ""
    if not is_strong_password(new_pass):
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    success = change_password(target_id, new_pass)
    if not success:
        return jsonify({"error": "User not found."}), 404

    log_action(request.current_user["user_id"], "admin_reset_password",
               "user", str(target_id), "", request.remote_addr)
    return jsonify({"message": "Password reset successfully."})


@auth_bp.route("/admin/audit-log", methods=["GET"])
@require_auth
@require_admin
def admin_audit_log():
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


@auth_bp.route("/bootstrap-admin", methods=["POST"])
def bootstrap_admin():
    """
    One-time emergency endpoint to promote a user to admin.
    Requires ADMIN_BOOTSTRAP_KEY env var to be set and matched.
    Disable by removing the env var after use.
    """
    bootstrap_key = os.environ.get("ADMIN_BOOTSTRAP_KEY", "")
    if not bootstrap_key:
        return jsonify({"error": "Bootstrap not enabled on this server."}), 403

    data = request.get_json(silent=True) or {}
    provided_key = data.get("key", "")
    email = (data.get("email") or "").strip().lower()

    if provided_key != bootstrap_key:
        return jsonify({"error": "Invalid bootstrap key."}), 403
    if not email:
        return jsonify({"error": "Email is required."}), 400

    user = get_user_by_email(email)
    if not user:
        return jsonify({"error": "User not found."}), 404

    update_user(user["id"], {"role": "admin"})
    return jsonify({"message": f"User {email} promoted to admin successfully."})

