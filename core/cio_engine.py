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

import logging
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
    # Balasore Alloys Ltd — real NSE symbol is BALASORE (BSE 513142), mapped in
    # TICKER_OVERRIDES so the identity is right and any future feed that covers
    # it will work. As of 2026-09-06 no free quote API (Yahoo NS/BO, Finnhub)
    # returns a price and Trendlyne's export has a blank Day Change, so today
    # it is still valued from the broker's last reported price.
    "BALASORE.NS":   "No free quote feed covers this NSE line yet — valued from your broker's price",
    "BALASORE":      "No free quote feed covers this NSE line yet — valued from your broker's price",
    "ISPATALLOY.NS": "No free quote feed covers this NSE line yet — valued from your broker's price",
    "ISPATALLOY":    "No free quote feed covers this NSE line yet — valued from your broker's price",
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



# ── UAE circuit breaker ───────────────────────────────────────────────────────
# Mubasher is the ONLY free source that covers ADX/DFM, and it sits behind
# Cloudflare, which 403s datacenter IPs — so on Render every UAE name walks the
# whole cascade (Mubasher 403 → Twelve Data, which has no ADX/DFM on this plan →
# yfinance, which 404s quoteSummary → Finnhub, which is US-only) and fails at the
# end of it. Measured in production 07-Sep-2026: ~53 SECONDS of guaranteed-failing
# lookups on every cold start, and the free tier cold-starts roughly every 17
# minutes. That is the single largest avoidable component of "the app is stuck".
#
# A breaker, not a hardcoded skip list: from a residential IP or a GitHub Actions
# runner Mubasher works fine (measured: ADCB.AE in 2.3s), and a NO_LIVE_SOURCE
# entry would disable it permanently everywhere. After three failed UAE lookups
# in one process we stop trying for that process's lifetime and fall straight
# through to last_known_price — the IBKR mark, which is what actually prices
# these lines today (core/ibkr_prices.apply_static_marks_to_holdings).
#
# Once open it STAYS open for the process: the short-circuit runs before the
# Mubasher call, so a later success cannot be observed to close it again. That is
# deliberate — a Render instance lives ~16 minutes, so a restart re-arms it soon
# enough, and probing a blocked CDN on every request to find out costs exactly the
# 5s-per-name this exists to avoid. reset_uae_circuit() re-arms it explicitly.
# The UAE circuit breaker lived here. It existed only to stop re-trying
# Mubasher after repeated Cloudflare 403s; with Mubasher removed from the price
# path there is nothing to break the circuit on.


# _fetch_one_quote() was here until 8 Sep 2026 — ~240 lines walking up to six
# sources per ticker, 186 times a refresh. core/market_data.py replaced it with
# per-market tier lists of batch-shaped providers, and everything the cascade
# could reach is now a provider there (including yfinance fast_info, which was
# the last thing only it contributed).
#
# Three of its six sources were known-dead and were being called anyway:
#   * Mubasher      HTTP 403 from Render — Cloudflare blocks datacenter IPs
#   * Twelve Data   404 "available starting with the Pro or Venture plan" for
#                   UAE, India and OTC funds on this subscription
#   * Twelve Data's UAE symbol rewrite, which turned EMAAR into "EMAAR:DFM" —
#                   a form no source could quote — and then cached it for 24h
#
# Deleting it removes the second, divergent price path rather than leaving two
# implementations to drift apart.


def fetch_batch_quotes(tickers: List[str]) -> tuple:
    """Price every ticker via core.market_data.

    Returns: (results, explicit_failures)
      results:           { ticker: {price, change, changesPercentage, source,
                                    currency, latency, asof} }
      explicit_failures: tickers every tier declined to price

    Unlike the cascade this replaced, a "failure" here is a real answer: the
    pipeline walked each market's whole tier list, ending at the broker's own
    mark, and nothing had a number. Those are genuinely unpriceable instruments
    (a suspended listing, an offshore fund with no public NAV), so marking them
    failed and backing off is correct rather than pessimistic.
    """
    if not tickers:
        return {}, set()

    from core.database import get_instrument_meta
    from core.market_data import fetch_for_tickers

    try:
        meta = get_instrument_meta(list(tickers))
    except Exception:
        meta = {}

    try:
        quotes, report = fetch_for_tickers(list(tickers), meta)
    except Exception as exc:  # noqa: BLE001
        # There is no second price path any more, so a total pipeline failure
        # must not also destroy the cached prices the caller already holds.
        logging.getLogger(__name__).error("quote pipeline failed: %r", exc)
        return {}, set()

    results = {tkr: quote.to_cache_row() for tkr, quote in quotes.items()}
    explicit_failures = set(report.unpriced)

    if report.requested:
        logging.getLogger(__name__).info(
            "quotes: %d/%d priced in %dms — sources %s, latency %s%s",
            report.priced, report.requested, report.elapsed_ms,
            report.by_source, report.by_latency,
            f", no source for {report.unpriced}" if report.unpriced else "",
        )
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
