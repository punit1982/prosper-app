"""
Portfolio Dashboard (v4)
========================
Live prices, P&L, extended metrics with persistent preferences.

v4 Enhancements:
- Persistent sidebar preferences (saved to settings)
- Currency tabs — one tab per portfolio currency
- Consensus rating + upside/downside potential next to price
- Funds/ETF separation with fund-specific metrics
- Auto-load extended metrics option
"""

import time
import math
import streamlit as st
import pandas as pd

from core.database import (get_all_holdings, clear_all_holdings, get_price_cache_age,
                          get_total_realized_pnl, get_all_cash_positions, save_cash_position,
                          delete_cash_position)
from core.cio_engine import enrich_portfolio, add_key_metrics
from core.data_engine import get_ticker_info_batch, fmt_large
from core.settings import SETTINGS, save_user_settings

# ─────────────────────────────────────────
# SIDEBAR — Persistent Preferences
# ─────────────────────────────────────────
with st.sidebar:
    st.subheader("Settings")
    currency_options = ["USD", "AED", "EUR", "GBP", "INR", "SGD", "HKD", "AUD", "CAD", "JPY"]
    default_idx = (
        currency_options.index(SETTINGS["base_currency"])
        if SETTINGS["base_currency"] in currency_options else 0
    )
    base_currency = st.selectbox("Base Currency", currency_options, index=default_idx)

    st.divider()
    st.subheader("Columns")
    show_day_gain   = st.checkbox("Day Gain / Loss",  value=SETTINGS.get("pref_dash_show_day_gain", True))
    show_unrealized = st.checkbox("Unrealized P&L",   value=SETTINGS.get("pref_dash_show_unrealized", True))
    show_extended   = st.checkbox("Extended Metrics (52W, FWD PE, Target)", value=SETTINGS.get("pref_dash_show_extended", False))
    show_growth     = st.checkbox("Growth & Financials", value=SETTINGS.get("pref_dash_show_growth", False))
    show_prosper     = st.checkbox("Prosper AI Ratings", value=SETTINGS.get("pref_dash_show_prosper", False))
    show_broker     = st.checkbox("Broker", value=SETTINGS.get("pref_dash_show_broker", False))

    # Auto-persist preferences when changed
    _prefs = {
        "pref_dash_show_day_gain": show_day_gain,
        "pref_dash_show_unrealized": show_unrealized,
        "pref_dash_show_extended": show_extended,
        "pref_dash_show_growth": show_growth,
        "pref_dash_show_prosper": show_prosper,
        "pref_dash_show_broker": show_broker,
    }
    _changed = {k: v for k, v in _prefs.items() if SETTINGS.get(k) != v}
    if _changed:
        save_user_settings(_changed)
        SETTINGS.update(_changed)

    st.divider()
    auto_ext = st.checkbox("Auto-load Extended Metrics", value=SETTINGS.get("pref_dash_auto_extended", False),
                            help="Automatically fetch extended data when prices load")
    if auto_ext != SETTINGS.get("pref_dash_auto_extended", False):
        save_user_settings({"pref_dash_auto_extended": auto_ext})
        SETTINGS["pref_dash_auto_extended"] = auto_ext

    load_extended_btn = st.button("📊 Load Extended Metrics", use_container_width=True,
                                   help="Fetches 52W H/L, Forward PE, Analyst Consensus, Growth data, Fund metrics, etc.")

    if st.button("🔁 Force Retry All Prices", use_container_width=True,
                  help="Clears failed-ticker cache and re-fetches ALL prices. Use if you see 'No live price' for stocks that should work."):
        from core.cio_engine import clear_failed_tickers
        clear_failed_tickers()
        try:
            from core.database import _get_connection
            conn = _get_connection()
            conn.execute("DELETE FROM price_cache WHERE price IS NULL")
            conn.execute("DELETE FROM ticker_cache")
            conn.commit()
            conn.close()
        except Exception:
            pass
        for key in list(st.session_state.keys()):
            if key.startswith("enriched_") or key.startswith("_de_resolved_") or key in ("extended_df", "last_refresh_time", "summary_info_map"):
                del st.session_state[key]
        st.rerun()

    # ── Quick IBKR Sync (only if configured) ──
    try:
        from core.settings import get_api_key as _dash_get_api_key, load_user_settings as _dash_load_settings
        _ibkr_token = _dash_get_api_key("IBKR_FLEX_TOKEN")
        _ibkr_placeholder = "your_" in _ibkr_token.lower() if _ibkr_token else True
        _ibkr_qid = _dash_load_settings().get("ibkr_flex_query_id", "")
        if bool(_ibkr_token) and not _ibkr_placeholder and _ibkr_qid:
            st.divider()
            if st.button("🔗 Sync IBKR", use_container_width=True,
                          help="Quick sync from Interactive Brokers via Flex Query"):
                st.switch_page("pages/25_IBKR_Sync.py")
    except Exception:
        pass

    # ── Cash Management ──
    st.divider()
    st.subheader("💵 Cash & Margin")
    with st.expander("Manage Cash Positions", expanded=False):
        from core.fortress import get_margin_rate, calculate_margin_cost, BROKER_MARGIN_RATES

        cash_df = get_all_cash_positions()
        total_margin_cost = 0.0
        if not cash_df.empty:
            for _, cpos in cash_df.iterrows():
                amt = float(cpos["amount"])
                broker = cpos.get("broker_source", "") or ""
                currency = cpos.get("currency", "USD")
                is_margin = bool(cpos.get("is_margin", 0)) or amt < 0

                c1, c2 = st.columns([5, 1])
                with c1:
                    if is_margin or amt < 0:
                        # Auto-detect margin rate from broker if not manually set
                        manual_rate = cpos.get("margin_rate")
                        if manual_rate and float(manual_rate) > 0:
                            rate = float(manual_rate)
                            rate_source = "manual"
                        elif broker:
                            margin_info = get_margin_rate(broker, amt, currency)
                            rate = margin_info.get("rate") or 0
                            rate_source = margin_info.get("broker_name", broker)
                        else:
                            rate = 0
                            rate_source = "unknown"

                        annual_cost = calculate_margin_cost(amt, rate) if rate > 0 else 0
                        total_margin_cost += annual_cost
                        st.markdown(
                            f"🔴 **{cpos['account_name']}** — {currency} {amt:,.2f} *(margin)* · "
                            f"Rate: **{rate:.2f}%** ({rate_source}) · "
                            f"Annual cost: **{currency} {annual_cost:,.0f}**"
                        )
                    else:
                        st.markdown(f"🟢 **{cpos['account_name']}** — {currency} {amt:,.2f}")
                with c2:
                    if st.button("🗑️", key=f"del_cash_{cpos['id']}", help="Delete"):
                        delete_cash_position(int(cpos["id"]))
                        st.rerun()

            # Summary
            net_cash = float(cash_df["amount"].sum())
            pos_cash = float(cash_df[cash_df["amount"] >= 0]["amount"].sum()) if len(cash_df[cash_df["amount"] >= 0]) > 0 else 0
            neg_cash = float(cash_df[cash_df["amount"] < 0]["amount"].sum()) if len(cash_df[cash_df["amount"] < 0]) > 0 else 0
            st.markdown("---")
            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                st.metric("Net Cash", f"{net_cash:,.0f}")
            with sc2:
                if neg_cash < 0:
                    st.metric("Margin Debt", f"{neg_cash:,.0f}")
                else:
                    st.metric("Margin Debt", "None")
            with sc3:
                if total_margin_cost > 0:
                    st.metric("Annual Margin Cost", f"{total_margin_cost:,.0f}")
                else:
                    st.metric("Annual Margin Cost", "—")
        else:
            st.caption("No cash positions added yet.")

        st.markdown("---")
        st.caption("**Add Cash Position**")
        cc1, cc2 = st.columns(2)
        with cc1:
            cash_acct = st.text_input("Account Name", placeholder="e.g. IBKR Cash", key="_cash_acct")
        with cc2:
            cash_cur = st.selectbox("Currency", ["USD", "AED", "EUR", "GBP", "INR", "SGD", "HKD"], key="_cash_cur")
        cc3, cc4 = st.columns(2)
        with cc3:
            cash_amt = st.number_input("Amount (negative = margin)", value=0.0, step=1000.0, key="_cash_amt")
        with cc4:
            broker_list = [""] + list(BROKER_MARGIN_RATES.keys())
            cash_broker = st.selectbox("Broker", broker_list, key="_cash_broker",
                                        format_func=lambda x: BROKER_MARGIN_RATES[x]["name"] if x else "Select broker...")
        cc5, cc6 = st.columns(2)
        with cc5:
            cash_is_margin = st.checkbox("Margin/Debit Balance", key="_cash_margin",
                                          value=(cash_amt < 0))
        with cc6:
            if cash_is_margin and cash_broker:
                # Auto-fill rate from broker
                auto_rate = get_margin_rate(cash_broker, cash_amt, cash_cur)
                default_rate = auto_rate.get("rate") or 6.5
                st.caption(f"Auto-detected: {default_rate:.2f}% ({auto_rate.get('broker_name', '')})")
                cash_margin_rate = st.number_input("Margin Rate %", value=default_rate, step=0.25, key="_cash_rate")
            elif cash_is_margin:
                cash_margin_rate = st.number_input("Margin Rate %", value=6.5, step=0.25, key="_cash_rate")
            else:
                cash_margin_rate = None

        if st.button("Add Cash Position", type="primary", use_container_width=True, key="_add_cash_btn"):
            if cash_acct.strip():
                save_cash_position(
                    account_name=cash_acct.strip(),
                    currency=cash_cur,
                    amount=cash_amt,
                    is_margin=cash_is_margin,
                    margin_rate=cash_margin_rate,
                    broker_source=cash_broker or None,
                )
                st.success(f"Added: {cash_acct} — {cash_cur} {cash_amt:,.2f}")
                st.rerun()
            else:
                st.warning("Please enter an account name.")

    # ── Clear Portfolio — 2-step confirmation ──
    if not st.session_state.get("_confirm_clear_portfolio"):
        if st.button("🗑️ Clear Entire Portfolio", type="secondary", use_container_width=True):
            st.session_state["_confirm_clear_portfolio"] = True
            st.rerun()
    else:
        st.warning("⚠️ This will **permanently delete** all holdings!")
        confirm_text = st.text_input("Type **DELETE** to confirm:", key="_clear_confirm_input")
        col_confirm, col_cancel = st.columns(2)
        with col_confirm:
            if st.button("Confirm Delete", type="primary", use_container_width=True,
                         disabled=(confirm_text != "DELETE")):
                clear_all_holdings()
                st.session_state["_confirm_clear_portfolio"] = False
                for key in list(st.session_state.keys()):
                    if key.startswith("enriched_") or key in ("metrics_df", "extended_df", "last_refresh_time"):
                        del st.session_state[key]
                st.rerun()
        with col_cancel:
            if st.button("Cancel", use_container_width=True):
                st.session_state["_confirm_clear_portfolio"] = False
                st.rerun()

