"""
Finnhub Client
==============
Secondary data source for tickers that yfinance cannot cover.
Free tier: 60 API calls/minute.

Provides: quotes, news, analyst upgrades/downgrades, insider transactions,
institutional ownership.  Falls back gracefully if no API key is configured.
"""

import os
import time
import threading
from typing import Dict, List, Optional

_client = None
_lock = threading.Lock()
_call_timestamps: List[float] = []
RATE_LIMIT = 55  # stay slightly under 60 to be safe


def get_client():
    """Lazy singleton Finnhub client."""
    global _client
    if _client is None:
        from core.settings import get_api_key
        key = get_api_key("FINNHUB_API_KEY")
        if not key:
            return None
        import finnhub
        _client = finnhub.Client(api_key=key)
    return _client


def _rate_limit():
    """Enforce rate limit (55 calls/min)."""
    with _lock:
        now = time.time()
        _call_timestamps[:] = [t for t in _call_timestamps if now - t < 60]
        if len(_call_timestamps) >= RATE_LIMIT:
            sleep_time = 60 - (now - _call_timestamps[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
        _call_timestamps.append(time.time())


# ─── Quotes ─────────────────────────────────────────────────────────────────

def quote(symbol: str) -> Dict:
    """Fetch a real-time quote. Returns dict with 'c' (current), 'pc' (prev close), etc."""
    client = get_client()
    if not client:
        return {}
    _rate_limit()
    try:
        return client.quote(symbol)
    except Exception:
        return {}


# ─── News ────────────────────────────────────────────────────────────────────

def company_news(symbol: str, from_date: str, to_date: str) -> List[Dict]:
    """Fetch company-specific news for a date range."""
    client = get_client()
    if not client:
        return []
    _rate_limit()
    try:
        return client.company_news(symbol, _from=from_date, to=to_date)
    except Exception:
        return []


def general_news(category: str = "general") -> List[Dict]:
    """Fetch general market news. Categories: general, forex, crypto, merger."""
    client = get_client()
    if not client:
        return []
    _rate_limit()
    try:
        return client.general_news(category)
    except Exception:
        return []


# ─── Analyst ─────────────────────────────────────────────────────────────────

def upgrade_downgrade(symbol: str) -> List[Dict]:
    """Fetch analyst upgrade/downgrade history."""
    client = get_client()
    if not client:
        return []
    _rate_limit()
    try:
        return client.upgrade_downgrade(symbol=symbol)
    except Exception:
        return []


def recommendation_trends(symbol: str) -> List[Dict]:
    """Fetch analyst recommendation trends."""
    client = get_client()
    if not client:
        return []
    _rate_limit()
    try:
        return client.recommendation_trends(symbol)
    except Exception:
        return []


# ─── Insider ─────────────────────────────────────────────────────────────────

def insider_transactions(symbol: str) -> Dict:
    """Fetch insider transactions for a symbol."""
    client = get_client()
    if not client:
        return {}
    _rate_limit()
    try:
        return client.stock_insider_transactions(symbol)
    except Exception:
        return {}


# ─── Institutional ──────────────────────────────────────────────────────────

def institutional_ownership(symbol: str) -> List[Dict]:
    """Fetch institutional ownership data."""
    client = get_client()
    if not client:
        return []
    _rate_limit()
    try:
        return client.institutional_ownership(symbol)
    except Exception:
        return []


def is_configured() -> bool:
    """Check if Finnhub API key is available."""
    from core.settings import get_api_key
    return bool(get_api_key("FINNHUB_API_KEY"))
