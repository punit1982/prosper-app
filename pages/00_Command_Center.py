"""
Prosper Command Center v2 — Executive Dashboard
=================================================
Bloomberg-style CIO morning view: market context, portfolio pulse,
performance attribution, FORTRESS regime, alerts, and AI briefing.
"""

import time
import streamlit as st
from core.ui_components import show_chart
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

from core.database import (
    get_all_holdings, get_nav_history, get_all_prosper_analyses,
    get_total_realized_pnl, get_all_cash_positions, get_price_cache_age,
)
try:
    from core.database import save_briefing, get_latest_briefing
except ImportError:
    save_briefing = None
    get_latest_briefing = None
from core.settings import SETTINGS, get_api_key, enriched_cache_key
from core.cio_engine import enrich_portfolio
from core.data_engine import fmt_large
from core.ui_components import fmt_age
from core.ui_errors import safe_message
import core.ledger_ui as _lu

# ── Page Header ──────────────────────────────────────────────────────────────
# Rendered after the data loads, so the date, the base currency and the
# data-freshness age fold into ONE line instead of three stacked blocks.

# ── Load Portfolio Data ──────────────────────────────────────────────────────
base_currency = SETTINGS.get("base_currency", "USD")
holdings = get_all_holdings()

if holdings.empty:
    st.info("Welcome to Prosper! Upload your first brokerage screenshot or CSV to get started.")
    st.page_link("pages/1_Upload_Portal.py", label="Go to Upload Portal", icon="📤")
    st.stop()

# ── Enrich Portfolio (use cache if available) ────────────────────────────────
cache_key = enriched_cache_key(base_currency)
if cache_key in st.session_state and st.session_state[cache_key] is not None and not st.session_state[cache_key].empty:
    enriched = st.session_state[cache_key]
else:
    # A skeleton shaped like the page, not a spinner. On the free tier this
    # instance spins down when idle, so a cold visit waits 30-60s before any
    # pixel of data — which makes this genuinely the most-seen screen in the
    # product. Saying what is happening and roughly how long beats a spinner
    # that could mean anything, and matching the row geometry stops the page
    # jumping when the data lands.
    import core.ledger_ui as _boot
    _boot.write(_boot.CSS)
    _ph = st.empty()
    with _ph.container():
        _boot.write(
            '<div class="p-hero"><div class="p-sk" style="width:52%;height:34px"></div>'
            '<div class="p-sk" style="width:36%;height:14px;margin-top:10px"></div></div>',
            '<div class="p-prov"><span>Pricing '
            f'{len(holdings)} holdings across every market. First load after an '
            'idle period also has to wake the server — up to a minute.</span></div>',
            _boot.section("Today's moves"),
            _boot.skeleton(4),
        )
    enriched = enrich_portfolio(holdings, base_currency)
    st.session_state[cache_key] = enriched
    st.session_state.setdefault("last_refresh_time", time.time())
    _ph.empty()

# Data-freshness caption — this view reuses whatever was last fetched (here or
# on Portfolio Dashboard) rather than re-fetching, so make that explicit
# instead of leaving the user unsure whether the numbers are live or stale.
_refresh_ts = st.session_state.get("last_refresh_time")
if _refresh_ts:
    _age_txt = fmt_age(time.time() - _refresh_ts)
else:
    _sqlite_age = get_price_cache_age()
    _age_txt = fmt_age(_sqlite_age) if (_sqlite_age is not None and _sqlite_age > 0) else "live"

from core.ui_components import page_header as _page_header
_page_header(
    "Command Center",
    f"{datetime.now().strftime('%a, %d %b %Y')} · {base_currency} · data {_age_txt}",
)

if enriched.empty:
    # An error state names what went wrong and what to do, and offers the
    # action rather than describing it.
    _ui.write(_ui.empty(
        "No prices came back",
        f"You hold {len(holdings)} positions, but the price layer returned "
        "nothing for any of them. That is usually a provider being briefly "
        "unreachable rather than anything wrong with your holdings — the "
        "figures return on the next refresh.",
    ))
    _c1, _c2 = st.columns(2)
    with _c1:
        if st.button("Try again", type="primary", use_container_width=True):
            st.session_state.pop(cache_key, None)
            st.rerun()
    with _c2:
        st.page_link("pages/0_Settings.py", label="Check data sources", icon="📡",
                     use_container_width=True)
    st.stop()