# ─────────────────────────────────────────
# PAGE SETUP
# ─────────────────────────────────────────
st.header("Portfolio Dashboard")

holdings = get_all_holdings()
if holdings.empty:
    st.info("Your portfolio is empty. Go to **Upload Portal** to add your first brokerage screenshot.")
    st.stop()

ttl       = SETTINGS.get("price_cache_ttl_seconds", 300)
cache_key = f"enriched_{base_currency}"


# ── Load Extended Metrics (outside fragment) ──
def _load_extended_metrics():
    """Fetch extended metrics including consensus, asset type, and fund data."""
    existing = st.session_state.get(cache_key)
    if existing is None:
        return False
    tickers = (existing["ticker_resolved"].dropna().tolist()
               if "ticker_resolved" in existing.columns
               else existing["ticker"].dropna().tolist())
    with st.spinner("Fetching extended metrics for all holdings (~15 s)…"):
        info_map = get_ticker_info_batch(tickers)
        ext = existing.copy()
        t_col = "ticker_resolved" if "ticker_resolved" in ext.columns else "ticker"

        # Standard stock metrics
        ext["52w_high"]        = ext[t_col].map(lambda t: info_map.get(t, {}).get("fiftyTwoWeekHigh"))
        ext["52w_low"]         = ext[t_col].map(lambda t: info_map.get(t, {}).get("fiftyTwoWeekLow"))
        ext["forward_pe"]      = ext[t_col].map(lambda t: info_map.get(t, {}).get("forwardPE"))
        ext["trailing_pe"]     = ext[t_col].map(lambda t: info_map.get(t, {}).get("trailingPE"))
        ext["analyst_target"]  = ext[t_col].map(lambda t: info_map.get(t, {}).get("targetMeanPrice"))
        ext["beta"]            = ext[t_col].map(lambda t: info_map.get(t, {}).get("beta"))
        ext["dividend_yield"]  = ext[t_col].map(lambda t: info_map.get(t, {}).get("dividendYield"))
        ext["sector"]          = ext[t_col].map(lambda t: info_map.get(t, {}).get("sector", ""))
        ext["industry"]        = ext[t_col].map(lambda t: info_map.get(t, {}).get("industry", ""))
        ext["country"]         = ext[t_col].map(lambda t: info_map.get(t, {}).get("country", ""))
        ext["market_cap"]      = ext[t_col].map(lambda t: info_map.get(t, {}).get("marketCap"))
        ext["revenue_growth"]  = ext[t_col].map(lambda t: info_map.get(t, {}).get("revenueGrowth"))
        ext["earnings_growth"] = ext[t_col].map(lambda t: info_map.get(t, {}).get("earningsGrowth"))
        ext["profit_margin"]   = ext[t_col].map(lambda t: info_map.get(t, {}).get("profitMargins"))
        ext["ebitda"]          = ext[t_col].map(lambda t: info_map.get(t, {}).get("ebitda"))
        ext["total_revenue"]   = ext[t_col].map(lambda t: info_map.get(t, {}).get("totalRevenue"))
        ext["trailing_eps"]    = ext[t_col].map(lambda t: info_map.get(t, {}).get("trailingEps"))
        ext["forward_eps"]     = ext[t_col].map(lambda t: info_map.get(t, {}).get("forwardEps"))
        ext["roe"]             = ext[t_col].map(lambda t: info_map.get(t, {}).get("returnOnEquity"))
        ext["debt_to_equity"]  = ext[t_col].map(lambda t: info_map.get(t, {}).get("debtToEquity"))

        # Consensus / Analyst data
        ext["recommendation_key"]  = ext[t_col].map(lambda t: info_map.get(t, {}).get("recommendationKey", ""))
        ext["recommendation_mean"] = ext[t_col].map(lambda t: info_map.get(t, {}).get("recommendationMean"))
        ext["num_analysts"]        = ext[t_col].map(lambda t: info_map.get(t, {}).get("numberOfAnalystOpinions"))

        # Asset type detection (EQUITY / ETF / MUTUALFUND)
        ext["quote_type"] = ext[t_col].map(lambda t: info_map.get(t, {}).get("quoteType", "EQUITY"))

        # Fund-specific metrics
        ext["fund_category"]   = ext[t_col].map(lambda t: info_map.get(t, {}).get("category", ""))
        ext["fund_family"]     = ext[t_col].map(lambda t: info_map.get(t, {}).get("fundFamily", ""))
        ext["expense_ratio"]   = ext[t_col].map(lambda t: info_map.get(t, {}).get("annualReportExpenseRatio"))
        ext["total_assets"]    = ext[t_col].map(lambda t: info_map.get(t, {}).get("totalAssets"))
        ext["ytd_return"]      = ext[t_col].map(lambda t: info_map.get(t, {}).get("ytdReturn"))
        ext["three_yr_return"] = ext[t_col].map(lambda t: info_map.get(t, {}).get("threeYearAverageReturn"))
        ext["five_yr_return"]  = ext[t_col].map(lambda t: info_map.get(t, {}).get("fiveYearAverageReturn"))

        st.session_state["extended_df"] = ext
    return True


