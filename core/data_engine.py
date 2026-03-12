"""
Data Engine
===========
Central data hub for ALL Prosper pages.

Fetches and caches extended data from yfinance with automatic
ticker-suffix resolution for UAE, Swiss, Indian, and other non-US markets.

Data types:
  • Ticker info    — sector, industry, 52W H/L, Forward PE, market cap, growth, etc.
  • News           — aggregated from all portfolio tickers + market indices
  • Analyst        — recommendations, price targets, rating history
  • Insider        — insider transactions (buys/sells)
  • Institutional  — top holders and ownership breakdown
  • History        — OHLCV for performance charts and benchmarks

Caching strategy:
  All data is cached in st.session_state with per-type TTLs.
  This avoids redundant HTTP calls when the user switches pages.
"""

import time
import os
import json
import hashlib
import pandas as pd
import streamlit as st
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

# ─────────────────────────────────────────
# CACHE TTLs (seconds)
# ─────────────────────────────────────────
INFO_TTL     = 3600   # 1 hour — fundamentals rarely change intraday
NEWS_TTL     = 900    # 15 minutes — news is time-sensitive
ANALYST_TTL  = 3600   # 1 hour
INSIDER_TTL  = 3600   # 1 hour
INST_TTL     = 3600   # 1 hour
HISTORY_TTL  = 300    # 5 minutes — price history for charts

# ─────────────────────────────────────────
# TICKER OVERRIDE MAP
# ─────────────────────────────────────────
# Hard-coded corrections for tickers stored incorrectly or without exchange suffix.
# Applied BEFORE any resolution logic — instant lookup, no API calls.
# Format: {stored_ticker: correct_yfinance_ticker}
TICKER_OVERRIDES: Dict[str, str] = {
    # Emirates NBD stored without full name — correct Yahoo Finance ticker
    "EMIRATESN.AE":  "EMIRATESNBD.AE",
    # ETFs/funds stored without exchange suffix — correct tickers with suffix
    "JEPG":          "JEPG.L",    # JPM Global Equity Premium Income UCITS ETF (LSE, USD)
    "IEDY":          "IEDY.L",    # iShares EM Dividend UCITS ETF (LSE, USD)
    "GHYC":          "GHYC.SW",   # iShares Global High Yield Corp Bond CHF Hedged ETF (Swiss, CHF)
    "SREN":          "SREN.SW",   # Swiss Re AG (SIX Swiss Exchange, CHF)
    # Franklin Income Fund stored as internal fund code — correct US mutual fund ticker
    "I288654906":    "FKINX",     # Franklin Income Fund Class A1
}

# ─────────────────────────────────────────
# TICKER SUFFIX RESOLUTION
# ─────────────────────────────────────────
# When a ticker has no exchange suffix and can't be found on Yahoo Finance,
# try these suffixes based on the stored currency.
SUFFIX_MAP = {
    "AED": [".AE", ".AD"],
    "INR": [".NS", ".BO"],
    "CHF": [".SW"],
    "GBP": [".L"],
    "EUR": [".PA", ".DE", ".AS", ".MI", ".MC"],
    "HKD": [".HK"],
    "SGD": [".SI"],
    "JPY": [".T"],
    "AUD": [".AX"],
    "CAD": [".TO"],
    "CNY": [".SS", ".SZ"],
    "KRW": [".KS"],
    "BRL": [".SA"],
    "ZAR": [".JO"],
    "ILS": [".TA"],
}

# Standard benchmark indices
BENCHMARKS = {
    "S&P 500":     "^GSPC",
    "Nasdaq 100":  "^NDX",
    "Nifty 50":    "^NSEI",
    "Sensex":      "^BSESN",
    "FTSE 100":    "^FTSE",
    "DAX":         "^GDAXI",
    "Hang Seng":   "^HSI",
    "Nikkei 225":  "^N225",
}


# ─────────────────────────────────────────
# SESSION-STATE CACHE HELPERS
# ─────────────────────────────────────────
def _cache_get(key: str, ttl: int) -> Optional[Any]:
    entry = st.session_state.get(f"_de_{key}")
    if entry and (time.time() - entry["ts"]) < ttl:
        return entry["data"]
    return None

def _cache_set(key: str, data: Any):
    st.session_state[f"_de_{key}"] = {"data": data, "ts": time.time()}


# ─────────────────────────────────────────
# TICKER RESOLUTION
# ─────────────────────────────────────────
def _try_yfinance(symbol: str) -> bool:
    """Check if a symbol has a valid price on yfinance."""
    import yfinance as yf
    try:
        return yf.Ticker(symbol).fast_info.last_price is not None
    except Exception:
        return False


def _try_finnhub(symbol: str) -> bool:
    """Check if a symbol has a valid price on Finnhub."""
    from core.finnhub_client import quote as fh_quote
    fh = fh_quote(symbol)
    return bool(fh and fh.get("c", 0) > 0)


