"""
Insider Activity
================
Insider buying/selling summary + full transaction history (past 12 months).
Detects Funds/ETFs and shows appropriate message (no insider data for funds).
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from core.database import get_all_holdings
from core.data_engine import get_insider_transactions, get_insider_purchases, get_ticker_info
from core.settings import SETTINGS

st.header("👤 Insider Activity")

holdings = get_all_holdings()
if holdings.empty:
    st.info("Add holdings via **Upload Portal** to see insider activity.")
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


st.divider()

# ── Detect Funds/ETFs — they don't have insider data ──
try:
    info = get_ticker_info(selected)
except Exception:
    info = {}

quote_type = info.get("quoteType", "EQUITY")
if quote_type in ("ETF", "MUTUALFUND"):
    st.info(
        f"**{selected}** is {'an ETF' if quote_type == 'ETF' else 'a Mutual Fund'}. "
        "Insider activity data is only available for individual stocks (equities). "
        "Funds are managed by fund companies and do not have insider buying/selling data."
    )

    # Still show basic fund info if available
    fund_family = info.get("fundFamily", "")
    category = info.get("category", "")
    total_assets = info.get("totalAssets")
    if fund_family or category:
        st.subheader("ℹ️ Fund Details")
        fc1, fc2, fc3 = st.columns(3)
        if fund_family:
            fc1.metric("Fund Family", fund_family)
        if category:
            fc2.metric("Category", category)
        if total_assets:
            from core.data_engine import fmt_large
            fc3.metric("Total Assets", fmt_large(total_assets))
    st.stop()

# ── Purchase Summary ──
st.subheader("📊 Insider Purchase Summary")
try:
    purchases = get_insider_purchases(selected)
except Exception as e:
    purchases = pd.DataFrame()
    st.warning(f"Could not fetch insider purchase data for {selected}: {e}")

if not purchases.empty:
    from core.data_engine import clean_nan
    # Rename columns to user-friendly labels
    purchase_renames = {
        "Insider Purchases Last 6m": "Period",
        "Purchases": "# Buys",
        "Sales": "# Sells",
        "Net Shares Purchased (Sold)": "Net Shares",
        "Total Insider Shares Held": "Total Shares Held",
        "% Net Shares Purchased (Sold)": "Net Change %",
    }
    purchases = purchases.rename(columns={k: v for k, v in purchase_renames.items() if k in purchases.columns})
    st.dataframe(clean_nan(purchases), use_container_width=True, hide_index=True)
else:
    st.info(f"No insider purchase summary available for **{selected}**.")

st.divider()

# ── Full Transaction History ──
st.subheader("📜 Insider Transactions (Past 12 Months)")

try:
    txns = get_insider_transactions(selected)
except Exception as e:
    txns = pd.DataFrame()
    st.warning(f"Could not fetch insider transactions for {selected}: {e}")

if not txns.empty:
    # Clean up columns
    display_cols = [c for c in txns.columns if c not in ("Unnamed: 0",)]
    txns_display = txns[display_cols].copy()

    # Rename raw yfinance columns to user-friendly names
    COL_RENAMES = {
        "Insider Trading": "Insider Name",
        "Text": "Transaction Type",
        "Start Date": "Transaction Date",
        "Shares": "Shares Traded",
        "Value": "Transaction Value",
    }
    txns_display = txns_display.rename(columns=COL_RENAMES)

    # Show summary metrics
    if "Shares Traded" in txns_display.columns and "Transaction Value" in txns_display.columns:
        type_col = "Transaction Type" if "Transaction Type" in txns_display.columns else None
        if type_col:
            buys  = txns_display[txns_display[type_col].str.contains("Purchase|Buy|Acquisition", case=False, na=False)]
            sells = txns_display[txns_display[type_col].str.contains("Sale|Sell|Disposition", case=False, na=False)]
        else:
            buys = sells = pd.DataFrame()

        # Calculate $ volume for buys and sells
        def _sum_val(df):
            if df.empty or "Transaction Value" not in df.columns:
                return None
            v = pd.to_numeric(df["Transaction Value"], errors="coerce").dropna()
            return float(v.sum()) if len(v) > 0 else None

        buy_val  = _sum_val(buys)
        sell_val = _sum_val(sells)

        def _fmt_val(v):
            if v is None: return "—"
            if abs(v) >= 1e9: return f"${v/1e9:.1f}B"
            if abs(v) >= 1e6: return f"${v/1e6:.1f}M"
            if abs(v) >= 1e3: return f"${v/1e3:.0f}K"
            return f"${v:,.0f}"

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Transactions", len(txns_display))
        c2.metric("📈 Buy Count",   len(buys))
        c3.metric("📈 Buy Volume",  _fmt_val(buy_val))
        c4.metric("📉 Sell Count",  len(sells))
        c5.metric("📉 Sell Volume", _fmt_val(sell_val))

    # Bar chart of transactions over time
    date_col = "Transaction Date" if "Transaction Date" in txns_display.columns else None
    if date_col:
        try:
            chart_df = txns_display.copy()
            chart_df["Date"] = pd.to_datetime(chart_df[date_col], errors="coerce")
            chart_df = chart_df.dropna(subset=["Date"]).sort_values("Date")

            if not chart_df.empty and "Shares Traded" in chart_df.columns:
                fig = px.bar(
                    chart_df, x="Date", y="Shares Traded",
                    color="Transaction Type" if "Transaction Type" in chart_df.columns else None,
                    title=f"Insider Transactions — {selected}",
                )
                fig.update_layout(height=400, margin=dict(t=50, b=20),
                                  plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
        except Exception:
            st.caption("ℹ️ Chart could not be generated for this data.")

    from core.data_engine import clean_nan
    st.dataframe(clean_nan(txns_display), use_container_width=True, hide_index=True)
else:
    st.info(f"No insider transaction data available for **{selected}** in the past 12 months.")

st.divider()

# ── Key Insider Info ──
st.subheader("ℹ️ Key Insider Details")
insider_pct = info.get("heldPercentInsiders")
inst_pct    = info.get("heldPercentInstitutions")

if insider_pct is not None or inst_pct is not None:
    c1, c2 = st.columns(2)
    if insider_pct is not None:
        c1.metric("% Held by Insiders", f"{insider_pct*100:.2f}%")
    if inst_pct is not None:
        c2.metric("% Held by Institutions", f"{inst_pct*100:.2f}%")
else:
    st.caption("Ownership percentage data not available for this ticker.")
