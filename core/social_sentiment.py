"""
Social Sentiment
================
Fetches sentiment data from StockTwits (free, no auth) and Reddit (public JSON feed).
Combines with news headline sentiment into a composite score.

Reddit approach: uses the public *.json feed — no API key or OAuth required.
"""

import requests
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


# ── Composite Score ──────────────────────────────────────────────────────────

def get_composite_sentiment(ticker: str, news_score: float) -> Dict:
    """
    Combine all sentiment sources into a weighted composite.

    Weights:
      - News headlines:  40%
      - StockTwits:      35%
      - Reddit:          25%

    Returns dict with composite_score and per-source breakdown.
    """
    st_data = get_stocktwits_sentiment(ticker)
    rd_data = get_reddit_sentiment(ticker)

    # Weighted composite
    composite = (
        news_score * 0.40 +
        st_data["score"] * 0.35 +
        rd_data["score"] * 0.25
    )

    return {
        "composite_score": round(composite, 2),
        "news": {"score": news_score, "weight": "40%"},
        "stocktwits": {**st_data, "weight": "35%"},
        "reddit": {**rd_data, "weight": "25%"},
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
