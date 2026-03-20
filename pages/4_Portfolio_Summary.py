"""
Portfolio Summary
=================
Diversification analysis with interactive charts.
• By Sector / Industry
• By Currency
• By Country
• By Market Cap
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from core.database import get_all_holdings, get_nav_history
from core.cio_engine import enrich_portfolio
from core.data_engine import (
    get_ticker_info_batch, get_history, calc_cagr,
    calc_max_drawdown, calc_sharpe_ratio, calc_sortino_ratio,
    calc_portfolio_beta, calc_portfolio_volatility,
)
from core.settings import SETTINGS

st.header("📊 Portfolio Summary")

holdings = get_all_holdings()
if holdings.empty:
    st.info("Add holdings via **Upload Portal** to see your portfolio summary.")
    st.stop()


try:
    base_currency = SETTINGS.get("base_currency", "USD")

    # ── Get enriched + info data ──
    cache_key = f"enriched_{base_currency}"
    if cache_key not in st.session_state:
        with st.spinner("Fetching live prices…"):
            enriched = enrich_portfolio(holdings, base_currency)
            st.session_state[cache_key] = enriched

    from core.data_engine import apply_global_filter
    enriched = apply_global_filter(st.session_state[cache_key]).copy()
    t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"

    # Fetch ticker info for sector/industry/country — use resolved tickers for yfinance
    _resolved_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else t_col
    info_key = "summary_info_map"

    # If extended_df is already loaded from Dashboard, extract sector/industry from it
    ext_df = st.session_state.get("extended_df")
    if ext_df is not None and "sector" in ext_df.columns:
        ext_t = "ticker_resolved" if "ticker_resolved" in ext_df.columns else "ticker"
        _ext_sector   = dict(zip(ext_df[ext_t], ext_df.get("sector", "")))
        _ext_industry = dict(zip(ext_df[ext_t], ext_df.get("industry", "")))
        _ext_country  = dict(zip(ext_df[ext_t], ext_df.get("country", "")))
        _ext_mcap     = dict(zip(ext_df[ext_t], ext_df.get("market_cap", 0)))
        _ext_qt       = dict(zip(ext_df[ext_t], ext_df.get("quote_type", "EQUITY")))

        info_map = {}
        for t in enriched[_resolved_col].dropna().tolist():
            info_map[t] = {
                "sector": _ext_sector.get(t, ""),
                "industry": _ext_industry.get(t, ""),
                "country": _ext_country.get(t, ""),
                "marketCap": _ext_mcap.get(t, 0),
                "quoteType": _ext_qt.get(t, "EQUITY"),
            }
    else:
        # Fetch fresh from yfinance using resolved tickers
        if info_key not in st.session_state:
            with st.spinner("Loading sector & industry data…"):
                resolved_tickers = enriched[_resolved_col].dropna().tolist()
                st.session_state[info_key] = get_ticker_info_batch(resolved_tickers)
        info_map = st.session_state[info_key]

    # Map original tickers → resolved ticker info (for pages that reference by original name)
    if _resolved_col != t_col:
        _map = dict(zip(enriched[t_col], enriched[_resolved_col]))
        for orig, resolved in _map.items():
            if orig not in info_map and resolved in info_map:
                info_map[orig] = info_map[resolved]

    # Enrich with classification data
    def _resolve_sector(t):
        _inf = info_map.get(t, {})
        qt = str(_inf.get("quoteType", "EQUITY")).upper()
        if qt in ("ETF", "MUTUALFUND"):
            # Try to classify ETF/fund by category or name
            cat = str(_inf.get("category", "")).lower()
            name_raw = str(_inf.get("shortName", "") or _inf.get("longName", "")).lower()
            for label, keywords in [
                ("Technology", ("tech", "semiconductor", "software", "internet", "ai ", "artificial")),
                ("Healthcare", ("health", "biotech", "pharma", "medical")),
                ("Financial Services", ("financ", "bank", "insurance")),
                ("Energy", ("energy", "oil", "gas", "petrol", "clean energy")),
                ("Real Estate", ("real estate", "reit", "property")),
                ("Fixed Income", ("bond", "income", "fixed", "treasury", "credit", "high yield", "debt")),
                ("Industrials", ("industrial", "aerospace", "defense")),
                ("Commodities", ("gold", "silver", "commodity", "metal", "mining")),
            ]:
                if any(k in cat or k in name_raw for k in keywords):
                    return label
            return "Funds & ETFs"
        sector = _inf.get("sector")
        if sector and str(sector) not in ("", "None", "nan"):
            return sector
        # Fallback: try to infer from company name in holdings
        name_val = enriched.loc[enriched[t_col] == t, "name"].values
        name_raw = str(name_val[0]).lower() if len(name_val) > 0 and name_val[0] else ""
        # Also check shortName from info
        short_name = str(_inf.get("shortName", "")).lower()
        n = name_raw or short_name
        if n:
            for label, keywords in [
                ("Financial Services", ("bank", "finance", "capital", "invest", "insurance", "brokerage", "credit")),
                ("Technology", ("tech", "software", "digital", "cyber", "semiconductor", "chip", "computing", "data", "cloud")),
                ("Energy", ("energy", "oil", "gas", "petrol", "solar", "wind", "power gen", "drilling")),
                ("Communication Services", ("telecom", "communication", "media", "broadcast", "entertainment")),
                ("Real Estate", ("real estate", "properties", "reit", "property", "housing")),
                ("Healthcare", ("health", "hospital", "pharma", "biotech", "medical", "therapeut")),
                ("Consumer Cyclical", ("retail", "auto", "luxury", "hotel", "restaurant", "e-commerce", "consumer")),
                ("Consumer Defensive", ("food", "beverage", "grocery", "tobacco", "household")),
                ("Industrials", ("industrial", "aerospace", "defense", "transport", "logistics", "construction", "engineering")),
                ("Utilities", ("utility", "electric", "water", "waste")),
                ("Basic Materials", ("mining", "chemical", "steel", "cement", "material", "metal")),
            ]:
                if any(k in n for k in keywords):
                    return label
        return "Other"

    def _resolve_industry(t):
        _inf = info_map.get(t, {})
        qt = str(_inf.get("quoteType", "EQUITY")).upper()
        if qt in ("ETF", "MUTUALFUND"):
            cat = _inf.get("category", "")
            if cat and str(cat) not in ("", "None", "nan"):
                return cat
            # Fallback: use fund name for classification
            name = str(_inf.get("shortName", "")).lower()
            if "bond" in name or "income" in name or "fixed" in name:
                return "Fixed Income Fund"
            if "equity" in name or "stock" in name or "growth" in name:
                return "Equity Fund"
            return "Fund / ETF"
        industry = _inf.get("industry")
        return industry if industry and str(industry) not in ("", "None", "nan") else _resolve_sector(t)

    _CURRENCY_COUNTRY = {
        "AED": "United Arab Emirates", "USD": "United States", "EUR": "Europe",
        "GBP": "United Kingdom", "INR": "India", "SGD": "Singapore",
        "HKD": "Hong Kong", "AUD": "Australia", "CAD": "Canada",
        "JPY": "Japan", "CHF": "Switzerland", "CNY": "China",
        "SAR": "Saudi Arabia", "ZAR": "South Africa", "KRW": "South Korea",
        "BRL": "Brazil",
    }

    def _resolve_country(t):
        _inf = info_map.get(t, {})
        country = _inf.get("country")
        if country and str(country) not in ("", "None", "nan"):
            return country
        # Fallback: infer from currency
        cur = enriched.loc[enriched[t_col] == t, "currency"].values
        if len(cur) > 0:
            return _CURRENCY_COUNTRY.get(str(cur[0]), "Unknown")
        return "Unknown"

    enriched["sector"]    = enriched[t_col].map(_resolve_sector)
    enriched["industry"]  = enriched[t_col].map(_resolve_industry)
    enriched["country"]   = enriched[t_col].map(_resolve_country)
    enriched["market_cap_raw"] = enriched[t_col].map(lambda t: info_map.get(t, {}).get("marketCap", 0))

    # Market cap size bucket
    def cap_bucket(mc):
        try:
            mc = float(mc)
            if mc >= 200e9:  return "Mega Cap (>200B)"
            elif mc >= 10e9: return "Large Cap (10-200B)"
            elif mc >= 2e9:  return "Mid Cap (2-10B)"
            elif mc >= 300e6: return "Small Cap (300M-2B)"
            else:            return "Micro Cap (<300M)"
        except (TypeError, ValueError):
            return "Unknown"

    enriched["cap_size"] = enriched["market_cap_raw"].apply(cap_bucket)

    # Use market_value as weight (or cost_basis if market_value unavailable)
    weight_col = "market_value"
    if weight_col not in enriched.columns or enriched[weight_col].isna().all():
        weight_col = "cost_basis"

    # ── Summary metrics ──
    total_val = enriched[weight_col].sum() if weight_col in enriched.columns else 0
    st.metric("Total Portfolio Value", f"{base_currency} {total_val:,.0f}" if total_val else "—")

    # ── Charts with drill-down ──
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["By Sector", "By Industry", "By Currency", "By Country", "By Market Cap"])

    def make_pie(df, group_col, value_col, title, tab_key):
        grouped = df.groupby(group_col)[value_col].sum().reset_index()
        grouped.columns = [group_col, "Value"]
        grouped = grouped[grouped["Value"] > 0].sort_values("Value", ascending=False)
        if grouped.empty:
            st.info("No data available for this breakdown.")
            return
        fig = px.pie(grouped, names=group_col, values="Value", title=title,
                     hole=0.4, color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(margin=dict(t=40, b=20, l=20, r=20), height=420,
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        event = st.plotly_chart(fig, use_container_width=True, on_select="rerun",
                                key=f"pie_{tab_key}")

        # Summary table
        grouped["% of Portfolio"] = (grouped["Value"] / grouped["Value"].sum() * 100).round(1)
        grouped["Value"] = grouped["Value"].apply(lambda x: f"{base_currency} {x:,.0f}")
        from core.data_engine import clean_nan
        st.dataframe(clean_nan(grouped), hide_index=True, use_container_width=True)

        # Drill-down: show holdings in selected segment
        selected_segment = None
        if event and event.get("selection", {}).get("points"):
            selected_segment = event["selection"]["points"][0].get("label")

        if selected_segment:
            st.divider()
            st.subheader(f"Holdings in: {selected_segment}")
            segment_df = df[df[group_col] == selected_segment].copy()
            t_col_d = "ticker_resolved" if "ticker_resolved" in segment_df.columns else "ticker"
            drill = pd.DataFrame()
            drill["Ticker"] = segment_df[t_col_d].values
            drill["Name"] = segment_df.get("name", pd.Series(dtype=str)).fillna("").values
            if "current_price" in segment_df.columns:
                drill["Price"] = segment_df["current_price"].apply(
                    lambda v: f"{float(v):,.2f}" if pd.notna(v) and float(v) >= 1 else (f"{float(v):,.4f}" if pd.notna(v) else "")).values
            if value_col in segment_df.columns:
                drill[f"Value ({base_currency})"] = segment_df[value_col].apply(
                    lambda v: f"{float(v):,.0f}" if pd.notna(v) else "").values
            if "unrealized_pnl" in segment_df.columns:
                drill["P&L"] = segment_df["unrealized_pnl"].apply(
                    lambda v: f"{float(v):+,.0f}" if pd.notna(v) else "").values
            if "unrealized_pnl_pct" in segment_df.columns:
                drill["Return %"] = segment_df["unrealized_pnl_pct"].apply(
                    lambda v: f"{float(v):+.1f}%" if pd.notna(v) else "").values
            from core.data_engine import clean_nan
            st.dataframe(clean_nan(drill), hide_index=True, use_container_width=True)

    with tab1:
        if weight_col in enriched.columns:
            make_pie(enriched, "sector", weight_col, "Sector Allocation", "sector")

    with tab2:
        if weight_col in enriched.columns:
            make_pie(enriched, "industry", weight_col, "Industry Allocation", "industry")

    with tab3:
        if weight_col in enriched.columns:
            make_pie(enriched, "currency", weight_col, "Currency Exposure", "currency")

    with tab4:
        if weight_col in enriched.columns:
            make_pie(enriched, "country", weight_col, "Country Exposure", "country")

    with tab5:
        if weight_col in enriched.columns:
            make_pie(enriched, "cap_size", weight_col, "Market Cap Distribution", "cap_size")

    # ── Performance Returns Table ────────────────────────────────────────────────
    st.divider()
    st.subheader("📈 Portfolio Returns")

    from core.data_engine import get_history, calc_cagr
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time as _time

    PERF_PERIODS = [
        ("1d",  "5d",  None),
        ("1w",  "5d",  None),
        ("1m",  "1mo", None),
        ("3m",  "3mo", None),
        ("6m",  "6mo", None),
        ("1y",  "1y",  1.0),
        ("YTD", "ytd", None),
        ("3y",  "3y",  3.0),
        ("5y",  "5y",  5.0),
    ]

    perf_t_col   = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
    perf_tickers = enriched[perf_t_col].dropna().tolist()

    # ── 30-min session_state cache — avoid re-fetching on every page visit ────
    PERF_CACHE_TTL  = 1800   # 30 minutes
    PERF_CACHE_KEY  = "portfolio_returns_cache"
    PERF_CACHE_TS   = "portfolio_returns_ts"

    now_ts     = _time.time()
    cached_ts  = st.session_state.get(PERF_CACHE_TS, 0)
    perf_cache = st.session_state.get(PERF_CACHE_KEY)
    cache_age  = int(now_ts - cached_ts)

    refresh_col, _ = st.columns([1, 5])
    with refresh_col:
        recalc_btn = st.button("🔄 Recalculate", key="perf_recalc",
                               help="Refresh multi-period return data (takes ~30s)")

    if recalc_btn:
        perf_cache = None   # force re-fetch

    if perf_tickers and weight_col in enriched.columns and perf_cache is None:
        total_mv = enriched[weight_col].sum()
        perf_weights = {
            row[perf_t_col]: row[weight_col] / total_mv if total_mv > 0 else 1.0 / len(perf_tickers)
            for _, row in enriched.iterrows()
        }

        # Fetch ALL period+ticker combos in ONE parallel pool (max 60 s total)
        def _fetch_period(t, yf_period):
            h = get_history(t, yf_period)
            if isinstance(h, pd.DataFrame) and len(h) >= 2:
                col = "Close" if "Close" in h.columns else h.columns[0]
                return t, yf_period, h[col].dropna()
            if isinstance(h, pd.Series) and len(h) >= 2:
                return t, yf_period, h.dropna()
            return t, yf_period, None

        all_combos   = [(t, yf_p) for t in perf_tickers for _, yf_p, _ in PERF_PERIODS]
        perf_hist    = {}   # {(ticker, yf_period): Series}

        with st.spinner(f"Calculating returns for {len(perf_tickers)} holdings across 9 periods…"):
            fetch_pool = ThreadPoolExecutor(max_workers=15)
            try:
                futs = {fetch_pool.submit(_fetch_period, t, p): (t, p) for t, p in all_combos}
                try:
                    for f in as_completed(futs, timeout=60):
                        try:
                            t, p, series = f.result(timeout=10)
                            if series is not None and len(series) >= 2:
                                perf_hist[(t, p)] = series
                        except Exception:
                            pass
                except Exception:
                    pass  # 60-second cap — use whatever we fetched
            finally:
                fetch_pool.shutdown(wait=False)

        # Compute weighted-average portfolio return for each period
        perf_results = {}
        for label, yf_p, years in PERF_PERIODS:
            histories = {t: perf_hist[(t, yf_p)] for t in perf_tickers if (t, yf_p) in perf_hist}
            if not histories:
                perf_results[label] = {"Return": None, "CAGR": None}
                continue
            normalized = {t: s / s.iloc[0] * 100 for t, s in histories.items() if len(s) > 0}
            if not normalized:
                perf_results[label] = {"Return": None, "CAGR": None}
                continue
            port_df  = pd.DataFrame(normalized).ffill().bfill()
            w_s = pd.Series({t: perf_weights.get(t, 0) for t in port_df.columns})
            w_s = w_s / w_s.sum()
            port_series = (port_df * w_s).sum(axis=1)
            ret_pct  = (port_series.iloc[-1] / port_series.iloc[0] - 1) * 100
            cagr_val = calc_cagr(port_series.iloc[0], port_series.iloc[-1], years) if years else None
            perf_results[label] = {"Return": ret_pct, "CAGR": cagr_val}

        # Save to session_state cache
        st.session_state[PERF_CACHE_KEY] = perf_results
        st.session_state[PERF_CACHE_TS]  = _time.time()
        perf_cache = perf_results

    if perf_cache is not None:
        age_str = f"{cache_age//60}m {cache_age%60}s ago" if cache_age >= 60 else f"{cache_age}s ago"
        st.caption(f"Returns calculated **{age_str}** · refreshes every 30 min")

        perf_rows = []
        for label, _, years in PERF_PERIODS:
            r    = perf_cache.get(label, {})
            ret  = r.get("Return")
            cagr = r.get("CAGR")
            perf_rows.append({
                "Period": label,
                "Return": f"{ret:+.2f}%" if ret is not None else "",
                "CAGR":   f"{cagr*100:+.2f}%" if cagr is not None else "",
            })
        perf_df = pd.DataFrame(perf_rows)
        # Color-code returns
        def _perf_color(val):
            if not val or val == "": return ""
            try:
                v = float(val.replace("%", "").replace("+", ""))
                if v > 0: return "color: #1a9e5c; font-weight: 600"
                if v < 0: return "color: #d63031; font-weight: 600"
            except ValueError:
                pass
            return ""
        styled_perf = perf_df.style.map(_perf_color, subset=["Return", "CAGR"])
        st.dataframe(styled_perf, hide_index=True, use_container_width=True)
    elif not perf_tickers or weight_col not in enriched.columns:
        st.caption("Market value data needed — ensure prices are loaded.")


    # ── Risk Metrics ──────────────────────────────────────────────────────────
    st.divider()
    st.subheader("⚠️ Risk Metrics")
    st.caption("Portfolio-level risk indicators. Requires price history and NAV snapshots.")

    try:
        risk_period = st.selectbox("Risk Period", ["1y", "2y", "3y", "5y"], index=0,
                                    format_func=lambda p: {"1y": "1 Year", "2y": "2 Years", "3y": "3 Years", "5y": "5 Years"}[p],
                                    key="risk_period_select")

        perf_t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
        risk_tickers = enriched[perf_t_col].dropna().tolist()

        if risk_tickers and weight_col in enriched.columns:
            total_mv = enriched[weight_col].sum()
            risk_weights = {
                row[perf_t_col]: row[weight_col] / total_mv if total_mv > 0 else 1.0 / len(risk_tickers)
                for _, row in enriched.iterrows()
            }

            # Calculate portfolio daily returns for Sharpe / Sortino
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with st.spinner("Calculating risk metrics…"):
                risk_histories = {}
                def _fetch_risk(ticker):
                    h = get_history(ticker, risk_period)
                    if h is not None and isinstance(h, pd.DataFrame) and len(h) >= 20:
                        col = "Close" if "Close" in h.columns else h.columns[0]
                        return ticker, h[col].dropna()
                    return ticker, None

                with ThreadPoolExecutor(max_workers=min(len(risk_tickers), 15)) as pool:
                    futs = {pool.submit(_fetch_risk, t): t for t in risk_tickers}
                    for f in as_completed(futs):
                        t, series = f.result()
                        if series is not None and len(series) >= 20:
                            risk_histories[t] = series

                if risk_histories:
                    # Build weighted portfolio series
                    normalized = {t: s / s.iloc[0] * 100 for t, s in risk_histories.items()}
                    port_df = pd.DataFrame(normalized).ffill().bfill()
                    w_s = pd.Series({t: risk_weights.get(t, 0) for t in port_df.columns})
                    w_s = w_s / w_s.sum()
                    port_series = (port_df * w_s).sum(axis=1)
                    port_daily_returns = port_series.pct_change().dropna()

                    # Calculate metrics
                    max_dd = calc_max_drawdown(port_series)
                    sharpe = calc_sharpe_ratio(port_daily_returns)
                    sortino = calc_sortino_ratio(port_daily_returns)
                    port_beta = calc_portfolio_beta(risk_tickers, risk_weights, risk_period)
                    port_vol = calc_portfolio_volatility(risk_tickers, risk_weights, risk_period)

                    rc1, rc2, rc3, rc4, rc5 = st.columns(5)
                    with rc1:
                        if port_beta is not None:
                            st.metric("Portfolio Beta", f"{port_beta:.2f}",
                                      help="Weighted avg beta vs market. 1.0 = same as market, >1 = more volatile.")
                        else:
                            st.metric("Portfolio Beta", "—")
                    with rc2:
                        if max_dd is not None:
                            st.metric("Max Drawdown", f"{max_dd*100:.1f}%",
                                      help="Largest peak-to-trough decline in the period.")
                        else:
                            st.metric("Max Drawdown", "—")
                    with rc3:
                        if port_vol is not None:
                            st.metric("Volatility (Ann.)", f"{port_vol*100:.1f}%",
                                      help="Annualized standard deviation of daily returns.")
                        else:
                            st.metric("Volatility (Ann.)", "—")
                    with rc4:
                        if sharpe is not None:
                            st.metric("Sharpe Ratio", f"{sharpe:.2f}",
                                      help="Risk-adjusted return. >1 is good, >2 is excellent.")
                        else:
                            st.metric("Sharpe Ratio", "—")
                    with rc5:
                        if sortino is not None:
                            st.metric("Sortino Ratio", f"{sortino:.2f}",
                                      help="Like Sharpe but only penalizes downside risk. Higher is better.")
                        else:
                            st.metric("Sortino Ratio", "—")

                    st.caption("ℹ️ Beta uses individual stock betas from market data. Sharpe/Sortino use 5% risk-free rate (US T-bills).")
                else:
                    st.info("Not enough price history to calculate risk metrics. Ensure prices are loaded on the Dashboard.")
        else:
            st.info("Market value data needed — ensure prices are loaded on the Dashboard.")

    except Exception as risk_err:
        st.warning(f"Could not calculate risk metrics: {risk_err}")


except Exception as _err:
    import traceback
    st.error("⚠️ An error occurred on this page. Please try refreshing.")
    with st.expander("🔍 Error details (for debugging)"):
        st.code(traceback.format_exc())
    if st.button("🔄 Retry", key="page_retry"):
        st.rerun()
