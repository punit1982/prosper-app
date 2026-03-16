"""
FORTRESS Dashboard — Dynamic Portfolio Governance
===================================================
Framework for Optimized Risk-Tuned Regime-Responsive Equity Sizing & Strategy

5 Tabs:
  1. Regime & Exposure — Current regime detection + exposure governor
  2. Position Sizing — FORTRESS sizing for each holding
  3. Factor & Correlation — Factor balance monitor + correlation heatmap
  4. Alerts & Rebalancing — Circuit breakers + rebalancing triggers
  5. Portfolio Health — Weekly health scorecard (10 dimensions)
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from core.database import (
    get_all_holdings, get_all_prosper_analyses, get_all_cash_positions,
    save_fortress_state, get_fortress_state, get_all_fortress_state,
)
from core.settings import SETTINGS
from core.cio_engine import enrich_portfolio
from core.data_engine import get_ticker_info_batch
from core.fortress import (
    # Module 1
    detect_regime, get_geopolitical_tier, REGIME_NAMES, REGIME_COLORS,
    REGIME_EXPANSION, REGIME_OVERHEATING, REGIME_CONTRACTION, REGIME_RECOVERY,
    GEO_GREEN, GEO_AMBER, GEO_RED,
    # Module 2
    get_exposure_limits, check_exposure_compliance, EXPOSURE_LIMITS,
    # Module 3
    calculate_position_size, get_conviction_tier, SIZING_MATRIX, REGIME_SCALAR,
    # Module 4
    analyze_factor_exposure, calculate_correlation_matrix, FACTOR_LIMITS,
    # Module 5
    check_rebalancing_triggers,
    # Module 6
    check_circuit_breakers, PORTFOLIO_BREAKERS, SINGLE_NAME_BREAKERS,
    # Module 7
    compute_health_score,
    # Module 8
    fortress_size_ticker, get_fortress_summary,
    # Margin
    BROKER_MARGIN_RATES, get_margin_rate, calculate_margin_cost,
)
from core.portfolio_optimizer import (
    analyze_current_allocation, concentration_risk_check, _classify_asset_class,
)

# ─────────────────────────────────────────
# PAGE SETUP
# ─────────────────────────────────────────
st.markdown(
    "<h2 style='margin-bottom:0'>🏰 FORTRESS Dashboard</h2>"
    "<p style='color:#888;margin-top:0'>Dynamic Portfolio Governance · Regime-Responsive Sizing & Strategy</p>",
    unsafe_allow_html=True,
)

# ── Load Portfolio ──
base_currency = SETTINGS.get("base_currency", "USD")
holdings = get_all_holdings()

if holdings.empty:
    st.info("No holdings found. Upload your portfolio first via the **Upload Portal**.")
    st.stop()

cache_key = f"enriched_{base_currency}"
if cache_key in st.session_state and st.session_state[cache_key] is not None and not st.session_state[cache_key].empty:
    enriched = st.session_state[cache_key]
else:
    with st.spinner("Enriching portfolio data…"):
        enriched = enrich_portfolio(holdings, base_currency)
        st.session_state[cache_key] = enriched

if enriched.empty or "market_value" not in enriched.columns:
    st.warning("Portfolio data not ready. Visit the **Portfolio Dashboard** first to load live prices.")
    st.stop()

enriched["market_value"] = pd.to_numeric(enriched["market_value"], errors="coerce").fillna(0)
enriched = enriched[enriched["market_value"] > 0]

if enriched.empty:
    st.warning("No holdings with valid market values.")
    st.stop()

# ── Fetch Ticker Info ──
tickers = enriched["ticker"].tolist()

@st.cache_data(ttl=3600, show_spinner=False)
def _get_info(tickers_tuple):
    return get_ticker_info_batch(list(tickers_tuple))

info_map = _get_info(tuple(tickers))

# ── Get PROSPER analyses ──
prosper_df = get_all_prosper_analyses()
prosper_map = prosper_df.set_index("ticker").to_dict("index") if not prosper_df.empty else {}

# ── Load / compute portfolio metrics ──
total_mv = enriched["market_value"].sum()
enriched["weight_pct"] = enriched["market_value"] / total_mv * 100

# Allocation analysis
current_alloc = analyze_current_allocation(enriched, info_map)

# Cash positions
cash_positions = get_all_cash_positions()
total_cash = float(cash_positions["amount"].sum()) if not cash_positions.empty else 0.0
cash_pct = (total_cash / (total_mv + total_cash) * 100) if (total_mv + total_cash) > 0 else 0

# Max concentrations
max_single_pct = enriched["weight_pct"].max() if not enriched.empty else 0
sector_alloc = current_alloc.get("sector", {})
max_sector_pct = max(sector_alloc.values()) * 100 if sector_alloc else 0
geo_alloc = current_alloc.get("geography", {})
max_geo_pct = max(geo_alloc.values()) * 100 if geo_alloc else 0

portfolio_metrics = {
    "gross_exposure": 100,  # Long-only portfolio = 100% gross
    "net_exposure": 100,
    "cash_pct": cash_pct,
    "max_single_name_pct": max_single_pct,
    "max_sector_pct": max_sector_pct,
    "max_geo_pct": max_geo_pct,
}

# ── Sidebar: Regime Input ──
with st.sidebar:
    st.subheader("🏰 FORTRESS Controls")

    st.markdown("**Regime Signals**")
    vix = st.number_input("VIX (current)", value=float(get_fortress_state("vix") or 18.0),
                          min_value=5.0, max_value=80.0, step=0.5, key="_f_vix")
    pmi = st.number_input("Global PMI", value=float(get_fortress_state("pmi") or 52.0),
                          min_value=30.0, max_value=65.0, step=0.5, key="_f_pmi")
    credit_spread = st.number_input("IG Credit Spread (bps)", value=float(get_fortress_state("credit_spread") or 110),
                                     min_value=50.0, max_value=500.0, step=5.0, key="_f_cs")
    yield_curve = st.number_input("Yield Curve 2s10s (%)", value=float(get_fortress_state("yield_curve") or 0.3),
                                   min_value=-2.0, max_value=3.0, step=0.05, key="_f_yc")
    inflation = st.number_input("Core CPI YoY (%)", value=float(get_fortress_state("inflation") or 2.8),
                                 min_value=0.0, max_value=15.0, step=0.1, key="_f_inf")
    fed = st.selectbox("Fed Trajectory", ["On hold", "Cutting", "Hiking", "Paused"],
                       index=["On hold", "Cutting", "Hiking", "Paused"].index(
                           get_fortress_state("fed_trajectory") or "On hold"), key="_f_fed")

    st.markdown("**Geopolitical**")
    geo_conflicts = st.number_input("Active Conflicts", value=int(get_fortress_state("geo_conflicts") or 0),
                                     min_value=0, max_value=10, step=1, key="_f_geo")
    geo_sanctions = st.checkbox("Sanctions affecting portfolio",
                                 value=(get_fortress_state("geo_sanctions") == "True"), key="_f_sanctions")

    if st.button("💾 Save Signals & Detect Regime", type="primary", use_container_width=True):
        for k, v in [("vix", vix), ("pmi", pmi), ("credit_spread", credit_spread),
                     ("yield_curve", yield_curve), ("inflation", inflation),
                     ("fed_trajectory", fed), ("geo_conflicts", geo_conflicts),
                     ("geo_sanctions", str(geo_sanctions))]:
            save_fortress_state(k, str(v))
        st.session_state.pop("_fortress_regime", None)
        st.rerun()

# ── Detect Regime ──
if "_fortress_regime" not in st.session_state:
    regime_result = detect_regime(
        vix=vix, pmi=pmi, credit_spread=credit_spread,
        yield_curve=yield_curve, inflation_yoy=inflation, fed_trajectory=fed,
    )
    geo_result = get_geopolitical_tier(
        active_conflicts=geo_conflicts,
        sanctions_affecting_portfolio=geo_sanctions,
    )
    st.session_state["_fortress_regime"] = regime_result
    st.session_state["_fortress_geo"] = geo_result

regime_result = st.session_state["_fortress_regime"]
geo_result = st.session_state["_fortress_geo"]
current_regime = regime_result["regime"]
confidence = regime_result["confidence"]
geo_tier = geo_result["tier"]

# Override regime if geopolitical RED
effective_regime = REGIME_CONTRACTION if geo_tier == GEO_RED else current_regime

# ── Top Status Bar ──
r_col1, r_col2, r_col3, r_col4 = st.columns(4)
with r_col1:
    color = REGIME_COLORS.get(current_regime, "#888")
    st.markdown(f"### <span style='color:{color}'>⬤</span> {REGIME_NAMES.get(current_regime, '?')}", unsafe_allow_html=True)
with r_col2:
    conf_color = {"HIGH": "🟢", "MODERATE": "🟡", "LOW": "🔴"}.get(confidence, "⚪")
    st.metric("Confidence", f"{conf_color} {confidence}")
with r_col3:
    geo_emoji = {"GREEN": "🟢", "AMBER": "🟡", "RED": "🔴"}.get(geo_tier, "⚪")
    st.metric("Geopolitical", f"{geo_emoji} {geo_tier}")
with r_col4:
    st.metric("Holdings", f"{len(enriched)}", help=f"Total MV: {base_currency} {total_mv:,.0f}")

if geo_tier == GEO_RED:
    st.error("🚨 **GEOPOLITICAL RED** — All parameters forced to Contraction (Regime III). Immediate risk reduction required.")
elif geo_tier == GEO_AMBER:
    st.warning(f"⚠️ **GEOPOLITICAL AMBER** — {geo_result['action']}")

st.divider()

# ─────────────────────────────────────────
# 5 TABS
# ─────────────────────────────────────────
tab_regime, tab_sizing, tab_factor, tab_alerts, tab_health = st.tabs([
    "📊 Regime & Exposure",
    "📐 Position Sizing",
    "🔬 Factor & Correlation",
    "🚨 Alerts & Rebalancing",
    "💚 Portfolio Health",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: REGIME & EXPOSURE
# ══════════════════════════════════════════════════════════════════════════════
with tab_regime:
    st.markdown("### Module 1: Regime Detection")

    # Regime scores visualization
    scores = regime_result["scores"]
    score_df = pd.DataFrame([
        {"Regime": REGIME_NAMES[r], "Score": s, "Color": REGIME_COLORS[r]}
        for r, s in scores.items()
    ])

    fig_regime = go.Figure(go.Bar(
        x=score_df["Score"],
        y=score_df["Regime"],
        orientation="h",
        marker_color=[REGIME_COLORS[r] for r in scores.keys()],
        text=score_df["Score"].apply(lambda x: f"{x:.1f}"),
        textposition="outside",
    ))
    fig_regime.update_layout(
        height=250, margin=dict(t=10, l=10, r=40, b=10),
        xaxis_title="Signal Score",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_regime, use_container_width=True)

    if regime_result.get("signals_used"):
        st.caption(f"Signals: {' · '.join(regime_result['signals_used'])}")

    st.divider()

    # Module 2: Exposure Governor
    st.markdown("### Module 2: Exposure Governor")
    limits = get_exposure_limits(effective_regime, confidence, geo_tier)
    violations = check_exposure_compliance(portfolio_metrics, effective_regime, confidence, geo_tier)

    # Exposure table
    exp_rows = []
    for v in violations:
        status_icon = {"OK": "🟢", "BELOW_MIN": "🟡", "ABOVE_MAX": "🔴"}.get(v["status"], "⚪")
        exp_rows.append({
            "Parameter": v["param"].replace("_", " ").title(),
            "Current": f"{v['current']:.1f}%",
            "Min": f"{v['limit_min']:.0f}%",
            "Max": f"{v['limit_max']:.0f}%",
            "Status": f"{status_icon} {v['status'].replace('_', ' ')}",
        })

    exp_df = pd.DataFrame(exp_rows)
    st.dataframe(exp_df, use_container_width=True, hide_index=True)

    # Cash position summary
    if not cash_positions.empty:
        st.markdown("#### 💵 Cash Positions & Margin")
        for _, cp in cash_positions.iterrows():
            broker = cp.get("broker_source", "") or "Unknown"
            currency = cp.get("currency", "USD")
            amount = float(cp["amount"])
            is_margin = bool(cp.get("is_margin", 0))

            if is_margin or amount < 0:
                # Get live margin rate
                margin_info = get_margin_rate(broker, amount, currency)
                rate = cp.get("margin_rate") or margin_info.get("rate") or 0
                annual_cost = calculate_margin_cost(amount, rate) if rate else 0
                st.markdown(
                    f"🔴 **{cp['account_name']}** ({broker}) — "
                    f"{currency} {amount:,.2f} · "
                    f"Rate: **{rate:.2f}%** ({margin_info.get('broker_name', broker)}) · "
                    f"Annual cost: **{currency} {annual_cost:,.0f}**"
                )
            else:
                st.markdown(f"🟢 **{cp['account_name']}** ({broker}) — {currency} {amount:,.2f}")

        # Margin rate comparison table
        with st.expander("📊 Broker Margin Rate Comparison"):
            rate_rows = []
            for broker_key, data in BROKER_MARGIN_RATES.items():
                for cur, rate in data.get("currency_rates", {}).items():
                    rate_rows.append({
                        "Broker": data["name"],
                        "Currency": cur,
                        "Rate %": rate,
                        "Benchmark": data.get("benchmark", ""),
                    })
            rate_df = pd.DataFrame(rate_rows)
            # Pivot for comparison
            if not rate_df.empty:
                pivot = rate_df.pivot_table(index="Broker", columns="Currency",
                                            values="Rate %", aggfunc="first")
                st.dataframe(pivot.style.format("{:.2f}%", na_rep="—"),
                            use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: POSITION SIZING
# ══════════════════════════════════════════════════════════════════════════════
with tab_sizing:
    st.markdown("### Module 3: Dynamic Position Sizing")
    st.caption(f"Regime: **{REGIME_NAMES.get(effective_regime)}** · Scalar: **{REGIME_SCALAR.get(effective_regime, 0.75):.2f}x**")

    sizing_rows = []
    for _, row in enriched.iterrows():
        ticker = row["ticker"]
        current_weight = row["weight_pct"]
        prosper_data = prosper_map.get(ticker, {})
        prosper_score = prosper_data.get("score", 50)  # Default 50 if no analysis

        # Get sizing recommendation
        sizing = calculate_position_size(
            prosper_score=prosper_score if pd.notna(prosper_score) else 50,
            regime=effective_regime,
        )

        target = sizing["size_pct"]
        diff = current_weight - target if target > 0 else 0
        action = "At Target" if abs(diff) < 0.5 else ("Trim" if diff > 0 else "Add")

        sizing_rows.append({
            "Ticker": ticker,
            "PROSPER Score": f"{prosper_score:.0f}" if pd.notna(prosper_score) else "—",
            "Conviction": sizing["conviction_tier"],
            "Current %": f"{current_weight:.1f}%",
            "Target %": f"{target:.1f}%" if target > 0 else "Exit",
            "Kelly (½)": f"{sizing['kelly_half']:.1f}%",
            "Action": action,
        })

    sizing_df = pd.DataFrame(sizing_rows)

    def _color_conviction(val):
        colors = {"MAXIMUM": "color:#1a9e5c;font-weight:700",
                  "HIGH": "color:#27ae60", "MODERATE": "color:#f39c12",
                  "LOW": "color:#e74c3c", "NO_POSITION": "color:#d63031;font-weight:700"}
        return colors.get(val, "")

    def _color_action(val):
        if val == "Trim":
            return "color:#ff9800;font-weight:600"
        elif val == "Add":
            return "color:#2196f3;font-weight:600"
        elif val == "Exit":
            return "color:#d63031;font-weight:700"
        return "color:#4caf50"

    styled = sizing_df.style.map(_color_conviction, subset=["Conviction"])
    styled = styled.map(_color_action, subset=["Action"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # Sizing calculator
    st.divider()
    st.markdown("#### 🧮 Size a Specific Ticker")
    calc_cols = st.columns(4)
    with calc_cols[0]:
        calc_ticker = st.text_input("Ticker", value="", placeholder="e.g. AAPL", key="_calc_ticker")
    with calc_cols[1]:
        calc_score = st.number_input("PROSPER Score", value=70.0, min_value=0.0, max_value=100.0, step=1.0, key="_calc_score")
    with calc_cols[2]:
        calc_p = st.number_input("P(Bull/Base)", value=0.60, min_value=0.1, max_value=0.95, step=0.05, key="_calc_p")
    with calc_cols[3]:
        calc_rr = st.number_input("Reward/Risk", value=2.0, min_value=0.5, max_value=10.0, step=0.25, key="_calc_rr")

    if st.button("Calculate Size", type="primary", key="_calc_btn"):
        result = fortress_size_ticker(
            ticker=calc_ticker or "TICKER",
            prosper_score=calc_score,
            regime=effective_regime,
            p_bull=calc_p,
            reward_risk=calc_rr,
        )
        if result["action"] == "BLOCKED":
            st.error(f"❌ {result['reason']}")
        elif result["size_pct"] == 0:
            st.warning(f"⚠️ {result['recommendation']}")
        else:
            st.success(
                f"✅ **{result['ticker']}**: {result['size_pct']:.1f}% position\n\n"
                f"Conviction: {result['conviction_tier']} · "
                f"Kelly(½): {result['kelly_half']:.1f}% · "
                f"Regime-adjusted: {result['regime_adjusted']:.1f}% · "
                f"Matrix: {result['matrix_min']}-{result['matrix_max']}%"
            )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: FACTOR & CORRELATION
# ══════════════════════════════════════════════════════════════════════════════
with tab_factor:
    st.markdown("### Module 4: Factor Balance")

    # Use extended_df if available for richer data
    analysis_df = st.session_state.get("extended_df", enriched)
    factor_analysis = analyze_factor_exposure(analysis_df, info_map)

    # Factor exposure display
    if factor_analysis["factors"]:
        factor_rows = []
        for factor, pct in factor_analysis["factors"].items():
            limit = FACTOR_LIMITS.get(factor, {}).get("max_pct", 100)
            status = "🟢 OK" if pct <= limit else "🔴 BREACH"
            factor_rows.append({
                "Factor": factor.replace("_", " ").title(),
                "Exposure %": f"{pct:.1f}%",
                "Limit %": f"{limit}%",
                "Status": status,
            })
        st.dataframe(pd.DataFrame(factor_rows), use_container_width=True, hide_index=True)

        if factor_analysis["violations"]:
            for v in factor_analysis["violations"]:
                st.error(f"⚠️ **{v['factor'].title()}** at {v['current']:.1f}% exceeds {v['limit']}% limit")
    else:
        st.info("Load **Extended Metrics** from the Dashboard to see factor analysis (requires P/E, revenue growth, market cap data).")

    st.divider()

    # Allocation pie charts
    st.markdown("### Current Allocation Breakdown")
    ac_cols = st.columns(4)
    for i, (dim, label) in enumerate([
        ("asset_class", "Asset Class"), ("sector", "Sector"),
        ("geography", "Geography"), ("cap_size", "Market Cap"),
    ]):
        with ac_cols[i]:
            alloc = current_alloc.get(dim, {})
            if alloc:
                fig = px.pie(values=list(alloc.values()), names=list(alloc.keys()),
                             title=label, hole=0.4)
                fig.update_layout(height=250, margin=dict(t=35, l=5, r=5, b=5),
                                  showlegend=True, legend=dict(font=dict(size=10)),
                                  paper_bgcolor="rgba(0,0,0,0)")
                fig.update_traces(textposition="inside", textinfo="percent")
                st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.markdown("### Correlation Monitor")
    st.caption("Pairwise correlations based on 60-day rolling returns. Requires price history data.")

    if st.button("🔬 Compute Correlations", type="primary", key="_corr_btn"):
        with st.spinner("Fetching 60-day returns…"):
            try:
                from core.data_engine import get_history
                frames = {}
                for t in tickers[:20]:  # Limit to top 20 to avoid timeout
                    hist = get_history(t, period="3mo")
                    if hist is not None and not hist.empty:
                        close = hist["Close"] if "Close" in hist.columns else hist.iloc[:, 0]
                        frames[t] = close
                if len(frames) >= 2:
                    prices = pd.DataFrame(frames).dropna()
                    returns = prices.pct_change().dropna().tail(60)
                    corr_result = calculate_correlation_matrix(returns)
                    st.session_state["_fortress_corr"] = corr_result
                else:
                    st.warning("Need at least 2 tickers with price history.")
            except Exception as e:
                st.error(f"Correlation calculation failed: {e}")

    corr_data = st.session_state.get("_fortress_corr")
    if corr_data and corr_data.get("correlation_matrix"):
        # Heatmap
        corr_matrix = pd.DataFrame(corr_data["correlation_matrix"])
        fig_corr = px.imshow(
            corr_matrix, text_auto=".2f", color_continuous_scale="RdYlGn_r",
            zmin=-1, zmax=1, aspect="auto",
        )
        fig_corr.update_layout(height=400, margin=dict(t=10, l=10, r=10, b=10))
        st.plotly_chart(fig_corr, use_container_width=True)

        # Summary metrics
        mc1, mc2, mc3 = st.columns(3)
        zone_icon = {"green": "🟢", "amber": "🟡", "red": "🔴"}.get
        with mc1:
            st.metric("Avg Pairwise", f"{corr_data['avg_pairwise']:.3f}",
                      help=f"Zone: {zone_icon(corr_data['avg_zone'], '?')} {corr_data['avg_zone'].upper()}")
        with mc2:
            st.metric("Max Pairwise", f"{corr_data['max_pairwise']:.3f}",
                      help=f"Pair: {corr_data.get('max_pair', ('?', '?'))}")
        with mc3:
            oz = corr_data["overall_zone"]
            st.metric("Overall Zone", f"{zone_icon(oz, '?')} {oz.upper()}")

        if corr_data["overall_zone"] == "red":
            st.error("🚨 **CORRELATION SPIKE PROTOCOL** — Freeze new positions. Reduce gross 10%. Add tail hedges.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: ALERTS & REBALANCING
# ══════════════════════════════════════════════════════════════════════════════
with tab_alerts:
    st.markdown("### Module 5: Rebalancing Triggers")

    # Calculate drawdown (simplified: from cost basis)
    total_cost = pd.to_numeric(enriched.get("cost_basis", pd.Series(dtype=float)), errors="coerce").sum()
    portfolio_drawdown = ((total_mv - total_cost) / total_cost * 100) if total_cost > 0 else 0

    # Check for previous regime
    prev_regime = get_fortress_state("prev_regime")

    triggers = check_rebalancing_triggers(
        portfolio_df=enriched,
        regime=effective_regime,
        prev_regime=prev_regime,
        drawdown_pct=min(portfolio_drawdown, 0),  # Only negative drawdowns matter
        factor_violations=factor_analysis.get("violations", []) if factor_analysis else [],
        correlation_zone=corr_data.get("overall_zone", "green") if corr_data else "green",
    )

    if triggers:
        for t in triggers:
            urgency_color = {"IMMEDIATE": "🔴", "HIGH": "🟠", "MODERATE": "🟡", "LOW": "🟢"}.get(t["urgency"], "⚪")
            with st.expander(f"{urgency_color} **{t['trigger']}** — {t['urgency']}", expanded=t["urgency"] in ("IMMEDIATE", "HIGH")):
                st.markdown(f"**Detail:** {t['detail']}")
                st.markdown(f"**Action:** {t['action']}")
    else:
        st.success("✅ No rebalancing triggers active. Portfolio is within all limits.")

    st.divider()

    # Module 6: Circuit Breakers
    st.markdown("### Module 6: Circuit Breakers")

    # Position-level drawdowns
    position_drawdowns = {}
    if "avg_cost" in enriched.columns and "current_price" in enriched.columns:
        for _, row in enriched.iterrows():
            cost = pd.to_numeric(row.get("avg_cost"), errors="coerce")
            price = pd.to_numeric(row.get("current_price"), errors="coerce")
            if pd.notna(cost) and pd.notna(price) and cost > 0:
                dd = (price - cost) / cost * 100
                if dd < 0:
                    position_drawdowns[row["ticker"]] = dd

    cb_result = check_circuit_breakers(
        portfolio_drawdown_pct=min(portfolio_drawdown, 0),
        position_drawdowns=position_drawdowns,
    )

    # Portfolio-level breaker
    pl = cb_result["portfolio_level"]
    level_colors = {"NONE": "🟢", "YELLOW": "🟡", "ORANGE": "🟠", "RED": "🔴", "CRITICAL": "⛔"}
    st.metric("Portfolio Level", f"{level_colors.get(pl['level'], '?')} {pl['level']}",
              help=pl.get("action", ""))

    if pl["level"] != "NONE":
        st.error(f"**{pl['level']}**: {pl['action']}")

    # Position-level breakers
    if cb_result["position_alerts"]:
        st.markdown("#### Single-Name Alerts")
        for alert in cb_result["position_alerts"]:
            st.warning(
                f"**{alert['ticker']}** — Drawdown: {alert['drawdown']:.1f}% "
                f"(Threshold: {alert['threshold']}%)  \n{alert['action']}"
            )

    # Breaker reference table
    with st.expander("📋 Circuit Breaker Thresholds"):
        st.markdown("**Portfolio-Level:**")
        for b in PORTFOLIO_BREAKERS:
            st.markdown(f"- **{b['threshold']}%** ({b['level']}): {b['action']}")
        st.markdown("**Single-Name:**")
        for b in SINGLE_NAME_BREAKERS:
            st.markdown(f"- **{b['threshold']}%**: {b['action']}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: PORTFOLIO HEALTH
# ══════════════════════════════════════════════════════════════════════════════
with tab_health:
    st.markdown("### Module 7: Portfolio Health Scorecard")

    # Compute average PROSPER score
    if prosper_map:
        scores_list = [v.get("score", 0) for v in prosper_map.values() if pd.notna(v.get("score"))]
        avg_prosper = sum(scores_list) / len(scores_list) if scores_list else 50
    else:
        avg_prosper = 50

    health = compute_health_score(
        regime=effective_regime,
        portfolio_df=enriched,
        exposure_violations=violations if 'violations' in dir() else [],
        factor_analysis=factor_analysis if 'factor_analysis' in dir() else None,
        correlation_data=corr_data,
        drawdown_pct=min(portfolio_drawdown, 0) if 'portfolio_drawdown' in dir() else 0,
        avg_prosper_score=avg_prosper,
        kill_risk_count=0,
    )

    # Big score display
    score = health["score"]
    total = health["total"]
    score_color = "#1a9e5c" if score >= 8 else ("#f39c12" if score >= 5 else "#d63031")

    st.markdown(
        f"<div style='text-align:center;padding:20px'>"
        f"<h1 style='font-size:72px;color:{score_color};margin:0'>{score}/{total}</h1>"
        f"<p style='font-size:18px;color:#888'>{health['overall_assessment']}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Dimension grid
    dims = health["dimensions"]
    dim_labels = {
        "regime_alignment": "Regime Alignment",
        "exposure_compliance": "Exposure Compliance",
        "single_name_concentration": "Single-Name Concentration",
        "sector_geo_concentration": "Sector/Geo Concentration",
        "factor_balance": "Factor Balance",
        "correlation": "Correlation",
        "liquidity_coverage": "Liquidity Coverage",
        "drawdown_status": "Drawdown Status",
        "prosper_score_avg": f"PROSPER Score Avg ({avg_prosper:.0f})",
        "open_kill_risks": "Open Kill Risks",
    }
    dim_icons = {"green": "🟢", "amber": "🟡", "red": "🔴"}

    cols = st.columns(5)
    for i, (key, label) in enumerate(dim_labels.items()):
        with cols[i % 5]:
            status = dims.get(key, "green")
            icon = dim_icons.get(status, "⚪")
            st.markdown(f"{icon} **{label}**")

    st.divider()

    # Summary counts
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.metric("🟢 Green", health["green"])
    with sc2:
        st.metric("🟡 Amber", health["amber"])
    with sc3:
        st.metric("🔴 Red", health["red"])

    # Action required
    if score < 6:
        st.error("⚠️ **Immediate action required.** Portfolio health is critical. Address RED dimensions before next trading session.")
    elif score < 8:
        st.warning("📋 **Attention needed.** Schedule a review within 5 days to address AMBER/RED items.")

    # FORTRESS summary
    st.divider()
    st.markdown("### 📋 FORTRESS Summary")
    summary = get_fortress_summary(
        regime=effective_regime,
        confidence=confidence,
        geo_tier=geo_tier,
        health_score=health,
        circuit_breakers=cb_result if 'cb_result' in dir() else {"any_breaker_active": False, "portfolio_level": {"level": "NONE"}},
        rebalancing_triggers=triggers if 'triggers' in dir() else [],
    )

    sum_cols = st.columns(4)
    with sum_cols[0]:
        st.metric("Regime", summary["regime_name"][:20])
    with sum_cols[1]:
        st.metric("Health", f"{summary['health_score']}/{summary['health_total']}")
    with sum_cols[2]:
        st.metric("Active Triggers", summary["active_triggers"])
    with sum_cols[3]:
        cb_status = "🔴 ACTIVE" if summary["circuit_breaker_active"] else "🟢 Clear"
        st.metric("Circuit Breakers", cb_status)
