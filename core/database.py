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


def _invalidate_holdings_cache():
    """Clear cached holdings so next read hits the DB. Call after any write."""
    try:
        for key in list(st.session_state.keys()):
            if key.startswith(_HOLDINGS_CACHE_KEY) or key.startswith("enriched_") or key in (
                "extended_df", "last_refresh_time", _REALIZED_PNL_CACHE_KEY, _ANALYSES_CACHE_KEY,
            ):
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
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS briefing_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            briefing_date TEXT NOT NULL,
            currency TEXT DEFAULT 'USD',
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    ]

    conn = _get_connection()

    # Turso: batch all statements in ONE HTTP call
    if hasattr(conn, 'execute_batch'):
        conn.execute_batch(_TABLE_STATEMENTS)
    else:
        # SQLite: execute one by one (fast locally)
        for sql in _TABLE_STATEMENTS:
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
        conn2.close()
    except Exception:
        pass  # Migration is best-effort — app works without it
    st.session_state["_db_initialized"] = True


# ─────────────────────────────────────────
# PORTFOLIOS
# ─────────────────────────────────────────

def get_all_portfolios() -> pd.DataFrame:
    """Return all portfolios."""
    conn = _get_connection()
    df = _read_sql("SELECT * FROM portfolios ORDER BY id ASC", conn)
    conn.close()
    return df


def create_portfolio(name: str, description: str = "") -> int:
    """Create a new portfolio. Returns its ID."""
    conn = _get_connection()
    conn.execute("INSERT INTO portfolios (name, description) VALUES (?, ?)", (name.strip(), description.strip()))
    conn.commit()
    row = conn.execute("SELECT id FROM portfolios WHERE name = ?", (name.strip(),)).fetchone()
    conn.close()
    pid = row[0] if isinstance(row, (tuple, list)) else row["id"]
    return pid


def rename_portfolio(portfolio_id: int, new_name: str):
    """Rename a portfolio."""
    conn = _get_connection()
    conn.execute("UPDATE portfolios SET name = ? WHERE id = ?", (new_name.strip(), portfolio_id))
    conn.commit()
    conn.close()


def delete_portfolio(portfolio_id: int):
    """Delete a portfolio and all its holdings."""
    if portfolio_id == 1:
        return  # Protect default
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM holdings WHERE portfolio_id = ?", (portfolio_id,))
    except Exception:
        pass  # portfolio_id column may not exist
    try:
        conn.execute("DELETE FROM portfolios WHERE id = ?", (portfolio_id,))
    except Exception:
        pass
    conn.commit()
    conn.close()
    _invalidate_holdings_cache()


def get_active_portfolio_id() -> int:
    """Return the currently selected portfolio ID from session state."""
    return st.session_state.get("active_portfolio_id", 1)


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
    """Insert holdings from a DataFrame into the database."""
    pid = portfolio_id or get_active_portfolio_id()
    conn = _get_connection()
    try:
        for _, row in df.iterrows():
            _ticker = str(row.get("ticker", "") or "").strip()
            _name = str(row.get("name", "") or "").strip()
            _qty = float(row.get("quantity", 0) or 0)
            _cost = float(row.get("avg_cost", 0) or 0)
            _ccy = str(row.get("currency", "USD") or "USD").strip()
            _src = broker_source or ""
            try:
                conn.execute(
                    """INSERT INTO holdings (ticker, name, quantity, avg_cost, currency, broker_source, portfolio_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (_ticker, _name, _qty, _cost, _ccy, _src, pid),
                )
            except Exception:
                # portfolio_id column may not exist — insert without it
                conn.execute(
                    """INSERT INTO holdings (ticker, name, quantity, avg_cost, currency, broker_source)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (_ticker, _name, _qty, _cost, _ccy, _src),
                )
        conn.commit()
        conn.close()
        _invalidate_holdings_cache()
    except Exception as e:
        error_msg = str(e)
        st.error(f"Database save failed: {error_msg}")
        raise


