"""
FMP client (stable API)
=======================
Financial Modeling Prep, `/stable/*` endpoints. Used ONLY as a fundamentals
fallback when yfinance's `.info` comes back empty — which, per the reliability
audit, is most tickers most of the time in production.

Coverage on the current key (verified 2026-09-05): US listings only. Non-US
symbols (`RELIANCE.NS`, `EMAAR.AE`, …) return a "not available under your
current subscription" message, so this client returns `None` for them and the
caller falls through to the next source.

The legacy `/api/v3/*` endpoints are dead ("no longer supported") — do not add
calls to them here.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional

import requests

from core.settings import get_api_key

_log = logging.getLogger("prosper.fmp")
_BASE = "https://financialmodelingprep.com/stable"
_TIMEOUT = 5
_cache: Dict[str, tuple] = {}
_CACHE_TTL = 6 * 3600  # fundamentals don't move intraday

# A response body that starts with any of these is a plan/permission wall,
# not data — treat as "no coverage" and stop trying.
_WALL_MARKERS = ("Premium Query", "Special Endpoint", "Legacy Endpoint", "Error Message")


def is_configured() -> bool:
    return bool(get_api_key("FMP_API_KEY"))


def _get(path: str, params: dict) -> Optional[list]:
    key = get_api_key("FMP_API_KEY")
    if not key:
        return None
    params = {**params, "apikey": key}
    try:
        r = requests.get(f"{_BASE}/{path}", params=params, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        text = r.text.lstrip()
        if any(text.startswith(m) or f'"{m}' in text[:40] for m in _WALL_MARKERS):
            return None
        data = r.json()
        return data if isinstance(data, list) else None
    except Exception:
        return None


def get_fundamentals(ticker: str) -> Optional[Dict]:
    """Return a dict shaped like yfinance's `.info` (marketCap, trailingPE,
    priceToBook, returnOnEquity, profitMargins, …) or None if FMP has no
    coverage for this symbol on the current plan."""
    tkr = (ticker or "").upper().strip()
    if not tkr:
        return None

    now = time.time()
    hit = _cache.get(tkr)
    if hit and (now - hit[1]) < _CACHE_TTL:
        return hit[0] or None

    # First call doubles as a coverage probe: if the plan doesn't cover this
    # symbol (every non-US ticker on the current key), stop here rather than
    # firing two more doomed requests.
    km = _get("key-metrics-ttm", {"symbol": tkr})
    quote = _get("quote", {"symbol": tkr})
    if not km and not quote:
        _cache[tkr] = (None, now)
        return None
    ratios = _get("ratios-ttm", {"symbol": tkr}) or _get("ratios", {"symbol": tkr})

    m0 = (km or [{}])[0]
    r0 = (ratios or [{}])[0]
    q0 = (quote or [{}])[0]

    def _f(*vals):
        for v in vals:
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None

    info: Dict = {
        "marketCap":       _f(m0.get("marketCap"), q0.get("marketCap")),
        "trailingPE":      _f(q0.get("pe"), r0.get("priceToEarningsRatioTTM"), r0.get("priceEarningsRatioTTM")),
        "priceToBook":     _f(m0.get("pbRatioTTM"), r0.get("priceToBookRatioTTM"), r0.get("priceToBookRatio")),
        "enterpriseValue": _f(m0.get("enterpriseValueTTM")),
        "returnOnEquity":  _f(m0.get("returnOnEquityTTM"), r0.get("returnOnEquityTTM")),
        "profitMargins":   _f(r0.get("netProfitMarginTTM"), r0.get("netIncomePerShareTTM") and None),
        "debtToEquity":    _f(m0.get("debtToEquityTTM"), r0.get("debtEquityRatioTTM")),
        "dividendYield":   _f(m0.get("dividendYieldTTM"), r0.get("dividendYieldTTM")),
        "trailingEps":     _f(q0.get("eps")),
        "beta":            _f(q0.get("beta")),
        "fiftyTwoWeekHigh": _f(q0.get("yearHigh")),
        "fiftyTwoWeekLow":  _f(q0.get("yearLow")),
        "currency":        "USD",
        "quoteType":       "EQUITY",
        "_source":         "fmp",
    }
    info = {k: v for k, v in info.items() if v is not None}
    if len([k for k in info if k not in ("currency", "quoteType", "_source")]) < 2:
        _cache[tkr] = (None, now)
        return None
    _cache[tkr] = (info, now)
    return info
