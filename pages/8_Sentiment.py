"""
Sentiment Score
===============
Composite sentiment from News Headlines + StockTwits + Reddit + Analyst Consensus + Google News.
Score range: -100 (very bearish) to +100 (very bullish).
Uses dynamic weight redistribution — empty sources have their weight redistributed.

Optimized:
- Results cached in session_state (30 min TTL) — no re-fetch on every click
- Per-ticker detail uses @st.fragment — only that section re-runs on ticker change
- Dates shown on headlines
"""

import time
import streamlit as st
import pandas as pd
import plotly.express as px

from core.database import get_all_holdings
from core.data_engine import get_ticker_sentiment, apply_global_filter
from core.social_sentiment import get_composite_sentiment
from core.settings import SETTINGS

SENT_TTL = 1800  # 30 minutes — re-fetch sentiment every 30 min

st.header("💬 Sentiment Score")

holdings = get_all_holdings()
if holdings.empty:
    st.info("Add holdings via **Upload Portal** to see sentiment analysis.")
    st.stop()

# ── Resolve tickers once ──────────────────────────────────────────────────────
base_currency = SETTINGS.get("base_currency", "USD")
cache_key     = f"enriched_{base_currency}"
if cache_key in st.session_state:
    enriched = apply_global_filter(st.session_state[cache_key])
    t_col    = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
    has_price = pd.to_numeric(enriched.get("current_price", pd.Series(dtype=float)), errors="coerce").notna()
    tickers   = sorted(enriched.loc[has_price, t_col].dropna().tolist(), key=str.upper)
else:
    tickers = sorted(holdings["ticker"].dropna().tolist(), key=str.upper)

if not tickers:
    st.info("No tickers with live prices. Load prices from **Portfolio Dashboard** first.")
    st.stop()

names = dict(zip(holdings["ticker"], holdings["name"]))

# ── Sentiment cache (30-min TTL in session_state) ─────────────────────────────
sent_key = f"sentiment_data_{hash(tuple(sorted(tickers)))}"
now      = time.time()

if sent_key not in st.session_state or (now - st.session_state[sent_key].get("ts", 0)) > SENT_TTL:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    with st.spinner(f"Analysing sentiment for {len(tickers)} holdings (News · StockTwits · Reddit · Analyst · Google News)…"):
        sentiments = {}
        composites = {}

        def _fetch(ticker):
            news_sent = get_ticker_sentiment(ticker)
            comp      = get_composite_sentiment(ticker, news_sent["score"])
            return ticker, news_sent, comp

        pool = ThreadPoolExecutor(max_workers=min(len(tickers), 15))
        futures = {pool.submit(_fetch, t): t for t in tickers}
        try:
            for f in as_completed(futures, timeout=60):
                try:
                    t, ns, comp = f.result()
                    sentiments[t] = ns
                    composites[t] = comp
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            pool.shutdown(wait=False)

    st.session_state[sent_key] = {
        "sentiments": sentiments,
        "composites": composites,
        "ts":         now,
    }

cached     = st.session_state[sent_key]
sentiments = cached["sentiments"]
composites = cached["composites"]
fetched_at = cached.get("ts", now)


# ── Helpers ──────────────────────────────────────────────────────────────────
def score_label(s):
    if s > 0.3:    return "🟢 Bullish"
    if s > 0.1:    return "🟡 Slightly Bullish"
    if s > -0.1:   return "⚪ Neutral"
    if s > -0.3:   return "🟠 Slightly Bearish"
    return "🔴 Bearish"

def _to_100(v):
    """Convert -1..+1 score to -100..+100 whole number."""
    return round(v * 100)


# ── Status bar + manual refresh ──────────────────────────────────────────────
age_min = int((time.time() - fetched_at) / 60)
hdr1, hdr2 = st.columns([7, 1])
with hdr1:
    st.caption(f"📡 Sentiment data: **{age_min}m ago** · refreshes every 30 min · {len(tickers)} holdings analysed")
with hdr2:
    if st.button("🔄", key="sent_refresh", help="Force refresh sentiment data"):
        st.session_state.pop(sent_key, None)
        st.rerun()