def get_all_holdings(portfolio_id: int = None) -> pd.DataFrame:
    """Retrieve holdings for the active portfolio as a DataFrame.

    PERFORMANCE: Returns session-cached copy if available.
    Cache is invalidated automatically by save/update/delete functions.
    """
    pid = portfolio_id or get_active_portfolio_id()
    cache_key = f"{_HOLDINGS_CACHE_KEY}_{pid}"
    try:
        cached = st.session_state.get(cache_key)
        if cached is not None:
            return cached.copy()
    except Exception:
        pass

    conn = _get_connection()
    try:
        df = _read_sql("SELECT * FROM holdings WHERE portfolio_id = ? ORDER BY ticker ASC", conn, params=(pid,))
    except Exception:
        # portfolio_id column may not exist yet — fall back to unfiltered query
        df = pd.DataFrame()
    conn.close()

    # Fallback: if portfolio_id column doesn't exist or returned empty
    if df.empty:
        conn2 = _get_connection()
        df = _read_sql("SELECT * FROM holdings ORDER BY ticker ASC", conn2)
        conn2.close()

    try:
        st.session_state[cache_key] = df.copy()
    except Exception:
        pass
    return df


def update_holding(holding_id: int, **kwargs):
    """Update specific fields of a holding by ID."""
    allowed = {"quantity", "avg_cost", "currency", "broker_source"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [holding_id]
    conn = _get_connection()
    conn.execute(f"UPDATE holdings SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
    conn.commit()
    conn.close()
    _invalidate_holdings_cache()


def delete_holding(holding_id: int):
    """Remove a single holding by its ID."""
    conn = _get_connection()
    conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
    conn.commit()
    conn.close()
    _invalidate_holdings_cache()


def clear_all_holdings(portfolio_id: int = None):
    """Delete all holdings for the active portfolio."""
    pid = portfolio_id or get_active_portfolio_id()
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM holdings WHERE portfolio_id = ?", (pid,))
    except Exception:
        # portfolio_id column may not exist — delete all
        conn.execute("DELETE FROM holdings")
    conn.commit()
    conn.close()
    _invalidate_holdings_cache()


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
    """Insert a single BUY or SELL transaction."""
    conn = _get_connection()
    conn.execute(
        """INSERT INTO transactions (ticker, name, type, quantity, price, currency, fees, date, broker_source, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticker.strip(), name, txn_type.upper(), abs(quantity), abs(price),
         currency.strip(), abs(fees), date, broker_source, notes),
    )
    conn.commit()
    conn.close()
    try:
        st.session_state.pop(_REALIZED_PNL_CACHE_KEY, None)
    except Exception:
        pass


def get_transactions(ticker: str = None, txn_type: str = None,
                     date_from: str = None, date_to: str = None) -> pd.DataFrame:
    """Retrieve transactions with optional filters. Returns a DataFrame."""
    conn = _get_connection()
    query = "SELECT * FROM transactions WHERE 1=1"
    params = []
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
    conn.close()
    return df


def delete_transaction(txn_id: int):
    """Remove a single transaction by its ID."""
    conn = _get_connection()
    conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
    conn.commit()
    conn.close()
    try:
        st.session_state.pop(_REALIZED_PNL_CACHE_KEY, None)
    except Exception:
        pass


def get_realized_pnl_summary() -> pd.DataFrame:
    """
    Calculate realized P&L per ticker using FIFO (First In, First Out).
    Returns DataFrame with: ticker, total_bought_qty, total_sold_qty,
    total_buy_cost, total_sell_revenue, realized_pnl, avg_buy_price, avg_sell_price
    """
    conn = _get_connection()
    # Get all transactions sorted by date (FIFO order)
    df = _read_sql(
        "SELECT ticker, type, quantity, price, fees, date FROM transactions ORDER BY date ASC, id ASC",
        conn,
    )
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
    """Add a stock to the watchlist."""
    conn = _get_connection()
    conn.execute(
        """INSERT INTO watchlist (ticker, name, currency, target_price, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (ticker.strip().upper(), name, currency.strip(), target_price, notes),
    )
    conn.commit()
    conn.close()


def get_watchlist() -> pd.DataFrame:
    """Retrieve all watchlist items."""
    conn = _get_connection()
    df = _read_sql("SELECT * FROM watchlist ORDER BY ticker ASC", conn)
    conn.close()
    return df


def remove_from_watchlist(item_id: int):
    """Remove a single item from the watchlist."""
    conn = _get_connection()
    conn.execute("DELETE FROM watchlist WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def update_watchlist_target(item_id: int, target_price: float):
    """Update the target price for a watchlist item."""
    conn = _get_connection()
    conn.execute("UPDATE watchlist SET target_price = ? WHERE id = ?", (target_price, item_id))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# NAV SNAPSHOTS  (Phase 2 — daily portfolio value)
# ─────────────────────────────────────────

def save_nav_snapshot(date: str, total_value: float, total_cost: float = None,
                      unrealized_pnl: float = None, realized_pnl: float = None,
                      holdings_count: int = None, base_currency: str = "USD"):
    """Save a daily portfolio snapshot. Uses INSERT OR REPLACE (1 per day per currency)."""
    conn = _get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO nav_snapshots
           (date, total_value, total_cost, unrealized_pnl, realized_pnl,
            holdings_count, base_currency)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (date, total_value, total_cost, unrealized_pnl, realized_pnl,
         holdings_count, base_currency),
    )
    conn.commit()
    conn.close()
    # Invalidate NAV history cache
    try:
        for key in list(st.session_state.keys()):
            if key.startswith(_NAV_HISTORY_CACHE_KEY):
                del st.session_state[key]
    except Exception:
        pass


def get_nav_history(days: int = 365, base_currency: str = None) -> pd.DataFrame:
    """Retrieve NAV history for the last N days. Session-cached."""
    cache_key = f"{_NAV_HISTORY_CACHE_KEY}_{base_currency or 'all'}"
    try:
        cached = st.session_state.get(cache_key)
        if cached is not None:
            return cached.copy()
    except Exception:
        pass

    conn = _get_connection()
    query = "SELECT * FROM nav_snapshots WHERE 1=1"
    params = []
    if base_currency:
        query += " AND base_currency = ?"
        params.append(base_currency)
    query += " ORDER BY date ASC"
    df = _read_sql(query, conn, params=params)
    conn.close()

    try:
        st.session_state[cache_key] = df.copy()
    except Exception:
        pass
    return df


def get_nav_snapshot_exists_today(base_currency: str = "USD") -> bool:
    """Check if a NAV snapshot already exists for today. Session-cached."""
    cache_key = f"_nav_exists_today_{base_currency}"
    try:
        cached = st.session_state.get(cache_key)
        if cached is not None:
            return cached
    except Exception:
        pass

    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM nav_snapshots WHERE date = ? AND base_currency = ?",
        (today, base_currency),
    ).fetchone()
    conn.close()
    result = row[0] > 0 if row else False

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
    """Insert a cash position (positive = cash, negative = margin)."""
    conn = _get_connection()
    conn.execute(
        """INSERT INTO cash_positions
           (account_name, currency, amount, is_margin, margin_rate, broker_source, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (account_name.strip(), currency.strip(), amount,
         1 if is_margin else 0, margin_rate, broker_source, notes),
    )
    conn.commit()
    conn.close()
    _invalidate_cash_cache()


def get_all_cash_positions() -> pd.DataFrame:
    """Retrieve all cash positions as a DataFrame. Session-cached."""
    try:
        cached = st.session_state.get(_CASH_POSITIONS_CACHE_KEY)
        if cached is not None:
            return cached.copy()
    except Exception:
        pass

    conn = _get_connection()
    df = _read_sql("SELECT * FROM cash_positions ORDER BY account_name ASC", conn)
    conn.close()

    try:
        st.session_state[_CASH_POSITIONS_CACHE_KEY] = df.copy()
    except Exception:
        pass
    return df


def update_cash_position(position_id: int, **kwargs):
    """Update specific fields of a cash position by ID."""
    allowed = {"account_name", "currency", "amount", "is_margin", "margin_rate",
               "broker_source", "notes"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [position_id]
    conn = _get_connection()
    conn.execute(
        f"UPDATE cash_positions SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        values,
    )
    conn.commit()
    conn.close()
    _invalidate_cash_cache()


def delete_cash_position(position_id: int):
    """Remove a single cash position by its ID."""
    conn = _get_connection()
    conn.execute("DELETE FROM cash_positions WHERE id = ?", (position_id,))
    conn.commit()
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
