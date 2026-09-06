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

import math
import pandas as pd
from typing import Dict, List, Optional

from core.settings import SETTINGS
from core.currency_normalizer import detect_currency_from_ticker, get_exchange_rate, normalise_currency
from core.parallel import gather


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


# Tickers with NO live quote on any source Prosper can reach, for a reason that
# is a property of the instrument rather than a transient fetch failure. These
# skip the whole fetch cascade and go straight to the broker's own last mark
# (holdings.last_known_price), and the UI reports them as "priced from the
# broker's mark", not as an error the user could fix by correcting a ticker.
# Each entry records WHY, because the right answer changes if the reason does.
NO_LIVE_SOURCE: Dict[str, str] = {
    # Ozon Holdings PLC ADR (ISIN US69269L1044). Nasdaq listing suspended;
    # IBKR carries the position on its internal "VALUE" exchange and marks it
    # by hand. Verified 2026-09-06: Yahoo returns "symbol may be delisted" for
    # both OZON and the OZONY OTC line.
    "OZON":         "Listing suspended — no public quote; IBKR's own mark is used",
    # Balasore Alloys Ltd (NSE ISPATALLOY / BSE 513142). Verified 2026-09-06:
    # no data on Yahoo for ISPATALLOY.NS, ISPATALLOY.BO or 513142.BO, and
    # Trendlyne's own export reports a blank Day Change % — i.e. the source
    # Prosper imports from has no live quote either.
    "ISPATALLOY.NS": "Trading suspended on NSE/BSE — last reported price is used",
    "ISPATALLOY":    "Trading suspended on NSE/BSE — last reported price is used",
}


def _is_unlisted_india_fund(ticker: str) -> bool:
    """Legacy rows where Trendlyne's Morningstar fund id was written straight
    into a ".NS" ticker (e.g. "F0GBR06R8K.NS"). Open-ended Indian mutual funds
    are not exchange-listed, so no NSE/BSE symbol exists and no quote API can
    ever price them. parse_trendlyne() now emits "MF:<id>" for these, but
    holdings saved before that fix still carry the ".NS" form — recognising it
    here self-heals them without needing a re-upload."""
    t = str(ticker).upper()
    base = t.split(".")[0]
    return t.endswith((".NS", ".BO")) and base.startswith("F0") and len(base) >= 8


def _is_synthetic_ticker(ticker) -> bool:
    """True for placeholder tickers with no real exchange symbol to price live —
    "MF:..." (Morningstar-ID-only mutual funds, core/file_parsers.py),
    "RESTRICTED:..." (unvested RSU/PSU stock-plan awards, core/screenshot_parser.py),
    legacy Morningstar-id-as-".NS" fund rows, and instruments in NO_LIVE_SOURCE.
    These always rely on last_known_price instead."""
    t = str(ticker)
    return (
        t.startswith("MF:")
        or t.startswith("RESTRICTED:")
        or _is_unlisted_india_fund(t)
        or t.upper() in NO_LIVE_SOURCE
    )


def no_live_source_reason(ticker) -> Optional[str]:
    """Plain-English reason this holding has no live quote, or None if it
    should be priceable and a missing price is a real failure."""
    t = str(ticker)
    if t.startswith("RESTRICTED:"):
        return "Unvested stock-plan award — valued at the plan's reported price"
    if t.startswith("MF:") or _is_unlisted_india_fund(t):
        return "Open-ended mutual fund — not exchange-listed; NAV from the broker"
    return NO_LIVE_SOURCE.get(t.upper())


# ─────────────────────────────────────────
# LIVE QUOTES  (parallel)
# ─────────────────────────────────────────

def _is_twelve_data_symbol(sym: str) -> bool:
    """Check if a symbol is in Twelve Data exchange format (e.g. 'EMAAR:DFM').

    Must accept every exchange code twelve_data_client.resolve_uae_symbol() can
    produce (DFM, ADX, XADS) — previously ':ADX' symbols were never routed to
    Twelve Data and always ended up as "No live price".
    """
    if ":" not in sym:
        return False
    try:
        from core.twelve_data_client import UAE_EXCHANGES
    except Exception:
        UAE_EXCHANGES = ["DFM", "ADX", "XADS"]
    return any(sym.endswith(f":{ex}") for ex in UAE_EXCHANGES)


