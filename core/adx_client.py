"""
ADX Client (Abu Dhabi Securities Exchange)
==========================================
Fetches live and historical prices for ADX-listed stocks via Mubasher's
publicly accessible intraday CSV files.

How it works:
  1. The Mubasher website (english.mubasher.info) renders stock pages for
     every ADX-listed stock. Each stock has a permanent chart ID embedded in
     the page HTML.
  2. Mubasher exposes the raw intraday OHLCV data as plain CSV files at:
       https://english.mubasher.info/mubasherFileServer/File.MubasherCharts/
         File.Delay_Stock_Intraday_Charts_Dir/{chart_id}.csv
  3. Historical daily data is available at:
       https://static.mubasher.info/File.MubasherCharts/
         File.Historical_Stock_Charts_Dir/{chart_id}.csv
  4. Both URLs return real-time / end-of-day data with no authentication.

Chart IDs were discovered by scraping each stock's Mubasher page once and
are stored here as a static map. They are stable (permanent per security).

CSV format:  datetime, open, high, low, close, volume
"""

import re
import time
import threading
import requests
from typing import Dict, List, Optional, Tuple

# ─── Static chart ID map ─────────────────────────────────────────────────────
# Format: {yfinance_ticker: (mubasher_slug, chart_id)}
# chart_id is used in both intraday and historical CSV URLs.
ADX_CHART_IDS: Dict[str, Tuple[str, str]] = {
    "ADCB.AE":       ("ADCB",       "3951543843a4723ed2ab08e18053ae6dc5b"),
    "ADNOCDRILL.AE": ("ADNOCDRILL", "1397970b01b28a4e30ca9a5e2b7134e22c77087"),
    "ADNOCLS.AE":    ("ADNOCLS",    "13986871934abb91bce4f962ca178e2b40fe210"),
    "ADPORTS.AE":    ("ADPORTS",    "139801459a226fe4aa397b5c65544fabf118802"),
    "BOROUGE.AE":    ("BOROUGE",    "1398369124d06557e8e4b13fb28d0e8aa773dd5"),
    "PUREHEALT.AE":  ("PUREHEALTH", "13988923147f9842d701d7b7a5c464257d4e35c"),
    "SPACE42.AE":    ("SPACE42",    "13984481df68259d264074211d14683a31c931d"),
}

INTRADAY_BASE = (
    "https://english.mubasher.info/mubasherFileServer/File.MubasherCharts"
    "/File.Delay_Stock_Intraday_Charts_Dir"
)
HISTORY_BASE = (
    "https://static.mubasher.info/File.MubasherCharts"
    "/File.Historical_Stock_Charts_Dir"
)
MUBASHER_STOCK_BASE = "https://english.mubasher.info/markets/ADX/stocks"

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://english.mubasher.info/",
    "Accept": "text/plain, text/csv, */*",
})

# In-memory cache: {ticker: (price, prev_close, timestamp)}
_price_cache: Dict[str, Tuple[float, float, float]] = {}
_CACHE_TTL = 60   # 1 minute — intraday data refreshes every 5 minutes on Mubasher


def _parse_csv_last_row(csv_text: str) -> Optional[Tuple[float, float]]:
    """
    Parse the last and second-to-last rows of a CSV to get (close, prev_close).
    CSV format: datetime, open, high, low, close, volume
    Returns (close, prev_close) or None if unparseable.
    """
    lines = [l.strip() for l in csv_text.strip().split("\n") if l.strip()]
    if not lines:
        return None
    try:
        last_close = float(lines[-1].split(",")[4])
        prev_close = float(lines[-2].split(",")[4]) if len(lines) >= 2 else last_close
        return last_close, prev_close
    except (IndexError, ValueError):
        return None


def _fetch_chart_id(ticker: str) -> Optional[str]:
    """
    Discover the chart ID for an ADX ticker by loading its Mubasher stock page.
    Used only for tickers not yet in ADX_CHART_IDS.
    """
    # Derive slug: strip .AE suffix
    slug = ticker.upper().replace(".AE", "").replace(".AD", "")
    url = f"{MUBASHER_STOCK_BASE}/{slug}"
    try:
        r = _SESSION.get(url, timeout=12)
        if r.status_code != 200:
            return None
        ids = re.findall(
            r"File\.Delay_Stock_Intraday_Charts_Dir/([a-f0-9]+)\.csv", r.text
        )
        return ids[0] if ids else None
    except Exception:
        return None


def get_quote(ticker: str) -> Optional[Dict]:
    """
    Fetch the latest price for an ADX-listed ticker.
    Returns dict with: price, change, changesPercentage, source
    or None if unavailable.

    Uses a 1-minute in-memory cache to avoid hammering Mubasher.
    """
    now = time.time()

    # Serve from in-memory cache if fresh
    if ticker in _price_cache:
        price, prev_close, ts = _price_cache[ticker]
        if (now - ts) < _CACHE_TTL:
            change = round(price - prev_close, 6)
            change_pct = round((change / prev_close) * 100, 4) if prev_close else None
            return {
                "symbol": ticker,
                "price": price,
                "change": change,
                "changesPercentage": change_pct,
                "source": "mubasher",
            }

    # Look up chart ID — static map first, then live discovery
    info = ADX_CHART_IDS.get(ticker)
    if info:
        _, chart_id = info
    else:
        chart_id = _fetch_chart_id(ticker)
        if not chart_id:
            return None

    # Fetch intraday CSV (today's 5-min bars)
    url = f"{INTRADAY_BASE}/{chart_id}.csv"
    try:
        r = _SESSION.get(url, timeout=10)
        if r.status_code != 200 or not r.text.strip():
            return None
        result = _parse_csv_last_row(r.text)
        if result is None:
            return None
        price, prev_close = result
        if price <= 0:
            return None

        # Store in cache
        _price_cache[ticker] = (price, prev_close, now)

        change = round(price - prev_close, 6)
        change_pct = round((change / prev_close) * 100, 4) if prev_close else None
        return {
            "symbol": ticker,
            "price": price,
            "change": change,
            "changesPercentage": change_pct,
            "source": "mubasher",
        }
    except Exception:
        return None


def get_history_csv(ticker: str) -> Optional[str]:
    """
    Fetch raw historical daily OHLCV CSV for an ADX ticker.
    Returns CSV text (date, open, high, low, close, volume) or None.
    """
    info = ADX_CHART_IDS.get(ticker)
    if not info:
        return None
    _, chart_id = info
    url = f"{HISTORY_BASE}/{chart_id}.csv"
    try:
        r = _SESSION.get(url, timeout=15)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def is_adx_ticker(ticker: str) -> bool:
    """Return True if this ticker is in the ADX static map."""
    return ticker in ADX_CHART_IDS


def get_all_tickers() -> List[str]:
    """Return all ADX tickers supported by this client."""
    return list(ADX_CHART_IDS.keys())
