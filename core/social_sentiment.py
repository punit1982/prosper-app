"""
Social Sentiment
================
Fetches sentiment data from StockTwits (free, no auth), Reddit (public JSON feed),
Analyst Consensus (via FMP), and Google News RSS.
Combines with news headline sentiment into a composite score with dynamic weight
redistribution — empty sources have their weight redistributed proportionally.

Reddit approach: uses the public *.json feed — no API key or OAuth required.
"""

import requests
import xml.etree.ElementTree as ET
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor

_REDDIT_HEADERS = {
    "User-Agent": "prosper-sentiment/1.0 (public JSON feed)"
}


# ── StockTwits (free, no auth required) ──────────────────────────────────────

def get_stocktwits_sentiment(ticker: str) -> Dict:
    """
    Fetch StockTwits messages and aggregate bull/bear sentiment.
    Returns: {score, messages, bulls, bears, top_messages}
    """
    try:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return {"score": 0, "messages": 0, "bulls": 0, "bears": 0, "top_messages": []}

        data = resp.json()
        messages = data.get("messages", [])
        if not messages:
            return {"score": 0, "messages": 0, "bulls": 0, "bears": 0, "top_messages": []}

        bulls = 0
        bears = 0
        top_msgs = []

        for m in messages:
            sentiment = (m.get("entities", {}).get("sentiment") or {}).get("basic", "")
            if sentiment == "Bullish":
                bulls += 1
            elif sentiment == "Bearish":
                bears += 1
            if len(top_msgs) < 5:
                top_msgs.append({
                    "body": m.get("body", "")[:200],
                    "sentiment": sentiment,
                    "created_at": m.get("created_at", ""),
                })

        total = bulls + bears
        score = round((bulls - bears) / total, 2) if total > 0 else 0

        return {
            "score": score,
            "messages": len(messages),
            "bulls": bulls,
            "bears": bears,
            "top_messages": top_msgs,
        }
    except Exception:
        return {"score": 0, "messages": 0, "bulls": 0, "bears": 0, "top_messages": []}


# ── Reddit (public JSON feed — no auth required) ─────────────────────────────

def get_reddit_sentiment(ticker: str) -> Dict:
    """
    Search Reddit for ticker mentions using the public JSON feed.
    No API key or OAuth required — hits /search.json directly.
    Returns: {score, mentions, top_posts, source}
    """
    # Strip exchange suffix for cleaner Reddit search (e.g. "EMAAR.AE" → "EMAAR")
    base_ticker = ticker.split(".")[0] if "." in ticker else ticker
    # Strip Twelve Data exchange format too (e.g. "EMAAR:DFM" → "EMAAR")
    if ":" in base_ticker:
        base_ticker = base_ticker.split(":")[0]

    try:
        url = (
            "https://www.reddit.com/r/stocks+wallstreetbets+investing/search.json"
            f"?q=%24{base_ticker}&sort=new&t=week&limit=25&restrict_sr=true"
        )
        resp = requests.get(url, headers=_REDDIT_HEADERS, timeout=10)
        if resp.status_code != 200:
            return {"score": 0, "mentions": 0, "top_posts": [], "source": "Reddit"}

        data = resp.json()
        children = data.get("data", {}).get("children", [])
        if not children:
            return {"score": 0, "mentions": 0, "top_posts": [], "source": "Reddit"}

        posts_data = [c.get("data", {}) for c in children]
        titles = [p.get("title", "") for p in posts_data if p.get("title")]
        top_posts = [
            {"title": p.get("title", ""), "score": p.get("score", 0), "url": p.get("url", "")}
            for p in posts_data[:5]
        ]

        # Keyword sentiment analysis on post titles
        from core.data_engine import calculate_headline_sentiment
        score = calculate_headline_sentiment(titles)

        return {
            "score": score,
            "mentions": len(posts_data),
            "top_posts": top_posts,
            "source": "Reddit (JSON feed)",
        }
    except Exception:
        return {"score": 0, "mentions": 0, "top_posts": [], "source": "Reddit"}


# ── Analyst Consensus (via FMP recommendations) ─────────────────────────────

def get_analyst_sentiment(ticker: str) -> Dict:
    """
    Derive sentiment from analyst buy/hold/sell recommendations.
    Contrarian-adjusted: Score = (strongBuy*2 + buy*0.5 + hold*-0.5 + sell*-1.5 + strongSell*-2) / total
    Normalized to -1..+1 range.
    """
    try:
        from core.data_engine import get_recommendations_summary
        recs = get_recommendations_summary(ticker)
        if not recs or not isinstance(recs, list) or len(recs) == 0:
            return {"score": 0, "total_recs": 0, "breakdown": {}, "source": "Analyst Consensus"}

        latest = recs[0]  # Most recent period
        strong_buy = latest.get("strongBuy", 0) or 0
        buy = latest.get("buy", 0) or 0
        hold = latest.get("hold", 0) or 0
        sell = latest.get("sell", 0) or 0
        strong_sell = latest.get("strongSell", 0) or 0

        total = strong_buy + buy + hold + sell + strong_sell
        if total == 0:
            return {"score": 0, "total_recs": 0, "breakdown": {}, "source": "Analyst Consensus"}

        # Contrarian-adjusted scoring: Hold is slightly negative (if analysts
        # can only say Hold, it's not positive), Buy weight reduced (lazy default)
        raw_score = (strong_buy * 2 + buy * 0.5 + hold * -0.5 + sell * -1.5 + strong_sell * -2) / total
        # raw_score range is -2..+2, normalize to -1..+1
        score = round(max(-1.0, min(1.0, raw_score / 2)), 2)

        return {
            "score": score,
            "total_recs": total,
            "breakdown": {
                "strongBuy": strong_buy, "buy": buy, "hold": hold,
                "sell": sell, "strongSell": strong_sell,
            },
            "source": "Analyst Consensus",
        }
    except Exception:
        return {"score": 0, "total_recs": 0, "breakdown": {}, "source": "Analyst Consensus"}


