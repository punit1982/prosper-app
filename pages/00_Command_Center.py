"""
Prosper Command Center — Executive Dashboard
=============================================
The CIO's morning view: portfolio health at a glance, top movers,
concentration alerts, and AI-generated daily briefing.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

from core.database import (
    get_all_holdings, get_nav_history, get_all_prosper_analyses,
    get_total_realized_pnl,
)
from core.settings import SETTINGS, get_api_key
from core.cio_engine import enrich_portfolio

# ── Page Header ──────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='margin-bottom:0'>Prosper</h1>"
    "<p style='color:#888;font-size:1.1rem;margin-top:0'>Command Center</p>",
    unsafe_allow_html=True,
)

# ── Load Portfolio Data ──────────────────────────────────────────────────────
base_currency = SETTINGS.get("base_currency", "USD")
holdings = get_all_holdings()

if holdings.empty:
    st.info("👋 **Welcome to Prosper!** Upload your first brokerage screenshot or CSV to get started.")
    st.page_link("pages/1_Upload_Portal.py", label="📤 Go to Upload Portal", icon="📤")
    st.stop()

# ── Enrich Portfolio (use cache if available) ────────────────────────────────
cache_key = f"enriched_{base_currency}"
if cache_key in st.session_state and st.session_state[cache_key] is not None and not st.session_state[cache_key].empty:
    enriched = st.session_state[cache_key]
else:
    with st.spinner("Loading portfolio data…"):
        enriched = enrich_portfolio(holdings, base_currency)
        st.session_state[cache_key] = enriched

if enriched.empty:
    st.warning("Could not load portfolio data. Try visiting the Portfolio Dashboard first.")
    st.stop()

# ── Compute Key Metrics ──────────────────────────────────────────────────────
total_value = pd.to_numeric(enriched.get("market_value"), errors="coerce").dropna().sum()
total_cost = pd.to_numeric(enriched.get("cost_basis"), errors="coerce").dropna().sum()
unrealized_pnl = pd.to_numeric(enriched.get("unrealized_pnl"), errors="coerce").dropna().sum()
day_gain = pd.to_numeric(enriched.get("day_gain"), errors="coerce").dropna().sum()
realized_pnl = get_total_realized_pnl()
holdings_count = len(enriched)

unrealized_pct = (unrealized_pnl / total_cost * 100) if total_cost > 0 else 0
day_pct = (day_gain / (total_value - day_gain) * 100) if (total_value - day_gain) > 0 else 0

# ── Hero Metrics Row ─────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
m1.metric(
    "Portfolio Value",
    f"{base_currency} {total_value:,.0f}",
    f"{day_gain:+,.0f} today ({day_pct:+.1f}%)",
)
m2.metric(
    "Unrealized P&L",
    f"{unrealized_pnl:+,.0f}",
    f"{unrealized_pct:+.1f}%",
)
m3.metric(
    "Realized P&L",
    f"{realized_pnl:+,.0f}" if realized_pnl != 0 else "—",
)
m4.metric(
    "Holdings",
    f"{holdings_count}",
    f"{len(enriched['currency'].unique())} currencies" if "currency" in enriched.columns else "",
)

st.divider()

# ── Top Movers & Alerts ─────────────────────────────────────────────────────
col_movers, col_alerts = st.columns([3, 2])

with col_movers:
    st.markdown("### 📊 Top Movers Today")

    if "day_change_pct" in enriched.columns:
        movers_df = enriched[["ticker", "name", "day_change_pct", "market_value"]].copy()
        movers_df["day_change_pct"] = pd.to_numeric(movers_df["day_change_pct"], errors="coerce")
        movers_df = movers_df.dropna(subset=["day_change_pct"])

        if not movers_df.empty:
            gainers = movers_df.nlargest(3, "day_change_pct")
            losers = movers_df.nsmallest(3, "day_change_pct")

            g_col, l_col = st.columns(2)
            with g_col:
                st.markdown("**🟢 Gainers**")
                for _, row in gainers.iterrows():
                    pct = row["day_change_pct"]
                    label = row.get("name", row["ticker"])
                    if isinstance(label, str) and len(label) > 20:
                        label = label[:18] + "…"
                    st.markdown(
                        f"<div style='padding:6px 10px;margin:4px 0;border-radius:8px;"
                        f"background:rgba(0,200,83,0.1);border-left:3px solid #00c853'>"
                        f"<b>{row['ticker']}</b> <span style='color:#00c853'>{pct:+.1f}%</span>"
                        f"<br><small style='color:#888'>{label}</small></div>",
                        unsafe_allow_html=True,
                    )

            with l_col:
                st.markdown("**🔴 Losers**")
                for _, row in losers.iterrows():
                    pct = row["day_change_pct"]
                    label = row.get("name", row["ticker"])
                    if isinstance(label, str) and len(label) > 20:
                        label = label[:18] + "…"
                    st.markdown(
                        f"<div style='padding:6px 10px;margin:4px 0;border-radius:8px;"
                        f"background:rgba(255,23,68,0.1);border-left:3px solid #ff1744'>"
                        f"<b>{row['ticker']}</b> <span style='color:#ff1744'>{pct:+.1f}%</span>"
                        f"<br><small style='color:#888'>{label}</small></div>",
                        unsafe_allow_html=True,
                    )
        else:
            st.caption("No price data available yet.")
    else:
        st.caption("Visit Portfolio Dashboard to load live prices.")

with col_alerts:
    st.markdown("### ⚠️ Attention Required")
    alerts = []

    # Concentration alerts
    if "market_value" in enriched.columns:
        mv = pd.to_numeric(enriched["market_value"], errors="coerce").fillna(0)
        total = mv.sum()
        if total > 0:
            weights = mv / total
            for idx, w in weights.items():
                if w > 0.15:
                    ticker = enriched.loc[idx, "ticker"]
                    alerts.append(f"🔴 **{ticker}** is {w:.0%} of portfolio (>15%)")

            # Sector concentration
            if "sector" in enriched.columns:
                sector_weights = enriched.copy()
                sector_weights["mv"] = mv
                sector_agg = sector_weights.groupby("sector")["mv"].sum() / total
                for sec, sw in sector_agg.items():
                    if sw > 0.35 and sec not in ("", "Unknown", None):
                        alerts.append(f"🟡 **{sec}** sector is {sw:.0%} (>35%)")

    # Stocks down significantly
    if "day_change_pct" in enriched.columns:
        big_drops = enriched[pd.to_numeric(enriched["day_change_pct"], errors="coerce") < -3]
        for _, row in big_drops.iterrows():
            pct = float(row["day_change_pct"])
            alerts.append(f"📉 **{row['ticker']}** down {pct:.1f}% today")

    # Recent AI analysis count
    try:
        analyses = get_all_prosper_analyses()
        if not analyses.empty:
            cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            recent = analyses[analyses["analysis_date"] >= cutoff]
            coverage = len(recent) / holdings_count * 100 if holdings_count > 0 else 0
            if coverage < 50:
                alerts.append(f"🤖 Only {coverage:.0f}% of holdings analysed in last 7 days")
    except Exception:
        pass

    if alerts:
        for alert in alerts[:6]:
            st.markdown(alert)
    else:
        st.success("✅ No alerts — portfolio looks healthy")

st.divider()

# ── Portfolio Heat Map ────────────────────────────────────────────────────────
st.markdown("### 🗺️ Portfolio Heat Map")
st.caption("Box size = position weight · Color = daily performance")

if "day_change_pct" in enriched.columns and "market_value" in enriched.columns:
    hm_df = enriched[["ticker", "name", "market_value", "day_change_pct"]].copy()
    hm_df["market_value"] = pd.to_numeric(hm_df["market_value"], errors="coerce").fillna(0)
    hm_df["day_change_pct"] = pd.to_numeric(hm_df["day_change_pct"], errors="coerce").fillna(0)
    hm_df = hm_df[hm_df["market_value"] > 0]
    hm_df["label"] = hm_df["ticker"] + "<br>" + hm_df["day_change_pct"].apply(lambda x: f"{x:+.1f}%")

    if not hm_df.empty:
        fig = px.treemap(
            hm_df,
            path=["label"],
            values="market_value",
            color="day_change_pct",
            color_continuous_scale=["#d32f2f", "#ff9800", "#424242", "#66bb6a", "#2e7d32"],
            color_continuous_midpoint=0,
            hover_data={"market_value": ":,.0f", "day_change_pct": ":.2f%"},
        )
        fig.update_layout(
            margin=dict(t=10, l=10, r=10, b=10),
            height=400,
            coloraxis_colorbar=dict(title="Day %"),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        fig.update_traces(
            textfont=dict(size=14, color="white"),
            textposition="middle center",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Insufficient data for heat map.")
else:
    st.caption("Visit Portfolio Dashboard first to load live prices.")

st.divider()

# ── Daily AI Briefing ────────────────────────────────────────────────────────
st.markdown("### 🧠 Daily AI Briefing")

briefing_cache_key = f"daily_briefing_{datetime.now().strftime('%Y-%m-%d')}_{base_currency}"

def generate_briefing():
    """Generate the daily AI briefing using Claude."""
    api_key = get_api_key("ANTHROPIC_API_KEY")
    if not api_key:
        return "⚠️ Anthropic API key not configured. Add it in Settings to enable AI briefings."

    try:
        import anthropic
        from core.settings import call_claude

        client = anthropic.Anthropic(api_key=api_key)

        # Build context for Claude
        portfolio_summary = []
        for _, row in enriched.head(20).iterrows():
            ticker = row.get("ticker", "?")
            name = row.get("name", "")
            mv = pd.to_numeric(row.get("market_value"), errors="coerce")
            pnl = pd.to_numeric(row.get("unrealized_pnl"), errors="coerce")
            day_chg = pd.to_numeric(row.get("day_change_pct"), errors="coerce")
            weight = (mv / total_value * 100) if total_value > 0 and pd.notna(mv) else 0
            portfolio_summary.append(
                f"{ticker} ({name[:25]}): weight={weight:.1f}%, "
                f"day={day_chg:+.1f}% unrealized_pnl={pnl:+,.0f}" if pd.notna(day_chg) else
                f"{ticker} ({name[:25]}): weight={weight:.1f}%"
            )

        # Recent AI analyses
        analysis_context = ""
        try:
            analyses = get_all_prosper_analyses()
            if not analyses.empty:
                recent = analyses.sort_values("analysis_date", ascending=False).head(10)
                analysis_lines = []
                for _, a in recent.iterrows():
                    analysis_lines.append(
                        f"{a['ticker']}: rating={a.get('rating','?')}, "
                        f"score={a.get('score','?')}, thesis={str(a.get('thesis',''))[:80]}"
                    )
                analysis_context = "\n".join(analysis_lines)
        except Exception:
            pass

        # Concentration warnings
        conc_warnings = []
        if total_value > 0:
            for _, row in enriched.iterrows():
                mv = pd.to_numeric(row.get("market_value"), errors="coerce")
                if pd.notna(mv) and mv / total_value > 0.12:
                    conc_warnings.append(f"{row['ticker']}: {mv/total_value:.0%}")

        prompt = f"""You are the Chief Investment Officer of a family office. Generate a concise morning briefing for this portfolio.

