"""
Database module - supports SQLite (local dev) and Turso/LibSQL via HTTP API.
"""

import os
import sys
import sqlite3
import json
import requests
import bcrypt
from datetime import datetime, timezone


def _utcnow() -> str:
    """Return current UTC time as ISO string (timezone-aware)."""
    return datetime.now(timezone.utc).isoformat()


def get_db_url():
    """Get the database URL/path from environment variables."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        sqlite_path = os.environ.get("SQLITE_PATH", "hotel_schema.db")
        url = f"sqlite:///{sqlite_path}"
    return url


def get_db_path():
    """Backward compatibility for paths, returns the path or URL."""
    url = get_db_url()
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "")
    return url


class DBWrapper:
    def __init__(self):
        self._url = None
        self._token = None
        self._is_turso = False
        self._http_url = None
        self.refresh_config()

    def refresh_config(self):
        self._url = get_db_url()
        self._token = os.environ.get("TURSO_DB_TOKEN", "")
        self._is_turso = self._url.startswith(("libsql://", "http://", "https://"))
        if self._is_turso:
            # Convert libsql:// to https:// for HTTP API
            http_url = self._url.replace("libsql://", "https://")
            # Strip trailing slash
            self._http_url = http_url.rstrip("/")

    def _turso_execute(self, sql: str, params: list) -> tuple:
        """Execute SQL against Turso via its HTTP API (no Rust libs needed)."""
        # Build the request payload using Turso's pipeline API
        # Named params use :name syntax, positional use ?
        # We convert positional params to the Turso format
        args = []
        for p in params:
            if p is None:
                args.append({"type": "null"})
            elif isinstance(p, bool):
                args.append({"type": "integer", "value": str(int(p))})
            elif isinstance(p, int):
                args.append({"type": "integer", "value": str(p)})
            elif isinstance(p, float):
                args.append({"type": "float", "value": str(p)})
            else:
                args.append({"type": "text", "value": str(p)})

        payload = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": sql,
                        "args": args
                    }
                },
                {"type": "close"}
            ]
        }

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json"
        }

        resp = requests.post(
            f"{self._http_url}/v2/pipeline",
            headers=headers,
            json=payload,
            timeout=15
        )

        if not resp.ok:
            raise RuntimeError(f"Turso HTTP error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        result = data["results"][0]

        if result.get("type") == "error":
            raise RuntimeError(f"Turso SQL error: {result.get('error', {}).get('message', 'unknown')}")

        inner = result.get("response", {}).get("result", {})
        cols = [c["name"] for c in inner.get("cols", [])]
        rows_raw = inner.get("rows", [])
        rows = []
        for row in rows_raw:
            record = {}
            for i, col in enumerate(cols):
                cell = row[i]
                cell_type = cell.get("type")
                cell_val = cell.get("value")
                if cell_type == "null":
                    record[col] = None
                elif cell_type == "integer":
                    record[col] = int(cell_val)
                elif cell_type == "float":
                    record[col] = float(cell_val)
                else:
                    record[col] = cell_val
            rows.append(record)

        last_insert_rowid = int(inner.get("last_insert_rowid") or 0)
        rows_affected = int(inner.get("affected_row_count") or 0)
        return rows, last_insert_rowid, rows_affected

    def execute(self, sql: str, params: list = None) -> tuple:
        params = params or []
        if self._is_turso:
            return self._turso_execute(sql, params)
        else:
            path = self._url.replace("sqlite:///", "")
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                last_id = cursor.lastrowid or 0
                affected = cursor.rowcount or 0
                rows = cursor.fetchall()
                conn.commit()
                rows_dict = [dict(r) for r in rows]
                return rows_dict, last_id, affected
            finally:
                conn.close()



db = DBWrapper()


def init_db(app):
    """Initialize database with required tables (SQLite or remote Turso/LibSQL)."""
    db.refresh_config()

    # Users table — role: admin | manager | contributor | viewer
    db.execute("""
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

    # Migrate existing DBs: add new columns/roles idempotently
    for _col_sql in [
        "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'contributor'",
        "ALTER TABLE users ADD COLUMN last_login TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1",
    ]:
        try:
            db.execute(_col_sql)
        except Exception:
            pass

    # Folders table
    db.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Audit log — every significant action recorded
    db.execute("""
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
    db.execute("""
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
            folder_id INTEGER DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (folder_id) REFERENCES folders(id)
        )
    """)

    # Migrate existing projects table: add folder_id column idempotently
    try:
        db.execute("ALTER TABLE projects ADD COLUMN folder_id INTEGER DEFAULT NULL")
    except Exception:
        pass

    # Knowledge Base — stores fed guidelines, validator results, schema.org updates
    db.execute("""
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
    db.execute("""
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
    db.execute("""
        CREATE TABLE IF NOT EXISTS trend_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            summary TEXT NOT NULL,
            raw_data TEXT DEFAULT '{}',
            fetched_at TEXT NOT NULL
        )
    """)

    print(f"[DB] Database initialized at {db._url}")


# ─── Role-Based User Management ───────────────────────────────────────────────

VALID_ROLES = ("admin", "manager", "contributor", "viewer")


def create_user(email: str, password: str, name: str, role: str = "contributor") -> dict:
    """Create a new user with role. First-ever user auto-promoted to admin. shahrier@razibmarketing.net auto-promoted to manager."""
    email = email.strip().lower()
    rows, _, _ = db.execute("SELECT id FROM users WHERE email = ?", (email,))
    if rows:
        raise ValueError("Email already registered.")

    rows_count, _, _ = db.execute("SELECT COUNT(*) as cnt FROM users")
    user_count = rows_count[0]["cnt"] if rows_count else 0
    
    # Auto-promote first user to admin
    if user_count == 0:
        role = "admin"

    # Auto-promote shahrier@razibmarketing.net to manager
    if email == "shahrier@razibmarketing.net":
        role = "manager"

    if role not in VALID_ROLES:
        role = "contributor"

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    now = _utcnow()

    _, user_id, _ = db.execute(
        "INSERT INTO users (email, password_hash, name, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (email, pw_hash, name, role, now)
    )
    return {"id": user_id, "email": email, "name": name, "role": role, "created_at": now}


def get_user_by_email(email: str) -> dict | None:
    rows, _, _ = db.execute("SELECT * FROM users WHERE email = ?", (email,))
    return rows[0] if rows else None


def get_user_by_id(user_id: int) -> dict | None:
    rows, _, _ = db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    return rows[0] if rows else None


def get_all_users() -> list:
    """Admin/Manager only: list all users."""
    rows, _, _ = db.execute("SELECT id, email, name, role, created_at, last_login, is_active FROM users ORDER BY created_at DESC")
    return rows


def update_user(user_id: int, updates: dict) -> bool:
    """Update user fields (name, role, is_active). Password excluded."""
    allowed = {"name", "role", "is_active"}
    updates = {k: v for k, v in updates.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    _, _, affected = db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", list(updates.values()) + [user_id])
    return affected > 0


def change_password(user_id: int, new_password: str) -> bool:
    pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    _, _, affected = db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user_id))
    return affected > 0


def touch_last_login(user_id: int) -> None:
    db.execute("UPDATE users SET last_login = ? WHERE id = ?", (_utcnow(), user_id))


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ─── Folders CRUD ─────────────────────────────────────────────────────────────

def create_folder(user_id: int, name: str) -> dict:
    now = _utcnow()
    _, folder_id, _ = db.execute(
        "INSERT INTO folders (user_id, name, created_at) VALUES (?, ?, ?)",
        (user_id, name, now)
    )
    return {"id": folder_id, "user_id": user_id, "name": name, "created_at": now}


def get_folders_by_user(user_id: int) -> list:
    rows, _, _ = db.execute("SELECT * FROM folders WHERE user_id = ? ORDER BY name ASC", (user_id,))
    return rows


def delete_folder(folder_id: int, user_id: int) -> bool:
    # Set projects in this folder to uncategorized
    db.execute("UPDATE projects SET folder_id = NULL WHERE folder_id = ? AND user_id = ?", (folder_id, user_id))
    rows, _, affected = db.execute("DELETE FROM folders WHERE id = ? AND user_id = ?", (folder_id, user_id))
    return affected > 0


# ─── Project CRUD ─────────────────────────────────────────────────────────────

def create_project(user_id: int, name: str, website_url: str, hotel_data: dict, folder_id: int = None) -> dict:
    now = _utcnow()
    _, project_id, _ = db.execute("""
        INSERT INTO projects (user_id, name, website_url, hotel_data, created_at, updated_at, folder_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, name, website_url, json.dumps(hotel_data), now, now, folder_id))

    return {
        "id": project_id, "user_id": user_id, "name": name,
        "website_url": website_url, "hotel_data": hotel_data,
        "pages_found": [], "schemas_generated": {},
        "sitemap_xml": "", "created_at": now, "updated_at": now,
        "folder_id": folder_id
    }


