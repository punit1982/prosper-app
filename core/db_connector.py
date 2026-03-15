"""
Database Connector — Turso (cloud) or SQLite (local)
=====================================================
Automatically selects the right backend:
  - If TURSO_DATABASE_URL is set → uses libsql with embedded replica
  - Otherwise → uses standard sqlite3 (local file)

Both provide identical sqlite3-compatible API (execute, fetchall, commit, etc.)
"""

import os
import sqlite3

# Store local DB in home directory
DB_DIR = os.path.expanduser("~/prosper_data")
DB_PATH = os.path.join(DB_DIR, "prosper.db")

# Turso connection config
TURSO_URL = None
TURSO_TOKEN = None
_turso_conn = None
_use_turso = False

def _resolve_turso_config():
    """Resolve Turso credentials from env vars or Streamlit secrets."""
    global TURSO_URL, TURSO_TOKEN, _use_turso

    # Try env vars first
    TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
    TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")

    # Try Streamlit secrets if env vars empty
    if not TURSO_URL:
        try:
            import streamlit as st
            TURSO_URL = st.secrets.get("TURSO_DATABASE_URL", "")
            TURSO_TOKEN = st.secrets.get("TURSO_AUTH_TOKEN", "")
        except Exception:
            pass
        # Also try nested [secrets] table
        if not TURSO_URL:
            try:
                import streamlit as st
                TURSO_URL = st.secrets["secrets"]["TURSO_DATABASE_URL"]
                TURSO_TOKEN = st.secrets["secrets"]["TURSO_AUTH_TOKEN"]
            except Exception:
                pass

    _use_turso = bool(TURSO_URL and TURSO_TOKEN)


def get_connection():
    """
    Return a database connection (Turso or SQLite).

    Both return sqlite3-compatible connection objects with:
      - .execute(sql, params)
      - .executemany(sql, params_list)
      - .commit()
      - .close()
      - cursor.fetchall(), cursor.fetchone()
    """
    global _turso_conn, _use_turso

    # Lazy resolve config on first call
    if TURSO_URL is None:
        _resolve_turso_config()

    if _use_turso:
        return _get_turso_connection()
    else:
        return _get_sqlite_connection()


def _get_sqlite_connection():
    """Standard local SQLite connection."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrent read performance
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _get_turso_connection():
    """Turso/libsql connection with embedded replica for speed."""
    global _turso_conn

    try:
        import libsql

        # Reuse existing connection if available
        if _turso_conn is not None:
            try:
                # Test if connection is still alive
                _turso_conn.execute("SELECT 1")
                return _turso_conn
            except Exception:
                _turso_conn = None

        # Create new connection with embedded replica (local cache + cloud sync)
        os.makedirs(DB_DIR, exist_ok=True)
        local_replica = os.path.join(DB_DIR, "prosper_replica.db")

        _turso_conn = libsql.connect(
            local_replica,
            sync_url=TURSO_URL,
            auth_token=TURSO_TOKEN,
        )
        _turso_conn.sync()

        return _turso_conn

    except ImportError:
        # libsql not installed — fall back to local SQLite
        print("⚠️ libsql not installed. Falling back to local SQLite. Install with: pip install libsql")
        return _get_sqlite_connection()
    except Exception as e:
        # Turso connection failed — fall back to local SQLite
        print(f"⚠️ Turso connection failed: {e}. Falling back to local SQLite.")
        return _get_sqlite_connection()


def sync_to_cloud():
    """Sync embedded replica to Turso cloud. Call after writes."""
    global _turso_conn
    if _use_turso and _turso_conn is not None:
        try:
            _turso_conn.sync()
        except Exception:
            pass  # Non-critical — sync will happen on next connection


def is_cloud_db():
    """Check if we're using Turso cloud database."""
    if TURSO_URL is None:
        _resolve_turso_config()
    return _use_turso


def get_db_info() -> dict:
    """Return info about current database backend for Settings page."""
    if TURSO_URL is None:
        _resolve_turso_config()
    return {
        "backend": "Turso (Cloud)" if _use_turso else "SQLite (Local)",
        "path": TURSO_URL if _use_turso else DB_PATH,
        "persistent": _use_turso,
    }