# ── Normalize column names ────────────────────────────────────────────────
# Enrichment creates 'change_pct'; ensure 'day_change_pct' alias exists for charts
if "change_pct" in enriched.columns and "day_change_pct" not in enriched.columns:
    enriched["day_change_pct"] = enriched["change_pct"]

# Also calculate day_change_pct from price_change if change_pct is all None
if "day_change_pct" not in enriched.columns or enriched.get("day_change_pct") is None or enriched["day_change_pct"].isna().all():
    if "price_change" in enriched.columns and "current_price" in enriched.columns:
        _pc = pd.to_numeric(enriched["price_change"], errors="coerce")
        _cp = pd.to_numeric(enriched["current_price"], errors="coerce")
        enriched["day_change_pct"] = (_pc / (_cp - _pc) * 100).round(4)

# ── Use resolved tickers for all lookups ──────────────────────────────────
_t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"

# Enrich with sector data if not already present (needed for heatmap + allocation)
if "sector" not in enriched.columns or enriched["sector"].isna().all():
    from core.data_engine import get_ticker_info_batch, resolve_sector
    _cmd_tickers = enriched[_t_col].tolist()

    @st.cache_data(ttl=3600, show_spinner=False)
    def _cmd_sector_fetch(tickers_tuple):
        return get_ticker_info_batch(list(tickers_tuple))

    _cmd_info = _cmd_sector_fetch(tuple(_cmd_tickers))

    def _assign_sector(row):
        ticker = row[_t_col]
        info = _cmd_info.get(ticker, {})
        name = str(row.get("name", "") or "")
        # Use resolve_sector which falls back to name-based keyword matching
        # for tickers that yfinance doesn't know (e.g. SGX, ADX, Swiss listings)
        return resolve_sector(ticker, info, name, asset_category=str(row.get("asset_category", "") or ""))

    enriched["sector"] = enriched.apply(_assign_sector, axis=1)

# ── Compute Key Metrics ──────────────────────────────────────────────────────
total_value = pd.to_numeric(enriched.get("market_value"), errors="coerce").dropna().sum()
total_cost = pd.to_numeric(enriched.get("cost_basis"), errors="coerce").dropna().sum()
unrealized_pnl = pd.to_numeric(enriched.get("unrealized_pnl"), errors="coerce").dropna().sum()
day_gain = pd.to_numeric(enriched.get("day_gain"), errors="coerce").dropna().sum()
realized_pnl = get_total_realized_pnl()
holdings_count = len(enriched)

# Cash positions
cash_positions = get_all_cash_positions()
from core.currency_normalizer import total_cash_in_base_currency
total_cash = total_cash_in_base_currency(cash_positions, base_currency)
net_portfolio = total_value + total_cash

unrealized_pct = (unrealized_pnl / total_cost * 100) if total_cost > 0 else 0
day_pct = (day_gain / (total_value - day_gain) * 100) if (total_value - day_gain) > 0 else 0

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: MARKET CONTEXT BAR
# ══════════════════════════════════════════════════════════════════════════════

# FORTRESS Regime detection
regime_name = "Unknown"
regime_color = "#888"
_regime_key = None  # The raw regime constant (e.g. REGIME_EXPANSION)
try:
    from core.fortress import (
        detect_regime, REGIME_NAMES, REGIME_COLORS, REGIME_DISPLAY,
        REGIME_EXPANSION, REGIME_OVERHEATING, REGIME_CONTRACTION, REGIME_RECOVERY,
    )
    from core.database import get_fortress_state
    # Use ALL saved fortress inputs — must match Risk & Strategy exactly
    vix_val = float(get_fortress_state("vix") or 18)
    pmi_val = float(get_fortress_state("pmi") or 52)
    _cs = float(get_fortress_state("credit_spread") or 110)
    _yc = float(get_fortress_state("yield_curve") or 0.3)
    _inf = float(get_fortress_state("inflation") or 2.8)
    _fed = get_fortress_state("fed_trajectory") or "On hold"
    regime_result = detect_regime(
        vix=vix_val, pmi=pmi_val, credit_spread=_cs,
        yield_curve=_yc, inflation_yoy=_inf, fed_trajectory=_fed,
    )
    _regime_key = regime_result["regime"]
    regime_color = REGIME_COLORS.get(_regime_key, "#888")
