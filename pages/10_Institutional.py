"""
Institutional Holdings
======================
Top institutional holders, mutual fund holders, and ownership breakdown.
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from core.database import get_all_holdings
from core.data_engine import (
    get_institutional_holders, get_major_holders,
    get_mutualfund_holders, get_ticker_info, fmt_large, clean_nan,
)
from core.settings import SETTINGS

st.header("🏛️ Institutional Holdings")

holdings = get_all_holdings()
if holdings.empty:
    st.info("Add holdings via **Upload Portal** to see institutional data.")
    st.stop()

# Use resolved tickers when available
base_currency = SETTINGS.get("base_currency", "USD")
cache_key = f"enriched_{base_currency}"
if cache_key in st.session_state:
    from core.data_engine import apply_global_filter
    enriched = apply_global_filter(st.session_state[cache_key])
    t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
    tickers = sorted(enriched[t_col].dropna().tolist(), key=str.upper)
    names = dict(zip(enriched[t_col], enriched["name"]))
else:
    tickers = sorted(holdings["ticker"].dropna().tolist(), key=str.upper)
    names = dict(zip(holdings["ticker"], holdings["name"]))

selected = st.selectbox("Select holding", tickers,
                         format_func=lambda t: f"{t} — {names.get(t, '')}")

if not selected:
    st.stop()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _fmt_shares(val):
    """Format share count to readable number."""
    try:
        v = float(val)
        if abs(v) >= 1e9:
            return f"{v/1e9:.1f}B"
        if abs(v) >= 1e6:
            return f"{v/1e6:.1f}M"
        if abs(v) >= 1e3:
            return f"{v/1e3:,.0f}K"
        return f"{v:,.0f}"
    except (TypeError, ValueError):
        return str(val) if val else "—"

def _fmt_pct(val):
    """Format percentage value (0.05 → '5.00%', already percentage → as-is)."""
    try:
        v = float(val)
        if v > 1:  # already a percentage like 45.2
            return f"{v:.2f}%"
        return f"{v*100:.2f}%"
    except (TypeError, ValueError):
        # Already a string like "45.20%" — return as-is
        s = str(val).strip()
        if s.endswith("%"):
            return s
        return str(val) if val else "—"

def _fmt_value(val):
    """Format dollar value."""
    try:
        v = float(val)
        if abs(v) >= 1e12:
            return f"${v/1e12:.1f}T"
        if abs(v) >= 1e9:
            return f"${v/1e9:.1f}B"
        if abs(v) >= 1e6:
            return f"${v/1e6:.1f}M"
        if abs(v) >= 1e3:
            return f"${v/1e3:.0f}K"
        return f"${v:,.0f}"
    except (TypeError, ValueError):
        return str(val) if val else "—"

def _fmt_date(val):
    """Format date to readable string."""
    try:
        return pd.to_datetime(val).strftime("%b %d, %Y")
    except Exception:
        return str(val) if val else "—"

def _format_holders_table(df):
    """Format an institutional/mutual fund holders DataFrame with clean columns."""
    if df.empty:
        return df

    display = df.copy()

    # Rename columns to simple, readable names
    col_renames = {
        "Holder":        "Name",
        "Shares":        "Shares Held",
        "Date Reported": "Reported On",
        "% Out":         "% Ownership",
        "pctHeld":       "% Ownership",
        "Value":         "Value ($)",
    }
    display = display.rename(columns={k: v for k, v in col_renames.items() if k in display.columns})

    # Format numeric columns
    if "Shares Held" in display.columns:
        display["Shares Held"] = display["Shares Held"].apply(_fmt_shares)
    if "% Ownership" in display.columns:
        display["% Ownership"] = display["% Ownership"].apply(_fmt_pct)
    if "Value ($)" in display.columns:
        display["Value ($)"] = display["Value ($)"].apply(_fmt_value)
    if "Reported On" in display.columns:
        display["Reported On"] = display["Reported On"].apply(_fmt_date)

    return display


try:
    st.divider()

    # ── Ownership Breakdown ──
    st.subheader("📊 Ownership Breakdown")
    try:
        major = get_major_holders(selected)
    except Exception:
        major = pd.DataFrame()

    if not major.empty:
        # yfinance major_holders returns a 2-column DataFrame:
        #   Column 0 = value (e.g. "1.49%"), Column 1 = description
        # Display as clean metric cards instead of a raw table

        # Try to extract key values from the major_holders data
        info = get_ticker_info(selected)
        insider_pct = info.get("heldPercentInsiders", 0) or 0
        inst_pct    = info.get("heldPercentInstitutions", 0) or 0
        float_pct   = info.get("floatShares")
        shares_out  = info.get("sharesOutstanding")

        # Display as metrics (much cleaner than raw table)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Insider Ownership", f"{insider_pct*100:.2f}%" if insider_pct else "—")
        with col2:
            st.metric("Institutional Ownership", f"{inst_pct*100:.2f}%" if inst_pct else "—")
        with col3:
            other = max(0, 1.0 - insider_pct - inst_pct)
            st.metric("Retail / Other", f"{other*100:.2f}%" if (insider_pct or inst_pct) else "—")

        # Additional row of metrics
        if shares_out or float_pct:
            c1, c2 = st.columns(2)
            if shares_out:
                c1.metric("Total Shares Outstanding", _fmt_shares(shares_out))
            if float_pct:
                c2.metric("Public Float", _fmt_shares(float_pct))

        # Pie chart
        if insider_pct > 0 or inst_pct > 0:
            other_pct = max(0, 1.0 - insider_pct - inst_pct)
            fig = px.pie(
                values=[insider_pct * 100, inst_pct * 100, other_pct * 100],
                names=["Insiders", "Institutions", "Other / Retail"],
                title=f"{selected} — Ownership Split",
                hole=0.4,
                color_discrete_sequence=["#FF6D00", "#2962FF", "#78909C"],
            )
            fig.update_traces(
                textposition="inside",
                textinfo="percent+label",
                textfont=dict(color="white", size=13),
            )
            fig.update_layout(
                height=380,
                margin=dict(t=50, b=20),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#FAFAFA"),
                legend=dict(font=dict(color="#FAFAFA")),
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No ownership breakdown data available.")

    st.divider()

    # ── Top Institutional Holders ──
    st.subheader("🏛️ Top Institutional Holders")
    try:
        inst = get_institutional_holders(selected)
    except Exception:
        inst = pd.DataFrame()

    if not inst.empty:
        inst_display = _format_holders_table(inst)
        st.dataframe(clean_nan(inst_display), use_container_width=True, hide_index=True)
    else:
        st.info("No institutional holder data available for this ticker.")

    st.divider()

    # ── Top Mutual Fund Holders ──
    st.subheader("📈 Top Mutual Fund Holders")
    try:
        mf = get_mutualfund_holders(selected)
    except Exception:
        mf = pd.DataFrame()

    if not mf.empty:
        mf_display = _format_holders_table(mf)
        st.dataframe(clean_nan(mf_display), use_container_width=True, hide_index=True)
    else:
        st.info("No mutual fund holder data available for this ticker.")

    st.divider()
    st.caption(
        "ℹ️ Institutional and mutual fund holdings are reported quarterly. "
        "Data may be up to 3 months old. Source: SEC 13-F filings via Yahoo Finance."
    )


except Exception as _err:
    import traceback
    st.error("⚠️ An error occurred on this page. Please try refreshing.")
    with st.expander("🔍 Error details (for debugging)"):
        st.code(traceback.format_exc())
    if st.button("🔄 Retry", key="page_retry"):
        st.rerun()