def _try_twelve_data_uae(base_ticker: str) -> Optional[str]:
    """
    Try to resolve a UAE ticker via Twelve Data (DFM / XADS exchanges).
    base_ticker: symbol without .AE suffix (e.g. "EMAAR", "ADCB").
    Returns the resolved Twelve Data symbol (e.g. "EMAAR:DFM") or None.
    """
    try:
        from core.twelve_data_client import resolve_uae_symbol, is_configured
        if not is_configured():
            return None
        return resolve_uae_symbol(base_ticker)
    except Exception:
        return None


def resolve_ticker(ticker: str, currency: str = "USD") -> str:
    """
    Resolve a ticker that may be missing its exchange suffix.

    Multi-source cascade:
    1. If ticker already has a suffix (.NS, .AE, etc.) → try yfinance, then Twelve Data (UAE), then Finnhub
    2. Try the bare ticker on Yahoo Finance
    3. Try common suffixes for the given currency on Yahoo Finance
    4. For AED currency / .AE tickers → try Twelve Data (DFM / XADS)
    5. Try bare ticker on Finnhub (if API key configured)
    6. Cache the resolved ticker for 24 hours

    Returns the working ticker symbol, or the original if nothing works.
    """
    if not ticker or len(ticker) < 1:
        return ticker

    # ── Ticker override map — apply before any API call ──────────────────────
    # Corrects tickers stored with wrong/missing exchange suffixes.
    if ticker in TICKER_OVERRIDES:
        resolved = TICKER_OVERRIDES[ticker]
        _cache_set(f"resolved_{ticker}", resolved)
        return resolved

    # ── ADX tickers — resolve immediately, skip yfinance probing (it hangs) ──
    # Prices come from Mubasher (adx_client), not yfinance.
    try:
        from core.adx_client import is_adx_ticker
        if is_adx_ticker(ticker):
            _cache_set(f"resolved_{ticker}", ticker)
            return ticker
    except Exception:
        pass

    # Check resolution cache (24h TTL)
    cached = _cache_get(f"resolved_{ticker}", 86400)
    if cached is not None:
        return cached

    # ── Detect UAE tickers ────────────────────────────────────────────────────
    is_uae = ticker.endswith(".AE") or currency in ("AED", "aed")
    base_ticker = ticker[:-3] if ticker.endswith(".AE") else ticker
    # Also strip Twelve Data format (e.g. "EMAAR:DFM") in case already resolved
    if ":" in base_ticker:
        base_ticker = base_ticker.split(":")[0]

    # Already has a suffix → try sources in order
    if "." in ticker[1:]:
        if _try_yfinance(ticker):
            _cache_set(f"resolved_{ticker}", ticker)
            return ticker
        # For .AE tickers, try Twelve Data before Finnhub
        if is_uae:
            td_sym = _try_twelve_data_uae(base_ticker)
            if td_sym:
                _cache_set(f"resolved_{ticker}", td_sym)
                _cache_set(f"source_{ticker}", "twelvedata")
                return td_sym
        if _try_finnhub(ticker):
            _cache_set(f"resolved_{ticker}", ticker)
            _cache_set(f"source_{ticker}", "finnhub")
            return ticker
        _cache_set(f"resolved_{ticker}", ticker)
        return ticker

    # Try bare ticker on yfinance
    if _try_yfinance(ticker):
        _cache_set(f"resolved_{ticker}", ticker)
        return ticker

    # Try suffixes based on currency
    from core.currency_normalizer import normalise_currency
    norm_currency = normalise_currency(currency)
    suffixes = SUFFIX_MAP.get(norm_currency, [])

    for suffix in suffixes:
        candidate = f"{ticker}{suffix}"
        if _try_yfinance(candidate):
            _cache_set(f"resolved_{ticker}", candidate)
            return candidate

    # For AED currency, try Twelve Data (DFM / XADS)
    if is_uae:
        td_sym = _try_twelve_data_uae(base_ticker)
        if td_sym:
            _cache_set(f"resolved_{ticker}", td_sym)
            _cache_set(f"source_{ticker}", "twelvedata")
            return td_sym

    # Try bare ticker on Finnhub (secondary source)
    if _try_finnhub(ticker):
        _cache_set(f"resolved_{ticker}", ticker)
        _cache_set(f"source_{ticker}", "finnhub")
        return ticker

    # Nothing worked — return original
    _cache_set(f"resolved_{ticker}", ticker)
    return ticker


