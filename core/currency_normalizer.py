"""
Currency Normalizer
===================
Auto-detects each stock's trading currency from its ticker suffix,
then converts all values to a chosen base currency using live FX rates.

FX rates come from yfinance (free, no API key). Yahoo uses "AEDUSD=X" notation.

Examples:
  AAPL         → USD  (no suffix = US market)
  RELIANCE.NS  → INR  (NSE India)
  EMAAR.AE     → AED  (Dubai DFM)
  0700.HK      → HKD  (Hong Kong)
"""

from typing import Dict

# Maps ticker suffix → home trading currency
TICKER_CURRENCY_MAP = {
    ".NS":  "INR",   # NSE India (National Stock Exchange)
    ".BO":  "INR",   # BSE India (Bombay Stock Exchange)
    ".AE":  "AED",   # Dubai Financial Market (DFM)
    ".AD":  "AED",   # Abu Dhabi Securities Exchange (ADX)
    ".DU":  "AED",   # Dubai (alternative suffix)
    ".HK":  "HKD",   # Hong Kong Stock Exchange
    ".SI":  "SGD",   # Singapore Exchange
    ".L":   "GBP",   # London Stock Exchange
    ".PA":  "EUR",   # Euronext Paris
    ".AS":  "EUR",   # Euronext Amsterdam
    ".DE":  "EUR",   # XETRA Germany
    ".MC":  "EUR",   # Madrid Stock Exchange
    ".MI":  "EUR",   # Milan Stock Exchange
    ".AX":  "AUD",   # Australian Securities Exchange
    ".TO":  "CAD",   # Toronto Stock Exchange
    ".SS":  "CNY",   # Shanghai Stock Exchange
    ".SZ":  "CNY",   # Shenzhen Stock Exchange
    ".T":   "JPY",   # Tokyo Stock Exchange
    ".KS":  "KRW",   # Korea Stock Exchange
    ".TW":  "TWD",   # Taiwan Stock Exchange
    ".SA":  "BRL",   # B3 Brazil
    ".JO":  "ZAR",   # Johannesburg Stock Exchange
    ".SW":  "CHF",   # SIX Swiss Exchange
    ".TA":  "ILS",   # Tel Aviv Stock Exchange
}

# In-memory FX rate cache — avoids redundant calls within a session
_fx_cache: Dict[str, float] = {}

import logging as _logging
_fx_log = _logging.getLogger("prosper.fx")

# ── Hard currency pegs ──────────────────────────────────────────────────────
# The UAE dirham has been pegged to the US dollar at exactly 3.6725 since 1997
# (1 USD = 3.6725 AED  ⇔  1 AED = 0.27229...  USD). It does not float, so it
# should never be fetched live and can never be the reason a rate is missing.
# Rates below are USD -> X.
_PEGGED_USD_RATES: Dict[str, float] = {
    "AED": 3.6725,   # UAE dirham — CBUAE peg
    "SAR": 3.7500,   # Saudi riyal — SAMA peg
    "HKD": 7.8000,   # HK dollar — HKMA band midpoint (soft peg, close enough for a fallback)
}

# ── Static fallback table (USD -> X), refreshed manually ────────────────────
# Last hand-updated 2026-09-05. Only ever used when BOTH the live fetch and
# every cached value have failed — a rough rate here is still far better than
# silently valuing a foreign holding 1:1 with USD. Keep the peg table above
# authoritative for the currencies it covers.
_STATIC_USD_RATES: Dict[str, float] = {
    "AED": 3.6725, "SAR": 3.7500, "HKD": 7.8000,
    "INR": 94.5, "EUR": 0.861, "GBP": 0.740, "JPY": 156.0, "CHF": 0.810,
    "SGD": 1.267, "CAD": 1.383, "AUD": 1.52, "CNY": 7.13, "KRW": 1385.0,
    "TWD": 30.5, "BRL": 5.45, "ZAR": 17.6, "ILS": 3.35,
}


