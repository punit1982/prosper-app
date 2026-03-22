"""
Performance
===========
Portfolio performance vs benchmark indices.
Default benchmarks: S&P 500, Nasdaq 100, Nifty 50, Sensex.

Optimized: parallel history fetching + skips tickers with no live price.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.database import get_all_holdings, get_nav_history
from core.data_engine import get_history, get_benchmark_history, BENCHMARKS, calc_max_drawdown, calc_cagr
from core.cio_engine import enrich_portfolio
from core.settings import SETTINGS, save_user_settings

st.header("📈 Performance")

holdings = get_all_holdings()
if holdings.empty:
    st.info("Add holdings via **Upload Portal** to see performance analysis.")
    st.stop()

base_currency = SETTINGS.get("base_currency", "USD")

with st.sidebar:
    PERIODS = ["5d", "1mo", "3mo", "6mo", "1y", "2y", "3y", "5y", "ytd"]
    PERIOD_LABELS = {
        "5d": "1 Week", "1mo": "1 Month", "3mo": "3 Months",
        "6mo": "6 Months", "1y": "1 Year", "2y": "2 Years",
        "3y": "3 Years", "5y": "5 Years", "ytd": "Year to Date",
    }
    PERIOD_YEARS = {"1y": 1, "2y": 2, "3y": 3, "5y": 5}

    # Load persisted preference
    saved_period = SETTINGS.get("pref_perf_period", "1y")
    period_idx = PERIODS.index(saved_period) if saved_period in PERIODS else 4
    period = st.selectbox("Time Period", PERIODS, index=period_idx,
                          format_func=lambda p: PERIOD_LABELS.get(p, p))

    saved_benchmarks = SETTINGS.get("pref_perf_benchmarks", ["S&P 500", "Nasdaq 100", "Nifty 50", "Sensex"])
    selected_benchmarks = st.multiselect(
        "Benchmark Indices",
        list(BENCHMARKS.keys()),
        default=saved_benchmarks,
    )

    # Persist changes
    if period != SETTINGS.get("pref_perf_period", "1y"):
        save_user_settings({"pref_perf_period": period})
        SETTINGS["pref_perf_period"] = period
    if selected_benchmarks != SETTINGS.get("pref_perf_benchmarks", ["S&P 500", "Nasdaq 100", "Nifty 50", "Sensex"]):
        save_user_settings({"pref_perf_benchmarks": selected_benchmarks})
        SETTINGS["pref_perf_benchmarks"] = selected_benchmarks

# ── Get enriched holdings (use cached if available) ──
cache_key = f"enriched_{base_currency}"
if cache_key not in st.session_state:
    with st.spinner("Fetching portfolio data…"):
        st.session_state[cache_key] = enrich_portfolio(holdings, base_currency)

from core.data_engine import apply_global_filter, calc_cagr
enriched = apply_global_filter(st.session_state[cache_key]).copy()
t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"

# OPTIMIZATION: only fetch history for tickers that have a live price
has_price = pd.to_numeric(enriched.get("current_price", pd.Series(dtype=float)), errors="coerce").notna()
live_tickers = enriched.loc[has_price, t_col].dropna().tolist()

if not live_tickers:
    st.warning("No tickers with live price data. Cannot build performance chart.")
    st.stop()


try:
    # Calculate weights
    if "market_value" in enriched.columns and enriched["market_value"].notna().any():
        total = enriched.loc[has_price, "market_value"].sum()
        weights = {}
        for _, row in enriched.loc[has_price].iterrows():
            t = row[t_col]
            weights[t] = row["market_value"] / total if total > 0 else 1.0 / len(live_tickers)
    else:
        weights = {t: 1.0 / len(live_tickers) for t in live_tickers}

    # ── Parallel history fetch ──
    with st.spinner(f"Loading {period} data for {len(live_tickers)} tickers + {len(selected_benchmarks)} benchmarks…"):
        port_histories = {}

        def _fetch_hist(ticker):
            h = get_history(ticker, period)
            if not h.empty and "Close" in h.columns:
                close = h["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                return ticker, close
            return ticker, None

        with ThreadPoolExecutor(max_workers=min(len(live_tickers), 15)) as pool:
            futures = {pool.submit(_fetch_hist, t): t for t in live_tickers}
            for f in as_completed(futures):
                t, series = f.result()
                if series is not None:
                    port_histories[t] = series

        bench_histories = {}
        def _fetch_bench(name):
            h = get_benchmark_history(name, period)
            if not h.empty and "Close" in h.columns:
                close = h["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                return name, close
            return name, None

        if selected_benchmarks:
            with ThreadPoolExecutor(max_workers=len(selected_benchmarks)) as pool:
                futures = {pool.submit(_fetch_bench, n): n for n in selected_benchmarks}
                for f in as_completed(futures):
                    name, series = f.result()
                    if series is not None:
                        bench_histories[name] = series

    # ── Portfolio return (indexed to 100) ──
    if port_histories:
        normalized = {}
        for t, series in port_histories.items():
            if len(series) > 0:
                normalized[t] = (series / series.iloc[0]) * 100
        if normalized:
            port_df = pd.DataFrame(normalized)
            # Forward-fill then back-fill to handle different start dates & missing days
            port_df = port_df.ffill().bfill()
            w_series = pd.Series({t: weights.get(t, 0) for t in port_df.columns})
            w_series = w_series / w_series.sum()
            portfolio_return = (port_df * w_series).sum(axis=1)
        else:
            portfolio_return = pd.Series(dtype=float)
    else:
        portfolio_return = pd.Series(dtype=float)

    # ── Plotly chart ──
    fig = go.Figure()

    if not portfolio_return.empty:
        fig.add_trace(go.Scatter(
            x=portfolio_return.index, y=portfolio_return.values,
            name="📈 Your Portfolio", line=dict(color="#2962FF", width=3),
        ))

    colors = ["#FF6D00", "#00C853", "#AA00FF", "#DD2C00", "#00BFA5", "#6200EA", "#FFD600", "#304FFE"]
    for i, (name, series) in enumerate(bench_histories.items()):
        norm = (series / series.iloc[0]) * 100
        fig.add_trace(go.Scatter(
            x=norm.index, y=norm.values, name=name,
            line=dict(color=colors[i % len(colors)], width=2, dash="dash"),
        ))

    fig.update_layout(
        title=f"Portfolio vs Benchmarks — {period} (Indexed to 100)",
        yaxis_title="Indexed Value", xaxis_title="Date",
        hovermode="x unified",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        height=500, margin=dict(t=50, b=30),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.add_hline(y=100, line_dash="dot", line_color="gray", annotation_text="Start = 100")
    st.plotly_chart(fig, use_container_width=True)

    # ── Summary table ──
    st.subheader("Return Summary")
    rows = []
    years = PERIOD_YEARS.get(period)
    if not portfolio_return.empty:
        port_ret = (portfolio_return.iloc[-1] / portfolio_return.iloc[0] - 1) * 100
        row = {"Name": "📈 Your Portfolio", "Return": f"{port_ret:+.2f}%",
               "Start": f"{portfolio_return.iloc[0]:.1f}", "End": f"{portfolio_return.iloc[-1]:.1f}"}
        if years:
            cagr = calc_cagr(portfolio_return.iloc[0], portfolio_return.iloc[-1], years)
            row["CAGR"] = f"{cagr*100:+.2f}%" if cagr is not None else ""
        rows.append(row)
    for name, series in bench_histories.items():
        if len(series) >= 2:
            ret = (series.iloc[-1] / series.iloc[0] - 1) * 100
            row = {"Name": name, "Return": f"{ret:+.2f}%",
                   "Start": f"{series.iloc[0]:,.1f}", "End": f"{series.iloc[-1]:,.1f}"}
            if years:
                cagr = calc_cagr(series.iloc[0], series.iloc[-1], years)
                row["CAGR"] = f"{cagr*100:+.2f}%" if cagr is not None else ""
            rows.append(row)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.caption(f"ℹ️ Based on {len(port_histories)} of {len(live_tickers)} tickers with available history.")

    # ── NAV History — Portfolio Value Over Time ──────────────────────────────
    st.divider()
    st.subheader("📈 Portfolio Value Over Time")
    st.caption("Daily snapshots of your total portfolio value. Saved automatically each time you load the Dashboard.")

    nav_data = get_nav_history(days=730, base_currency=base_currency)

    if nav_data.empty or len(nav_data) < 2:
        st.info(
            "Not enough NAV snapshots yet. Portfolio value is saved daily when you visit the **Dashboard**. "
            "Come back after a few days to see your portfolio value chart."
        )
    else:
        nav_data["date"] = pd.to_datetime(nav_data["date"])
        nav_data = nav_data.sort_values("date")

        # Summary metrics
        latest_val = nav_data["total_value"].iloc[-1]
        first_val = nav_data["total_value"].iloc[0]
        ath = nav_data["total_value"].max()
        drawdown_from_ath = ((latest_val - ath) / ath * 100) if ath > 0 else 0

        # Time-weighted return
        total_return_pct = ((latest_val / first_val) - 1) * 100 if first_val > 0 else 0
        # Sanity: cap display at ±10,000%
        if abs(total_return_pct) > 10000:
            total_return_pct = None

        # CAGR
        days_diff = (nav_data["date"].iloc[-1] - nav_data["date"].iloc[0]).days
        years_diff = days_diff / 365.25 if days_diff > 0 else None
        nav_cagr = calc_cagr(first_val, latest_val, years_diff) if years_diff and years_diff > 0 else None

        nc1, nc2, nc3, nc4 = st.columns(4)
        nc1.metric("Current Value", f"{base_currency} {latest_val:,.0f}")
        nc2.metric("All-Time High", f"{base_currency} {ath:,.0f}")
        nc3.metric("Drawdown from ATH", f"{drawdown_from_ath:+.1f}%")
        nc4.metric(
            "Total Return",
            f"{total_return_pct:+.1f}%" if total_return_pct is not None else "—",
            delta=f"CAGR: {nav_cagr*100:+.1f}%" if nav_cagr is not None else ""
        )

        # NAV chart
        nav_fig = go.Figure()
        nav_fig.add_trace(go.Scatter(
            x=nav_data["date"], y=nav_data["total_value"],
            name="Portfolio Value", line=dict(color="#2962FF", width=2.5),
            fill="tozeroy", fillcolor="rgba(41, 98, 255, 0.1)",
        ))

        # Add cost basis line if available
        if "total_cost" in nav_data.columns and nav_data["total_cost"].notna().any():
            nav_fig.add_trace(go.Scatter(
                x=nav_data["date"], y=nav_data["total_cost"],
                name="Cost Basis", line=dict(color="#FF6D00", width=2, dash="dash"),
            ))

        nav_fig.update_layout(
            title="Portfolio NAV History",
            yaxis_title=f"Value ({base_currency})",
            xaxis_title="Date",
            hovermode="x unified",
            height=420, margin=dict(t=50, b=30),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        )
        st.plotly_chart(nav_fig, use_container_width=True)

        st.caption(f"ℹ️ {len(nav_data)} snapshots recorded since {nav_data['date'].iloc[0].strftime('%Y-%m-%d')}.")


except Exception as _err:
    import traceback
    st.error("⚠️ An error occurred on this page. Please try refreshing.")
    with st.expander("🔍 Error details (for debugging)"):
        st.code(traceback.format_exc())
    if st.button("🔄 Retry", key="page_retry"):
        st.rerun()
