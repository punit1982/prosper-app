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


def _fetch_finnhub_analyst(ticker: str) -> str:
    """
    Fetch analyst consensus + recent upgrades/downgrades from Finnhub and
    format them as a context string for an analysis prompt. Returns "" if
    Finnhub has no coverage (common for non-US names) or on any failure.

    Moved here from core/prosper_analysis.py (retired PROSPER v3.0 engine);
    core/grow_engine.py is the only caller.
    """
    try:
        from datetime import datetime
        from core.data_engine import get_finnhub_analyst_data
        data = get_finnhub_analyst_data(ticker)
        if not data:
            return ""

        lines = []
        # Recommendation trends (latest month)
        recs = data.get("recommendations", [])
        if recs:
            latest = recs[0]  # Most recent month
            buy = latest.get("buy", 0) + latest.get("strongBuy", 0)
            hold = latest.get("hold", 0)
            sell = latest.get("sell", 0) + latest.get("strongSell", 0)
            total = buy + hold + sell
            period = latest.get("period", "")
            if total > 0:
                lines.append(f"Finnhub Analyst Consensus ({period}): {buy} Buy, {hold} Hold, {sell} Sell (n={total})")
                # Show trend if we have 3+ months
                if len(recs) >= 3:
                    prev = recs[2]
                    prev_buy = prev.get("buy", 0) + prev.get("strongBuy", 0)
                    if prev_buy > 0:
                        trend = "improving" if buy > prev_buy else "declining" if buy < prev_buy else "stable"
                        lines.append(f"Buy Rating Trend (3mo): {trend} ({prev_buy} → {buy})")

        # Upgrade/downgrade history
        upgrades = data.get("upgrades", [])
        if upgrades:
            recent = upgrades[:5]
            ud_lines = []
            for ud in recent:
                action = ud.get("action", "")
                firm = ud.get("company", "Unknown")
                from_grade = ud.get("fromGrade", "")
                to_grade = ud.get("toGrade", "")
                date = ud.get("gradeTime", "")
                if isinstance(date, (int, float)) and date > 0:
                    date = datetime.fromtimestamp(date).strftime("%Y-%m-%d")
                if action and to_grade:
                    ud_lines.append(f"  {date}: {firm} {action} → {to_grade}" +
                                    (f" (from {from_grade})" if from_grade else ""))
            if ud_lines:
                lines.append("Recent Analyst Actions:\n" + "\n".join(ud_lines))

        return "\n".join(lines)
    except Exception:
        return ""


# ─── Fundamentals ───────────────────────────────────────────────────────────

def basic_financials(symbol: str) -> Dict:
    """Fetch Finnhub 'basic financials' (metric=all) and reshape the pieces
    Prosper uses into yfinance `.info` key names. Returns {} on any failure or
    if Finnhub has no coverage for the symbol (common for non-US). Used as the
    last fundamentals fallback after yfinance and FMP."""
    client = get_client()
    if not client:
        return {}
    _rate_limit()
    try:
        raw = client.company_basic_financials(symbol, "all") or {}
    except Exception:
        return {}
    m = raw.get("metric") or {}
    if not m:
        return {}

    def _f(*names, scale=1.0):
        for n in names:
            v = m.get(n)
            if v is not None:
                try:
                    return float(v) * scale
                except (TypeError, ValueError):
                    continue
        return None

    # Finnhub reports ratios as percentages (roeTTM = 137.18) and D/E as a
    # bare ratio (1.5). yfinance's .info convention — which every downstream
    # caller assumes — is: ROE / margins / yield / growth as FRACTIONS
    # (0.15), and debtToEquity as ratio×100 (150). Convert here so a Finnhub
    # fallback value renders identically to a yfinance one.
    info = {
        "trailingPE":       _f("peTTM", "peBasicExclExtraTTM", "peInclExtraTTM"),
        "forwardPE":        _f("forwardPE"),
        "priceToBook":      _f("pbAnnual", "pbQuarterly"),
        "returnOnEquity":   _f("roeTTM", "roeRfy", scale=0.01),
        "profitMargins":    _f("netProfitMarginTTM", "netProfitMarginAnnual", scale=0.01),
        "debtToEquity":     _f("totalDebt/totalEquityAnnual", "totalDebt/totalEquityQuarterly", scale=100.0),
        "dividendYield":    _f("dividendYieldIndicatedAnnual", "currentDividendYieldTTM", scale=0.01),
        "revenueGrowth":    _f("revenueGrowthTTMYoy", "revenueGrowth5Y", scale=0.01),
        "trailingEps":      _f("epsTTM", "epsBasicExclExtraItemsTTM"),
        "beta":             _f("beta"),
        "fiftyTwoWeekHigh": _f("52WeekHigh"),
        "fiftyTwoWeekLow":  _f("52WeekLow"),
        "_source":          "finnhub",
    }
    info = {k: v for k, v in info.items() if v is not None}
    return info if len([k for k in info if k != "_source"]) >= 2 else {}


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
