"""
Prosper Command Center v2 — Executive Dashboard
=================================================
Bloomberg-style CIO morning view: market context, portfolio pulse,
performance attribution, FORTRESS regime, alerts, and AI briefing.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

from core.database import (
    get_all_holdings, get_nav_history, get_all_prosper_analyses,
    get_total_realized_pnl, get_all_cash_positions,
)
from core.settings import SETTINGS, get_api_key
from core.cio_engine import enrich_portfolio
from core.data_engine import fmt_large

# ── Page Header ──────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='margin-bottom:0;letter-spacing:-1px'>Prosper</h1>"
    "<p style='color:#888;font-size:1.05rem;margin-top:0'>"
    f"Command Center &nbsp;·&nbsp; {datetime.now().strftime('%A, %B %d %Y')}</p>",
    unsafe_allow_html=True,
)

# ── Load Portfolio Data ──────────────────────────────────────────────────────
base_currency = SETTINGS.get("base_currency", "USD")
holdings = get_all_holdings()

if holdings.empty:
    st.info("Welcome to Prosper! Upload your first brokerage screenshot or CSV to get started.")
    st.page_link("pages/1_Upload_Portal.py", label="Go to Upload Portal", icon="📤")
    st.stop()

# ── Enrich Portfolio (use cache if available) ────────────────────────────────
cache_key = f"enriched_{base_currency}"
if cache_key in st.session_state and st.session_state[cache_key] is not None and not st.session_state[cache_key].empty:
    enriched = st.session_state[cache_key]
else:
    with st.spinner("Loading portfolio data..."):
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

# Cash positions
cash_positions = get_all_cash_positions()
total_cash = float(cash_positions["amount"].sum()) if not cash_positions.empty else 0.0
net_portfolio = total_value + total_cash

unrealized_pct = (unrealized_pnl / total_cost * 100) if total_cost > 0 else 0
day_pct = (day_gain / (total_value - day_gain) * 100) if (total_value - day_gain) > 0 else 0

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: MARKET CONTEXT BAR
# ══════════════════════════════════════════════════════════════════════════════

# FORTRESS Regime detection
regime_name = "Unknown"
regime_color = "#888"
try:
    from core.fortress import detect_regime, REGIME_NAMES, REGIME_COLORS
    from core.database import get_fortress_state
    vix_val = float(get_fortress_state("vix") or 18)
    pmi_val = float(get_fortress_state("pmi") or 52)
    regime_result = detect_regime(vix=vix_val, pmi=pmi_val)
    regime = regime_result["regime"]
    regime_name = REGIME_NAMES.get(regime, "Unknown")
    regime_color = REGIME_COLORS.get(regime, "#888")
except Exception:
    pass

# Market context bar
st.markdown(
    f"<div style='display:flex;gap:24px;padding:10px 16px;background:rgba(255,255,255,0.03);"
    f"border-radius:10px;border:1px solid rgba(255,255,255,0.08);margin-bottom:16px;flex-wrap:wrap;align-items:center'>"
    f"<span style='font-size:0.85rem;color:#999'>FORTRESS Regime:</span>"
    f"<span style='background:{regime_color};color:white;padding:3px 12px;border-radius:12px;"
    f"font-weight:700;font-size:0.85rem'>{regime_name}</span>"
    f"<span style='color:#666'>|</span>"
    f"<span style='font-size:0.85rem;color:#999'>Holdings: <b style=\"color:#eee\">{holdings_count}</b></span>"
    f"<span style='color:#666'>|</span>"
    f"<span style='font-size:0.85rem;color:#999'>Currencies: <b style=\"color:#eee\">"
    f"{len(enriched['currency'].unique()) if 'currency' in enriched.columns else 1}</b></span>"
    f"<span style='color:#666'>|</span>"
    f"<span style='font-size:0.85rem;color:#999'>Cash: <b style=\"color:#eee\">"
    f"{base_currency} {total_cash:,.0f}</b></span>"
    f"</div>",
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: HERO METRICS ROW
# ══════════════════════════════════════════════════════════════════════════════
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric(
    "Net Portfolio Value",
    f"{base_currency} {net_portfolio:,.0f}",
    f"{day_gain:+,.0f} today ({day_pct:+.1f}%)",
)
m2.metric(
    "Unrealized P&L",
    f"{base_currency} {unrealized_pnl:+,.0f}",
    f"{unrealized_pct:+.1f}%",
)
m3.metric(
    "Realized P&L",
    f"{base_currency} {realized_pnl:+,.0f}" if realized_pnl != 0 else "---",
)
m4.metric(
    "Today's P&L",
    f"{base_currency} {day_gain:+,.0f}",
    f"{day_pct:+.1f}%",
)

# Dividend income estimate — use cached value or show placeholder (avoid slow batch fetch on load)
_div_cache_key = f"cmd_div_income_{base_currency}"
div_income_est = st.session_state.get(_div_cache_key, 0)

with m5:
    if div_income_est > 0:
        m5.metric("Annual Div Income", f"{base_currency} {div_income_est:,.0f}",
                  f"{div_income_est/12:,.0f}/mo")
    else:
        m5.metric("Annual Div Income", "---", help="Visit Dividend Dashboard for estimates")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: TOP MOVERS + PERFORMANCE ATTRIBUTION + ALERTS (3 columns)
# ══════════════════════════════════════════════════════════════════════════════
col_movers, col_attrib, col_alerts = st.columns([2, 2, 2])

# ── Top Movers ──
with col_movers:
    st.markdown("#### Top Movers Today")

    if "day_change_pct" in enriched.columns:
        movers_df = enriched[["ticker", "name", "day_change_pct", "day_gain", "market_value"]].copy()
        movers_df["day_change_pct"] = pd.to_numeric(movers_df["day_change_pct"], errors="coerce")
        movers_df["day_gain"] = pd.to_numeric(movers_df["day_gain"], errors="coerce")
        movers_df = movers_df.dropna(subset=["day_change_pct"])

        if not movers_df.empty:
            gainers = movers_df.nlargest(3, "day_change_pct")
            losers = movers_df.nsmallest(3, "day_change_pct")

            for _, row in gainers.iterrows():
                pct = row["day_change_pct"]
                gain = row.get("day_gain", 0)
                gain_str = f" (+{gain:,.0f})" if pd.notna(gain) and gain > 0 else ""
                st.markdown(
                    f"<div style='padding:5px 10px;margin:3px 0;border-radius:6px;"
                    f"background:rgba(0,200,83,0.08);border-left:3px solid #00c853'>"
                    f"<b>{row['ticker']}</b> <span style='color:#00c853'>{pct:+.1f}%</span>"
                    f"<span style='color:#666;font-size:0.85em'>{gain_str}</span></div>",
                    unsafe_allow_html=True,
                )
            for _, row in losers.iterrows():
                pct = row["day_change_pct"]
                loss = row.get("day_gain", 0)
                loss_str = f" ({loss:,.0f})" if pd.notna(loss) and loss < 0 else ""
                st.markdown(
                    f"<div style='padding:5px 10px;margin:3px 0;border-radius:6px;"
                    f"background:rgba(255,23,68,0.08);border-left:3px solid #ff1744'>"
                    f"<b>{row['ticker']}</b> <span style='color:#ff1744'>{pct:+.1f}%</span>"
                    f"<span style='color:#666;font-size:0.85em'>{loss_str}</span></div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No price data available yet.")
    else:
        st.caption("Visit Portfolio Dashboard to load live prices.")

# ── Performance Attribution ──
with col_attrib:
    st.markdown("#### P&L Attribution")

    if "day_gain" in enriched.columns:
        attrib_df = enriched[["ticker", "day_gain", "market_value"]].copy()
        attrib_df["day_gain"] = pd.to_numeric(attrib_df["day_gain"], errors="coerce").fillna(0)
        attrib_df = attrib_df[attrib_df["day_gain"] != 0].sort_values("day_gain")

        if not attrib_df.empty:
            top_contrib = attrib_df.tail(5)  # top 5 positive
            bot_contrib = attrib_df.head(5)  # top 5 negative
            show_df = pd.concat([bot_contrib, top_contrib]).drop_duplicates()
            show_df = show_df.sort_values("day_gain")

            colors = ["#ef5350" if v < 0 else "#26a69a" for v in show_df["day_gain"]]
            fig_attr = go.Figure(go.Bar(
                x=show_df["day_gain"],
                y=show_df["ticker"],
                orientation="h",
                marker_color=colors,
                text=show_df["day_gain"].apply(lambda x: f"{x:+,.0f}"),
                textposition="outside",
            ))
            fig_attr.update_layout(
                height=220, margin=dict(t=5, l=5, r=40, b=5),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="", yaxis_title="",
                xaxis=dict(showgrid=False, zeroline=True, zerolinecolor="rgba(255,255,255,0.2)"),
                yaxis=dict(showgrid=False),
                font=dict(size=11),
            )
            st.plotly_chart(fig_attr, use_container_width=True, key="cmd_attrib")
        else:
            st.caption("No P&L changes today.")
    else:
        st.caption("Load prices from Dashboard first.")

# ── Alerts ──
with col_alerts:
    st.markdown("#### Attention Required")
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
                    alerts.append(("🔴", f"**{ticker}** is {w:.0%} of portfolio"))

            if "sector" in enriched.columns:
                sector_weights = enriched.copy()
                sector_weights["mv"] = mv
                sector_agg = sector_weights.groupby("sector")["mv"].sum() / total
                for sec, sw in sector_agg.items():
                    if sw > 0.35 and sec not in ("", "Unknown", None):
                        alerts.append(("🟡", f"**{sec}** sector {sw:.0%}"))

    # Big daily drops
    if "day_change_pct" in enriched.columns:
        big_drops = enriched[pd.to_numeric(enriched["day_change_pct"], errors="coerce") < -3]
        for _, row in big_drops.iterrows():
            pct = float(row["day_change_pct"])
            alerts.append(("📉", f"**{row['ticker']}** down {pct:.1f}%"))

    # Earnings within 5 days — use cached earnings data if available (avoid slow batch fetch)
    _earnings_cache = st.session_state.get("cmd_earnings_alerts", [])
    for tk, days in _earnings_cache:
        tag = "TODAY" if days == 0 else f"in {days}d"
        alerts.append(("📅", f"**{tk}** earnings {tag}"))

    # AI analysis coverage
    try:
        analyses = get_all_prosper_analyses()
        if not analyses.empty:
            cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            recent = analyses[analyses["analysis_date"] >= cutoff]
            coverage = len(recent) / holdings_count * 100 if holdings_count > 0 else 0
            if coverage < 50:
                alerts.append(("🤖", f"Only {coverage:.0f}% analysed (7d)"))
    except Exception:
        pass

    # FORTRESS regime warnings
    try:
        from core.fortress import check_circuit_breakers
        if regime_name == "Contraction":
            alerts.append(("🏰", "**Contraction** regime active"))
        elif regime_name == "Overheating":
            alerts.append(("🏰", "**Late cycle** — tighten stops"))

        if total_cost > 0:
            dd_pct = min(0, (total_value - total_cost) / total_cost * 100)
            if dd_pct <= -5:
                cb = check_circuit_breakers(dd_pct)
                level = cb["portfolio_level"]["level"]
                if level != "NONE":
                    alerts.append(("🚨", f"Breaker **{level}**: {dd_pct:.1f}%"))
    except Exception:
        pass

    if alerts:
        for icon, text in alerts[:8]:
            st.markdown(
                f"<div style='padding:4px 8px;margin:2px 0;border-radius:6px;"
                f"background:rgba(255,255,255,0.03);font-size:0.9rem'>"
                f"{icon} {text}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.success("No alerts — portfolio looks healthy")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: HEATMAP + ALLOCATION PIE (side by side)
# ══════════════════════════════════════════════════════════════════════════════
col_hm, col_alloc = st.columns([3, 2])

with col_hm:
    st.markdown("#### Portfolio Heat Map")

    if "day_change_pct" in enriched.columns and "market_value" in enriched.columns:
        hm_df = enriched[["ticker", "name", "market_value", "day_change_pct"]].copy()
        hm_df["market_value"] = pd.to_numeric(hm_df["market_value"], errors="coerce").fillna(0)
        hm_df["day_change_pct"] = pd.to_numeric(hm_df["day_change_pct"], errors="coerce").fillna(0)
        hm_df = hm_df[hm_df["market_value"] > 0]
        hm_df["label"] = hm_df["ticker"] + "<br>" + hm_df["day_change_pct"].apply(lambda x: f"{x:+.1f}%")

        if not hm_df.empty:
            try:
                # Add sector if available for hierarchical treemap
                if "sector" in enriched.columns:
                    sector_map = dict(zip(enriched["ticker"], enriched.get("sector", "").fillna("Other")))
                    hm_df["sector"] = hm_df["ticker"].map(sector_map).fillna("Other")
                    hm_df["sector"] = hm_df["sector"].replace({"": "Other", "nan": "Other"})
                    path_cols = ["sector", "label"]
                else:
                    path_cols = ["label"]

                fig = px.treemap(
                    hm_df,
                    path=path_cols,
                    values="market_value",
                    color="day_change_pct",
                    color_continuous_scale=["#d32f2f", "#ff9800", "#424242", "#66bb6a", "#2e7d32"],
                    color_continuous_midpoint=0,
                )
                fig.update_layout(
                    margin=dict(t=5, l=5, r=5, b=5),
                    height=350,
                    coloraxis_colorbar=dict(title="Day %", len=0.5),
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                fig.update_traces(textfont=dict(size=13, color="white"), textposition="middle center")
                st.plotly_chart(fig, use_container_width=True, key="cmd_heatmap")
            except Exception:
                # Fallback: simple bar chart if treemap fails
                hm_df = hm_df.sort_values("market_value", ascending=True).tail(15)
                colors = ["#26a69a" if v >= 0 else "#ef5350" for v in hm_df["day_change_pct"]]
                fig = go.Figure(go.Bar(
                    x=hm_df["market_value"], y=hm_df["ticker"],
                    orientation="h", marker_color=colors,
                    text=hm_df["day_change_pct"].apply(lambda x: f"{x:+.1f}%"),
                    textposition="outside",
                ))
                fig.update_layout(
                    height=350, margin=dict(t=5, l=5, r=40, b=5),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis_title="Market Value", yaxis_title="",
                )
                st.plotly_chart(fig, use_container_width=True, key="cmd_heatmap_fallback")

with col_alloc:
    st.markdown("#### Allocation")

    if "market_value" in enriched.columns and "sector" in enriched.columns:
        alloc_df = enriched[["sector", "market_value"]].copy()
        alloc_df["market_value"] = pd.to_numeric(alloc_df["market_value"], errors="coerce").fillna(0)
        alloc_df = alloc_df.groupby("sector")["market_value"].sum().reset_index()
        alloc_df = alloc_df[alloc_df["market_value"] > 0].sort_values("market_value", ascending=False)

        if not alloc_df.empty:
            fig_alloc = px.pie(
                alloc_df, names="sector", values="market_value", hole=0.5,
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_alloc.update_traces(textposition="inside", textinfo="percent")
            fig_alloc.update_layout(
                height=350, margin=dict(t=5, l=5, r=5, b=5),
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
                legend=dict(font=dict(size=10), orientation="h", y=-0.1),
            )
            st.plotly_chart(fig_alloc, use_container_width=True, key="cmd_alloc")
    elif "market_value" in enriched.columns:
        # Simple top-10 bar chart if no sector data
        top10 = enriched.nlargest(10, "market_value")[["ticker", "market_value"]]
        fig_t10 = px.bar(top10, x="ticker", y="market_value", color="market_value",
                         color_continuous_scale="Blues")
        fig_t10.update_layout(height=350, margin=dict(t=5, l=5, r=5, b=5),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              showlegend=False)
        st.plotly_chart(fig_t10, use_container_width=True, key="cmd_top10")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: AI BRIEFING (auto-generated)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("#### AI CIO Briefing")

briefing_cache_key = f"daily_briefing_{datetime.now().strftime('%Y-%m-%d')}_{base_currency}"


def generate_briefing():
    """Generate the daily AI briefing using Claude."""
    api_key = get_api_key("ANTHROPIC_API_KEY")
    if not api_key:
        return "Anthropic API key not configured. Add it in Settings to enable AI briefings."

    try:
        import anthropic
        from core.settings import call_claude

        client = anthropic.Anthropic(api_key=api_key)

        # Build context
        portfolio_summary = []
        for _, row in enriched.sort_values(
            pd.to_numeric(enriched.get("market_value"), errors="coerce"),
            ascending=False
        ).head(25).iterrows():
            ticker = row.get("ticker", "?")
            name = str(row.get("name", ""))[:25]
            mv = pd.to_numeric(row.get("market_value"), errors="coerce")
            pnl = pd.to_numeric(row.get("unrealized_pnl"), errors="coerce")
            day_chg = pd.to_numeric(row.get("day_change_pct"), errors="coerce")
            weight = (mv / total_value * 100) if total_value > 0 and pd.notna(mv) else 0
            line = f"{ticker} ({name}): wt={weight:.1f}%"
            if pd.notna(day_chg):
                line += f", day={day_chg:+.1f}%"
            if pd.notna(pnl):
                line += f", pnl={pnl:+,.0f}"
            portfolio_summary.append(line)

        # Recent AI analyses
        analysis_context = ""
        try:
            analyses = get_all_prosper_analyses()
            if not analyses.empty:
                recent = analyses.sort_values("analysis_date", ascending=False).head(10)
                analysis_lines = []
                for _, a in recent.iterrows():
                    analysis_lines.append(
                        f"{a['ticker']}: {a.get('rating','?')} score={a.get('score','?')}"
                    )
                analysis_context = ", ".join(analysis_lines)
        except Exception:
            pass

        prompt = f"""You are the Chief Investment Officer of a family office. Generate a sharp morning briefing.

