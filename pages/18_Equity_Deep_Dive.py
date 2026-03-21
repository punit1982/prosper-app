"""
Equity Deep Dive
================
Single-stock 360° research view — all data in one place.
Sections: Identity, Price, Chart, Fundamentals, Analyst, Sentiment,
          Ownership, Portfolio Position, Prosper AI (on-demand).
"""

import math
import streamlit as st
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
from core.prosper_analysis import run_analysis, MODEL_TIERS, ARCHETYPE_WEIGHTS
from core.settings import SETTINGS

st.header("Equity Deep Dive")
st.caption("Comprehensive 360° view of any stock — fundamentals, analyst consensus, sentiment, ownership, and Prosper AI analysis.")

# ─────────────────────────────────────────
# TICKER PICKER — Main Screen
# ─────────────────────────────────────────
holdings = get_all_holdings()
portfolio_tickers = sorted(holdings["ticker"].dropna().unique().tolist()) if not holdings.empty else []

# Build resolved ticker map from enriched data if available
base_currency = SETTINGS.get("base_currency", "USD")
_enriched_cache = st.session_state.get(f"enriched_{base_currency}")
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

c1, c2, c3, c4 = st.columns(4)

with c1:
    if price:
        delta_str = f"{day_change:+.2f} ({day_pct:+.1f}%)" if day_change is not None else None
        st.metric("Price", f"${price:,.2f}", delta=delta_str)

with c2:
    if mcap:
        st.metric("Market Cap", fmt_large(mcap))

