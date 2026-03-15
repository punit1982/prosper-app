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


def _resolve_turso_config():
    """Resolve Turso credentials from env vars or Streamlit secrets."""
    global _turso_url, _turso_token, _use_turso

    # Try env vars first
    _turso_url = os.getenv("TURSO_DATABASE_URL", "")
    _turso_token = os.getenv("TURSO_AUTH_TOKEN", "")

    # Try Streamlit secrets if env vars empty
    if not _turso_url:
        try:
            import streamlit as st
            _turso_url = st.secrets.get("TURSO_DATABASE_URL", "")
            _turso_token = st.secrets.get("TURSO_AUTH_TOKEN", "")
        except Exception:
            pass
        if not _turso_url:
            try:
                import streamlit as st
                _turso_url = st.secrets["secrets"]["TURSO_DATABASE_URL"]
                _turso_token = st.secrets["secrets"]["TURSO_AUTH_TOKEN"]
            except Exception:
                pass

    # Convert libsql:// to https:// for HTTP API
    if _turso_url and _turso_url.startswith("libsql://"):
        _turso_url = _turso_url.replace("libsql://", "https://")

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
        self._pipeline_url = f"{self._base_url}/v2/pipeline"
        self._headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }
        self._pending = []  # Batch of statements to execute on commit

    def _type_for_value(self, val):
        """Map Python value to Turso arg type."""
        if val is None:
            return {"type": "null", "value": None}
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
        requests_list.append({"type": "close"})

        payload = {"requests": requests_list}

        try:
            resp = requests.post(
                self._pipeline_url,
                headers=self._headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Turso HTTP error: {e}")

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
    return {
        "backend": "Turso (Cloud)" if _use_turso else "SQLite (Local)",
        "path": _turso_url if _use_turso else DB_PATH,
        "persistent": _use_turso,
    }