if load_extended_btn:
    if not _load_extended_metrics():
        st.warning("Prices must load first. Please wait and try again.")

# Auto-load if preference is set and extended data not yet loaded
if auto_ext and "extended_df" not in st.session_state and cache_key in st.session_state:
    _load_extended_metrics()

# Re-load extended metrics after manual price refresh (preserves extended view)
if st.session_state.pop("_reload_extended", False) and cache_key in st.session_state:
    _load_extended_metrics()


# ─────────────────────────────────────────
# FORMATTING HELPERS
# ─────────────────────────────────────────
def fmt_val(val):
    try:
        v = float(val)
        if math.isnan(v): return ""
        if abs(v) >= 100:
            return f"{v:+,.0f}"
        elif abs(v) >= 1:
            return f"{v:+,.2f}"
        else:
            return f"{v:+,.4f}"
    except (TypeError, ValueError):
        return ""

def fmt_pct(val):
    try:
        v = float(val)
        if math.isnan(v): return ""
        return f"{v:+.2f}%"
    except (TypeError, ValueError):
        return ""

def fmt_price(val):
    try:
        v = float(val)
        if math.isnan(v): return ""
        # Adaptive decimals: 2 for >10, 3 for 1-10, 4 for <1
        if abs(v) >= 10:
            return f"{v:,.2f}"
        elif abs(v) >= 1:
            return f"{v:,.3f}"
        else:
            return f"{v:,.4f}"
    except (TypeError, ValueError):
        return ""

