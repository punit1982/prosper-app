"""
Analyst Consensus
=================
Analyst ratings, price targets, and recommendation history
for every holding in the portfolio.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from core.database import get_all_holdings
from core.data_engine import (
    get_ticker_info,
    get_analyst_price_targets, get_recommendations_summary, fmt_large,
)
from core.settings import SETTINGS

st.header("🎯 Analyst Consensus")

holdings = get_all_holdings()
if holdings.empty:
    st.info("Add holdings via **Upload Portal** to see analyst data.")
    st.stop()

# Use resolved tickers when available (e.g. EMAAR.AE instead of EMAAR)
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

# Ticker selector
selected = st.selectbox(
    "Select a holding",
    tickers,
    format_func=lambda t: f"{t} — {names.get(t, '')}",
)

if not selected:
    st.stop()


try:
    st.divider()

    # ── Price Targets ──
    st.subheader("📊 Analyst Price Targets")

    info    = get_ticker_info(selected)
    targets = get_analyst_price_targets(selected)

    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    target_low    = targets.get("low")  or info.get("targetLowPrice")
    target_mean   = targets.get("mean") or info.get("targetMeanPrice")
    target_high   = targets.get("high") or info.get("targetHighPrice")
    num_analysts  = info.get("numberOfAnalystOpinions", "—")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Current Price", f"{current_price:,.2f}" if current_price else "—")
    c2.metric("Target Low", f"{target_low:,.2f}" if target_low else "—")
    c3.metric("Target Mean", f"{target_mean:,.2f}" if target_mean else "—")
    c4.metric("Target High", f"{target_high:,.2f}" if target_high else "—")
    c5.metric("# Analysts", str(num_analysts))

    # Upside / downside
    if current_price and target_mean:
        upside = ((target_mean - current_price) / current_price) * 100
        color = "green" if upside > 0 else "red"
        st.markdown(f"**Consensus upside: :{color}[{upside:+.1f}%]** from current price to mean target")

    # Gauge chart
    if current_price and target_low and target_high:
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=current_price,
            delta={"reference": target_mean, "relative": True, "valueformat": ".1%"},
            gauge={
                "axis": {"range": [target_low * 0.8, target_high * 1.1]},
                "bar": {"color": "#2962FF"},
                "steps": [
                    {"range": [target_low * 0.8, target_low], "color": "#ffcdd2"},
                    {"range": [target_low, target_mean], "color": "#fff9c4"},
                    {"range": [target_mean, target_high], "color": "#c8e6c9"},
                    {"range": [target_high, target_high * 1.1], "color": "#a5d6a7"},
                ],
                "threshold": {
                    "line": {"color": "black", "width": 2},
                    "thickness": 0.8,
                    "value": target_mean,
                },
            },
            title={"text": f"{selected} — Price vs Analyst Range"},
        ))
        fig.update_layout(height=300, margin=dict(t=50, b=20),
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Recommendation Summary ──
    st.subheader("📋 Rating Summary")

    rec_key = info.get("recommendationKey") or ""
    rec_mean_raw = info.get("recommendationMean")

    # Invert scale: 1=Strong Sell → 5=Strong Buy (higher = better conviction to buy)
    rec_mean = (6 - rec_mean_raw) if rec_mean_raw else None

    if rec_key:
        rec_colors = {"strongBuy": "🟢", "buy": "🟢", "hold": "🟡",
                      "sell": "🔴", "strongSell": "🔴", "underperform": "🔴"}
        emoji = rec_colors.get(rec_key.lower().replace("_","").replace(" ",""), "⚪")

        # Build descriptive label: 1 = Strong Sell, 5 = Strong Buy
        if rec_mean:
            if rec_mean >= 4.5:
                conviction = "Strong Buy"
            elif rec_mean >= 3.5:
                conviction = "Buy"
            elif rec_mean >= 2.5:
                conviction = "Hold"
            elif rec_mean >= 1.5:
                conviction = "Sell"
            else:
                conviction = "Strong Sell"
            score_text = f" — **{rec_mean:.1f} / 5** ({conviction})"
        else:
            score_text = ""

        st.markdown(f"### {emoji} Consensus: **{rec_key.upper()}**{score_text}")
        if rec_mean:
            st.caption("ℹ️ Scale: 1 = Strong Sell → 5 = Strong Buy. Higher score = stronger buy conviction.")
    else:
        st.info(f"No analyst consensus rating available for **{selected}**. "
                "This may be due to limited analyst coverage for this stock.")

    # Recommendations summary chart
    summary = get_recommendations_summary(selected)
    if summary and isinstance(summary, list) and len(summary) > 0:
        try:
            sdf = pd.DataFrame(summary)
            if not sdf.empty and "period" in sdf.columns:
                rating_cols = [c for c in sdf.columns if c != "period"]
                sdf_melted = sdf.melt(id_vars="period", value_vars=rating_cols,
                                       var_name="Rating", value_name="Count")
                # Rename to user-friendly labels
                label_map = {
                    "strongBuy": "5 — Strong Buy",
                    "buy": "4 — Buy",
                    "hold": "3 — Hold",
                    "sell": "2 — Sell",
                    "strongSell": "1 — Strong Sell",
                }
                sdf_melted["Rating"] = sdf_melted["Rating"].map(lambda x: label_map.get(x, x))
                color_map = {
                    "5 — Strong Buy": "#00C853",
                    "4 — Buy": "#64DD17",
                    "3 — Hold": "#FFD600",
                    "2 — Sell": "#FF6D00",
                    "1 — Strong Sell": "#DD2C00",
                }
                # Order categories from Strong Buy (top) to Strong Sell (bottom)
                cat_order = ["5 — Strong Buy", "4 — Buy", "3 — Hold", "2 — Sell", "1 — Strong Sell"]
                fig = px.bar(sdf_melted, x="period", y="Count", color="Rating",
                             color_discrete_map=color_map, barmode="stack",
                             category_orders={"Rating": cat_order},
                             title="Recommendation Breakdown by Period")
                fig.update_layout(height=350, margin=dict(t=50, b=20),
                                  plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                  font=dict(color="#FAFAFA"),
                                  legend=dict(font=dict(color="#FAFAFA")))
                st.plotly_chart(fig, use_container_width=True)
        except Exception:
            pass

    st.divider()

    # ── Upgrades & Downgrades (yfinance primary) ──
    st.subheader("⬆️ Recent Upgrades & Downgrades")

    from core.data_engine import get_upgrade_downgrade
    upgrades = get_upgrade_downgrade(selected)

    if upgrades:
        ud_df = pd.DataFrame(upgrades)
        col_renames = {
            "company":            "Analyst Firm",
            "action":             "Action",
            "fromGrade":          "From Grade",
            "toGrade":            "To Grade",
            "gradeTime":          "Date",
            "currentPriceTarget": "Price Target",
            "priorPriceTarget":   "Prior Target",
            "priceTargetAction":  "Target Action",
        }
        ud_df = ud_df.rename(columns={k: v for k, v in col_renames.items() if k in ud_df.columns})
        if "Date" in ud_df.columns:
            ud_df["Date"] = pd.to_datetime(ud_df["Date"], unit="s", errors="coerce").dt.strftime("%Y-%m-%d")
            ud_df = ud_df.sort_values("Date", ascending=False)

        # Show key columns first, extras if available
        priority_cols = ["Date", "Analyst Firm", "Action", "From Grade", "To Grade", "Price Target", "Prior Target"]
        show_cols = [c for c in priority_cols if c in ud_df.columns]
        from core.data_engine import clean_nan
        st.dataframe(clean_nan(ud_df[show_cols].head(25)), use_container_width=True, hide_index=True)

        # AI Summary of recent analyst activity
        if len(ud_df) >= 1:
            try:
                import os
                api_key = os.getenv("ANTHROPIC_API_KEY", "")
                if api_key and api_key != "your_anthropic_api_key_here":
                    import anthropic
                    recent_text = ud_df[show_cols].head(5).to_string(index=False)
                    client = anthropic.Anthropic(api_key=api_key)
                    response = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=200,
                        messages=[{"role": "user", "content":
                            f"Summarize the recent analyst activity for {selected} in 2-3 sentences. "
                            f"Focus on the overall trend (bullish/bearish) and key actions:\n\n{recent_text}"}],
                    )
                    st.info(f"🤖 **AI Summary:** {response.content[0].text}")
            except Exception:
                pass
    else:
        st.info("No upgrade/downgrade data available for this ticker.")


except Exception as _err:
    import traceback
    st.error("⚠️ An error occurred on this page. Please try refreshing.")
    with st.expander("🔍 Error details (for debugging)"):
        st.code(traceback.format_exc())
    if st.button("🔄 Retry", key="page_retry"):
        st.rerun()
