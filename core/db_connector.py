"""
Database Connector — Turso HTTP API (cloud) or SQLite (local)
=============================================================
Automatically selects the right backend:
  - If TURSO_DATABASE_URL is set → uses Turso HTTP Pipeline API via `requests`
  - Otherwise → uses standard sqlite3 (local file)

The Turso backend wraps the HTTP API to provide a sqlite3-compatible interface
so that database.py works identically with either backend.

No native dependencies required — only `requests` (already in requirements).
"""

import os
import sqlite3
import json
import requests

# Store local DB in home directory
DB_DIR = os.path.expanduser("~/prosper_data")
DB_PATH = os.path.join(DB_DIR, "prosper.db")

# Turso connection config (resolved lazily)
_turso_url = None
_turso_token = None
_use_turso = None  # None = not yet checked


def _get_secret(key_name: str) -> str:
    """Get a secret value — tries env vars, then 5 Streamlit secrets patterns."""
    # 1. Environment variable
    val = os.getenv(key_name, "")
    if val:
        return val

    # 2-6. Streamlit secrets — try every pattern that might work
    try:
        import streamlit as st
        # Pattern A: direct attribute access
        try:
            val = getattr(st.secrets, key_name, "")
            if val:
                return str(val)
        except Exception:
            pass
        # Pattern B: dict-style access
        try:
            val = st.secrets[key_name]
            if val:
                return str(val)
        except Exception:
            pass
        # Pattern C: .get()
        try:
            val = st.secrets.get(key_name, "")
            if val:
                return str(val)
        except Exception:
            pass
        # Pattern D: nested under [secrets] table
        try:
            val = st.secrets["secrets"][key_name]
            if val:
                return str(val)
        except Exception:
            pass
        # Pattern E: iterate all keys and match case-insensitively
        try:
            for k in st.secrets:
                if k.upper() == key_name.upper():
                    return str(st.secrets[k])
        except Exception:
            pass
    except Exception:
        pass

    return ""


def _resolve_turso_config():
    """Resolve Turso credentials from env vars or Streamlit secrets."""
    global _turso_url, _turso_token, _use_turso

    _turso_url = _get_secret("TURSO_DATABASE_URL").strip().strip('"').strip("'")
    _turso_token = _get_secret("TURSO_AUTH_TOKEN").strip().strip('"').strip("'")

    # Convert libsql:// to https:// for HTTP API
    if _turso_url and _turso_url.startswith("libsql://"):
        _turso_url = _turso_url.replace("libsql://", "https://")

    # Ensure https:// prefix
    if _turso_url and not _turso_url.startswith("http"):
        _turso_url = "https://" + _turso_url

    _use_turso = bool(_turso_url and _turso_token)


# ─────────────────────────────────────────────────────────────────────────────
# Turso HTTP Wrapper — sqlite3-compatible interface
# ─────────────────────────────────────────────────────────────────────────────