def fmt_ratio(val):
    try:
        v = float(val)
        if math.isnan(v): return ""
        return f"{v:.2f}"
    except (TypeError, ValueError):
        return ""

def fmt_pct_plain(val):
    try:
        v = float(val)
        if math.isnan(v): return ""
        pct = v * 100 if abs(v) < 1 else v
        if abs(pct) > 500: return ""  # nonsensical — suppress
        return f"{pct:.1f}%"
    except (TypeError, ValueError):
        return ""

def safe_sum(series):
    try:
        vals = pd.to_numeric(series, errors="coerce").dropna()
        return float(vals.sum()) if len(vals) > 0 else None
    except Exception:
        return None

def color_signed(val, sym=""):
    if not isinstance(val, str) or val in ("", "—"):
        return ""
    stripped = val
    for ch in [sym, ",", " ", "m", "M", "k", "%", "+"]:
        stripped = stripped.replace(ch, "")
    try:
        v = float(stripped)
        if v > 0:
            return "color: #1a9e5c; font-weight: 600"
        elif v < 0:
            return "color: #d63031; font-weight: 600"
    except ValueError:
        pass
    return ""

def _rating_label(key):
    """Convert yfinance recommendationKey to a display label."""
    mapping = {
        "strongBuy": "Strong Buy", "buy": "Buy", "hold": "Hold",
        "underperform": "Underperform", "sell": "Sell", "strongSell": "Strong Sell",
    }
    return mapping.get(str(key).strip(), str(key).title() if key else "")

def _rating_color_from_label(label):
    """Return CSS style for a consensus rating label."""
    l = str(label).strip().lower()
    if l in ("strong buy", "buy"):
        return "color: #1a9e5c; font-weight: 600"
    elif l in ("sell", "strong sell", "underperform"):
        return "color: #d63031; font-weight: 600"
    elif l == "hold":
        return "color: #f39c12; font-weight: 600"
    return ""

def _is_fund(qt):
    """Check if quoteType indicates a fund or ETF."""
    return str(qt).upper() in ("ETF", "MUTUALFUND")


