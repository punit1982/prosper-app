"""
Portfolio News
==============
Aggregated news from all portfolio holdings.
• Loads instantly from SQLite cache (1-hour TTL, survives restarts)
• Fetches top 15 holdings by value first — covers >80% of portfolio
• One click → AI summary (Claude-powered)
• "Load all" button to fetch remaining tickers on demand
"""

import hashlib
import streamlit as st
import pandas as pd
from datetime import datetime

from core.database import get_all_holdings, get_news_cache
from core.cio_engine import enrich_portfolio
from core.data_engine import get_portfolio_news, summarize_news_with_ai, apply_global_filter
from core.settings import SETTINGS, save_user_settings, enriched_cache_key

st.header("📰 Portfolio News")

holdings = get_all_holdings()
if holdings.empty:
    st.info("Add holdings via **Upload Portal** to see related news.")
    st.stop()

# ── Controls (persisted) ──
with st.sidebar:
    max_articles = st.slider("Max articles", 10, 100,
                              value=SETTINGS.get("pref_news_max_articles", 30), step=10)
    auto_summary = st.toggle("🤖 Auto-show AI summaries",
                              value=SETTINGS.get("pref_news_auto_summary", False),
                              help="Uses your Anthropic API credits (~$0.01 per summary)")
    # Persist changes
    _news_prefs = {"pref_news_max_articles": max_articles, "pref_news_auto_summary": auto_summary}
    _news_changed = {k: v for k, v in _news_prefs.items() if SETTINGS.get(k) != v}
    if _news_changed:
        save_user_settings(_news_changed)
        SETTINGS.update(_news_changed)

# ── Resolve top tickers by portfolio value ──────────────────────────────────
base_currency = SETTINGS.get("base_currency", "USD")
enriched_key  = enriched_cache_key(base_currency)
names = dict(zip(holdings["ticker"], holdings.get("name", pd.Series(dtype=str))))

all_tickers = []
fund_tickers = []
if enriched_key in st.session_state:
    enriched = apply_global_filter(st.session_state[enriched_key])
    t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
    has_price = pd.to_numeric(enriched.get("current_price", pd.Series(dtype=float)), errors="coerce").notna()
    priced = enriched[has_price].copy()
    if "market_value" in priced.columns:
        priced = priced.sort_values("market_value", ascending=False)

    # Exclude Funds/ETFs from stock news (they return generic/irrelevant news)
    _ETF_KEYWORDS = ("ISHARES", "VANGUARD", "SPDR", "INVESCO", "PROSHARES", "WISDOMTREE",
                      "SCHWAB", "FIRST TRUST", "GLOBAL X", "PIMCO", "JPMORGAN EQUITY",
                      "ETF", "FUND", "INDEX", "TRUST")

    def _is_fund_or_etf(row):
        qt = str(row.get("quote_type", "")).upper()
        if qt in ("ETF", "MUTUALFUND"):
            return True
        name = str(row.get("name", "")).upper()
        if any(kw in name for kw in _ETF_KEYWORDS):
            return True
        return False

    is_fund = priced.apply(_is_fund_or_etf, axis=1)
    fund_tickers = priced.loc[is_fund, t_col].dropna().tolist()
    priced = priced[~is_fund]

    all_tickers = priced[t_col].dropna().tolist()

# Fallback: use raw holdings tickers if not enriched yet
if not all_tickers:
    all_tickers = holdings["ticker"].dropna().tolist()

if fund_tickers:
    st.caption(f"ℹ️ Excluded **{len(fund_tickers)}** Funds/ETFs from stock news — see **Market News** for fund coverage.")

# Top 15 by value — covers the bulk of the portfolio quickly
TOP_N = 15
top_tickers  = all_tickers[:TOP_N]
rest_tickers = all_tickers[TOP_N:]

# ── Check SQLite cache warmth to decide whether to show spinner ─────────────
top_hash     = hashlib.md5(",".join(sorted(top_tickers)).encode()).hexdigest()[:12]
has_db_cache = get_news_cache(f"pnews_{top_hash}") is not None

