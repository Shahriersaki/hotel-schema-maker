"""
Database module - supports SQLite (local dev) and Supabase (production).
"""

import os
import sys
import sqlite3
import json
import bcrypt
from datetime import datetime, timezone


def _utcnow() -> str:
    """Return current UTC time as ISO string (timezone-aware)."""
    return datetime.now(timezone.utc).isoformat()


def get_db_path():
    return os.environ.get("SQLITE_PATH", "hotel_schema.db")


def init_db(app):
    """Initialize SQLite database with required tables."""
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # Users table — role: admin | contributor | viewer
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'contributor',
                created_at TEXT NOT NULL,
                last_login TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1
            )
        """)
        # Migrate existing DBs: add new columns idempotently
        for _col_sql in [
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'contributor'",
            "ALTER TABLE users ADD COLUMN last_login TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1",
        ]:
            try: cursor.execute(_col_sql)
            except Exception: pass

        # Audit log — every significant action recorded
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT DEFAULT '',
                resource_id TEXT DEFAULT '',
                detail TEXT DEFAULT '',
                ip_address TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)

        # Projects table (each hotel website = one project)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                website_url TEXT NOT NULL,
                hotel_data TEXT NOT NULL,
                pages_found TEXT DEFAULT '[]',
                schemas_generated TEXT DEFAULT '{}',
                sitemap_xml TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Knowledge Base — stores fed guidelines, validator results, schema.org updates
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                entry_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Schema Corrections — stores validator errors + corrected schema pairs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                page_url TEXT NOT NULL,
                original_schema TEXT NOT NULL,
                validator_errors TEXT DEFAULT '[]',
                instructions TEXT DEFAULT '',
                corrected_schema TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT DEFAULT '',
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Trend Snapshots — cached trend data from schema.org / Google
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trend_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                summary TEXT NOT NULL,
                raw_data TEXT DEFAULT '{}',
                fetched_at TEXT NOT NULL
            )
        """)

        conn.commit()
    print(f"[DB] SQLite database initialized at {db_path}")


# ─── Role-Based User Management ───────────────────────────────────────────────

VALID_ROLES = ("admin", "contributor", "viewer")


def create_user(email: str, password: str, name: str, role: str = "contributor") -> dict:
    """Create a new user with role. First-ever user auto-promoted to admin."""
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            raise ValueError("Email already registered.")

        # Auto-promote first user to admin
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        if user_count == 0:
            role = "admin"

        if role not in VALID_ROLES:
            role = "contributor"

        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        now = _utcnow()

        cursor.execute(
            "INSERT INTO users (email, password_hash, name, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (email, pw_hash, name, role, now)
        )
        conn.commit()
        user_id = cursor.lastrowid
    return {"id": user_id, "email": email, "name": name, "role": role, "created_at": now}


def get_user_by_email(email: str) -> dict | None:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
    return dict(row) if row else None


def get_all_users() -> list:
    """Admin only: list all users."""
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, name, role, created_at, last_login, is_active FROM users ORDER BY created_at DESC")
        rows = cursor.fetchall()
    return [dict(r) for r in rows]


def update_user(user_id: int, updates: dict) -> bool:
    """Update user fields (name, role, is_active). Password excluded — use change_password."""
    allowed = {"name", "role", "is_active"}
    updates = {k: v for k, v in updates.items() if k in allowed}
    if not updates:
        return False
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        cursor.execute(f"UPDATE users SET {set_clause} WHERE id = ?", list(updates.values()) + [user_id])
        conn.commit()
        affected = cursor.rowcount
    return affected > 0


def change_password(user_id: int, new_password: str) -> bool:
    pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user_id))
        conn.commit()
        affected = cursor.rowcount
    return affected > 0


def touch_last_login(user_id: int) -> None:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_login = ? WHERE id = ?",
                       (_utcnow(), user_id))
        conn.commit()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ─── Project CRUD ─────────────────────────────────────────────────────────────

def create_project(user_id: int, name: str, website_url: str, hotel_data: dict) -> dict:
    db_path = get_db_path()
    now = _utcnow()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO projects (user_id, name, website_url, hotel_data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, name, website_url, json.dumps(hotel_data), now, now))
        conn.commit()
        project_id = cursor.lastrowid

    return {
        "id": project_id, "user_id": user_id, "name": name,
        "website_url": website_url, "hotel_data": hotel_data,
        "pages_found": [], "schemas_generated": {},
        "sitemap_xml": "", "created_at": now, "updated_at": now
    }