PORTFOLIO OVERVIEW:
- Total Value: {base_currency} {total_value:,.0f}
- Today's P&L: {day_gain:+,.0f} ({day_pct:+.1f}%)
- Unrealized P&L: {unrealized_pnl:+,.0f} ({unrealized_pct:+.1f}%)
- Holdings: {holdings_count} across {len(enriched['currency'].unique()) if 'currency' in enriched.columns else 1} currencies

TOP HOLDINGS (by weight):
{chr(10).join(portfolio_summary)}

{f'CONCENTRATION WARNINGS: {", ".join(conc_warnings)}' if conc_warnings else ''}

{f'RECENT AI ANALYSES:{chr(10)}{analysis_context}' if analysis_context else ''}

FORMAT YOUR RESPONSE EXACTLY AS:

**Portfolio Pulse:** [1-line health check — how is the portfolio doing today vs recent trend]

**Top Movers:** [2-3 bullets on why the biggest gainers/losers moved today]

**Attention Required:** [2-3 bullets on stocks needing attention — concentration risk, big drawdowns, thesis changes. Say "None — portfolio looks well-positioned" if nothing urgent]

**Action Items:** [2-3 specific, actionable suggestions like "Consider trimming X" or "Review thesis on Y given recent downgrade"]

Keep it sharp and actionable. No fluff. This is for a sophisticated investor who wants signal, not noise."""

        response = call_claude(
            client,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            preferred_model="claude-opus-4-5",
        )
        return response.content[0].text

    except Exception as e:
        return f"⚠️ Could not generate briefing: {str(e)[:100]}"


# Show briefing
if briefing_cache_key in st.session_state:
    st.info(f"🤖 {st.session_state[briefing_cache_key]}")
    if st.button("🔄 Refresh Briefing"):
        with st.spinner("Generating fresh AI briefing…"):
            st.session_state[briefing_cache_key] = generate_briefing()
            st.rerun()
else:
    if st.button("🧠 Generate Today's Briefing", type="primary", use_container_width=True):
        with st.spinner("Your AI CIO is analysing the portfolio…"):
            st.session_state[briefing_cache_key] = generate_briefing()
            st.rerun()
    st.caption("Click above to get your personalised AI morning brief")

st.divider()

# ── Quick Navigation Cards ───────────────────────────────────────────────────
st.markdown("### 🧭 Quick Navigation")
n1, n2, n3, n4 = st.columns(4)
with n1:
    st.page_link("pages/2_Portfolio_Dashboard.py", label="📊 Portfolio Dashboard", icon="📊")
    st.caption("Live prices & P&L")
with n2:
    st.page_link("pages/18_Equity_Deep_Dive.py", label="🔬 Equity Research", icon="🔬")
    st.caption("360° stock analysis")
with n3:
    st.page_link("pages/3_Portfolio_News.py", label="📰 Portfolio News", icon="📰")
    st.caption("AI-summarised news")
with n4:
    st.page_link("pages/19_Portfolio_Optimizer.py", label="⚖️ Optimizer", icon="⚖️")
    st.caption("Rebalance & MPT")

# ── NAV History Sparkline ─────────────────────────────────────────────────────
nav_history = get_nav_history(base_currency)
if not nav_history.empty and len(nav_history) > 1:
    st.divider()
    st.markdown("### 📈 Portfolio Value History")
    nav_history["date"] = pd.to_datetime(nav_history["date"])
    fig_nav = go.Figure()
    fig_nav.add_trace(go.Scatter(
        x=nav_history["date"],
        y=nav_history["total_value"],
        mode="lines+markers",
        line=dict(color="#1E88E5", width=2),
        marker=dict(size=4),
        fill="tozeroy",
        fillcolor="rgba(30,136,229,0.1)",
    ))
    fig_nav.update_layout(
        height=250,
        margin=dict(t=10, l=10, r=10, b=10),
        xaxis_title="",
        yaxis_title=base_currency,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_nav, use_container_width=True)
