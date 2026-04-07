"""
Earnings Calendar — Upcoming Earnings for Portfolio Holdings
=============================================================
Shows earnings dates, expected EPS, and how close each holding is to reporting.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from core.database import get_all_holdings
from core.settings import SETTINGS, enriched_cache_key
from core.cio_engine import enrich_portfolio
from core.data_engine import get_ticker_info_batch

st.markdown(
    "<h2 style='margin-bottom:0'>📅 Earnings Calendar</h2>"
    "<p style='color:#888;margin-top:0'>Upcoming earnings dates for your portfolio holdings</p>",
    unsafe_allow_html=True,
)

# ── Load Portfolio ──
base_currency = SETTINGS.get("base_currency", "USD")
holdings = get_all_holdings()

if holdings.empty:
    st.info("No holdings found. Upload your portfolio first.")
    st.stop()

cache_key = enriched_cache_key(base_currency)
if cache_key in st.session_state and st.session_state[cache_key] is not None:
    enriched = st.session_state[cache_key]
else:
    with st.spinner("Loading portfolio…"):
        enriched = enrich_portfolio(holdings, base_currency)
        st.session_state[cache_key] = enriched

if enriched.empty:
    st.warning("Portfolio data not ready. Visit the Portfolio Dashboard first.")
    st.stop()

# Use resolved tickers for better yfinance coverage
_t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
tickers = enriched[_t_col].tolist()

# ── Fetch Earnings Data ──
@st.cache_data(ttl=3600, show_spinner="Fetching earnings data…")
def _get_earnings_info(tickers_tuple):
    """Fetch earnings dates and EPS data for all tickers."""
    info_map = get_ticker_info_batch(list(tickers_tuple))
    rows = []
    for ticker in tickers_tuple:
        info = info_map.get(ticker, {})
        earnings_date = None
        # yfinance stores earnings dates in different fields
        ed = info.get("earningsDate")
        if ed:
            if isinstance(ed, list) and len(ed) > 0:
                earnings_date = ed[0]
            elif isinstance(ed, (int, float)):
                earnings_date = datetime.fromtimestamp(ed).strftime("%Y-%m-%d")
        if not earnings_date:
            ed_ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
            if ed_ts:
                try:
                    earnings_date = datetime.fromtimestamp(ed_ts).strftime("%Y-%m-%d")
                except (ValueError, OSError, TypeError):
                    pass

        rows.append({
            "ticker": ticker,
            "name": info.get("shortName", info.get("longName", "")),
            "earnings_date": earnings_date,
            "trailing_eps": info.get("trailingEps"),
            "forward_eps": info.get("forwardEps"),
            "recommendation": info.get("recommendationKey", ""),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector", ""),
        })
    return pd.DataFrame(rows)

earnings_df = _get_earnings_info(tuple(tickers))

# ── Merge with portfolio weights ──
if "market_value" in enriched.columns:
    total_mv = pd.to_numeric(enriched["market_value"], errors="coerce").sum()
    weight_map = dict(zip(enriched[_t_col],
                          pd.to_numeric(enriched["market_value"], errors="coerce") / total_mv * 100))
    earnings_df["weight_pct"] = earnings_df["ticker"].map(weight_map).fillna(0)
else:
    earnings_df["weight_pct"] = 0

# ── Parse dates and calculate days until ──
today = datetime.now().date()
earnings_df["earnings_dt"] = pd.to_datetime(earnings_df["earnings_date"], errors="coerce")
earnings_df["days_until"] = earnings_df["earnings_dt"].apply(
    lambda x: (x.date() - today).days if pd.notna(x) else None
)

# ── Filter Controls ──
with st.sidebar:
    st.subheader("📅 Filters")
    show_past = st.checkbox("Show past earnings", value=False)
    days_ahead = st.slider("Days ahead", 7, 180, 60)

# ── Separate into upcoming and unknown ──
has_date = earnings_df[earnings_df["earnings_dt"].notna()].copy()
no_date = earnings_df[earnings_df["earnings_dt"].isna()].copy()

if not has_date.empty:
    if not show_past:
        has_date = has_date[has_date["days_until"] >= -1]  # Include today and yesterday
    upcoming = has_date[has_date["days_until"] <= days_ahead].sort_values("days_until")
else:
    upcoming = pd.DataFrame()

# ── Summary Metrics ──
m1, m2, m3, m4 = st.columns(4)
this_week = upcoming[upcoming["days_until"].between(0, 7)] if not upcoming.empty else pd.DataFrame()
next_2_weeks = upcoming[upcoming["days_until"].between(0, 14)] if not upcoming.empty else pd.DataFrame()

with m1:
    st.metric("Reporting This Week", len(this_week))
with m2:
    st.metric("Next 2 Weeks", len(next_2_weeks))
with m3:
    if not this_week.empty:
        tw_weight = this_week["weight_pct"].sum()
        st.metric("Weight Reporting", f"{tw_weight:.1f}%")
    else:
        st.metric("Weight Reporting", "0%")
with m4:
    st.metric("No Date Available", len(no_date))

st.divider()

# ── Earnings Timeline ──
if not upcoming.empty:
    st.markdown("### 📊 Upcoming Earnings")

    def _urgency_tag(days):
        if days is None:
            return ""
        if days <= 0:
            return "🔴 **TODAY/PAST**"
        elif days <= 3:
            return "🟠 **THIS WEEK**"
        elif days <= 7:
            return "🟡 This week"
        elif days <= 14:
            return "🔵 Next 2 weeks"
        return "⚪"

    display_rows = []
    for _, row in upcoming.iterrows():
        days = row["days_until"]
        urgency = _urgency_tag(days)
        display_rows.append({
            "": urgency,
            "Ticker": row["ticker"],
            "Company": (row["name"] or "")[:30],
            "Earnings Date": row["earnings_dt"].strftime("%b %d, %Y") if pd.notna(row["earnings_dt"]) else "—",
            "Days": f"{int(days)}" if pd.notna(days) else "—",
            "Weight %": f"{row['weight_pct']:.1f}%",
            "Trail EPS": f"${row['trailing_eps']:.2f}" if pd.notna(row['trailing_eps']) else "—",
            "Fwd EPS": f"${row['forward_eps']:.2f}" if pd.notna(row['forward_eps']) else "—",
            "Sector": row["sector"],
        })

    display_df = pd.DataFrame(display_rows)
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Alert for imminent earnings
    imminent = upcoming[upcoming["days_until"].between(0, 3)]
    if not imminent.empty:
        tickers_str = ", ".join(imminent["ticker"].tolist())
        total_weight = imminent["weight_pct"].sum()
        st.warning(
            f"⚠️ **{len(imminent)} holding(s) report within 3 days:** {tickers_str} "
            f"({total_weight:.1f}% of portfolio). Consider reviewing positions before earnings."
        )
else:
    st.info(f"No earnings dates found in the next {days_ahead} days.")

# ── Unknown earnings dates ──
if not no_date.empty and len(no_date) > 0:
    with st.expander(f"📋 {len(no_date)} holdings without earnings date", expanded=False):
        no_date_display = no_date[["ticker", "name", "weight_pct", "sector"]].copy()
        no_date_display["weight_pct"] = no_date_display["weight_pct"].apply(lambda x: f"{x:.1f}%")
        no_date_display.columns = ["Ticker", "Company", "Weight %", "Sector"]
        st.dataframe(no_date_display, use_container_width=True, hide_index=True)
        st.caption("Earnings dates may not be available for ETFs, mutual funds, or some international stocks.")