def resolve_tickers_batch(tickers_with_currency: List[Tuple[str, str]]) -> Dict[str, str]:
    """
    Resolve multiple tickers in parallel.
    Checks SQLite ticker_cache first (24h TTL) — eliminates yfinance pings on repeat sessions.
    Input: [(ticker, currency), ...]
    Returns: {original_ticker: resolved_ticker, ...}
    """
    from core.database import get_ticker_resolution_cache, save_ticker_resolution_cache

    all_tickers = [t for t, _ in tickers_with_currency]
    result = {}
    items_to_resolve = []

    # Layer 0: Hard-coded overrides (instant, no API calls)
    for ticker, currency in tickers_with_currency:
        if ticker in TICKER_OVERRIDES:
            result[ticker] = TICKER_OVERRIDES[ticker]

    remaining = [(t, c) for t, c in tickers_with_currency if t not in result]
    remaining_tickers = [t for t, _ in remaining]

    # Layer 1: SQLite cache (24h — survives browser restarts)
    sqlite_resolved = get_ticker_resolution_cache(remaining_tickers)

    for ticker, currency in remaining:
        if ticker in sqlite_resolved:
            result[ticker] = sqlite_resolved[ticker]
            _cache_set(f"resolved_{ticker}", sqlite_resolved[ticker])  # warm session_state too
        elif (cached := _cache_get(f"resolved_{ticker}", 86400)) is not None:
            result[ticker] = cached
        else:
            items_to_resolve.append((ticker, currency))

    if items_to_resolve:
        pool = ThreadPoolExecutor(max_workers=min(len(items_to_resolve), 10))
        try:
            futures = {
                pool.submit(resolve_ticker, t, c): t
                for t, c in items_to_resolve
            }
            try:
                for f in as_completed(futures, timeout=30):
                    orig = futures[f]
                    try:
                        result[orig] = f.result(timeout=10)
                    except Exception:
                        result[orig] = orig
            except Exception:
                # Timeout — fill unresolved with original tickers
                for t, _ in items_to_resolve:
                    if t not in result:
                        result[t] = t
        finally:
            pool.shutdown(wait=False)

        # Save newly resolved tickers to SQLite for next session
        new_resolutions = {t: result[t] for t, _ in items_to_resolve if t in result}
        save_ticker_resolution_cache(new_resolutions)

    return result


# ─────────────────────────────────────────
# TICKER INFO (fundamentals)
# ─────────────────────────────────────────
def get_ticker_info(ticker: str) -> Dict:
    """
    Fetch comprehensive ticker info from yfinance (cached 1h).

    Returns a dict with keys like:
      sector, industry, country, city, marketCap, enterpriseValue,
      trailingPE, forwardPE, fiftyTwoWeekHigh, fiftyTwoWeekLow,
      targetMeanPrice, recommendationKey, revenueGrowth, earningsGrowth,
      profitMargins, ebitda, totalRevenue, trailingEps, forwardEps,
      returnOnEquity, debtToEquity, dividendYield, beta, etc.
    """
    cached = _cache_get(f"info_{ticker}", INFO_TTL)
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        _cache_set(f"info_{ticker}", info)
        return info
    except Exception:
        return {}


def get_ticker_info_batch(tickers: List[str]) -> Dict[str, Dict]:
    """Fetch info for all tickers in parallel (max 10 workers, 60s total timeout)."""
    results = {}
    if not tickers:
        return results
    max_w = min(len(tickers), 10)
    pool = ThreadPoolExecutor(max_workers=max_w)
    try:
        futures = {pool.submit(get_ticker_info, t): t for t in tickers}
        try:
            for f in as_completed(futures, timeout=60):
                t = futures[f]
                try:
                    results[t] = f.result(timeout=10)
                except Exception:
                    results[t] = {}
        except Exception:
            # Timeout — fill remaining with empty
            for t in tickers:
                if t not in results:
                    results[t] = {}
    finally:
        pool.shutdown(wait=False)
    return results


# ─────────────────────────────────────────
# NEWS
# ─────────────────────────────────────────
def _fetch_news_search_api(ticker: str) -> List[Dict]:
    """
    Yahoo Finance search API — fallback for non-US tickers (UAE, etc.)
    where the RSS feed returns no articles. Uses requests with 5s timeout.
    """
    import requests
    try:
        resp = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={"q": ticker, "newsCount": 20, "quotesCount": 0, "lang": "en-US", "region": "US"},
            timeout=5,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Prosper/1.0)"},
        )
        data = resp.json()
        return [
            {
                "title":               n.get("title", ""),
                "link":                n.get("link", ""),
                "publisher":           n.get("publisher", "Yahoo Finance"),
                "providerPublishTime": n.get("providerPublishTime", 0),
            }
            for n in data.get("news", [])
            if n.get("title")
        ]
    except Exception:
        return []