def get_projects_by_user(user_id: int) -> list:
    rows, _, _ = db.execute("""
        SELECT p.*, f.name as folder_name FROM projects p 
        LEFT JOIN folders f ON p.folder_id = f.id 
        WHERE p.user_id = ? ORDER BY p.updated_at DESC
    """, (user_id,))

    projects = []
    for row in rows:
        p = dict(row)
        p["hotel_data"] = json.loads(p["hotel_data"])
        p["pages_found"] = json.loads(p["pages_found"])
        p["schemas_generated"] = json.loads(p["schemas_generated"])
        projects.append(p)
    return projects


def get_project(project_id: int, user_id: int) -> dict | None:
    rows, _, _ = db.execute("""
        SELECT p.*, f.name as folder_name FROM projects p 
        LEFT JOIN folders f ON p.folder_id = f.id 
        WHERE p.id = ? AND p.user_id = ?
    """, (project_id, user_id))

    if not rows:
        return None
    p = dict(rows[0])
    p["hotel_data"] = json.loads(p["hotel_data"])
    p["pages_found"] = json.loads(p["pages_found"])
    p["schemas_generated"] = json.loads(p["schemas_generated"])
    return p


def update_project(project_id: int, user_id: int, updates: dict) -> bool:
    # Serialize complex fields
    updates = dict(updates)
    for field in ["hotel_data", "pages_found", "schemas_generated"]:
        if field in updates and isinstance(updates[field], (dict, list)):
            updates[field] = json.dumps(updates[field])

    updates["updated_at"] = _utcnow()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [project_id, user_id]

    _, _, affected = db.execute(f"UPDATE projects SET {set_clause} WHERE id = ? AND user_id = ?", values)
    return affected > 0