# ─────────────────────────────────────────
# TABLE BUILDERS
# ─────────────────────────────────────────
def _build_stock_table(sub_df, sym):
    """Build display DataFrame for stocks with consensus columns."""
    display = pd.DataFrame()
    display["Ticker"] = sub_df["ticker"].values
    display["Name"]   = sub_df.get("name", pd.Series(dtype=str)).fillna("").apply(lambda x: str(x)[:25]).values
    display["Qty"]    = sub_df["quantity"].apply(lambda x: f"{float(x):g}" if pd.notna(x) else "").values
    display["Avg Cost"]  = sub_df["avg_cost"].apply(fmt_price).values
    display["Price"]     = sub_df.get("current_price", pd.Series(dtype=float)).apply(fmt_price).values

    # Consensus columns — always show if extended data loaded
    if "recommendation_key" in sub_df.columns:
        display["Rating"] = sub_df["recommendation_key"].apply(_rating_label).values
        display["Target"] = sub_df.get("analyst_target", pd.Series(dtype=float)).apply(fmt_price).values
        # Vectorized upside calculation
        target_v = pd.to_numeric(sub_df["analyst_target"], errors="coerce")
        current_v = pd.to_numeric(sub_df["current_price"], errors="coerce")
        upside = ((target_v.values - current_v.values) / current_v.values * 100)
        display["Upside %"] = pd.Series(upside).apply(
            lambda v: f"{v:+.1f}%" if pd.notna(v) and not math.isinf(v) else ""
        ).values

    if show_day_gain and "day_gain" in sub_df.columns:
        display[f"Day P&L ({sym})"] = sub_df["day_gain"].apply(fmt_val).values
        display["Day %"] = sub_df.get("change_pct", pd.Series(dtype=float)).apply(fmt_pct).values

    if "market_value" in sub_df.columns:
        display[f"Value ({sym})"] = sub_df["market_value"].apply(fmt_val).values

    if show_unrealized and "unrealized_pnl" in sub_df.columns:
        display[f"P&L ({sym})"] = sub_df["unrealized_pnl"].apply(fmt_val).values
        display["Return %"] = sub_df.get("unrealized_pnl_pct", pd.Series(dtype=float)).apply(fmt_pct).values

    if show_extended:
        if "52w_high" in sub_df.columns:
            display["52W High"] = sub_df["52w_high"].apply(fmt_price).values
            display["52W Low"]  = sub_df["52w_low"].apply(fmt_price).values
        if "forward_pe" in sub_df.columns:
            display["Fwd P/E"] = sub_df["forward_pe"].apply(fmt_ratio).values
        if "beta" in sub_df.columns:
            display["Beta"] = sub_df["beta"].apply(fmt_ratio).values
        if "dividend_yield" in sub_df.columns:
            display["Div Yield"] = sub_df["dividend_yield"].apply(fmt_pct_plain).values

    if show_growth:
        if "revenue_growth" in sub_df.columns:
            display["Rev Growth"]  = sub_df["revenue_growth"].apply(fmt_pct_plain).values
            display["Earn Growth"] = sub_df["earnings_growth"].apply(fmt_pct_plain).values
            display["Margin"]      = sub_df["profit_margin"].apply(fmt_pct_plain).values
        if "trailing_eps" in sub_df.columns:
            display["EPS"] = sub_df["trailing_eps"].apply(fmt_ratio).values
        if "roe" in sub_df.columns:
            display["ROE"] = sub_df["roe"].apply(fmt_pct_plain).values

    if show_prosper:
        from core.database import get_all_prosper_analyses
        prosper_df = get_all_prosper_analyses()
        if not prosper_df.empty:
            prosper_map = prosper_df.set_index("ticker").to_dict("index")
            tickers = sub_df["ticker"].values
            display["AI Rating"] = [prosper_map.get(t, {}).get("rating", "") for t in tickers]
            display["AI Score"] = [
                f"{prosper_map[t]['score']:.0f}" if t in prosper_map and pd.notna(prosper_map[t].get("score")) else ""
                for t in tickers
            ]
            display["AI Upside"] = [
                f"{prosper_map[t]['upside_pct']:+.1f}%" if t in prosper_map and pd.notna(prosper_map[t].get("upside_pct")) else ""
                for t in tickers
            ]

    if show_broker and "broker_source" in sub_df.columns:
        display["Broker"] = sub_df["broker_source"].fillna("").values

    return display.sort_values("Ticker", key=lambda x: x.str.upper()).reset_index(drop=True)


