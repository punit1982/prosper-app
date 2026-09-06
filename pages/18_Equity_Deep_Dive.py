"""
Equity Deep Dive
================
Single-stock 360° research view — all data in one place.
Sections: Identity, Price, Chart, Fundamentals, Analyst, Sentiment,
          Ownership, Portfolio Position, Prosper AI (on-demand).
"""

import math
import streamlit as st
from core.ui_components import show_chart
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

from core.database import get_all_holdings, get_prosper_analysis, save_prosper_analysis
from core.data_engine import (
    get_ticker_info, get_history, get_ticker_sentiment, get_ticker_news,
    get_analyst_price_targets, get_upgrade_downgrade,
    get_insider_transactions, get_insider_purchases,
    get_institutional_holders, get_major_holders,
    fmt_large, clean_nan, summarize_news_with_ai,
)
from core.grow_engine import run_grow, GROW_TIERS
from core.settings import SETTINGS, enriched_cache_key
from core.ui_errors import fetch_failed, empty_state

from core.ui_components import (page_header, hero_metric, stat_grid,
                                fmt_compact, render_responsive_table)
page_header("Equity Deep Dive", "One name, everything Prosper knows about it")
st.caption("Comprehensive 360° view of any stock — fundamentals, analyst consensus, sentiment, ownership, and the GROW two-verdict analysis.")

# ─────────────────────────────────────────
# TICKER PICKER — Main Screen
# ─────────────────────────────────────────
holdings = get_all_holdings()
portfolio_tickers = sorted(holdings["ticker"].dropna().unique().tolist()) if not holdings.empty else []

# Build resolved ticker map from enriched data if available
base_currency = SETTINGS.get("base_currency", "USD")
_enriched_cache = st.session_state.get(enriched_cache_key(base_currency))
_resolve_map = {}
if _enriched_cache is not None and not _enriched_cache.empty and "ticker_resolved" in _enriched_cache.columns:
    _resolve_map = dict(zip(_enriched_cache["ticker"], _enriched_cache["ticker_resolved"]))

pick_col1, pick_col2, pick_col3 = st.columns([1, 2, 2])
with pick_col1:
    source = st.radio("Source", ["Portfolio", "Manual"], horizontal=True, key="dd_source")
with pick_col2:
    if source == "Portfolio" and portfolio_tickers:
        # Search filter
        names_map = dict(zip(holdings["ticker"], holdings["name"])) if not holdings.empty else {}
        search = st.text_input("Search", placeholder="Type ticker or name...", key="dd_search", label_visibility="collapsed")
        if search:
            filtered = [t for t in portfolio_tickers
                       if search.upper() in t.upper() or search.lower() in names_map.get(t, "").lower()]
        else:
            filtered = portfolio_tickers
    else:
        filtered = []
        search = ""
with pick_col3:
    if source == "Portfolio" and filtered:
        names_map = dict(zip(holdings["ticker"], holdings["name"])) if not holdings.empty else {}
        _display_ticker = st.selectbox("Ticker", filtered, key="dd_ticker_select",
                              format_func=lambda t: f"{t} — {names_map.get(t, '')}",
                              label_visibility="collapsed")
        # Use resolved ticker for data fetching (e.g. EMAAR → EMAAR.AE)
        ticker = _resolve_map.get(_display_ticker, _display_ticker) if _display_ticker else _display_ticker
    elif source == "Portfolio" and not filtered and search:
        st.warning("No matches")
        ticker = None
    else:
        ticker = st.text_input("Enter Ticker", value="AAPL", max_chars=20,
                               key="dd_ticker_input", label_visibility="collapsed").strip().upper()

if not ticker:
    st.info("Select a ticker above to begin.")
    st.stop()

# ─────────────────────────────────────────
# FETCH CORE DATA
# ─────────────────────────────────────────
with st.spinner(f"Loading data for **{ticker}**…"):
    info = get_ticker_info(ticker)