# ── Portfolio overview chart ─────────────────────────────────────────────────
rows = []
for t in tickers:
    c = composites.get(t, {})
    s = sentiments.get(t, {})
    rows.append({
        "Ticker":         t,
        "Name":           names.get(t, ""),
        "Composite":      _to_100(c.get("composite_score", 0)),
        "News":           _to_100(c.get("news", {}).get("score", 0)),
        "StockTwits":     _to_100(c.get("stocktwits", {}).get("score", 0)),
        "Reddit":         _to_100(c.get("reddit", {}).get("score", 0)),
        "Analyst":        _to_100(c.get("analyst", {}).get("score", 0)),
        "Google News":    _to_100(c.get("google_news", {}).get("score", 0)),
        "Headlines":      s.get("total_headlines", 0),
        "Active Sources": c.get("sources_active", 1),
        "Signal":         score_label(c.get("composite_score", 0)),
    })

sdf = pd.DataFrame(rows)

if not sdf.empty:
    fig = px.bar(
        sdf.sort_values("Composite"),
        x="Composite", y="Ticker", orientation="h",
        color="Composite",
        color_continuous_scale=[
            [0.0,  "#DD2C00"],   # -100: deep bearish red
            [0.2,  "#FF6D00"],   # -60:  bearish orange
            [0.35, "#FFD600"],   # -30:  slightly bearish yellow
            [0.45, "#E0E0E0"],   # -10:  neutral zone start (grey)
            [0.55, "#E0E0E0"],   # +10:  neutral zone end (grey)
            [0.65, "#FFD600"],   # +30:  slightly bullish yellow
            [0.8,  "#64DD17"],   # +60:  bullish light green
            [1.0,  "#00C853"],   # +100: deep bullish green
        ],
        range_color=[-100, 100],
        title="Sentiment Score — All Holdings (-100 to +100)",
        text="Signal",
    )
    fig.update_layout(
        height=max(320, len(sdf) * 32),
        margin=dict(t=50, b=10, l=10, r=10),
        yaxis=dict(categoryorder="total ascending"),
        coloraxis_showscale=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(fig, use_container_width=True)

    avg_raw = sdf["Composite"].mean()
    avg_display = round(avg_raw)
    c1, c2, c3 = st.columns(3)
    c1.metric("Portfolio Avg Sentiment", f"{avg_display:+d}", delta=score_label(avg_raw / 100))
    c2.metric("Most Bullish", sdf.loc[sdf["Composite"].idxmax(), "Ticker"] if not sdf.empty else "—")
    c3.metric("Most Bearish", sdf.loc[sdf["Composite"].idxmin(), "Ticker"] if not sdf.empty else "—")

    with st.expander("📊 Full Sentiment Table", expanded=False):
        from core.data_engine import clean_nan
        st.dataframe(
            clean_nan(sdf[["Ticker", "Name", "Composite", "News", "StockTwits", "Reddit", "Analyst", "Google News", "Active Sources", "Signal", "Headlines"]]),
            hide_index=True, use_container_width=True,
        )

st.divider()

# ── Per-ticker detail (fragment = only this section re-runs on selectbox change) ──
@st.fragment
def ticker_detail():
    search_col, pick_col = st.columns([1, 2])
    with search_col:
        search_text = st.text_input("🔍 Search", placeholder="Type ticker or name...",
                                     key="sentiment_search", label_visibility="collapsed")
    with pick_col:
        if search_text:
            filtered_tickers = [t for t in tickers
                               if search_text.upper() in t.upper() or search_text.lower() in names.get(t, "").lower()]
        else:
            filtered_tickers = tickers
        selected = st.selectbox(
            "🔍 Deep-dive into a holding",
            filtered_tickers if filtered_tickers else tickers,
            format_func=lambda t: f"{t}  —  {names.get(t, '')}",
            label_visibility="collapsed",
        )
    if not selected:
        return

    s = sentiments.get(selected, {})
    c = composites.get(selected, {})

    comp_score = c.get("composite_score", 0)
    label      = score_label(comp_score)
    comp_100   = round(comp_score * 100)

    st.markdown(f"### {selected}  ·  {label}  `{comp_100:+d}`")

    sources_active = c.get("sources_active", 1)
    st.caption(f"**{sources_active} of 5 sources active** — weights redistributed dynamically")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric(f"📰 News ({c.get('news', {}).get('weight', '25%')})",
                f"{round(c.get('news', {}).get('score', 0) * 100):+d}")
    col2.metric(f"💬 StockTwits ({c.get('stocktwits', {}).get('weight', '15%')})",
                f"{round(c.get('stocktwits', {}).get('score', 0) * 100):+d}")
    col3.metric(f"📡 Reddit ({c.get('reddit', {}).get('weight', '10%')})",
                f"{round(c.get('reddit', {}).get('score', 0) * 100):+d}")
    col4.metric(f"🏦 Analyst ({c.get('analyst', {}).get('weight', '30%')})",
                f"{round(c.get('analyst', {}).get('score', 0) * 100):+d}")
    col5.metric(f"🌐 G-News ({c.get('google_news', {}).get('weight', '20%')})",
                f"{round(c.get('google_news', {}).get('score', 0) * 100):+d}")

    # StockTwits messages
    st_data = c.get("stocktwits", {})
    if st_data.get("messages", 0) > 0:
        st.markdown(
            f"**StockTwits:** {st_data.get('bulls', 0)} 🐂 bullish · "
            f"{st_data.get('bears', 0)} 🐻 bearish  "
            f"out of {st_data.get('messages', 0)} messages"
        )
        for msg in st_data.get("top_messages", [])[:3]:
            emoji = "🟢" if msg.get("sentiment") == "Bullish" else "🔴" if msg.get("sentiment") == "Bearish" else "⚪"
            ts = msg.get("created_at", "")
            date_str = f" · {ts[:10]}" if ts else ""
            st.caption(f"{emoji}{date_str}  {msg.get('body', '')[:160]}")

    # Reddit posts
    rd_data = c.get("reddit", {})
    if rd_data.get("mentions", 0) > 0:
        st.markdown(f"**Reddit:** {rd_data.get('mentions', 0)} mentions this week")
        for post in rd_data.get("top_posts", [])[:3]:
            score = post.get("score", 0)
            date  = post.get("created_utc", "")
            date_str = f" · {date[:10]}" if date else ""
            st.caption(f"📝{date_str}  {post.get('title', '')}  *(↑{score})*")

    # Analyst consensus
    an_data = c.get("analyst", {})
    if an_data.get("total_recs", 0) > 0:
        bd = an_data.get("breakdown", {})
        st.markdown(
            f"**Analyst Consensus:** {an_data.get('total_recs', 0)} analysts — "
            f"{bd.get('strongBuy', 0)} Strong Buy · {bd.get('buy', 0)} Buy · "
            f"{bd.get('hold', 0)} Hold · {bd.get('sell', 0)} Sell · "
            f"{bd.get('strongSell', 0)} Strong Sell"
        )

    # Google News RSS
    gn_data = c.get("google_news", {})
    if gn_data.get("headlines", 0) > 0:
        st.markdown(f"**Google News:** {gn_data.get('headlines', 0)} headlines analysed")

    # News headlines with dates
    col_pos, col_neg = st.columns(2)
    with col_pos:
        st.markdown("#### 🟢 Positive Headlines")
        headlines_pos = s.get("top_positive", [])
        if headlines_pos:
            for h in headlines_pos[:5]:
                if isinstance(h, dict):
                    date_str = f"*{h.get('date', '')}*  " if h.get("date") else ""
                    st.success(f"{date_str}{h.get('title', h)}")
                else:
                    st.success(h)
        else:
            st.caption("No positive headlines found.")

    with col_neg:
        st.markdown("#### 🔴 Negative Headlines")
        headlines_neg = s.get("top_negative", [])
        if headlines_neg:
            for h in headlines_neg[:5]:
                if isinstance(h, dict):
                    date_str = f"*{h.get('date', '')}*  " if h.get("date") else ""
                    st.error(f"{date_str}{h.get('title', h)}")
                else:
                    st.error(h)
        else:
            st.caption("No negative headlines found.")

ticker_detail()

st.divider()
st.caption(
    "**Methodology:** News 30% · StockTwits 15% · Reddit 10% · Analyst 20% · Google News 25%  ·  "
    "Weights redistribute dynamically when sources return empty data  ·  "
    "Score: −100 (very bearish) → +100 (very bullish)"
)