# ── Google News RSS ──────────────────────────────────────────────────────────

def get_google_news_sentiment(ticker: str) -> Dict:
    """
    Fetch Google News RSS headlines for a ticker and calculate sentiment.
    """
    base_ticker = ticker.split(".")[0] if "." in ticker else ticker
    if ":" in base_ticker:
        base_ticker = base_ticker.split(":")[0]

    try:
        url = f"https://news.google.com/rss/search?q={base_ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return {"score": 0, "headlines": 0, "source": "Google News RSS"}

        root = ET.fromstring(resp.content)
        titles = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                titles.append(title_el.text)

        if not titles:
            return {"score": 0, "headlines": 0, "source": "Google News RSS"}

        from core.data_engine import calculate_headline_sentiment
        score = calculate_headline_sentiment(titles)

        return {
            "score": round(score, 2),
            "headlines": len(titles),
            "source": "Google News RSS",
        }
    except Exception:
        return {"score": 0, "headlines": 0, "source": "Google News RSS"}


# ── Composite Score ──────────────────────────────────────────────────────────

def get_composite_sentiment(ticker: str, news_score: float) -> Dict:
    """
    Combine all sentiment sources into a weighted composite with dynamic
    weight redistribution.

    Default weights:
      - News headlines:   30%
      - StockTwits:       15%
      - Reddit:           10%
      - Analyst Consensus: 20%
      - Google News RSS:  25%

    If a source returns empty data, its weight is redistributed proportionally
    to sources that DO have real data.

    Returns dict with composite_score, per-source breakdown, and sources_active count.
    """
    # Fetch all 4 sources in parallel (within this single ticker)
    from concurrent.futures import as_completed
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_st = pool.submit(get_stocktwits_sentiment, ticker)
        f_rd = pool.submit(get_reddit_sentiment, ticker)
        f_an = pool.submit(get_analyst_sentiment, ticker)
        f_gn = pool.submit(get_google_news_sentiment, ticker)

        try:
            st_data = f_st.result(timeout=12)
        except Exception:
            st_data = {"score": 0, "messages": 0, "bulls": 0, "bears": 0, "top_messages": []}
        try:
            rd_data = f_rd.result(timeout=12)
        except Exception:
            rd_data = {"score": 0, "mentions": 0, "top_posts": [], "source": "Reddit"}
        try:
            an_data = f_an.result(timeout=12)
        except Exception:
            an_data = {"score": 0, "total_recs": 0, "breakdown": {}, "source": "Analyst Consensus"}
        try:
            gn_data = f_gn.result(timeout=12)
        except Exception:
            gn_data = {"score": 0, "headlines": 0, "source": "Google News RSS"}

    # Default weights
    sources = {
        "news":        {"score": news_score, "default_weight": 0.30, "has_data": True},  # news always counted
        "stocktwits":  {"score": st_data["score"],  "default_weight": 0.15, "has_data": st_data.get("messages", 0) > 0},
        "reddit":      {"score": rd_data["score"],  "default_weight": 0.10, "has_data": rd_data.get("mentions", 0) > 0},
        "analyst":     {"score": an_data["score"],   "default_weight": 0.20, "has_data": an_data.get("total_recs", 0) > 0},
        "google_news": {"score": gn_data["score"],  "default_weight": 0.25, "has_data": gn_data.get("headlines", 0) > 0},
    }

    # Calculate redistributed weights
    active_weight = sum(s["default_weight"] for s in sources.values() if s["has_data"])
    sources_active = sum(1 for s in sources.values() if s["has_data"])

    composite = 0.0
    actual_weights = {}
    if active_weight > 0:
        for name, info in sources.items():
            if info["has_data"]:
                actual_w = info["default_weight"] / active_weight  # redistribute proportionally
                actual_weights[name] = actual_w
                composite += info["score"] * actual_w
            else:
                actual_weights[name] = 0.0
    else:
        for name in sources:
            actual_weights[name] = 0.0

    def _fmt_w(w):
        return f"{round(w * 100)}%"

    return {
        "composite_score": round(composite, 2),
        "sources_active": sources_active,
        "news":        {"score": news_score, "weight": _fmt_w(actual_weights["news"])},
        "stocktwits":  {**st_data, "weight": _fmt_w(actual_weights["stocktwits"])},
        "reddit":      {**rd_data, "weight": _fmt_w(actual_weights["reddit"])},
        "analyst":     {**an_data, "weight": _fmt_w(actual_weights["analyst"])},
        "google_news": {**gn_data, "weight": _fmt_w(actual_weights["google_news"])},
    }


def get_composite_sentiment_batch(tickers_with_news: List[tuple]) -> Dict[str, Dict]:
    """
    Fetch composite sentiment for multiple tickers in parallel.
    Input: [(ticker, news_score), ...]
    """
    results = {}

    def _fetch(item):
        ticker, news_score = item
        return ticker, get_composite_sentiment(ticker, news_score)

    with ThreadPoolExecutor(max_workers=min(len(tickers_with_news), 10)) as pool:
        futures = {pool.submit(_fetch, item): item[0] for item in tickers_with_news}
        from concurrent.futures import as_completed
        for f in as_completed(futures):
            try:
                t, data = f.result()
                results[t] = data
            except Exception:
                pass

    return results
