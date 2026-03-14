"""
CIO Engine
==========
Fetches live stock prices and health metrics using yfinance (free, no API key).

Speed improvement (v2):
- Parallel fetching via ThreadPoolExecutor — all tickers are fetched simultaneously
  instead of one-at-a-time, cutting typical latency from ~30s to ~5s for 20 stocks.

Why yfinance?
- Free — no API key, no quota limits
- Supports all global exchanges: US, India (.NS/.BO), UAE (.AE), HK (.HK), SG (.SI), etc.
- Returns prices, day change, P/E, Debt/Equity, and more
"""

import pandas as pd
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.settings import SETTINGS
from core.currency_normalizer import detect_currency_from_ticker, get_exchange_rate, normalise_currency


# ─────────────────────────────────────────
# FAILED-TICKER CACHE  (10-min cooldown)
# Avoids re-fetching tickers we know have no price data on any source.
# ─────────────────────────────────────────
import time as _time
_failed_tickers: Dict[str, float] = {}   # {ticker: failed_at_timestamp}
_FAIL_COOLDOWN = 600   # 10 minutes — retry sooner (was 30 min)


def _mark_failed(sym: str):
    _failed_tickers[sym] = _time.time()


def _is_failed(sym: str) -> bool:
    t = _failed_tickers.get(sym, 0)
    return (_time.time() - t) < _FAIL_COOLDOWN


def clear_failed_tickers():
    """Clear the in-memory failed-ticker cooldown so all tickers are retried."""
    _failed_tickers.clear()


# ─────────────────────────────────────────
# LIVE QUOTES  (parallel)
# ─────────────────────────────────────────

def _is_twelve_data_symbol(sym: str) -> bool:
    """Check if a symbol is in Twelve Data exchange format (e.g. 'EMAAR:DFM')."""
    return ":" in sym and any(sym.endswith(f":{ex}") for ex in ("DFM", "XADS"))


def _fetch_one_quote(sym: str) -> tuple:
    """
    Fetch price data for a single ticker.
    Cascade: ADX/Mubasher (ADX stocks) → Twelve Data (UAE/DFM) → yfinance → Finnhub
    """
    import yfinance as yf

    # Source 0a: Mubasher intraday CSV — for ADX stocks (.AE suffix, static chart IDs)
    try:
        from core.adx_client import get_quote as adx_quote, is_adx_ticker
        if is_adx_ticker(sym):
            adx = adx_quote(sym)
            if adx and adx.get("price", 0) > 0:
                return sym, adx
    except Exception:
        pass

    # Source 0b: Twelve Data — for UAE symbols resolved as TICKER:DFM / TICKER:ADX
    if _is_twelve_data_symbol(sym):
        try:
            from core.twelve_data_client import get_quote as td_quote
            td = td_quote(sym)
            if td:
                price = float(td.get("close", 0) or 0)
                prev  = float(td.get("previous_close", price) or price)
                change     = round(price - prev, 6)
                change_pct = round(float(td.get("percent_change", 0) or 0), 4)
                if price > 0:
                    return sym, {
                        "symbol":            sym,
                        "price":             price,
                        "change":            change,
                        "changesPercentage": change_pct,
                        "source":            "twelvedata",
                    }
        except Exception:
            pass

    # Source 1: yfinance
    try:
        fi = yf.Ticker(sym).fast_info
        price = fi.last_price
        if price is not None:
            prev  = fi.previous_close
            change     = round(price - prev, 6) if prev else None
            change_pct = round((change / prev) * 100, 4) if (prev and change is not None) else None
            return sym, {
                "symbol":            sym,
                "price":             price,
                "change":            change,
                "changesPercentage": change_pct,
                "source":            "yfinance",
            }
    except Exception:
        pass

    # Source 2: Finnhub (fallback for everything else)
    try:
        from core.finnhub_client import quote as fh_quote
        fh = fh_quote(sym)
        if fh and fh.get("c", 0) > 0:
            price = fh["c"]
            prev  = fh.get("pc", price)
            change     = round(price - prev, 6)
            change_pct = round((change / prev) * 100, 4) if prev else None
            return sym, {
                "symbol":            sym,
                "price":             price,
                "change":            change,
                "changesPercentage": change_pct,
                "source":            "finnhub",
            }
    except Exception:
        pass

    # All sources failed — mark as failed so we skip for 30 min
    _mark_failed(sym)
    return sym, None