PORTFOLIO: {base_currency} {net_portfolio:,.0f} ({holdings_count} holdings, {len(enriched['currency'].unique()) if 'currency' in enriched.columns else 1} currencies)
TODAY: {day_gain:+,.0f} ({day_pct:+.1f}%) | UNREALIZED: {unrealized_pnl:+,.0f} ({unrealized_pct:+.1f}%)
REGIME: {regime_name} | CASH: {base_currency} {total_cash:,.0f}

TOP HOLDINGS:
{chr(10).join(portfolio_summary)}

{f'AI RATINGS: {analysis_context}' if analysis_context else ''}

FORMAT (use markdown):
**Portfolio Pulse:** [1 sentence — overall health today vs trend]

**Key Moves:** [2-3 bullets explaining biggest movers. Be specific about why — earnings, macro, sector rotation]

**Risk Watch:** [1-2 bullets on concentration, regime implications, or holdings needing attention]

**Action Items:** [2-3 specific suggestions: "Trim X to Y%", "Review Y pre-earnings", "Add to Z on weakness"]

Be sharp, specific, actionable. No generic advice. This investor has {holdings_count} positions worth {base_currency} {net_portfolio:,.0f}."""

        response = call_claude(
            client,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700,
            preferred_model="claude-sonnet-4-5",
        )
        return response.content[0].text

    except Exception as e:
        return f"Could not generate briefing: {str(e)[:100]}"


# Auto-show if cached, otherwise offer button
if briefing_cache_key in st.session_state:
    st.markdown(st.session_state[briefing_cache_key])
    col_refresh, _ = st.columns([1, 5])
    with col_refresh:
        if st.button("Refresh Briefing", key="refresh_brief"):
            with st.spinner("Generating..."):
                st.session_state[briefing_cache_key] = generate_briefing()
                st.rerun()
else:
    # Show generate button (don't auto-generate — it blocks page load)
    api_key = get_api_key("ANTHROPIC_API_KEY")
    if api_key and api_key != "your_anthropic_api_key_here":
        if st.button("Generate Today's AI Briefing", type="primary", key="gen_briefing"):
            with st.spinner("Your AI CIO is preparing today's briefing..."):
                st.session_state[briefing_cache_key] = generate_briefing()
                st.rerun()
        st.caption("Click to generate your personalized CIO briefing for today.")
    else:
        st.caption("Configure your Anthropic API key in Settings to enable AI briefings.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: NAV HISTORY + QUICK NAV
# ══════════════════════════════════════════════════════════════════════════════
col_nav, col_links = st.columns([3, 2])

with col_nav:
    nav_history = get_nav_history(base_currency)
    if not nav_history.empty and len(nav_history) > 1:
        st.markdown("#### Portfolio Value History")
        nav_history["date"] = pd.to_datetime(nav_history["date"])
        fig_nav = go.Figure()
        fig_nav.add_trace(go.Scatter(
            x=nav_history["date"],
            y=nav_history["total_value"],
            mode="lines",
            line=dict(color="#1E88E5", width=2.5),
            fill="tozeroy",
            fillcolor="rgba(30,136,229,0.08)",
        ))
        fig_nav.update_layout(
            height=220,
            margin=dict(t=5, l=5, r=5, b=5),
            xaxis_title="", yaxis_title=base_currency,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_nav, use_container_width=True, key="cmd_nav_hist")
    else:
        st.markdown("#### Portfolio Value History")
        st.caption("NAV snapshots accumulate daily when you visit the Dashboard. Check back soon.")

with col_links:
    st.markdown("#### Quick Navigation")

    nav_items = [
        ("pages/2_Portfolio_Dashboard.py", "Dashboard", "Live prices, P&L, holdings"),
        ("pages/18_FORTRESS_Dashboard.py", "FORTRESS", "Regime, sizing, risk governance"),
        ("pages/18_Equity_Deep_Dive.py", "Equity Deep Dive", "360-degree stock research"),
        ("pages/22_Dividend_Dashboard.py", "Dividends", "Income tracking & projections"),
        ("pages/20_Earnings_Calendar.py", "Earnings Calendar", "Upcoming reporting dates"),
        ("pages/21_Technical_Analysis.py", "Technical Analysis", "Charts & indicators"),
        ("pages/23_Peer_Comparison.py", "Peer Comparison", "Side-by-side fundamentals"),
        ("pages/3_Portfolio_News.py", "Portfolio News", "AI-summarised news feed"),
    ]

    for page, label, desc in nav_items:
        st.page_link(page, label=f"{label} — *{desc}*")