class TursoRow:
    """Mimics sqlite3.Row so that row["column_name"] and row[0] both work."""
    def __init__(self, columns, values):
        self._columns = columns
        self._values = values
        self._map = {c: v for c, v in zip(columns, values)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def __contains__(self, key):
        return key in self._map

    def keys(self):
        return self._columns


class TursoCursor:
    """Mimics a sqlite3.Cursor returned by connection.execute()."""
    def __init__(self, columns, rows, affected_rows=0, last_rowid=None):
        self._columns = columns
        self._rows = [TursoRow(columns, r) for r in rows]
        self._pos = 0
        self.rowcount = affected_rows
        self.lastrowid = last_rowid
        self.description = [(c, None, None, None, None, None, None) for c in columns] if columns else None

    def fetchall(self):
        return self._rows

    def fetchone(self):
        if self._pos < len(self._rows):
            row = self._rows[self._pos]
            self._pos += 1
            return row
        return None

    def fetchmany(self, size=1):
        result = self._rows[self._pos:self._pos + size]
        self._pos += size
        return result

    def __iter__(self):
        return iter(self._rows)


class TursoConnection:
    """
    A sqlite3.Connection-compatible wrapper around Turso's HTTP Pipeline API.
    Endpoint: POST {database_url}/v2/pipeline
    """
    def __init__(self, base_url, auth_token):
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token
        self._headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }
        # Try v3 first (current), fall back to v2
        self._pipeline_url = self._find_pipeline_url()

    def _find_pipeline_url(self):
        """Detect which pipeline API version works."""
        for version in ("v3", "v2"):
            url = f"{self._base_url}/{version}/pipeline"
            try:
                resp = requests.post(
                    url,
                    headers=self._headers,
                    json={"requests": [{"type": "execute", "stmt": {"sql": "SELECT 1"}}]},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return url
            except Exception:
                continue
        # Default to v3
        return f"{self._base_url}/v3/pipeline"

    def _type_for_value(self, val):
        """Map Python value to Turso arg type."""
        if val is None:
            return {"type": "null"}
        elif isinstance(val, bool):
            return {"type": "integer", "value": "1" if val else "0"}
        elif isinstance(val, int):
            return {"type": "integer", "value": str(val)}
        elif isinstance(val, float):
            return {"type": "float", "value": str(val)}
        elif isinstance(val, bytes):
            import base64
            return {"type": "blob", "value": base64.b64encode(val).decode()}
        else:
            return {"type": "text", "value": str(val)}

    def _send_pipeline(self, statements):
        """Send a list of statement dicts to the pipeline endpoint."""
        requests_list = []
        for stmt in statements:
            requests_list.append({"type": "execute", "stmt": stmt})

        payload = {"requests": requests_list}

        try:
            resp = requests.post(
                self._pipeline_url,
                headers=self._headers,
                json=payload,
                timeout=30,
            )
            if resp.status_code >= 400:
                body = resp.text[:500]
                raise Exception(
                    f"Turso HTTP {resp.status_code}: {body} "
                    f"(URL: {self._pipeline_url})"
                )
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise Exception(
                f"Turso HTTP error: {e} "
                f"(URL: {self._pipeline_url})"
            )

    def _parse_result(self, result_obj):
        """Parse a single result from pipeline response into TursoCursor."""
        if result_obj.get("type") == "ok":
            response = result_obj.get("response", {})
            if response.get("type") == "execute":
                result = response.get("result", {})
                cols = [c.get("name", f"col_{i}") for i, c in enumerate(result.get("cols", []))]
                rows = []
                for row in result.get("rows", []):
                    row_values = []
                    for cell in row:
                        cell_type = cell.get("type", "null")
                        cell_value = cell.get("value")
                        if cell_type == "null":
                            row_values.append(None)
                        elif cell_type == "integer":
                            row_values.append(int(cell_value))
                        elif cell_type == "float":
                            row_values.append(float(cell_value))
                        else:
                            row_values.append(cell_value)
                    rows.append(row_values)
                return TursoCursor(
                    cols, rows,
                    affected_rows=result.get("affected_row_count", 0),
                    last_rowid=result.get("last_insert_rowid"),
                )
        elif result_obj.get("type") == "error":
            error = result_obj.get("error", {})
            raise Exception(f"Turso SQL error: {error.get('message', str(error))}")
        return TursoCursor([], [])

    def execute(self, sql, parameters=None):
        """Execute a single SQL statement immediately (like sqlite3)."""
        stmt = {"sql": sql}
        if parameters:
            stmt["args"] = [self._type_for_value(v) for v in parameters]

        response = self._send_pipeline([stmt])
        results = response.get("results", [])

        # Find the execute result (skip close result)
        for r in results:
            if r.get("type") == "error":
                error = r.get("error", {})
                raise Exception(f"Turso SQL error: {error.get('message', str(error))}")
            resp = r.get("response", {})
            if resp.get("type") == "execute":
                return self._parse_result(r)

        return TursoCursor([], [])

    def executemany(self, sql, param_list):
        """Execute the same SQL with multiple parameter sets."""
        statements = []
        for params in param_list:
            stmt = {"sql": sql, "args": [self._type_for_value(v) for v in params]}
            statements.append(stmt)

        if statements:
            self._send_pipeline(statements)

    def commit(self):
        """No-op — Turso HTTP API auto-commits each request."""
        pass

    def close(self):
        """No-op — HTTP connections are stateless."""
        pass

    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, val):
        pass  # TursoRow already provides dict-like access


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_connection():
    """
    Return a database connection (Turso HTTP or local SQLite).
    Both provide sqlite3-compatible API: execute(), commit(), close().
    """
    global _use_turso
    if _use_turso is None:
        _resolve_turso_config()

    if _use_turso:
        return TursoConnection(_turso_url, _turso_token)
    else:
        return _get_sqlite_connection()


def _get_sqlite_connection():
    """Standard local SQLite connection."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    return conn


def sync_to_cloud():
    """No-op — Turso HTTP API auto-commits. Kept for API compatibility."""
    pass


def is_cloud_db():
    """Check if we're using Turso cloud database."""
    global _use_turso
    if _use_turso is None:
        _resolve_turso_config()
    return _use_turso


def get_db_info() -> dict:
    """Return info about current database backend for Settings page."""
    global _use_turso
    if _use_turso is None:
        _resolve_turso_config()

    info = {
        "backend": "Turso (Cloud)" if _use_turso else "SQLite (Local)",
        "path": _turso_url if _use_turso else DB_PATH,
        "persistent": _use_turso,
    }

    # Add diagnostic info
    if _use_turso:
        # Mask the token but show first/last 4 chars
        masked_token = ""
        if _turso_token and len(_turso_token) > 8:
            masked_token = _turso_token[:4] + "…" + _turso_token[-4:]
        elif _turso_token:
            masked_token = "***"
        info["url"] = _turso_url
        info["token_preview"] = masked_token
        # Quick connectivity test — try v3 then v2
        info["connected"] = False
        for ver in ("v3", "v2"):
            test_url = f"{_turso_url.rstrip('/')}/{ver}/pipeline"
            try:
                test_resp = requests.post(
                    test_url,
                    headers={"Authorization": f"Bearer {_turso_token}", "Content-Type": "application/json"},
                    json={"requests": [{"type": "execute", "stmt": {"sql": "SELECT 1"}}]},
                    timeout=10,
                )
                info["pipeline_url"] = test_url
                info["status"] = f"HTTP {test_resp.status_code} ({ver})"
                if test_resp.status_code == 200:
                    info["connected"] = True
                    break
                else:
                    info["error"] = test_resp.text[:300]
            except Exception as e:
                info["pipeline_url"] = test_url
                info["error"] = str(e)[:300]
    else:
        info["turso_url_found"] = bool(_turso_url)
        info["turso_token_found"] = bool(_turso_token)

    return info