def fetch_batch_quotes(tickers: List[str]) -> tuple:
    """
    Fetch live price and day change for all tickers in parallel.
    Cap at 12 workers to avoid memory spikes and API rate-limit bans.

    Returns: (results, explicit_failures)
      results:           { ticker: {price, change, changesPercentage, source} }  — successful fetches
      explicit_failures: set of tickers that were processed AND returned no price (all sources tried)

    Tickers that didn't complete before the 60s timeout are NOT in explicit_failures —
    they are silently skipped so the caller can retry them later without the 30-min cooldown.
    """
    if not tickers:
        return {}, set()

    results: Dict[str, dict] = {}
    explicit_failures: set = set()
    max_workers = min(len(tickers), 15)   # increased from 12 for larger portfolios

    # Scale timeout: 60s base + 3s per ticker beyond 20
    batch_timeout = max(60, 60 + (len(tickers) - 20) * 3) if len(tickers) > 20 else 60

    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {pool.submit(_fetch_one_quote, sym): sym for sym in tickers}
        try:
            for future in as_completed(futures, timeout=batch_timeout):
                try:
                    sym, data = future.result(timeout=15)
                    if data is not None:
                        results[sym] = data
                    else:
                        # _fetch_one_quote tried all sources and returned None explicitly
                        explicit_failures.add(sym)
                except Exception:
                    pass
        except Exception:
            # Timeout — return whatever completed; timed-out tickers are NOT failed
            pass
    finally:
        pool.shutdown(wait=False)

    return results, explicit_failures


def fetch_batch_quotes_with_cache(tickers: List[str]) -> Dict[str, dict]:
    """
    SQLite-backed incremental price fetch.

    Flow:
      1. Read ALL prices from SQLite instantly (sub-millisecond)
      2. Find stale tickers  (missing OR older than 5 minutes)
      3. Fetch ONLY the stale ones via the live API
      4. Write fresh prices back to SQLite
      5. Return merged result

    First call (empty cache): fetches everything — same as before.
    Subsequent calls: only re-fetches tickers whose price is >5 min old.
    Server restart: SQLite survives — prices load from DB, only stale ones re-fetched.
    """
    if not tickers:
        return {}

    from core.database import get_price_cache, save_price_cache, get_stale_tickers

    # Step 1: Serve from SQLite immediately
    cached = get_price_cache(tickers)

    # Step 2: Identify what needs refreshing
    # Skip tickers in the 30-min failed-ticker cooldown — they reliably return no price
    stale = [t for t in get_stale_tickers(tickers) if not _is_failed(t)]

    if stale:
        # Step 3: Fetch only stale tickers
        fresh, explicit_failures = fetch_batch_quotes(stale)
        # Step 4: Persist to SQLite
        # Only mark EXPLICIT failures (all sources tried, none returned a price).
        # Tickers that timed out (never processed) are NOT marked failed — they'll retry next cycle.
        if fresh:
            save_price_cache(fresh)
        if explicit_failures:
            from core.database import save_failed_tickers
            save_failed_tickers(list(explicit_failures))
        # Step 5: Merge fresh into cached
        cached.update(fresh)

    return cached


# ─────────────────────────────────────────
# KEY METRICS (on-demand, parallel)
# ─────────────────────────────────────────

def _fetch_one_metrics(sym: str) -> tuple:
    """Fetch fundamental metrics for a single ticker. Runs in a thread pool."""
    import yfinance as yf
    try:
        info = yf.Ticker(sym).info
        return sym, {
            "peRatioTTM":      info.get("trailingPE"),
            "roicTTM":         info.get("returnOnEquity"),  # Closest free equivalent to ROIC
            "debtToEquityTTM": info.get("debtToEquity"),
        }
    except Exception:
        return sym, {}


def fetch_key_metrics(ticker: str) -> dict:
    """
    Fetch fundamental health metrics for one ticker.
    Called only when user clicks 'Load Health Metrics'.
    """
    _, data = _fetch_one_metrics(ticker)
    return data