def _rate_from_usd_table(table: Dict[str, float], frm: str, to: str):
    """Derive a cross rate frm->to from a USD-based table. Returns None if
    either leg is missing."""
    f = 1.0 if frm == "USD" else table.get(frm)
    t = 1.0 if to == "USD" else table.get(to)
    if f and t:
        return t / f
    return None


def _fetch_rate_open_er_api(base: str):
    """Free, keyless FX source (open.er-api.com, ~160 currencies incl. AED/INR/
    SGD). Returns {code: rate} for USD... actually for `base`. 8s timeout."""
    try:
        import requests
        from core.parallel import run_with_timeout

        def _go():
            r = requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=6)
            j = r.json()
            return j.get("rates") if j.get("result") == "success" else None

        return run_with_timeout(_go, timeout=8, default=None)
    except Exception:
        return None

# Maps common incorrect/non-standard currency codes → correct ISO codes
# Claude sometimes returns exchange names (DFM, NSE) instead of proper currencies
CURRENCY_CORRECTIONS = {
    "DFM":  "AED",   # Dubai Financial Market  → UAE Dirham
    "ADX":  "AED",   # Abu Dhabi Securities     → UAE Dirham
    "NSE":  "INR",   # National Stock Exchange  → Indian Rupee
    "BSE":  "INR",   # Bombay Stock Exchange    → Indian Rupee
    "HKEX": "HKD",   # Hong Kong Exchange       → HK Dollar
    "SGX":  "SGD",   # Singapore Exchange       → SGD
    "LSE":  "GBP",   # London Stock Exchange    → GBP
}


def detect_currency_from_ticker(ticker: str) -> str:
    """
    Detect the trading currency from a ticker symbol's exchange suffix.
    Falls back to USD for US-listed stocks (no suffix).

    Examples:
      "AAPL"        → "USD"
      "RELIANCE.NS" → "INR"
      "EMAAR.AE"    → "AED"
      "0700.HK"     → "HKD"
    """
    if not ticker:
        return "USD"
    ticker_upper = ticker.strip().upper()
    for suffix, currency in TICKER_CURRENCY_MAP.items():
        if ticker_upper.endswith(suffix.upper()):
            return currency
    return "USD"


def normalise_currency(code: str) -> str:
    """
    Convert a currency string to a proper ISO 4217 code.
    Handles common mistakes like 'DFM' → 'AED', 'NSE' → 'INR', etc.
    """
    if not code:
        return "USD"
    upper = code.strip().upper()
    return CURRENCY_CORRECTIONS.get(upper, upper)


