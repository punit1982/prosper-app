import sqlite3
import os
import json
import time
import pandas as pd
import streamlit as st
from typing import Optional, List, Dict
from datetime import datetime, timedelta

from core.db_connector import get_connection as _get_cloud_connection, sync_to_cloud, is_cloud_db, DB_PATH

# ─────────────────────────────────────────
# SESSION CACHE KEYS — avoid redundant Turso HTTP calls
# ─────────────────────────────────────────
_HOLDINGS_CACHE_KEY = "_prosper_holdings_cache"
_REALIZED_PNL_CACHE_KEY = "_prosper_realized_pnl_cache"
_NAV_HISTORY_CACHE_KEY = "_prosper_nav_history_cache"
_ANALYSES_CACHE_KEY = "_prosper_analyses_cache"
_CASH_POSITIONS_CACHE_KEY = "_prosper_cash_positions_cache"


def _get_connection():
    """Get a database connection (Turso cloud or local SQLite)."""
    return _get_cloud_connection()


def _current_user_id() -> str:
    """Resolve the active user_id from session_state.

    A1 multi-tenancy guard: every multi-tenant query MUST scope by this.
    Returns 'default' for the legacy single-user shard or when auth disabled.
    """
    try:
        uid = st.session_state.get("user_id") or "default"
        return str(uid).strip() or "default"
    except Exception:
        return "default"


def _invalidate_holdings_cache(portfolio_id: int = None):
    """Clear cached holdings for the active portfolio so next read hits the DB.

    B11: scoped to the active portfolio when possible — clearing every
    `enriched_*` key on any write thrashes unrelated portfolios in the same session.
    """
    try:
        pid = portfolio_id or st.session_state.get("active_portfolio_id", 1)
        prefixes_to_clear = (
            f"{_HOLDINGS_CACHE_KEY}_{pid}",
            f"enriched_{pid}_",
        )
        exact_to_clear = {
            "extended_df", "last_refresh_time",
            _REALIZED_PNL_CACHE_KEY, _ANALYSES_CACHE_KEY,
        }
        for key in list(st.session_state.keys()):
            if any(key.startswith(p) for p in prefixes_to_clear) or key in exact_to_clear:
                del st.session_state[key]
    except Exception:
        pass


def _read_sql(query: str, conn, params=None) -> pd.DataFrame:
    """
    Run a SELECT query and return a DataFrame.
    Works with both sqlite3 connections (pd.read_sql_query) and
    TursoConnection (manual cursor → DataFrame conversion).
    """
    if isinstance(conn, sqlite3.Connection):
        return pd.read_sql_query(query, conn, params=params)
    else:
        # TursoConnection — execute and build DataFrame manually
        cursor = conn.execute(query, params or [])
        rows = cursor.fetchall()
        if not rows:
            # Try to get column names from cursor description
            cols = [d[0] for d in cursor.description] if cursor.description else []
            return pd.DataFrame(columns=cols)
        cols = rows[0].keys() if hasattr(rows[0], 'keys') else []
        data = [[row[c] for c in cols] for row in rows]
        return pd.DataFrame(data, columns=cols)