def delete_project(project_id: int, user_id: int) -> bool:
    _, _, affected = db.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id))
    return affected > 0


# ─── Knowledge Base CRUD ──────────────────────────────────────────────────────

def create_kb_entry(user_id: int, entry_type: str, title: str,
                    content: str, source: str = "", tags: list = None) -> dict:
    now = _utcnow()
    tags_json = json.dumps(tags or [])
    _, entry_id, _ = db.execute(
        "INSERT INTO knowledge_base (user_id, entry_type, title, content, source, tags, created_at) VALUES (?,?,?,?,?,?,?)",
        (user_id, entry_type, title, content, source, tags_json, now)
    )
    return {"id": entry_id, "user_id": user_id, "entry_type": entry_type,
            "title": title, "content": content, "source": source,
            "tags": tags or [], "active": 1, "created_at": now}


def get_kb_entry(entry_id: int, user_id: int) -> dict | None:
    rows, _, _ = db.execute("SELECT * FROM knowledge_base WHERE id=? AND user_id=?", (entry_id, user_id))
    if not rows:
        return None
    e = dict(rows[0])
    e["tags"] = json.loads(e["tags"])
    return e


def delete_kb_entry(entry_id: int, user_id: int) -> bool:
    _, _, affected = db.execute("UPDATE knowledge_base SET active=0 WHERE id=? AND user_id=?", (entry_id, user_id))
    return affected > 0


