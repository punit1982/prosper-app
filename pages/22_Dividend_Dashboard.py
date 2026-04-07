"""
Dividend Dashboard — Income Tracking & Projections
====================================================
Portfolio dividend income, ex-dates, yield analysis, and income projections.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from core.database import get_all_holdings
from core.settings import SETTINGS, enriched_cache_key
from core.cio_engine import enrich_portfolio
from core.data_engine import get_ticker_info_batch, fmt_large

st.markdown(
    "<h2 style='margin-bottom:0'>💰 Dividend Dashboard</h2>"
    "<p style='color:#888;margin-top:0'>Income tracking, yield analysis & dividend projections</p>",
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
    with st.spinner("Loading portfolio…"):
        enriched = enrich_portfolio(holdings, base_currency)
        st.session_state[cache_key] = enriched

if enriched.empty:
    st.warning("Portfolio data not ready. Visit the Portfolio Dashboard first.")
    st.stop()

# Use resolved tickers for better yfinance coverage (e.g. EMAAR.AE vs EMAAR)
_t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
tickers = enriched[_t_col].tolist()
# Keep mapping from resolved → original ticker for display
_ticker_display = dict(zip(enriched[_t_col], enriched["ticker"]))

# ── Fetch Dividend Data ──
@st.cache_data(ttl=3600, show_spinner="Fetching dividend data…", max_entries=5)
def _get_dividend_info(tickers_tuple):
    import logging
    logger = logging.getLogger(__name__)
    info_map = get_ticker_info_batch(list(tickers_tuple))
    rows = []
    payers_count = 0

    for ticker in tickers_tuple:
        info = info_map.get(ticker, {})

        # Try multiple dividend data sources
        div_rate = info.get("dividendRate")
        div_yield = info.get("dividendYield")

        # Fallback: check trailingAnnualDividendRate if dividendRate missing
        if not div_rate:
            div_rate = info.get("trailingAnnualDividendRate")
        if not div_yield:
            div_yield = info.get("trailingAnnualDividendYield")

        ex_date = info.get("exDividendDate")
        payout_ratio = info.get("payoutRatio")
        five_yr_avg = info.get("fiveYearAvgDividendYield")

        # Track payers
        if div_rate or div_yield:
            payers_count += 1

        # Convert ex-date timestamp
        ex_date_str = None
        if ex_date:
            try:
                ex_date_str = datetime.fromtimestamp(ex_date).strftime("%Y-%m-%d")
            except (ValueError, OSError, TypeError):
                pass

        rows.append({
            "ticker": ticker,
            "name": info.get("shortName", ""),
            "dividend_rate": div_rate,
            "dividend_yield": div_yield,
            "ex_date": ex_date_str,
            "payout_ratio": payout_ratio,
            "five_yr_avg_yield": five_yr_avg,
            "sector": info.get("sector", ""),
            "quote_type": info.get("quoteType", "EQUITY"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
        })
    return pd.DataFrame(rows)

div_df = _get_dividend_info(tuple(tickers))

# ── Merge with portfolio data ──
if "quantity" in enriched.columns:
    qty_map = dict(zip(enriched[_t_col], pd.to_numeric(enriched["quantity"], errors="coerce")))
    div_df["quantity"] = div_df["ticker"].map(qty_map).fillna(0)
else:
    div_df["quantity"] = 0

if "market_value" in enriched.columns:
    mv_map = dict(zip(enriched[_t_col], pd.to_numeric(enriched["market_value"], errors="coerce")))
    div_df["market_value"] = div_df["ticker"].map(mv_map).fillna(0)
    total_mv = div_df["market_value"].sum()
else:
    div_df["market_value"] = 0
    total_mv = 0

if "avg_cost" in enriched.columns:
    cost_map = dict(zip(enriched[_t_col], pd.to_numeric(enriched["avg_cost"], errors="coerce")))
    div_df["avg_cost"] = div_df["ticker"].map(cost_map).fillna(0)

# ── Calculate annual income ──
div_df["annual_income"] = div_df.apply(
    lambda r: r["quantity"] * r["dividend_rate"] if pd.notna(r["dividend_rate"]) and r["quantity"] > 0 else 0,
    axis=1,
)

# Yield on cost
div_df["yield_on_cost"] = div_df.apply(
    lambda r: (r["dividend_rate"] / r["avg_cost"] * 100)
    if pd.notna(r.get("dividend_rate")) and r.get("avg_cost", 0) > 0 else None,
    axis=1,
)

# Payers vs non-payers
payers = div_df[div_df["dividend_rate"].notna() & (div_df["dividend_rate"] > 0)]
non_payers = div_df[~div_df.index.isin(payers.index)]

total_annual_income = payers["annual_income"].sum()
portfolio_yield = (total_annual_income / total_mv * 100) if total_mv > 0 else 0

# ── Hero Metrics ──
m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.metric("Annual Dividend Income",
              f"{base_currency} {total_annual_income:,.0f}" if total_annual_income > 0 else "—")
with m2:
    st.metric("Portfolio Yield", f"{portfolio_yield:.2f}%" if portfolio_yield > 0 else "—")
with m3:
    st.metric("Monthly Income",
              f"{base_currency} {total_annual_income/12:,.0f}" if total_annual_income > 0 else "—")
with m4:
    st.metric("Dividend Payers", f"{len(payers)}/{len(div_df)}")
with m5:
    payer_weight = payers["market_value"].sum() / total_mv * 100 if total_mv > 0 else 0
    st.metric("Payer Weight", f"{payer_weight:.1f}%")

st.divider()

# ── Tabs ──
tab_income, tab_yield, tab_calendar, tab_growth = st.tabs([
    "💵 Income Breakdown", "📊 Yield Analysis", "📅 Ex-Date Calendar", "📈 Growth Potential",
])

# ── TAB 1: Income Breakdown ──
with tab_income:
    if not payers.empty:
        income_df = payers[["ticker", "name", "quantity", "dividend_rate", "annual_income",
                            "dividend_yield", "yield_on_cost", "sector"]].copy()
        income_df = income_df.sort_values("annual_income", ascending=False)

        display = income_df.copy()
        display["Div/Share"] = display["dividend_rate"].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "—")
        display["Annual Income"] = display["annual_income"].apply(lambda x: f"${x:,.0f}" if x > 0 else "—")
        display["Yield"] = display["dividend_yield"].apply(lambda x: f"{x*100:.2f}%" if pd.notna(x) else "—")
        display["Yield on Cost"] = display["yield_on_cost"].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "—")
        display["Monthly"] = income_df["annual_income"].apply(lambda x: f"${x/12:,.0f}" if x > 0 else "—")

        st.dataframe(
            display[["ticker", "name", "Div/Share", "Annual Income", "Monthly", "Yield", "Yield on Cost", "sector"]].rename(
                columns={"ticker": "Ticker", "name": "Company", "sector": "Sector"}
            ),
            use_container_width=True, hide_index=True,
        )

        # Income by sector pie
        sector_income = income_df.groupby("sector")["annual_income"].sum().reset_index()
        sector_income = sector_income[sector_income["annual_income"] > 0]
        if not sector_income.empty:
            fig = px.pie(sector_income, values="annual_income", names="sector",
                         title="Dividend Income by Sector", hole=0.4)
            fig.update_layout(height=300, margin=dict(t=40, l=10, r=10, b=10),
                              paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)

        # Top contributors bar chart
        top10 = income_df.head(10)
        fig_bar = px.bar(top10, x="ticker", y="annual_income",
                         title="Top 10 Dividend Contributors",
                         color="annual_income", color_continuous_scale="Greens")
        fig_bar.update_layout(height=300, margin=dict(t=40, l=40, r=20, b=20),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              xaxis_title="", yaxis_title=f"Annual Income ({base_currency})")
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("None of your holdings currently pay dividends.")

# ── TAB 2: Yield Analysis ──
with tab_yield:
    if not payers.empty:
        st.markdown("### Yield Comparison")
        yield_df = payers[["ticker", "name", "dividend_yield", "yield_on_cost",
                           "five_yr_avg_yield", "payout_ratio"]].copy()
        yield_df = yield_df.sort_values("dividend_yield", ascending=False)

        display_y = yield_df.copy()
        display_y["Current Yield"] = display_y["dividend_yield"].apply(
            lambda x: f"{x*100:.2f}%" if pd.notna(x) else "—")
        display_y["Yield on Cost"] = display_y["yield_on_cost"].apply(
            lambda x: f"{x:.2f}%" if pd.notna(x) else "—")
        display_y["5Y Avg Yield"] = display_y["five_yr_avg_yield"].apply(
            lambda x: f"{x:.2f}%" if pd.notna(x) else "—")
        display_y["Payout Ratio"] = display_y["payout_ratio"].apply(
            lambda x: f"{x*100:.0f}%" if pd.notna(x) else "—")

        st.dataframe(
            display_y[["ticker", "name", "Current Yield", "Yield on Cost", "5Y Avg Yield", "Payout Ratio"]].rename(
                columns={"ticker": "Ticker", "name": "Company"}
            ),
            use_container_width=True, hide_index=True,
        )

        # Yield scatter: current yield vs payout ratio
        scatter_df = payers[payers["payout_ratio"].notna() & payers["dividend_yield"].notna()].copy()
        if not scatter_df.empty:
            scatter_df["yield_pct"] = scatter_df["dividend_yield"] * 100
            scatter_df["payout_pct"] = scatter_df["payout_ratio"] * 100
            fig_scatter = px.scatter(
                scatter_df, x="payout_pct", y="yield_pct", text="ticker",
                title="Yield vs Payout Ratio (lower payout = more sustainable)",
                labels={"payout_pct": "Payout Ratio %", "yield_pct": "Dividend Yield %"},
                size="annual_income", size_max=30,
            )
            fig_scatter.update_traces(textposition="top center")
            fig_scatter.add_vline(x=75, line_dash="dash", line_color="red", opacity=0.5,
                                  annotation_text="75% payout (caution)")
            fig_scatter.update_layout(height=400, margin=dict(t=40, l=40, r=20, b=40),
                                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_scatter, use_container_width=True)

        # Sustainability flags
        high_payout = payers[payers["payout_ratio"].notna() & (payers["payout_ratio"] > 0.90)]
        if not high_payout.empty:
            st.warning(
                "⚠️ **High payout ratio (>90%):** " +
                ", ".join(f"{r['ticker']} ({r['payout_ratio']*100:.0f}%)" for _, r in high_payout.iterrows()) +
                " — Dividend may not be sustainable."
            )
    else:
        st.info("No dividend-paying holdings found.")

# ── TAB 3: Ex-Date Calendar ──
with tab_calendar:
    ex_dates = div_df[div_df["ex_date"].notna()].copy()
    if not ex_dates.empty:
        ex_dates["ex_dt"] = pd.to_datetime(ex_dates["ex_date"])
        ex_dates = ex_dates.sort_values("ex_dt")
        today = datetime.now().date()
        ex_dates["days_until"] = ex_dates["ex_dt"].apply(lambda x: (x.date() - today).days)

        upcoming = ex_dates[ex_dates["days_until"] >= -7].head(20)
        if not upcoming.empty:
            st.markdown("### Upcoming Ex-Dividend Dates")
            for _, row in upcoming.iterrows():
                days = row["days_until"]
                if days < 0:
                    icon = "⬛"
                    tag = "Past"
                elif days <= 3:
                    icon = "🔴"
                    tag = "Imminent"
                elif days <= 14:
                    icon = "🟡"
                    tag = "Soon"
                else:
                    icon = "🟢"
                    tag = ""

                income_per = row["quantity"] * row["dividend_rate"] / 4 if pd.notna(row["dividend_rate"]) else 0
                st.markdown(
                    f"{icon} **{row['ticker']}** — {row['ex_dt'].strftime('%b %d, %Y')} "
                    f"({days} days) "
                    f"{'· Est income: $' + f'{income_per:,.0f}' if income_per > 0 else ''} "
                    f"{'· ' + tag if tag else ''}"
                )
        else:
            st.info("No upcoming ex-dividend dates found.")
    else:
        st.info("No ex-dividend date data available for your holdings.")

# ── TAB 4: Growth Potential ──
with tab_growth:
    st.markdown("### 📈 Income Growth Projection")
    st.caption("Estimates future dividend income assuming consistent dividend growth rates.")

    growth_rate = st.slider("Assumed Annual Dividend Growth Rate", 0, 15, 5, 1,
                            help="Historical S&P 500 dividend growth: ~5-7% annually")

    if total_annual_income > 0:
        years = list(range(0, 11))
        projected = [total_annual_income * (1 + growth_rate / 100) ** y for y in years]

        proj_df = pd.DataFrame({"Year": [f"Year {y}" for y in years], "Income": projected})
        fig_proj = px.bar(proj_df, x="Year", y="Income",
                          title=f"Projected Annual Dividend Income ({growth_rate}% growth)",
                          color="Income", color_continuous_scale="Greens")
        fig_proj.update_layout(height=350, margin=dict(t=40, l=40, r=20, b=20),
                               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                               yaxis_title=f"Annual Income ({base_currency})")
        st.plotly_chart(fig_proj, use_container_width=True)

        # Summary
        st.markdown(
            f"- **Today:** {base_currency} {total_annual_income:,.0f}/year ({total_annual_income/12:,.0f}/month)\n"
            f"- **5 years:** {base_currency} {projected[5]:,.0f}/year ({projected[5]/12:,.0f}/month)\n"
            f"- **10 years:** {base_currency} {projected[10]:,.0f}/year ({projected[10]/12:,.0f}/month)"
        )
    else:
        st.info("No current dividend income to project. Add dividend-paying stocks to see projections.")