def _fetch_news_rss(ticker: str) -> List[Dict]:
    """
    Fetch news via Yahoo Finance RSS feed using requests with a hard 5s timeout.
    This is a genuine network-level timeout — it cannot hang.
    Returns [] on any error (timeout, bad ticker, network issue).
    """
    import requests
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    # URL-encode the ticker (^ in index tickers needs encoding)
    from urllib.parse import quote
    url = (
        f"https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={quote(ticker)}&region=US&lang=en-US"
    )
    try:
        resp = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        items = []
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "").strip()
            pub   = item.findtext("pubDate", "")
            ts = 0
            try:
                ts = int(parsedate_to_datetime(pub).timestamp()) if pub else 0
            except Exception:
                pass
            if title:
                items.append({
                    "title": title,
                    "link": link,
                    "publisher": "Yahoo Finance",
                    "providerPublishTime": ts,
                })
        # Fallback to search API for non-US tickers (UAE, etc.) when RSS returns nothing
        if not items:
            return _fetch_news_search_api(ticker)
        return items
    except Exception:
        return []


def get_ticker_news(ticker: str) -> List[Dict]:
    """
    Fetch news for one ticker via RSS (5s real HTTP timeout — never hangs).
    Falls back to Finnhub if configured.
    Cached 15 min in session_state.
    """
    cached = _cache_get(f"news_{ticker}", NEWS_TTL)
    if cached is not None:
        return cached

    all_news = _fetch_news_rss(ticker)   # real timeout, always returns

    # Finnhub fallback (free tier returns data for US stocks)
    try:
        import requests as _req
        from core.finnhub_client import company_news as fh_company_news
        today    = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        fh_items = fh_company_news(ticker, week_ago, today) or []
        for item in fh_items:
            all_news.append({
                "title":               item.get("headline", ""),
                "publisher":           item.get("source", ""),
                "link":                item.get("url", ""),
                "providerPublishTime": item.get("datetime", 0),
            })
    except Exception:
        pass

    # Deduplicate by title
    seen, unique = set(), []
    for item in sorted(all_news, key=lambda x: x.get("providerPublishTime", 0), reverse=True):
        t = item.get("title", "")
        if t and t not in seen:
            seen.add(t)
            unique.append(item)

    _cache_set(f"news_{ticker}", unique)
    return unique


def get_portfolio_news(tickers: List[str], limit: int = 50) -> List[Dict]:
    """
    Aggregate news from portfolio tickers, sorted by date (newest first).

    Caching (two-tier):
      1. SQLite (1-hour TTL) — survives server restarts and new browser sessions
      2. session_state (15-min TTL) — fastest within the same browser session

    Each ticker fetch has a hard 5s HTTP timeout, so this can never hang forever.
    """
    if not tickers:
        return []

    from core.database import get_news_cache, save_news_cache

    # Short, stable SQLite cache key from sorted ticker hash
    ticker_hash = hashlib.md5(",".join(sorted(tickers)).encode()).hexdigest()[:12]
    sqlite_key  = f"pnews_{ticker_hash}"
    ss_key      = f"portfolio_news_{ticker_hash}"

    # Layer 1: SQLite cache (1-hour TTL — survives restarts)
    sqlite_cached = get_news_cache(sqlite_key)
    if sqlite_cached is not None:
        return sqlite_cached[:limit]

    # Layer 2: session_state cache (15-min TTL within session)
    cached = _cache_get(ss_key, NEWS_TTL)
    if cached is not None:
        return cached[:limit]

    # Fetch fresh — each get_ticker_news() is bounded by 5s HTTP timeout,
    # so we don't need a tight outer timeout. Use shutdown(wait=False) to
    # avoid hanging on executor cleanup.
    all_news = []
    pool = ThreadPoolExecutor(max_workers=min(len(tickers), 6))
    futures = {pool.submit(get_ticker_news, t): t for t in tickers}
    try:
        for f in as_completed(futures, timeout=45):
            ticker_done = futures[f]
            try:
                items = f.result()
                for item in items:
                    item["related_ticker"] = ticker_done
                    all_news.append(item)
            except Exception:
                pass
    except Exception:
        pass   # TimeoutError or other — return whatever collected so far
    finally:
        pool.shutdown(wait=False)   # don't block on any remaining stragglers

    # Sort by publish time (newest first), deduplicate by title
    seen_titles = set()
    unique_news = []
    for item in sorted(all_news, key=lambda x: x.get("providerPublishTime", 0), reverse=True):
        title = item.get("title", "")
        if title not in seen_titles:
            seen_titles.add(title)
            unique_news.append(item)

    # Persist to both cache layers
    save_news_cache(sqlite_key, unique_news)
    _cache_set(ss_key, unique_news)
    return unique_news[:limit]