except Exception:
    pass

# Plain-English regime labels — use shared REGIME_DISPLAY from fortress.py
_rd = REGIME_DISPLAY.get(_regime_key, {}) if _regime_key is not None else {}
regime_name = _rd.get("label", "Unknown")
regime_color = _rd.get("color", "#888")
_regime_icon = _rd.get("icon", "")
_regime_explanation = _rd.get("explanation", "")
_regime_action = _rd.get("action", "")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1+2: HERO — the portfolio first, the market context second
# ══════════════════════════════════════════════════════════════════════════════
# Measured before this change on a 375x812 phone: the first portfolio number
# sat 526px down the page — 65% of the opening screen went to a title, a
# freshness caption, a market-context bar and a four-chip cycle scale, none of
# which is the reason anyone opens this page. Order is now value first,
# context second, and the KPI rows use ui_components.stat_grid rather than
# st.columns(), which stacks below ~640px with no opt-out and turned each
# three-KPI row into three separate ~70px rows.
from core.ui_components import mobile_shell, fmt_compact
import core.ledger_ui as _ui
mobile_shell()

# Phase 3: the label moves BELOW the figure. A kicker above a heading is the
# single most recognisable generated-UI tell, and here it also pushed the one
# number the page exists for further down the opening screen.
_ui.write(_ui.hero(
    fmt_compact(net_portfolio, base_currency),
    delta=f"{day_gain:+,.0f} ({day_pct:+.2f}%) today",
    delta_value=day_gain,
    sub=f"Net portfolio value · {holdings_count} holdings · {base_currency}",
    title=f"{base_currency} {net_portfolio:,.2f}",
))

# Two 3-cell carded grids become one ruled block. stat_row drops cells with no
# value before laying out, so "Realized —" and "Div / yr —" stop occupying a
# slot each instead of rendering as holes.
_div_cache_key = f"cmd_div_income_{base_currency}"
div_income_est = st.session_state.get(_div_cache_key, 0)
_ui.write(_ui.stat_row([
    ("Today", fmt_compact(day_gain, base_currency), f"{day_pct:+.2f}%", day_gain),
    ("Unrealized", fmt_compact(unrealized_pnl, base_currency), f"{unrealized_pct:+.1f}%", unrealized_pnl),
    ("Realized", fmt_compact(realized_pnl, base_currency) if realized_pnl else "", "", realized_pnl),
    ("Cash", fmt_compact(total_cash, base_currency) if total_cash else ""),
    ("Currencies", str(len(enriched["currency"].unique()) if "currency" in enriched.columns else 1)),
    ("Div / yr", fmt_compact(div_income_est, base_currency) if div_income_est > 0 else ""),
], columns=3))

# Market regime — one line, with the guidance behind a tap rather than a
# permanently-open 173px block of chips. The regime still reads at a glance;
# what changed is that it no longer outranks the portfolio for screen space.
from core.ui_components import status_chip as _chip
_regime_level = {"Growing": "good", "Bouncing Back": "good",
                 "Heating Up": "warn", "Slowing Down": "critical"}.get(regime_name, "neutral")
