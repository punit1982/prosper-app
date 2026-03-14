"""
Prosper AI Analysis — Batch Processing
=======================================
Batch CIO-grade equity analysis for all portfolio holdings.
Individual stock analysis is available in Equity Deep Dive.
"""

import streamlit as st
import pandas as pd

from core.database import (
    get_all_holdings, get_prosper_analysis, save_prosper_analysis,
    get_all_prosper_analyses, delete_prosper_analysis,
)
from core.prosper_analysis import MODEL_TIERS, ARCHETYPE_WEIGHTS, run_analysis
from core.data_engine import get_ticker_info_batch

st.header("Prosper AI Analysis")
st.caption("Batch CIO-grade equity analysis for your entire portfolio. For individual stock analysis, use **Equity Deep Dive**.")

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

_RATING_COLORS = {
    "STRONG BUY": "#00C853",
    "BUY": "#1a9e5c",
    "HOLD": "#f39c12",
    "SELL": "#FF6D00",
    "STRONG SELL": "#DD2C00",
}

_SCORE_LABELS = {
    "revenue_growth": "Revenue Growth",
    "margins": "Margins",
    "moat_ip": "Moat / IP",
    "balance_sheet": "Balance Sheet",
    "valuation": "Valuation",
    "execution": "Execution",
    "risk_adj_upside": "Risk-Adj Upside",
}


def _rating_badge(rating: str) -> str:
    color = _RATING_COLORS.get(rating, "#888")
    return f'<span style="background:{color}; color:white; padding:4px 12px; border-radius:4px; font-weight:700; font-size:1.1em;">{rating}</span>'


def _score_bar(score: float) -> str:
    if score >= 80:
        color = "#00C853"
    elif score >= 65:
        color = "#1a9e5c"
    elif score >= 50:
        color = "#f39c12"
    elif score >= 35:
        color = "#FF6D00"
    else:
        color = "#DD2C00"
    width = min(score, 100)
    return (
        f'<div style="background:#333; border-radius:4px; height:20px; width:100%;">'
        f'<div style="background:{color}; height:20px; border-radius:4px; width:{width}%; '
        f'text-align:center; color:white; font-size:12px; line-height:20px; font-weight:600;">'
        f'{score:.0f}</div></div>'
    )


# ─────────────────────────────────────────
# BATCH ANALYSIS — Main Screen Controls
# ─────────────────────────────────────────

holdings = get_all_holdings()
portfolio_tickers = sorted(holdings["ticker"].dropna().unique().tolist()) if not holdings.empty else []

if not portfolio_tickers:
    st.info("Upload holdings via **Upload Portal** to use batch analysis.")
    st.stop()

# Batch controls on main screen
batch_col1, batch_col2, batch_col3 = st.columns([2, 2, 1])
with batch_col1:
    batch_tier = st.selectbox(
        "Analysis Tier",
        list(MODEL_TIERS.keys()),
        format_func=lambda t: f"{MODEL_TIERS[t]['label']} — {MODEL_TIERS[t]['description']}",
        index=0,  # Default to Quick for batch
        key="batch_tier",
    )
with batch_col2:
    st.markdown(f"**{len(portfolio_tickers)} stocks** in portfolio")
    est_cost = len(portfolio_tickers) * (0.008 if batch_tier == "quick" else 0.04)
    st.caption(f"Estimated cost: ~${est_cost:.2f}")
with batch_col3:
    st.markdown("<br>", unsafe_allow_html=True)
    batch_btn = st.button(f"Analyze All ({len(portfolio_tickers)})", type="primary",
                          use_container_width=True, key="batch_analysis_btn")


# ─────────────────────────────────────────
# RUN BATCH ANALYSIS
# ─────────────────────────────────────────

if batch_btn:
    progress = st.progress(0, text="Starting batch analysis...")

    info_map = {}
    with st.spinner("Fetching market data for all tickers..."):
        info_map = get_ticker_info_batch(portfolio_tickers)

    total = len(portfolio_tickers)
    results = {}
    errors = []

    for i, t in enumerate(portfolio_tickers):
        progress.progress((i + 1) / total, text=f"Analyzing {t} ({i+1}/{total})...")
        info = info_map.get(t, {})
        result, error = run_analysis(t, tier=batch_tier, info=info)
        if result:
            save_prosper_analysis(t, result)
            results[t] = result
        else:
            errors.append(f"{t}: {error}")

    progress.empty()
    st.success(f"Batch complete: {len(results)}/{total} analyzed successfully.")
    if errors:
        with st.expander(f"Errors ({len(errors)})"):
            for e in errors:
                st.caption(e)
    st.rerun()


# ─────────────────────────────────────────
# DISPLAY — All Analysis Results
# ─────────────────────────────────────────

st.divider()
st.subheader("All Analyzed Tickers")

all_analyses = get_all_prosper_analyses()
if all_analyses.empty:
    st.info("No analyses yet. Click **Analyze All** above to run batch analysis.")
else:
    def _color_rating(val):
        color = _RATING_COLORS.get(str(val).strip(), "")
        return f"color: {color}; font-weight: 600" if color else ""

    def _color_score(val):
        try:
            v = float(val)
            if v >= 80: return "color: #00C853; font-weight: 600"
            elif v >= 65: return "color: #1a9e5c; font-weight: 600"
            elif v >= 50: return "color: #f39c12; font-weight: 600"
            elif v >= 35: return "color: #FF6D00; font-weight: 600"
            else: return "color: #DD2C00; font-weight: 600"
        except (TypeError, ValueError):
            return ""

    def _color_upside(val):
        try:
            v = float(val)
            if v > 0: return "color: #1a9e5c; font-weight: 600"
            elif v < 0: return "color: #d63031; font-weight: 600"
        except (TypeError, ValueError):
            pass
        return ""

    display = all_analyses.rename(columns={
        "ticker": "Ticker", "analysis_date": "Date", "rating": "Rating",
        "score": "Score", "archetype_name": "Archetype", "fair_value_base": "Fair Value",
        "upside_pct": "Upside %", "conviction": "Conviction", "thesis": "Thesis",
        "env_net": "Env", "model_used": "Tier",
    })

    if "Fair Value" in display.columns:
        display["Fair Value"] = display["Fair Value"].apply(lambda v: f"${v:,.2f}" if pd.notna(v) else "—")
    if "Upside %" in display.columns:
        display["Upside %"] = display["Upside %"].apply(lambda v: f"{v:+.1f}%" if pd.notna(v) else "—")
    if "Score" in display.columns:
        display["Score"] = display["Score"].apply(lambda v: f"{v:.0f}" if pd.notna(v) else "—")

    styled = display.style
    if "Rating" in display.columns:
        styled = styled.map(_color_rating, subset=["Rating"])
    if "Score" in display.columns:
        styled = styled.map(_color_score, subset=["Score"])
    if "Upside %" in display.columns:
        styled = styled.map(_color_upside, subset=["Upside %"])

    st.dataframe(styled, use_container_width=True, hide_index=True)

    # Summary stats
    total_cost = 0
    for _, row in all_analyses.iterrows():
        a = get_prosper_analysis(row["ticker"])
        if a and a.get("cost_estimate"):
            total_cost += a["cost_estimate"]
    st.caption(f"{len(all_analyses)} tickers analyzed · Total API cost: ${total_cost:.4f}")

    # Delete all button
    if st.button("Clear All Analyses", type="secondary"):
        for _, row in all_analyses.iterrows():
            delete_prosper_analysis(row["ticker"])
        st.rerun()