def init_db():
    """Create all tables if they don't exist.

    PERFORMANCE: On Turso, all CREATE TABLE statements are batched into a
    SINGLE HTTP pipeline call (1 request instead of 10). Also skipped entirely
    if already done this session.
    """
    # Skip if already initialized this session
    if st.session_state.get("_db_initialized"):
        return

    _TABLE_STATEMENTS = [
        """CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL, name TEXT,
            quantity REAL NOT NULL, avg_cost REAL NOT NULL,
            currency TEXT DEFAULT 'USD', broker_source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS parse_cache (
            image_hash TEXT PRIMARY KEY, result_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS price_cache (
            ticker TEXT PRIMARY KEY, price REAL, change_val REAL,
            change_pct REAL, source TEXT DEFAULT 'unknown',
            fetched_at REAL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS news_cache (
            cache_key TEXT PRIMARY KEY, news_json TEXT NOT NULL,
            fetched_at REAL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS ticker_cache (
            ticker TEXT PRIMARY KEY, resolved TEXT NOT NULL,
            fetched_at REAL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL, name TEXT, type TEXT NOT NULL,
            quantity REAL NOT NULL, price REAL NOT NULL,
            currency TEXT DEFAULT 'USD', fees REAL DEFAULT 0,
            date TEXT NOT NULL, broker_source TEXT, notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL, name TEXT, currency TEXT DEFAULT 'USD',
            target_price REAL, notes TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS nav_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, total_value REAL NOT NULL,
            total_cost REAL, unrealized_pnl REAL, realized_pnl REAL,
            holdings_count INTEGER, base_currency TEXT DEFAULT 'USD',
            snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, base_currency))""",
        """CREATE TABLE IF NOT EXISTS prosper_analysis (
            ticker TEXT PRIMARY KEY, analysis_date TEXT NOT NULL,
            model_used TEXT DEFAULT 'sonnet', rating TEXT, score REAL,
            archetype TEXT, archetype_name TEXT,
            fair_value_base REAL, fair_value_bear REAL, fair_value_bull REAL,
            upside_pct REAL, conviction TEXT, thesis TEXT, env_net TEXT,
            score_breakdown TEXT, key_risks TEXT, key_catalysts TEXT,
            full_response TEXT, cost_estimate REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS cash_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_name TEXT NOT NULL,
            currency TEXT DEFAULT 'USD',
            amount REAL NOT NULL DEFAULT 0,
            is_margin INTEGER DEFAULT 0,
            margin_rate REAL,
            broker_source TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS fortress_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            user_id TEXT DEFAULT 'default',
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS briefing_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            briefing_date TEXT NOT NULL,
            currency TEXT DEFAULT 'USD',
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS user_preferences (
            user_id TEXT PRIMARY KEY,
            settings_json TEXT DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            first_name TEXT,
            last_name TEXT,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS ai_call_cache (
            call_hash TEXT PRIMARY KEY,
            response_text TEXT NOT NULL,
            ttl_days INTEGER DEFAULT 7,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    ]

    # ── Performance indexes on frequently queried columns ──
    _INDEX_STATEMENTS = [
        "CREATE INDEX IF NOT EXISTS idx_holdings_portfolio ON holdings(portfolio_id)",
        "CREATE INDEX IF NOT EXISTS idx_holdings_ticker ON holdings(ticker)",
        "CREATE INDEX IF NOT EXISTS idx_holdings_user ON holdings(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_cash_user ON cash_positions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_portfolios_user ON portfolios(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_price_cache_ticker ON price_cache(ticker)",
        "CREATE INDEX IF NOT EXISTS idx_nav_snapshots_currency ON nav_snapshots(base_currency)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_ticker ON transactions(ticker)",
        # A5: bootstrap admin uniqueness — at most one admin during first-run.
        # Day-2 promotion via UPDATE works because the index targets INSERT paths.
        "CREATE UNIQUE INDEX IF NOT EXISTS uniq_one_admin ON users(role) WHERE role = 'admin'",
    ]

    conn = _get_connection()

    # Turso: batch all statements in ONE HTTP call
    if hasattr(conn, 'execute_batch'):
        conn.execute_batch(_TABLE_STATEMENTS + _INDEX_STATEMENTS)
    else:
        # SQLite: execute one by one (fast locally)
        for sql in _TABLE_STATEMENTS + _INDEX_STATEMENTS:
            conn.execute(sql)
        conn.commit()

    conn.close()

    # ── Migrations: add portfolio_id column if missing ──
    # Use ALTER TABLE directly (works on both SQLite & Turso); catch "duplicate" error
    try:
        conn2 = _get_connection()
        try:
            conn2.execute("ALTER TABLE holdings ADD COLUMN portfolio_id INTEGER DEFAULT 1")
            conn2.commit()
        except Exception:
            pass  # Column already exists — that's fine
        # Ensure default portfolio exists
        try:
            _default = conn2.execute("SELECT id FROM portfolios WHERE id = 1").fetchone()
            if not _default:
                conn2.execute("INSERT INTO portfolios (id, name, description) VALUES (1, 'Main Portfolio', 'Default portfolio')")
                conn2.commit()
        except Exception:
            pass
        # Migration: add user_id column to portfolios if missing
        try:
            conn2.execute("ALTER TABLE portfolios ADD COLUMN user_id TEXT DEFAULT 'default'")
            conn2.commit()
        except Exception:
            pass  # Column already exists — that's fine
        # A1 multi-tenancy migration: add user_id to every multi-tenant table.
        # Existing rows fall into the 'default' shard, preserving legacy single-user data.
        for _table in (
            "holdings", "transactions", "cash_positions", "watchlist",
            "nav_snapshots", "prosper_analysis", "briefing_cache",
            "fortress_state", "parse_cache", "ai_call_cache",
        ):
            try:
                conn2.execute(f"ALTER TABLE {_table} ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")
                conn2.commit()
            except Exception:
                pass  # Column already exists
        conn2.close()
    except Exception:
        pass  # Migration is best-effort — app works without it

    # ── Migration: copy users from auth_config.yaml into the users table ──
    _migrate_yaml_users_to_db()

    # A4: rotate any password_hash equal to bcrypt(email) — closes
    # the email-as-password fallback for legacy Google-OAuth users.
    try:
        rotate_oauth_user_passwords()
    except Exception:
        pass

    st.session_state["_db_initialized"] = True


# ─────────────────────────────────────────
# PORTFOLIOS
# ─────────────────────────────────────────

def get_all_portfolios(user_id: str = None) -> pd.DataFrame:
    """Return portfolios scoped to user_id.

    A1: defaults to the current user — never returns unfiltered results,
    which previously leaked every user's portfolios across tenants.
    """
    if user_id is None:
        user_id = _current_user_id()
    conn = _get_connection()
    try:
        df = _read_sql(
            "SELECT * FROM portfolios WHERE user_id = ? ORDER BY id ASC",
            conn, params=(user_id,),
        )
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


def create_portfolio(name: str, description: str = "", user_id: str = None) -> int:
    """Create a new portfolio for the given user. Returns its ID.

    A1: legacy schema has UNIQUE on portfolios.name, so two users can't both
    claim "Main Portfolio" by name. We retry with " (alice@…)" suffix on
    collision so each tenant gets its own row instead of silently sharing
    the global ID=1 portfolio.
    """
    if user_id is None:
        user_id = _current_user_id()
    base_name = name.strip()
    desc = description.strip()

    candidate = base_name
    for attempt in range(5):
        conn = _get_connection()
        try:
            conn.execute(
                "INSERT INTO portfolios (name, description, user_id) VALUES (?, ?, ?)",
                (candidate, desc, user_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id FROM portfolios WHERE name = ? AND user_id = ?",
                (candidate, user_id),
            ).fetchone()
            if row:
                return row[0] if isinstance(row, (tuple, list)) else row["id"]
            return -1
        except Exception:
            # UNIQUE collision on `name` — disambiguate with the user_id suffix.
            short_uid = (user_id or "user").split("@")[0][:12]
            candidate = f"{base_name} ({short_uid})" if attempt == 0 else f"{base_name} ({short_uid} {attempt})"
        finally:
            try:
                conn.close()
            except Exception:
                pass
    # Last resort — re-query for any portfolio owned by this user
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM portfolios WHERE user_id = ? ORDER BY id ASC LIMIT 1",
            (user_id,),
        ).fetchone()
        if row:
            return row[0] if isinstance(row, (tuple, list)) else row["id"]
    finally:
        conn.close()
    return -1  # signal failure rather than the legacy magic ID 1


def rename_portfolio(portfolio_id: int, new_name: str):
    """Rename a portfolio — verifies the caller owns it."""
    uid = _current_user_id()
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE portfolios SET name = ? WHERE id = ? AND user_id = ?",
            (new_name.strip(), portfolio_id, uid),
        )
        conn.commit()
    finally:
        conn.close()


def delete_portfolio(portfolio_id: int):
    """Delete a portfolio and all its holdings — verifies ownership first.

    A1: scope by user_id so a logged-in user cannot delete another user's portfolio
    by passing its ID. Also refuses to delete the user's last remaining portfolio
    (the legacy magic-number `portfolio_id == 1` check was wrong post-multitenancy
    because every user now gets their own "Main Portfolio" with a different ID).
    """
    uid = _current_user_id()
    conn = _get_connection()
    try:
        # Ownership check
        owner_row = conn.execute(
            "SELECT user_id FROM portfolios WHERE id = ?", (portfolio_id,)
        ).fetchone()
        if not owner_row:
            return
        owner = owner_row[0] if isinstance(owner_row, (tuple, list)) else owner_row["user_id"]
        if owner != uid:
            return  # Not owned by this user — silent refuse

        # Refuse deletion of the user's last portfolio
        remaining = conn.execute(
            "SELECT COUNT(*) FROM portfolios WHERE user_id = ?", (uid,)
        ).fetchone()
        count = remaining[0] if isinstance(remaining, (tuple, list)) else remaining[0]
        if count <= 1:
            return  # Cannot delete last portfolio for this user

        try:
            conn.execute(
                "DELETE FROM holdings WHERE portfolio_id = ? AND user_id = ?",
                (portfolio_id, uid),
            )
        except Exception:
            pass
        conn.execute("DELETE FROM portfolios WHERE id = ? AND user_id = ?", (portfolio_id, uid))
        conn.commit()
    finally:
        conn.close()
    _invalidate_holdings_cache()


def get_active_portfolio_id() -> int:
    """Return the currently selected portfolio ID from session state.

    Falls back to the user's first owned portfolio (NOT magic ID 1, which
    leaks across users). Lazily creates one if none exists.
    """
    pid = st.session_state.get("active_portfolio_id")
    if pid:
        return pid
    uid = _current_user_id()
    pid = _ensure_user_default_portfolio(uid)
    st.session_state["active_portfolio_id"] = pid
    return pid


def _ensure_user_default_portfolio(user_id: str) -> int:
    """Return the user's main portfolio ID, creating one if needed.

    A1: each user gets their own portfolio row instead of sharing global ID=1.

    Legacy data inheritance: if this is the FIRST admin signing in AND legacy
    rows tagged user_id='default' exist (from pre-multitenancy single-user
    mode), reassign them to this admin so the user keeps seeing their data.
    Idempotent — runs at most once because subsequent calls find the user's
    own portfolio row immediately.
    """
    try:
        conn = _get_connection()
        row = conn.execute(
            "SELECT id FROM portfolios WHERE user_id = ? ORDER BY id ASC LIMIT 1",
            (user_id,),
        ).fetchone()
        conn.close()
        if row:
            return row[0] if isinstance(row, (tuple, list)) else row["id"]
    except Exception:
        pass

    # Legacy auto-claim: only when there's exactly ONE user (this admin)
    # and legacy 'default' data exists. Multi-user installs are unaffected.
    try:
        _claim_legacy_default_shard(user_id)
        # After reassignment the user's portfolio query may now succeed.
        conn = _get_connection()
        row = conn.execute(
            "SELECT id FROM portfolios WHERE user_id = ? ORDER BY id ASC LIMIT 1",
            (user_id,),
        ).fetchone()
        conn.close()
        if row:
            return row[0] if isinstance(row, (tuple, list)) else row["id"]
    except Exception:
        pass
    # Create one — create_portfolio returns -1 on hard failure rather
    # than the legacy magic ID 1 (which would cause cross-tenant sharing).
    try:
        new_id = create_portfolio(
            name="Main Portfolio",
            description="Default portfolio",
            user_id=user_id,
        )
        if new_id and new_id > 0:
            return new_id
    except Exception:
        pass
    return 1  # Last-resort fallback (legacy single-user); user_id scope still isolates data


def _claim_legacy_default_shard(user_id: str) -> None:
    """One-shot reassignment of pre-multitenancy data ('default' shard) to user_id.

    Runs only when:
      1. There's exactly ONE non-default user account in the DB (this user).
      2. Legacy rows tagged user_id='default' actually exist.

    Both conditions ensure we only touch single-user installs upgrading from
    the old schema. Multi-user installs see this as a no-op.
    """
    if not user_id or user_id == "default":
        return
    conn = _get_connection()
    try:
        # Count real users (excluding the legacy 'default' sentinel).
        users_row = conn.execute(
            "SELECT COUNT(*) FROM users WHERE username != 'default'"
        ).fetchone()
        n_users = users_row[0] if users_row else 0
        if n_users != 1:
            return  # Multi-user install — refuse to auto-claim.

        # Reassign every multi-tenant table.
        tables = (
            "holdings", "transactions", "cash_positions", "watchlist",
            "nav_snapshots", "portfolios",
        )
        for tbl in tables:
            try:
                conn.execute(f"UPDATE {tbl} SET user_id = ? WHERE user_id = 'default'", (user_id,))
            except Exception:
                continue
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def get_or_create_user_portfolios(user_id: str) -> pd.DataFrame:
    """Return portfolios owned by user_id, creating a default one if none exist.

    A1: NEVER falls back to unfiltered queries — the previous behavior
    silently leaked all users' portfolios when the per-user query came up empty.
    """
    df = get_all_portfolios(user_id=user_id)
    if df.empty:
        _ensure_user_default_portfolio(user_id)
        df = get_all_portfolios(user_id=user_id)
    return df


# ─────────────────────────────────────────
# USER PREFERENCES  (per-user settings)
# ─────────────────────────────────────────

def get_user_settings_db(user_id: str) -> dict:
    """Return per-user settings dict from the user_preferences table. Empty dict if none found."""
    try:
        conn = _get_connection()
        row = conn.execute(
            "SELECT settings_json FROM user_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        if row:
            raw = row[0] if isinstance(row, (tuple, list)) else row["settings_json"]
            return json.loads(raw) if raw else {}
    except Exception:
        pass
    return {}


def save_user_settings_db(user_id: str, settings: dict) -> None:
    """Upsert per-user settings into the user_preferences table."""
    try:
        conn = _get_connection()
        conn.execute(
            """INSERT OR REPLACE INTO user_preferences (user_id, settings_json, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)""",
            (user_id, json.dumps(settings, default=str)),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─────────────────────────────────────────
# BRIEFING CACHE
# ─────────────────────────────────────────

def save_briefing(briefing_date: str, currency: str, content: str):
    """Save an AI briefing to the database for persistence across sessions."""
    try:
        conn = _get_connection()
        # Delete old briefings for this date+currency to avoid duplicates
        conn.execute("DELETE FROM briefing_cache WHERE briefing_date = ? AND currency = ?", (briefing_date, currency))
        conn.execute(
            "INSERT INTO briefing_cache (briefing_date, currency, content) VALUES (?, ?, ?)",
            (briefing_date, currency, content),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Best-effort — app works without persistence


def get_latest_briefing(currency: str = "USD") -> Optional[Dict]:
    """Get the most recent briefing (today or yesterday) from the database."""
    try:
        conn = _get_connection()
        row = conn.execute(
            "SELECT briefing_date, content, created_at FROM briefing_cache WHERE currency = ? ORDER BY briefing_date DESC, created_at DESC LIMIT 1",
            (currency,),
        ).fetchone()
        conn.close()
        if row:
            if isinstance(row, dict):
                return {"date": row.get("briefing_date", ""), "content": row.get("content", ""), "created_at": row.get("created_at", "")}
            return {"date": row[0], "content": row[1], "created_at": row[2]}
    except Exception:
        pass
    return None


# ─────────────────────────────────────────
# HOLDINGS
# ─────────────────────────────────────────

def save_holdings(df: pd.DataFrame, broker_source: str = None, portfolio_id: int = None):
    """Upsert holdings from a DataFrame into the database — atomic per A1+B2.

    A1: every row is tagged with the active user_id so it cannot leak to others.
    B2: DELETE+INSERT happens inside a single transaction (BEGIN/COMMIT) so a
        mid-flight failure cannot orphan or destroy holdings.
    """
    uid = _current_user_id()
    pid = portfolio_id or get_active_portfolio_id()
    conn = _get_connection()
    try:
        rows = []
        for _, row in df.iterrows():
            _ticker = str(row.get("ticker", "") or "").strip()
            if not _ticker:
                continue
            _name = str(row.get("name", "") or "").strip()
            _qty = float(row.get("quantity", 0) or 0)
            _cost = float(row.get("avg_cost", 0) or 0)
            _ccy = str(row.get("currency", "USD") or "USD").strip()
            _src = broker_source or ""
            rows.append((_ticker, _name, _qty, _cost, _ccy, _src))

        if not rows:
            conn.close()
            return

        # B2: prefer atomic pipeline transaction on Turso
        if hasattr(conn, "execute_in_transaction"):
            stmts = []
            for t in rows:
                stmts.append((
                    "DELETE FROM holdings WHERE portfolio_id = ? AND user_id = ? AND ticker = ?",
                    (pid, uid, t[0]),
                ))
            for t in rows:
                stmts.append((
                    "INSERT INTO holdings (ticker, name, quantity, avg_cost, currency, broker_source, portfolio_id, user_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (t[0], t[1], t[2], t[3], t[4], t[5], pid, uid),
                ))
            conn.execute_in_transaction(stmts)
        else:
            # SQLite path — `with conn:` is implicit transactional
            try:
                conn.execute("BEGIN")
            except Exception:
                pass
            conn.executemany(
                "DELETE FROM holdings WHERE portfolio_id = ? AND user_id = ? AND ticker = ?",
                [(pid, uid, t[0]) for t in rows],
            )
            conn.executemany(
                "INSERT INTO holdings (ticker, name, quantity, avg_cost, currency, broker_source, portfolio_id, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(t[0], t[1], t[2], t[3], t[4], t[5], pid, uid) for t in rows],
            )
            conn.commit()

        conn.close()
        _invalidate_holdings_cache(pid)
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        # Log server-side; do NOT echo raw exception to UI (can leak schema/path info)
        import logging as _lg
        _lg.getLogger("prosper.db").exception("save_holdings failed")
        st.error("Database save failed. Please try again or contact support.")
        raise


def get_all_holdings(portfolio_id: int = None) -> pd.DataFrame:
    """Retrieve holdings for the active portfolio AND active user (A1).

    Session-cached. Returns empty DataFrame if user/portfolio combination
    has no rows — never falls back to unfiltered (which leaked across users).
    """
    uid = _current_user_id()
    pid = portfolio_id or get_active_portfolio_id()
    cache_key = f"{_HOLDINGS_CACHE_KEY}_{uid}_{pid}"
    try:
        cached = st.session_state.get(cache_key)
        if cached is not None:
            return cached.copy()
    except Exception:
        pass

    conn = _get_connection()
    try:
        df = _read_sql(
            "SELECT * FROM holdings WHERE portfolio_id = ? AND user_id = ? ORDER BY ticker ASC",
            conn, params=(pid, uid),
        )
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()

    try:
        st.session_state[cache_key] = df.copy()
    except Exception:
        pass
    return df


def update_holding(holding_id: int, **kwargs):
    """Update fields of a holding — scoped by current user_id (A1)."""
    allowed = {"quantity", "avg_cost", "currency", "broker_source"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return
    uid = _current_user_id()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [holding_id, uid]
    conn = _get_connection()
    try:
        conn.execute(
            f"UPDATE holdings SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
            f"WHERE id = ? AND user_id = ?",
            values,
        )
        conn.commit()
    finally:
        conn.close()
    _invalidate_holdings_cache()


def delete_holding(holding_id: int):
    """Delete a holding by ID — scoped by current user_id (A1)."""
    uid = _current_user_id()
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM holdings WHERE id = ? AND user_id = ?", (holding_id, uid))
        conn.commit()
    finally:
        conn.close()
    _invalidate_holdings_cache()


def clear_all_holdings(portfolio_id: int = None):
    """Delete all holdings for active portfolio + active user (A1)."""
    uid = _current_user_id()
    pid = portfolio_id or get_active_portfolio_id()
    conn = _get_connection()
    try:
        conn.execute(
            "DELETE FROM holdings WHERE portfolio_id = ? AND user_id = ?",
            (pid, uid),
        )
        conn.commit()
    finally:
        conn.close()
    _invalidate_holdings_cache(pid)


# ─────────────────────────────────────────
# PARSE CACHE
# ─────────────────────────────────────────

def get_cached_parse(image_hash: str, ttl_days: int = 90) -> Optional[List[Dict]]:
    """
    Return cached parse result for an image hash if it exists and isn't expired.
    Returns None if no valid cache entry found.
    """
    conn = _get_connection()
    row = conn.execute(
        "SELECT result_json, created_at FROM parse_cache WHERE image_hash = ?",
        (image_hash,),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    # Check TTL
    created_at = datetime.fromisoformat(str(row["created_at"]))
    if datetime.now() - created_at > timedelta(days=ttl_days):
        return None  # Expired

    try:
        return json.loads(row["result_json"])
    except (json.JSONDecodeError, TypeError):
        return None


def save_parse_cache(image_hash: str, result: List[Dict]):
    """Save a successful parse result to the cache."""
    conn = _get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO parse_cache (image_hash, result_json, created_at)
           VALUES (?, ?, ?)""",
        (image_hash, json.dumps(result), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def clear_parse_cache():
    """Wipe the entire parse cache (forces re-parsing all screenshots)."""
    conn = _get_connection()
    conn.execute("DELETE FROM parse_cache")
    conn.commit()
    conn.close()


def get_parse_cache_stats() -> dict:
    """Return stats about the parse cache for display in the UI."""
    conn = _get_connection()
    count = conn.execute("SELECT COUNT(*) FROM parse_cache").fetchone()[0]
    conn.close()
    return {"cached_images": count}


# ─────────────────────────────────────────
# AI CALL CACHE  (prevents repeated identical Claude calls)
# ─────────────────────────────────────────

def get_ai_cache(call_hash: str, ttl_days: int = 7) -> Optional[str]:
    """Return cached AI response text if it exists and hasn't expired."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT response_text, created_at FROM ai_call_cache WHERE call_hash = ?",
            (call_hash,),
        ).fetchone()
        if row:
            created = row[1] if isinstance(row, (list, tuple)) else row["created_at"]
            age = datetime.now() - datetime.fromisoformat(str(created))
            if age < timedelta(days=ttl_days):
                return row[0] if isinstance(row, (list, tuple)) else row["response_text"]
    except Exception:
        pass
    finally:
        conn.close()
    return None


def save_ai_cache(call_hash: str, response_text: str, ttl_days: int = 7):
    """Persist an AI response to the cache."""
    conn = _get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO ai_call_cache (call_hash, response_text, ttl_days, created_at)
               VALUES (?, ?, ?, ?)""",
            (call_hash, response_text, ttl_days, datetime.now().isoformat()),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ─────────────────────────────────────────
# PRICE CACHE  (persists across restarts)
# ─────────────────────────────────────────

PRICE_CACHE_TTL = 900   # 15 minutes — re-fetch if older than this (was 5min, too aggressive for 116+ tickers)


def get_price_cache(tickers: List[str]) -> Dict[str, dict]:
    """
    Read cached prices from SQLite for the given tickers.
    Returns: { ticker: {price, change, change_pct, source, fetched_at}, ... }
    Only returns entries — missing tickers simply won't be in the dict.
    """
    if not tickers:
        return {}
    try:
        conn = _get_connection()
        placeholders = ",".join("?" * len(tickers))
        rows = conn.execute(
            f"SELECT ticker, price, change_val, change_pct, source, fetched_at "
            f"FROM price_cache WHERE ticker IN ({placeholders})",
            tickers,
        ).fetchall()
        conn.close()
        return {
            row["ticker"]: {
                "price":             row["price"],
                "change":            row["change_val"],
                "changesPercentage": row["change_pct"],
                "source":            row["source"] or "cached",
                "fetched_at":        row["fetched_at"] or 0,
            }
            for row in rows
            if row["price"] is not None
        }
    except Exception:
        return {}


def save_price_cache(quotes: Dict[str, dict]) -> None:
    """
    Write fresh price data to SQLite price_cache.
    quotes: { ticker: {price, change, changesPercentage, source} }

    Entries with price=None are saved as failed attempts (price=NULL, fetched_at=now).
    get_stale_tickers() will skip these for 30 min, preventing repeated retries
    for dead UAE/delisted tickers that never return a price.
    """
    if not quotes:
        return
    now = time.time()
    rows = [
        (
            ticker,
            data.get("price") if data else None,
            data.get("change") if data else None,
            data.get("changesPercentage") if data else None,
            data.get("source", "failed") if data else "failed",
            now,
        )
        for ticker, data in quotes.items()
    ]
    if not rows:
        return
    try:
        conn = _get_connection()
        conn.executemany(
            """INSERT OR REPLACE INTO price_cache
               (ticker, price, change_val, change_pct, source, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def save_failed_tickers(tickers: List[str]) -> None:
    """
    Mark tickers as having no available price (failed_at = now, price = NULL).
    These won't be retried for FAILED_TICKER_COOLDOWN seconds (30 min by default).
    """
    if not tickers:
        return
    save_price_cache({t: None for t in tickers})


FAILED_TICKER_COOLDOWN = 600  # 10 min — retry sooner (was 30 min)


def get_stale_tickers(tickers: List[str], max_age: float = PRICE_CACHE_TTL) -> List[str]:
    """
    Return tickers that need a fresh price fetch:
    - Missing entirely from price_cache
    - Cached price exists but is older than max_age (5 min default)
    - Failed attempt (price=NULL) whose fetched_at is older than 30 min cooldown

    Tickers with a recent failed attempt (price=NULL, < 30 min ago) are skipped —
    this avoids hammering dead UAE/delisted tickers on every refresh cycle.
    """
    if not tickers:
        return []
    try:
        conn = _get_connection()
        placeholders = ",".join("?" * len(tickers))
        rows = conn.execute(
            f"SELECT ticker, price, fetched_at FROM price_cache WHERE ticker IN ({placeholders})",
            tickers,
        ).fetchall()
        conn.close()

        cache_map = {r["ticker"]: (r["price"], r["fetched_at"] or 0) for r in rows}
        now  = time.time()
        stale = []
        for t in tickers:
            if t not in cache_map:
                stale.append(t)   # Never attempted → fetch
            else:
                price, fetched_at = cache_map[t]
                age = now - fetched_at
                if price is not None and age > max_age:
                    stale.append(t)   # Good price but stale → re-fetch
                elif price is None and age > FAILED_TICKER_COOLDOWN:
                    stale.append(t)   # Failed long ago → retry
                # else: fresh price OR recent failure → skip
        return stale
    except Exception:
        # Fallback to simple cache-miss logic
        cached = get_price_cache(tickers)
        now = time.time()
        return [t for t in tickers
                if t not in cached or (now - cached[t].get("fetched_at", 0)) > max_age]


def get_price_cache_age() -> Optional[float]:
    """Return age in seconds of the MOST RECENT cached price, or None if empty.

    Uses MAX (most recent) instead of MIN to show when data was last refreshed.
    Excludes fetched_at=0 (default/unset values).
    """
    try:
        cached_ts = st.session_state.get("_price_cache_max_ts")
        if cached_ts is not None:
            return time.time() - cached_ts if cached_ts > 1000000000 else None  # Sanity: must be a valid epoch
    except Exception:
        pass

    try:
        conn = _get_connection()
        # Use MAX to get the most recent fetch time; exclude 0s and very old values
        row = conn.execute(
            "SELECT MAX(fetched_at) FROM price_cache WHERE price IS NOT NULL AND fetched_at > 1000000000"
        ).fetchone()
        conn.close()
        val = row[0] if row else None
        # Handle Turso returning string or numeric
        if val is not None:
            ts = float(val)
            if ts > 1000000000:  # Valid UNIX epoch (post-2001)
                try:
                    st.session_state["_price_cache_max_ts"] = ts
                except Exception:
                    pass
                return time.time() - ts
        try:
            st.session_state["_price_cache_max_ts"] = 0
        except Exception:
            pass
        return None
    except Exception:
        return None


# ─────────────────────────────────────────
# NEWS CACHE  (persists across restarts)
# ─────────────────────────────────────────

NEWS_CACHE_TTL = 3600   # 1 hour


def get_news_cache(cache_key: str, max_age: float = NEWS_CACHE_TTL) -> Optional[List]:
    """
    Read cached news from SQLite.
    Returns list of news dicts if fresh, or None if missing/stale.
    """
    try:
        conn = _get_connection()
        row = conn.execute(
            "SELECT news_json, fetched_at FROM news_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        age = time.time() - (row["fetched_at"] or 0)
        if age > max_age:
            return None
        return json.loads(row["news_json"])
    except Exception:
        return None


def save_news_cache(cache_key: str, news: List) -> None:
    """Write news list to SQLite news_cache."""
    try:
        conn = _get_connection()
        conn.execute(
            """INSERT OR REPLACE INTO news_cache (cache_key, news_json, fetched_at)
               VALUES (?, ?, ?)""",
            (cache_key, json.dumps(news, default=str), time.time()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─────────────────────────────────────────
# FX RATE CACHE  (1-hour TTL — survives server restarts)
# Stores FX pair rates so they don't need re-fetching on every restart.
# ─────────────────────────────────────────

FX_CACHE_TTL = 3600   # 1 hour — FX rates change slowly


def get_fx_rate_cache(pairs: List[str]) -> Dict[str, float]:
    """
    Read FX rates from price_cache using special 'FX_<from>_<to>' key format.
    pairs: list of strings like 'AED_USD'
    Returns: {'AED_USD': 0.272, ...}
    """
    if not pairs:
        return {}
    keys = [f"FX_{p}" for p in pairs]
    try:
        conn = _get_connection()
        placeholders = ",".join("?" * len(keys))
        rows = conn.execute(
            f"SELECT ticker, price, fetched_at FROM price_cache WHERE ticker IN ({placeholders})",
            keys,
        ).fetchall()
        conn.close()
        cutoff = time.time() - FX_CACHE_TTL
        result = {}
        for r in rows:
            if r["price"] is not None and (r["fetched_at"] or 0) > cutoff:
                pair_key = r["ticker"][3:]  # Strip "FX_" prefix
                result[pair_key] = r["price"]
        return result
    except Exception:
        return {}


def save_fx_rate_cache(rates: Dict[str, float]) -> None:
    """Save FX rates to price_cache with 'FX_<from>_<to>' key format."""
    if not rates:
        return
    now = time.time()
    rows = [(f"FX_{pair}", rate, None, None, "fx", now) for pair, rate in rates.items() if rate]
    if not rows:
        return
    try:
        conn = _get_connection()
        conn.executemany(
            """INSERT OR REPLACE INTO price_cache
               (ticker, price, change_val, change_pct, source, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─────────────────────────────────────────
# TICKER RESOLUTION CACHE  (24-hour SQLite cache eliminates yfinance ping on every session)
# ─────────────────────────────────────────

TICKER_CACHE_TTL = 86400  # 24 hours


def get_ticker_resolution_cache(tickers: List[str]) -> Dict[str, str]:
    """
    Read resolved ticker names from SQLite for the given list.
    Returns {original_ticker: resolved_ticker} for those found and still fresh.
    """
    if not tickers:
        return {}
    try:
        conn = _get_connection()
        placeholders = ",".join("?" * len(tickers))
        rows = conn.execute(
            f"SELECT ticker, resolved, fetched_at FROM ticker_cache WHERE ticker IN ({placeholders})",
            tickers,
        ).fetchall()
        conn.close()
        cutoff = time.time() - TICKER_CACHE_TTL
        return {r["ticker"]: r["resolved"] for r in rows if (r["fetched_at"] or 0) > cutoff}
    except Exception:
        return {}


def save_ticker_resolution_cache(resolutions: Dict[str, str]) -> None:
    """Save {original_ticker: resolved_ticker} pairs to SQLite ticker_cache."""
    if not resolutions:
        return
    try:
        conn = _get_connection()
        now = time.time()
        conn.executemany(
            "INSERT OR REPLACE INTO ticker_cache (ticker, resolved, fetched_at) VALUES (?, ?, ?)",
            [(ticker, resolved, now) for ticker, resolved in resolutions.items()],
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─────────────────────────────────────────
# TRANSACTIONS  (Phase 2 — buy/sell trade log)
# ─────────────────────────────────────────

def save_transaction(ticker: str, txn_type: str, quantity: float, price: float,
                     currency: str = "USD", fees: float = 0, date: str = "",
                     broker_source: str = None, notes: str = None, name: str = None):
    """Insert a single BUY or SELL transaction — scoped to current user (A1)."""
    uid = _current_user_id()
    conn = _get_connection()
    try:
        conn.execute(
            """INSERT INTO transactions (ticker, name, type, quantity, price, currency, fees, date, broker_source, notes, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticker.strip(), name, txn_type.upper(), abs(quantity), abs(price),
             currency.strip(), abs(fees), date, broker_source, notes, uid),
        )
        conn.commit()
    finally:
        conn.close()
    try:
        st.session_state.pop(_REALIZED_PNL_CACHE_KEY, None)
    except Exception:
        pass


def get_transactions(ticker: str = None, txn_type: str = None,
                     date_from: str = None, date_to: str = None) -> pd.DataFrame:
    """Retrieve transactions with optional filters — scoped to current user (A1)."""
    uid = _current_user_id()
    conn = _get_connection()
    try:
        query = "SELECT * FROM transactions WHERE user_id = ?"
        params = [uid]
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)
        if txn_type:
            query += " AND type = ?"
            params.append(txn_type.upper())
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
        query += " ORDER BY date DESC, created_at DESC"
        df = _read_sql(query, conn, params=params)
    finally:
        conn.close()
    return df


def delete_transaction(txn_id: int):
    """Delete a transaction by ID — scoped by current user (A1)."""
    uid = _current_user_id()
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (txn_id, uid))
        conn.commit()
    finally:
        conn.close()
    try:
        st.session_state.pop(_REALIZED_PNL_CACHE_KEY, None)
    except Exception:
        pass


def get_realized_pnl_summary() -> pd.DataFrame:
    """
    Calculate realized P&L per ticker using FIFO — scoped to current user (A1).
    """
    uid = _current_user_id()
    conn = _get_connection()
    try:
        df = _read_sql(
            "SELECT ticker, type, quantity, price, fees, date FROM transactions "
            "WHERE user_id = ? ORDER BY date ASC, id ASC",
            conn, params=(uid,),
        )
    finally:
        conn.close()

    if df.empty:
        return pd.DataFrame(columns=["ticker", "total_bought_qty", "total_sold_qty",
                                      "total_buy_cost", "total_sell_revenue",
                                      "realized_pnl", "total_fees"])

    results = []
    for ticker in df["ticker"].unique():
        t_df = df[df["ticker"] == ticker]
        buys = t_df[t_df["type"] == "BUY"]
        sells = t_df[t_df["type"] == "SELL"]

        total_bought_qty = buys["quantity"].sum()
        total_sold_qty = sells["quantity"].sum()
        total_buy_cost = (buys["quantity"] * buys["price"]).sum()
        total_sell_revenue = (sells["quantity"] * sells["price"]).sum()
        total_fees = t_df["fees"].sum()

        # FIFO realized P&L calculation
        buy_queue = list(zip(buys["quantity"].tolist(), buys["price"].tolist()))
        realized = 0.0
        for _, sell_row in sells.iterrows():
            sell_qty = sell_row["quantity"]
            sell_price = sell_row["price"]
            while sell_qty > 0 and buy_queue:
                buy_qty, buy_price = buy_queue[0]
                matched = min(sell_qty, buy_qty)
                realized += matched * (sell_price - buy_price)
                sell_qty -= matched
                buy_qty -= matched
                if buy_qty <= 0:
                    buy_queue.pop(0)
                else:
                    buy_queue[0] = (buy_qty, buy_price)

        realized -= total_fees  # Subtract all fees from realized P&L

        avg_buy = total_buy_cost / total_bought_qty if total_bought_qty > 0 else 0
        avg_sell = total_sell_revenue / total_sold_qty if total_sold_qty > 0 else 0

        results.append({
            "ticker": ticker,
            "total_bought_qty": total_bought_qty,
            "total_sold_qty": total_sold_qty,
            "total_buy_cost": total_buy_cost,
            "total_sell_revenue": total_sell_revenue,
            "realized_pnl": realized,
            "total_fees": total_fees,
            "avg_buy_price": avg_buy,
            "avg_sell_price": avg_sell,
        })

    return pd.DataFrame(results)


def get_total_realized_pnl() -> float:
    """Return total realized P&L across all tickers. Session-cached."""
    try:
        cached = st.session_state.get(_REALIZED_PNL_CACHE_KEY)
        if cached is not None:
            return cached
    except Exception:
        pass

    summary = get_realized_pnl_summary()
    result = 0.0 if summary.empty else float(summary["realized_pnl"].sum())

    try:
        st.session_state[_REALIZED_PNL_CACHE_KEY] = result
    except Exception:
        pass
    return result


# ─────────────────────────────────────────
# WATCHLIST  (Phase 2 — stocks to track)
# ─────────────────────────────────────────

def add_to_watchlist(ticker: str, name: str = None, currency: str = "USD",
                     target_price: float = None, notes: str = None):
    """Add a stock to the user's watchlist (A1)."""
    uid = _current_user_id()
    conn = _get_connection()
    try:
        conn.execute(
            """INSERT INTO watchlist (ticker, name, currency, target_price, notes, user_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ticker.strip().upper(), name, currency.strip(), target_price, notes, uid),
        )
        conn.commit()
    finally:
        conn.close()


def get_watchlist() -> pd.DataFrame:
    """Retrieve current user's watchlist (A1)."""
    uid = _current_user_id()
    conn = _get_connection()
    try:
        df = _read_sql(
            "SELECT * FROM watchlist WHERE user_id = ? ORDER BY ticker ASC",
            conn, params=(uid,),
        )
    finally:
        conn.close()
    return df


def remove_from_watchlist(item_id: int):
    """Remove a watchlist item — scoped by user (A1)."""
    uid = _current_user_id()
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM watchlist WHERE id = ? AND user_id = ?", (item_id, uid))
        conn.commit()
    finally:
        conn.close()


def update_watchlist_target(item_id: int, target_price: float):
    """Update target price — scoped by user (A1)."""
    uid = _current_user_id()
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE watchlist SET target_price = ? WHERE id = ? AND user_id = ?",
            (target_price, item_id, uid),
        )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────
# NAV SNAPSHOTS  (Phase 2 — daily portfolio value)
# ─────────────────────────────────────────

def save_nav_snapshot(date: str, total_value: float, total_cost: float = None,
                      unrealized_pnl: float = None, realized_pnl: float = None,
                      holdings_count: int = None, base_currency: str = "USD"):
    """Save a daily portfolio snapshot — scoped to current user (A1).

    Uses DELETE+INSERT scoped by (date, base_currency, user_id) so two users
    can both have a snapshot for the same day in the same currency.
    """
    uid = _current_user_id()
    conn = _get_connection()
    try:
        conn.execute(
            "DELETE FROM nav_snapshots WHERE date = ? AND base_currency = ? AND user_id = ?",
            (date, base_currency, uid),
        )
        conn.execute(
            """INSERT INTO nav_snapshots
               (date, total_value, total_cost, unrealized_pnl, realized_pnl,
                holdings_count, base_currency, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, total_value, total_cost, unrealized_pnl, realized_pnl,
             holdings_count, base_currency, uid),
        )
        conn.commit()
    except Exception:
        # Best-effort: legacy UNIQUE(date, base_currency) constraint may still
        # exist from pre-multitenancy schema. App continues without snapshot.
        pass
    finally:
        conn.close()
    try:
        for key in list(st.session_state.keys()):
            if key.startswith(_NAV_HISTORY_CACHE_KEY) or key.startswith("_nav_exists_today_"):
                del st.session_state[key]
    except Exception:
        pass


def get_nav_history(days: int = 365, base_currency: str = None) -> pd.DataFrame:
    """Retrieve NAV history for the current user (A1). Session-cached."""
    uid = _current_user_id()
    cache_key = f"{_NAV_HISTORY_CACHE_KEY}_{uid}_{base_currency or 'all'}"
    try:
        cached = st.session_state.get(cache_key)
        if cached is not None:
            return cached.copy()
    except Exception:
        pass

    conn = _get_connection()
    try:
        query = "SELECT * FROM nav_snapshots WHERE user_id = ?"
        params = [uid]
        if base_currency:
            query += " AND base_currency = ?"
            params.append(base_currency)
        query += " ORDER BY date ASC"
        df = _read_sql(query, conn, params=params)
    finally:
        conn.close()

    try:
        st.session_state[cache_key] = df.copy()
    except Exception:
        pass
    return df


def get_nav_snapshot_exists_today(base_currency: str = "USD") -> bool:
    """Check if a NAV snapshot already exists for today FOR THE CURRENT USER (A1)."""
    uid = _current_user_id()
    cache_key = f"_nav_exists_today_{uid}_{base_currency}"
    try:
        cached = st.session_state.get(cache_key)
        if cached is not None:
            return cached
    except Exception:
        pass

    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM nav_snapshots WHERE date = ? AND base_currency = ? AND user_id = ?",
            (today, base_currency, uid),
        ).fetchone()
    finally:
        conn.close()
    result = (row[0] > 0) if row else False

    try:
        st.session_state[cache_key] = result
    except Exception:
        pass
    return result


# ─────────────────────────────────────────
# PROSPER AI ANALYSIS  (Phase 4 — CIO-grade equity analysis)
# ─────────────────────────────────────────

def save_prosper_analysis(ticker: str, data: dict):
    """Save or update a Prosper AI analysis result for a ticker."""
    conn = _get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO prosper_analysis
           (ticker, analysis_date, model_used, rating, score, archetype,
            archetype_name, fair_value_base, fair_value_bear, fair_value_bull,
            upside_pct, conviction, thesis, env_net, score_breakdown,
            key_risks, key_catalysts, full_response, cost_estimate, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ticker.strip().upper(),
            data.get("analysis_date", datetime.now().strftime("%Y-%m-%d")),
            data.get("model_used", "sonnet"),
            data.get("rating"),
            data.get("score"),
            data.get("archetype"),
            data.get("archetype_name"),
            data.get("fair_value_base"),
            data.get("fair_value_bear"),
            data.get("fair_value_bull"),
            data.get("upside_pct"),
            data.get("conviction"),
            data.get("thesis"),
            data.get("env_net"),
            json.dumps(data.get("score_breakdown")) if data.get("score_breakdown") else None,
            json.dumps(data.get("key_risks")) if data.get("key_risks") else None,
            json.dumps(data.get("key_catalysts")) if data.get("key_catalysts") else None,
            json.dumps(data.get("full_response")) if data.get("full_response") else None,
            data.get("cost_estimate"),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    try:
        st.session_state.pop(_ANALYSES_CACHE_KEY, None)
    except Exception:
        pass


def get_prosper_analysis(ticker: str) -> Optional[Dict]:
    """Retrieve the latest Prosper analysis for a ticker. Returns dict or None."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM prosper_analysis WHERE ticker = ?",
        (ticker.strip().upper(),),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    result = dict(row)
    # Parse JSON fields
    for field in ("score_breakdown", "key_risks", "key_catalysts", "full_response"):
        if result.get(field):
            try:
                result[field] = json.loads(result[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return result


def get_all_prosper_analyses() -> pd.DataFrame:
    """Retrieve all Prosper analyses as a DataFrame. Session-cached."""
    try:
        cached = st.session_state.get(_ANALYSES_CACHE_KEY)
        if cached is not None:
            return cached.copy()
    except Exception:
        pass

    conn = _get_connection()
    df = _read_sql(
        "SELECT ticker, analysis_date, rating, score, archetype_name, "
        "fair_value_base, upside_pct, conviction, thesis, env_net, model_used "
        "FROM prosper_analysis ORDER BY score DESC",
        conn,
    )
    conn.close()

    try:
        st.session_state[_ANALYSES_CACHE_KEY] = df.copy()
    except Exception:
        pass
    return df


def delete_prosper_analysis(ticker: str):
    """Remove analysis for a ticker."""
    conn = _get_connection()
    conn.execute("DELETE FROM prosper_analysis WHERE ticker = ?", (ticker.strip().upper(),))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# CASH POSITIONS  (Phase 5 — cash management)
# ─────────────────────────────────────────

def _invalidate_cash_cache():
    """Clear cached cash positions so next read hits the DB."""
    try:
        st.session_state.pop(_CASH_POSITIONS_CACHE_KEY, None)
    except Exception:
        pass


def save_cash_position(account_name: str, currency: str = "USD", amount: float = 0,
                       is_margin: bool = False, margin_rate: float = None,
                       broker_source: str = None, notes: str = None):
    """Insert a cash position scoped to current user (A1)."""
    uid = _current_user_id()
    conn = _get_connection()
    try:
        conn.execute(
            """INSERT INTO cash_positions
               (account_name, currency, amount, is_margin, margin_rate, broker_source, notes, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_name.strip(), currency.strip(), amount,
             1 if is_margin else 0, margin_rate, broker_source, notes, uid),
        )
        conn.commit()
    finally:
        conn.close()
    _invalidate_cash_cache()


def get_all_cash_positions() -> pd.DataFrame:
    """Retrieve cash positions for current user (A1)."""
    uid = _current_user_id()
    cache_key = f"{_CASH_POSITIONS_CACHE_KEY}_{uid}"
    try:
        cached = st.session_state.get(cache_key)
        if cached is not None:
            return cached.copy()
    except Exception:
        pass

    conn = _get_connection()
    try:
        df = _read_sql(
            "SELECT * FROM cash_positions WHERE user_id = ? ORDER BY account_name ASC",
            conn, params=(uid,),
        )
    finally:
        conn.close()

    try:
        st.session_state[cache_key] = df.copy()
    except Exception:
        pass
    return df


def update_cash_position(position_id: int, **kwargs):
    """Update fields of a cash position — scoped by user (A1)."""
    allowed = {"account_name", "currency", "amount", "is_margin", "margin_rate",
               "broker_source", "notes"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    uid = _current_user_id()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [position_id, uid]
    conn = _get_connection()
    try:
        conn.execute(
            f"UPDATE cash_positions SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
            f"WHERE id = ? AND user_id = ?",
            values,
        )
        conn.commit()
    finally:
        conn.close()
    _invalidate_cash_cache()


def delete_cash_position(position_id: int):
    """Delete a cash position — scoped by user (A1)."""
    uid = _current_user_id()
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM cash_positions WHERE id = ? AND user_id = ?", (position_id, uid))
        conn.commit()
    finally:
        conn.close()
    _invalidate_cash_cache()


def get_total_cash(currency: str = None) -> float:
    """Return total cash across all accounts. Optionally filter by currency."""
    positions = get_all_cash_positions()
    if positions.empty:
        return 0.0
    if currency:
        positions = positions[positions["currency"] == currency]
    return float(positions["amount"].sum()) if not positions.empty else 0.0


# ─────────────────────────────────────────
# FORTRESS STATE  (key-value store for regime, circuit breakers, etc.)
# ─────────────────────────────────────────

def save_fortress_state(key: str, value: str):
    """Save a FORTRESS state value (JSON-encoded)."""
    conn = _get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO fortress_state (key, value, updated_at)
           VALUES (?, ?, ?)""",
        (key, value, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_fortress_state(key: str) -> Optional[str]:
    """Retrieve a FORTRESS state value by key. Returns None if not found."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT value FROM fortress_state WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    return row["value"] if row else None


def get_all_fortress_state() -> Dict[str, str]:
    """Retrieve all FORTRESS state key-value pairs."""
    conn = _get_connection()
    rows = conn.execute("SELECT key, value FROM fortress_state").fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}


# ─────────────────────────────────────────
# USERS  (database-backed auth — replaces ephemeral auth_config.yaml)
# ─────────────────────────────────────────

def _migrate_yaml_users_to_db():
    """One-time, idempotent migration: copy users from auth_config.yaml into the users table.

    Skips any username that already exists in the DB so it is safe to call on every startup.
    """
    try:
        import yaml
        yaml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "auth_config.yaml")
        if not os.path.exists(yaml_path):
            return  # No YAML file — nothing to migrate

        with open(yaml_path, "r") as f:
            config = yaml.safe_load(f)

        usernames_block = (config or {}).get("credentials", {}).get("usernames", {})
        if not usernames_block:
            return

        conn = _get_connection()
        for username, info in usernames_block.items():
            # Check if user already exists (idempotent)
            try:
                existing = conn.execute(
                    "SELECT username FROM users WHERE username = ?", (username,)
                ).fetchone()
                if existing:
                    continue  # Already migrated
            except Exception:
                pass

            try:
                conn.execute(
                    """INSERT INTO users (username, email, first_name, last_name, password_hash, role)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        username,
                        info.get("email", ""),
                        info.get("first_name", ""),
                        info.get("last_name", ""),
                        info.get("password", ""),   # already a bcrypt hash in the YAML
                        info.get("role", "user"),
                    ),
                )
            except Exception:
                pass  # Duplicate email or other constraint — skip gracefully
        conn.commit()
        conn.close()
    except ImportError:
        pass  # PyYAML not installed — skip migration
    except Exception:
        pass  # Best-effort migration


def get_user_by_username(username: str) -> Optional[Dict]:
    """Return a user dict by username, or None if not found."""
    try:
        conn = _get_connection()
        row = conn.execute(
            "SELECT username, email, first_name, last_name, password_hash, role, created_at "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        if isinstance(row, dict):
            return dict(row)
        # sqlite3.Row or tuple
        keys = ["username", "email", "first_name", "last_name", "password_hash", "role", "created_at"]
        if hasattr(row, "keys"):
            return {k: row[k] for k in keys}
        return dict(zip(keys, row))
    except Exception:
        return None


def get_user_by_email(email: str) -> Optional[Dict]:
    """Return a user dict by email, or None if not found."""
    try:
        conn = _get_connection()
        row = conn.execute(
            "SELECT username, email, first_name, last_name, password_hash, role, created_at "
            "FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        if isinstance(row, dict):
            return dict(row)
        keys = ["username", "email", "first_name", "last_name", "password_hash", "role", "created_at"]
        if hasattr(row, "keys"):
            return {k: row[k] for k in keys}
        return dict(zip(keys, row))
    except Exception:
        return None


def create_user(username: str, email: str, first_name: str, last_name: str,
                password_hash: str, role: str = "user") -> str:
    """Create a new user in the database. Returns the username."""
    conn = _get_connection()
    conn.execute(
        """INSERT INTO users (username, email, first_name, last_name, password_hash, role)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (username.strip(), email.strip(), first_name.strip(), last_name.strip(),
         password_hash, role),
    )
    conn.commit()
    conn.close()
    return username.strip()


def get_all_users() -> List[Dict]:
    """Return a list of all user dicts (for admin views)."""
    try:
        conn = _get_connection()
        rows = conn.execute(
            "SELECT username, email, first_name, last_name, password_hash, role, created_at "
            "FROM users ORDER BY created_at ASC"
        ).fetchall()
        conn.close()
        keys = ["username", "email", "first_name", "last_name", "password_hash", "role", "created_at"]
        result = []
        for row in rows:
            if isinstance(row, dict):
                result.append(dict(row))
            elif hasattr(row, "keys"):
                result.append({k: row[k] for k in keys})
            else:
                result.append(dict(zip(keys, row)))
        return result
    except Exception:
        return []


def update_user_password(username: str, new_password_hash: str):
    """Update the password hash for an existing user."""
    conn = _get_connection()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (new_password_hash, username),
    )
    conn.commit()
    conn.close()


def delete_user(username: str):
    """Delete a user by username."""
    conn = _get_connection()
    conn.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# A4: rotate any password_hash that equals bcrypt(email).
# Closes the legacy "email-as-password" fallback for Google OAuth users.
# Idempotent: runs at every cold start; once rotated, hashes never match again.
# ─────────────────────────────────────────
def rotate_oauth_user_passwords() -> int:
    """Replace any password_hash == bcrypt(email) with a random hash.

    Returns: number of users rotated (0 once stable).
    """
    try:
        import bcrypt
        import secrets as _s
    except ImportError:
        return 0
    conn = _get_connection()
    rotated = 0
    try:
        rows = conn.execute("SELECT username, email, password_hash FROM users").fetchall()
        for r in rows:
            try:
                if isinstance(r, (tuple, list)):
                    username, email, hash_ = r[0], r[1], r[2]
                elif hasattr(r, "keys"):
                    username = r["username"]
                    email = r["email"]
                    hash_ = r["password_hash"]
                else:
                    continue
                if not (email and hash_):
                    continue
                if bcrypt.checkpw(email.encode("utf-8"), hash_.encode("utf-8")):
                    new_hash = bcrypt.hashpw(
                        _s.token_urlsafe(32).encode("utf-8"), bcrypt.gensalt()
                    ).decode("utf-8")
                    conn.execute(
                        "UPDATE users SET password_hash = ? WHERE username = ?",
                        (new_hash, username),
                    )
                    rotated += 1
            except Exception:
                continue
        if rotated:
            conn.commit()
    except Exception:
        pass
    finally:
        conn.close()
    return rotated


# ─────────────────────────────────────────
# A5: distinguish "DB unreachable" from "DB empty" before promoting to admin.
# ─────────────────────────────────────────
def users_query_succeeded() -> bool:
    """Run a tiny SELECT against the users table — return True only if it didn't raise.

    Used by core.auth before granting first-user admin role: a DB outage
    must NOT silently make the next signup an admin.
    """
    try:
        conn = _get_connection()
        try:
            conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            return True
        finally:
            conn.close()
    except Exception:
        return False