st.markdown(
    "<div style='display:flex;align-items:center;gap:8px;margin:0.1rem 0 0.5rem;"
    "font-size:0.8rem'>"
    "<span style='opacity:0.55;text-transform:uppercase;letter-spacing:0.05em;"
    f"font-size:0.68rem;font-weight:600'>Market cycle</span>{_chip(regime_name, _regime_level)}"
    "</div>",
    unsafe_allow_html=True,
)
if _regime_explanation:
    with st.expander(f"What “{regime_name}” means for you", expanded=False):
        st.markdown(f"{_regime_icon} **{regime_name}** — {_regime_explanation}")
        st.markdown(f"**What to do:** {_regime_action}")

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
        # Drop exactly-zero rows: a missing day change is filled as 0, not null,
        # so without this the top-3 / bottom-3 fill with "+0.0%" lines in ticker
        # order and the widget looks like it has data when it has none.
        movers_df = movers_df[movers_df["day_change_pct"] != 0]

        if not movers_df.empty:
            gainers = movers_df.nlargest(3, "day_change_pct")
            losers = movers_df.nsmallest(3, "day_change_pct")

            # Phase 3: tinted cards with a 3px coloured border-left become
            # ruled rows. Two substantive changes, not just styling:
            #   * the MONEY is now the same size and weight as the percent,
            #     right-aligned with it. It was 0.85em in #666 — about 2.8:1
            #     on this ground, which is below the AA floor and is why it
            #     read as faint grey noise beside the number that matters.
            #   * the position's market value leads the row, so a +11% on a
            #     small line no longer looks like a +11% on a large one.
            _rows = []
            for _, row in pd.concat([gainers, losers]).iterrows():
                pct = float(row["day_change_pct"])
                amt = row.get("day_gain")
                amt = float(amt) if pd.notna(amt) else None
                _rows.append(_ui.ledger_row(
                    str(row["ticker"]),
                    str(row.get("name") or "")[:38],
                    fmt_compact(row.get("market_value"), base_currency),
                    change=_ui.money(amt, pct, base_currency) if amt is not None
                           else f'<span class="{"up" if pct > 0 else "down"}">{pct:+.1f}%</span>',
                    change_value=amt if amt is not None else pct,
                ))
            st.markdown("".join(_rows), unsafe_allow_html=True)
        else:
            st.caption("No price data available yet.")
    else:
        st.caption("Visit Portfolio Dashboard to load live prices.")