def _build_fund_table(sub_df, sym):
    """Build display DataFrame for Funds & ETFs with fund-specific metrics."""
    display = pd.DataFrame()
    display["Ticker"] = sub_df["ticker"].values
    display["Name"]   = sub_df.get("name", pd.Series(dtype=str)).fillna("").values
    display["Type"]   = sub_df.get("quote_type", pd.Series(dtype=str)).apply(
        lambda x: "ETF" if str(x).upper() == "ETF" else "Fund"
    ).values
    display["Qty"]    = sub_df["quantity"].apply(lambda x: f"{float(x):,.4f}" if pd.notna(x) else "").values
    display["Price"]  = sub_df.get("current_price", pd.Series(dtype=float)).apply(fmt_price).values

    if show_day_gain and "day_gain" in sub_df.columns:
        display[f"Day P&L ({sym})"] = sub_df["day_gain"].apply(fmt_val).values
        display["Day %"] = sub_df.get("change_pct", pd.Series(dtype=float)).apply(fmt_pct).values

    if "market_value" in sub_df.columns:
        display[f"Value ({sym})"] = sub_df["market_value"].apply(fmt_val).values

    if show_unrealized and "unrealized_pnl" in sub_df.columns:
        display[f"P&L ({sym})"] = sub_df["unrealized_pnl"].apply(fmt_val).values
        display["Return %"] = sub_df.get("unrealized_pnl_pct", pd.Series(dtype=float)).apply(fmt_pct).values

    # Fund-specific columns
    if "fund_category" in sub_df.columns:
        display["Category"]    = sub_df["fund_category"].fillna("").values
    if "fund_family" in sub_df.columns:
        display["Fund Family"] = sub_df["fund_family"].fillna("").values
    if "expense_ratio" in sub_df.columns:
        display["Exp Ratio"]   = sub_df["expense_ratio"].apply(fmt_pct_plain).values
    if "total_assets" in sub_df.columns:
        display["AUM"]         = sub_df["total_assets"].apply(fmt_large).values
    if "ytd_return" in sub_df.columns:
        display["YTD"]  = sub_df["ytd_return"].apply(fmt_pct_plain).values
    if "three_yr_return" in sub_df.columns:
        display["3Y Avg"] = sub_df["three_yr_return"].apply(fmt_pct_plain).values
    if "five_yr_return" in sub_df.columns:
        display["5Y Avg"] = sub_df["five_yr_return"].apply(fmt_pct_plain).values

    return display.sort_values("Ticker", key=lambda x: x.str.upper()).reset_index(drop=True)


