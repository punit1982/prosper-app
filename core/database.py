import sqlite3
import os
import json
import time
import pandas as pd
from typing import Optional, List, Dict
from datetime import datetime, timedelta

from core.db_connector import get_connection as _get_cloud_connection, sync_to_cloud, DB_PATH


def _get_connection():
    """Get a database connection (Turso cloud or local SQLite)."""
    return _get_cloud_connection()


def init_db():
    """Create the database and all tables if they don't exist."""
    conn = _get_connection()

    # Holdings table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            name TEXT,
            quantity REAL NOT NULL,
            avg_cost REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            broker_source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Parse cache table — avoids re-calling Claude for the same screenshot
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parse_cache (
            image_hash TEXT PRIMARY KEY,
            result_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Price cache — persists live prices across server restarts (TTL: 5 min)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_cache (
            ticker      TEXT PRIMARY KEY,
            price       REAL,
            change_val  REAL,
            change_pct  REAL,
            source      TEXT DEFAULT 'unknown',
            fetched_at  REAL DEFAULT 0
        )
    """)

    # News cache — persists aggregated news across sessions (TTL: 1 hour)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_cache (
            cache_key   TEXT PRIMARY KEY,
            news_json   TEXT NOT NULL,
            fetched_at  REAL DEFAULT 0
        )
    """)

    # Ticker resolution cache — persists yfinance ticker probing (TTL: 24 hours)
    # Eliminates 79+ HTTP pings on every new browser session; single SQLite read instead
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticker_cache (
            ticker      TEXT PRIMARY KEY,
            resolved    TEXT NOT NULL,
            fetched_at  REAL DEFAULT 0
        )
    """)

    # ── Phase 2 tables ──────────────────────────────────────────────────────────

    # Transactions table — buy/sell trade history for realized P&L
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            name TEXT,
            type TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            fees REAL DEFAULT 0,
            date TEXT NOT NULL,
            broker_source TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Watchlist table — stocks being tracked (not in portfolio)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            name TEXT,
            currency TEXT DEFAULT 'USD',
            target_price REAL,
            notes TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # NAV snapshots — daily portfolio value for historical performance
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nav_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            total_value REAL NOT NULL,
            total_cost REAL,
            unrealized_pnl REAL,
            realized_pnl REAL,
            holdings_count INTEGER,
            base_currency TEXT DEFAULT 'USD',
            snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, base_currency)
        )
    """)

    # ── Phase 4 tables ──────────────────────────────────────────────────────────

    # Prosper AI Analysis — stores CIO-grade analysis results per ticker
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prosper_analysis (
            ticker          TEXT PRIMARY KEY,
            analysis_date   TEXT NOT NULL,
            model_used      TEXT DEFAULT 'sonnet',
            rating          TEXT,
            score           REAL,
            archetype       TEXT,
            archetype_name  TEXT,
            fair_value_base REAL,
            fair_value_bear REAL,
            fair_value_bull REAL,
            upside_pct      REAL,
            conviction      TEXT,
            thesis          TEXT,
            env_net         TEXT,
            score_breakdown TEXT,
            key_risks       TEXT,
            key_catalysts   TEXT,
            full_response   TEXT,
            cost_estimate   REAL,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# ─────────────────────────────────────────
# HOLDINGS
# ─────────────────────────────────────────

def save_holdings(df: pd.DataFrame, broker_source: str = None):
    """Insert holdings from a DataFrame into the database."""
    conn = _get_connection()
    for _, row in df.iterrows():
        conn.execute(
            """INSERT INTO holdings (ticker, name, quantity, avg_cost, currency, broker_source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(row.get("ticker", "") or "").strip(),
                str(row.get("name", "") or "").strip(),
                float(row.get("quantity", 0) or 0),
                float(row.get("avg_cost", 0) or 0),
                str(row.get("currency", "USD") or "USD").strip(),
                broker_source,
            ),
        )
    conn.commit()
    conn.close()
    sync_to_cloud()


def get_all_holdings() -> pd.DataFrame:
    """Retrieve all holdings as a DataFrame."""
    conn = _get_connection()
    df = pd.read_sql_query("SELECT * FROM holdings ORDER BY ticker ASC", conn)
    conn.close()
    return df


def update_holding(holding_id: int, **kwargs):
    """Update specific fields of a holding by ID. Accepts quantity, avg_cost, currency, country."""
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
    sync_to_cloud()


def delete_holding(holding_id: int):
    """Remove a single holding by its ID."""
    conn = _get_connection()
    conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
    conn.commit()
    conn.close()
    sync_to_cloud()


def clear_all_holdings():
    """Delete all holdings from the database."""
    conn = _get_connection()
    conn.execute("DELETE FROM holdings")
    conn.commit()
    conn.close()
    sync_to_cloud()


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

PRICE_CACHE_TTL = 300   # 5 minutes — re-fetch if older than this


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
    """Return age in seconds of the oldest cached price, or None if empty."""
    try:
        conn = _get_connection()
        row = conn.execute("SELECT MIN(fetched_at) FROM price_cache WHERE price IS NOT NULL").fetchone()
        conn.close()
        if row and row[0]:
            return time.time() - row[0]
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
    sync_to_cloud()


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
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def delete_transaction(txn_id: int):
    """Remove a single transaction by its ID."""
    conn = _get_connection()
    conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
    conn.commit()
    conn.close()
    sync_to_cloud()


def get_realized_pnl_summary() -> pd.DataFrame:
    """
    Calculate realized P&L per ticker using FIFO (First In, First Out).
    Returns DataFrame with: ticker, total_bought_qty, total_sold_qty,
    total_buy_cost, total_sell_revenue, realized_pnl, avg_buy_price, avg_sell_price
    """
    conn = _get_connection()
    # Get all transactions sorted by date (FIFO order)
    df = pd.read_sql_query(
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
    """Return total realized P&L across all tickers."""
    summary = get_realized_pnl_summary()
    if summary.empty:
        return 0.0
    return float(summary["realized_pnl"].sum())


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
    df = pd.read_sql_query("SELECT * FROM watchlist ORDER BY ticker ASC", conn)
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
    sync_to_cloud()


def get_nav_history(days: int = 365, base_currency: str = None) -> pd.DataFrame:
    """Retrieve NAV history for the last N days."""
    conn = _get_connection()
    query = "SELECT * FROM nav_snapshots WHERE 1=1"
    params = []
    if base_currency:
        query += " AND base_currency = ?"
        params.append(base_currency)
    query += " ORDER BY date ASC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_nav_snapshot_exists_today(base_currency: str = "USD") -> bool:
    """Check if a NAV snapshot already exists for today."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM nav_snapshots WHERE date = ? AND base_currency = ?",
        (today, base_currency),
    ).fetchone()
    conn.close()
    return row[0] > 0 if row else False


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
    sync_to_cloud()


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
    """Retrieve all Prosper analyses as a DataFrame."""
    conn = _get_connection()
    df = pd.read_sql_query(
        "SELECT ticker, analysis_date, rating, score, archetype_name, "
        "fair_value_base, upside_pct, conviction, thesis, env_net, model_used "
        "FROM prosper_analysis ORDER BY score DESC",
        conn,
    )
    conn.close()
    return df


def delete_prosper_analysis(ticker: str):
    """Remove analysis for a ticker."""
    conn = _get_connection()
    conn.execute("DELETE FROM prosper_analysis WHERE ticker = ?", (ticker.strip().upper(),))
    conn.commit()
    conn.close()