if not info:
    st.warning(f"Could not fetch data for **{ticker}**. Check the ticker symbol and try again.")
    st.stop()


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def _sf(v):
    """Safe float conversion."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _safe(val, fmt=None):
    """Return formatted value or None if missing."""
    if val is None:
        return None
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return None
    except (TypeError, ValueError):
        pass
    if fmt == "pct":
        v = float(val)
        # yfinance sometimes returns already-percentage values (8.5 vs 0.085)
        pct = v * 100 if abs(v) < 1 else v
        if abs(pct) > 200:
            return None  # nonsensical — suppress
        return f"{pct:.1f}%"
    if fmt == "money":
        return fmt_large(val)
    if fmt == "ratio":
        v = float(val)
        if abs(v) > 10000:
            return None  # nonsensical ratio — suppress
        return f"{v:.2f}"
    return str(val)


def _mcap_badge(mcap):
    if mcap is None:
        return ""
    if mcap >= 200e9:
        return "Mega Cap"
    elif mcap >= 10e9:
        return "Large Cap"
    elif mcap >= 2e9:
        return "Mid Cap"
    elif mcap >= 300e6:
        return "Small Cap"
    return "Micro Cap"


_COUNTRY_FLAGS = {
    "United States": "🇺🇸", "India": "🇮🇳", "United Kingdom": "🇬🇧",
    "Switzerland": "🇨🇭", "Germany": "🇩🇪", "France": "🇫🇷",
    "Japan": "🇯🇵", "China": "🇨🇳", "Hong Kong": "🇭🇰",
    "Canada": "🇨🇦", "Australia": "🇦🇺", "Singapore": "🇸🇬",
    "United Arab Emirates": "🇦🇪", "South Korea": "🇰🇷", "Brazil": "🇧🇷",
}

_RATING_COLORS = {
    "STRONG BUY": "#00C853", "BUY": "#1a9e5c", "HOLD": "#f39c12",
    "SELL": "#FF6D00", "STRONG SELL": "#DD2C00",
}


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — IDENTITY HEADER
# ═══════════════════════════════════════════════════════════════════
company_name = info.get("longName") or info.get("shortName", ticker)
sector = info.get("sector", "")
industry = info.get("industry", "")
country = info.get("country", "")
exchange = info.get("exchange", "")
mcap = info.get("marketCap")
flag = _COUNTRY_FLAGS.get(country, "🌐")
badge = _mcap_badge(mcap)

st.markdown(f"## {company_name}")
breadcrumb_parts = [f"`{ticker}`"]
if exchange:
    breadcrumb_parts.append(exchange)
if sector:
    breadcrumb_parts.append(f"**{sector}**")
if industry:
    breadcrumb_parts.append(industry)
if badge:
    breadcrumb_parts.append(badge)
st.caption(f"{flag} {' · '.join(breadcrumb_parts)}")

# Business summary
summary = info.get("longBusinessSummary", "")
if summary:
    # Take first 2-3 sentences
    sentences = summary.replace(". ", ".|").split("|")
    short = ". ".join(s.strip() for s in sentences[:3])
    if not short.endswith("."):
        short += "."
    st.markdown(f"*{short}*")

st.divider()

# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — PRICE & VALUATION SNAPSHOT
# ═══════════════════════════════════════════════════════════════════
# Every per-share figure on this page is quoted in the instrument's OWN
# currency, not the user's base. Printing "USD 6731.0" for a Tokyo listing was
# not a formatting nit — it silently misstated the price by ~150x.
from core.currency_normalizer import instrument_currency as _instr_ccy
ccy = _instr_ccy(ticker, info)

price = info.get("currentPrice") or info.get("regularMarketPrice")
prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
day_change = None
day_pct = None
if price and prev_close and prev_close > 0:
    day_change = price - prev_close
    day_pct = (day_change / prev_close) * 100

hi52 = info.get("fiftyTwoWeekHigh")
lo52 = info.get("fiftyTwoWeekLow")
pe = info.get("trailingPE")
fwd_pe = info.get("forwardPE")

# Price is the headline; market cap, P/E and the 52-week position support it.
# As st.columns(4) these were four equal tracks that stacked into four rows on
# a phone, putting the tab strip below the fold on the app's densest page.
hero_metric(
    "Price",
    f"{ccy} {price:,.2f}" if price else "—",
    delta=(f"{day_change:+.2f} ({day_pct:+.1f}%) today"
           if day_change is not None else ""),
    delta_value=day_change,
    sub=info.get("shortName") or info.get("longName") or "",
)

_pe_v = _sf(pe)
_fwd_v = _sf(fwd_pe)
stat_grid([
    ("Market cap", fmt_large(mcap) if mcap else "—"),
    ("P/E", f"{_pe_v:.1f}" if _pe_v is not None else "—"),
    ("Fwd P/E", f"{_fwd_v:.1f}" if _fwd_v is not None else "—"),
], columns=3)

# 52-week position — a bar says "where in the year's range are we" faster than
# two numbers do, so it stays, but as a full-width row rather than one cramped
# quarter of a four-column split.
if hi52 and lo52 and price:
    range_span = hi52 - lo52
    if range_span > 0:
        pct = max(0, min(100, ((price - lo52) / range_span) * 100))
        color = "#1a9e5c" if pct > 60 else "#a6741a" if pct > 30 else "#d63031"
        st.markdown(
            '<div style="margin:2px 0 12px">'
            '<div style="font-size:0.63rem;letter-spacing:0.05em;text-transform:uppercase;'
            'opacity:0.55;font-weight:600;margin-bottom:5px">52-week range</div>'
            '<div style="display:flex;align-items:center;gap:9px">'
            f'<span style="font-size:0.72rem;opacity:0.7;font-variant-numeric:tabular-nums">'
            f'{lo52:,.0f}</span>'
            '<div style="flex:1;background:rgba(128,128,128,0.25);border-radius:4px;height:7px;'
            'position:relative">'
            f'<div style="background:{color};height:7px;border-radius:4px;width:{pct:.0f}%"></div>'
            '</div>'
            f'<span style="font-size:0.72rem;opacity:0.7;font-variant-numeric:tabular-nums">'
            f'{hi52:,.0f}</span>'
            '</div></div>',
            unsafe_allow_html=True,
        )

st.divider()

# ═══════════════════════════════════════════════════════════════════
# TABBED LAYOUT
# ═══════════════════════════════════════════════════════════════════
# One screen per name. "Peers" closes the last gap that still sent the user to
# a separate page for research on the same ticker — Analyst, Sentiment and
# Technical already live here as tabs.
(tab_chart, tab_fundamentals, tab_analyst, tab_peers,
 tab_ownership, tab_technical, tab_ai) = st.tabs([
    "Price & Chart", "Fundamentals", "Analyst & Sentiment", "Peers",
    "Ownership", "Technical Signals", "GROW",
])

with tab_peers:
    try:
        from core.data_engine import get_ticker_info_batch as _peer_info_batch
        st.markdown("#### Sector peers")
        _sector = info.get("sector") or ""
        _industry = info.get("industry") or ""
        if not _sector:
            empty_state("sector data for this ticker",
                        action="Peer comparison needs a sector, which this listing does not report.")
        else:
            st.caption(f"{_sector}{' · ' + _industry if _industry else ''}")
            # Peers are drawn from the user's OWN holdings in the same sector —
            # a comparison against names they actually own is more useful than
            # an arbitrary index slice, and it costs no extra API calls.
            _peer_pool = []
            if _enriched_cache is not None and not _enriched_cache.empty:
                _ec = _enriched_cache
                if "sector" in _ec.columns:
                    _peer_pool = [t for t in _ec[_ec["sector"] == _sector]["ticker_resolved"].dropna().unique()
                                  if str(t) != str(ticker)][:11]
            if not _peer_pool:
                _tk_col = "ticker_resolved" if (_enriched_cache is not None
                                               and "ticker_resolved" in _enriched_cache.columns) else None
                _all = list(_enriched_cache[_tk_col].dropna().unique()) if _tk_col else []
                _pinfo = _peer_info_batch([t for t in _all if str(t) != str(ticker)][:40])
                _peer_pool = [t for t, i in _pinfo.items() if (i or {}).get("sector") == _sector][:11]

            if not _peer_pool:
                empty_state("peers in this sector",
                            action="No other holding in your portfolio shares this sector yet.")
            else:
                _pi = _peer_info_batch([ticker] + list(_peer_pool))
                _rows = []
                for _t in [ticker] + list(_peer_pool):
                    _i = _pi.get(_t) or {}
                    _rows.append({
                        "Ticker": _t + (" ←" if _t == ticker else ""),
                        "Name": (_i.get("shortName") or "")[:22],
                        "Price": (f"{_instr_ccy(_t, _i)} {_i['currentPrice']:,.2f}"
                                  if _i.get("currentPrice") else "—"),
                        "P/E": f"{_i['trailingPE']:.1f}" if _i.get("trailingPE") else "—",
                        "Fwd P/E": f"{_i['forwardPE']:.1f}" if _i.get("forwardPE") else "—",
                        "Mkt Cap": fmt_large(_i["marketCap"]) if _i.get("marketCap") else "—",
                        "Div Yld": (f"{_i['dividendYield']*100:.2f}%"
                                    if _i.get("dividendYield") else "—"),
                    })
                render_responsive_table(pd.DataFrame(_rows), title_col="Ticker")
                st.caption(
                    "Peers are the other holdings in your portfolio that share this sector. "
                    "For a wider screen against non-holdings, use **Peer Comparison**."
                )
    except Exception as e:
        fetch_failed("peer data", e)

# ═══════════════════════════════════════════════════════════════════
# TAB 1 — PRICE CHART (wrapped in container for tab context)
# ═══════════════════════════════════════════════════════════════════
with tab_chart:
    try:
        st.subheader("Price History")

        period_map = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "1Y": "1y", "2Y": "2y", "5Y": "5y"}
        col_period, col_bench = st.columns([3, 2])
        with col_period:
            period_label = st.selectbox("Period", list(period_map.keys()), index=2, key="dd_period", label_visibility="collapsed")
        with col_bench:
            # Auto-detect benchmark
            is_india = ticker.endswith(".NS") or ticker.endswith(".BO") or country == "India"
            default_bench = "^NSEI" if is_india else "^GSPC"
            bench_label = "Nifty 50" if is_india else "S&P 500"
            show_bench = st.checkbox(f"Compare vs {bench_label}", value=True, key="dd_bench")

        period = period_map[period_label]
        hist = get_history(ticker, period)

        # Sanitize yfinance output (flatten MultiIndex, dedup, tz-naive)
        from core.yf_utils import sanitize_history
        hist = sanitize_history(hist)
        if hist is not None and not hist.empty:
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                vertical_spacing=0.03, row_heights=[0.75, 0.25],
            )

            # Price line
            close_col = "Close" if "Close" in hist.columns else hist.columns[0]
            fig.add_trace(
                go.Scatter(x=hist.index, y=hist[close_col], name=ticker, line=dict(color="#1a9e5c", width=2),
                           hovertemplate="%{x|%b %d, %Y}<br>Price: %{y:,.2f}<extra>" + ticker + "</extra>"),
                row=1, col=1,
            )

            # Volume bars
            if "Volume" in hist.columns:
                colors = ["#1a9e5c" if c >= o else "#d63031"
                          for c, o in zip(hist.get("Close", hist[close_col]), hist.get("Open", hist[close_col]))]
                fig.add_trace(
                    go.Bar(x=hist.index, y=hist["Volume"], name="Volume", marker_color=colors, opacity=0.4),
                    row=2, col=1,
                )

            # Benchmark overlay (indexed to 100)
            if show_bench:
                bench_hist = get_history(default_bench, period)
                bench_hist = sanitize_history(bench_hist)
                if bench_hist is not None and not bench_hist.empty:
                    b_col = "Close" if "Close" in bench_hist.columns else bench_hist.columns[0]
                    # Index both to 100
                    stock_indexed = (hist[close_col] / hist[close_col].iloc[0]) * 100
                    bench_indexed = (bench_hist[b_col] / bench_hist[b_col].iloc[0]) * 100

                    # Replace stock line with indexed version, store actual prices in customdata
                    fig.data[0].y = stock_indexed
                    fig.data[0].customdata = hist[close_col].values
                    fig.data[0].name = f"{ticker} (indexed)"
                    fig.data[0].hovertemplate = "%{x|%b %d, %Y}<br>Indexed: %{y:.1f}<br>Price: %{customdata:,.2f}<extra>" + ticker + "</extra>"

                    fig.add_trace(
                        go.Scatter(x=bench_hist.index, y=bench_indexed, name=f"{bench_label} (indexed)",
                                   line=dict(color="#888", width=1, dash="dash"),
                                   customdata=bench_hist[b_col].values,
                                   hovertemplate="%{x|%b %d, %Y}<br>Indexed: %{y:.1f}<br>Price: %{customdata:,.2f}<extra>" + bench_label + "</extra>"),
                        row=1, col=1,
                    )

            fig.update_layout(
                height=420, margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", y=1.02),
                xaxis2_title="",
                yaxis_title="Price" if not show_bench else "Indexed (100)",
                yaxis2_title="Volume",
                template="plotly_dark",
                showlegend=True,
            )
            fig.update_xaxes(rangeslider_visible=False)
            show_chart(fig)
        else:
            st.info("No price history available for this ticker.")

        st.divider()

        # ═══════════════════════════════════════════════════════════════════
        # -- Dividend snapshot (uses current ticker's info) --
        _div_rate = info.get("dividendRate")
        _div_yield = info.get("dividendYield")
        _ex_date = info.get("exDividendDate")
        _payout = info.get("payoutRatio")
        if _div_rate or _div_yield:
            st.markdown("---")
            st.caption(f"**Dividend Summary — {ticker}**")
            _div_rate_f = _sf(_div_rate)
            _dy_f = _sf(_div_yield)
            _dy = _dy_f * 100 if _dy_f is not None and _dy_f < 1 else _dy_f
            _payout_f = _sf(_payout)
            _ed = "—"
            if _ex_date:
                try:
                    from datetime import datetime as _dt
                    _ed = _dt.fromtimestamp(_ex_date).strftime("%d %b %Y")
                except Exception:
                    _ed = "—"
            stat_grid([
                ("Div / share", f"{ccy} {_div_rate_f:.2f}" if _div_rate_f is not None else "—"),
                ("Yield", f"{_dy:.2f}%" if _dy is not None else "—"),
                ("Payout", f"{_payout_f*100:.0f}%" if _payout_f is not None else "—"),
            ], columns=3)
            stat_grid([("Ex-dividend date", _ed)], columns=2)
    except Exception as e:
        fetch_failed("this section", e)

with tab_fundamentals:
    try:
        st.subheader("Key Fundamentals")

        col_val, col_health = st.columns(2)

        with col_val:
            st.markdown("**Valuation**")
            val_items = []
            for key, label in [
                ("trailingPE", "P/E (TTM)"), ("forwardPE", "Forward P/E"), ("priceToBook", "P/B"),
                ("priceToSalesTrailing12Months", "P/S"), ("pegRatio", "PEG"),
                ("enterpriseToEbitda", "EV/EBITDA"), ("dividendYield", "Dividend Yield"),
            ]:
                v = info.get(key)
                if v is not None:
                    try:
                        if math.isnan(v) or math.isinf(v):
                            continue
                    except (TypeError, ValueError):
                        continue
                    if key == "dividendYield":
                        pct = v * 100 if abs(v) < 1 else v
                        if abs(pct) > 50:
                            continue  # nonsensical — suppress
                        val_items.append(f"**{label}:** {pct:.2f}%")
                    elif key in ("trailingPE", "forwardPE") and (v <= 0 or v > 2000):
                        continue  # negative or extreme P/E — suppress
                    elif key in ("pegRatio",) and (v < -10 or v > 100):
                        continue  # extreme PEG — suppress
                    elif key == "enterpriseToEbitda" and (v <= 0 or v > 500):
                        continue  # nonsensical EV/EBITDA — suppress
                    else:
                        val_items.append(f"**{label}:** {v:.2f}")

            if val_items:
                for item in val_items:
                    st.markdown(item)
            else:
                st.caption("No valuation data available")

        with col_health:
            st.markdown("**Financial Health**")
            health_items = []

            for key, label, fmt in [
                ("totalRevenue", "Revenue", "money"), ("ebitda", "EBITDA", "money"),
                ("freeCashflow", "Free Cash Flow", "money"),
                ("profitMargins", "Profit Margin", "pct"), ("returnOnEquity", "ROE", "pct"),
                ("debtToEquity", "Debt/Equity", "ratio"), ("currentRatio", "Current Ratio", "ratio"),
                ("revenueGrowth", "Revenue Growth", "pct"), ("earningsGrowth", "Earnings Growth", "pct"),
            ]:
                v = info.get(key)
                formatted = _safe(v, fmt)
                if formatted:
                    # Add trend arrow for growth metrics
                    arrow = ""
                    if key in ("revenueGrowth", "earningsGrowth") and isinstance(v, (int, float)):
                        arrow = " 📈" if v > 0 else " 📉" if v < 0 else ""
                    health_items.append(f"**{label}:** {formatted}{arrow}")

            if health_items:
                for item in health_items:
                    st.markdown(item)
            else:
                st.caption("No financial data available")

        # ── Historical Financials (3Y + TTM) ──
        with st.expander("Historical Financials (3 Years + TTM)", expanded=False):
            import yfinance as yf
            tk = yf.Ticker(ticker)

            # Fetch annual financials
            try:
                annual_is = tk.financials  # income statement
                annual_bs = tk.balance_sheet
                annual_cf = tk.cashflow
                quarterly_is = tk.quarterly_financials

                if annual_is is not None and not annual_is.empty:
                    # Build a summary table with key metrics
                    # Columns: latest 3 annual years + TTM (sum of last 4 quarters)
                    # Rows: Revenue, Gross Profit, Operating Income, Net Income, EBITDA
                    # From balance sheet: Total Debt, Total Cash, Total Assets
                    # From cashflow: Operating Cash Flow, Free Cash Flow, CapEx

                    metrics = {}
                    # Get column headers (dates) - most recent first
                    annual_cols = annual_is.columns[:3]  # last 3 years
                    col_labels = [c.strftime("%Y") if hasattr(c, 'strftime') else str(c)[:4] for c in annual_cols]

                    # Add TTM from quarterly
                    if quarterly_is is not None and not quarterly_is.empty and len(quarterly_is.columns) >= 4:
                        col_labels = ["TTM"] + col_labels
                        has_ttm = True
                    else:
                        has_ttm = False

                    # Helper to get row from a dataframe
                    def _get_row(df, row_names, label):
                        for name in row_names:
                            if name in df.index:
                                vals = []
                                if has_ttm and quarterly_is is not None and name in quarterly_is.index:
                                    ttm_val = quarterly_is.loc[name].iloc[:4].sum()
                                    vals.append(ttm_val)
                                elif has_ttm:
                                    vals.append(None)
                                for col in annual_cols:
                                    try:
                                        vals.append(df.loc[name, col])
                                    except (KeyError, IndexError):
                                        vals.append(None)
                                return vals
                        return [None] * len(col_labels)

                    # Income Statement rows
                    rows_data = {}
                    for label, names, source in [
                        ("Revenue", ["Total Revenue", "Revenue"], annual_is),
                        ("Gross Profit", ["Gross Profit"], annual_is),
                        ("Operating Income", ["Operating Income", "EBIT"], annual_is),
                        ("Net Income", ["Net Income", "Net Income Common Stockholders"], annual_is),
                        ("EBITDA", ["EBITDA", "Normalized EBITDA"], annual_is),
                        ("Total Debt", ["Total Debt", "Long Term Debt"], annual_bs),
                        ("Cash & Equivalents", ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"], annual_bs),
                        ("Total Assets", ["Total Assets"], annual_bs),
                        ("Operating Cash Flow", ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], annual_cf),
                        ("Capital Expenditure", ["Capital Expenditure"], annual_cf),
                        ("Free Cash Flow", ["Free Cash Flow"], annual_cf),
                    ]:
                        vals = _get_row(source, names, label)
                        if any(v is not None and v != 0 for v in vals):
                            rows_data[label] = vals

                    if rows_data:
                        # Format values as compact numbers
                        table_data = {}
                        for period in col_labels:
                            table_data[period] = []

                        row_labels = []
                        for label, vals in rows_data.items():
                            row_labels.append(label)
                            for i, v in enumerate(vals):
                                formatted = fmt_large(v) if v is not None else "\u2014"
                                table_data[col_labels[i]].append(formatted)

                        hist_df = pd.DataFrame(table_data, index=row_labels)
                        st.dataframe(hist_df, use_container_width=True)
                    else:
                        st.caption("No historical financial data available.")
                else:
                    st.caption("No historical financial data available for this ticker.")
            except Exception as e:
                st.caption("Could not load historical financials.")

        st.divider()

        # ═══════════════════════════════════════════════════════════════════
    except Exception as e:
        fetch_failed("this section", e)

with tab_analyst:
    try:
        st.subheader("Analyst Consensus")

        targets = get_analyst_price_targets(ticker)
        target_low = targets.get("low")
        target_mean = targets.get("mean")
        target_high = targets.get("high")
        n_analysts = info.get("numberOfAnalystOpinions")
        consensus = info.get("recommendationKey", "").replace("_", " ").title()

        if target_mean and price:
            # Gauge: price position within analyst range
            gauge_col, info_col = st.columns([3, 2])
            with gauge_col:
                fig_gauge = go.Figure(go.Indicator(
                    mode="gauge+number+delta",
                    value=price,
                    delta={"reference": target_mean, "relative": True, "valueformat": ".1%"},
                    title={"text": f"Current vs Target ({n_analysts or '?'} analysts)"},
                    gauge={
                        "axis": {"range": [target_low * 0.9 if target_low else price * 0.7,
                                            target_high * 1.1 if target_high else price * 1.3]},
                        "bar": {"color": "#1a9e5c"},
                        "steps": [
                            {"range": [target_low * 0.9 if target_low else price * 0.7, target_low or price * 0.85], "color": "#DD2C00"},
                            {"range": [target_low or price * 0.85, target_mean or price], "color": "#f39c12"},
                            {"range": [target_mean or price, target_high or price * 1.15], "color": "#1a9e5c"},
                        ],
                        "threshold": {"line": {"color": "white", "width": 2}, "value": target_mean},
                    },
                ))
                fig_gauge.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=10), template="plotly_dark")
                show_chart(fig_gauge)

            with info_col:
                upside = ((target_mean - price) / price * 100) if target_mean and price else None
                stat_grid([
                    ("Consensus", consensus or "—"),
                    ("Mean target", f"{ccy} {target_mean:,.2f}" if target_mean else "—",
                     f"{upside:+.1f}% upside" if upside else "", upside),
                ], columns=2)
                if target_low and target_high:
                    st.caption(f"Range: {ccy} {target_low:,.2f} — {ccy} {target_high:,.2f}")

            # Recent upgrades/downgrades
            upgrades = get_upgrade_downgrade(ticker)
            if upgrades:
                recent = upgrades[:5]
                ud_rows = []
                for ud in recent:
                    date_val = ud.get("gradeTime", "")
                    if isinstance(date_val, (int, float)) and date_val > 0:
                        date_val = datetime.fromtimestamp(date_val).strftime("%b %d, %Y")
                    ud_rows.append({
                        "Date": date_val,
                        "Firm": ud.get("company", "—"),
                        "Action": ud.get("action", "—"),
                        "To": ud.get("toGrade", "—"),
                    })
                if ud_rows:
                    st.caption("**Recent Analyst Actions**")
                    render_responsive_table(pd.DataFrame(ud_rows))
        else:
            st.info("No analyst coverage data available for this ticker.")

        st.divider()

        # ═══════════════════════════════════════════════════════════════════
        # SECTION 6 — SENTIMENT PULSE
        # ═══════════════════════════════════════════════════════════════════
        @st.fragment
        def sentiment_section():
            st.subheader("Sentiment Pulse")

            sentiment = get_ticker_sentiment(ticker, company_name)
            score = sentiment.get("score", 0)
            label = sentiment.get("label", "No Data")
            total_h = sentiment.get("total_headlines", 0)
            relevant = sentiment.get("relevant_count", 0)
            breakdown = sentiment.get("relevance_breakdown", {})

            if total_h > 0:
                # Score display — convert to -100..+100 scale
                score_100 = round(score * 100)
                score_color = "#00C853" if score > 0.1 else "#DD2C00" if score < -0.1 else "#f39c12"
                stat_grid([
                    ("Sentiment", f"{score_100:+d}", label, score),
                    ("Headlines", str(total_h)),
                    ("Direct", f"{relevant}/{total_h}"),
                ], columns=3)

                # Top positive & negative headlines with AI summaries
                top_pos = sentiment.get("top_positive", [])[:3]
                top_neg = sentiment.get("top_negative", [])[:3]

                # Get full news items for links
                news_items = get_ticker_news(ticker)
                title_to_link = {n.get("title", ""): n.get("link", "") for n in news_items}

                if top_pos or top_neg:
                    pos_col, neg_col = st.columns(2)

                    with pos_col:
                        if top_pos:
                            st.markdown("**Positive Signals**")
                            for h in top_pos:
                                title = h.get("title", "")
                                date = h.get("date", "")
                                link = title_to_link.get(title, "")

                                # AI summary
                                skey = f"dd_pos_{hash(title)}"
                                if skey not in st.session_state:
                                    try:
                                        st.session_state[skey] = summarize_news_with_ai(title, "", ticker, company_name)
                                    except Exception:
                                        st.session_state[skey] = title

                                st.success(f"🤖 **AI Summary:** {st.session_state[skey]}")
                                caption_parts = []
                                if date:
                                    caption_parts.append(date)
                                if link:
                                    caption_parts.append(f"[Read →]({link})")
                                if caption_parts:
                                    st.caption(" · ".join(caption_parts))

                    with neg_col:
                        if top_neg:
                            st.markdown("**Negative Signals**")
                            for h in top_neg:
                                title = h.get("title", "")
                                date = h.get("date", "")
                                link = title_to_link.get(title, "")

                                skey = f"dd_neg_{hash(title)}"
                                if skey not in st.session_state:
                                    try:
                                        st.session_state[skey] = summarize_news_with_ai(title, "", ticker, company_name)
                                    except Exception:
                                        st.session_state[skey] = title

                                st.error(f"🤖 **AI Summary:** {st.session_state[skey]}")
                                caption_parts = []
                                if date:
                                    caption_parts.append(date)
                                if link:
                                    caption_parts.append(f"[Read →]({link})")
                                if caption_parts:
                                    st.caption(" · ".join(caption_parts))
            else:
                st.info("No sentiment data available. News headlines may not be available for this ticker.")

        sentiment_section()

        st.divider()

        # ═══════════════════════════════════════════════════════════════════
    except Exception as e:
        fetch_failed("this section", e)

with tab_ownership:
    try:
        @st.fragment
        def ownership_section():
            st.subheader("Ownership & Insider Activity")

            # Fetch all ownership data
            major = get_major_holders(ticker)
            inst_holders = get_institutional_holders(ticker)
            purchases = get_insider_purchases(ticker)
            transactions = get_insider_transactions(ticker)

            # Parse ownership percentages from info
            insider_pct = info.get("heldPercentInsiders")
            inst_pct = info.get("heldPercentInstitutions")

            # ── Ownership Split (metrics + pie) ──
            if insider_pct is not None or inst_pct is not None:
                ins_v = (insider_pct or 0) * 100 if insider_pct and insider_pct < 1 else (insider_pct or 0)
                inst_v = (inst_pct or 0) * 100 if inst_pct and inst_pct < 1 else (inst_pct or 0)
                retail_v = max(0, 100 - ins_v - inst_v)

                pie_col, insight_col = st.columns([2, 3])
                with pie_col:
                    fig_pie = go.Figure(go.Pie(
                        labels=["Insiders", "Institutions", "Retail/Other"],
                        values=[ins_v, inst_v, retail_v],
                        marker_colors=["#f39c12", "#1a9e5c", "#888"],
                        hole=0.5,
                        textinfo="label+percent",
                    ))
                    fig_pie.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0),
                                           template="plotly_dark", showlegend=False)
                    show_chart(fig_pie)

                with insight_col:
                    st.markdown("**Ownership Insights**")
                    insights = []
                    if inst_v > 70:
                        insights.append("Heavily institutional — price moves driven by fund flows, sensitive to earnings misses")
                    elif inst_v > 40:
                        insights.append("Moderate institutional ownership — balanced between smart money and retail")
                    elif inst_v < 15:
                        insights.append("Low institutional ownership — may indicate undiscovered name or higher risk profile")

                    if ins_v > 20:
                        insights.append("High insider ownership — management has strong skin in the game (aligned interests)")
                    elif ins_v > 5:
                        insights.append("Moderate insider ownership — management maintains meaningful stake")
                    elif ins_v < 1 and ins_v > 0:
                        insights.append("Very low insider ownership — management may not have strong alignment with shareholders")

                    if retail_v > 50:
                        insights.append("Majority retail-held — can lead to higher volatility and momentum-driven moves")

                    for insight in insights:
                        st.markdown(f"- {insight}")

                    # Insider activity trend
                    if not transactions.empty:
                        type_col = "Text" if "Text" in transactions.columns else None
                        if type_col:
                            buys = transactions[transactions[type_col].str.contains("Purchase|Buy|Acquisition", case=False, na=False)]
                            sells = transactions[transactions[type_col].str.contains("Sale|Sell|Disposition", case=False, na=False)]
                            if len(buys) > len(sells):
                                st.markdown(f"- **Insider trend: NET BUYING** ({len(buys)} buys vs {len(sells)} sells in past 12 months)")
                            elif len(sells) > len(buys):
                                st.markdown(f"- **Insider trend: NET SELLING** ({len(sells)} sells vs {len(buys)} buys in past 12 months)")
                            else:
                                st.markdown(f"- **Insider trend: BALANCED** ({len(buys)} buys, {len(sells)} sells)")

            # ── Top Institutional Holders + Recent Insider Transactions ──
            inst_tab, insider_tab = st.columns(2)

            with inst_tab:
                if not inst_holders.empty:
                    st.markdown("**Top 5 Institutional Holders**")
                    display_inst = inst_holders.head(5).copy()
                    if "Holder" in display_inst.columns:
                        cols_show = ["Holder"]
                        if "pctHeld" in display_inst.columns:
                            display_inst["Ownership"] = display_inst["pctHeld"].apply(
                                lambda x: f"{x * 100:.2f}%" if pd.notna(x) and x < 1 else (f"{x:.2f}%" if pd.notna(x) else "—")
                            )
                            cols_show.append("Ownership")
                        if "Shares" in display_inst.columns:
                            display_inst["Shares"] = display_inst["Shares"].apply(
                                lambda x: f"{x/1e6:.1f}M" if pd.notna(x) and x >= 1e6 else (f"{x:,.0f}" if pd.notna(x) else "—")
                            )
                            cols_show.append("Shares")
                        render_responsive_table(display_inst[cols_show])
                else:
                    st.caption("No institutional holder data available")

            with insider_tab:
                if not transactions.empty:
                    st.markdown("**Recent Insider Transactions**")
                    recent_txns = transactions.head(5).copy()

                    # Normalize column names across data sources
                    # yfinance uses "Insider", legacy Finnhub mapping used "Insider Trading"
                    if "Insider Trading" in recent_txns.columns and "Insider" not in recent_txns.columns:
                        recent_txns = recent_txns.rename(columns={"Insider Trading": "Insider"})

                    # Rename "Insider" to a clearer display label
                    if "Insider" in recent_txns.columns:
                        recent_txns = recent_txns.rename(columns={"Insider": "Name"})

                    # Rename "Text" to "Transaction" for clarity (only if no existing Transaction col)
                    if "Text" in recent_txns.columns and "Transaction" not in recent_txns.columns:
                        recent_txns = recent_txns.rename(columns={"Text": "Transaction"})
                    elif "Text" in recent_txns.columns:
                        recent_txns = recent_txns.drop(columns=["Text"], errors="ignore")

                    # Drop any duplicate columns
                    recent_txns = recent_txns.loc[:, ~recent_txns.columns.duplicated()]

                    # Build display columns — name, title/position, transaction type, date, shares, value
                    display_cols = []

                    # Insider name
                    if "Name" in recent_txns.columns:
                        display_cols.append("Name")

                    # Title/Position (yfinance sometimes provides this)
                    for title_col in ["Title", "Position", "Relationship"]:
                        if title_col in recent_txns.columns:
                            display_cols.append(title_col)
                            break

                    # Transaction type
                    if "Transaction" in recent_txns.columns:
                        display_cols.append("Transaction")

                    # Date
                    if "Start Date" in recent_txns.columns:
                        display_cols.append("Start Date")

                    # Shares and Value
                    if "Shares" in recent_txns.columns:
                        display_cols.append("Shares")
                    if "Value" in recent_txns.columns:
                        display_cols.append("Value")

                    # Filter to only existing, unique columns
                    display_cols = list(dict.fromkeys(c for c in display_cols if c in recent_txns.columns))
                    if display_cols:
                        render_responsive_table(clean_nan(recent_txns[display_cols]))
                    else:
                        # Fallback: show whatever columns exist
                        render_responsive_table(clean_nan(recent_txns))
                elif not purchases.empty:
                    st.markdown("**Insider Purchase Summary**")
                    render_responsive_table(purchases.head(3))
                else:
                    st.caption("No insider activity data available")

        ownership_section()

        st.divider()

        # ═══════════════════════════════════════════════════════════════════
    except Exception as e:
        fetch_failed("this section", e)

with tab_technical:
    try:
        st.subheader("Technical Signals")
        _tech_hist = get_history(ticker, "1y")
        # Fallback to longer periods if not enough data
        if _tech_hist is None or _tech_hist.empty or len(_tech_hist) < 50:
            for _fp in ["2y", "5y"]:
                _tech_hist = get_history(ticker, _fp)
                if _tech_hist is not None and not _tech_hist.empty and len(_tech_hist) >= 50:
                    break
        if _tech_hist is not None and not _tech_hist.empty and len(_tech_hist) >= 50:
            from core.yf_utils import extract_close_series
            _closes = extract_close_series(_tech_hist, ticker)
            _closes = _closes.astype(float)
            _sma50 = _closes.rolling(50).mean()
            _sma200 = _closes.rolling(200).mean() if len(_closes) >= 200 else None
            _last = _closes.iloc[-1]

            # RSI 14
            _delta = _closes.diff()
            _gain = _delta.clip(lower=0).rolling(14).mean()
            _loss = (-_delta.clip(upper=0)).rolling(14).mean()
            _rs = _gain / _loss.replace(0, float("nan"))
            _rsi = 100 - (100 / (1 + _rs))
            _rsi_val = _rsi.iloc[-1] if not _rsi.empty else None

            # Signals
            _signals = []
            _sma50_val = _sf(_sma50.iloc[-1]) if not _sma50.empty else None
            if _sma50_val is not None:
                above50 = _last > _sma50_val
                _signals.append(("SMA 50", f"{ccy} {_sma50_val:,.2f}", "Above" if above50 else "Below", "#00C853" if above50 else "#DD2C00"))
            if _sma200 is not None and not _sma200.empty:
                _sma200_val = _sf(_sma200.iloc[-1])
                if _sma200_val is not None:
                    above200 = _last > _sma200_val
                    _signals.append(("SMA 200", f"{ccy} {_sma200_val:,.2f}", "Above" if above200 else "Below", "#00C853" if above200 else "#DD2C00"))
                    if _sma50_val is not None:
                        cross = "Golden Cross" if _sma50_val > _sma200_val else "Death Cross"
                        _signals.append(("SMA Cross", cross, "", "#00C853" if "Golden" in cross else "#DD2C00"))
            _rsi_val_f = _sf(_rsi_val)
            if _rsi_val_f is not None:
                rsi_label = "Overbought" if _rsi_val_f > 70 else "Oversold" if _rsi_val_f < 30 else "Neutral"
                rsi_color = "#DD2C00" if _rsi_val_f > 70 else "#00C853" if _rsi_val_f < 30 else "#f39c12"
                _signals.append(("RSI 14", f"{_rsi_val_f:.1f}", rsi_label, rsi_color))

            # Display signal cards
            # One CSS grid rather than st.columns(4): the signal cards are the
            # densest thing on this tab and stacking them four-deep on a phone
            # buried the price chart below them. Two per row at 375px, four on
            # desktop, from the same markup.
            if _signals:
                _cards = "".join(
                    f"<div style='padding:9px 11px;border-radius:8px;"
                    f"border-left:3px solid {_scolor};background:rgba(128,128,128,0.08)'>"
                    f"<div style='font-size:0.63rem;letter-spacing:0.04em;text-transform:uppercase;"
                    f"opacity:0.6;font-weight:600'>{_sname}</div>"
                    f"<div style='font-size:1.05rem;font-weight:700;"
                    f"font-variant-numeric:tabular-nums;line-height:1.3'>{_sval}</div>"
                    f"<div style='font-size:0.75rem;font-weight:600;color:{_scolor}'>{_slabel}</div>"
                    f"</div>"
                    for _sname, _sval, _slabel, _scolor in _signals
                )
                st.markdown(
                    "<div style='display:grid;gap:8px;margin:4px 0 12px;"
                    "grid-template-columns:repeat(auto-fit,minmax(150px,1fr))'>"
                    f"{_cards}</div>",
                    unsafe_allow_html=True,
                )

            # Mini chart with overlays
            _fig_tech = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
            _fig_tech.add_trace(go.Scatter(x=_tech_hist.index, y=_closes, name="Price", line=dict(color="#1a9e5c", width=2)), row=1, col=1)
            _fig_tech.add_trace(go.Scatter(x=_tech_hist.index, y=_sma50, name="SMA 50", line=dict(color="#FFA726", width=1, dash="dash")), row=1, col=1)
            if _sma200 is not None:
                _fig_tech.add_trace(go.Scatter(x=_tech_hist.index, y=_sma200, name="SMA 200", line=dict(color="#42A5F5", width=1, dash="dot")), row=1, col=1)
            if _rsi is not None:
                _fig_tech.add_trace(go.Scatter(x=_tech_hist.index, y=_rsi, name="RSI", line=dict(color="#AB47BC", width=1.5)), row=2, col=1)
                _fig_tech.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=2, col=1)
                _fig_tech.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5, row=2, col=1)
            _fig_tech.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0), template="plotly_dark",
                                    legend=dict(orientation="h", y=1.02), yaxis2_title="RSI")
            show_chart(_fig_tech)
        else:
            st.info("Not enough price history for technical analysis (need at least 50 data points).")
        st.caption("For detailed technical analysis with MACD, Bollinger Bands, and more patterns, visit the Technical Analysis page.")
    except Exception as e:
        fetch_failed("this section", e)

with tab_ai:
    try:
        # ── Portfolio position display (if user holds this stock) ──
        if not holdings.empty:
            base_currency = SETTINGS.get("base_currency", "USD")
            enriched_key = enriched_cache_key(base_currency)
            enriched = st.session_state.get(enriched_key)

            if enriched is not None and not enriched.empty:
                t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
                match = enriched[enriched[t_col] == ticker]

                # Also check original ticker column
                if match.empty and "ticker" in enriched.columns:
                    match = enriched[enriched["ticker"] == ticker]

                if not match.empty:
                    row = match.iloc[0]
                    st.markdown("#### Your position")

                    avg = row.get("avg_cost")
                    mv  = row.get("market_value")
                    pnl = row.get("unrealized_pnl")
                    pnl_pct = row.get("unrealized_pnl_pct")
                    total_val = pd.to_numeric(enriched.get("market_value"), errors="coerce").sum()
                    weight = (float(mv) / float(total_val) * 100) if (total_val and mv) else None

                    # market_value is already converted to the user's base
                    # currency by enrich_portfolio — this one is NOT the
                    # instrument's own currency, unlike everything above.
                    hero_metric(
                        "Market value",
                        fmt_compact(mv, base_currency) if mv else "—",
                        delta=(f"{fmt_compact(pnl, base_currency)} ({pnl_pct:+.1f}%)"
                               if (pnl and pnl_pct) else ""),
                        delta_value=pnl,
                        sub=f"{row.get('quantity', 0):,.2f} shares"
                            + (f" · {weight:.1f}% of portfolio" if weight else ""),
                        title=f"{base_currency} {mv:,.2f}" if mv else "",
                    )
                    stat_grid([
                        ("Shares", f"{row.get('quantity', 0):,.2f}"),
                        ("Avg cost", f"{ccy} {avg:,.2f}" if avg else "—"),
                        ("Weight", f"{weight:.1f}%" if weight else "—"),
                    ], columns=3)

                    st.divider()

        # ═══════════════════════════════════════════════════════════════════
        # GROW v5.1 ANALYSIS — two verdicts: Durability (own?) · Entry (buy today?)
        # ═══════════════════════════════════════════════════════════════════
        analysis = get_prosper_analysis(ticker)
        if not analysis and ticker in _resolve_map.values():
            _orig = next((k for k, v in _resolve_map.items() if v == ticker), None)
            if _orig:
                analysis = get_prosper_analysis(_orig)

        if analysis:
            from core.grow_render import render_grow_analysis, is_grow
            _ccy = str((info or {}).get("currency") or "")
            render_grow_analysis(analysis, ticker, _ccy)
            _rerun_col, _ = st.columns([1, 3])
            with _rerun_col:
                _btn_label = "Run GROW" if not is_grow(analysis) else "Re-run GROW (update)"
                if st.button(_btn_label, use_container_width=True, key="dd_rerun_btn"):
                    st.session_state["_dd_force_rerun"] = True
                    st.rerun()


        # ─────────────────────────────────────────────────────────────
        # RUN ANALYSIS SECTION (no analysis exists, or force re-run)
        # ─────────────────────────────────────────────────────────────
        _force_rerun = st.session_state.pop("_dd_force_rerun", False)

        if not analysis or _force_rerun:
            if not analysis:
                st.markdown("---")
                st.markdown(
                    f'<div style="text-align:center; padding:30px; background:rgba(26,158,92,0.05); '
                    f'border:1px dashed rgba(26,158,92,0.3); border-radius:12px; margin:16px 0;">'
                    f'<div style="font-size:1.2em; font-weight:600; margin-bottom:8px;">No GROW analysis yet</div>'
                    f'<div style="color:#999;">Run GROW on <strong>{ticker}</strong> for the two verdicts: Durability (is it worth owning) '
                    f'and Entry (is it worth buying at today\'s price) with the full price ladder.</div></div>',
                    unsafe_allow_html=True,
                )

            tier_col, btn_col = st.columns([2, 1])
            with tier_col:
                run_tier = st.selectbox(
                    "Run type",
                    list(GROW_TIERS.keys()),
                    format_func=lambda t: f"{GROW_TIERS[t]['label']} — {GROW_TIERS[t]['description']}",
                    index=1,
                    key="dd_run_tier",
                )
            with btn_col:
                st.markdown("<br>", unsafe_allow_html=True)
                run_btn = st.button("Run GROW", type="primary", use_container_width=True, key="dd_run_btn")

            if run_btn:
                _wait = "this retrieves filings via web search and can take 2–5 minutes" if GROW_TIERS[run_tier]["web"] else "about 30 seconds"
                with st.spinner(f"Running {GROW_TIERS[run_tier]['label']} on **{ticker}** — {_wait}…"):
                    # Position-blind (GROW rule 13): holdings are NOT passed to the engine.
                    _prior = analysis if (analysis and str(analysis.get("framework") or "").startswith("GROW")) else None
                    _pq = None
                    try:
                        from core.database import get_price_cache as _gpc
                        _pq = (_gpc([ticker]) or {}).get(ticker)
                    except Exception:
                        pass
                    result, error = run_grow(ticker, tier=run_tier, info=info, price_quote=_pq, prior=_prior)

                if error:
                    st.error(error)
                elif result:
                    save_prosper_analysis(ticker, result)
                    st.success(
                        f"GROW complete — Durability {result.get('durability', 0):.0f}/100 · Entry {result.get('entry_verdict')} · "
                        f"buy below {result.get('buy_below') or '—'} · cost USD {result.get('cost_estimate', 0):.3f}"
                    )
                    st.rerun()
    except Exception as e:
        fetch_failed("this section", e)
