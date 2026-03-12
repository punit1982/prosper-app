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

    # Layer 1: in-memory
    if cache_key in _fx_cache:
        return _fx_cache[cache_key]

    # Layer 2: SQLite (survives restarts)
    try:
        from core.database import get_fx_rate_cache
        sqlite_rates = get_fx_rate_cache([cache_key])
        if cache_key in sqlite_rates:
            rate = sqlite_rates[cache_key]
            _fx_cache[cache_key] = rate
            return rate
    except Exception:
        pass

    # Layer 3: live fetch from yfinance (5-second timeout)
    try:
        import yfinance as yf
        from concurrent.futures import ThreadPoolExecutor
        pair = f"{from_currency}{to_currency}=X"

        def _fetch_rate():
            return yf.Ticker(pair).fast_info.last_price

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_fetch_rate)
            rate = future.result(timeout=5)

        if rate and float(rate) > 0:
            _fx_cache[cache_key] = float(rate)
            try:
                from core.database import save_fx_rate_cache
                save_fx_rate_cache({cache_key: float(rate)})
            except Exception:
                pass
            return float(rate)
    except Exception:
        pass

    # Safe fallback
    _fx_cache[cache_key] = 1.0
    return 1.0


def clear_fx_cache():
    """Clear the in-memory FX rate cache (called when base currency changes)."""
    _fx_cache.clear()
