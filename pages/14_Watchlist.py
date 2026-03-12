"""
Watchlist
=========
Track stocks you're considering buying — without adding them to your portfolio.
See live prices vs your target entry price.
"""

import math
import streamlit as st
import pandas as pd

from core.database import get_watchlist, add_to_watchlist, remove_from_watchlist
from core.data_engine import get_ticker_info, resolve_ticker, clean_nan
from core.settings import SETTINGS

st.header("👁️ Watchlist")

# ─────────────────────────────────────────
# ADD TO WATCHLIST
# ─────────────────────────────────────────
with st.expander("➕ Add Stock to Watchlist", expanded=False):
    with st.form("add_watchlist", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)

        with col1:
            wl_ticker = st.text_input("Ticker", placeholder="e.g. MSFT, RELIANCE.NS")
        with col2:
            wl_target = st.number_input("Target Price (optional)", min_value=0.0, value=0.0,
                                         step=1.0, format="%.2f",
                                         help="Your desired entry price. Leave 0 to skip.")
        with col3:
            wl_currency = st.selectbox("Currency", ["USD", "AED", "EUR", "GBP", "INR", "SGD", "HKD", "CHF"])

        wl_notes = st.text_input("Notes (optional)", placeholder="e.g. Wait for earnings dip")

        submitted = st.form_submit_button("➕ Add to Watchlist", type="primary", use_container_width=True)

        if submitted:
            if not wl_ticker.strip():
                st.error("Please enter a ticker symbol.")
            else:
                ticker_clean = wl_ticker.strip().upper()
                # Try to auto-fill name from yfinance
                try:
                    resolved = resolve_ticker(ticker_clean, wl_currency)
                    info = get_ticker_info(resolved)
                    wl_name = info.get("shortName") or info.get("longName") or ticker_clean
                except Exception:
                    wl_name = ticker_clean

                add_to_watchlist(
                    ticker=ticker_clean,
                    name=wl_name,
                    currency=wl_currency,
                    target_price=wl_target if wl_target > 0 else None,
                    notes=wl_notes or None,
                )
                st.success(f"✅ {ticker_clean} added to watchlist!")
                st.rerun()

st.divider()

# ─────────────────────────────────────────
# WATCHLIST TABLE
# ─────────────────────────────────────────
watchlist = get_watchlist()

if watchlist.empty:
    st.info("Your watchlist is empty. Add stocks above to start tracking them.")
    st.stop()

st.subheader(f"📋 Tracking {len(watchlist)} Stock(s)")

# Fetch live prices for all watchlist tickers
@st.cache_data(ttl=300, show_spinner="Fetching watchlist prices…")
def _fetch_watchlist_prices(tickers):
    """Fetch current prices for watchlist tickers."""
    results = {}
    for ticker in tickers:
        try:
            resolved = resolve_ticker(ticker)
            info = get_ticker_info(resolved)
            results[ticker] = {
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "change_pct": info.get("regularMarketChangePercent"),
                "name": info.get("shortName") or info.get("longName"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "market_cap": info.get("marketCap"),
                "sector": info.get("sector"),
            }
        except Exception:
            results[ticker] = {}
    return results

tickers = watchlist["ticker"].tolist()
prices = _fetch_watchlist_prices(tuple(tickers))  # tuple for cache hashability

# Build display table
rows = []
for _, item in watchlist.iterrows():
    ticker = item["ticker"]
    price_data = prices.get(ticker, {})
    current = price_data.get("current_price")
    target = item.get("target_price")
    change_pct = price_data.get("change_pct")

    # Calculate gap from target
    gap_pct = None
    if current and target and target > 0:
        gap_pct = ((current - target) / target) * 100

    def _fmt(v, fmt_str="{:,.2f}"):
        try:
            f = float(v)
            if math.isnan(f):
                return "—"
            return fmt_str.format(f)
        except (TypeError, ValueError):
            return "—"

    rows.append({
        "Ticker": ticker,
        "Name": price_data.get("name") or item.get("name", ""),
        "Current Price": _fmt(current),
        "Day Change": f"{change_pct:+.2f}%" if change_pct is not None else "—",
        "Target Price": _fmt(target) if target else "—",
        "Gap from Target": f"{gap_pct:+.1f}%" if gap_pct is not None else "—",
        "52W High": _fmt(price_data.get("52w_high")),
        "52W Low": _fmt(price_data.get("52w_low")),
        "Sector": price_data.get("sector", "—") or "—",
        "Notes": item.get("notes", "") or "",
    })

display_df = pd.DataFrame(rows)

# Summary metrics
items_below_target = sum(1 for r in rows if r["Gap from Target"] != "—" and r["Gap from Target"].startswith("-"))
items_above_target = sum(1 for r in rows if r["Gap from Target"] != "—" and not r["Gap from Target"].startswith("-") and r["Gap from Target"] != "+0.0%")

c1, c2, c3 = st.columns(3)
c1.metric("Watchlist Items", len(watchlist))
c2.metric("Below Target 🟢", items_below_target, help="Stocks currently below your target entry price")
c3.metric("Above Target 🔴", items_above_target, help="Stocks currently above your target entry price")

# Color the gap column
def _color_gap(val):
    if val == "—":
        return ""
    try:
        v = float(val.replace("%", "").replace("+", ""))
        if v < 0:
            return "color: #1a9e5c; font-weight: 600"  # Green = below target (buying opportunity)
        elif v > 0:
            return "color: #d63031; font-weight: 600"  # Red = above target
    except (ValueError, AttributeError):
        pass
    return ""

def _color_change(val):
    if val == "—":
        return ""
    try:
        v = float(val.replace("%", "").replace("+", ""))
        if v > 0:
            return "color: #1a9e5c; font-weight: 600"
        elif v < 0:
            return "color: #d63031; font-weight: 600"
    except (ValueError, AttributeError):
        pass
    return ""

styled = display_df.style.map(_color_gap, subset=["Gap from Target"]).map(_color_change, subset=["Day Change"])
st.dataframe(styled, use_container_width=True, hide_index=True)

st.divider()

# ─────────────────────────────────────────
# REMOVE FROM WATCHLIST
# ─────────────────────────────────────────
with st.expander("🗑️ Remove from Watchlist"):
    remove_labels = [f"{row['ticker']} — {row.get('name', '')}" for _, row in watchlist.iterrows()]
    remove_ids = watchlist["id"].tolist()

    selected = st.selectbox("Select stock to remove", remove_labels)
    if st.button("🗑️ Remove", type="secondary"):
        idx = remove_labels.index(selected)
        remove_from_watchlist(remove_ids[idx])
        st.success(f"Removed from watchlist!")
        st.rerun()

st.divider()
st.caption("ℹ️ Prices auto-refresh every 5 minutes. Green gap = stock is below your target (buying opportunity).")
