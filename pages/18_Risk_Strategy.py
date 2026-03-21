"""
Risk & Strategy — Unified Portfolio Governance
================================================
Merges FORTRESS risk framework with Portfolio Optimizer.
Plain-English approach: regime awareness, position guidance, allocation
comparison, and concentration checks — all in one place.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

from core.database import (
    get_all_holdings, get_all_prosper_analyses, get_prosper_analysis, get_all_cash_positions,
    save_fortress_state, get_fortress_state, get_all_fortress_state,
)
from core.settings import SETTINGS
from core.cio_engine import enrich_portfolio
from core.data_engine import get_ticker_info_batch
from core.fortress import (
    detect_regime, get_geopolitical_tier, REGIME_NAMES, REGIME_COLORS, REGIME_DISPLAY,
    REGIME_EXPANSION, REGIME_OVERHEATING, REGIME_CONTRACTION, REGIME_RECOVERY,
    GEO_GREEN, GEO_AMBER, GEO_RED,
    get_exposure_limits, check_exposure_compliance,
    calculate_position_size, REGIME_SCALAR,
    analyze_factor_exposure, FACTOR_LIMITS,
    check_rebalancing_triggers,
    check_circuit_breakers, PORTFOLIO_BREAKERS, SINGLE_NAME_BREAKERS,
    compute_health_score,
    fortress_size_ticker, get_fortress_summary,
    BROKER_MARGIN_RATES, get_margin_rate, calculate_margin_cost,
)
from core.portfolio_optimizer import (
    MODEL_PORTFOLIOS, MODEL_DESCRIPTIONS,
    analyze_current_allocation, concentration_risk_check,
    suggest_rebalance, get_efficient_frontier, get_optimal_portfolio,
    HAS_SCIPY,
)

# ─────────────────────────────────────────
# Simplified labels — pulled from shared REGIME_DISPLAY in core/fortress.py
# ─────────────────────────────────────────
_REGIME_SIMPLE = {
    k: (v["label"], v["explanation"])
    for k, v in REGIME_DISPLAY.items()
}

_GEO_SIMPLE = {GEO_GREEN: "Calm", GEO_AMBER: "Elevated", GEO_RED: "Critical"}

# ─────────────────────────────────────────
# PAGE SETUP
# ─────────────────────────────────────────
st.markdown(
    "<h2 style='margin-bottom:0'>Risk & Strategy</h2>"
    "<p style='color:#888;margin-top:0'>Portfolio governance, regime awareness, position sizing & optimization</p>",
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
    with st.spinner("Loading portfolio data..."):
        enriched = enrich_portfolio(holdings, base_currency)
        st.session_state[cache_key] = enriched

if enriched.empty or "market_value" not in enriched.columns:
    st.warning("Portfolio data not ready. Visit the **Dashboard** first to load live prices.")
    st.stop()

enriched["market_value"] = pd.to_numeric(enriched["market_value"], errors="coerce").fillna(0)
enriched = enriched[enriched["market_value"] > 0]

if enriched.empty:
    st.warning("No holdings with valid market values.")
    st.stop()

# ── Fetch Ticker Info (cached) — use resolved tickers for yfinance coverage ──
_t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
tickers = enriched[_t_col].tolist()

@st.cache_data(ttl=3600, show_spinner=False)
def _get_info(tickers_tuple):
    return get_ticker_info_batch(list(tickers_tuple))

info_map = _get_info(tuple(tickers))
# Also map original tickers to info for functions that use original ticker names
if _t_col != "ticker":
    _orig_to_resolved = dict(zip(enriched["ticker"], enriched[_t_col]))
    for orig, resolved in _orig_to_resolved.items():
        if orig not in info_map and resolved in info_map:
            info_map[orig] = info_map[resolved]

# ── PROSPER analyses ──
prosper_df = get_all_prosper_analyses()
prosper_map = prosper_df.set_index("ticker").to_dict("index") if not prosper_df.empty else {}

# ── Portfolio metrics ──
total_mv = enriched["market_value"].sum()
enriched["weight_pct"] = enriched["market_value"] / total_mv * 100
# Use resolved tickers for allocation analysis (info_map is keyed by resolved tickers)
_alloc_df = enriched.copy()
if _t_col != "ticker" and _t_col in _alloc_df.columns:
    _alloc_df["ticker"] = _alloc_df[_t_col]
current_alloc = analyze_current_allocation(_alloc_df, info_map)

cash_positions = get_all_cash_positions()
total_cash = float(cash_positions["amount"].sum()) if not cash_positions.empty else 0.0
cash_pct = (total_cash / (total_mv + total_cash) * 100) if (total_mv + total_cash) > 0 else 0

max_single_pct = enriched["weight_pct"].max() if not enriched.empty else 0
sector_alloc = current_alloc.get("sector", {})
max_sector_pct = max(sector_alloc.values()) * 100 if sector_alloc else 0
geo_alloc = current_alloc.get("geography", {})
max_geo_pct = max(geo_alloc.values()) * 100 if geo_alloc else 0

portfolio_metrics = {
    "gross_exposure": 100, "net_exposure": 100,
    "cash_pct": cash_pct,
    "max_single_name_pct": max_single_pct,
    "max_sector_pct": max_sector_pct,
    "max_geo_pct": max_geo_pct,
}

# ── Sidebar: Regime Signals ──
with st.sidebar:
    st.subheader("Market Signals")
    vix = st.number_input("VIX", value=float(get_fortress_state("vix") or 18.0),
                          min_value=5.0, max_value=80.0, step=0.5, key="_f_vix")
    pmi = st.number_input("Global PMI", value=float(get_fortress_state("pmi") or 52.0),
                          min_value=30.0, max_value=65.0, step=0.5, key="_f_pmi")
    credit_spread = st.number_input("Credit Spread (bps)", value=float(get_fortress_state("credit_spread") or 110),
                                     min_value=50.0, max_value=500.0, step=5.0, key="_f_cs")
    yield_curve = st.number_input("Yield Curve 2s10s (%)", value=float(get_fortress_state("yield_curve") or 0.3),
                                   min_value=-2.0, max_value=3.0, step=0.05, key="_f_yc")
    inflation = st.number_input("Core CPI YoY (%)", value=float(get_fortress_state("inflation") or 2.8),
                                 min_value=0.0, max_value=15.0, step=0.1, key="_f_inf")
    fed = st.selectbox("Fed Direction", ["On hold", "Cutting", "Hiking", "Paused"],
                       index=["On hold", "Cutting", "Hiking", "Paused"].index(
                           get_fortress_state("fed_trajectory") or "On hold"), key="_f_fed")
    geo_conflicts = st.number_input("Active Conflicts", value=int(get_fortress_state("geo_conflicts") or 0),
                                     min_value=0, max_value=10, step=1, key="_f_geo")
    geo_sanctions = st.checkbox("Sanctions affecting portfolio",
                                 value=(get_fortress_state("geo_sanctions") == "True"), key="_f_sanctions")

    if st.button("Save & Update", type="primary", use_container_width=True):
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
effective_regime = REGIME_CONTRACTION if geo_tier == GEO_RED else current_regime

# ── Top Status Bar (plain English) ──
simple_name, simple_desc = _REGIME_SIMPLE.get(current_regime, ("Unknown", ""))
_rd = REGIME_DISPLAY.get(current_regime, {})
_regime_icon = _rd.get("icon", "")
_regime_action = _rd.get("action", "")
geo_simple = _GEO_SIMPLE.get(geo_tier, "Unknown")
r_color = _rd.get("color", REGIME_COLORS.get(current_regime, "#888"))

st.markdown(
    f"<div style='display:flex;gap:20px;padding:12px 18px;background:rgba(255,255,255,0.03);"
    f"border-radius:10px;border:1px solid rgba(255,255,255,0.08);margin-bottom:12px;flex-wrap:wrap;align-items:center'>"
    f"<div><span style='color:#999;font-size:0.8rem'>Market Regime</span><br>"
    f"<span style='background:{r_color};color:white;padding:3px 12px;border-radius:12px;"
    f"font-weight:700;font-size:0.95rem'>{simple_name}</span></div>"
    f"<div><span style='color:#999;font-size:0.8rem'>World Risk</span><br>"
    f"<b style='font-size:0.95rem'>{geo_simple}</b></div>"
    f"<div><span style='color:#999;font-size:0.8rem'>Holdings</span><br>"
    f"<b style='font-size:0.95rem'>{len(enriched)}</b></div>"
    f"<div><span style='color:#999;font-size:0.8rem'>Cash</span><br>"
    f"<b style='font-size:0.95rem'>{base_currency} {total_cash:,.0f} ({cash_pct:.0f}%)</b></div>"
    f"</div>",
    unsafe_allow_html=True,
)
# Plain-English summary: combine regime explanation + geo context
_combined_summary = {
    ("Growing", "Calm"): "Markets are favourable. You can take full-size positions in high-conviction stocks. No need to reduce exposure.",
    ("Growing", "Elevated"): "Economy is strong but geopolitical tensions exist. Maintain positions but keep extra cash as buffer.",
    ("Growing", "Critical"): "Economy is strong but world events are dangerous. Move to defensive positioning despite good fundamentals.",
    ("Heating Up", "Calm"): "Economy is showing late-cycle signals (rising inflation, stretched valuations). Start tightening stop-losses and trim overweight winners.",
    ("Heating Up", "Elevated"): "Late cycle + geopolitical risk. Be defensive: reduce position sizes, increase cash, avoid new speculative bets.",
    ("Heating Up", "Critical"): "Multiple risk factors converging. Move aggressively to cash and defensive holdings.",
    ("Slowing Down", "Calm"): "Economy weakening. Reduce equity exposure, increase cash, focus on quality defensive names.",
    ("Slowing Down", "Elevated"): "Economic weakness + geopolitical risk. Significantly reduce exposure. Cash is king.",
    ("Slowing Down", "Critical"): "Maximum caution. Minimize equity exposure. Preserve capital.",
    ("Bouncing Back", "Calm"): "Early recovery. Gradually build positions in quality growth stocks. Best risk/reward phase of the cycle.",
    ("Bouncing Back", "Elevated"): "Recovery underway but with geopolitical caution. Add selectively to high-conviction names.",
    ("Bouncing Back", "Critical"): "Recovery signals but world events are dangerous. Stay cautious despite improving fundamentals.",
}
_summary_text = _combined_summary.get((simple_name, geo_simple), simple_desc)
# Show regime explanation + action clearly (user complained they can't see what regime means)
st.markdown(
    f"<div style='margin:4px 0 12px 0;padding:12px 16px;border-radius:8px;"
    f"background:rgba(255,255,255,0.03);border-left:4px solid {r_color}'>"
    f"<div style='font-size:0.9rem;color:#ccc;margin-bottom:6px'>"
    f"{_regime_icon} <b>{simple_name}</b> — {simple_desc}</div>"
    f"<div style='font-size:0.85rem;color:#aaa;margin-bottom:6px'>"
    f"<b>What to do:</b> {_regime_action}</div>"
    f"<div style='font-size:0.85rem;color:#aaa'>"
    f"<b>With current world risk ({geo_simple}):</b> {_summary_text}</div>"
    f"</div>",
    unsafe_allow_html=True,
)

if geo_tier == GEO_RED:
    st.error("**World Risk: Critical** — All parameters forced to defensive mode. Reduce exposure immediately.")
elif geo_tier == GEO_AMBER:
    st.warning(f"**World Risk: Elevated** — {geo_result['action']}")

st.divider()

# ─────────────────────────────────────────
# 4 TABS (merged from FORTRESS 5 + Optimizer 3)
# ─────────────────────────────────────────
tab_health, tab_sizing, tab_alloc, tab_advanced = st.tabs([
    "Portfolio Health", "Position Guidance", "Allocation & Models", "Advanced",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: PORTFOLIO HEALTH (simplified scorecard + alerts + circuit breakers)
# ══════════════════════════════════════════════════════════════════════════════
with tab_health:

    # Health scorecard
    if prosper_map:
        scores_list = [v.get("score", 0) for v in prosper_map.values() if pd.notna(v.get("score"))]
        avg_prosper = sum(scores_list) / len(scores_list) if scores_list else 50
    else:
        avg_prosper = 50

    limits = get_exposure_limits(effective_regime, confidence, geo_tier)
    violations = check_exposure_compliance(portfolio_metrics, effective_regime, confidence, geo_tier)

    # Factor analysis
    analysis_df = st.session_state.get("extended_df", enriched)
    factor_analysis = analyze_factor_exposure(analysis_df, info_map)

    # Correlation data (if previously computed)
    corr_data = st.session_state.get("_fortress_corr")

    # Drawdown
    total_cost = pd.to_numeric(enriched.get("cost_basis", pd.Series(dtype=float)), errors="coerce").sum()
    portfolio_drawdown = ((total_mv - total_cost) / total_cost * 100) if total_cost > 0 else 0

    health = compute_health_score(
        regime=effective_regime,
        portfolio_df=enriched,
        exposure_violations=violations,
        factor_analysis=factor_analysis,
        correlation_data=corr_data,
        drawdown_pct=min(portfolio_drawdown, 0),
        avg_prosper_score=avg_prosper,
        kill_risk_count=0,
    )

    # Big score + plain English assessment
    score = health["score"]
    total = health["total"]
    score_color = "#1a9e5c" if score >= 8 else ("#f39c12" if score >= 5 else "#d63031")

    # Track score over time in session state
    prev_score = st.session_state.get("_health_score_prev")
    prev_dims = st.session_state.get("_health_dims_prev", {})
    st.session_state["_health_score_prev"] = score
    st.session_state["_health_dims_prev"] = health.get("dimensions", {})

    # Build change indicator
    score_change_text = ""
    change_reasons = []
    if prev_score is not None and prev_score != score:
        arrow = "\u2191" if score > prev_score else "\u2193"
        score_change_text = f" ({arrow} from {prev_score}/{total})"
        # Determine WHY score changed by comparing dimension statuses
        dims_now = health.get("dimensions", {})
        dim_labels_map = {
            "regime_alignment": "Market positioning",
            "exposure_compliance": "Risk limits",
            "single_name_concentration": "Single-stock risk",
            "sector_geo_concentration": "Sector/country spread",
            "factor_balance": "Investment style mix",
            "correlation": "Stock independence",
            "liquidity_coverage": "Cash buffer",
            "drawdown_status": "Loss control",
            "prosper_score_avg": "Stock quality",
            "open_kill_risks": "Deal-breaker risks",
        }
        status_rank = {"green": 0, "amber": 1, "red": 2}
        for dim_key, dim_label in dim_labels_map.items():
            old_status = prev_dims.get(dim_key, "green")
            new_status = dims_now.get(dim_key, "green")
            if status_rank.get(new_status, 0) > status_rank.get(old_status, 0):
                change_reasons.append(f"{dim_label} worsened")
            elif status_rank.get(new_status, 0) < status_rank.get(old_status, 0):
                change_reasons.append(f"{dim_label} improved")

    # Simplified assessment
    if score >= 9:
        health_label = "Excellent"
        health_advice = "Your portfolio is well-positioned. No immediate action needed."
    elif score >= 7:
        health_label = "Good"
        health_advice = "Minor items to review. No urgent action required."
    elif score >= 5:
        health_label = "Needs Attention"
        health_advice = "Some areas require adjustment within the next few days."
    else:
        health_label = "Action Required"
        health_advice = "Several issues need immediate attention. Review below."

    h1, h2 = st.columns([1, 3])
    with h1:
        st.markdown(
            f"<div style='text-align:center;padding:15px'>"
            f"<div style='font-size:56px;font-weight:700;color:{score_color}'>{score}/{total}{score_change_text}</div>"
            f"<div style='font-size:1.1rem;color:#ccc'>{health_label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with h2:
        st.markdown(f"**{health_advice}**")
        if change_reasons:
            st.caption(f"Score changed because: {', '.join(change_reasons[:3])}")

        # Dimension summary in plain English
        dims = health["dimensions"]
        dim_labels = {
            "regime_alignment": "Market positioning",
            "exposure_compliance": "Risk limits",
            "single_name_concentration": "Single-stock risk",
            "sector_geo_concentration": "Sector/country spread",
            "factor_balance": "Investment style mix",
            "correlation": "Stock independence",
            "liquidity_coverage": "Cash buffer",
            "drawdown_status": "Loss control",
            "prosper_score_avg": "Stock quality",
            "open_kill_risks": "Deal-breaker risks",
        }
        dim_icons = {"green": "🟢", "amber": "🟡", "red": "🔴"}

        cols = st.columns(5)
        for i, (key, label) in enumerate(dim_labels.items()):
            with cols[i % 5]:
                status = dims.get(key, "green")
                st.markdown(f"{dim_icons.get(status, '⚪')} {label}")

    st.divider()

    # ── Alerts & Circuit Breakers (combined) ──
    st.markdown("#### Alerts")

    # Rebalancing triggers
    prev_regime = get_fortress_state("prev_regime")
    triggers = check_rebalancing_triggers(
        portfolio_df=enriched,
        regime=effective_regime,
        prev_regime=prev_regime,
        drawdown_pct=min(portfolio_drawdown, 0),
        factor_violations=factor_analysis.get("violations", []) if factor_analysis else [],
        correlation_zone=corr_data.get("overall_zone", "green") if corr_data else "green",
    )

    # Position-level drawdowns for circuit breakers
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

    has_alerts = False

    # Circuit breaker alerts (most urgent first)
    if cb_result["portfolio_level"]["level"] != "NONE":
        pl = cb_result["portfolio_level"]
        st.error(f"**Portfolio down {portfolio_drawdown:.1f}%** — {pl['action']}")
        has_alerts = True

    for alert in cb_result.get("position_alerts", []):
        ticker = alert["ticker"]
        drawdown = alert["drawdown"]
        # Look up PROSPER analysis for this ticker
        pa = prosper_map.get(ticker)
        if pa:
            analysis_date_str = pa.get("analysis_date", "")
            is_recent = False
            try:
                analysis_dt = datetime.strptime(analysis_date_str[:10], "%Y-%m-%d")
                is_recent = (datetime.now() - analysis_dt) <= timedelta(days=30)
            except (ValueError, TypeError):
                pass

            if is_recent:
                rating = pa.get("rating", "N/A")
                p_score = pa.get("score", 0)
                conviction = pa.get("conviction", "N/A")
                thesis = pa.get("thesis", "No thesis available")
                # Truncate thesis for display
                thesis_short = thesis[:120] + "..." if len(str(thesis)) > 120 else thesis

                # Cross-reference PROSPER score with drawdown severity
                score_num = float(p_score) if p_score else 0
                conv_upper = str(conviction).upper()

                if score_num >= 70 and conv_upper in ("HIGH", "VERY HIGH"):
                    if abs(drawdown) < 20:
                        action_text = "Drawdown within tolerable range for a high-conviction position. Thesis intact — HOLD."
                    else:
                        action_text = "Drawdown exceeds normal range but thesis intact. Consider adding on weakness if cash allows."
                elif score_num >= 50:
                    if abs(drawdown) < 15:
                        action_text = "Moderate-conviction position under pressure. Monitor closely for thesis deterioration."
                    else:
                        action_text = "Thesis may be weakening under sustained drawdown. Consider trimming 25-50% to reduce risk."
                else:
                    action_text = "Low PROSPER score combined with significant drawdown. Thesis weakened — consider exiting or trimming aggressively."

                st.warning(
                    f"**{ticker}** down {drawdown:.1f}% | "
                    f"PROSPER: **{rating}** ({score_num:.0f}/100, {conviction} conviction) | "
                    f"Thesis: {thesis_short} | "
                    f"→ {action_text}"
                )
            else:
                # Analysis exists but is stale (>30 days)
                st.warning(
                    f"**{ticker}** is down {drawdown:.1f}% — "
                    f"PROSPER analysis is over 30 days old (from {analysis_date_str[:10]}). "
                    f"Re-run PROSPER analysis to get current conviction-weighted guidance."
                )
        else:
            # No PROSPER analysis exists
            st.warning(
                f"**{ticker}** is down {drawdown:.1f}% — "
                f"No PROSPER analysis found. Run a PROSPER analysis on this ticker "
                f"to get a specific recommendation on whether to hold, trim, or add."
            )
        has_alerts = True

    # Rebalancing triggers (simplified language)
    if triggers:
        for t in triggers[:5]:
            urgency_icon = {"IMMEDIATE": "🔴", "HIGH": "🟠", "MODERATE": "🟡", "LOW": "🟢"}.get(t["urgency"], "⚪")
            st.markdown(f"{urgency_icon} **{t['trigger']}** — {t['action']}")
        has_alerts = True

    # Concentration warnings (use resolved tickers for info lookup)
    risk_df = enriched.copy()
    from core.portfolio_optimizer import _normalise_sector
    risk_df["sector"] = risk_df[_t_col].apply(lambda t: _normalise_sector(info_map.get(t, {})))
    risk_df["country"] = risk_df[_t_col].apply(lambda t: (info_map.get(t, {}).get("country") or "Unknown"))
    conc_warnings = concentration_risk_check(risk_df)
    if conc_warnings:
        for w in conc_warnings[:3]:
            st.markdown(f"🟡 **Concentration:** {w['detail']}")
        has_alerts = True

    if not has_alerts:
        st.success("No alerts — portfolio looks healthy.")

    # ── Exposure Governor (with explanations) ──
    with st.expander("Exposure Limits — What do these mean?"):
        _param_explain = {
            "Gross Exposure": "Total value of all positions as % of portfolio. 100% = fully invested.",
            "Net Exposure": "Long positions minus short positions. 100% = all long, no hedging.",
            "Cash Pct": "Cash as % of total portfolio. Higher = more defensive.",
            "Max Single Name Pct": "Largest single stock as % of portfolio. Over 10% = concentrated risk.",
            "Max Sector Pct": "Largest sector as % of portfolio. Over 30% = sector concentration.",
            "Max Geo Pct": "Largest country as % of portfolio. Over 50% = geographic concentration.",
        }
        exp_rows = []
        for v in violations:
            status_icon = {"OK": "🟢", "BELOW_MIN": "🟡", "ABOVE_MAX": "🔴"}.get(v["status"], "⚪")
            param_name = v["param"].replace("_", " ").title()
            exp_rows.append({
                "Parameter": param_name,
                "Current": f"{v['current']:.1f}%",
                "Min": f"{v['limit_min']:.0f}%",
                "Max": f"{v['limit_max']:.0f}%",
                "Status": f"{status_icon} {v['status'].replace('_', ' ')}",
            })
        st.dataframe(pd.DataFrame(exp_rows), use_container_width=True, hide_index=True)
        st.caption("Limits auto-adjust based on market regime. In 'Slowing Down' mode, limits get tighter (more defensive).")
        for name, explain in _param_explain.items():
            st.markdown(f"- **{name}:** {explain}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: POSITION GUIDANCE (sizing + per-stock actions)
# ══════════════════════════════════════════════════════════════════════════════
with tab_sizing:
    st.markdown("#### Position Guidance")

    # Build guidance data
    sizing_rows = []
    action_counts = {"Hold": 0, "Trim": 0, "Add": 0, "Sell": 0}
    for _, row in enriched.iterrows():
        ticker = row["ticker"]
        current_weight = row["weight_pct"]
        prosper_data = prosper_map.get(ticker, {})
        prosper_score = prosper_data.get("score", 50)

        sizing = calculate_position_size(
            prosper_score=prosper_score if pd.notna(prosper_score) else 50,
            regime=effective_regime,
        )

        target = sizing["size_pct"]
        diff = current_weight - target if target > 0 else 0
        if target == 0:
            action = "Sell"
        elif abs(diff) < 0.5:
            action = "Hold"
        elif diff > 0:
            action = "Trim"
        else:
            action = "Add"
        action_counts[action] = action_counts.get(action, 0) + 1

        conv_simple = {
            "MAXIMUM": "Very High", "HIGH": "High",
            "MODERATE": "Medium", "LOW": "Low", "NO_POSITION": "Sell"
        }.get(sizing["conviction_tier"], sizing["conviction_tier"])

        sizing_rows.append({
            "Ticker": ticker,
            "Name": str(row.get("name", ""))[:20],
            "Score": prosper_score if pd.notna(prosper_score) else 50,
            "Confidence": conv_simple,
            "Current %": current_weight,
            "Target %": target,
            "Action": action,
        })

    sizing_df = pd.DataFrame(sizing_rows)

    # ── Visual Action Summary (cards) ──
    regime_scalar = REGIME_SCALAR.get(effective_regime, 0.75)
    st.markdown(
        f"<div style='padding:12px 16px;border-radius:10px;background:rgba(255,255,255,0.03);"
        f"border:1px solid rgba(255,255,255,0.08);margin-bottom:12px'>"
        f"<p style='margin:0 0 8px 0;color:#999;font-size:0.85rem'>"
        f"Regime: <b>{simple_name}</b> — positions scaled to <b>{regime_scalar:.0%}</b> of normal. "
        f"Guidance is based on your Prosper AI score for each stock.</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    _action_colors = {"Hold": "#4CAF50", "Add": "#2196F3", "Trim": "#FF9800", "Sell": "#f44336"}
    _action_icons = {"Hold": "✅", "Add": "📈", "Trim": "✂️", "Sell": "🚫"}
    action_cols = st.columns(4)
    for i, (act, cnt) in enumerate(action_counts.items()):
        with action_cols[i]:
            st.markdown(
                f"<div style='text-align:center;padding:10px;border-radius:8px;"
                f"border:2px solid {_action_colors[act]};background:rgba(255,255,255,0.02)'>"
                f"<div style='font-size:1.5rem'>{_action_icons[act]}</div>"
                f"<div style='font-size:1.4rem;font-weight:700;color:{_action_colors[act]}'>{cnt}</div>"
                f"<div style='font-size:0.8rem;color:#999'>{act}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ── Visual chart: action-colored scatter plot ──
    if not sizing_df.empty:
        fig_guide = go.Figure()
        for act in ["Sell", "Trim", "Hold", "Add"]:
            mask = sizing_df["Action"] == act
            subset = sizing_df[mask]
            if not subset.empty:
                fig_guide.add_trace(go.Scatter(
                    x=subset["Current %"], y=subset["Target %"],
                    mode="markers+text", text=subset["Ticker"],
                    textposition="top center", textfont=dict(size=9),
                    marker=dict(size=10, color=_action_colors[act]),
                    name=f"{act} ({len(subset)})",
                ))
        # Add diagonal line (current = target)
        max_val = max(sizing_df["Current %"].max(), sizing_df["Target %"].max(), 5)
        fig_guide.add_trace(go.Scatter(
            x=[0, max_val], y=[0, max_val], mode="lines",
            line=dict(dash="dash", color="rgba(255,255,255,0.2)"),
            showlegend=False,
        ))
        fig_guide.update_layout(
            height=350, margin=dict(t=10, l=40, r=10, b=40),
            xaxis_title="Current Weight %", yaxis_title="Target Weight %",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=-0.15),
        )
        st.plotly_chart(fig_guide, use_container_width=True)
        st.caption("*Stocks above the line need adding, below need trimming.*")

    st.divider()

    # ── Detailed Table ──
    st.markdown("#### Detailed Guidance")
    display_sizing = sizing_df.copy()
    display_sizing["Score"] = display_sizing["Score"].apply(lambda x: f"{x:.0f}")
    display_sizing["Current %"] = display_sizing["Current %"].apply(lambda x: f"{x:.1f}%")
    display_sizing["Target %"] = display_sizing["Target %"].apply(lambda x: f"{x:.1f}%" if x > 0 else "Exit")

    def _color_action(val):
        colors = {"Trim": "color:#ff9800;font-weight:600", "Add": "color:#2196f3;font-weight:600",
                  "Sell": "color:#d63031;font-weight:700", "Hold": "color:#4caf50"}
        return colors.get(val, "")

    styled = display_sizing[["Ticker", "Name", "Score", "Confidence", "Current %", "Target %", "Action"]].style.map(
        _color_action, subset=["Action"]
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # Quick sizing calculator
    with st.expander("Size a specific ticker"):
        calc_cols = st.columns(4)
        with calc_cols[0]:
            calc_ticker = st.text_input("Ticker", value="", placeholder="e.g. AAPL", key="_calc_ticker")
        with calc_cols[1]:
            calc_score = st.number_input("Score (0-100)", value=70.0, min_value=0.0, max_value=100.0, step=1.0, key="_calc_score")
        with calc_cols[2]:
            calc_p = st.number_input("Win probability", value=0.60, min_value=0.1, max_value=0.95, step=0.05, key="_calc_p")
        with calc_cols[3]:
            calc_rr = st.number_input("Reward/Risk ratio", value=2.0, min_value=0.5, max_value=10.0, step=0.25, key="_calc_rr")

        if st.button("Calculate", type="primary", key="_calc_btn"):
            result = fortress_size_ticker(
                ticker=calc_ticker or "TICKER",
                prosper_score=calc_score,
                regime=effective_regime,
                p_bull=calc_p,
                reward_risk=calc_rr,
            )
            if result["action"] == "BLOCKED":
                st.error(result['reason'])
            elif result["size_pct"] == 0:
                st.warning(result['recommendation'])
            else:
                st.success(f"**{result['ticker']}**: allocate {result['size_pct']:.1f}% of portfolio")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: ALLOCATION & MODELS (from Optimizer)
# ══════════════════════════════════════════════════════════════════════════════
with tab_alloc:
    # Current allocation (single set of pie charts — no duplication)
    st.markdown("#### Your Current Allocation")
    ac_cols = st.columns(4)
    for i, (dim, label) in enumerate([
        ("asset_class", "Asset Class"), ("sector", "Sector"),
        ("geography", "Geography"), ("cap_size", "Market Cap"),
    ]):
        with ac_cols[i]:
            alloc = current_alloc.get(dim, {})
            # Filter out meaningless "Unknown" if it's the only entry
            if alloc:
                alloc = {k: v for k, v in alloc.items() if k not in ("Unknown", "", "None") or len(alloc) == 1}
            if alloc and len(alloc) > 1:
                fig = px.pie(values=list(alloc.values()), names=list(alloc.keys()),
                             title=label, hole=0.4,
                             color_discrete_sequence=px.colors.qualitative.Set2)
                fig.update_layout(height=250, margin=dict(t=35, l=5, r=5, b=5),
                                  showlegend=True, legend=dict(font=dict(size=9)),
                                  paper_bgcolor="rgba(0,0,0,0)")
                fig.update_traces(textposition="inside", textinfo="percent+label",
                                  textfont_size=10)
                st.plotly_chart(fig, use_container_width=True)
            elif alloc:
                # Single category — show as metric instead of pie
                k, v = list(alloc.items())[0]
                st.metric(label, k, f"{v*100:.0f}%")

    st.divider()

    # Model portfolio comparison
    st.markdown("#### Compare to Model Portfolios")
    selected_model = st.selectbox(
        "Choose a strategy",
        list(MODEL_PORTFOLIOS.keys()),
        index=3,  # Default: Balanced Growth
    )
    if selected_model in MODEL_DESCRIPTIONS:
        st.info(f"**{selected_model}:** {MODEL_DESCRIPTIONS[selected_model]}")

    rebalance = suggest_rebalance(current_alloc.get("asset_class", {}), selected_model)
    if rebalance:
        reb_df = pd.DataFrame(rebalance)

        fig_compare = go.Figure()
        fig_compare.add_trace(go.Bar(name="Current", x=reb_df["category"], y=reb_df["current_pct"], marker_color="#1E88E5"))
        fig_compare.add_trace(go.Bar(name=f"Target ({selected_model})", x=reb_df["category"], y=reb_df["target_pct"], marker_color="#FF9800"))
        fig_compare.update_layout(barmode="group", height=320, margin=dict(t=20, l=40, r=20, b=20),
                                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_compare, use_container_width=True)

        # Summary actions
        overweight = [r for r in rebalance if r["action"] == "Overweight"]
        underweight = [r for r in rebalance if r["action"] == "Underweight"]
        if overweight:
            st.markdown("**Trim:** " + ", ".join(f"{r['category']} ({r['diff_pct']:+.1f}%)" for r in overweight))
        if underweight:
            st.markdown("**Add:** " + ", ".join(f"{r['category']} ({r['diff_pct']:+.1f}%)" for r in underweight))

    st.divider()

    # Concentration snapshot
    st.markdown("#### Concentration Risk")
    weight_df = enriched[["ticker", "market_value"]].copy()
    weight_df["weight_pct"] = (weight_df["market_value"] / weight_df["market_value"].sum() * 100)
    weight_df = weight_df.sort_values("weight_pct", ascending=True).tail(15)

    fig_w = px.bar(weight_df, x="weight_pct", y="ticker", orientation="h",
                   color="weight_pct", color_continuous_scale=["#1E88E5", "#FF9800", "#d32f2f"],
                   labels={"weight_pct": "Weight %", "ticker": ""})
    fig_w.add_vline(x=10, line_dash="dash", line_color="red", annotation_text="10% limit")
    fig_w.update_layout(height=380, margin=dict(t=10, l=10, r=10, b=10),
                        showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_w, use_container_width=True)

    # HHI with explanation
    if total_mv > 0:
        weights = enriched["market_value"] / total_mv
        hhi = (weights ** 2).sum() * 10000
        if hhi < 1000:
            hhi_label, hhi_color, hhi_icon = "Highly Diversified", "#4CAF50", "🟢"
        elif hhi < 1500:
            hhi_label, hhi_color, hhi_icon = "Well Diversified", "#8BC34A", "🟢"
        elif hhi < 2500:
            hhi_label, hhi_color, hhi_icon = "Moderately Concentrated", "#FF9800", "🟡"
        else:
            hhi_label, hhi_color, hhi_icon = "Concentrated", "#f44336", "🔴"
        st.markdown(f"#### Diversification Score")
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:12px;padding:10px 16px;"
            f"background:rgba(255,255,255,0.03);border-radius:10px;border:1px solid rgba(255,255,255,0.08)'>"
            f"<span style='font-size:2rem;font-weight:700;color:{hhi_color}'>{hhi:.0f}</span>"
            f"<div><b>{hhi_icon} {hhi_label}</b><br>"
            f"<span style='font-size:0.8rem;color:#999'>HHI Scale: "
            f"<span style='color:#4CAF50'>0-1500 Diversified</span> · "
            f"<span style='color:#FF9800'>1500-2500 Moderate</span> · "
            f"<span style='color:#f44336'>2500+ Concentrated</span></span></div>"
            f"</div>",
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: ADVANCED (efficient frontier, factor analysis, correlations, margin)
# ══════════════════════════════════════════════════════════════════════════════
with tab_advanced:
    adv_section = st.selectbox("Section", [
        "Efficient Frontier (MPT)",
        "Factor Exposure",
        "Correlation Analysis",
        "Regime Signals Detail",
        "Cash & Margin",
    ])

    if adv_section == "Efficient Frontier (MPT)":
        if not HAS_SCIPY:
            st.warning("scipy required. Install with: `pip install scipy`")
        else:
            st.markdown(
                "**What is this?** The Efficient Frontier shows all possible portfolio mixes of your stocks, "
                "plotted by risk (volatility) vs return. The *optimal* portfolio gives you the best return per "
                "unit of risk (highest Sharpe ratio). If your portfolio is far from the frontier, you could "
                "get better returns without taking more risk."
            )
            st.caption("🟠 Orange = your portfolio · ⭐ Green star = optimal (highest return per risk)")
            ticker_list = enriched[_t_col].tolist()
            weight_list = (enriched["market_value"] / total_mv).tolist()
            period = st.selectbox("Lookback", ["6mo", "1y", "2y"], index=1)

            if st.button("Compute Frontier", type="primary"):
                with st.spinner("Computing..."):
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
                current_pts = [p for p in frontier if p.get("is_current")]
                random_pts = [p for p in frontier if not p.get("is_current")]

                fig_ef = go.Figure()
                if random_pts:
                    rp_df = pd.DataFrame(random_pts)
                    fig_ef.add_trace(go.Scatter(
                        x=rp_df["risk"]*100, y=rp_df["return_"]*100, mode="markers",
                        marker=dict(size=5, color=rp_df["sharpe"], colorscale="Viridis",
                                    colorbar=dict(title="Sharpe"), opacity=0.6),
                        name="Random Portfolios"))
                if current_pts:
                    cp = current_pts[0]
                    fig_ef.add_trace(go.Scatter(
                        x=[cp["risk"]*100], y=[cp["return_"]*100], mode="markers",
                        marker=dict(size=16, color="#FF9800", symbol="circle", line=dict(width=2, color="white")),
                        name=f"Your Portfolio (Sharpe: {cp['sharpe']:.2f})"))
                if optimal and optimal.get("risk"):
                    fig_ef.add_trace(go.Scatter(
                        x=[optimal["risk"]*100], y=[optimal["return_"]*100], mode="markers",
                        marker=dict(size=18, color="#00E676", symbol="star", line=dict(width=2, color="white")),
                        name=f"Optimal (Sharpe: {optimal['sharpe']:.2f})"))

                fig_ef.update_layout(
                    xaxis_title="Volatility (%)", yaxis_title="Return (%)",
                    height=450, margin=dict(t=10, l=50, r=20, b=50),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_ef, use_container_width=True)

                if current_pts and optimal and optimal.get("risk"):
                    cp = current_pts[0]
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Your Portfolio**")
                        st.metric("Return", f"{cp['return_']*100:.1f}%")
                        st.metric("Risk", f"{cp['risk']*100:.1f}%")
                        st.metric("Sharpe", f"{cp['sharpe']:.2f}")
                    with c2:
                        st.markdown("**Optimal Portfolio**")
                        st.metric("Return", f"{optimal['return_']*100:.1f}%",
                                  f"{(optimal['return_']-cp['return_'])*100:+.1f}%")
                        st.metric("Risk", f"{optimal['risk']*100:.1f}%",
                                  f"{(optimal['risk']-cp['risk'])*100:+.1f}%")
                        st.metric("Sharpe", f"{optimal['sharpe']:.2f}",
                                  f"{optimal['sharpe']-cp['sharpe']:+.2f}")

    elif adv_section == "Factor Exposure":
        st.markdown(
            "**What is this?** Factor exposure shows your portfolio's tilt towards different investment styles. "
            "Over-concentration in one style increases risk if that style falls out of favour."
        )
        _factor_explain = {
            "value": "Cheap stocks (low P/E, high dividend) — outperform in recoveries, lag in momentum markets",
            "growth": "High-growth companies — outperform in expansion, risky in downturns",
            "quality": "Profitable, low-debt companies — defensive, steady performers",
            "momentum": "Recent winners — strong in trends, sharp reversals in regime shifts",
            "size": "Small-cap tilt — higher return potential but more volatile",
        }
        if factor_analysis["factors"]:
            factor_rows = []
            for factor, pct in factor_analysis["factors"].items():
                limit = FACTOR_LIMITS.get(factor, {}).get("max_pct", 100)
                status = "🟢 OK" if pct <= limit else "🔴 Over limit"
                factor_rows.append({
                    "Style": factor.replace("_", " ").title(),
                    "Exposure": f"{pct:.1f}%",
                    "Limit": f"{limit}%",
                    "Status": status,
                    "What it means": _factor_explain.get(factor, ""),
                })
            st.dataframe(pd.DataFrame(factor_rows), use_container_width=True, hide_index=True)

            # Radar chart for visual overview
            f_names = [f.replace("_", " ").title() for f in factor_analysis["factors"].keys()]
            f_vals = list(factor_analysis["factors"].values())
            if len(f_names) >= 3:
                fig_radar = go.Figure(go.Scatterpolar(
                    r=f_vals + [f_vals[0]], theta=f_names + [f_names[0]],
                    fill="toself", fillcolor="rgba(30,136,229,0.15)",
                    line=dict(color="#1E88E5", width=2),
                ))
                fig_radar.update_layout(
                    polar=dict(radialaxis=dict(visible=True, range=[0, max(f_vals) * 1.2])),
                    height=300, margin=dict(t=20, l=40, r=40, b=20),
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_radar, use_container_width=True)
        else:
            st.info(
                "No factor data available yet. Visit the **Portfolio Dashboard** and click "
                "**Load Extended Metrics** to enrich your holdings with style/factor data."
            )

    elif adv_section == "Correlation Analysis":
        st.markdown(
            "**What is this?** Correlation measures how your stocks move relative to each other. "
            "If everything is highly correlated (dark red), a single bad event can drag down your "
            "entire portfolio. Green/low values mean your stocks provide real diversification."
        )
        if st.button("Compute Correlations", type="primary"):
            with st.spinner("Fetching 3-month price data for top 20 holdings..."):
                try:
                    from core.data_engine import get_history
                    from core.fortress import calculate_correlation_matrix
                    frames = {}
                    for t in tickers[:20]:
                        hist = get_history(t, period="3mo")
                        if hist is not None and not hist.empty:
                            close = hist["Close"] if "Close" in hist.columns else hist.iloc[:, 0]
                            frames[t] = close
                    if len(frames) >= 2:
                        prices = pd.DataFrame(frames).dropna()
                        returns = prices.pct_change().dropna().tail(60)
                        st.session_state["_fortress_corr"] = calculate_correlation_matrix(returns)
                    else:
                        st.warning("Need at least 2 tickers with price history.")
                except Exception as e:
                    st.error(f"Failed: {e}")

        corr_data = st.session_state.get("_fortress_corr")
        if corr_data and corr_data.get("correlation_matrix"):
            corr_matrix = pd.DataFrame(corr_data["correlation_matrix"])
            fig_corr = px.imshow(corr_matrix, text_auto=".2f", color_continuous_scale="RdYlGn_r",
                                 zmin=-1, zmax=1, aspect="auto")
            fig_corr.update_layout(height=400, margin=dict(t=10, l=10, r=10, b=10))
            st.plotly_chart(fig_corr, use_container_width=True)

            zone = corr_data["overall_zone"]
            zone_labels = {
                "green": "🟢 Your stocks move independently — good diversification",
                "amber": "🟡 Some herding detected — consider adding uncorrelated assets",
                "red": "🔴 High correlation — your portfolio may drop together in a downturn",
            }
            st.info(f"**{zone_labels.get(zone, zone.upper())}")

            avg_corr = corr_data.get("average_correlation")
            if avg_corr is not None:
                st.caption(f"Average pairwise correlation: {avg_corr:.2f} (below 0.4 is ideal)")
        else:
            st.caption("Click the button above to compute correlations. Takes ~10 seconds for 20 holdings.")

    elif adv_section == "Regime Signals Detail":
        st.markdown(
            "**What is this?** The regime detector scores four possible economic states based on your "
            "market signals (VIX, PMI, credit spreads, yield curve, inflation, Fed policy). "
            "The highest-scoring regime determines your portfolio's risk posture."
        )
        _regime_labels = {k: v["label"] for k, v in REGIME_DISPLAY.items()}
        scores = regime_result["scores"]
        score_df = pd.DataFrame([
            {"Regime": _regime_labels.get(r, REGIME_NAMES.get(r, r)), "Score": s}
            for r, s in scores.items()
        ])
        fig_regime = go.Figure(go.Bar(
            x=score_df["Score"], y=score_df["Regime"], orientation="h",
            marker_color=[REGIME_COLORS[r] for r in scores.keys()],
            text=score_df["Score"].apply(lambda x: f"{x:.1f}"), textposition="outside"))
        fig_regime.update_layout(height=250, margin=dict(t=10, l=10, r=40, b=10),
                                 paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_regime, use_container_width=True)

        # Show which signals drove the decision
        if regime_result.get("signals_used"):
            st.markdown("**Signals that drove this regime call:**")
            for sig in regime_result["signals_used"]:
                st.markdown(f"- {sig}")

        st.caption(
            "💡 Adjust signals in the sidebar and click *Save & Update* to recalculate. "
            "The regime with the highest score wins."
        )

    elif adv_section == "Cash & Margin":
        if not cash_positions.empty:
            for _, cp in cash_positions.iterrows():
                broker = cp.get("broker_source", "") or "Unknown"
                currency = cp.get("currency", "USD")
                amount = float(cp["amount"])
                is_margin = bool(cp.get("is_margin", 0))
                if is_margin or amount < 0:
                    margin_info = get_margin_rate(broker, amount, currency)
                    rate = cp.get("margin_rate") or margin_info.get("rate") or 0
                    annual_cost = calculate_margin_cost(amount, rate) if rate else 0
                    st.markdown(
                        f"🔴 **{cp['account_name']}** ({broker}) — "
                        f"{currency} {amount:,.2f} · Rate: **{rate:.2f}%** · "
                        f"Annual cost: **{currency} {annual_cost:,.0f}**")
                else:
                    st.markdown(f"🟢 **{cp['account_name']}** ({broker}) — {currency} {amount:,.2f}")

            with st.expander("Broker Margin Rate Comparison"):
                rate_rows = []
                for broker_key, data in BROKER_MARGIN_RATES.items():
                    for cur, rate in data.get("currency_rates", {}).items():
                        rate_rows.append({"Broker": data["name"], "Currency": cur, "Rate %": rate})
                rate_df = pd.DataFrame(rate_rows)
                if not rate_df.empty:
                    pivot = rate_df.pivot_table(index="Broker", columns="Currency", values="Rate %", aggfunc="first")
                    st.dataframe(pivot.style.format("{:.2f}%", na_rep="—"), use_container_width=True)
        else:
            st.info("No cash positions recorded. Add them via Upload Portal.")
