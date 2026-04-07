"""
Market & Industry News
======================
Cached per focus area (session_state, 15-min TTL).
AI summary toggle + sleek card layout.
Includes "My Funds & ETFs" section from portfolio.
"""

import time
import hashlib
import streamlit as st
import pandas as pd
from datetime import datetime

from core.data_engine import get_ticker_news, summarize_news_with_ai, apply_global_filter
from core.settings import SETTINGS, save_user_settings, enriched_cache_key

NEWS_TTL = 900  # 15 minutes

st.header("🌍 Market & Industry News")

focus_map = {
    "🌐 Global Markets":         ["^GSPC", "^NDX", "^DJI", "^NSEI", "^FTSE", "^HSI"],
    "🇺🇸 US Markets":            ["^GSPC", "^NDX", "^DJI"],
    "🇮🇳 India":                 ["^NSEI", "^BSESN"],
    "💻 Technology":             ["XLK", "QQQ", "AAPL", "MSFT", "NVDA", "GOOGL"],
    "⚡ Energy":                  ["XLE", "CVX", "XOM", "COP"],
    "🏥 Healthcare":             ["XLV", "JNJ", "UNH", "PFE"],
    "🏦 Financials":             ["XLF", "JPM", "BAC", "GS"],
}

# Build "My Funds & ETFs" option from portfolio
_fund_tickers = []
base_currency = SETTINGS.get("base_currency", "USD")
_enriched_key = enriched_cache_key(base_currency)
if _enriched_key in st.session_state:
    _enr = st.session_state[_enriched_key]
    _t_col = "ticker_resolved" if "ticker_resolved" in _enr.columns else "ticker"
    # Check for extended_df which has quote_type
    _ext_df = st.session_state.get("extended_df")
    _src = _ext_df if _ext_df is not None else _enr
    if "quote_type" in _src.columns:
        _is_fund = _src["quote_type"].apply(lambda x: str(x).upper() in ("ETF", "MUTUALFUND"))
        _fund_tickers = _src.loc[_is_fund, _t_col].dropna().tolist()

if _fund_tickers:
    focus_map["📊 My Funds & ETFs"] = _fund_tickers

with st.sidebar:
    focus       = st.selectbox("Market Focus", list(focus_map.keys()))
    max_articles = st.slider("Max articles", 10, 50, 20)
    auto_summary = st.toggle("🤖 Auto AI Summaries",
                              value=SETTINGS.get("pref_mkt_auto_summary", False),
                              help="Generates an AI insight for every article (~$0.01 each)")
    # Persist preference
    if auto_summary != SETTINGS.get("pref_mkt_auto_summary", False):
        save_user_settings({"pref_mkt_auto_summary": auto_summary})
        SETTINGS["pref_mkt_auto_summary"] = auto_summary

    if st.button("🔄 Refresh News", use_container_width=True):
        cache_key = f"mkt_news_{focus}"
        st.session_state.pop(cache_key, None)
        st.session_state.pop(f"{cache_key}_ts", None)

tickers   = focus_map.get(focus, ["^GSPC"])
cache_key = f"mkt_news_{focus}"

# ── Load from session_state cache (15-min TTL) ────────────────────────────────
cached_ts = st.session_state.get(f"{cache_key}_ts", 0)
has_cache = cache_key in st.session_state and (time.time() - cached_ts) < NEWS_TTL

if not has_cache:
    with st.spinner(f"Loading {focus} news…"):
        all_news = []
        for t in tickers:
            try:
                items = get_ticker_news(t)
                for item in items:
                    item["related_ticker"] = t
                    all_news.append(item)
            except Exception:
                pass  # Skip tickers that fail

        seen, unique = set(), []
        for item in sorted(all_news, key=lambda x: x.get("providerPublishTime", 0), reverse=True):
            title = item.get("title", "")
            if title and title not in seen:
                seen.add(title)
                unique.append(item)

        st.session_state[cache_key]          = unique[:max_articles]
        st.session_state[f"{cache_key}_ts"]  = time.time()

news = st.session_state.get(cache_key, [])[:max_articles]

if not news:
    st.info(f"No recent news found for {focus}. Try clicking **Refresh News**.")
    st.stop()

# Age indicator
age_s   = int(time.time() - cached_ts)
age_str = f"{age_s // 60}m {age_s % 60}s ago" if age_s >= 60 else f"{age_s}s ago"
st.caption(f"**{len(news)}** articles · {focus} · cached **{age_str}**")

if focus == "📊 My Funds & ETFs":
    st.info(f"Showing news for **{len(tickers)}** Funds & ETFs from your portfolio. "
            "These are excluded from Portfolio News to keep stock-level focus.")

st.divider()

# ── News cards ────────────────────────────────────────────────────────────────
for i, item in enumerate(news):
    title     = item.get("title", "Untitled")
    publisher = item.get("publisher", "")
    link      = item.get("link", "")
    ticker    = item.get("related_ticker", "")
    ts        = item.get("providerPublishTime", 0)
    date_str  = datetime.fromtimestamp(ts).strftime("%b %d · %I:%M %p") if ts else ""

    with st.container():
        col_main, col_btn = st.columns([6, 1])
        with col_main:
            st.markdown(f"**{title}**")
            st.caption(f"🏷️ `{ticker}` &nbsp;·&nbsp; {publisher} &nbsp;·&nbsp; {date_str}")
        with col_btn:
            if link:
                st.link_button("Read →", link, use_container_width=True)

        skey = f"mkt_summary_{i}"

        if auto_summary:
            if skey not in st.session_state:
                with st.spinner("Generating AI insight…"):
                    st.session_state[skey] = summarize_news_with_ai(
                        title, publisher, ticker, "Market Index"
                    )
            st.info(f"🤖 **AI Summary:** {st.session_state[skey]}")
        else:
            if st.button("🤖 AI Summary", key=f"mkt_btn_{i}", use_container_width=False):
                if skey not in st.session_state:
                    with st.spinner("Generating AI summary…"):
                        st.session_state[skey] = summarize_news_with_ai(
                            title, publisher, ticker, "Market Index"
                        )
            if skey in st.session_state:
                st.info(f"🤖 **AI Summary:** {st.session_state[skey]}")

    st.divider()