def _price_sanity_check(sym: str, price: float, source: str = "") -> bool:
    """
    Return True if the price looks valid.  Suppresses:
      - None / NaN / infinite prices (data error)
      - Negative prices (data error)
      - ETF/fund prices > 10 000 (likely wrong ticker or currency mismatch)
    """
    if price is None:
        return False
    try:
        price = float(price)
    except (TypeError, ValueError):
        return False
    if math.isnan(price) or math.isinf(price) or price < 0:
        return False
    # ETF / fund prices should not exceed 10 000 — flag as suspicious
    # (most ETFs/funds trade well below 1 000; > 10 000 usually means wrong ticker)
    if price > 10_000:
        # Only flag for known ETF-like tickers (suffix-based heuristic)
        etf_hints = (".L", ".SW", ".PA", ".DE", ".AS")
        if any(sym.upper().endswith(h) for h in etf_hints):
            import logging
            logging.getLogger(__name__).warning(
                "Price sanity: %s has price %.2f from %s — possibly incorrect ETF/fund price",
                sym, price, source,
            )
            return False
    return True


def _fetch_one_quote(sym: str) -> tuple:
    """
    Fetch price data for a single ticker.
    Cascade: ADX/Mubasher (ADX stocks) → Twelve Data (UAE/DFM) → yfinance → Finnhub
    """
    import yfinance as yf

    # Source 0a: Mubasher intraday CSV — the ONLY working free source for UAE
    # (ADX + DFM) prices. Gated on is_uae_symbol(), not is_adx_ticker(): the
    # latter is an exact-key lookup in a 7-entry static chart-ID map, so
    # ALDAR.AE / BURJEEL.AE / PUREHEALTH.AE and every ":DFM"/":ADX" colon form
    # never reached Mubasher at all and fell through to sources with no UAE
    # coverage. adx_client discovers chart IDs at runtime for anything not in
    # the map, so the map is an optimisation, not the supported-ticker list.
    try:
        from core.adx_client import get_quote as adx_quote, is_uae_symbol
        if is_uae_symbol(sym):
            adx = adx_quote(sym)
            if adx and adx.get("price", 0) > 0:
                adx["symbol"] = sym
                adx.setdefault("currency", "AED")
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
    # Hard per-call timeout — same reasoning as core/data_engine.py
    # _yf_fetch_info: a slow/blocked yfinance call can occupy its worker slot
    # far longer than the batch's own outer timeout accounts for, since that
    # outer timeout only bounds how long the CALLER waits for already-done
    # futures, not how long a still-running call keeps its slot. fast_info
    # currently appears to still work reliably, but .info (a different Yahoo
    # endpoint) started silently failing slowly across the board — bounding
    # this call too prevents that same failure mode from ever reintroducing a
    # multi-minute page hang here.
    try:
        from core.parallel import run_with_timeout

        def _fetch_fast_info():
            tk = yf.Ticker(sym)
            fi = tk.fast_info
            return fi.last_price, fi.previous_close, getattr(fi, "currency", None)

        _fi_result = run_with_timeout(_fetch_fast_info, timeout=6, default=None)
        price, prev_close, yf_ccy = _fi_result if _fi_result else (None, None, None)
        if price is not None and _price_sanity_check(sym, price, "yfinance"):
            prev  = prev_close
            change     = round(price - prev, 6) if prev else None
            change_pct = round((change / prev) * 100, 4) if (prev and change is not None) else None
            # Include trading currency so enrichment can override suffix-based guess
            yf_currency = yf_ccy or ""
            result = {
                "symbol":            sym,
                "price":             price,
                "change":            change,
                "changesPercentage": change_pct,
                "source":            "yfinance",
            }
            if yf_currency:
                result["currency"] = yf_currency.upper()
            return sym, result
    except Exception:
        pass

    # Source 1b: Yahoo's public `chart` endpoint, called directly.
    # The reliability audit (5 Sep 2026) confirmed live that `chart` still
    # serves quotes with no auth and no crumb, while the `quoteSummary` and v7
    # `quote` endpoints yfinance also relies on now return "Unauthorized /
    # Invalid Crumb" on a raw call — yfinance only works because of an internal
    # crumb workaround that has already broken once (v7.4). This is the same
    # data from the same vendor without that fragility, and it covers the
    # non-US exchanges Finnhub below does not (Borsa Italiana, BSE, SGX, SIX).
    try:
        import requests as _rq
        r = _rq.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
            # range=1d: meta.chartPreviousClose is then the PREVIOUS SESSION's
            # close, which is what a day change is measured against. Over a
            # longer range it is instead the close before the window starts
            # (5d gave Prysmian a "+0.16%" and an SME line a "-47%" day move).
            params={"range": "1d", "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        if r.status_code == 200:
            meta = ((r.json().get("chart") or {}).get("result") or [{}])[0].get("meta") or {}
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            if prev is not None and float(prev) <= 0:
                prev = None
            if price and _price_sanity_check(sym, price, "yahoo-chart"):
                price = float(price)
                change = round(price - float(prev), 6) if prev else None
                result = {
                    "symbol":            sym,
                    "price":             price,
                    "change":            change,
                    "changesPercentage": round((change / float(prev)) * 100, 4) if (prev and change is not None) else None,
                    "source":            "yahoo-chart",
                }
                if meta.get("currency"):
                    result["currency"] = str(meta["currency"]).upper()
                return sym, result
    except Exception:
        pass

    # Source 2: Finnhub (fallback for everything else)
    try:
        from core.finnhub_client import quote as fh_quote
        fh = fh_quote(sym)
        if fh and fh.get("c", 0) > 0 and _price_sanity_check(sym, fh["c"], "finnhub"):
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

    # Source 3: Twelve Data general fallback — for anything NOT already routed
    # to it above (i.e. not UAE). Twelve Data's symbol format is
    # "TICKER:EXCHANGE"; only include suffixes verified against the live API.
    # NOTE (2026-09-05): NSE/BSE (India) and OTC mutual-fund symbols currently
    # return "available starting with the Grow or Venture plan" on the
    # TWELVE_DATA_API_KEY free tier configured for this app — this fallback
    # will keep failing for Indian tickers/funds until that plan is upgraded,
    # but costs nothing extra when it does (it's a last resort, after
    # yfinance+Finnhub both already failed) and starts working immediately
    # the day the plan changes, with no further code changes.
    if not _is_twelve_data_symbol(sym):
        try:
            from core.twelve_data_client import get_quote as td_quote, is_configured as td_configured
            if td_configured():
                base, _, suffix = sym.partition(".")
                td_symbol = {
                    "NS": f"{base}:NSE", "BO": f"{base}:BSE", "L": f"{base}:LSE",
                }.get(suffix.upper(), sym if "." not in sym else None)
                if td_symbol:
                    td = td_quote(td_symbol)
                    if td:
                        price = float(td.get("close", 0) or 0)
                        prev  = float(td.get("previous_close", price) or price)
                        if price > 0 and _price_sanity_check(sym, price, "twelvedata"):
                            return sym, {
                                "symbol":            sym,
                                "price":             price,
                                "change":            round(price - prev, 6),
                                "changesPercentage": round(((price - prev) / prev) * 100, 4) if prev else None,
                                "source":            "twelvedata",
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

    # Scale timeout: 30s base + 2s per ticker beyond 20. This is now a REAL
    # deadline — core.parallel.gather() abandons stragglers instead of waiting.
    batch_timeout = max(30, 30 + (len(tickers) - 20) * 2) if len(tickers) > 20 else 30

    done, _errored = gather(
        _fetch_one_quote,
        [(sym, (sym,)) for sym in tickers],
        max_workers=6,
        timeout=batch_timeout,
    )
    for sym, (_, data) in done.items():
        if data is not None:
            results[sym] = data
        else:
            explicit_failures.add(sym)
    # Timed-out / errored tickers are NOT marked failed — they retry next cycle.

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

    done, _ = gather(
        _fetch_one_metrics,
        [(sym, (sym,)) for sym in tickers],
        max_workers=5,
        timeout=max(30, 3 * len(tickers)),
    )
    for sym, (_, data) in done.items():
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
    # "MF:..." and "RESTRICTED:..." are synthetic tickers with no real exchange
    # symbol to resolve — skip them so the resolver cascade doesn't burn API
    # calls on a guaranteed miss.
    from core.data_engine import resolve_tickers_batch
    pairs = [(str(row["ticker"]), str(row["currency"])) for _, row in df.iterrows()
             if pd.notna(row.get("ticker")) and not _is_synthetic_ticker(row["ticker"])]
    resolved = resolve_tickers_batch(pairs)
    df["ticker_resolved"] = df["ticker"].map(lambda t: resolved.get(t, t))

    # Step 1c: Backfill missing/useless company names. Japanese (.T) and
    # Singaporean (.SI) exchanges use numeric scrip codes as the ticker itself
    # (e.g. "4519.T", "S08.SI") — when the source statement had no separate
    # description column, "name" ends up being that same numeric code, which
    # tells the user nothing. Fetch the real company name for just those rows.
    def _name_is_useless(name, ticker) -> bool:
        n = str(name or "").strip()
        if not n or n.lower() in ("nan", "none"):
            return True
        base_ticker = str(ticker or "").split(".")[0]
        return n == str(ticker) or n == base_ticker or n.replace(" ", "").isdigit()

    _needs_name = [
        str(row["ticker_resolved"]) for _, row in df.iterrows()
        if pd.notna(row.get("ticker_resolved")) and not _is_synthetic_ticker(row["ticker_resolved"])
        and _name_is_useless(row.get("name"), row.get("ticker"))
    ]
    if _needs_name:
        from core.data_engine import get_ticker_info_batch
        _name_info = get_ticker_info_batch(_needs_name)
        _name_map = {
            t: (info.get("shortName") or info.get("longName"))
            for t, info in _name_info.items() if info.get("shortName") or info.get("longName")
        }
        if _name_map:
            for idx, row in df.iterrows():
                better = _name_map.get(str(row["ticker_resolved"]))
                if better:
                    df.at[idx, "name"] = better

    # Step 2: Batch-fetch live quotes in parallel (use resolved tickers)
    # Uses SQLite cache — instant on second load, only re-fetches stale tickers.
    # "MF:..." (see core/file_parsers.py parse_trendlyne) and "RESTRICTED:..."
    # (see core/screenshot_parser.py) are synthetic — not a real exchange
    # symbol — for holdings with no live-tradeable ticker at all (Morningstar-
    # ID-only Indian mutual funds; unvested RSU/PSU stock-plan awards). Fetching
    # them would just burn a cascade of guaranteed-failing API calls on every
    # load; skip straight to their last_known_price fallback in Step 4 instead.
    tickers = [t for t in df["ticker_resolved"].dropna().tolist() if not _is_synthetic_ticker(t)]
    quotes  = fetch_batch_quotes_with_cache(tickers)

    # Step 2b: Override currency if yfinance reports a different trading currency
    # This fixes cases like U03A.L which has .L suffix (→ GBP) but trades in USD.
    for idx, row in df.iterrows():
        resolved_ticker = row.get("ticker_resolved", row.get("ticker", ""))
        quote = quotes.get(resolved_ticker, {})
        yf_currency = quote.get("currency", "")
        if yf_currency and yf_currency != row["currency"]:
            df.at[idx, "currency"] = yf_currency

    # Step 3: Fetch FX rates for each unique currency in parallel (15s hard deadline)
    unique_currencies = df["currency"].unique().tolist()
    fx_rates: Dict[str, float] = {}
    if unique_currencies:
        done, _ = gather(
            get_exchange_rate,
            [(c, (c, base_currency)) for c in unique_currencies],
            max_workers=4,
            timeout=15,
        )
        fx_rates.update({c: float(r) for c, r in done.items() if r})
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

        # No live source can price this ticker (offshore/unlisted funds — see
        # core/file_parsers.py for how last_known_price is captured from the
        # broker's own statement). Fall back to it so market value reflects
        # something real instead of silently disappearing.
        if current_price is None:
            fallback_price = row.get("last_known_price")
            if fallback_price is not None and float(fallback_price) > 0:
                current_price = float(fallback_price)
                price_change = change_pct = None

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