def get_market_news() -> List[Dict]:
    """Fetch news for major market indices from yfinance + Finnhub general news."""
    market_tickers = ["^GSPC", "^NDX", "^DJI", "^NSEI", "^BSESN", "^FTSE"]
    yf_news = get_portfolio_news(market_tickers, limit=30)

    # Add Finnhub general news
    try:
        from core.finnhub_client import general_news as fh_general
        fh_items = fh_general("general")
        for item in (fh_items or [])[:20]:
            yf_news.append({
                "title": item.get("headline", ""),
                "publisher": item.get("source", ""),
                "link": item.get("url", ""),
                "providerPublishTime": item.get("datetime", 0),
                "related_ticker": "Market",
            })
    except Exception:
        pass

    # Deduplicate
    seen = set()
    unique = []
    for item in sorted(yf_news, key=lambda x: x.get("providerPublishTime", 0), reverse=True):
        title = item.get("title", "")
        if title and title not in seen:
            seen.add(title)
            unique.append(item)

    return unique[:50]


# ─────────────────────────────────────────
# AI NEWS SUMMARY
# ─────────────────────────────────────────
def summarize_news_with_ai(title: str, publisher: str, ticker: str, ticker_name: str = "") -> str:
    """
    Use Claude to generate a concise AI analysis of a news headline.
    Uses claude-sonnet for speed + cost efficiency.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key == "your_anthropic_api_key_here":
        return "AI summary unavailable — Anthropic API key not configured."

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""You are a CIO-level financial analyst. Analyze this news headline and provide a brief, actionable summary.

Headline: "{title}"
Publisher: {publisher}
Related stock: {ticker} ({ticker_name})

In 2-3 sentences:
1. What does this news mean for the stock/company?
2. Is this likely positive, negative, or neutral for investors?
3. Any key risk or opportunity to watch?

Be concise and professional. No disclaimers."""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        return f"Summary unavailable: {str(e)[:100]}"


# ─────────────────────────────────────────
# ANALYST DATA
# ─────────────────────────────────────────
def get_analyst_recommendations(ticker: str) -> pd.DataFrame:
    """Fetch analyst recommendation history (cached 1h)."""
    cached = _cache_get(f"analyst_rec_{ticker}", ANALYST_TTL)
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        recs = yf.Ticker(ticker).recommendations
        if recs is not None and not recs.empty:
            _cache_set(f"analyst_rec_{ticker}", recs)
            return recs
    except Exception:
        pass
    empty = pd.DataFrame()
    _cache_set(f"analyst_rec_{ticker}", empty)
    return empty


def get_analyst_price_targets(ticker: str) -> Dict:
    """Fetch analyst price targets: current, low, high, mean, median."""
    cached = _cache_get(f"analyst_pt_{ticker}", ANALYST_TTL)
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        targets = {}
        # Try .analyst_price_targets attribute
        try:
            apt = t.analyst_price_targets
            if apt is not None:
                if isinstance(apt, dict):
                    targets = apt
                elif isinstance(apt, pd.DataFrame) and not apt.empty:
                    targets = apt.to_dict()
        except Exception:
            pass

        # Fallback: get from .info
        if not targets:
            info = get_ticker_info(ticker)
            targets = {
                "current": info.get("currentPrice"),
                "low":     info.get("targetLowPrice"),
                "high":    info.get("targetHighPrice"),
                "mean":    info.get("targetMeanPrice"),
                "median":  info.get("targetMedianPrice"),
            }

        _cache_set(f"analyst_pt_{ticker}", targets)
        return targets
    except Exception:
        return {}


def get_recommendations_summary(ticker: str) -> Dict:
    """Fetch Buy/Hold/Sell summary counts."""
    cached = _cache_get(f"rec_summary_{ticker}", ANALYST_TTL)
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        summary = yf.Ticker(ticker).recommendations_summary
        if summary is not None and not summary.empty:
            result = summary.to_dict("records")
            _cache_set(f"rec_summary_{ticker}", result)
            return result
    except Exception:
        pass
    _cache_set(f"rec_summary_{ticker}", [])
    return []