with c3:
    if hi52 and lo52 and price:
        range_span = hi52 - lo52
        if range_span > 0:
            position = (price - lo52) / range_span
            pct = max(0, min(100, position * 100))
            color = "#00C853" if pct > 60 else "#f39c12" if pct > 30 else "#DD2C00"
            st.caption("52-Week Range")
            st.markdown(
                f'<div style="display:flex; align-items:center; gap:8px;">'
                f'<span style="font-size:12px;">${lo52:,.0f}</span>'
                f'<div style="flex:1; background:#333; border-radius:4px; height:8px; position:relative;">'
                f'<div style="background:{color}; height:8px; border-radius:4px; width:{pct:.0f}%;"></div>'
                f'</div>'
                f'<span style="font-size:12px;">${hi52:,.0f}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

with c4:
    pe_parts = []
    if pe:
        pe_parts.append(f"P/E: {pe:.1f}")
    if fwd_pe:
        pe_parts.append(f"Fwd: {fwd_pe:.1f}")
    if pe_parts:
        st.metric("P/E Ratio", pe_parts[0].split(": ")[1] if pe else "—")
        if len(pe_parts) > 1:
            st.caption(pe_parts[1])

st.divider()

# ═══════════════════════════════════════════════════════════════════
# TABBED LAYOUT
# ═══════════════════════════════════════════════════════════════════
tab_chart, tab_fundamentals, tab_analyst, tab_ownership, tab_technical, tab_ai = st.tabs([
    "Price & Chart", "Fundamentals", "Analyst & Sentiment",
    "Ownership", "Technical Signals", "Prosper AI",
])

# ═══════════════════════════════════════════════════════════════════
# TAB 1 — PRICE CHART (wrapped in container for tab context)
# ═══════════════════════════════════════════════════════════════════
with tab_chart:
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
        st.plotly_chart(fig, use_container_width=True)
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
        _d1, _d2, _d3, _d4 = st.columns(4)
        with _d1:
            st.metric("Dividend/Share", f"${_div_rate:.2f}" if _div_rate else "---", key=f"div_rate_{ticker}")
        with _d2:
            _dy = _div_yield * 100 if _div_yield and _div_yield < 1 else _div_yield
            st.metric("Dividend Yield", f"{_dy:.2f}%" if _dy else "---", key=f"div_yield_{ticker}")
        with _d3:
            if _ex_date:
                try:
                    from datetime import datetime as _dt
                    _ed = _dt.fromtimestamp(_ex_date).strftime("%b %d, %Y")
                    st.metric("Ex-Dividend Date", _ed, key=f"div_exdate_{ticker}")
                except Exception:
                    st.metric("Ex-Dividend Date", "---", key=f"div_exdate_{ticker}")
            else:
                st.metric("Ex-Dividend Date", "---", key=f"div_exdate_{ticker}")
        with _d4:
            st.metric("Payout Ratio", f"{_payout*100:.0f}%" if _payout else "---", key=f"div_payout_{ticker}")

with tab_fundamentals:
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

with tab_analyst:
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
            st.plotly_chart(fig_gauge, use_container_width=True)

        with info_col:
            upside = ((target_mean - price) / price * 100) if target_mean and price else None
            st.metric("Consensus", consensus or "—")
            st.metric("Mean Target", f"${target_mean:,.2f}" if target_mean else "—",
                      delta=f"{upside:+.1f}% upside" if upside else None)
            if target_low and target_high:
                st.caption(f"Range: ${target_low:,.2f} — ${target_high:,.2f}")

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
                st.dataframe(pd.DataFrame(ud_rows), use_container_width=True, hide_index=True)
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
            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                st.metric("Sentiment Score", f"{score_100:+d}", delta=label)
            with sc2:
                st.metric("Headlines Analyzed", str(total_h))
            with sc3:
                st.metric("Direct/Related", f"{relevant} of {total_h}")

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

with tab_ownership:
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
                st.plotly_chart(fig_pie, use_container_width=True)

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
                    st.dataframe(display_inst[cols_show], use_container_width=True, hide_index=True)
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

                # Rename "Text" to "Transaction" for clarity
                if "Text" in recent_txns.columns:
                    recent_txns = recent_txns.rename(columns={"Text": "Transaction"})

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

                if display_cols:
                    st.dataframe(clean_nan(recent_txns[display_cols]), use_container_width=True, hide_index=True)
                else:
                    # Fallback: show whatever columns exist
                    st.dataframe(clean_nan(recent_txns), use_container_width=True, hide_index=True)
            elif not purchases.empty:
                st.markdown("**Insider Purchase Summary**")
                st.dataframe(purchases.head(3), use_container_width=True, hide_index=True)
            else:
                st.caption("No insider activity data available")

    ownership_section()

    st.divider()

    # ═══════════════════════════════════════════════════════════════════

with tab_technical:
    st.subheader("Technical Signals")
    _tech_hist = get_history(ticker, "1y")
    if _tech_hist is not None and not _tech_hist.empty and len(_tech_hist) >= 50:
        _tc = "Close" if "Close" in _tech_hist.columns else _tech_hist.columns[0]
        _closes = _tech_hist[_tc].astype(float)
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
        _sma50_val = _sma50.iloc[-1] if not _sma50.empty else None
        if _sma50_val:
            above50 = _last > _sma50_val
            _signals.append(("SMA 50", f"${_sma50_val:,.2f}", "Above" if above50 else "Below", "#00C853" if above50 else "#DD2C00"))
        if _sma200 is not None and not _sma200.empty:
            _sma200_val = _sma200.iloc[-1]
            if pd.notna(_sma200_val):
                above200 = _last > _sma200_val
                _signals.append(("SMA 200", f"${_sma200_val:,.2f}", "Above" if above200 else "Below", "#00C853" if above200 else "#DD2C00"))
                if _sma50_val and pd.notna(_sma50_val):
                    cross = "Golden Cross" if _sma50_val > _sma200_val else "Death Cross"
                    _signals.append(("SMA Cross", cross, "", "#00C853" if "Golden" in cross else "#DD2C00"))
        if _rsi_val and pd.notna(_rsi_val):
            rsi_label = "Overbought" if _rsi_val > 70 else "Oversold" if _rsi_val < 30 else "Neutral"
            rsi_color = "#DD2C00" if _rsi_val > 70 else "#00C853" if _rsi_val < 30 else "#f39c12"
            _signals.append(("RSI 14", f"{_rsi_val:.1f}", rsi_label, rsi_color))

        # Display signal cards
        _sig_cols = st.columns(min(len(_signals), 4)) if _signals else []
        for _si, (_sname, _sval, _slabel, _scolor) in enumerate(_signals):
            with _sig_cols[_si % len(_sig_cols)]:
                st.markdown(
                    f"<div style='padding:10px;border-radius:8px;border-left:4px solid {_scolor};"
                    f"background:rgba(255,255,255,0.03);margin-bottom:8px'>"
                    f"<div style='font-size:0.8rem;color:#999'>{_sname}</div>"
                    f"<div style='font-size:1.1rem;font-weight:700'>{_sval}</div>"
                    f"<div style='font-size:0.85rem;color:{_scolor}'>{_slabel}</div></div>",
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
        st.plotly_chart(_fig_tech, use_container_width=True)
    else:
        st.info("Not enough price history for technical analysis (need at least 50 data points).")
    st.caption("For detailed technical analysis with MACD, Bollinger Bands, and more patterns, visit the Technical Analysis page.")

with tab_ai:
    # ── Portfolio position display (if user holds this stock) ──
    if not holdings.empty:
        base_currency = SETTINGS.get("base_currency", "USD")
        enriched_key = f"enriched_{base_currency}"
        enriched = st.session_state.get(enriched_key)

        if enriched is not None and not enriched.empty:
            t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
            match = enriched[enriched[t_col] == ticker]

            # Also check original ticker column
            if match.empty and "ticker" in enriched.columns:
                match = enriched[enriched["ticker"] == ticker]

            if not match.empty:
                row = match.iloc[0]
                st.subheader("Your Position")

                p1, p2, p3, p4, p5 = st.columns(5)
                with p1:
                    st.metric("Shares", f"{row.get('quantity', 0):,.2f}")
                with p2:
                    avg = row.get("avg_cost")
                    st.metric("Avg Cost", f"${avg:,.2f}" if avg else "—")
                with p3:
                    mv = row.get("market_value")
                    st.metric("Market Value", fmt_large(mv) if mv else "—")
                with p4:
                    pnl = row.get("unrealized_pnl")
                    pnl_pct = row.get("unrealized_pnl_pct")
                    delta_str = f"{pnl_pct:+.1f}%" if pnl_pct else None
                    st.metric("Unrealized P&L", fmt_large(pnl) if pnl else "—", delta=delta_str)
                with p5:
                    # Portfolio weight
                    total_val = pd.to_numeric(enriched.get("market_value"), errors="coerce").sum()
                    if total_val and mv:
                        weight = (float(mv) / float(total_val)) * 100
                        st.metric("Portfolio Weight", f"{weight:.1f}%")

                st.divider()

    # ═══════════════════════════════════════════════════════════════════
    # PROSPER AI ANALYSIS — Full Framework Display
    # ═══════════════════════════════════════════════════════════════════

    # Also check original ticker for saved analysis
    analysis = get_prosper_analysis(ticker)
    if not analysis and ticker in _resolve_map.values():
        _orig = next((k for k, v in _resolve_map.items() if v == ticker), None)
        if _orig:
            analysis = get_prosper_analysis(_orig)

    if analysis:
        # ── Analysis age + staleness warning ──
        _analysis_date = analysis.get("analysis_date") or analysis.get("updated_at", "")
        _days_old = None
        if _analysis_date:
            try:
                _ad = pd.to_datetime(_analysis_date)
                _days_old = (pd.Timestamp.now() - _ad).days
            except Exception:
                pass
        if _days_old is not None and _days_old > 30:
            st.warning(f"This analysis is **{_days_old} days old**. Consider re-running for up-to-date insights.")

        # ── Data quality warning banner ──
        _dq_warning = analysis.get("data_quality_warning")
        if _dq_warning == "INSUFFICIENT":
            st.warning("**Insufficient data** — Not enough data points available to generate a reliable analysis for this stock.")
        elif _dq_warning == "LOW":
            st.warning("**Low confidence analysis** — Limited data sources available. Results should be interpreted with caution.")

        # ── Extract all analysis fields ──
        rating = analysis.get("rating", "N/A")
        ai_score = analysis.get("score", 0)
        arch = analysis.get("archetype", "")
        arch_name = analysis.get("archetype_name", "")
        conviction = analysis.get("conviction", "N/A")
        thesis = analysis.get("thesis", "")
        env_net = analysis.get("env_net", "")
        full_resp = analysis.get("full_response", {})
        if isinstance(full_resp, str):
            try:
                import json as _json
                full_resp = _json.loads(full_resp)
            except Exception:
                full_resp = {}

        fv = full_resp.get("fair_value", {})
        if not fv or not isinstance(fv, dict):
            fv = {
                "bear": analysis.get("fair_value_bear"),
                "base": analysis.get("fair_value_base"),
                "bull": analysis.get("fair_value_bull"),
            }

        scores = analysis.get("score_breakdown")
        if not scores or not isinstance(scores, dict):
            scores = full_resp.get("scores", {})

        risks = analysis.get("key_risks")
        if not risks or not isinstance(risks, list):
            risks = full_resp.get("risks", [])

        catalysts = analysis.get("key_catalysts")
        if not catalysts or not isinstance(catalysts, list):
            catalysts = full_resp.get("catalysts", [])

        data_sources = analysis.get("data_sources", [])
        if isinstance(data_sources, str):
            try:
                import json as _json
                data_sources = _json.loads(data_sources)
            except Exception:
                data_sources = [data_sources]

        tier_used = analysis.get("model_used", "")
        cost = analysis.get("cost_estimate", 0)
        upside_pct = analysis.get("upside_pct")

        # ─────────────────────────────────────────────────────────────
        # SECTION 1: HEADER CARD — Rating badge, score, conviction, archetype
        # ─────────────────────────────────────────────────────────────
        _rating_color = _RATING_COLORS.get(rating, "#888")
        _score_color = "#00C853" if ai_score >= 80 else "#1a9e5c" if ai_score >= 65 else "#f39c12" if ai_score >= 50 else "#FF6D00" if ai_score >= 35 else "#DD2C00"
        _conv_color = {"HIGH": "#00C853", "MEDIUM": "#f39c12", "LOW": "#FF6D00"}.get(conviction, "#888")

        st.markdown(
            f'<div style="background:linear-gradient(135deg, rgba(26,158,92,0.08), rgba(26,158,92,0.02)); '
            f'border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:20px 24px; margin-bottom:16px;">'
            f'<div style="display:flex; align-items:center; flex-wrap:wrap; gap:20px;">'
            # Rating badge
            f'<div style="text-align:center;">'
            f'<div style="background:{_rating_color}; color:white; padding:10px 24px; border-radius:8px; '
            f'font-weight:800; font-size:1.5em; letter-spacing:0.5px;">{rating}</div>'
            f'<div style="color:#999; font-size:0.75em; margin-top:4px;">PROSPER Rating</div></div>'
            # Score
            f'<div style="text-align:center; min-width:100px;">'
            f'<div style="font-size:2.2em; font-weight:800; color:{_score_color};">{ai_score:.0f}</div>'
            f'<div style="background:#333; border-radius:4px; height:6px; width:100px; margin:4px auto;">'
            f'<div style="background:{_score_color}; height:6px; border-radius:4px; width:{min(ai_score, 100):.0f}%;"></div></div>'
            f'<div style="color:#999; font-size:0.75em;">Score / 100</div></div>'
            # Archetype
            f'<div style="text-align:center; flex:1;">'
            f'<div style="font-size:1.1em; font-weight:600;">{arch}: {arch_name}</div>'
            f'<div style="color:#999; font-size:0.75em;">Archetype</div></div>'
            # Conviction
            f'<div style="text-align:center;">'
            f'<div style="font-size:1.3em; font-weight:700; color:{_conv_color};">{conviction}</div>'
            f'<div style="background:{_conv_color}; height:3px; border-radius:2px; width:60px; margin:4px auto;"></div>'
            f'<div style="color:#999; font-size:0.75em;">Conviction</div></div>'
            f'</div>'
            f'<div style="color:#777; font-size:0.8em; margin-top:10px;">Analyzed: {analysis.get("analysis_date", "N/A")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ─────────────────────────────────────────────────────────────
        # SECTION 2: ENVIRONMENTAL SCAN
        # ─────────────────────────────────────────────────────────────
        if env_net:
            _env_colors = {"NET POSITIVE": "#00C853", "NET NEGATIVE": "#DD2C00", "NEUTRAL": "#f39c12"}
            _env_icons = {"NET POSITIVE": "+", "NET NEGATIVE": "-", "NEUTRAL": "~"}
            _env_color = _env_colors.get(env_net, "#888")
            _env_icon = _env_icons.get(env_net, "?")
            _env_descriptions = {
                "NET POSITIVE": "Macro, regulatory, and industry conditions are broadly favorable for this stock. Tailwinds outweigh headwinds.",
                "NET NEGATIVE": "Macro, regulatory, or industry conditions present significant headwinds. Caution warranted.",
                "NEUTRAL": "Macro and industry conditions are mixed. No strong directional bias from external environment.",
            }
            _env_desc = _env_descriptions.get(env_net, "Environmental assessment based on macro, geopolitical, regulatory, tech disruption, industry cycle, and thematic factors.")

            st.markdown(
                f'<div style="border-left:4px solid {_env_color}; padding:12px 16px; margin:8px 0 16px 0; '
                f'background:rgba(255,255,255,0.02); border-radius:0 8px 8px 0;">'
                f'<div style="font-weight:700; font-size:1em; margin-bottom:4px;">'
                f'Environmental Scan: <span style="color:{_env_color};">{env_net}</span></div>'
                f'<div style="color:#aaa; font-size:0.9em;">{_env_desc}</div></div>',
                unsafe_allow_html=True,
            )

        # ─────────────────────────────────────────────────────────────
        # SECTION 3: INVESTMENT THESIS
        # ─────────────────────────────────────────────────────────────
        if thesis:
            thesis_safe = thesis.replace("$", "\\$")
            st.markdown(
                f'<div style="background:rgba(26,158,92,0.06); border:1px solid rgba(26,158,92,0.15); '
                f'border-radius:10px; padding:16px 20px; margin:8px 0 16px 0;">'
                f'<div style="font-weight:700; font-size:0.85em; color:#1a9e5c; margin-bottom:6px; text-transform:uppercase; letter-spacing:1px;">Investment Thesis</div>'
                f'<div style="font-size:1.05em; line-height:1.6;">{thesis_safe}</div></div>',
                unsafe_allow_html=True,
            )

        # ─────────────────────────────────────────────────────────────
        # SECTION 4: ARCHETYPE CLASSIFICATION
        # ─────────────────────────────────────────────────────────────
        if arch:
            _archetype_descriptions = {
                "A": "Mature, cash-generative businesses with durable competitive advantages. Emphasis on margin stability, moat durability, and capital allocation discipline.",
                "B": "High-growth platforms with network effects or marketplace dynamics. Revenue growth and TAM expansion are primary drivers, with path to profitability as secondary factor.",
                "C": "Early-stage companies with breakthrough potential but limited revenue. Evaluation centers on IP strength, execution capability, and risk-adjusted upside potential.",
                "D": "Clinical-stage biotech or pharma companies. Pipeline IP and balance sheet runway are critical; traditional revenue metrics are less relevant.",
                "E": "Companies tied to commodity cycles or economic cycles. Balance sheet resilience and valuation discipline are key, with timing of cycle turns as the primary catalyst.",
                "F": "Distressed or underperforming companies with restructuring potential. Execution of the turnaround plan and balance sheet repair are the primary focus areas.",
                "G": "High-growth companies with elevated volatility. Revenue growth trajectory and risk-adjusted upside potential are heavily weighted, with valuation as a secondary concern.",
                "H": "Deep technology or frontier science companies (AI, quantum, space, etc.). IP moat and long-term vision are paramount; near-term financials are less indicative of value.",
            }
            with st.expander(f"Archetype: {arch} - {arch_name}", expanded=False):
                _arch_desc = _archetype_descriptions.get(arch, "Custom archetype classification.")
                st.markdown(f"**{arch_name}** (Category {arch})")
                st.markdown(f"*{_arch_desc}*")

                # Show archetype-specific weights
                _arch_weights = ARCHETYPE_WEIGHTS.get(arch, {}).get("weights", {})
                if _arch_weights:
                    st.markdown("**Scoring Weights for this Archetype:**")
                    _weight_labels = {
                        "revenue_growth": "Revenue Growth", "margins": "Margins",
                        "moat_ip": "Moat / IP", "balance_sheet": "Balance Sheet",
                        "valuation": "Valuation", "execution": "Execution",
                        "risk_adj_upside": "Risk-Adj Upside",
                    }
                    _sorted_weights = sorted(_arch_weights.items(), key=lambda x: x[1], reverse=True)
                    for _wk, _wv in _sorted_weights:
                        _wlabel = _weight_labels.get(_wk, _wk.replace("_", " ").title())
                        _bar_w = _wv * 3  # scale for visual
                        st.markdown(
                            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
                            f'<span style="min-width:130px;font-size:0.85em;">{_wlabel}</span>'
                            f'<div style="flex:1;background:#333;border-radius:3px;height:14px;">'
                            f'<div style="background:#1a9e5c;height:14px;border-radius:3px;width:{_bar_w}%;'
                            f'display:flex;align-items:center;justify-content:center;">'
                            f'<span style="font-size:0.7em;color:white;font-weight:600;">{_wv}%</span></div></div></div>',
                            unsafe_allow_html=True,
                        )

        # ─────────────────────────────────────────────────────────────
        # SECTION 5: SCORE BREAKDOWN — Radar chart + bars
        # ─────────────────────────────────────────────────────────────
        if scores and isinstance(scores, dict):
            st.markdown("---")
            st.markdown("#### Score Breakdown")

            _score_labels_map = {
                "revenue_growth": "Revenue Growth", "margins": "Margins",
                "moat_ip": "Moat / IP", "balance_sheet": "Balance Sheet",
                "valuation": "Valuation", "execution": "Execution",
                "risk_adj_upside": "Risk-Adj Upside",
            }
            _dim_order = ["revenue_growth", "margins", "moat_ip", "balance_sheet", "valuation", "execution", "risk_adj_upside"]
            _radar_labels = [_score_labels_map.get(d, d) for d in _dim_order]
            _radar_values = [scores.get(d, 0) for d in _dim_order]

            arch_key = analysis.get("archetype", "A")
            weights = ARCHETYPE_WEIGHTS.get(arch_key, {}).get("weights", {})

            radar_col, bars_col = st.columns([1, 1])

            with radar_col:
                # Radar / spider chart
                _rv_closed = _radar_values + [_radar_values[0]]
                _rl_closed = _radar_labels + [_radar_labels[0]]

                fig_radar = go.Figure()
                fig_radar.add_trace(go.Scatterpolar(
                    r=_rv_closed,
                    theta=_rl_closed,
                    fill="toself",
                    fillcolor="rgba(26,158,92,0.15)",
                    line=dict(color="#1a9e5c", width=2),
                    name="Score",
                ))
                fig_radar.update_layout(
                    polar=dict(
                        radialaxis=dict(visible=True, range=[0, 10], tickvals=[2, 4, 6, 8, 10],
                                        gridcolor="rgba(255,255,255,0.1)"),
                        angularaxis=dict(gridcolor="rgba(255,255,255,0.1)"),
                        bgcolor="rgba(0,0,0,0)",
                    ),
                    height=340,
                    margin=dict(l=60, r=60, t=30, b=30),
                    template="plotly_dark",
                    showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_radar, use_container_width=True)

            with bars_col:
                # Individual score bars with weights and data context
                _factor_context = {}
                rev_g = info.get("revenueGrowth")
                earn_g = info.get("earningsGrowth")
                if rev_g is not None:
                    _pct_rg = rev_g * 100 if abs(rev_g) < 1 else rev_g
                    _factor_context["revenue_growth"] = f"Rev: {_pct_rg:+.1f}%" + (f", Earn: {earn_g*100:+.1f}%" if earn_g else "")
                pm = info.get("profitMargins")
                om = info.get("operatingMargins")
                if pm is not None:
                    _factor_context["margins"] = f"Profit: {pm*100:.1f}%" + (f", Op: {om*100:.1f}%" if om else "")
                if info.get("debtToEquity") is not None or info.get("currentRatio") is not None:
                    _bs_parts = []
                    if info.get("debtToEquity") is not None:
                        _bs_parts.append(f"D/E: {info['debtToEquity']:.1f}")
                    if info.get("currentRatio") is not None:
                        _bs_parts.append(f"CR: {info['currentRatio']:.1f}")
                    _factor_context["balance_sheet"] = ", ".join(_bs_parts)
                _pe_v = info.get("trailingPE")
                _fwd_pe_v = info.get("forwardPE")
                if _pe_v is not None:
                    _factor_context["valuation"] = f"P/E: {_pe_v:.1f}" + (f", Fwd: {_fwd_pe_v:.1f}" if _fwd_pe_v else "")
                _roe_v = info.get("returnOnEquity")
                if _roe_v is not None:
                    _factor_context["execution"] = f"ROE: {_roe_v*100:.1f}%"

                for _dim in _dim_order:
                    s = scores.get(_dim, 0)
                    w = weights.get(_dim, 0)
                    weighted = s * w / 10
                    s_color = "#00C853" if s >= 8 else "#1a9e5c" if s >= 6 else "#f39c12" if s >= 5 else "#FF6D00" if s >= 3 else "#DD2C00"
                    _dlabel = _score_labels_map.get(_dim, _dim)
                    _ctx = _factor_context.get(_dim, "")

                    st.markdown(
                        f'<div style="margin-bottom:6px;">'
                        f'<div style="display:flex;justify-content:space-between;align-items:baseline;">'
                        f'<span style="font-size:0.85em;font-weight:600;">{_dlabel}</span>'
                        f'<span style="font-size:0.8em;color:#aaa;">{s}/10 (wt:{w}%, +{weighted:.1f})</span></div>'
                        + (f'<div style="font-size:0.72em;color:#777;margin-bottom:2px;">{_ctx}</div>' if _ctx else '')
                        + f'<div style="background:#333;border-radius:3px;height:8px;">'
                        f'<div style="background:{s_color};height:8px;border-radius:3px;width:{s*10}%;"></div></div></div>',
                        unsafe_allow_html=True,
                    )

        # ─────────────────────────────────────────────────────────────
        # SECTION 6: FAIR VALUE ANALYSIS — Visual chart + probabilities
        # ─────────────────────────────────────────────────────────────
        if fv and fv.get("base"):
            st.markdown("---")
            st.markdown("#### Fair Value Analysis")

            _bear = fv.get("bear", 0) or 0
            _base = fv.get("base", 0) or 0
            _bull = fv.get("bull", 0) or 0
            _p_bear = fv.get("prob_bear", 0) or 0
            _p_base = fv.get("prob_base", 0) or 0
            _p_bull = fv.get("prob_bull", 0) or 0
            _current = price or 0

            # Probability-weighted fair value
            _pw_fv = (_bear * _p_bear + _base * _p_base + _bull * _p_bull) / 100 if (_p_bear + _p_base + _p_bull) > 0 else _base

            fv_chart_col, fv_metrics_col = st.columns([3, 2])

            with fv_chart_col:
                # Horizontal bar chart showing bear/base/bull ranges
                fig_fv = go.Figure()

                # Background range bar (bear to bull)
                fig_fv.add_trace(go.Bar(
                    y=["Fair Value"], x=[_bull - _bear], base=_bear,
                    orientation="h", marker_color="rgba(26,158,92,0.12)",
                    showlegend=False, hoverinfo="skip",
                ))

                # Bear marker
                fig_fv.add_trace(go.Scatter(
                    x=[_bear], y=["Fair Value"], mode="markers+text",
                    marker=dict(size=14, color="#DD2C00", symbol="diamond"),
                    text=[f"Bear<br>${_bear:,.0f}"], textposition="bottom center",
                    textfont=dict(size=10, color="#DD2C00"),
                    name=f"Bear (${_bear:,.2f})", showlegend=False,
                ))

                # Base marker
                fig_fv.add_trace(go.Scatter(
                    x=[_base], y=["Fair Value"], mode="markers+text",
                    marker=dict(size=18, color="#1a9e5c", symbol="diamond"),
                    text=[f"Base<br>${_base:,.0f}"], textposition="top center",
                    textfont=dict(size=11, color="#1a9e5c"),
                    name=f"Base (${_base:,.2f})", showlegend=False,
                ))

                # Bull marker
                fig_fv.add_trace(go.Scatter(
                    x=[_bull], y=["Fair Value"], mode="markers+text",
                    marker=dict(size=14, color="#00C853", symbol="diamond"),
                    text=[f"Bull<br>${_bull:,.0f}"], textposition="bottom center",
                    textfont=dict(size=10, color="#00C853"),
                    name=f"Bull (${_bull:,.2f})", showlegend=False,
                ))

                # Current price line
                if _current > 0:
                    fig_fv.add_vline(x=_current, line_dash="dash", line_color="white", line_width=2,
                                     annotation_text=f"Current: ${_current:,.0f}",
                                     annotation_position="top right",
                                     annotation_font_color="white")

                # Probability-weighted FV line
                if _pw_fv > 0:
                    fig_fv.add_vline(x=_pw_fv, line_dash="dot", line_color="#f39c12", line_width=1.5,
                                     annotation_text=f"PW FV: ${_pw_fv:,.0f}",
                                     annotation_position="bottom right",
                                     annotation_font_color="#f39c12")

                _range_min = min(_bear, _current) * 0.9 if _current > 0 else _bear * 0.9
                _range_max = max(_bull, _current) * 1.1 if _current > 0 else _bull * 1.1
                fig_fv.update_layout(
                    height=160, margin=dict(l=0, r=0, t=30, b=40),
                    template="plotly_dark",
                    xaxis=dict(range=[_range_min, _range_max], title="Price"),
                    yaxis=dict(visible=False),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_fv, use_container_width=True)

            with fv_metrics_col:
                # Metrics cards
                _m1, _m2, _m3 = st.columns(3)
                with _m1:
                    _bear_upside = ((_bear - _current) / _current * 100) if _current > 0 else None
                    st.metric("Bear Case", f"${_bear:,.2f}",
                              delta=f"{_bear_upside:+.1f}%" if _bear_upside is not None else None,
                              help=f"{_p_bear}% probability")
                with _m2:
                    _base_upside = ((_base - _current) / _current * 100) if _current > 0 else None
                    st.metric("Base Case", f"${_base:,.2f}",
                              delta=f"{_base_upside:+.1f}%" if _base_upside is not None else None,
                              help=f"{_p_base}% probability")
                with _m3:
                    _bull_upside = ((_bull - _current) / _current * 100) if _current > 0 else None
                    st.metric("Bull Case", f"${_bull:,.2f}",
                              delta=f"{_bull_upside:+.1f}%" if _bull_upside is not None else None,
                              help=f"{_p_bull}% probability")

                # Probability distribution bar
                if _p_bear + _p_base + _p_bull > 0:
                    st.markdown(
                        f'<div style="margin-top:8px;">'
                        f'<div style="font-size:0.8em;color:#999;margin-bottom:4px;">Probability Distribution</div>'
                        f'<div style="display:flex;height:20px;border-radius:4px;overflow:hidden;">'
                        f'<div style="width:{_p_bear}%;background:#DD2C00;display:flex;align-items:center;justify-content:center;">'
                        f'<span style="font-size:0.7em;color:white;">{_p_bear}%</span></div>'
                        f'<div style="width:{_p_base}%;background:#1a9e5c;display:flex;align-items:center;justify-content:center;">'
                        f'<span style="font-size:0.7em;color:white;">{_p_base}%</span></div>'
                        f'<div style="width:{_p_bull}%;background:#00C853;display:flex;align-items:center;justify-content:center;">'
                        f'<span style="font-size:0.7em;color:white;">{_p_bull}%</span></div>'
                        f'</div>'
                        f'<div style="display:flex;justify-content:space-between;font-size:0.7em;color:#777;margin-top:2px;">'
                        f'<span>Bear</span><span>Base</span><span>Bull</span></div></div>',
                        unsafe_allow_html=True,
                    )

                # Probability-weighted FV + overall upside
                if _pw_fv > 0 and _current > 0:
                    _overall_upside = ((_pw_fv - _current) / _current) * 100
                    st.metric("Prob-Weighted FV", f"${_pw_fv:,.2f}",
                              delta=f"{_overall_upside:+.1f}% upside" if _overall_upside else None)

        # ─────────────────────────────────────────────────────────────
        # SECTION 7: RISK FACTORS
        # ─────────────────────────────────────────────────────────────
        if risks and isinstance(risks, list):
            st.markdown("---")
            st.markdown("#### Risk Factors")
            for _ri, _risk in enumerate(risks):
                _risk_safe = str(_risk).replace("$", "\\$")
                # Assign severity color based on position (first = highest)
                _sev_colors = ["#DD2C00", "#FF6D00", "#f39c12", "#f39c12", "#888"]
                _sev_labels = ["HIGH", "HIGH", "MEDIUM", "MEDIUM", "LOW"]
                _sc = _sev_colors[min(_ri, len(_sev_colors) - 1)]
                _sl = _sev_labels[min(_ri, len(_sev_labels) - 1)]
                st.markdown(
                    f'<div style="border-left:3px solid {_sc}; padding:6px 12px; margin-bottom:6px; '
                    f'background:rgba(255,255,255,0.02); border-radius:0 6px 6px 0;">'
                    f'<span style="font-size:0.7em; font-weight:700; color:{_sc}; margin-right:8px;">{_sl}</span>'
                    f'<span style="font-size:0.9em;">{_risk_safe}</span></div>',
                    unsafe_allow_html=True,
                )

        # ─────────────────────────────────────────────────────────────
        # SECTION 8: CATALYSTS
        # ─────────────────────────────────────────────────────────────
        if catalysts and isinstance(catalysts, list):
            st.markdown("---")
            st.markdown("#### Catalysts")
            for _ci, _cat in enumerate(catalysts):
                _cat_safe = str(_cat).replace("$", "\\$")
                st.markdown(
                    f'<div style="border-left:3px solid #1a9e5c; padding:6px 12px; margin-bottom:6px; '
                    f'background:rgba(26,158,92,0.04); border-radius:0 6px 6px 0;">'
                    f'<span style="font-size:0.9em;">{_cat_safe}</span></div>',
                    unsafe_allow_html=True,
                )

        # ─────────────────────────────────────────────────────────────
        # SECTION 9: DATA QUALITY & SOURCES
        # ─────────────────────────────────────────────────────────────
        with st.expander("Data Quality & Sources", expanded=False):
            _dq = analysis.get("data_quality_warning")
            _dq_color = {"HIGH": "#DD2C00", "MEDIUM": "#f39c12", "LOW": "#FF6D00", "INSUFFICIENT": "#DD2C00"}.get(_dq or "", "#00C853")
            _dq_label = _dq if _dq else "GOOD"

            dq1, dq2 = st.columns([1, 2])
            with dq1:
                st.markdown(f"**Data Confidence:** <span style='color:{_dq_color};font-weight:700;'>{_dq_label}</span>",
                            unsafe_allow_html=True)
                st.markdown(f"**Analysis Tier:** {tier_used.title() if tier_used else 'N/A'}")
                st.markdown(f"**Cost:** ${cost:.4f}" if cost else "**Cost:** N/A")
                if _analysis_date:
                    st.markdown(f"**Analysis Date:** {_analysis_date[:10]}")
                if _days_old is not None:
                    st.markdown(f"**Age:** {_days_old} day{'s' if _days_old != 1 else ''}")

            with dq2:
                if data_sources:
                    st.markdown("**Data Sources Used:**")
                    for _src in data_sources:
                        _src_icons = {
                            "yfinance": "Yahoo Finance (fundamentals, price, ratios)",
                            "Finnhub": "Finnhub (analyst consensus, upgrades/downgrades)",
                            "Serper": "Serper/Google (web search context, recent analysis)",
                            "Google News": "Google News (headline sentiment, breaking news)",
                            "Portfolio": "Portfolio (user holdings data)",
                        }
                        _desc = _src_icons.get(_src, _src)
                        st.markdown(f"- **{_src}** — {_desc}")
                else:
                    st.caption("No source information recorded for this analysis.")

                # Model info
                _full_resp_meta = full_resp
                _input_tok = _full_resp_meta.get("input_tokens") or analysis.get("input_tokens")
                _output_tok = _full_resp_meta.get("output_tokens") or analysis.get("output_tokens")
                _elapsed = _full_resp_meta.get("elapsed_seconds") or analysis.get("elapsed_seconds")
                _meta_parts = []
                if _input_tok:
                    _meta_parts.append(f"Input: {_input_tok:,} tokens")
                if _output_tok:
                    _meta_parts.append(f"Output: {_output_tok:,} tokens")
                if _elapsed:
                    _meta_parts.append(f"Elapsed: {_elapsed}s")
                if _meta_parts:
                    st.caption(" | ".join(_meta_parts))

        # ─────────────────────────────────────────────────────────────
        # SECTION 14: ACTION SUMMARY — Clear recommendation + sizing
        # ─────────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### Action Summary")

        _action_bg = {
            "STRONG BUY": "rgba(0,200,83,0.08)", "BUY": "rgba(26,158,92,0.08)",
            "HOLD": "rgba(243,156,18,0.08)", "SELL": "rgba(255,109,0,0.08)",
            "STRONG SELL": "rgba(221,44,0,0.08)",
        }
        _action_border = {
            "STRONG BUY": "#00C853", "BUY": "#1a9e5c",
            "HOLD": "#f39c12", "SELL": "#FF6D00", "STRONG SELL": "#DD2C00",
        }
        _action_guidance = {
            "STRONG BUY": "Strong conviction to accumulate. Consider building a full position (3-5% of portfolio). Dollar-cost average on any pullbacks.",
            "BUY": "Favorable risk/reward. Consider initiating or adding to position (2-4% of portfolio). Set a target entry zone near the base case.",
            "HOLD": "Maintain current position. Risk/reward is balanced at current levels. Monitor for catalyst-driven re-rating opportunities.",
            "SELL": "Consider reducing position. Risk/reward has deteriorated. Trim to reduce exposure while monitoring for potential turnaround.",
            "STRONG SELL": "High conviction to exit. Consider closing position entirely. Downside risks outweigh potential upside significantly.",
        }

        _ab = _action_bg.get(rating, "rgba(128,128,128,0.08)")
        _abr = _action_border.get(rating, "#888")
        _ag = _action_guidance.get(rating, "Review the full analysis above to determine appropriate action.")

        _upside_text = ""
        if upside_pct is not None:
            _upside_text = f"Estimated upside to base case: <strong>{upside_pct:+.1f}%</strong>. "
        elif fv and fv.get("base") and price and price > 0:
            _calc_upside = ((fv["base"] - price) / price) * 100
            _upside_text = f"Estimated upside to base case: <strong>{_calc_upside:+.1f}%</strong>. "

        st.markdown(
            f'<div style="background:{_ab}; border:1px solid {_abr}; border-radius:10px; padding:16px 20px;">'
            f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">'
            f'<span style="background:{_abr}; color:white; padding:6px 16px; border-radius:6px; '
            f'font-weight:800; font-size:1.1em;">{rating}</span>'
            f'<span style="font-size:0.9em;color:#aaa;">Conviction: {conviction} | Score: {ai_score:.0f}/100</span></div>'
            f'<div style="font-size:0.95em;line-height:1.6;">{_upside_text}{_ag}</div>'
            f'<div style="font-size:0.75em;color:#777;margin-top:8px;font-style:italic;">'
            f'This is AI-generated analysis for informational purposes only. Not financial advice. '
            f'Always conduct your own due diligence before making investment decisions.</div></div>',
            unsafe_allow_html=True,
        )

        # ─────────────────────────────────────────────────────────────
        # Export & Re-run buttons
        # ─────────────────────────────────────────────────────────────
        st.markdown("")
        _exp_col, _rerun_col = st.columns([1, 1])
        with _exp_col:
            _export_lines = [
                f"PROSPER AI ANALYSIS — {ticker}",
                f"{'=' * 50}",
                f"Rating: {rating} | Score: {ai_score:.0f}/100 | Conviction: {conviction}",
                f"Archetype: {arch} — {arch_name}",
                f"Environment: {env_net}",
                "",
                f"INVESTMENT THESIS:",
                f"{thesis}",
                "",
            ]
            if fv and fv.get("base"):
                _export_lines.append(f"FAIR VALUE:")
                _export_lines.append(f"  Bear: ${fv.get('bear', 0):,.2f} ({fv.get('prob_bear', '?')}% prob)")
                _export_lines.append(f"  Base: ${fv.get('base', 0):,.2f} ({fv.get('prob_base', '?')}% prob)")
                _export_lines.append(f"  Bull: ${fv.get('bull', 0):,.2f} ({fv.get('prob_bull', '?')}% prob)")
                if _current and _current > 0:
                    _pw = (fv.get('bear',0) * fv.get('prob_bear',0) + fv.get('base',0) * fv.get('prob_base',0) + fv.get('bull',0) * fv.get('prob_bull',0)) / 100
                    _export_lines.append(f"  Prob-Weighted FV: ${_pw:,.2f} ({((_pw - _current)/_current*100):+.1f}% from current)")
                _export_lines.append("")

            if scores and isinstance(scores, dict):
                _export_lines.append("SCORE BREAKDOWN:")
                for _f, _s in scores.items():
                    _w = weights.get(_f, 0) if weights else 0
                    _export_lines.append(f"  {_f.replace('_', ' ').title()}: {_s}/10 (weight: {_w}%)")
                _export_lines.append("")

            if risks:
                _export_lines.append("KEY RISKS:")
                for r in risks:
                    _export_lines.append(f"  - {r}")
                _export_lines.append("")
            if catalysts:
                _export_lines.append("KEY CATALYSTS:")
                for c in catalysts:
                    _export_lines.append(f"  - {c}")
                _export_lines.append("")

            _export_lines.append(f"Analysis date: {_analysis_date[:10] if _analysis_date else 'N/A'}")
            _export_lines.append(f"Tier: {tier_used} | Cost: ${cost:.4f}")
            if data_sources:
                _export_lines.append(f"Sources: {', '.join(data_sources)}")
            _export_text = "\n".join(_export_lines)
            st.download_button(
                "Export Analysis (.txt)", _export_text, file_name=f"prosper_{ticker}_analysis.txt",
                mime="text/plain", use_container_width=True,
            )
        with _rerun_col:
            if st.button("Re-run Analysis", use_container_width=True, key="dd_rerun_btn"):
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
                f'<div style="font-size:1.2em; font-weight:600; margin-bottom:8px;">No PROSPER Analysis Found</div>'
                f'<div style="color:#999;">Run a PROSPER analysis for <strong>{ticker}</strong> to see the full CIO-grade equity breakdown: '
                f'rating, score, fair value, risk factors, catalysts, and more.</div></div>',
                unsafe_allow_html=True,
            )

        tier_col, btn_col = st.columns([2, 1])
        with tier_col:
            run_tier = st.selectbox(
                "Analysis Tier",
                list(MODEL_TIERS.keys()),
                format_func=lambda t: f"{MODEL_TIERS[t]['label']} — {MODEL_TIERS[t]['description']}",
                index=1,
                key="dd_run_tier",
            )
        with btn_col:
            st.markdown("<br>", unsafe_allow_html=True)
            run_btn = st.button("Run PROSPER Analysis", type="primary", use_container_width=True, key="dd_run_btn")

        if run_btn:
            with st.spinner(f"Running {MODEL_TIERS[run_tier]['label']} analysis on **{ticker}**..."):
                enriched_row = None
                ext_df = st.session_state.get("extended_df")
                if ext_df is not None and not ext_df.empty:
                    t_col = "ticker_resolved" if "ticker_resolved" in ext_df.columns else "ticker"
                    match = ext_df[ext_df[t_col] == ticker]
                    if not match.empty:
                        enriched_row = match.iloc[0].to_dict()

                result, error = run_analysis(ticker, tier=run_tier, info=info, enriched_row=enriched_row)

            if error:
                st.error(error)
            elif result:
                save_prosper_analysis(ticker, result)
                st.success(
                    f"Analysis complete — {result.get('rating')} | Score: {result.get('score', 0):.0f}/100 | "
                    f"${result.get('cost_estimate', 0):.4f}"
                )
                st.rerun()