def get_projects_by_user(user_id: int) -> list:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
        rows = cursor.fetchall()

    projects = []
    for row in rows:
        p = dict(row)
        p["hotel_data"] = json.loads(p["hotel_data"])
        p["pages_found"] = json.loads(p["pages_found"])
        p["schemas_generated"] = json.loads(p["schemas_generated"])
        projects.append(p)
    return projects


def get_project(project_id: int, user_id: int) -> dict | None:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id))
        row = cursor.fetchone()

    if not row:
        return None
    p = dict(row)
    p["hotel_data"] = json.loads(p["hotel_data"])
    p["pages_found"] = json.loads(p["pages_found"])
    p["schemas_generated"] = json.loads(p["schemas_generated"])
    return p


def update_project(project_id: int, user_id: int, updates: dict) -> bool:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # Serialize complex fields
        for field in ["hotel_data", "pages_found", "schemas_generated"]:
            if field in updates and isinstance(updates[field], (dict, list)):
                updates[field] = json.dumps(updates[field])

        updates["updated_at"] = _utcnow()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [project_id, user_id]

        cursor.execute(f"UPDATE projects SET {set_clause} WHERE id = ? AND user_id = ?", values)
        conn.commit()
        affected = cursor.rowcount
    return affected > 0


def delete_project(project_id: int, user_id: int) -> bool:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id))
        conn.commit()
        affected = cursor.rowcount
    return affected > 0


# ─── Knowledge Base CRUD ──────────────────────────────────────────────────────

def create_kb_entry(user_id: int, entry_type: str, title: str,
                    content: str, source: str = "", tags: list = None) -> dict:
    db_path = get_db_path()
    now = _utcnow()
    tags_json = json.dumps(tags or [])
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO knowledge_base (user_id, entry_type, title, content, source, tags, created_at) VALUES (?,?,?,?,?,?,?)",
            (user_id, entry_type, title, content, source, tags_json, now)
        )
        conn.commit()
        entry_id = cursor.lastrowid
    return {"id": entry_id, "user_id": user_id, "entry_type": entry_type,
            "title": title, "content": content, "source": source,
            "tags": tags or [], "active": 1, "created_at": now}


def get_kb_entry(entry_id: int, user_id: int) -> dict | None:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM knowledge_base WHERE id=? AND user_id=?", (entry_id, user_id))
        row = cursor.fetchone()
    if not row:
        return None
    e = dict(row)
    e["tags"] = json.loads(e["tags"])
    return e


def delete_kb_entry(entry_id: int, user_id: int) -> bool:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE knowledge_base SET active=0 WHERE id=? AND user_id=?", (entry_id, user_id))
        conn.commit()
        affected = cursor.rowcount
    return affected > 0


# ─── Schema Corrections CRUD ──────────────────────────────────────────────────

def create_correction(project_id: int, user_id: int, page_url: str,
                      original_schema: dict, validator_errors: list,
                      instructions: str = "") -> dict:
    db_path = get_db_path()
    now = _utcnow()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO schema_corrections
                (project_id, user_id, page_url, original_schema, validator_errors, instructions, status, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (project_id, user_id, page_url,
              json.dumps(original_schema), json.dumps(validator_errors),
              instructions, "pending", now))
        conn.commit()
        corr_id = cursor.lastrowid
    return {"id": corr_id, "project_id": project_id, "user_id": user_id,
            "page_url": page_url, "original_schema": original_schema,
            "validator_errors": validator_errors, "instructions": instructions,
            "corrected_schema": "", "status": "pending", "created_at": now}


def get_corrections(project_id: int, user_id: int) -> list:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM schema_corrections WHERE project_id=? AND user_id=? ORDER BY created_at DESC",
            (project_id, user_id)
        )
        rows = cursor.fetchall()
    result = []
    for row in rows:
        c = dict(row)
        c["original_schema"] = json.loads(c["original_schema"])
        c["validator_errors"] = json.loads(c["validator_errors"])
        if c["corrected_schema"]:
            try:
                c["corrected_schema"] = json.loads(c["corrected_schema"])
            except Exception:
                pass
        result.append(c)
    return result