# ─── Schema Corrections CRUD ──────────────────────────────────────────────────

def create_correction(project_id: int, user_id: int, page_url: str,
                      original_schema: dict, validator_errors: list,
                      instructions: str = "") -> dict:
    now = _utcnow()
    _, corr_id, _ = db.execute("""
        INSERT INTO schema_corrections
            (project_id, user_id, page_url, original_schema, validator_errors, instructions, status, created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (project_id, user_id, page_url,
          json.dumps(original_schema), json.dumps(validator_errors),
          instructions, "pending", now))
    return {"id": corr_id, "project_id": project_id, "user_id": user_id,
            "page_url": page_url, "original_schema": original_schema,
            "validator_errors": validator_errors, "instructions": instructions,
            "corrected_schema": "", "status": "pending", "created_at": now}


def get_corrections(project_id: int, user_id: int) -> list:
    rows, _, _ = db.execute(
        "SELECT * FROM schema_corrections WHERE project_id=? AND user_id=? ORDER BY created_at DESC",
        (project_id, user_id)
    )
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
    now = _utcnow()
    _, _, affected = db.execute("""
        UPDATE schema_corrections
        SET corrected_schema=?, status='resolved', resolved_at=?
        WHERE id=? AND user_id=?
    """, (json.dumps(corrected_schema), now, corr_id, user_id))
    return affected > 0


# ─── Trend Snapshots ──────────────────────────────────────────────────────────

def save_trend_snapshot(source: str, summary: str, raw_data: dict) -> dict:
    now = _utcnow()
    _, snap_id, _ = db.execute(
        "INSERT INTO trend_snapshots (source, summary, raw_data, fetched_at) VALUES (?,?,?,?)",
        (source, summary, json.dumps(raw_data), now)
    )
    return {"id": snap_id, "source": source, "summary": summary, "fetched_at": now}


def get_latest_trend_snapshots(limit: int = 10) -> list:
    rows, _, _ = db.execute(
        "SELECT * FROM trend_snapshots ORDER BY fetched_at DESC LIMIT ?", (limit,)
    )
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
        db.execute("""
            INSERT INTO audit_log (user_id, action, resource_type, resource_id, detail, ip_address, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, action, resource_type, str(resource_id), detail[:500], ip, _utcnow()))
    except Exception as e:
        print(f"[AUDIT LOG ERROR] Failed to log action '{action}': {e}", file=sys.stderr)


def get_audit_log(limit: int = 50, user_id: int = None) -> list:
    if user_id:
        rows, _, _ = db.execute("""
            SELECT a.*, u.email, u.name FROM audit_log a
            LEFT JOIN users u ON a.user_id = u.id
            WHERE a.user_id = ? ORDER BY a.created_at DESC LIMIT ?
        """, (user_id, limit))
    else:
        rows, _, _ = db.execute("""
            SELECT a.*, u.email, u.name FROM audit_log a
            LEFT JOIN users u ON a.user_id = u.id
            ORDER BY a.created_at DESC LIMIT ?
        """, (limit,))
    return rows


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
    if entry_type:
        rows, _, _ = db.execute(
            "SELECT * FROM knowledge_base WHERE user_id=? AND entry_type=? AND active=1 ORDER BY created_at DESC",
            (user_id, entry_type)
        )
    else:
        rows, _, _ = db.execute(
            "SELECT * FROM knowledge_base WHERE user_id=? AND active=1 ORDER BY created_at DESC",
            (user_id,)
        )
    result = []
    for row in rows:
        e = dict(row)
        e["tags"] = json.loads(e["tags"])
        e["priority_score"] = _score_source(e.get("source", ""))
        result.append(e)
    return result
