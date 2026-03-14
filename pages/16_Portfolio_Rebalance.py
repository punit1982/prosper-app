"""
Prosper – Portfolio Rebalance & Optimization
=============================================
Two modes:
  1. Rule-Based: compare your portfolio against model allocations.
  2. MPT Advanced: efficient frontier and optimal portfolio via Modern Portfolio Theory.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from core.database import get_all_holdings
from core.cio_engine import enrich_portfolio
from core.data_engine import get_ticker_info_batch, get_history
from core.portfolio_optimizer import (
    analyze_current_allocation,
    concentration_risk_check,
    suggest_rebalance,
    MODEL_PORTFOLIOS,
    MODEL_DESCRIPTIONS,
)
from core.settings import SETTINGS

try:
    from core.portfolio_optimizer import get_efficient_frontier, get_optimal_portfolio
    HAS_MPT = True
except ImportError:
    HAS_MPT = False

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.title("⚖️ Portfolio Rebalance & Optimization")

try:
    # -------------------------------------------------------------------
    # Sidebar controls
    # -------------------------------------------------------------------
    mode = st.sidebar.radio(
        "Optimization Mode",
        ["Rule-Based Allocation", "MPT Advanced"],
        index=0,
    )

    if mode == "Rule-Based Allocation":
        model_names = list(MODEL_PORTFOLIOS.keys())
        default_model_idx = model_names.index("Balanced Growth") if "Balanced Growth" in model_names else 0
        selected_model = st.sidebar.selectbox(
            "Model Portfolio",
            model_names,
            index=default_model_idx,
            help="Select an allocation strategy to compare against your portfolio.",
        )
        # Show model description
        desc = MODEL_DESCRIPTIONS.get(selected_model, "")
        if desc:
            st.sidebar.caption(desc)
        # Show target allocation for selected model
        targets = MODEL_PORTFOLIOS.get(selected_model, {})
        if targets:
            st.sidebar.markdown("**Target allocation:**")
            for cat, pct in targets.items():
                st.sidebar.markdown(f"  • {cat}: {pct*100:.0f}%")
    else:
        selected_model = None

    # -------------------------------------------------------------------
    # Load portfolio data
    # -------------------------------------------------------------------
    holdings = get_all_holdings()
    if holdings.empty:
        st.info("No holdings found. Upload a brokerage statement to get started.")
        st.stop()

    with st.spinner("Enriching portfolio data..."):
        enriched = enrich_portfolio(holdings)

    if enriched.empty or "market_value" not in enriched.columns:
        st.warning("Could not enrich holdings. Check your data and try again.")
        st.stop()

    tickers = enriched["ticker"].tolist()
    with st.spinner("Fetching ticker metadata..."):
        info_map = get_ticker_info_batch(tickers)

    # Add sector / country columns for concentration check
    enriched["sector"] = enriched["ticker"].apply(
        lambda t: (info_map.get(t, {}).get("sector") or "Unknown")
    )
    enriched["country"] = enriched["ticker"].apply(
        lambda t: (info_map.get(t, {}).get("country") or "Unknown")
    )

    # -------------------------------------------------------------------
    # Current allocation analysis
    # -------------------------------------------------------------------
    alloc = analyze_current_allocation(enriched, info_map)

    st.header("📊 Current Allocation")

    col1, col2, col3 = st.columns(3)

    _pie_layout = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=30, b=10, l=10, r=10),
        font=dict(color="white"),
        legend=dict(font=dict(color="white")),
    )

    with col1:
        if alloc["asset_class"]:
            fig_ac = px.pie(
                names=list(alloc["asset_class"].keys()),
                values=list(alloc["asset_class"].values()),
                title="Asset Class",
                hole=0.4,
            )
            fig_ac.update_layout(**_pie_layout)
            st.plotly_chart(fig_ac, use_container_width=True)
        else:
            st.caption("No asset class data available.")

    with col2:
        if alloc["sector"]:
            fig_sec = px.pie(
                names=list(alloc["sector"].keys()),
                values=list(alloc["sector"].values()),
                title="Sector",
                hole=0.4,
            )
            fig_sec.update_layout(**_pie_layout)
            st.plotly_chart(fig_sec, use_container_width=True)
        else:
            st.caption("No sector data available.")

    with col3:
        if alloc["geography"]:
            fig_geo = px.pie(
                names=list(alloc["geography"].keys()),
                values=list(alloc["geography"].values()),
                title="Geography",
                hole=0.4,
            )
            fig_geo.update_layout(**_pie_layout)
            st.plotly_chart(fig_geo, use_container_width=True)
        else:
            st.caption("No geography data available.")

    # -------------------------------------------------------------------
    # Concentration risk alerts
    # -------------------------------------------------------------------
    st.header("🚨 Concentration Risk Alerts")

    warnings = concentration_risk_check(enriched)
    if warnings:
        for w in warnings:
            st.warning(
                f"**{w['type']}:** {w['detail']}  "
                f"(threshold: {w['threshold']}%)"
            )
    else:
        st.success("No concentration risks detected. Portfolio is well diversified.")

    # ===================================================================
    # MODE 1 – Rule-Based Rebalancing
    # ===================================================================
    if mode == "Rule-Based Allocation":
        st.header(f"📋 Rebalancing vs. *{selected_model}* Model")

        suggestions = suggest_rebalance(alloc["asset_class"], selected_model)
        if not suggestions:
            st.info("No rebalancing data available.")
        else:
            df_sug = pd.DataFrame(suggestions)
            df_sug.columns = ["Category", "Current %", "Target %", "Diff %", "Action"]

            def _color_action(val):
                if val == "Overweight":
                    return "color: #ff6b6b"  # red
                elif val == "Underweight":
                    return "color: #74b9ff"  # blue
                elif val == "At Target":
                    return "color: #55efc4"  # green
                return ""

            styled = df_sug.style.applymap(
                _color_action, subset=["Action"]
            ).format({
                "Current %": "{:.1f}%",
                "Target %": "{:.1f}%",
                "Diff %": "{:+.1f}%",
            })

            st.dataframe(styled, use_container_width=True, hide_index=True)

            # Suggested actions summary
            st.subheader("Suggested Actions")
            over = [s for s in suggestions if s["action"] == "Overweight"]
            under = [s for s in suggestions if s["action"] == "Underweight"]

            if over:
                st.markdown("**Reduce exposure in:**")
                for s in over:
                    st.markdown(
                        f"- **{s['category']}**: currently {s['current_pct']:.1f}% "
                        f"vs target {s['target_pct']:.1f}% "
                        f"→ trim by ~{abs(s['diff_pct']):.1f}pp"
                    )
            if under:
                st.markdown("**Increase exposure in:**")
                for s in under:
                    st.markdown(
                        f"- **{s['category']}**: currently {s['current_pct']:.1f}% "
                        f"vs target {s['target_pct']:.1f}% "
                        f"→ add ~{abs(s['diff_pct']):.1f}pp"
                    )
            if not over and not under:
                st.success("Portfolio is aligned with the selected model.")

    # ===================================================================
    # MODE 2 – Modern Portfolio Theory
    # ===================================================================
    elif mode == "MPT Advanced":
        st.header("📈 Modern Portfolio Theory – Efficient Frontier")

        if not HAS_MPT:
            st.error(
                "MPT mode requires **scipy**. "
                "Install it with `pip install scipy` and restart."
            )
            st.stop()

        # Prepare weights
        total_mv = enriched["market_value"].sum()
        if total_mv == 0:
            st.warning("Total portfolio value is zero. Cannot run MPT.")
            st.stop()

        ticker_list = enriched["ticker"].tolist()
        weight_list = (enriched["market_value"] / total_mv).tolist()

        period = st.sidebar.selectbox(
            "Historical Period", ["6mo", "1y", "2y", "5y"], index=1
        )

        with st.spinner("Computing efficient frontier (this may take a moment)..."):
            frontier = get_efficient_frontier(
                ticker_list, weight_list, period=period
            )
            optimal = get_optimal_portfolio(
                ticker_list, weight_list, period=period
            )

        if not frontier:
            st.warning(
                "Could not compute frontier. Need at least 2 tickers "
                "with sufficient price history."
            )
            st.stop()

        # Build scatter plot
        df_front = pd.DataFrame(frontier)
        df_front["label"] = df_front["is_current"].apply(
            lambda x: "Your Portfolio" if x else "Simulated"
        )

        fig = go.Figure()

        # Simulated portfolios
        sim = df_front[~df_front["is_current"]]
        fig.add_trace(go.Scatter(
            x=sim["risk"],
            y=sim["return_"],
            mode="markers",
            marker=dict(
                size=6,
                color=sim["sharpe"],
                colorscale="Viridis",
                showscale=True,
                colorbar=dict(title="Sharpe"),
            ),
            text=[f"Sharpe: {s:.2f}" for s in sim["sharpe"]],
            hovertemplate="Risk: %{x:.2%}<br>Return: %{y:.2%}<br>%{text}",
            name="Simulated Portfolios",
        ))

        # Current portfolio
        cur = df_front[df_front["is_current"]]
        if not cur.empty:
            fig.add_trace(go.Scatter(
                x=cur["risk"],
                y=cur["return_"],
                mode="markers",
                marker=dict(size=14, color="#ff6b6b", symbol="star"),
                name="Your Portfolio",
                hovertemplate="Risk: %{x:.2%}<br>Return: %{y:.2%}",
            ))

        # Optimal portfolio
        if optimal:
            fig.add_trace(go.Scatter(
                x=[optimal["risk"]],
                y=[optimal["return_"]],
                mode="markers",
                marker=dict(size=14, color="#55efc4", symbol="diamond"),
                name="Optimal (Max Sharpe)",
                hovertemplate="Risk: %{x:.2%}<br>Return: %{y:.2%}",
            ))

        fig.update_layout(
            title="Efficient Frontier",
            xaxis_title="Annualised Risk (Volatility)",
            yaxis_title="Annualised Return",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"),
            legend=dict(font=dict(color="white")),
            xaxis=dict(tickformat=".0%", gridcolor="rgba(255,255,255,0.1)"),
            yaxis=dict(tickformat=".0%", gridcolor="rgba(255,255,255,0.1)"),
        )

        st.plotly_chart(fig, use_container_width=True)

        # Optimal weights table
        if optimal:
            st.subheader("Optimal Portfolio Weights (Max Sharpe Ratio)")
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Expected Return", f"{optimal['return_']:.2%}")
            col_b.metric("Risk (Volatility)", f"{optimal['risk']:.2%}")
            col_c.metric("Sharpe Ratio", f"{optimal['sharpe']:.2f}")

            opt_df = pd.DataFrame(
                [
                    {"Ticker": t, "Weight": f"{w:.1%}"}
                    for t, w in sorted(
                        optimal["weights"].items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )
                    if w > 0.001
                ]
            )
            st.dataframe(opt_df, use_container_width=True, hide_index=True)

            # Suggested actions
            st.subheader("Suggested Actions")
            cur_weights = dict(zip(ticker_list, weight_list))
            increases = []
            decreases = []
            for t, opt_w in optimal["weights"].items():
                cur_w = cur_weights.get(t, 0)
                diff = opt_w - cur_w
                if diff > 0.01:
                    increases.append((t, cur_w, opt_w, diff))
                elif diff < -0.01:
                    decreases.append((t, cur_w, opt_w, diff))

            if increases:
                st.markdown("**Consider increasing:**")
                for t, cw, ow, d in sorted(increases, key=lambda x: -x[3]):
                    st.markdown(
                        f"- **{t}**: {cw:.1%} → {ow:.1%} (+{d:.1%})"
                    )
            if decreases:
                st.markdown("**Consider reducing:**")
                for t, cw, ow, d in sorted(decreases, key=lambda x: x[3]):
                    st.markdown(
                        f"- **{t}**: {cw:.1%} → {ow:.1%} ({d:.1%})"
                    )
            if not increases and not decreases:
                st.success(
                    "Your current portfolio is close to the optimal allocation."
                )
        else:
            st.warning("Could not determine an optimal portfolio.")

except Exception as _err:
    import traceback
    st.error("⚠️ An error occurred. Please try refreshing.")
    with st.expander("🔍 Error details"):
        st.code(traceback.format_exc())
