"""
Performance
===========
Portfolio performance vs benchmark indices.
Default benchmarks: S&P 500, Nasdaq 100, Nifty 50, Sensex.

Optimized: parallel history fetching + skips tickers with no live price.
"""

import streamlit as st
from core.ui_components import show_chart
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.database import get_all_holdings, get_nav_history
from core.data_engine import get_benchmark_history, BENCHMARKS, calc_cagr
from core.settings import SETTINGS, save_user_settings

from core.ui_components import page_header
import core.ledger_ui as _lu
page_header('Performance', 'How the portfolio has actually done')
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

# ── Period → start date ────────────────────────────────────────────────────
_PERIOD_DAYS = {"5d": 7, "1mo": 31, "3mo": 93, "6mo": 186,
                "1y": 366, "2y": 731, "3y": 1096, "5y": 1826}
_today = datetime.now().date()
if period == "ytd":
    _period_start = pd.Timestamp(datetime(_today.year, 1, 1))
else:
    _period_start = pd.Timestamp(_today - timedelta(days=_PERIOD_DAYS.get(period, 366)))


try:
    # ── Portfolio return, from the daily NAV snapshots ──────────────────────
    # This page used to rebuild the portfolio curve from a full history fetch
    # for every one of ~180 holdings (4 workers, 6s each) — the "Performance
    # never loads" freeze. nav_snapshots is written every time the Dashboard
    # is opened and already holds exactly this series, so the only network
    # work left here is the handful of selected benchmarks.
    nav_all = get_nav_history(days=3660, base_currency=base_currency)
    if not nav_all.empty:
        nav_all = nav_all.copy()
        nav_all["date"] = pd.to_datetime(nav_all["date"])
        nav_all = nav_all.sort_values("date").drop_duplicates("date", keep="last")
        nav_win = nav_all[nav_all["date"] >= _period_start]
    else:
        nav_win = nav_all

    bench_histories = {}

    if nav_win.empty or len(nav_win) < 2:
        portfolio_return = pd.Series(dtype=float)
        st.info(
            "Not enough portfolio history for this period yet. Your total value is saved "
            "as a daily snapshot every time you open the **Dashboard** — the comparison "
            "chart fills in as those build up. The value chart below shows whatever has "
            "been recorded so far."
        )
    else:
        _pv = nav_win.set_index("date")["total_value"].astype(float)
        portfolio_return = (_pv / _pv.iloc[0]) * 100
        _win_start = nav_win["date"].iloc[0]

        # Benchmarks over the same window — a handful of fetches, not ~180
        def _fetch_bench(name):
            from core.yf_utils import extract_close_series
            h = get_benchmark_history(name, period)
            if h.empty:
                return name, None
            close = extract_close_series(h, name)
            if close.empty:
                return name, None
            close.index = pd.to_datetime(close.index)
            close = close[close.index >= _win_start]
            return name, close if len(close) >= 2 else None

        if selected_benchmarks:
            with st.spinner(f"Loading {len(selected_benchmarks)} benchmark(s)…"):
                with ThreadPoolExecutor(max_workers=max(1, len(selected_benchmarks))) as pool:
                    futures = {pool.submit(_fetch_bench, n): n for n in selected_benchmarks}
                    for f in as_completed(futures):
                        name, series = f.result()
                        if series is not None:
                            bench_histories[name] = series

    # ── Plotly chart ──
    if not portfolio_return.empty or bench_histories:
        fig = go.Figure()
        if not portfolio_return.empty:
            fig.add_trace(go.Scatter(
                x=portfolio_return.index, y=portfolio_return.values,
                name="📈 Your Portfolio", line=dict(color="#1E3A8A", width=3),
            ))
        colors = _lu.CHART_SEQUENCE  # one qualitative sequence, shared app-wide
        for i, (name, series) in enumerate(bench_histories.items()):
            norm = (series / series.iloc[0]) * 100
            fig.add_trace(go.Scatter(
                x=norm.index, y=norm.values, name=name,
                line=dict(color=colors[i % len(colors)], width=2, dash="dash"),
            ))
        fig.update_layout(
            title=f"Portfolio vs Benchmarks — {PERIOD_LABELS.get(period, period)} (Indexed to 100)",
            yaxis_title="Indexed Value", xaxis_title="Date",
            hovermode="x unified",
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
            height=500, margin=dict(t=50, b=30),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        fig.add_hline(y=100, line_dash="dot", line_color="gray", annotation_text="Start = 100")
        show_chart(fig)

    # ── Summary table ──
    if not portfolio_return.empty or bench_histories:
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

        if not portfolio_return.empty:
            st.caption(
                f"ℹ️ Portfolio line from {len(nav_win)} daily NAV snapshots since "
                f"{nav_win['date'].iloc[0].strftime('%Y-%m-%d')}. Benchmarks clipped to the same window."
            )

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
            name="Portfolio Value", line=dict(color="#1E3A8A", width=2.5),
            fill="tozeroy", fillcolor="rgba(41, 98, 255, 0.1)",
        ))

        # Add cost basis line if available
        if "total_cost" in nav_data.columns and nav_data["total_cost"].notna().any():
            nav_fig.add_trace(go.Scatter(
                x=nav_data["date"], y=nav_data["total_cost"],
                name="Cost Basis", line=dict(color="#B45309", width=2, dash="dash"),
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
        show_chart(nav_fig)

        st.caption(f"ℹ️ {len(nav_data)} snapshots recorded since {nav_data['date'].iloc[0].strftime('%Y-%m-%d')}.")


except Exception as _err:
    import traceback
    st.error("⚠️ An error occurred on this page. Please try refreshing.")
    with st.expander("🔍 Error details (for debugging)"):
        st.code(traceback.format_exc())
    if st.button("🔄 Retry", key="page_retry"):
        st.rerun()