# ── Performance Attribution ──
with col_attrib:
    st.markdown("#### P&L Attribution")

    if "day_gain" in enriched.columns:
        _acols = [c for c in ("ticker", "name", "day_gain", "market_value")
                  if c in enriched.columns]
        attrib_df = enriched[_acols].copy()
        attrib_df["day_gain"] = pd.to_numeric(attrib_df["day_gain"], errors="coerce").fillna(0)
        attrib_df["market_value"] = pd.to_numeric(attrib_df["market_value"], errors="coerce").fillna(0)
        attrib_df = attrib_df[attrib_df["day_gain"] != 0].sort_values("day_gain")

        if not attrib_df.empty:
            # Calculate % contribution to total day P&L
            total_day_pnl = attrib_df["day_gain"].sum()
            attrib_df["pct_contrib"] = (attrib_df["day_gain"] / attrib_df["market_value"] * 100).round(2)

            top_contrib = attrib_df.tail(5)
            bot_contrib = attrib_df.head(5)
            show_df = pd.concat([bot_contrib, top_contrib]).drop_duplicates()
            show_df = show_df.sort_values("day_gain")

            # Phase 3: this was a horizontal Plotly bar chart with
            # textposition="outside" and a 5px left margin, so every NEGATIVE
            # bar wrote its label off the canvas — "0 (-5.2%)" and "+2," were
            # clipped at both ends on a real phone. A ranked list carries the
            # same three facts (who, how much money, what percent of that
            # position) with no clipping, no axis to read, and no chart
            # bundle on a 512MiB instance.
            show_df = show_df.sort_values("day_gain", ascending=False)
            _attr = []
            for _, r in show_df.iterrows():
                _amt = float(r["day_gain"])
                _attr.append(_ui.ledger_row(
                    str(r["ticker"]),
                    str(r.get("name") or "")[:34],
                    _ui.money(_amt, None, base_currency),
                    change=f'<span class="{"up" if _amt > 0 else "down"}">'
                           f'{float(r["pct_contrib"]):+.1f}% of position</span>',
                    change_value=_amt,
                ))
            st.markdown("".join(_attr), unsafe_allow_html=True)
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
                    alerts.append(("critical", "🎯", f"**{ticker}** is {w:.0%} of portfolio"))

            if "sector" in enriched.columns:
                sector_weights = enriched.copy()
                sector_weights["mv"] = mv
                sector_agg = sector_weights.groupby("sector")["mv"].sum() / total
                for sec, sw in sector_agg.items():
                    if sw > 0.35 and sec not in ("", "Unknown", None):
                        alerts.append(("warn", "🎯", f"**{sec}** sector {sw:.0%}"))

    # Big daily drops
    if "day_change_pct" in enriched.columns:
        big_drops = enriched[pd.to_numeric(enriched["day_change_pct"], errors="coerce") < -3]
        for _, row in big_drops.iterrows():
            pct = float(row["day_change_pct"])
            alerts.append(("warn", "📉", f"**{row['ticker']}** down {pct:.1f}%"))

    # Earnings within 5 days — use cached earnings data if available (avoid slow batch fetch)
    _earnings_cache = st.session_state.get("cmd_earnings_alerts", [])
    for tk, days in _earnings_cache:
        tag = "TODAY" if days == 0 else f"in {days}d"
        alerts.append(("neutral", "📅", f"**{tk}** earnings {tag}"))

    # AI analysis coverage
    try:
        analyses = get_all_prosper_analyses()
        if not analyses.empty:
            cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            recent = analyses[analyses["analysis_date"] >= cutoff]
            coverage = len(recent) / holdings_count * 100 if holdings_count > 0 else 0
            if coverage < 50:
                alerts.append(("neutral", "🤖", f"Only {coverage:.0f}% analysed (7d)"))
    except Exception:
        pass

    # FORTRESS regime warnings
    try:
        from core.fortress import check_circuit_breakers
        if regime_name == "Slowing Down":
            alerts.append(("warn", "🏰", "**Slowing Down** regime active — reduce risk"))
        elif regime_name == "Heating Up":
            alerts.append(("warn", "🏰", "**Heating Up** — tighten stops, trim winners"))

        if total_cost > 0:
            dd_pct = min(0, (total_value - total_cost) / total_cost * 100)
            if dd_pct <= -5:
                cb = check_circuit_breakers(dd_pct)
                level = cb["portfolio_level"]["level"]
                if level != "NONE":
                    alerts.append(("critical", "🚨", f"Breaker **{level}**: {dd_pct:.1f}%"))
    except Exception:
        pass

    if alerts:
        # Phase 3: the same alerts, rendered as ruled rows instead of eight
        # tinted pills of one visual class. Severity now reads from a dot and
        # the row's own words; the emoji, the status chip and the
        # rgba(255,255,255,0.03) fill (which only works on a dark ground) are
        # gone. Alert text and ordering are unchanged.
        #
        # Sorted so critical outranks warn outranks neutral — previously the
        # first eight in generation order won, which is concentration-then-
        # drops-then-earnings, not severity.
        import re as _re
        from core.ledger_ui import attention as _attention

        _rank = {"critical": 0, "warn": 1, "neutral": 2}
        _lvl = {"critical": "critical", "warn": "warn", "neutral": "info"}
        _ordered = sorted(alerts, key=lambda a: _rank.get(a[0], 3))

        _items = []
        for level, _icon, text in _ordered:
            # Alert text is authored with Markdown emphasis ("**ADBE** down
            # 6.7%") and goes into raw HTML, where Streamlit does not run the
            # Markdown parser. attention() escapes its inputs, so strip the
            # emphasis markers rather than converting them to tags.
            _items.append({
                "level": _lvl.get(level, "info"),
                "title": _re.sub(r"\*\*(.+?)\*\*", r"\1", text),
                "why": "",
                "source": "",
            })
        st.markdown(_attention(_items, limit=4), unsafe_allow_html=True)
    else:
        # The healthy state, designed. This is the modal condition — most days
        # nothing has breached anything — so it should read as a finished
        # answer, not as an absence of content.
        st.markdown(_ui.empty(
            "Nothing needs you today",
            "No holding is outside its concentration limit, no position moved "
            "more than 3%, and the market cycle has not changed. The next thing "
            "that could need attention is an earnings date.",
        ), unsafe_allow_html=True)

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
                    color_continuous_scale=_ui.DIVERGING,
                    color_continuous_midpoint=0,
                )
                fig.update_layout(
                    margin=dict(t=5, l=5, r=5, b=5),
                    height=350,
                    coloraxis_colorbar=dict(title="Day %", len=0.5),
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                fig.update_traces(textfont=dict(size=13), textposition="middle center")
                show_chart(fig, key="cmd_heatmap")
            except Exception:
                # Fallback: simple bar chart if treemap fails
                hm_df = hm_df.sort_values("market_value", ascending=True).tail(15)
                colors = ["#047857" if v >= 0 else "#b91c1c" for v in hm_df["day_change_pct"]]
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
                show_chart(fig, key="cmd_heatmap_fallback")

with col_alloc:
    st.markdown("#### Allocation by Sector")

    if "market_value" in enriched.columns and "sector" in enriched.columns:
        alloc_df = enriched[["sector", "market_value"]].copy()
        alloc_df["market_value"] = pd.to_numeric(alloc_df["market_value"], errors="coerce").fillna(0)
        alloc_df = alloc_df.groupby("sector")["market_value"].sum().reset_index()
        alloc_df = alloc_df[alloc_df["market_value"] > 0].sort_values("market_value", ascending=True)
        total_alloc = alloc_df["market_value"].sum()
        alloc_df["pct"] = (alloc_df["market_value"] / total_alloc * 100).round(1)

        if not alloc_df.empty:
            # Phase 3: ranked bars instead of a Plotly bar chart. Same three
            # facts per row, a third of the height, no chart bundle, and the
            # ordering is guaranteed by the component rather than by whichever
            # sort the caller happened to apply. Chart guidance is explicit
            # that category must never be encoded by colour alone — every bar
            # carries its own name, percent and money.
            _top = alloc_df.sort_values("market_value", ascending=False)
            _lead = _top.iloc[0]
            st.markdown(_ui.read(
                f'Largest exposure is <b>{_lead["sector"]}</b> at '
                f'{_lead["pct"]:.1f}% of the book. Top three are '
                f'{_top.head(3)["pct"].sum():.1f}%.'
            ), unsafe_allow_html=True)
            st.markdown(_ui.ranked_bars([
                {"name": str(r["sector"]) or "Unclassified",
                 "pct": float(r["pct"]),
                 "meta": f'{base_currency} {r["market_value"]:,.0f}',
                 "state": "over" if float(r["pct"]) > 25 else ""}
                for _, r in _top.iterrows()
            ], limit=12), unsafe_allow_html=True)
    elif "market_value" in enriched.columns:
        # Simple top-10 bar chart if no sector data
        top10 = enriched.nlargest(10, "market_value")[["ticker", "market_value"]]
        fig_t10 = px.bar(top10, x="ticker", y="market_value", color="market_value",
                         color_continuous_scale="Blues")
        fig_t10.update_layout(height=350, margin=dict(t=5, l=5, r=5, b=5),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              showlegend=False)
        show_chart(fig_t10, key="cmd_top10")

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
        _briefing_df = enriched.copy()
        _briefing_df["_mv_sort"] = pd.to_numeric(_briefing_df.get("market_value"), errors="coerce")
        portfolio_summary = []
        for _, row in _briefing_df.nlargest(25, "_mv_sort").iterrows():
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

Be sharp, specific, actionable. No generic advice. This investor has {holdings_count} positions worth {base_currency} {net_portfolio:,.0f}.

IMPORTANT: Only ever name a ticker or company that appears in TOP HOLDINGS above. Never mention any other
stock, ETF, or company — even as a sector comparison or "similar names to watch" — if it is not one of this
investor's actual holdings listed above."""

        from core.settings import extract_text, CLAUDE_DEFAULT_MODEL
        response = call_claude(
            client,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            preferred_model=CLAUDE_DEFAULT_MODEL,
        )
        text = extract_text(response)
        if not text:
            # One bounded retry — an empty completion with no exception raised
            # is rare but has been reported; a fresh call usually succeeds.
            response = call_claude(
                client,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                preferred_model=CLAUDE_DEFAULT_MODEL,
            )
            text = extract_text(response)
        return text or "Briefing came back empty after a retry — please try again in a moment."

    except Exception as e:
        return safe_message("the briefing", e)


# ── Briefing presentation ────────────────────────────────────────────────────
# The model returns four bold-headed sections — Portfolio Pulse, Key Moves,
# Risk Watch, Action Items — and the page rendered all four as one block of
# editorial. Good content, wrong packaging for a phone: the answer ("am I
# fine?") and the ask ("what do I do?") were separated by two paragraphs of
# explanation.
#
# This shows the pulse and the actions, and puts the explanation one tap away.
# It PARSES rather than re-prompts, so briefings already saved in the database
# render the new way without regenerating — and if the model ever returns a
# shape this cannot read, the whole text falls through unchanged.
def _split_briefing(text: str) -> dict:
    import re as _re
    if not text:
        return {}
    parts, current = {}, None
    for line in text.splitlines():
        m = _re.match(r"\s*\*\*(.+?):?\*\*\s*(.*)$", line)
        if m:
            current = m.group(1).strip().lower()
            parts[current] = [m.group(2).strip()] if m.group(2).strip() else []
        elif current is not None:
            parts[current].append(line)
    return {k: "\n".join(v).strip() for k, v in parts.items() if "\n".join(v).strip()}


def _render_briefing(text: str, meta: str = "") -> None:
    """Pulse and actions up front, explanation behind a tap."""
    _p = _split_briefing(text)
    _pulse = _p.get("portfolio pulse")
    _actions = _p.get("action items")
    _rest = [(k.title(), v) for k, v in _p.items()
             if k not in ("portfolio pulse", "action items")]

    if not _pulse and not _actions:
        st.markdown(text)                      # unrecognised shape — show it all
        if meta:
            st.caption(meta)
        return

    if _pulse:
        st.markdown(_ui.read(f"<b>What changed.</b> {_pulse}"), unsafe_allow_html=True)
    if _actions:
        st.markdown(_ui.section("What to do"), unsafe_allow_html=True)
        st.markdown(_actions)
    if _rest:
        with st.expander("Why it matters — key moves and risk watch", expanded=False):
            for _title, _body in _rest:
                st.markdown(f"**{_title}**")
                st.markdown(_body)
    if meta:
        st.caption(meta)


# Auto-show: check session → DB → offer generate button
_today_str = datetime.now().strftime("%Y-%m-%d")
_briefing_shown = False

if briefing_cache_key in st.session_state:
    # Show today's session-cached briefing
    _render_briefing(st.session_state[briefing_cache_key],
                     f"Generated today · {_today_str}")
    _briefing_shown = True
elif get_latest_briefing:
    # Try to load from database (persists across sessions)
    _saved = get_latest_briefing(base_currency)
    if _saved and _saved.get("content"):
        st.session_state[briefing_cache_key] = _saved["content"]
        _bdate = _saved.get("date", "")
        _btimestamp = _saved.get("created_at", "")
        _meta = (f"Generated today · {_btimestamp}" if _bdate == _today_str
                 else f"From {_bdate} · {_btimestamp} — Refresh to update for today")
        _render_briefing(_saved["content"], _meta)
        _briefing_shown = True

if _briefing_shown:
    col_refresh, _ = st.columns([1, 5])
    with col_refresh:
        if st.button("🔄 Refresh Briefing", key="refresh_brief"):
            with st.spinner("Generating..."):
                _new_briefing = generate_briefing()
                st.session_state[briefing_cache_key] = _new_briefing
                if save_briefing:
                    save_briefing(_today_str, base_currency, _new_briefing)
                st.rerun()
else:
    # No briefing found anywhere — show generate button
    api_key = get_api_key("ANTHROPIC_API_KEY")
    if api_key and api_key != "your_anthropic_api_key_here":
        if st.button("Generate Today's AI Briefing", type="primary", key="gen_briefing"):
            with st.spinner("Your AI CIO is preparing today's briefing..."):
                _new_briefing = generate_briefing()
                st.session_state[briefing_cache_key] = _new_briefing
                if save_briefing:
                    save_briefing(_today_str, base_currency, _new_briefing)
                st.rerun()
        st.caption("Click to generate your personalized CIO briefing for today.")
    else:
        st.caption("Configure your Anthropic API key in Settings to enable AI briefings.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: PORTFOLIO VALUE HISTORY
# ══════════════════════════════════════════════════════════════════════════════
# Quick Navigation (8 st.page_links duplicating the sidebar and the bottom
# bar) was deleted in Phase 3: a dashboard should carry contextual actions,
# not a second sitemap. The NAV history chart now uses the full width.
nav_history = get_nav_history(base_currency)
if not nav_history.empty and len(nav_history) > 1:
    st.markdown("#### Portfolio Value History")
    nav_history["date"] = pd.to_datetime(nav_history["date"])
    fig_nav = go.Figure()
    fig_nav.add_trace(go.Scatter(
        x=nav_history["date"],
        y=nav_history["total_value"],
        mode="lines",
        line=dict(color="#1E3A8A", width=2.5),
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
    show_chart(fig_nav, key="cmd_nav_hist")
else:
    st.caption("NAV snapshots accumulate daily when you visit the Dashboard. Check back soon.")