def _render_currency_section(currency_df, sym, currency_label, tab_key):
    """Render a currency section: summary metrics + stock table + fund table."""
    cur_value      = safe_sum(currency_df.get("market_value"))
    cur_cost       = safe_sum(currency_df.get("cost_basis"))
    cur_unrealized = safe_sum(currency_df.get("unrealized_pnl"))
    cur_day_gain   = safe_sum(currency_df.get("day_gain"))

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        st.metric(f"{currency_label} Value", f"{sym} {fmt_large(cur_value)}" if cur_value else "—")
    with mc2:
        if cur_day_gain is not None:
            base_v = (cur_value - cur_day_gain) if cur_value else None
            d_pct = (cur_day_gain / base_v * 100) if base_v else 0
            st.metric("Today", f"{sym} {fmt_large(abs(cur_day_gain))}",
                      delta=f"{cur_day_gain:+,.0f} ({d_pct:+.1f}%)")
        else:
            st.metric("Today", "—")
    with mc3:
        if cur_unrealized is not None and cur_cost:
            u_pct = cur_unrealized / cur_cost * 100
            st.metric("Unrealized P&L", f"{sym} {fmt_large(abs(cur_unrealized))}",
                      delta=f"{cur_unrealized:+,.0f} ({u_pct:+.1f}%)")
        else:
            st.metric("Unrealized P&L", "—")

    # Split into stocks vs funds/ETFs
    has_type_info = "quote_type" in currency_df.columns
    if has_type_info:
        funds_mask = currency_df["quote_type"].apply(_is_fund)
        stocks_df  = currency_df[~funds_mask]
        funds_df   = currency_df[funds_mask]
    else:
        stocks_df = currency_df
        funds_df  = pd.DataFrame()

    # ── Stocks table ──
    if not stocks_df.empty:
        stock_display = _build_stock_table(stocks_df, sym)

        # Color coding
        signed_cols = [c for c in stock_display.columns
                       if any(kw in c for kw in ["Day P&L", "Day %", "P&L (", "Return %", "Upside %", "AI Upside"])]
        rating_cols = [c for c in stock_display.columns if c == "Rating"]
        ai_rating_cols = [c for c in stock_display.columns if c == "AI Rating"]

        styled = stock_display.style
        if signed_cols:
            styled = styled.map(lambda v: color_signed(v, sym), subset=signed_cols)
        if rating_cols:
            styled = styled.map(_rating_color_from_label, subset=rating_cols)
        if ai_rating_cols:
            def _ai_rating_color(val):
                v = str(val).strip().upper()
                if v in ("STRONG BUY", "BUY"):
                    return "color: #1a9e5c; font-weight: 600"
                elif v in ("SELL", "STRONG SELL"):
                    return "color: #d63031; font-weight: 600"
                elif v == "HOLD":
                    return "color: #f39c12; font-weight: 600"
                return ""
            styled = styled.map(_ai_rating_color, subset=ai_rating_cols)

        label = f"📈 Stocks — {len(stocks_df)}" if has_type_info else f"Holdings — {len(stocks_df)}"
        st.caption(f"**{label}**")
        st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Funds & ETFs table ──
    if not funds_df.empty:
        fund_display = _build_fund_table(funds_df, sym)

        fund_signed = [c for c in fund_display.columns
                       if any(kw in c for kw in ["Day P&L", "Day %", "P&L (", "Return %"])]
        fund_styled = (fund_display.style.map(lambda v: color_signed(v, sym), subset=fund_signed)
                       if fund_signed else fund_display.style)

        st.caption(f"**📊 Funds & ETFs — {len(funds_df)}**")
        st.dataframe(fund_styled, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────
# AUTO-REFRESHING PORTFOLIO SECTION
# ─────────────────────────────────────────
@st.fragment(run_every=ttl)
def portfolio_section():
    sym       = base_currency
    now       = time.time()
    last      = st.session_state.get("last_refresh_time", 0)
    cache_age = now - last

    has_cache      = cache_key in st.session_state
    cache_is_stale = cache_age >= ttl

    # SQLite cache age — survives server restarts, shows on fresh sessions
    sqlite_age = get_price_cache_age()

    hdr1, hdr2 = st.columns([7, 1])
    with hdr1:
        def _fmt_age(secs):
            """Human-friendly age string."""
            s = int(secs)
            if s < 60: return f"{s}s ago"
            if s < 3600: return f"{s//60}m {s%60}s ago"
            if s < 86400: return f"{s//3600}h {(s%3600)//60}m ago"
            return f"{s//86400}d ago"

        _best_age = None
        if has_cache and 0 < cache_age < 86400 * 7:
            _best_age = cache_age
        elif sqlite_age is not None and 0 < sqlite_age < 86400 * 7:
            _best_age = sqlite_age

        if _best_age is not None:
            st.caption(f"📡 Prices: **{_fmt_age(_best_age)}** · Base: **{sym}**")
        else:
            st.caption(f"📡 Prices: **live** · Base: **{sym}**")
    with hdr2:
        manual_refresh = st.button("🔄", use_container_width=True, key="frag_refresh",
                                    help="Refresh prices now")

    needs_fetch = not has_cache or cache_is_stale or manual_refresh

    if needs_fetch:
        cold_start = sqlite_age is None
        if cold_start or manual_refresh:
            with st.spinner("Fetching live prices…" if cold_start else "Refreshing prices…"):
                enriched = enrich_portfolio(holdings, base_currency)
        else:
            enriched = enrich_portfolio(holdings, base_currency)
        st.session_state[cache_key] = enriched
        st.session_state["last_refresh_time"] = time.time()
        # Re-load extended metrics if they were previously loaded (preserve user's extended view)
        if manual_refresh and "extended_df" in st.session_state:
            st.session_state["_reload_extended"] = True

    if cache_key not in st.session_state:
        st.info("No price data available. Click 🔄 to retry.")
        return

    # Use extended_df if available, otherwise base enriched data
    full_enriched = st.session_state[cache_key]
    ext = st.session_state.get("extended_df")
    df = (ext if ext is not None else full_enriched).copy()

    # ── Grand Total Summary Cards ─────────────────────────────────────────────
    total_value      = safe_sum(df.get("market_value"))
    total_cost       = safe_sum(df.get("cost_basis"))
    total_unrealized = safe_sum(df.get("unrealized_pnl"))
    total_day_gain   = safe_sum(df.get("day_gain"))
    total_realized   = get_total_realized_pnl()

    # Cash positions
    cash_positions = get_all_cash_positions()
    total_cash = float(cash_positions["amount"].sum()) if not cash_positions.empty else 0.0
    margin_debt = float(cash_positions[cash_positions["is_margin"] == 1]["amount"].sum()) if not cash_positions.empty and "is_margin" in cash_positions.columns else 0.0
    net_portfolio_value = (total_value or 0) + total_cash

    # Row 1: Big 3 metrics
    c1, c2, c3 = st.columns(3)
    with c1:
        if total_value is not None:
            label = f"{sym} {fmt_large(net_portfolio_value)}" if total_cash != 0 else f"{sym} {fmt_large(total_value)}"
            st.metric("Total Portfolio Value", label,
                      help=f"Securities: {sym} {fmt_large(total_value)}" + (f" + Cash: {sym} {total_cash:,.0f}" if total_cash != 0 else ""))
        else:
            st.metric("Total Portfolio Value", f"{len(df)} holdings")
    with c2:
        if total_day_gain is not None:
            base = (total_value - total_day_gain) if total_value else None
            pct  = (total_day_gain / base * 100) if base else 0
            st.metric("Today's Gain / Loss", f"{sym} {fmt_large(abs(total_day_gain))}",
                      delta=f"{total_day_gain:+,.0f} ({pct:+.2f}%)")
        else:
            st.metric("Today's Gain / Loss", "—")
    with c3:
        if total_unrealized is not None and total_cost:
            pct = total_unrealized / total_cost * 100
            st.metric("Unrealized P&L", f"{sym} {fmt_large(abs(total_unrealized))}",
                      delta=f"{total_unrealized:+,.0f} ({pct:+.1f}%)")
        else:
            st.metric("Unrealized P&L", "—")
    # Row 2: Secondary metrics
    c4, c5, c6 = st.columns(3)
    with c4:
        if total_realized != 0:
            st.metric("Realized P&L", f"{sym} {fmt_large(abs(total_realized))}",
                      delta=f"{total_realized:+,.0f}",
                      help="Net realized gains/losses from sell transactions.")
        else:
            st.metric("Realized P&L", "—", help="Add sell transactions in Transaction Log to see realized P&L.")
    with c5:
        if total_cash != 0:
            cash_label = f"{sym} {total_cash:,.0f}"
            margin_help = f"Margin debt: {sym} {margin_debt:,.0f}" if margin_debt < 0 else ""
            cash_pct = (total_cash / net_portfolio_value * 100) if net_portfolio_value else 0
            st.metric("Cash & Equivalents", cash_label,
                      delta=f"{cash_pct:.1f}% of portfolio",
                      help=f"Net cash across all accounts. {margin_help}".strip())
        else:
            st.metric("Cash & Equivalents", "—",
                      help="Add cash positions via sidebar → 💵 Cash Positions")
    with c6:
        live = int(pd.to_numeric(df.get("current_price", pd.Series(dtype=float)), errors="coerce").notna().sum())
        st.metric("Holdings", f"{len(df)}", help=f"{live} with live prices · {len(df)-live} missing")

    st.divider()

    # ── Currency Tabs — with "All" tab, country-friendly names ─────────────
    _CUR_COUNTRY = {
        "USD": "United States", "AED": "UAE", "EUR": "Europe", "GBP": "United Kingdom",
        "INR": "India", "SGD": "Singapore", "HKD": "Hong Kong", "AUD": "Australia",
        "CAD": "Canada", "JPY": "Japan", "CHF": "Switzerland", "CNY": "China",
        "BRL": "Brazil", "KRW": "South Korea", "SEK": "Sweden", "NOK": "Norway",
    }
    currencies = sorted(df["currency"].dropna().unique().tolist()) if "currency" in df.columns else [sym]

    if len(currencies) <= 1:
        _render_currency_section(df, sym, currencies[0] if currencies else sym, "single")
    else:
        tab_labels = ["All"]
        for cur in currencies:
            country = _CUR_COUNTRY.get(cur, cur)
            tab_labels.append(country)

        tabs = st.tabs(tab_labels)
        # "All" tab
        with tabs[0]:
            _render_currency_section(df, sym, "All", "tab_all")
        # Per-currency tabs
        for i, cur in enumerate(currencies):
            with tabs[i + 1]:
                cur_df = df[df["currency"] == cur].copy()
                _render_currency_section(cur_df, sym, cur, f"tab_{cur}")

    # ── Inline Editing ─────────────────────────────
    st.divider()
    with st.expander("✏️ Edit Holdings", expanded=False):
        from core.database import update_holding
        raw_holdings = get_all_holdings()
        if not raw_holdings.empty:
            edit_df = raw_holdings[["id", "ticker", "name", "quantity", "avg_cost", "currency"]].copy()
            edited = st.data_editor(
                edit_df,
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                    "ticker": st.column_config.TextColumn("Ticker", disabled=True),
                    "name": st.column_config.TextColumn("Name", disabled=True),
                    "quantity": st.column_config.NumberColumn("Quantity", min_value=0, format="%.4f"),
                    "avg_cost": st.column_config.NumberColumn("Avg Cost", min_value=0, format="%.4f"),
                    "currency": st.column_config.SelectboxColumn("Currency",
                        options=["USD", "AED", "EUR", "GBP", "INR", "SGD", "HKD", "AUD", "CAD", "JPY", "CHF"]),
                },
                hide_index=True,
                use_container_width=True,
                key="holdings_editor",
            )

            if st.button("Save Changes", type="primary", key="save_edit"):
                changes = 0
                for idx in range(len(edit_df)):
                    row_id = int(edit_df.iloc[idx]["id"])
                    for col in ["quantity", "avg_cost", "currency"]:
                        orig = edit_df.iloc[idx][col]
                        new_val = edited.iloc[idx][col]
                        if str(orig) != str(new_val):
                            update_holding(row_id, **{col: new_val})
                            changes += 1
                if changes > 0:
                    st.success(f"Saved {changes} change(s). Refreshing...")
                    for key in list(st.session_state.keys()):
                        if key.startswith("enriched_") or key in ("extended_df", "last_refresh_time"):
                            del st.session_state[key]
                    st.rerun()
                else:
                    st.info("No changes detected.")

    # ── Footer ─────────────────────────────
    st.divider()
    missing = df[pd.to_numeric(df.get("current_price", pd.Series(dtype=float)), errors="coerce").isna()]["ticker"].tolist()
    if missing:
        st.warning(
            f"**No live price for: {', '.join(missing)}**  \n"
            "Ticker resolution tried common exchange suffixes (.AE, .AD, .SW, .SI, etc.) but these weren't found.  \n"
            "For UAE: try `EMAAR.AE` (DFM) or `ADCB.AD` (ADX) · Swiss: `NESN.SW` · Singapore: `D05.SI`"
        )
    if "52w_high" not in df.columns:
        st.caption("ℹ️ Click **📊 Load Extended Metrics** for Analyst Consensus, 52W H/L, Growth data, Fund metrics, and more.")
    st.caption("ℹ️ Prices auto-refresh every 5 min. Click 🔄 for instant update.")

portfolio_section()
