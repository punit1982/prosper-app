"""
Twelve Data Client
==================
Primary data source for UAE (.AE) stocks that yfinance cannot cover.

Free tier: 800 API credits/day, 8 calls/minute.
One price call = 1 credit.  Batch calls count per symbol.

UAE Exchange codes:
  DFM  = Dubai Financial Market
  XADS = Abu Dhabi Securities Exchange (ADX)

Usage:
  quote = get_quote("EMAAR:DFM")   → full OHLCV + change data
  price = get_price("EMAAR:DFM")   → just the current price (float)
  sym   = resolve_uae_symbol("EMAAR")  → tries DFM then XADS
"""

import os
import time
import threading
from typing import Dict, List, Optional

BASE_URL = "https://api.twelvedata.com"

_lock = threading.Lock()
_call_timestamps: List[float] = []
RATE_LIMIT = 7          # stay safely under 8/min free-tier limit
UAE_EXCHANGES = ["DFM", "ADX", "XADS"]   # try Dubai first, then Abu Dhabi (ADX = exchange name, XADS = MIC code)


# ─── Internal helpers ────────────────────────────────────────────────────────

def _api_key() -> str:
    from core.settings import get_api_key
    return get_api_key("TWELVE_DATA_API_KEY")


def _rate_limit() -> None:
    """Enforce ≤7 calls/minute (free tier is 8/min)."""
    with _lock:
        now = time.time()
        _call_timestamps[:] = [t for t in _call_timestamps if now - t < 60]
        if len(_call_timestamps) >= RATE_LIMIT:
            sleep_time = 60 - (now - _call_timestamps[0]) + 0.5
            if sleep_time > 0:
                time.sleep(sleep_time)
        _call_timestamps.append(time.time())


def _get(endpoint: str, params: dict) -> Optional[dict]:
    """Make a GET request to Twelve Data API. Returns parsed JSON or None."""
    import requests
    key = _api_key()
    if not key:
        return None
    _rate_limit()
    try:
        params["apikey"] = key
        resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        # Twelve Data returns {"code": 400, "message": "..."} for invalid symbols
        if isinstance(data, dict) and data.get("code") in (400, 404, 429):
            return None
        return data
    except Exception:
        return None


# ─── Public API ──────────────────────────────────────────────────────────────

def get_quote(symbol: str) -> Optional[Dict]:
    """
    Fetch full quote for a symbol (e.g. "EMAAR:DFM").
    Returns dict with: close, previous_close, change, percent_change, currency, name
    or None if unavailable.
    """
    data = _get("quote", {"symbol": symbol})
    if not data:
        return None
    # Valid quote has a numeric 'close' field
    try:
        float(data.get("close", ""))
        return data
    except (TypeError, ValueError):
        return None


def get_price(symbol: str) -> Optional[float]:
    """
    Fetch just the current price for a symbol.
    Returns float price or None.
    """
    data = _get("price", {"symbol": symbol})
    if not data:
        return None
    try:
        return float(data.get("price", ""))
    except (TypeError, ValueError):
        return None


def get_price_batch(symbols: List[str]) -> Dict[str, Optional[float]]:
    """
    Fetch prices for multiple symbols in one API call.
    symbols: list of Twelve Data formatted symbols (e.g. ["EMAAR:DFM", "ADCB:XADS"])
    Returns: {symbol: price_float_or_None, ...}
    """
    if not symbols:
        return {}
    key = _api_key()
    if not key:
        return {s: None for s in symbols}

    _rate_limit()
    import requests
    try:
        resp = requests.get(
            f"{BASE_URL}/price",
            params={"symbol": ",".join(symbols), "apikey": key},
            timeout=15,
        )
        if resp.status_code != 200:
            return {s: None for s in symbols}
        data = resp.json()

        result = {}
        if len(symbols) == 1:
            # Single symbol returns dict directly
            try:
                result[symbols[0]] = float(data.get("price", ""))
            except (TypeError, ValueError):
                result[symbols[0]] = None
        else:
            # Multiple symbols return {symbol: {price: ...}, ...}
            for sym in symbols:
                try:
                    result[sym] = float(data.get(sym, {}).get("price", ""))
                except (TypeError, ValueError):
                    result[sym] = None
        return result
    except Exception:
        return {s: None for s in symbols}


def resolve_uae_symbol(base_ticker: str) -> Optional[str]:
    """
    Given a bare ticker (e.g. "EMAAR", "ADCB"), find its Twelve Data symbol.
    Tries DFM (Dubai) first, then XADS (Abu Dhabi).
    Returns the working symbol string (e.g. "EMAAR:DFM") or None.
    """
    for exchange in UAE_EXCHANGES:
        candidate = f"{base_ticker}:{exchange}"
        price = get_price(candidate)
        if price is not None and price > 0:
            return candidate
    return None


def is_configured() -> bool:
    """Check if Twelve Data API key is available."""
    return bool(_api_key())
