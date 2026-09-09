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
    deduplicate_tickers,
)
from core.settings import SETTINGS, enriched_cache_key

from core.ui_components import (page_header, hero_metric, stat_grid,
                                fmt_compact, render_responsive_table)
page_header("Allocation", "Where the money actually sits")

holdings = get_all_holdings()
if holdings.empty:
    st.info("Add holdings via **Add holdings** to see your portfolio summary.")
    st.stop()


try:
    base_currency = SETTINGS.get("base_currency", "USD")

    # ── Get enriched + info data ──
    cache_key = enriched_cache_key(base_currency)
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
    def _get_asset_category(t):
        vals = enriched.loc[enriched[t_col] == t, "asset_category"].values if "asset_category" in enriched.columns else []
        return str(vals[0]).lower() if len(vals) > 0 and vals[0] else ""

    def _resolve_sector(t):
        _inf = info_map.get(t, {})
        qt = str(_inf.get("quoteType", "EQUITY")).upper()
        # asset_category comes from the broker statement itself (ground truth —
        # doesn't need the ticker to resolve on any live price API, unlike
        # quoteType which defaults to EQUITY when a fund fails to price).
        ac = _get_asset_category(t)
        if "fund" in ac or "etf" in ac:
            qt = "MUTUALFUND"
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
        if "fund" in _get_asset_category(t) or "etf" in _get_asset_category(t):
            qt = "MUTUALFUND"
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
    _n_pos = len(enriched)
    _n_ccy = enriched["currency"].nunique() if "currency" in enriched.columns else 1
    hero_metric(
        "Total Portfolio Value",
        fmt_compact(total_val, base_currency) if total_val else "—",
        sub=f"{_n_pos} positions · {_n_ccy} currencies",
        title=f"{base_currency} {total_val:,.2f}" if total_val else "",
    )

    # ── Allocation, one dimension at a time ─────────────────────────────────
    # Was five st.tabs, each drawing a Plotly donut — and Streamlit tabs are
    # eager, so all five rendered on every visit whether or not they were
    # opened. Five donuts at ~330px each, for a question ("how is the book
    # split?") that a ranked list answers better: a donut cannot be sorted,
    # spends its area on a hole, and at 375px hides any slice whose label
    # would render below 10px — which for a 14-sector allocation is most of
    # them.
    #
    # The pie's click-to-drill is preserved as a selectbox. Tapping a slice at
    # 375px was fiddly at best, and a list of segment names is both reachable
    # and readable.
    import core.ledger_ui as _lu

    _DIMS = {
        "Sector":     "sector",
        "Industry":   "industry",
        "Currency":   "currency",
        "Country":    "country",
        "Market cap": "cap_size",
    }
    _dim_label = st.segmented_control(
        "Break down by", list(_DIMS), key="sum_dim", default="Sector",
    ) or "Sector"
    group_col = _DIMS[_dim_label]

    if weight_col in enriched.columns and group_col in enriched.columns:
        grouped = enriched.groupby(group_col)[weight_col].sum().reset_index()
        grouped.columns = [group_col, "Value"]
        grouped = grouped[grouped["Value"] > 0].sort_values("Value", ascending=False)

        if grouped.empty:
            st.info("No data available for this breakdown.")
        else:
            _total = grouped["Value"].sum()
            grouped["pct"] = (grouped["Value"] / _total * 100).round(1)
            _lead = grouped.iloc[0]
            st.markdown(_lu.read(
                f'Largest {_dim_label.lower()} exposure is <b>{_lead[group_col] or "Unclassified"}</b> '
                f'at {_lead["pct"]:.1f}%. Top three are {grouped.head(3)["pct"].sum():.1f}% '
                f'of {len(grouped)} groups.'
            ), unsafe_allow_html=True)
            st.markdown(_lu.ranked_bars([
                {"name": str(r[group_col]) or "Unclassified",
                 "pct": float(r["pct"]),
                 "meta": f'{base_currency} {r["Value"]:,.0f}',
                 "state": "over" if float(r["pct"]) > 25 else ""}
                for _, r in grouped.iterrows()
            ], limit=14), unsafe_allow_html=True)

            # ── Drill-down ──
            _segments = grouped[group_col].astype(str).tolist()
            _pick = st.selectbox(
                f"Show holdings in a {_dim_label.lower()}",
                ["—"] + _segments, key=f"sum_drill_{group_col}",
            )
            if _pick and _pick != "—":
                segment_df = enriched[enriched[group_col].astype(str) == _pick].copy()
                t_col_d = "ticker_resolved" if "ticker_resolved" in segment_df.columns else "ticker"
                drill = pd.DataFrame()
                drill["Ticker"] = segment_df[t_col_d].values
                drill["Name"] = segment_df.get("name", pd.Series(dtype=str)).fillna("").values
                if "current_price" in segment_df.columns:
                    drill["Price"] = segment_df["current_price"].apply(
                        lambda v: f"{float(v):,.2f}" if pd.notna(v) and float(v) >= 1
                        else (f"{float(v):,.4f}" if pd.notna(v) else "")).values
                if weight_col in segment_df.columns:
                    drill[f"Value ({base_currency})"] = segment_df[weight_col].apply(
                        lambda v: f"{float(v):,.0f}" if pd.notna(v) else "").values
                if "unrealized_pnl" in segment_df.columns:
                    drill["P&L"] = segment_df["unrealized_pnl"].apply(
                        lambda v: f"{float(v):+,.0f}" if pd.notna(v) else "").values
                if "unrealized_pnl_pct" in segment_df.columns:
                    drill["Return %"] = segment_df["unrealized_pnl_pct"].apply(
                        lambda v: f"{float(v):+.1f}%" if pd.notna(v) else "").values
                from core.data_engine import clean_nan
                st.caption(f"**{len(drill)} holdings in {_pick}**")
                render_responsive_table(clean_nan(drill), title_col="Ticker")

    # ── Portfolio Returns: REMOVED (Phase 3) ────────────────────────────────
    # This fetched a price history for every holding across nine periods —
    # 182 x 9 = 1,638 get_history() calls in a 5-worker pool with a 60s cap,
    # session-cached only. Same fan-out P2-2 removed from the Performance
    # page, and the last known freeze path on a 512MiB / 0.15vCPU instance.
    #
    # It was also wrong in a way nothing surfaced: it applied TODAY's weights
    # to historical prices, so its 1-year return disagreed with the
    # Performance page's, which draws the portfolio line from nav_snapshots.
    # Two pages, one question, two answers, no reconciliation.
    #
    # Performance is now the single owner of "how did the portfolio do".
    st.divider()
    st.caption("Returns over time live on the **Performance** page, which draws "
               "the portfolio line from daily NAV snapshots.")
    st.page_link("views/5_Performance.py", label="Open Performance", icon="📈")

    # ── Risk Metrics ──────────────────────────────────────────────────────────
    st.divider()
    st.subheader("⚠️ Risk Metrics")
    st.caption("Portfolio-level risk indicators. Requires price history and NAV snapshots.")

    try:
        risk_period = st.selectbox("Risk Period", ["1y", "2y", "3y", "5y"], index=0,
                                    format_func=lambda p: {"1y": "1 Year", "2y": "2 Years", "3y": "3 Years", "5y": "5 Years"}[p],
                                    key="risk_period_select")

        perf_t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
        # Deduplicate tickers to prevent "duplicate labels" error when creating DataFrame
        risk_tickers = deduplicate_tickers(enriched[perf_t_col].dropna().tolist())

        if risk_tickers and weight_col in enriched.columns:
            total_mv = enriched[weight_col].sum()
            # Build weights from deduplicated tickers, summing market_value for duplicate rows
            risk_weights = {}
            for t in risk_tickers:
                mv = enriched[enriched[perf_t_col] == t][weight_col].sum()
                risk_weights[t] = mv / total_mv if total_mv > 0 else 1.0 / len(risk_tickers)

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

                with ThreadPoolExecutor(max_workers=min(len(risk_tickers), 5)) as pool:
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

                    # Five risk figures. As st.columns(5) each track was ~65px
                    # wide on a phone and the values collided; below ~640px they
                    # stacked into five separate rows instead. Two grids keep
                    # them side by side and grouped by what they measure —
                    # exposure first, then reward-for-risk.
                    _pc = lambda v: f"{v*100:.1f}%" if v is not None else "—"
                    stat_grid([
                        ("Beta", f"{port_beta:.2f}" if port_beta is not None else "—"),
                        ("Max drawdown", _pc(max_dd), "", max_dd),
                        ("Volatility", _pc(port_vol)),
                    ], columns=3)
                    stat_grid([
                        ("Sharpe", f"{sharpe:.2f}" if sharpe is not None else "—", "", sharpe),
                        ("Sortino", f"{sortino:.2f}" if sortino is not None else "—", "", sortino),
                    ], columns=2)
                    st.caption(
                        "Beta 1.0 = moves with the market. Max drawdown is the worst "
                        "peak-to-trough fall in the period. Sharpe/Sortino above 1 is good; "
                        "Sortino only counts downside moves."
                    )
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
