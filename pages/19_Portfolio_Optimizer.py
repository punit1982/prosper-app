"""
Prosper Portfolio Optimizer
===========================
Two modes:
  1. Rule-Based — compare current allocation to model portfolios (Ray Dalio, 60/40, etc.)
  2. Modern Portfolio Theory — efficient frontier, maximum-Sharpe-ratio optimal portfolio
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from core.database import get_all_holdings
from core.settings import SETTINGS
from core.cio_engine import enrich_portfolio
from core.data_engine import get_ticker_info_batch
from core.portfolio_optimizer import (
    MODEL_PORTFOLIOS,
    MODEL_DESCRIPTIONS,
    analyze_current_allocation,
    concentration_risk_check,
    suggest_rebalance,
    get_efficient_frontier,
    get_optimal_portfolio,
    HAS_SCIPY,
)

st.markdown(
    "<h2 style='margin-bottom:0'>⚖️ Portfolio Optimizer</h2>"
    "<p style='color:#888;margin-top:0'>Model allocation comparison & Modern Portfolio Theory</p>",
    unsafe_allow_html=True,
)

# ── Load Portfolio ───────────────────────────────────────────────────────────
base_currency = SETTINGS.get("base_currency", "USD")
holdings = get_all_holdings()

if holdings.empty:
    st.info("No holdings found. Upload your portfolio first.")
    st.stop()

cache_key = f"enriched_{base_currency}"
if cache_key in st.session_state and st.session_state[cache_key] is not None and not st.session_state[cache_key].empty:
    enriched = st.session_state[cache_key]
else:
    with st.spinner("Enriching portfolio data…"):
        enriched = enrich_portfolio(holdings, base_currency)
        st.session_state[cache_key] = enriched

if enriched.empty or "market_value" not in enriched.columns:
    st.warning("Portfolio data not ready. Visit the Portfolio Dashboard first to load live prices.")
    st.stop()

enriched["market_value"] = pd.to_numeric(enriched["market_value"], errors="coerce").fillna(0)
enriched = enriched[enriched["market_value"] > 0]

if enriched.empty:
    st.warning("No holdings with valid market values.")
    st.stop()

# ── Fetch Ticker Info ────────────────────────────────────────────────────────
tickers = enriched["ticker"].tolist()

@st.cache_data(ttl=3600, show_spinner="Fetching stock classifications…")
def _get_info(tickers_tuple):
    return get_ticker_info_batch(list(tickers_tuple))

info_map = _get_info(tuple(tickers))

# ── Tab Layout ───────────────────────────────────────────────────────────────
tab_rules, tab_mpt, tab_risk = st.tabs([
    "📋 Model Allocation",
    "📈 Efficient Frontier (MPT)",
    "⚠️ Concentration Risk",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: Rule-Based Model Allocation
# ══════════════════════════════════════════════════════════════════════════════
with tab_rules:
    current_alloc = analyze_current_allocation(enriched, info_map)

    # Show current allocation
    st.markdown("#### Your Current Allocation")
    ac_cols = st.columns(4)
    for i, (dim, label) in enumerate([
        ("asset_class", "Asset Class"),
        ("sector", "Sector"),
        ("geography", "Geography"),
        ("cap_size", "Market Cap"),
    ]):
        with ac_cols[i]:
            alloc = current_alloc.get(dim, {})
            if alloc:
                fig = px.pie(
                    values=list(alloc.values()),
                    names=list(alloc.keys()),
                    title=label,
                    hole=0.4,
                )
                fig.update_layout(
                    height=250,
                    margin=dict(t=35, l=5, r=5, b=5),
                    showlegend=True,
                    legend=dict(font=dict(size=10)),
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                fig.update_traces(textposition="inside", textinfo="percent")
                st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Model portfolio comparison
    st.markdown("#### Compare to Model Portfolios")
    selected_model = st.selectbox(
        "Choose a model portfolio",
        list(MODEL_PORTFOLIOS.keys()),
        index=3,  # Default: Balanced Growth
    )

    if selected_model in MODEL_DESCRIPTIONS:
        st.info(f"**{selected_model}:** {MODEL_DESCRIPTIONS[selected_model]}")

    rebalance = suggest_rebalance(current_alloc.get("asset_class", {}), selected_model)
    if rebalance:
        reb_df = pd.DataFrame(rebalance)

        # Visual comparison bar chart
        fig_compare = go.Figure()
        fig_compare.add_trace(go.Bar(
            name="Current",
            x=reb_df["category"],
            y=reb_df["current_pct"],
            marker_color="#1E88E5",
        ))
        fig_compare.add_trace(go.Bar(
            name=f"Target ({selected_model})",
            x=reb_df["category"],
            y=reb_df["target_pct"],
            marker_color="#FF9800",
        ))
        fig_compare.update_layout(
            barmode="group",
            title="Current vs Target Allocation (%)",
            height=350,
            margin=dict(t=40, l=40, r=20, b=20),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_compare, use_container_width=True)

        # Rebalance suggestions table
        st.markdown("#### Suggested Adjustments")

        def _style_action(val):
            if val == "Overweight":
                return "color: #ff9800"
            elif val == "Underweight":
                return "color: #2196f3"
            return "color: #4caf50"

        display_df = reb_df.rename(columns={
            "category": "Asset Class",
            "current_pct": "Current %",
            "target_pct": "Target %",
            "diff_pct": "Difference %",
            "action": "Action",
        })
        st.dataframe(
            display_df.style.applymap(_style_action, subset=["Action"]),
            use_container_width=True,
            hide_index=True,
        )

        # Summary
        overweight = [r for r in rebalance if r["action"] == "Overweight"]
        underweight = [r for r in rebalance if r["action"] == "Underweight"]
        if overweight:
            st.markdown("**Trim (Overweight):** " + ", ".join(
                f"{r['category']} ({r['diff_pct']:+.1f}%)" for r in overweight
            ))
        if underweight:
            st.markdown("**Add (Underweight):** " + ", ".join(
                f"{r['category']} ({r['diff_pct']:+.1f}%)" for r in underweight
            ))

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: Modern Portfolio Theory
# ══════════════════════════════════════════════════════════════════════════════
with tab_mpt:
    if not HAS_SCIPY:
        st.warning("scipy is required for MPT calculations. Install with: `pip install scipy`")
        st.stop()

    st.markdown("#### Efficient Frontier Analysis")
    st.caption(
        "Using 1-year daily returns to compute the risk-return tradeoff. "
        "The orange dot is your current portfolio; the star is the optimal (max Sharpe) portfolio."
    )

    # Compute weights — use resolved tickers for reliable yfinance lookups
    total_mv = enriched["market_value"].sum()
    _t_col_opt = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
    ticker_list = enriched[_t_col_opt].tolist()
    weight_list = (enriched["market_value"] / total_mv).tolist()

    period = st.selectbox("Lookback Period", ["6mo", "1y", "2y"], index=1)

    if st.button("🔬 Compute Efficient Frontier", type="primary"):
        with st.spinner("Fetching historical returns and computing frontier…"):
            frontier_result = get_efficient_frontier(ticker_list, weight_list, period=period, n_points=200)
            optimal = get_optimal_portfolio(ticker_list, weight_list, period=period)
            st.session_state["mpt_frontier"] = frontier_result
            st.session_state["mpt_optimal"] = optimal

    frontier_result = st.session_state.get("mpt_frontier")
    optimal = st.session_state.get("mpt_optimal")

    # Handle both old list format and new dict format for backward compat
    if isinstance(frontier_result, list):
        frontier_result = {"points": frontier_result, "failed_tickers": [], "error": None}

    if frontier_result:
        if frontier_result.get("error"):
            st.warning(f"Could not compute frontier: {frontier_result['error']}")
        if frontier_result.get("failed_tickers"):
            st.info(f"No price data for: {', '.join(frontier_result['failed_tickers'])}")

    frontier = frontier_result.get("points", []) if frontier_result else []

    if frontier:
        # Separate current portfolio from random points
        current = [p for p in frontier if p.get("is_current")]
        random_pts = [p for p in frontier if not p.get("is_current")]

        fig_ef = go.Figure()

        # Random portfolios (frontier cloud)
        if random_pts:
            rp_df = pd.DataFrame(random_pts)
            fig_ef.add_trace(go.Scatter(
                x=rp_df["risk"] * 100,
                y=rp_df["return_"] * 100,
                mode="markers",
                marker=dict(
                    size=5,
                    color=rp_df["sharpe"],
                    colorscale="Viridis",
                    colorbar=dict(title="Sharpe"),
                    opacity=0.6,
                ),
                name="Random Portfolios",
                hovertemplate="Risk: %{x:.1f}%<br>Return: %{y:.1f}%<extra></extra>",
            ))

        # Current portfolio
        if current:
            cp = current[0]
            fig_ef.add_trace(go.Scatter(
                x=[cp["risk"] * 100],
                y=[cp["return_"] * 100],
                mode="markers",
                marker=dict(size=16, color="#FF9800", symbol="circle", line=dict(width=2, color="white")),
                name=f"Your Portfolio (Sharpe: {cp['sharpe']:.2f})",
            ))

        # Optimal portfolio
        if optimal and optimal.get("risk"):
            fig_ef.add_trace(go.Scatter(
                x=[optimal["risk"] * 100],
                y=[optimal["return_"] * 100],
                mode="markers",
                marker=dict(size=18, color="#00E676", symbol="star", line=dict(width=2, color="white")),
                name=f"Optimal (Sharpe: {optimal['sharpe']:.2f})",
            ))

        fig_ef.update_layout(
            title="Efficient Frontier",
            xaxis_title="Annualised Volatility (%)",
            yaxis_title="Annualised Return (%)",
            height=500,
            margin=dict(t=40, l=50, r=20, b=50),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_ef, use_container_width=True)

        # Stats comparison
        if current and optimal and optimal.get("risk"):
            cp = current[0]
            comp_col1, comp_col2 = st.columns(2)
            with comp_col1:
                st.markdown("#### 🟠 Your Portfolio")
                st.metric("Expected Return", f"{cp['return_']*100:.1f}%")
                st.metric("Volatility (Risk)", f"{cp['risk']*100:.1f}%")
                st.metric("Sharpe Ratio", f"{cp['sharpe']:.2f}")

            with comp_col2:
                st.markdown("#### ⭐ Optimal Portfolio")
                st.metric("Expected Return", f"{optimal['return_']*100:.1f}%",
                          f"{(optimal['return_']-cp['return_'])*100:+.1f}%")
                st.metric("Volatility (Risk)", f"{optimal['risk']*100:.1f}%",
                          f"{(optimal['risk']-cp['risk'])*100:+.1f}%")
                st.metric("Sharpe Ratio", f"{optimal['sharpe']:.2f}",
                          f"{optimal['sharpe']-cp['sharpe']:+.2f}")

            # Optimal weights table
            if optimal.get("weights"):
                st.markdown("#### Optimal Weights")
                opt_rows = []
                for ticker in ticker_list:
                    cur_weight = weight_list[ticker_list.index(ticker)] * 100 if ticker in ticker_list else 0
                    opt_weight = optimal["weights"].get(ticker, 0) * 100
                    diff = opt_weight - cur_weight
                    action = "Hold" if abs(diff) < 1 else ("Buy" if diff > 0 else "Trim")
                    opt_rows.append({
                        "Ticker": ticker,
                        "Current %": round(cur_weight, 1),
                        "Optimal %": round(opt_weight, 1),
                        "Change %": round(diff, 1),
                        "Action": action,
                    })

                opt_df = pd.DataFrame(opt_rows)
                opt_df = opt_df[opt_df["Optimal %"] > 0.5]  # Only show meaningful allocations
                opt_df = opt_df.sort_values("Optimal %", ascending=False)

                def _color_action(val):
                    if val == "Buy":
                        return "color: #4caf50"
                    elif val == "Trim":
                        return "color: #ff9800"
                    return ""

                st.dataframe(
                    opt_df.style.applymap(_color_action, subset=["Action"]),
                    use_container_width=True,
                    hide_index=True,
                )
    else:
        st.caption("Click the button above to compute the efficient frontier.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: Concentration Risk
# ══════════════════════════════════════════════════════════════════════════════
with tab_risk:
    st.markdown("#### Concentration Risk Check")
    st.caption("Flags positions where concentration exceeds prudent thresholds")

    # Add sector/country from info_map for the check
    risk_df = enriched.copy()
    risk_df["sector"] = risk_df["ticker"].apply(lambda t: (info_map.get(t, {}).get("sector") or "Unknown"))
    risk_df["country"] = risk_df["ticker"].apply(lambda t: (info_map.get(t, {}).get("country") or "Unknown"))

    warnings = concentration_risk_check(risk_df)

    if warnings:
        for w in warnings:
            severity = "🔴" if w["value"] > w["threshold"] * 1.5 else "🟡"
            st.markdown(
                f"{severity} **{w['type']}:** {w['detail']}  "
                f"*(threshold: {w['threshold']}%)*"
            )

        # Visualise top holdings by weight
        st.markdown("#### Portfolio Weight Distribution")
        weight_df = enriched[["ticker", "market_value"]].copy()
        weight_df["weight_pct"] = (weight_df["market_value"] / weight_df["market_value"].sum() * 100)
        weight_df = weight_df.sort_values("weight_pct", ascending=True).tail(15)

        fig_w = px.bar(
            weight_df,
            x="weight_pct",
            y="ticker",
            orientation="h",
            color="weight_pct",
            color_continuous_scale=["#1E88E5", "#FF9800", "#d32f2f"],
            labels={"weight_pct": "Weight %", "ticker": ""},
        )
        fig_w.add_vline(x=10, line_dash="dash", line_color="red", annotation_text="10% threshold")
        fig_w.update_layout(
            height=400,
            margin=dict(t=10, l=10, r=10, b=10),
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_w, use_container_width=True)
    else:
        st.success("✅ No concentration risks detected — portfolio is well-diversified!")

    # Herfindahl-Hirschman Index
    total_mv = enriched["market_value"].sum()
    if total_mv > 0:
        weights = enriched["market_value"] / total_mv
        hhi = (weights ** 2).sum() * 10000
        st.metric(
            "Herfindahl-Hirschman Index (HHI)",
            f"{hhi:.0f}",
            help="<1500 = diversified, 1500-2500 = moderate concentration, >2500 = concentrated",
        )
        if hhi < 1500:
            st.caption("📗 Well-diversified portfolio")
        elif hhi < 2500:
            st.caption("📙 Moderate concentration — consider rebalancing")
        else:
            st.caption("📕 Concentrated portfolio — high single-name risk")