def resolve_correction(corr_id: int, user_id: int, corrected_schema: dict) -> bool:
    db_path = get_db_path()
    now = _utcnow()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE schema_corrections
            SET corrected_schema=?, status='resolved', resolved_at=?
            WHERE id=? AND user_id=?
        """, (json.dumps(corrected_schema), now, corr_id, user_id))
        conn.commit()
        affected = cursor.rowcount
    return affected > 0


# ─── Trend Snapshots ──────────────────────────────────────────────────────────

def save_trend_snapshot(source: str, summary: str, raw_data: dict) -> dict:
    db_path = get_db_path()
    now = _utcnow()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO trend_snapshots (source, summary, raw_data, fetched_at) VALUES (?,?,?,?)",
            (source, summary, json.dumps(raw_data), now)
        )
        conn.commit()
        snap_id = cursor.lastrowid
    return {"id": snap_id, "source": source, "summary": summary, "fetched_at": now}


def get_latest_trend_snapshots(limit: int = 10) -> list:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM trend_snapshots ORDER BY fetched_at DESC LIMIT ?", (limit,)
        )
        rows = cursor.fetchall()
    result = []
    for row in rows:
        s = dict(row)
        try:
            s["raw_data"] = json.loads(s["raw_data"])
        except Exception:
            s["raw_data"] = {}
        result.append(s)
    return result


# ─── Audit Log ────────────────────────────────────────────────────────────────

def log_action(user_id: int, action: str, resource_type: str = "",
               resource_id: str = "", detail: str = "", ip: str = "") -> None:
    """Non-blocking audit logger. Logs errors to stderr instead of silently swallowing."""
    try:
        db_path = get_db_path()
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO audit_log (user_id, action, resource_type, resource_id, detail, ip_address, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, action, resource_type, str(resource_id), detail[:500], ip, _utcnow()))
            conn.commit()
    except Exception as e:
        print(f"[AUDIT LOG ERROR] Failed to log action '{action}': {e}", file=sys.stderr)


def get_audit_log(limit: int = 50, user_id: int = None) -> list:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if user_id:
            cursor.execute("""
                SELECT a.*, u.email, u.name FROM audit_log a
                LEFT JOIN users u ON a.user_id = u.id
                WHERE a.user_id = ? ORDER BY a.created_at DESC LIMIT ?
            """, (user_id, limit))
        else:
            cursor.execute("""
                SELECT a.*, u.email, u.name FROM audit_log a
                LEFT JOIN users u ON a.user_id = u.id
                ORDER BY a.created_at DESC LIMIT ?
            """, (limit,))
        rows = cursor.fetchall()
    return [dict(r) for r in rows]


# ─── KB with Priority Scoring ─────────────────────────────────────────────────

SOURCE_PRIORITY = {
    "google": 100,
    "google rich results": 100,
    "google search central": 95,
    "schema.org": 90,
    "schema.org validator": 88,
    "user": 80,
    "manual": 75,
    "auto-suggested": 50,
    "default": 40,
}


def _score_source(source: str) -> int:
    s = (source or "").lower()
    for key, score in SOURCE_PRIORITY.items():
        if key in s:
            return score
    return SOURCE_PRIORITY["default"]


def get_kb_entries_prioritized(user_id: int, entry_type: str = None) -> list:
    """Return KB entries sorted by source priority (highest first)."""
    entries = get_kb_entries(user_id, entry_type)
    for e in entries:
        e["priority_score"] = _score_source(e.get("source", ""))
    entries.sort(key=lambda e: (-e["priority_score"], e["created_at"]))
    return entries


def get_kb_entries(user_id: int, entry_type: str = None) -> list:
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if entry_type:
            cursor.execute(
                "SELECT * FROM knowledge_base WHERE user_id=? AND entry_type=? AND active=1 ORDER BY created_at DESC",
                (user_id, entry_type)
            )
        else:
            cursor.execute(
                "SELECT * FROM knowledge_base WHERE user_id=? AND active=1 ORDER BY created_at DESC",
                (user_id,)
            )
        rows = cursor.fetchall()
    result = []
    for row in rows:
        e = dict(row)
        e["tags"] = json.loads(e["tags"])
        e["priority_score"] = _score_source(e.get("source", ""))
        result.append(e)
    return result