def get_exchange_rate(from_currency: str, to_currency: str) -> float:
    """
    Get live exchange rate using yfinance (free, no API key).
    Yahoo Finance FX pairs use the format: AEDUSD=X

    Three-layer cache:
    1. In-memory dict (_fx_cache) — fastest, lasts for server process lifetime
    2. SQLite (fx_rate_cache table) — survives server restarts, 1-hour TTL
    3. Live fetch from yfinance — with 5-second timeout
    Returns 1.0 safely if the rate cannot be fetched.
    """
    from_currency = normalise_currency(from_currency)
    to_currency   = normalise_currency(to_currency)

    if from_currency == to_currency:
        return 1.0

    cache_key = f"{from_currency}_{to_currency}"

    # Layer 0: hard pegs — resolve without any network call at all.
    pegged = _rate_from_usd_table(_PEGGED_USD_RATES, from_currency, to_currency)
    if pegged is not None:
        _fx_cache[cache_key] = pegged
        return pegged

    # Layer 1: in-memory
    if cache_key in _fx_cache:
        return _fx_cache[cache_key]

    # Layer 2: SQLite (survives restarts) — fresh rows only (1h TTL)
    try:
        from core.database import get_fx_rate_cache
        sqlite_rates = get_fx_rate_cache([cache_key])
        if cache_key in sqlite_rates:
            rate = sqlite_rates[cache_key]
            _fx_cache[cache_key] = rate
            return rate
    except Exception:
        pass

    # Layer 3: live fetch from yfinance (real 8-second timeout — the thread is
    # abandoned on timeout instead of blocking the page until it finishes)
    try:
        import yfinance as yf
        from core.parallel import run_with_timeout
        pair = f"{from_currency}{to_currency}=X"

        def _fetch_rate():
            return yf.Ticker(pair).fast_info.last_price

        rate = run_with_timeout(_fetch_rate, timeout=8, default=None)

        if rate and float(rate) > 0:
            return _remember_rate(cache_key, float(rate))
    except Exception:
        pass

    # Layer 4: independent live source (open.er-api.com — free, no key, no Yahoo)
    try:
        rates = _fetch_rate_open_er_api(from_currency)
        if rates and to_currency in rates and float(rates[to_currency]) > 0:
            return _remember_rate(cache_key, float(rates[to_currency]))
        # try the USD-based table and cross-derive
        usd_rates = _fetch_rate_open_er_api("USD")
        if usd_rates:
            crossed = _rate_from_usd_table(usd_rates, from_currency, to_currency)
            if crossed:
                return _remember_rate(cache_key, float(crossed))
    except Exception:
        pass

    # Layer 5: STALE cached rate of any age — a day-old rate beats 1.0 by miles
    try:
        from core.database import get_fx_rate_cache
        stale = get_fx_rate_cache([cache_key], max_age=float("inf"))
        if cache_key in stale and float(stale[cache_key]) > 0:
            _fx_log.warning("FX %s: live sources failed, using stale cached rate", cache_key)
            _fx_cache[cache_key] = float(stale[cache_key])
            return float(stale[cache_key])
    except Exception:
        pass

    # Layer 6: static hand-maintained approximate table
    static = _rate_from_usd_table(_STATIC_USD_RATES, from_currency, to_currency)
    if static is not None:
        _fx_log.warning("FX %s: all live+cache sources failed, using static approx rate %.4f",
                        cache_key, static)
        _fx_cache[cache_key] = static
        return static

    # Layer 7: genuinely unknown currency and every source failed. 1.0 would
    # misstate the holding; log loudly so it surfaces rather than hides.
    _fx_log.error("FX %s: NO rate available from any source — returning 1.0 (holding value will be wrong)", cache_key)
    _fx_cache[cache_key] = 1.0
    return 1.0


def _remember_rate(cache_key: str, rate: float) -> float:
    """Store a freshly fetched rate in both cache layers and return it."""
    _fx_cache[cache_key] = rate
    try:
        from core.database import save_fx_rate_cache
        save_fx_rate_cache({cache_key: rate})
    except Exception:
        pass
    return rate


def clear_fx_cache():
    """Clear the in-memory FX rate cache (called when base currency changes)."""
    _fx_cache.clear()


def cash_positions_to_base_currency(cash_df, base_currency: str = "USD"):
    """
    Return cash_df with an added 'amount_base' column: each row's amount
    converted from its own currency into base_currency.

    cash_positions rows are multi-currency (IBKR Forex Balances alone can list
    AED, CHF, EUR, JPY, SGD, USD balances on the same account — see
    core/file_parsers.py parse_ibkr_statement). Summing the raw 'amount' column
    across rows mixes units (e.g. -9,150,285 JPY summed with -101,183 CHF and
    247,712 AED as if they were all the same currency), which produces a
    meaningless total. Every caller that aggregates cash across positions must
    use 'amount_base', not 'amount'.
    """
    import pandas as pd

    if cash_df is None or cash_df.empty:
        if cash_df is None:
            cash_df = pd.DataFrame()
        out = cash_df.copy()
        out["amount_base"] = pd.Series(dtype=float)
        return out

    out = cash_df.copy()
    out["amount_base"] = [
        float(row["amount"]) * get_exchange_rate(row.get("currency") or base_currency, base_currency)
        for _, row in out.iterrows()
    ]
    return out


def total_cash_in_base_currency(cash_df, base_currency: str = "USD") -> float:
    """Sum of all cash_positions rows converted to base_currency. See
    cash_positions_to_base_currency() for why a raw sum of 'amount' is wrong."""
    if cash_df is None or cash_df.empty:
        return 0.0
    return float(cash_positions_to_base_currency(cash_df, base_currency)["amount_base"].sum())
