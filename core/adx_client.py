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
# Mubasher covers both UAE exchanges under separate market-path segments —
# confirmed live: /markets/ADX/stocks/{slug} and /markets/DFM/stocks/{slug}
# both return a real stock page. A ".AE" ticker could be either exchange, so
# get_fundamentals() tries both rather than assuming ADX.
_UAE_MUBASHER_MARKETS = ["ADX", "DFM"]

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


# ─── Fundamentals (Market Cap, P/E, P/B, EPS) ───────────────────────────────
# yfinance's .info returns NOTHING for ADX/DFM tickers — confirmed via
# production logs as a real "Quote not found" 404, not just thin coverage —
# and no free tier of Twelve Data/FMP/Finnhub covers UAE fundamentals either
# (all three gate it behind a paid plan; verified live, September 2026).
# Mubasher's own stock page renders these numbers directly in static HTML
# (no auth, no JS execution needed) — this is the one free source that
# actually has them.
_STAT_PATTERN = re.compile(
    r'stock-overview__text">([^<]+)</span>\s*'
    r'<span class="stock-overview__value[^"]*">\s*'
    r'<span class="number[^"]*">([^<]+)</span>',
    re.S,
)
# Mubasher's own label -> the yfinance .info key name it corresponds to, so
# the result merges into the same downstream path as a normal yfinance fetch.
_STAT_LABEL_MAP = {
    "Market Cap":        "marketCap",
    "P/E Ratio":         "trailingPE",
    "P/B Ratio":         "priceToBook",
    "EPS":               "trailingEps",
    "Book Value (BVPS)": "bookValue",
}
_FUNDAMENTALS_CACHE_TTL = 6 * 3600  # 6 hours — these don't move intraday
_fundamentals_cache: Dict[str, Tuple[dict, float]] = {}

# Mubasher's slug is not always the bare ticker. Map the normalised symbol
# (uppercase, no exchange suffix) -> the exact slug in the Mubasher URL.
_MUBASHER_SLUG_OVERRIDES: Dict[str, str] = {
    "PUREHEALT":  "PUREHEALTH",
    "ADNOCDRILL": "ADNOCDRILL",
    "ADNOCDRIL":  "ADNOCDRILL",
    "EMIRATESN":  "EMIRATESNBD",
    "EMIRATESNBD": "EMIRATESNBD",
    "EMAARDEV":   "EMAARDEV",
    "EMAAR":      "EMAAR",
    "TECOM":      "TECOM",
    "ALDAR":      "ALDAR",
    "ADCB":       "ADCB",
    "BURJEEL":    "BURJEEL",
}


def _normalise_uae_symbol(ticker: str) -> str:
    """Strip every UAE exchange marker Prosper might store a ticker with —
    '.AE' / '.AD' / '.DU' suffixes and Twelve Data ':DFM' / ':ADX' forms —
    and upper-case, so downstream slug lookup has one clean key."""
    t = (ticker or "").upper().strip()
    for suf in (".AE", ".AD", ".DU"):
        if t.endswith(suf):
            t = t[: -len(suf)]
    if ":" in t:
        t = t.split(":", 1)[0]
    return t


def is_uae_symbol(ticker: str) -> bool:
    """True for anything that looks like a UAE listing in any of the forms
    Prosper stores (suffix, Twelve Data colon form, or a known slug)."""
    t = (ticker or "").upper()
    if t.endswith((".AE", ".AD", ".DU")) or ":DFM" in t or ":ADX" in t:
        return True
    norm = _normalise_uae_symbol(t)
    return norm in _MUBASHER_SLUG_OVERRIDES or (norm + ".AE") in ADX_CHART_IDS


def get_fundamentals(ticker: str) -> Optional[Dict]:
    """
    Scrape basic fundamentals from the stock's own Mubasher page.

    Returns a dict keyed exactly like yfinance's .info (marketCap, trailingPE,
    priceToBook, trailingEps, bookValue, currency, quoteType) so callers can
    treat it as a drop-in substitute — see core/data_engine.py get_ticker_info().
    None if the page has no recognizable stats (e.g. this ADX/DFM slug is a
    fund, not a company) or the request fails.
    """
    now = time.time()
    cached = _fundamentals_cache.get(ticker)
    if cached and (now - cached[1]) < _FUNDAMENTALS_CACHE_TTL:
        return cached[0]

    # Normalise whatever form the ticker was stored in (ADCB / ADCB.AE /
    # ADCB.AD / ADCB:DFM) down to one key, then map to Mubasher's slug:
    # explicit override → curated slug in ADX_CHART_IDS → the bare symbol.
    norm = _normalise_uae_symbol(ticker)
    _known = ADX_CHART_IDS.get(ticker) or ADX_CHART_IDS.get(norm + ".AE")
    slug = _MUBASHER_SLUG_OVERRIDES.get(norm) or (_known[0] if _known else norm)
    for market in _UAE_MUBASHER_MARKETS:
        url = f"https://english.mubasher.info/markets/{market}/stocks/{slug}"
        try:
            r = _SESSION.get(url, timeout=12)
            if r.status_code != 200:
                continue
            result: Dict = {}
            for label, raw_value in _STAT_PATTERN.findall(r.text):
                key = _STAT_LABEL_MAP.get(label.strip())
                if not key:
                    continue
                try:
                    result[key] = float(raw_value.strip().replace(",", ""))
                except ValueError:
                    continue
            if not result:
                continue
            result["currency"] = "AED"
            result["quoteType"] = "EQUITY"
            _fundamentals_cache[ticker] = (result, now)
            return result
        except Exception:
            continue
    return None


def is_adx_ticker(ticker: str) -> bool:
    """Return True if this ticker is in the ADX static map."""
    return ticker in ADX_CHART_IDS


def get_all_tickers() -> List[str]:
    """Return all ADX tickers supported by this client."""
    return list(ADX_CHART_IDS.keys())