def get_upgrade_downgrade(ticker: str) -> List[Dict]:
    """
    Fetch analyst upgrade/downgrade history.
    Primary: yfinance .upgrades_downgrades (free, rich data)
    Fallback: Finnhub upgrade_downgrade (requires premium plan)
    Cached 1h.
    """
    cached = _cache_get(f"updown_{ticker}", ANALYST_TTL)
    if cached is not None:
        return cached

    # Source 1: yfinance — free, returns Firm, ToGrade, FromGrade, Action, price targets
    try:
        import yfinance as yf
        df = yf.Ticker(ticker).upgrades_downgrades
        if df is not None and not df.empty:
            df = df.reset_index()
            # Normalise column names to match the display format
            col_map = {
                "GradeDate": "gradeTime",
                "Firm":       "company",
                "ToGrade":    "toGrade",
                "FromGrade":  "fromGrade",
                "Action":     "action",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            # Convert date to unix timestamp (page uses unit="s" to parse)
            if "gradeTime" in df.columns:
                import pandas as pd
                df["gradeTime"] = pd.to_datetime(df["gradeTime"], utc=True).astype("int64") // 10**9
            records = df.to_dict("records")
            _cache_set(f"updown_{ticker}", records)
            return records
    except Exception:
        pass

    # Source 2: Finnhub (premium plan required for this endpoint)
    try:
        from core.finnhub_client import upgrade_downgrade
        data = upgrade_downgrade(ticker)
        _cache_set(f"updown_{ticker}", data or [])
        return data or []
    except Exception:
        pass

    _cache_set(f"updown_{ticker}", [])
    return []


# ─────────────────────────────────────────
# INSIDER TRANSACTIONS
# ─────────────────────────────────────────
def get_insider_transactions(ticker: str) -> pd.DataFrame:
    """Fetch insider transactions from yfinance + Finnhub (cached 1h)."""
    cached = _cache_get(f"insider_{ticker}", INSIDER_TTL)
    if cached is not None:
        return cached

    combined = pd.DataFrame()

    # Source 1: yfinance
    try:
        import yfinance as yf
        txns = yf.Ticker(ticker).insider_transactions
        if txns is not None and not txns.empty:
            combined = txns
    except Exception:
        pass

    # Source 2: Finnhub (supplement if yfinance is sparse)
    if combined.empty or len(combined) < 3:
        try:
            from core.finnhub_client import insider_transactions as fh_insider
            fh_data = fh_insider(ticker)
            if fh_data and "data" in fh_data and fh_data["data"]:
                fh_df = pd.DataFrame(fh_data["data"])
                fh_rename = {
                    "name": "Insider Trading",
                    "share": "Shares",
                    "change": "Value",
                    "transactionDate": "Start Date",
                    "transactionType": "Text",
                }
                fh_df = fh_df.rename(columns={k: v for k, v in fh_rename.items() if k in fh_df.columns})
                if combined.empty:
                    combined = fh_df
                else:
                    combined = pd.concat([combined, fh_df], ignore_index=True).drop_duplicates()
        except Exception:
            pass

    _cache_set(f"insider_{ticker}", combined)
    return combined


def get_insider_purchases(ticker: str) -> pd.DataFrame:
    """Fetch insider purchase summary."""
    cached = _cache_get(f"insider_purchases_{ticker}", INSIDER_TTL)
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        purchases = yf.Ticker(ticker).insider_purchases
        if purchases is not None and not purchases.empty:
            _cache_set(f"insider_purchases_{ticker}", purchases)
            return purchases
    except Exception:
        pass

    empty = pd.DataFrame()
    _cache_set(f"insider_purchases_{ticker}", empty)
    return empty


# ─────────────────────────────────────────
# INSTITUTIONAL HOLDERS
# ─────────────────────────────────────────
def get_institutional_holders(ticker: str) -> pd.DataFrame:
    """Fetch top institutional holders (cached 1h)."""
    cached = _cache_get(f"inst_{ticker}", INST_TTL)
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        holders = yf.Ticker(ticker).institutional_holders
        if holders is not None and not holders.empty:
            _cache_set(f"inst_{ticker}", holders)
            return holders
    except Exception:
        pass

    empty = pd.DataFrame()
    _cache_set(f"inst_{ticker}", empty)
    return empty


def get_major_holders(ticker: str) -> pd.DataFrame:
    """Fetch ownership breakdown (% held by insiders, institutions, etc.)."""
    cached = _cache_get(f"major_{ticker}", INST_TTL)
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        major = yf.Ticker(ticker).major_holders
        if major is not None and not major.empty:
            _cache_set(f"major_{ticker}", major)
            return major
    except Exception:
        pass

    empty = pd.DataFrame()
    _cache_set(f"major_{ticker}", empty)
    return empty


def get_mutualfund_holders(ticker: str) -> pd.DataFrame:
    """Fetch top mutual fund holders."""
    cached = _cache_get(f"mf_{ticker}", INST_TTL)
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        mf = yf.Ticker(ticker).mutualfund_holders
        if mf is not None and not mf.empty:
            _cache_set(f"mf_{ticker}", mf)
            return mf
    except Exception:
        pass

    empty = pd.DataFrame()
    _cache_set(f"mf_{ticker}", empty)
    return empty


# ─────────────────────────────────────────
# HISTORICAL DATA (for performance charts)
# ─────────────────────────────────────────
def get_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch OHLCV history for a ticker (cached 5 min)."""
    cached = _cache_get(f"hist_{ticker}_{period}", HISTORY_TTL)
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=period)
        if hist is not None and not hist.empty:
            _cache_set(f"hist_{ticker}_{period}", hist)
            return hist
    except Exception:
        pass

    return pd.DataFrame()


def get_benchmark_history(benchmark_name: str, period: str = "1y") -> pd.DataFrame:
    """Fetch benchmark index history by name."""
    symbol = BENCHMARKS.get(benchmark_name)
    if not symbol:
        return pd.DataFrame()
    return get_history(symbol, period)


# ─────────────────────────────────────────
# FINANCIALS (income statement, balance sheet)
# ─────────────────────────────────────────
def get_financials(ticker: str) -> Dict[str, pd.DataFrame]:
    """Fetch annual and quarterly financials."""
    cached = _cache_get(f"financials_{ticker}", INFO_TTL)
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        result = {
            "income_annual":      t.financials if t.financials is not None else pd.DataFrame(),
            "income_quarterly":   t.quarterly_financials if t.quarterly_financials is not None else pd.DataFrame(),
            "balance_annual":     t.balance_sheet if t.balance_sheet is not None else pd.DataFrame(),
            "balance_quarterly":  t.quarterly_balance_sheet if t.quarterly_balance_sheet is not None else pd.DataFrame(),
            "cashflow_annual":    t.cashflow if t.cashflow is not None else pd.DataFrame(),
            "cashflow_quarterly": t.quarterly_cashflow if t.quarterly_cashflow is not None else pd.DataFrame(),
        }
        _cache_set(f"financials_{ticker}", result)
        return result
    except Exception:
        return {}


# ─────────────────────────────────────────
# SENTIMENT (basic headline-based)
# ─────────────────────────────────────────
_POSITIVE_WORDS = {
    "surge", "soar", "jump", "gain", "rise", "rally", "record", "beat",
    "upgrade", "buy", "outperform", "bullish", "profit", "growth", "strong",
    "positive", "boost", "expand", "high", "up", "exceeds", "dividend",
    "breakthrough", "innovation", "approve", "partnership", "deal", "win",
}

_NEGATIVE_WORDS = {
    "drop", "fall", "decline", "loss", "cut", "downgrade", "sell", "bear",
    "crash", "plunge", "miss", "weak", "negative", "risk", "layoff", "fire",
    "debt", "default", "lawsuit", "probe", "investigation", "recall",
    "underperform", "warning", "down", "low", "concern", "fear", "slump",
}


def calculate_headline_sentiment(headlines: List[str]) -> float:
    """
    Simple keyword-based sentiment score from -1.0 to +1.0.
    Returns 0.0 for neutral / no data.
    """
    if not headlines:
        return 0.0

    total_pos = 0
    total_neg = 0

    for headline in headlines:
        words = set(headline.lower().split())
        total_pos += len(words & _POSITIVE_WORDS)
        total_neg += len(words & _NEGATIVE_WORDS)

    total = total_pos + total_neg
    if total == 0:
        return 0.0

    return round((total_pos - total_neg) / total, 2)


def get_ticker_sentiment(ticker: str) -> Dict:
    """
    Calculate sentiment for a ticker based on recent news headlines.
    Returns: {score, label, positive_count, negative_count, total_headlines, top_positive, top_negative}
    """
    news = get_ticker_news(ticker)
    headlines = [n.get("title", "") for n in news if n.get("title")]

    if not headlines:
        return {"score": 0.0, "label": "No Data", "total_headlines": 0,
                "positive_count": 0, "negative_count": 0,
                "top_positive": [], "top_negative": []}

    score = calculate_headline_sentiment(headlines)

    # Classify each headline
    positive_headlines = []
    negative_headlines = []
    for h in headlines:
        words = set(h.lower().split())
        pos = len(words & _POSITIVE_WORDS)
        neg = len(words & _NEGATIVE_WORDS)
        if pos > neg:
            positive_headlines.append(h)
        elif neg > pos:
            negative_headlines.append(h)

    if score > 0.3:
        label = "Bullish"
    elif score > 0.1:
        label = "Slightly Bullish"
    elif score < -0.3:
        label = "Bearish"
    elif score < -0.1:
        label = "Slightly Bearish"
    else:
        label = "Neutral"

    return {
        "score":           score,
        "label":           label,
        "total_headlines":  len(headlines),
        "positive_count":   len(positive_headlines),
        "negative_count":   len(negative_headlines),
        "top_positive":     positive_headlines[:3],
        "top_negative":     negative_headlines[:3],
    }


# ─────────────────────────────────────────
# UTILITY: Global currency filter
# ─────────────────────────────────────────
def apply_global_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Filter a DataFrame by the global currency filter stored in session_state."""
    filt = st.session_state.get("global_currency_filter", "All")
    if filt == "All" or "currency" not in df.columns:
        return df
    return df[df["currency"] == filt].reset_index(drop=True)


def clean_nan(df: pd.DataFrame) -> pd.DataFrame:
    """Replace all NaN/None/'nan' values with empty strings for clean display."""
    result = df.fillna("")
    # Also catch string 'nan' that can appear after conversion
    result = result.replace("nan", "")
    return result


# ─────────────────────────────────────────
# UTILITY: CAGR calculation
# ─────────────────────────────────────────
def calc_cagr(start_val: float, end_val: float, years: float) -> Optional[float]:
    """Compound Annual Growth Rate. Returns None if inputs invalid."""
    if start_val <= 0 or years <= 0 or end_val <= 0:
        return None
    return (end_val / start_val) ** (1.0 / years) - 1.0


# ─────────────────────────────────────────
# UTILITY: Format large numbers
# ─────────────────────────────────────────
def calc_max_drawdown(nav_series: pd.Series) -> Optional[float]:
    """
    Calculate maximum drawdown from a NAV or price series.
    Returns the largest peak-to-trough decline as a negative percentage (e.g., -0.25 = -25%).
    """
    try:
        if nav_series is None or len(nav_series) < 2:
            return None
        values = pd.to_numeric(nav_series, errors="coerce").dropna()
        if len(values) < 2:
            return None
        cummax = values.cummax()
        drawdowns = (values - cummax) / cummax
        return float(drawdowns.min())
    except Exception:
        return None


def calc_sharpe_ratio(returns: pd.Series, risk_free_annual: float = 0.05) -> Optional[float]:
    """
    Calculate annualized Sharpe ratio from a series of daily returns.
    risk_free_annual: annualized risk-free rate (default 5% for US T-bills).
    """
    try:
        if returns is None or len(returns) < 20:
            return None
        clean = pd.to_numeric(returns, errors="coerce").dropna()
        if len(clean) < 20 or clean.std() == 0:
            return None
        daily_rf = (1 + risk_free_annual) ** (1 / 252) - 1
        excess = clean - daily_rf
        return float((excess.mean() / excess.std()) * (252 ** 0.5))
    except Exception:
        return None


def calc_sortino_ratio(returns: pd.Series, risk_free_annual: float = 0.05) -> Optional[float]:
    """
    Calculate annualized Sortino ratio (only penalizes downside volatility).
    """
    try:
        if returns is None or len(returns) < 20:
            return None
        clean = pd.to_numeric(returns, errors="coerce").dropna()
        if len(clean) < 20:
            return None
        daily_rf = (1 + risk_free_annual) ** (1 / 252) - 1
        excess = clean - daily_rf
        downside = excess[excess < 0]
        if len(downside) == 0 or downside.std() == 0:
            return None
        return float((excess.mean() / downside.std()) * (252 ** 0.5))
    except Exception:
        return None


def calc_portfolio_beta(tickers: list, weights: dict, period: str = "1y") -> Optional[float]:
    """
    Calculate weighted average beta for a portfolio.
    Uses individual stock betas from yfinance info data.
    """
    try:
        if not tickers:
            return None
        import numpy as np
        betas = []
        w_vals = []
        for t in tickers:
            info = _cache_get(f"info_{t}", INFO_TTL)
            if info is None:
                continue
            b = info.get("beta")
            if b is not None:
                try:
                    b_val = float(b)
                    w_val = float(weights.get(t, 0))
                    if not (pd.isna(b_val) or pd.isna(w_val)):
                        betas.append(b_val)
                        w_vals.append(w_val)
                except (TypeError, ValueError):
                    pass
        if not betas:
            return None
        w_arr = pd.Series(w_vals)
        w_arr = w_arr / w_arr.sum()
        return float((pd.Series(betas) * w_arr).sum())
    except Exception:
        return None


def calc_portfolio_volatility(tickers: list, weights: dict, period: str = "1y") -> Optional[float]:
    """
    Calculate annualized portfolio volatility from individual stock returns.
    Simplified: uses weighted average of individual volatilities (ignores correlation).
    """
    try:
        import numpy as np
        if not tickers:
            return None
        vols = []
        w_vals = []
        for t in tickers:
            h = get_history(t, period)
            if h is not None and isinstance(h, pd.DataFrame) and len(h) >= 20:
                col = "Close" if "Close" in h.columns else h.columns[0]
                daily_ret = h[col].pct_change().dropna()
                if len(daily_ret) >= 20:
                    ann_vol = float(daily_ret.std() * (252 ** 0.5))
                    w_val = float(weights.get(t, 0))
                    vols.append(ann_vol)
                    w_vals.append(w_val)
        if not vols:
            return None
        w_arr = pd.Series(w_vals)
        w_arr = w_arr / w_arr.sum()
        return float((pd.Series(vols) * w_arr).sum())
    except Exception:
        return None


def fmt_large(val) -> str:
    """Format a large number: 1.2B, 450M, 12.5K, etc."""
    try:
        v = float(val)
        if abs(v) >= 1e12:
            return f"{v/1e12:.1f}T"
        elif abs(v) >= 1e9:
            return f"{v/1e9:.1f}B"
        elif abs(v) >= 1e6:
            return f"{v/1e6:.1f}M"
        elif abs(v) >= 1e3:
            return f"{v/1e3:.1f}K"
        else:
            return f"{v:,.2f}"
    except (TypeError, ValueError):
        return "—"
