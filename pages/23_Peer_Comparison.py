"""
Peer Comparison — Side-by-Side Fundamental Analysis
=====================================================
Auto-detect sector peers for any portfolio holding and compare key metrics.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from core.database import get_all_holdings
from core.settings import SETTINGS, enriched_cache_key
from core.cio_engine import enrich_portfolio
from core.data_engine import get_ticker_info_batch, fmt_large

st.markdown(
    "<h2 style='margin-bottom:0'>🔍 Peer Comparison</h2>"
    "<p style='color:#888;margin-top:0'>Side-by-side fundamental analysis against sector peers</p>",
    unsafe_allow_html=True,
)

# ── Load Portfolio ──
base_currency = SETTINGS.get("base_currency", "USD")
holdings = get_all_holdings()

if holdings.empty:
    st.info("No holdings found. Upload your portfolio first.")
    st.stop()

cache_key = enriched_cache_key(base_currency)
if cache_key in st.session_state and st.session_state[cache_key] is not None:
    enriched = st.session_state[cache_key]
else:
    with st.spinner("Loading portfolio..."):
        enriched = enrich_portfolio(holdings, base_currency)
        st.session_state[cache_key] = enriched

if enriched.empty:
    st.warning("Portfolio data not ready. Visit the Portfolio Dashboard first.")
    st.stop()

# Use resolved tickers for better yfinance data coverage
_t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
tickers = enriched[_t_col].tolist()

# ── Fetch info for all portfolio tickers ──
@st.cache_data(ttl=3600, show_spinner="Fetching company data...")
def _get_info_cached(tickers_tuple):
    return get_ticker_info_batch(list(tickers_tuple))

info_map = _get_info_cached(tuple(tickers))

# ── Build selector with sector info ──
ticker_labels = {}
sector_map = {}
for t in tickers:
    info = info_map.get(t, {})
    name = info.get("shortName", t)
    sector = info.get("sector", "Unknown")
    sector_map[t] = sector
    ticker_labels[t] = f"{t} — {name} ({sector})"

# ── Peer detection ──
# Industry-level peers from the same sector, plus manual well-known peers
_SECTOR_PEERS = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSM", "AVGO", "ORCL", "CRM", "ADBE", "INTC", "AMD"],
    "Financial Services": ["JPM", "BAC", "GS", "MS", "WFC", "C", "BLK", "SCHW", "AXP", "V", "MA"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT", "DHR", "BMY", "AMGN"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "NKE", "MCD", "SBUX", "TJX", "LOW", "BKNG", "CMG"],
    "Communication Services": ["GOOGL", "META", "DIS", "NFLX", "CMCSA", "T", "VZ", "TMUS", "CHTR"],
    "Industrials": ["HON", "UPS", "CAT", "BA", "GE", "MMM", "LMT", "RTX", "DE", "UNP"],
    "Consumer Defensive": ["PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL", "MDLZ", "KHC"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "DVN"],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "WEC", "ED"],
    "Real Estate": ["PLD", "AMT", "CCI", "EQIX", "SPG", "O", "PSA", "DLR", "WELL", "AVB"],
    "Basic Materials": ["LIN", "APD", "SHW", "ECL", "DD", "FCX", "NEM", "NUE", "DOW", "PPG"],
}

def _get_peers(ticker, info, n=8):
    """Get peer tickers for comparison."""
    industry = (info.get("industry") or "").lower()
    sector = info.get("sector", "Unknown")
    market_cap = info.get("marketCap") or 0

    # Priority 1: Same-industry tickers from portfolio
    same_industry = []
    same_sector = []
    for t in tickers:
        if t == ticker:
            continue
        peer_info = info_map.get(t, {})
        peer_industry = (peer_info.get("industry") or "").lower()
        peer_sector = peer_info.get("sector", "Unknown")
        if peer_industry and peer_industry == industry:
            same_industry.append(t)
        elif peer_sector == sector:
            same_sector.append(t)

    peers = same_industry + same_sector

    # Priority 2: Well-known sector peers (try multiple sector name variants)
    sector_keys = [sector]
    # Also try common yfinance sector names that may differ
    _SECTOR_ALIASES = {
        "Financials": "Financial Services",
        "Financial Services": "Financials",
        "Consumer Discretionary": "Consumer Cyclical",
        "Consumer Cyclical": "Consumer Discretionary",
        "Consumer Staples": "Consumer Defensive",
        "Consumer Defensive": "Consumer Staples",
        "Materials": "Basic Materials",
        "Basic Materials": "Materials",
    }
    if sector in _SECTOR_ALIASES:
        sector_keys.append(_SECTOR_ALIASES[sector])

    for sk in sector_keys:
        sector_defaults = _SECTOR_PEERS.get(sk, [])
        for p in sector_defaults:
            if p != ticker and p not in peers and p not in tickers:
                peers.append(p)

    return peers[:n]


# ── UI: Ticker Selection ──
col_sel1, col_sel2 = st.columns([1, 2])
with col_sel1:
    # Default to first preferred ticker that's in portfolio, else first portfolio ticker
    default_idx = 0
    preferred = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "ADBE", "META", "TSLA"]
    for i, pref in enumerate(preferred):
        if pref in tickers:
            default_idx = tickers.index(pref)
            break

    selected_ticker = st.selectbox(
        "Select a holding to compare",
        tickers,
        index=default_idx,
        format_func=lambda t: ticker_labels.get(t, t),
    )

selected_info = info_map.get(selected_ticker, {})
default_peers = _get_peers(selected_ticker, selected_info)

with col_sel2:
    # Let user customize peers
    custom_peers_input = st.text_input(
        "Peer tickers (comma-separated, or leave blank for auto-detected)",
        value=", ".join(default_peers[:6]),
        help="Enter ticker symbols separated by commas. Auto-detected peers are pre-filled.",
    )

if custom_peers_input.strip():
    peer_tickers = [t.strip().upper() for t in custom_peers_input.split(",") if t.strip()]
else:
    peer_tickers = default_peers[:6]

if not peer_tickers:
    st.info("No peers found. Enter peer tickers manually above.")
    st.stop()

# ── Fetch peer data ──
all_compare = [selected_ticker] + [p for p in peer_tickers if p != selected_ticker]

@st.cache_data(ttl=3600, show_spinner="Fetching peer data...")
def _get_peer_info(tickers_tuple):
    return get_ticker_info_batch(list(tickers_tuple))

compare_info = _get_peer_info(tuple(all_compare))

# ── Build comparison table ──
def _safe_get(info, key, default=None):
    v = info.get(key)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return default
    return v

rows = []
for t in all_compare:
    info = compare_info.get(t, {})
    is_holding = t == selected_ticker

    market_cap = _safe_get(info, "marketCap")
    pe_trailing = _safe_get(info, "trailingPE")
    pe_forward = _safe_get(info, "forwardPE")
    pb = _safe_get(info, "priceToBook")
    ps = _safe_get(info, "priceToSalesTrailing12Months")
    ev_ebitda = _safe_get(info, "enterpriseToEbitda")
    div_yield = _safe_get(info, "dividendYield")
    roe = _safe_get(info, "returnOnEquity")
    roa = _safe_get(info, "returnOnAssets")
    profit_margin = _safe_get(info, "profitMargins")
    revenue_growth = _safe_get(info, "revenueGrowth")
    earnings_growth = _safe_get(info, "earningsGrowth")
    debt_equity = _safe_get(info, "debtToEquity")
    current_ratio = _safe_get(info, "currentRatio")
    beta = _safe_get(info, "beta")
    price = _safe_get(info, "currentPrice") or _safe_get(info, "regularMarketPrice")
    w52_high = _safe_get(info, "fiftyTwoWeekHigh")
    w52_low = _safe_get(info, "fiftyTwoWeekLow")

    pct_from_high = ((price / w52_high - 1) * 100) if price and w52_high else None

    rows.append({
        "Ticker": t,
        "Company": info.get("shortName", t),
        "is_holding": is_holding,
        "Sector": info.get("sector", "—"),
        "Industry": info.get("industry", "—"),
        "Market Cap": market_cap,
        "Price": price,
        "P/E (TTM)": pe_trailing,
        "P/E (Fwd)": pe_forward,
        "P/B": pb,
        "P/S": ps,
        "EV/EBITDA": ev_ebitda,
        "Div Yield": div_yield,
        "ROE": roe,
        "ROA": roa,
        "Profit Margin": profit_margin,
        "Revenue Growth": revenue_growth,
        "Earnings Growth": earnings_growth,
        "D/E": debt_equity,
        "Current Ratio": current_ratio,
        "Beta": beta,
        "52W High": w52_high,
        "52W Low": w52_low,
        "% from 52W High": pct_from_high,
    })

comp_df = pd.DataFrame(rows)

# ── Hero: Selected Stock Summary ──
sel_row = comp_df[comp_df["is_holding"]].iloc[0] if not comp_df[comp_df["is_holding"]].empty else None
if sel_row is not None:
    st.markdown(f"### {sel_row['Ticker']} — {sel_row['Company']}")
    st.caption(f"{sel_row['Sector']} / {sel_row['Industry']}")

    hero_cols = st.columns(6)
    with hero_cols[0]:
        st.metric("Price", f"${sel_row['Price']:,.2f}" if sel_row['Price'] else "—")
    with hero_cols[1]:
        st.metric("Market Cap", fmt_large(sel_row['Market Cap']) if sel_row['Market Cap'] else "—")
    with hero_cols[2]:
        st.metric("P/E (Fwd)", f"{sel_row['P/E (Fwd)']:.1f}" if sel_row['P/E (Fwd)'] else "—")
    with hero_cols[3]:
        st.metric("ROE", f"{sel_row['ROE']*100:.1f}%" if sel_row['ROE'] else "—")
    with hero_cols[4]:
        st.metric("Div Yield", f"{sel_row['Div Yield']*100:.2f}%" if sel_row['Div Yield'] else "—")
    with hero_cols[5]:
        st.metric("Beta", f"{sel_row['Beta']:.2f}" if sel_row['Beta'] else "—")

st.divider()

# ── Tabs ──
tab_table, tab_valuation, tab_quality, tab_growth, tab_risk = st.tabs([
    "📋 Full Comparison", "💰 Valuation", "✅ Quality", "📈 Growth", "⚠️ Risk",
])

# ── TAB 1: Full Table ──
with tab_table:
    display_df = comp_df.copy()

    # Format columns
    def _fmt_pct(v):
        return f"{v*100:.1f}%" if pd.notna(v) and v is not None else "—"

    def _fmt_num(v, decimals=1):
        return f"{v:.{decimals}f}" if pd.notna(v) and v is not None else "—"

    def _fmt_cap(v):
        return fmt_large(v) if pd.notna(v) and v is not None else "—"

    fmt_df = pd.DataFrame({
        "Ticker": display_df["Ticker"],
        "Company": display_df["Company"],
        "Mkt Cap": display_df["Market Cap"].apply(_fmt_cap),
        "Price": display_df["Price"].apply(lambda x: f"${x:,.2f}" if pd.notna(x) and x else "—"),
        "P/E (TTM)": display_df["P/E (TTM)"].apply(lambda x: _fmt_num(x)),
        "P/E (Fwd)": display_df["P/E (Fwd)"].apply(lambda x: _fmt_num(x)),
        "P/B": display_df["P/B"].apply(lambda x: _fmt_num(x)),
        "EV/EBITDA": display_df["EV/EBITDA"].apply(lambda x: _fmt_num(x)),
        "Div Yield": display_df["Div Yield"].apply(_fmt_pct),
        "ROE": display_df["ROE"].apply(_fmt_pct),
        "Profit Mgn": display_df["Profit Margin"].apply(_fmt_pct),
        "Rev Growth": display_df["Revenue Growth"].apply(_fmt_pct),
        "D/E": display_df["D/E"].apply(lambda x: _fmt_num(x, 0)),
        "Beta": display_df["Beta"].apply(lambda x: _fmt_num(x, 2)),
        "% from High": display_df["% from 52W High"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) and x is not None else "—"),
    })

    st.dataframe(fmt_df, use_container_width=True, hide_index=True)

# ── TAB 2: Valuation ──
with tab_valuation:
    val_metrics = ["P/E (TTM)", "P/E (Fwd)", "P/B", "P/S", "EV/EBITDA"]
    val_data = comp_df[["Ticker"] + val_metrics].copy()

    # Bar charts for each valuation metric
    for metric in val_metrics:
        subset = val_data[val_data[metric].notna()].copy()
        if subset.empty:
            continue
        colors = ["#FF9800" if t == selected_ticker else "#1E88E5" for t in subset["Ticker"]]
        fig = px.bar(
            subset, x="Ticker", y=metric, title=metric,
            color_discrete_sequence=["#1E88E5"],
        )
        fig.update_traces(marker_color=colors)
        fig.update_layout(
            height=280, margin=dict(t=35, l=40, r=10, b=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
        )
        # Add peer median line
        peer_vals = subset[subset["Ticker"] != selected_ticker][metric].dropna()
        if not peer_vals.empty:
            median_val = peer_vals.median()
            fig.add_hline(y=median_val, line_dash="dash", line_color="rgba(255,255,255,0.5)",
                          annotation_text=f"Peer Median: {median_val:.1f}")
        st.plotly_chart(fig, use_container_width=True)

    # Valuation summary
    st.markdown("#### Valuation Verdict")
    sel_pe = comp_df[comp_df["Ticker"] == selected_ticker]["P/E (Fwd)"].values
    peer_pe = comp_df[comp_df["Ticker"] != selected_ticker]["P/E (Fwd)"].dropna()
    if len(sel_pe) > 0 and pd.notna(sel_pe[0]) and not peer_pe.empty:
        sel_val = sel_pe[0]
        med_val = peer_pe.median()
        if sel_val < med_val * 0.8:
            st.success(f"**{selected_ticker}** trades at a **discount** to peers (Fwd P/E {sel_val:.1f} vs peer median {med_val:.1f})")
        elif sel_val > med_val * 1.2:
            st.warning(f"**{selected_ticker}** trades at a **premium** to peers (Fwd P/E {sel_val:.1f} vs peer median {med_val:.1f})")
        else:
            st.info(f"**{selected_ticker}** is **in-line** with peers (Fwd P/E {sel_val:.1f} vs peer median {med_val:.1f})")

# ── TAB 3: Quality ──
with tab_quality:
    quality_metrics = {
        "ROE": ("Return on Equity", True),
        "ROA": ("Return on Assets", True),
        "Profit Margin": ("Profit Margin", True),
        "Current Ratio": ("Current Ratio", True),
    }

    quality_data = comp_df[["Ticker"] + list(quality_metrics.keys())].copy()

    # Radar chart for quality comparison
    sel_data = quality_data[quality_data["Ticker"] == selected_ticker].iloc[0] if not quality_data.empty else None
    if sel_data is not None:
        peer_medians = {}
        for m in quality_metrics:
            peer_vals = quality_data[quality_data["Ticker"] != selected_ticker][m].dropna()
            peer_medians[m] = peer_vals.median() if not peer_vals.empty else 0

        # Normalize to 0-100 scale for radar
        categories = list(quality_metrics.keys())
        cat_labels = [quality_metrics[c][0] for c in categories]

        sel_values = []
        peer_values = []
        for c in categories:
            sv = sel_data[c] if pd.notna(sel_data[c]) else 0
            pv = peer_medians.get(c, 0) or 0
            max_val = max(abs(sv), abs(pv), 0.01)
            sel_values.append(sv / max_val * 100 if max_val else 0)
            peer_values.append(pv / max_val * 100 if max_val else 0)

        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=sel_values + [sel_values[0]],
            theta=cat_labels + [cat_labels[0]],
            fill="toself",
            name=selected_ticker,
            line_color="#FF9800",
        ))
        fig_radar.add_trace(go.Scatterpolar(
            r=peer_values + [peer_values[0]],
            theta=cat_labels + [cat_labels[0]],
            fill="toself",
            name="Peer Median",
            line_color="#1E88E5",
            opacity=0.5,
        ))
        fig_radar.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 120])),
            height=400, margin=dict(t=30, l=60, r=60, b=30),
            paper_bgcolor="rgba(0,0,0,0)",
            title="Quality Comparison (Normalized)",
        )
        st.plotly_chart(fig_radar, use_container_width=True)

    # Quality metrics bar charts
    for metric, (label, higher_better) in quality_metrics.items():
        subset = quality_data[quality_data[metric].notna()].copy()
        if subset.empty:
            continue
        subset[f"{metric}_pct"] = subset[metric] * 100 if metric != "Current Ratio" else subset[metric]
        colors = ["#FF9800" if t == selected_ticker else "#1E88E5" for t in subset["Ticker"]]
        fig = px.bar(subset, x="Ticker", y=f"{metric}_pct", title=label)
        fig.update_traces(marker_color=colors)
        fig.update_layout(
            height=260, margin=dict(t=35, l=40, r=10, b=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False, yaxis_title="%" if metric != "Current Ratio" else "Ratio",
        )
        st.plotly_chart(fig, use_container_width=True)

# ── TAB 4: Growth ──
with tab_growth:
    growth_metrics = {
        "Revenue Growth": "Revenue Growth (YoY)",
        "Earnings Growth": "Earnings Growth (YoY)",
    }

    growth_data = comp_df[["Ticker"] + list(growth_metrics.keys())].copy()

    for metric, label in growth_metrics.items():
        subset = growth_data[growth_data[metric].notna()].copy()
        if subset.empty:
            continue
        subset[f"{metric}_pct"] = subset[metric] * 100
        colors = ["#FF9800" if t == selected_ticker else "#4CAF50" for t in subset["Ticker"]]
        fig = px.bar(subset, x="Ticker", y=f"{metric}_pct", title=label)
        fig.update_traces(marker_color=colors)
        fig.add_hline(y=0, line_color="rgba(255,255,255,0.3)")
        fig.update_layout(
            height=300, margin=dict(t=35, l=40, r=10, b=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False, yaxis_title="%",
        )
        st.plotly_chart(fig, use_container_width=True)

    # PEG-like comparison: forward PE vs earnings growth
    peg_data = comp_df[comp_df["P/E (Fwd)"].notna() & comp_df["Earnings Growth"].notna()].copy()
    if not peg_data.empty:
        peg_data["eg_pct"] = peg_data["Earnings Growth"] * 100
        colors = ["#FF9800" if t == selected_ticker else "#1E88E5" for t in peg_data["Ticker"]]

        fig_peg = px.scatter(
            peg_data, x="eg_pct", y="P/E (Fwd)", text="Ticker",
            title="Growth vs Valuation (lower-right = better value)",
            labels={"eg_pct": "Earnings Growth %", "P/E (Fwd)": "Forward P/E"},
        )
        fig_peg.update_traces(marker=dict(size=14, color=colors), textposition="top center")
        fig_peg.update_layout(
            height=400, margin=dict(t=40, l=50, r=20, b=40),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_peg, use_container_width=True)

# ── TAB 5: Risk ──
with tab_risk:
    risk_metrics = {
        "Beta": "Beta (Market Sensitivity)",
        "D/E": "Debt-to-Equity Ratio",
        "% from 52W High": "Distance from 52-Week High",
    }

    for metric, label in risk_metrics.items():
        subset = comp_df[comp_df[metric].notna()].copy()
        if subset.empty:
            continue
        colors = ["#FF9800" if t == selected_ticker else "#1E88E5" for t in subset["Ticker"]]
        fig = px.bar(subset, x="Ticker", y=metric, title=label)
        fig.update_traces(marker_color=colors)

        # Reference lines
        if metric == "Beta":
            fig.add_hline(y=1.0, line_dash="dash", line_color="rgba(255,255,255,0.5)",
                          annotation_text="Market Beta = 1.0")
        elif metric == "D/E":
            fig.add_hline(y=100, line_dash="dash", line_color="rgba(255,100,100,0.5)",
                          annotation_text="D/E = 100 (caution)")

        fig.update_layout(
            height=300, margin=dict(t=35, l=40, r=10, b=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    # Risk summary
    st.markdown("#### Risk Profile Summary")
    sel_beta = comp_df[comp_df["Ticker"] == selected_ticker]["Beta"].values
    sel_de = comp_df[comp_df["Ticker"] == selected_ticker]["D/E"].values

    summary_points = []
    if len(sel_beta) > 0 and pd.notna(sel_beta[0]):
        b = sel_beta[0]
        if b > 1.3:
            summary_points.append(f"**High beta ({b:.2f})** — more volatile than the market")
        elif b < 0.7:
            summary_points.append(f"**Low beta ({b:.2f})** — defensive, less volatile")
        else:
            summary_points.append(f"**Moderate beta ({b:.2f})** — moves roughly with the market")

    if len(sel_de) > 0 and pd.notna(sel_de[0]):
        d = sel_de[0]
        if d > 200:
            summary_points.append(f"**High leverage (D/E: {d:.0f})** — elevated financial risk")
        elif d < 50:
            summary_points.append(f"**Low leverage (D/E: {d:.0f})** — conservative balance sheet")
        else:
            summary_points.append(f"**Moderate leverage (D/E: {d:.0f})**")

    if summary_points:
        for sp in summary_points:
            st.markdown(f"- {sp}")
    else:
        st.info("Insufficient risk data available for this ticker.")