def add_key_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add P/E, ROE (≈ROIC), and Debt/Equity to the enriched portfolio DataFrame.
    Fetches ALL tickers in parallel — call only when user explicitly requests it.
    """
    if df.empty:
        return df

    df = df.copy()
    tickers = df["ticker"].dropna().tolist()
    metrics_map: Dict[str, dict] = {}

    max_workers = min(len(tickers), 15)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one_metrics, sym): sym for sym in tickers}
        for future in as_completed(futures):
            sym, data = future.result()
            metrics_map[sym] = data

    df["pe_ratio"]       = df["ticker"].map(lambda t: metrics_map.get(t, {}).get("peRatioTTM"))
    df["roic"]           = df["ticker"].map(lambda t: metrics_map.get(t, {}).get("roicTTM"))
    df["debt_to_equity"] = df["ticker"].map(lambda t: metrics_map.get(t, {}).get("debtToEquityTTM"))
    return df


# ─────────────────────────────────────────
# PORTFOLIO ENRICHMENT (main function)
# ─────────────────────────────────────────

def enrich_portfolio(df: pd.DataFrame, base_currency: str = "USD") -> pd.DataFrame:
    """
    Takes raw holdings from the database and returns a fully enriched DataFrame.

    For each holding:
    1. Auto-detects the correct trading currency from ticker suffix
    2. Fetches live price + day change (all tickers in parallel via ThreadPoolExecutor)
    3. Gets the FX rate to convert to your chosen base_currency
    4. Calculates market value, unrealized P&L, day gain — all in base_currency

    New columns added:
      current_price, price_change, change_pct,
      fx_rate, cost_basis, market_value,
      unrealized_pnl, unrealized_pnl_pct, day_gain
    """
    if df.empty:
        return df

    df = df.copy()

    # Step 1: Resolve currency for each holding
    # Ticker suffix is ground truth (overrides DB value for known exchanges)
    def resolve_currency(row):
        detected = detect_currency_from_ticker(str(row.get("ticker", "")))
        if detected != "USD":
            return detected   # Definitive: .NS=INR, .AE=AED, .HK=HKD, etc.
        # Fall back to stored currency — normalise common mistakes (DFM→AED, NSE→INR, etc.)
        stored = str(row.get("currency") or "USD").strip()
        return normalise_currency(stored) if stored else "USD"

    df["currency"] = df.apply(resolve_currency, axis=1)

    # Step 1b: Resolve tickers that are missing exchange suffixes (UAE, Swiss, etc.)
    from core.data_engine import resolve_tickers_batch
    pairs = [(str(row["ticker"]), str(row["currency"])) for _, row in df.iterrows()
             if pd.notna(row.get("ticker"))]
    resolved = resolve_tickers_batch(pairs)
    df["ticker_resolved"] = df["ticker"].map(lambda t: resolved.get(t, t))

    # Step 2: Batch-fetch live quotes in parallel (use resolved tickers)
    # Uses SQLite cache — instant on second load, only re-fetches stale tickers
    tickers = df["ticker_resolved"].dropna().tolist()
    quotes  = fetch_batch_quotes_with_cache(tickers)

    # Step 3: Fetch FX rates for each unique currency in parallel (5s timeout each)
    unique_currencies = df["currency"].unique().tolist()
    fx_rates: Dict[str, float] = {}
    if unique_currencies:
        fx_pool = ThreadPoolExecutor(max_workers=min(len(unique_currencies), 8))
        try:
            fx_futures = {fx_pool.submit(get_exchange_rate, c, base_currency): c
                          for c in unique_currencies}
            try:
                for f in as_completed(fx_futures, timeout=15):
                    c = fx_futures[f]
                    try:
                        fx_rates[c] = f.result(timeout=5)
                    except Exception:
                        fx_rates[c] = 1.0
            except Exception:
                pass
        finally:
            fx_pool.shutdown(wait=False)
        # Fill any missing currencies
        for c in unique_currencies:
            fx_rates.setdefault(c, 1.0)

    # Step 4: Calculate enriched values row by row
    rows = []
    for _, row in df.iterrows():
        ticker   = str(row.get("ticker_resolved", row.get("ticker", "")))
        quote    = quotes.get(ticker, {})
        currency = row.get("currency", "USD") or "USD"
        fx       = fx_rates.get(currency, 1.0)

        qty      = float(row.get("quantity", 0) or 0)
        avg_cost = float(row.get("avg_cost", 0) or 0)

        current_price = quote.get("price")
        price_change  = quote.get("change")
        change_pct    = quote.get("changesPercentage")

        cost_basis = qty * avg_cost * fx

        if current_price is not None:
            market_value       = qty * current_price * fx
            unrealized_pnl     = market_value - cost_basis
            unrealized_pnl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost else None
            day_gain           = (qty * price_change * fx) if price_change is not None else None
        else:
            market_value = unrealized_pnl = unrealized_pnl_pct = day_gain = None

        rows.append({
            **row.to_dict(),
            "current_price":      current_price,
            "price_change":       price_change,
            "change_pct":         change_pct,
            "fx_rate":            fx,
            "cost_basis":         cost_basis,
            "market_value":       market_value,
            "unrealized_pnl":     unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "day_gain":           day_gain,
        })

    return pd.DataFrame(rows)