st.caption(
    f"📡 Showing news for top **{len(top_tickers)}** holdings by value"
    + (f" · {len(rest_tickers)} more available" if rest_tickers else "")
    + (" · from cache" if has_db_cache else "")
)

# ── Fetch top-15 news ───────────────────────────────────────────────────────
if has_db_cache:
    # Instant load — SQLite cache is warm
    news_items = get_portfolio_news(top_tickers, limit=max_articles)
else:
    with st.spinner(f"Fetching news for {len(top_tickers)} holdings (~{len(top_tickers) * 2}s)…"):
        news_items = get_portfolio_news(top_tickers, limit=max_articles)

if not news_items:
    st.info("No recent news found for your top holdings.")
    # Still allow loading the rest below
else:
    st.caption(f"Showing **{len(news_items)}** articles from **{len(set(n.get('related_ticker','') for n in news_items))}** tickers")
    st.divider()

    # ── News feed ──────────────────────────────────────────────────────────
    for i, item in enumerate(news_items):
        title     = item.get("title", "Untitled")
        publisher = item.get("publisher", "Unknown")
        link      = item.get("link", "")
        ticker    = item.get("related_ticker", "")
        ts        = item.get("providerPublishTime", 0)
        date_str  = datetime.fromtimestamp(ts).strftime("%b %d, %Y · %I:%M %p") if ts else "—"

        col1, col2 = st.columns([5, 1])
        with col1:
            st.markdown(f"**{title}**")
            st.caption(f"🏷️ {ticker} · {publisher} · {date_str}")
        with col2:
            if link:
                st.link_button("Read →", link, use_container_width=True)

        summary_key = f"news_summary_{i}"

        if auto_summary:
            if summary_key not in st.session_state:
                ticker_name = names.get(ticker, "")
                st.session_state[summary_key] = summarize_news_with_ai(title, publisher, ticker, ticker_name)
            st.info(f"🤖 **AI Summary:** {st.session_state[summary_key]}")
        else:
            if st.button("🤖 AI Summary", key=f"btn_summary_{i}"):
                if summary_key not in st.session_state:
                    ticker_name = names.get(ticker, "")
                    with st.spinner("Generating AI summary…"):
                        st.session_state[summary_key] = summarize_news_with_ai(title, publisher, ticker, ticker_name)
                st.info(f"🤖 **AI Summary:** {st.session_state[summary_key]}")

        st.divider()

# ── Load remaining tickers on demand ────────────────────────────────────────
if rest_tickers:
    st.subheader(f"Load news for remaining {len(rest_tickers)} holdings")
    if st.button(f"📰 Load {len(rest_tickers)} more holdings", use_container_width=True):
        rest_hash     = hashlib.md5(",".join(sorted(rest_tickers)).encode()).hexdigest()[:12]
        has_rest_cache = get_news_cache(f"pnews_{rest_hash}") is not None

        if has_rest_cache:
            more_news = get_portfolio_news(rest_tickers, limit=max_articles)
        else:
            with st.spinner(f"Fetching news for {len(rest_tickers)} more holdings…"):
                more_news = get_portfolio_news(rest_tickers, limit=max_articles)

        if more_news:
            st.caption(f"Found **{len(more_news)}** more articles")
            for i, item in enumerate(more_news, start=len(news_items)):
                title     = item.get("title", "Untitled")
                publisher = item.get("publisher", "Unknown")
                link      = item.get("link", "")
                ticker    = item.get("related_ticker", "")
                ts        = item.get("providerPublishTime", 0)
                date_str  = datetime.fromtimestamp(ts).strftime("%b %d, %Y · %I:%M %p") if ts else "—"

                col1, col2 = st.columns([5, 1])
                with col1:
                    st.markdown(f"**{title}**")
                    st.caption(f"🏷️ {ticker} · {publisher} · {date_str}")
                with col2:
                    if link:
                        st.link_button("Read →", link, use_container_width=True)
                st.divider()
        else:
            st.info("No news found for remaining holdings.")
