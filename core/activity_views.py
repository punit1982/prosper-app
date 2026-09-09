"""
core/activity_views.py — the four time-ordered surfaces, as callable views.

Portfolio News, Market News, Earnings and Transactions were four top-level
destinations answering one question: what happened, and does it touch me?
Portfolio News even told the user to go to Market News for fund coverage —
the product admitting its own split was arbitrary.

They are one page now (views/9_Activity.py), selected with a segmented
control rather than st.tabs, because tabs are eager: every hidden tab is
built and shipped on every render, and one of these fans out to a news API.
A segmented control renders exactly the slice asked for.

Each function below is the original page body, verbatim apart from its
docstring and its own page_header call — Activity owns the header. Imports
stay function-local so a segment only pays for what it uses.
"""


def portfolio_news() -> None:

    import hashlib
    import streamlit as st
    import pandas as pd
    from datetime import datetime

    from core.database import get_all_holdings, get_news_cache
    from core.cio_engine import enrich_portfolio
    from core.data_engine import get_portfolio_news, summarize_news_with_ai, apply_global_filter
    from core.settings import SETTINGS, save_user_settings, enriched_cache_key

    from core.ui_components import page_header
    holdings = get_all_holdings()
    if holdings.empty:
        st.info("Add holdings via **Add holdings** to see related news.")
        st.stop()

    # ── Controls (persisted) ──
    with st.sidebar:
        max_articles = st.slider("Max articles", 10, 100,
                                  value=SETTINGS.get("pref_news_max_articles", 30), step=10)
        auto_summary = st.toggle("🤖 Auto-show AI summaries",
                                  value=SETTINGS.get("pref_news_auto_summary", False),
                                  help="Uses your Anthropic API credits (~$0.01 per summary)")
        # Persist changes
        _news_prefs = {"pref_news_max_articles": max_articles, "pref_news_auto_summary": auto_summary}
        _news_changed = {k: v for k, v in _news_prefs.items() if SETTINGS.get(k) != v}
        if _news_changed:
            save_user_settings(_news_changed)
            SETTINGS.update(_news_changed)

    # ── Resolve top tickers by portfolio value ──────────────────────────────────
    base_currency = SETTINGS.get("base_currency", "USD")
    enriched_key  = enriched_cache_key(base_currency)
    names = dict(zip(holdings["ticker"], holdings.get("name", pd.Series(dtype=str))))

    all_tickers = []
    fund_tickers = []
    if enriched_key in st.session_state:
        enriched = apply_global_filter(st.session_state[enriched_key])
        t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
        has_price = pd.to_numeric(enriched.get("current_price", pd.Series(dtype=float)), errors="coerce").notna()
        priced = enriched[has_price].copy()
        if "market_value" in priced.columns:
            priced = priced.sort_values("market_value", ascending=False)

        # Exclude Funds/ETFs from stock news (they return generic/irrelevant news)
        _ETF_KEYWORDS = ("ISHARES", "VANGUARD", "SPDR", "INVESCO", "PROSHARES", "WISDOMTREE",
                          "SCHWAB", "FIRST TRUST", "GLOBAL X", "PIMCO", "JPMORGAN EQUITY",
                          "ETF", "FUND", "INDEX", "TRUST")

        def _is_fund_or_etf(row):
            qt = str(row.get("quote_type", "")).upper()
            if qt in ("ETF", "MUTUALFUND"):
                return True
            name = str(row.get("name", "")).upper()
            if any(kw in name for kw in _ETF_KEYWORDS):
                return True
            return False

        is_fund = priced.apply(_is_fund_or_etf, axis=1)
        fund_tickers = priced.loc[is_fund, t_col].dropna().tolist()
        priced = priced[~is_fund]

        all_tickers = priced[t_col].dropna().tolist()

    # Fallback: use raw holdings tickers if not enriched yet
    if not all_tickers:
        all_tickers = holdings["ticker"].dropna().tolist()

    if fund_tickers:
        st.caption(f"ℹ️ Excluded **{len(fund_tickers)}** Funds/ETFs from stock news — see **Market News** for fund coverage.")

    # Top 15 by value — covers the bulk of the portfolio quickly
    TOP_N = 15
    top_tickers  = all_tickers[:TOP_N]
    rest_tickers = all_tickers[TOP_N:]

    # ── Check SQLite cache warmth to decide whether to show spinner ─────────────
    top_hash     = hashlib.md5(",".join(sorted(top_tickers)).encode()).hexdigest()[:12]
    has_db_cache = get_news_cache(f"pnews_{top_hash}") is not None

    st.caption(
        f"📡 Showing news for top **{len(top_tickers)}** holdings by value"
        + (f" · {len(rest_tickers)} more available" if rest_tickers else "")
        + (" · from cache" if has_db_cache else "")
    )

    # ── Fetch top-15 news ───────────────────────────────────────────────────────
    if has_db_cache:
        # Instant load — SQLite cache is warm
        news_items = get_portfolio_news(top_tickers, limit=max_articles)
    else:
        with st.spinner(f"Fetching news for {len(top_tickers)} holdings (~{len(top_tickers) * 2}s)…"):
            news_items = get_portfolio_news(top_tickers, limit=max_articles)

    if not news_items:
        st.info("No recent news found for your top holdings.")
        # Still allow loading the rest below
    else:
        st.caption(f"Showing **{len(news_items)}** articles from **{len(set(n.get('related_ticker','') for n in news_items))}** tickers")
        st.divider()

        # ── News feed ──────────────────────────────────────────────────────────
        for i, item in enumerate(news_items):
            title     = item.get("title", "Untitled")
            publisher = item.get("publisher", "Unknown")
            link      = item.get("link", "")
            ticker    = item.get("related_ticker", "")
            ts        = item.get("providerPublishTime", 0)
            date_str  = datetime.fromtimestamp(ts).strftime("%b %d, %Y · %I:%M %p") if ts else "—"

            col1, col2 = st.columns([5, 1])
            with col1:
                st.markdown(f"**{title}**")
                st.caption(f"🏷️ {ticker} · {publisher} · {date_str}")
            with col2:
                if link:
                    st.link_button("Read →", link, use_container_width=True)

            summary_key = f"news_summary_{i}"

            if auto_summary:
                if summary_key not in st.session_state:
                    ticker_name = names.get(ticker, "")
                    st.session_state[summary_key] = summarize_news_with_ai(title, publisher, ticker, ticker_name)
                st.info(f"🤖 **AI Summary:** {st.session_state[summary_key]}")
            else:
                if st.button("🤖 AI Summary", key=f"btn_summary_{i}"):
                    if summary_key not in st.session_state:
                        ticker_name = names.get(ticker, "")
                        with st.spinner("Generating AI summary…"):
                            st.session_state[summary_key] = summarize_news_with_ai(title, publisher, ticker, ticker_name)
                    st.info(f"🤖 **AI Summary:** {st.session_state[summary_key]}")

            st.divider()

    # ── Load remaining tickers on demand ────────────────────────────────────────
    if rest_tickers:
        st.subheader(f"Load news for remaining {len(rest_tickers)} holdings")
        if st.button(f"📰 Load {len(rest_tickers)} more holdings", use_container_width=True):
            rest_hash     = hashlib.md5(",".join(sorted(rest_tickers)).encode()).hexdigest()[:12]
            has_rest_cache = get_news_cache(f"pnews_{rest_hash}") is not None

            if has_rest_cache:
                more_news = get_portfolio_news(rest_tickers, limit=max_articles)
            else:
                with st.spinner(f"Fetching news for {len(rest_tickers)} more holdings…"):
                    more_news = get_portfolio_news(rest_tickers, limit=max_articles)

            if more_news:
                st.caption(f"Found **{len(more_news)}** more articles")
                for i, item in enumerate(more_news, start=len(news_items)):
                    title     = item.get("title", "Untitled")
                    publisher = item.get("publisher", "Unknown")
                    link      = item.get("link", "")
                    ticker    = item.get("related_ticker", "")
                    ts        = item.get("providerPublishTime", 0)
                    date_str  = datetime.fromtimestamp(ts).strftime("%b %d, %Y · %I:%M %p") if ts else "—"

                    col1, col2 = st.columns([5, 1])
                    with col1:
                        st.markdown(f"**{title}**")
                        st.caption(f"🏷️ {ticker} · {publisher} · {date_str}")
                    with col2:
                        if link:
                            st.link_button("Read →", link, use_container_width=True)
                    st.divider()
            else:
                st.info("No news found for remaining holdings.")


def market_news() -> None:

    import time
    import hashlib
    import streamlit as st
    import pandas as pd
    from datetime import datetime

    from core.data_engine import get_ticker_news, summarize_news_with_ai, apply_global_filter
    from core.database import get_news_cache, save_news_cache
    from core.settings import SETTINGS, save_user_settings, enriched_cache_key

    NEWS_TTL = 900  # 15 minutes

    from core.ui_components import page_header
    focus_map = {
        "🌐 Global Markets":         ["^GSPC", "^NDX", "^DJI", "^NSEI", "^FTSE", "^HSI"],
        "🇺🇸 US Markets":            ["^GSPC", "^NDX", "^DJI"],
        "🇮🇳 India":                 ["^NSEI", "^BSESN"],
        "💻 Technology":             ["XLK", "QQQ", "AAPL", "MSFT", "NVDA", "GOOGL"],
        "⚡ Energy":                  ["XLE", "CVX", "XOM", "COP"],
        "🏥 Healthcare":             ["XLV", "JNJ", "UNH", "PFE"],
        "🏦 Financials":             ["XLF", "JPM", "BAC", "GS"],
    }

    # Build "My Funds & ETFs" option from portfolio
    _fund_tickers = []
    base_currency = SETTINGS.get("base_currency", "USD")
    _enriched_key = enriched_cache_key(base_currency)
    if _enriched_key in st.session_state:
        _enr = st.session_state[_enriched_key]
        _t_col = "ticker_resolved" if "ticker_resolved" in _enr.columns else "ticker"
        # Check for extended_df which has quote_type
        _ext_df = st.session_state.get("extended_df")
        _src = _ext_df if _ext_df is not None else _enr
        if "quote_type" in _src.columns:
            _is_fund = _src["quote_type"].apply(lambda x: str(x).upper() in ("ETF", "MUTUALFUND"))
            _fund_tickers = _src.loc[_is_fund, _t_col].dropna().tolist()

    if _fund_tickers:
        focus_map["📊 My Funds & ETFs"] = _fund_tickers

    with st.sidebar:
        focus       = st.selectbox("Market Focus", list(focus_map.keys()))
        max_articles = st.slider("Max articles", 10, 50, 20)
        auto_summary = st.toggle("🤖 Auto AI Summaries",
                                  value=SETTINGS.get("pref_mkt_auto_summary", False),
                                  help="Generates an AI insight for every article (~$0.01 each)")
        # Persist preference
        if auto_summary != SETTINGS.get("pref_mkt_auto_summary", False):
            save_user_settings({"pref_mkt_auto_summary": auto_summary})
            SETTINGS["pref_mkt_auto_summary"] = auto_summary

        if st.button("🔄 Refresh News", use_container_width=True):
            cache_key = f"mkt_news_{focus}"
            st.session_state.pop(cache_key, None)
            st.session_state.pop(f"{cache_key}_ts", None)
            st.session_state["_mkt_news_force"] = True   # also skip the SQLite layer this run

    tickers   = focus_map.get(focus, ["^GSPC"])
    cache_key = f"mkt_news_{focus}"
    _force    = st.session_state.pop("_mkt_news_force", False)

    # ── Load from session_state cache (15-min TTL) ────────────────────────────────
    cached_ts = st.session_state.get(f"{cache_key}_ts", 0)
    has_cache = cache_key in st.session_state and (time.time() - cached_ts) < NEWS_TTL

    # ── Durable SQLite layer (1-hour TTL) — survives cold starts and free-tier
    #    spin-downs, which is what made this page take ~12s on every first visit.
    sqlite_key = f"mktnews_{hashlib.md5(focus.encode()).hexdigest()[:12]}"
    if not has_cache and not _force:
        _sq = get_news_cache(sqlite_key)   # None if missing or older than 1 hour
        if _sq is not None:
            st.session_state[cache_key]         = _sq[:max_articles]
            st.session_state[f"{cache_key}_ts"] = time.time()
            cached_ts = st.session_state[f"{cache_key}_ts"]
            has_cache = True

    if not has_cache:
        with st.spinner(f"Loading {focus} news…"):
            all_news = []
            for t in tickers:
                try:
                    items = get_ticker_news(t)
                    for item in items:
                        item["related_ticker"] = t
                        all_news.append(item)
                except Exception:
                    pass  # Skip tickers that fail

            seen, unique = set(), []
            for item in sorted(all_news, key=lambda x: x.get("providerPublishTime", 0), reverse=True):
                title = item.get("title", "")
                if title and title not in seen:
                    seen.add(title)
                    unique.append(item)

            st.session_state[cache_key]          = unique[:max_articles]
            st.session_state[f"{cache_key}_ts"]  = time.time()
            if unique:
                save_news_cache(sqlite_key, unique)   # full set — the slider re-slices on read

    news = st.session_state.get(cache_key, [])[:max_articles]

    if not news:
        st.info(f"No recent news found for {focus}. Try clicking **Refresh News**.")
        st.stop()

    # Age indicator
    age_s   = int(time.time() - cached_ts)
    age_str = f"{age_s // 60}m {age_s % 60}s ago" if age_s >= 60 else f"{age_s}s ago"
    st.caption(f"**{len(news)}** articles · {focus} · cached **{age_str}**")

    if focus == "📊 My Funds & ETFs":
        st.info(f"Showing news for **{len(tickers)}** Funds & ETFs from your portfolio. "
                "These are excluded from Portfolio News to keep stock-level focus.")

    st.divider()

    # ── News cards ────────────────────────────────────────────────────────────────
    for i, item in enumerate(news):
        title     = item.get("title", "Untitled")
        publisher = item.get("publisher", "")
        link      = item.get("link", "")
        ticker    = item.get("related_ticker", "")
        ts        = item.get("providerPublishTime", 0)
        date_str  = datetime.fromtimestamp(ts).strftime("%b %d · %I:%M %p") if ts else ""

        with st.container():
            col_main, col_btn = st.columns([6, 1])
            with col_main:
                st.markdown(f"**{title}**")
                st.caption(f"🏷️ `{ticker}` &nbsp;·&nbsp; {publisher} &nbsp;·&nbsp; {date_str}")
            with col_btn:
                if link:
                    st.link_button("Read →", link, use_container_width=True)

            skey = f"mkt_summary_{i}"

            if auto_summary:
                if skey not in st.session_state:
                    with st.spinner("Generating AI insight…"):
                        st.session_state[skey] = summarize_news_with_ai(
                            title, publisher, ticker, "Market Index"
                        )
                st.info(f"🤖 **AI Summary:** {st.session_state[skey]}")
            else:
                if st.button("🤖 AI Summary", key=f"mkt_btn_{i}", use_container_width=False):
                    if skey not in st.session_state:
                        with st.spinner("Generating AI summary…"):
                            st.session_state[skey] = summarize_news_with_ai(
                                title, publisher, ticker, "Market Index"
                            )
                if skey in st.session_state:
                    st.info(f"🤖 **AI Summary:** {st.session_state[skey]}")

        st.divider()


def earnings() -> None:

    import streamlit as st
    from core.ui_components import page_header
    import pandas as pd
    from datetime import datetime, timedelta

    from core.database import get_all_holdings
    from core.settings import SETTINGS, enriched_cache_key
    from core.cio_engine import enrich_portfolio
    from core.data_engine import get_ticker_info_batch


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

    # Use resolved tickers for better yfinance coverage
    _t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
    tickers = enriched[_t_col].tolist()

    # ── Fetch Earnings Data ──
    @st.cache_data(ttl=3600, show_spinner="Fetching earnings data…", max_entries=5)
    def _get_earnings_info(tickers_tuple):
        """Fetch earnings dates and EPS data for all tickers."""
        info_map = get_ticker_info_batch(list(tickers_tuple))
        rows = []
        for ticker in tickers_tuple:
            info = info_map.get(ticker, {})
            earnings_date = None
            # yfinance stores earnings dates in different fields
            ed = info.get("earningsDate")
            if ed:
                if isinstance(ed, list) and len(ed) > 0:
                    earnings_date = ed[0]
                elif isinstance(ed, (int, float)):
                    earnings_date = datetime.fromtimestamp(ed).strftime("%Y-%m-%d")
            if not earnings_date:
                ed_ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
                if ed_ts:
                    try:
                        earnings_date = datetime.fromtimestamp(ed_ts).strftime("%Y-%m-%d")
                    except (ValueError, OSError, TypeError):
                        pass

            rows.append({
                "ticker": ticker,
                "name": info.get("shortName", info.get("longName", "")),
                "earnings_date": earnings_date,
                "trailing_eps": info.get("trailingEps"),
                "forward_eps": info.get("forwardEps"),
                "recommendation": info.get("recommendationKey", ""),
                "market_cap": info.get("marketCap"),
                "sector": info.get("sector", ""),
            })
        return pd.DataFrame(rows)

    earnings_df = _get_earnings_info(tuple(tickers))

    # ── Merge with portfolio weights ──
    if "market_value" in enriched.columns:
        total_mv = pd.to_numeric(enriched["market_value"], errors="coerce").sum()
        weight_map = dict(zip(enriched[_t_col],
                              pd.to_numeric(enriched["market_value"], errors="coerce") / total_mv * 100))
        earnings_df["weight_pct"] = earnings_df["ticker"].map(weight_map).fillna(0)
    else:
        earnings_df["weight_pct"] = 0

    # ── Parse dates and calculate days until ──
    today = datetime.now().date()
    earnings_df["earnings_dt"] = pd.to_datetime(earnings_df["earnings_date"], errors="coerce")
    earnings_df["days_until"] = earnings_df["earnings_dt"].apply(
        lambda x: (x.date() - today).days if pd.notna(x) else None
    )

    # ── Filter Controls ──
    with st.sidebar:
        st.subheader("📅 Filters")
        show_past = st.checkbox("Show past earnings", value=False)
        days_ahead = st.slider("Days ahead", 7, 180, 60)

    # ── Separate into upcoming and unknown ──
    has_date = earnings_df[earnings_df["earnings_dt"].notna()].copy()
    no_date = earnings_df[earnings_df["earnings_dt"].isna()].copy()

    if not has_date.empty:
        if not show_past:
            has_date = has_date[has_date["days_until"] >= -1]  # Include today and yesterday
        upcoming = has_date[has_date["days_until"] <= days_ahead].sort_values("days_until")
    else:
        upcoming = pd.DataFrame()

    this_week = upcoming[upcoming["days_until"].between(0, 7)] if not upcoming.empty else pd.DataFrame()
    next_2_weeks = upcoming[upcoming["days_until"].between(0, 14)] if not upcoming.empty else pd.DataFrame()
    _tw_weight = this_week["weight_pct"].sum() if not this_week.empty else 0.0

    from core.ui_components import hero_metric, stat_grid
    from core.currency_normalizer import instrument_currency as _ec_ccy
    hero_metric(
        "Reporting this week",
        str(len(this_week)),
        delta=f"{_tw_weight:.1f}% of portfolio value" if _tw_weight else "",
        delta_value=_tw_weight or None,
        sub="Positions with a confirmed date in the next 7 days",
    )
    stat_grid([
        ("Next 2 weeks", str(len(next_2_weeks))),
        ("Weight reporting", f"{_tw_weight:.1f}%"),
        ("No date", str(len(no_date))),
    ], columns=3)

    st.divider()

    # ── Earnings Timeline ──
    if not upcoming.empty:
        st.markdown("### 📊 Upcoming Earnings")

        def _urgency_tag(days):
            if days is None:
                return ""
            if days <= 0:
                return "🔴 **TODAY/PAST**"
            elif days <= 3:
                return "🟠 **THIS WEEK**"
            elif days <= 7:
                return "🟡 This week"
            elif days <= 14:
                return "🔵 Next 2 weeks"
            return "⚪"

        display_rows = []
        for _, row in upcoming.iterrows():
            days = row["days_until"]
            urgency = _urgency_tag(days)
            display_rows.append({
                "": urgency,
                "Ticker": row["ticker"],
                "Company": (row["name"] or "")[:30],
                "Earnings Date": row["earnings_dt"].strftime("%b %d, %Y") if pd.notna(row["earnings_dt"]) else "—",
                "Days": f"{int(days)}" if pd.notna(days) else "—",
                "Weight %": f"{row['weight_pct']:.1f}%",
                # EPS is per-share, so it carries the listing's own currency.
                "Trail EPS": (f"{_ec_ccy(str(row.get('ticker','')))} {row['trailing_eps']:.2f}"
                              if pd.notna(row['trailing_eps']) else "—"),
                "Fwd EPS": (f"{_ec_ccy(str(row.get('ticker','')))} {row['forward_eps']:.2f}"
                            if pd.notna(row['forward_eps']) else "—"),
                "Sector": row["sector"],
            })

        display_df = pd.DataFrame(display_rows)
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Alert for imminent earnings
        imminent = upcoming[upcoming["days_until"].between(0, 3)]
        if not imminent.empty:
            tickers_str = ", ".join(imminent["ticker"].tolist())
            total_weight = imminent["weight_pct"].sum()
            st.warning(
                f"⚠️ **{len(imminent)} holding(s) report within 3 days:** {tickers_str} "
                f"({total_weight:.1f}% of portfolio). Consider reviewing positions before earnings."
            )
    else:
        st.info(f"No earnings dates found in the next {days_ahead} days.")

    # ── Unknown earnings dates ──
    if not no_date.empty and len(no_date) > 0:
        with st.expander(f"📋 {len(no_date)} holdings without earnings date", expanded=False):
            no_date_display = no_date[["ticker", "name", "weight_pct", "sector"]].copy()
            no_date_display["weight_pct"] = no_date_display["weight_pct"].apply(lambda x: f"{x:.1f}%")
            no_date_display.columns = ["Ticker", "Company", "Weight %", "Sector"]
            st.dataframe(no_date_display, use_container_width=True, hide_index=True)
            st.caption("Earnings dates may not be available for ETFs, mutual funds, or some international stocks.")


def transactions() -> None:

    import streamlit as st
    import pandas as pd
    from datetime import datetime, date

    from core.database import (
        get_all_holdings, save_transaction, get_transactions,
        delete_transaction, get_realized_pnl_summary, get_total_realized_pnl,
    )

    from core.ui_components import (page_header, hero_metric, stat_grid,
                                    render_responsive_table, fmt_compact)

    # ─────────────────────────────────────────
    # ADD TRANSACTION FORM
    # ─────────────────────────────────────────
    st.subheader("➕ Add Transaction")

    holdings = get_all_holdings()
    ticker_list = sorted(holdings["ticker"].dropna().unique().tolist(), key=str.upper) if not holdings.empty else []

    with st.form("add_transaction", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)

        with col1:
            txn_type = st.selectbox("Type", ["BUY", "SELL"])
            txn_ticker = st.text_input(
                "Ticker",
                placeholder="e.g. AAPL, EMAAR.AE",
                help="Enter a stock ticker. Must match the ticker in your portfolio.",
            )

        with col2:
            txn_date = st.date_input("Date", value=date.today(), max_value=date.today())
            txn_qty = st.number_input("Quantity", min_value=0.0001, value=1.0, step=1.0, format="%.4f")

        with col3:
            txn_price = st.number_input("Price per Share", min_value=0.0001, value=100.0, step=0.01, format="%.4f")
            txn_fees = st.number_input("Fees / Commission", min_value=0.0, value=0.0, step=0.01, format="%.2f")

        col_a, col_b = st.columns(2)
        with col_a:
            txn_currency = st.selectbox("Currency", ["USD", "AED", "EUR", "GBP", "INR", "SGD", "HKD", "CHF", "AUD", "CAD", "JPY"])
        with col_b:
            txn_broker = st.text_input("Broker (optional)", placeholder="e.g. IBKR, Zerodha")

        txn_notes = st.text_input("Notes (optional)", placeholder="e.g. Earnings play, rebalance")

        submitted = st.form_submit_button("💾 Save Transaction", type="primary", use_container_width=True)

        if submitted:
            if not txn_ticker.strip():
                st.error("Please enter a ticker symbol.")
            elif txn_qty <= 0:
                st.error("Quantity must be greater than zero.")
            elif txn_price <= 0:
                st.error("Price must be greater than zero.")
            else:
                # Look up name from holdings
                name_match = holdings[holdings["ticker"].str.upper() == txn_ticker.strip().upper()]
                txn_name = name_match.iloc[0]["name"] if not name_match.empty else None

                save_transaction(
                    ticker=txn_ticker.strip().upper(),
                    txn_type=txn_type,
                    quantity=txn_qty,
                    price=txn_price,
                    currency=txn_currency,
                    fees=txn_fees,
                    date=txn_date.isoformat(),
                    broker_source=txn_broker or None,
                    notes=txn_notes or None,
                    name=txn_name,
                )
                st.success(f"✅ {txn_type} {txn_qty:,.4f} × {txn_ticker.upper()} @ {txn_price:,.4f} saved!")
                st.rerun()

    st.divider()

    # ─────────────────────────────────────────
    # REALIZED P&L SUMMARY
    # ─────────────────────────────────────────
    st.subheader("📊 Realized P&L Summary")

    pnl_summary = get_realized_pnl_summary()

    if not pnl_summary.empty:
        total_realized = pnl_summary["realized_pnl"].sum()
        total_gains = pnl_summary[pnl_summary["realized_pnl"] > 0]["realized_pnl"].sum()
        total_losses = pnl_summary[pnl_summary["realized_pnl"] < 0]["realized_pnl"].sum()
        total_fees = pnl_summary["total_fees"].sum()

        hero_metric(
            "Net realized P&L",
            fmt_compact(total_realized, _base_ccy),
            delta="Profit" if total_realized >= 0 else "Loss",
            delta_value=total_realized,
            title=f"{_base_ccy} {total_realized:,.2f}",
        )
        stat_grid([
            ("Gains", fmt_compact(total_gains, _base_ccy), "", 1),
            ("Losses", fmt_compact(abs(total_losses), _base_ccy), "", -1),
            ("Fees", fmt_compact(total_fees, _base_ccy)),
        ], columns=3)

        # Per-ticker breakdown
        st.markdown("**Per-Ticker Breakdown**")
        display_pnl = pnl_summary.copy()
        display_pnl = display_pnl.rename(columns={
            "ticker": "Ticker",
            "total_bought_qty": "Total Bought",
            "total_sold_qty": "Total Sold",
            "avg_buy_price": "Avg Buy Price",
            "avg_sell_price": "Avg Sell Price",
            "realized_pnl": "Realized P&L",
            "total_fees": "Fees",
        })

        # Format numbers
        for col in ["Total Bought", "Total Sold"]:
            if col in display_pnl.columns:
                display_pnl[col] = display_pnl[col].apply(lambda x: f"{x:,.2f}")
        for col in ["Avg Buy Price", "Avg Sell Price"]:
            if col in display_pnl.columns:
                display_pnl[col] = display_pnl[col].apply(
                    lambda x: f"{_base_ccy} {x:,.4f}" if x > 0 else "—")
        if "Realized P&L" in display_pnl.columns:
            display_pnl["Realized P&L"] = display_pnl["Realized P&L"].apply(
                lambda x: f"{_base_ccy} {x:+,.2f}")
        if "Fees" in display_pnl.columns:
            display_pnl["Fees"] = display_pnl["Fees"].apply(lambda x: f"{_base_ccy} {x:,.2f}")

        show_cols = ["Ticker", "Total Bought", "Total Sold", "Avg Buy Price", "Avg Sell Price", "Realized P&L", "Fees"]
        show_cols = [c for c in show_cols if c in display_pnl.columns]

        from core.data_engine import clean_nan
        render_responsive_table(clean_nan(display_pnl[show_cols]), title_col="Ticker")
    else:
        st.info("No transactions recorded yet. Add buy/sell trades above to see realized P&L.")

    st.divider()

    # ─────────────────────────────────────────
    # TRANSACTION HISTORY
    # ─────────────────────────────────────────
    st.subheader("📜 Transaction History")

    # Filters
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:
        filter_ticker = st.text_input("Filter by Ticker", placeholder="Leave empty for all")
    with filter_col2:
        filter_type = st.selectbox("Filter by Type", ["All", "BUY", "SELL"])
    with filter_col3:
        filter_range = st.selectbox("Date Range", ["All Time", "Last 7 Days", "Last 30 Days", "Last 90 Days", "This Year"])

    # Calculate date range
    date_from = None
    if filter_range == "Last 7 Days":
        date_from = (datetime.now() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    elif filter_range == "Last 30 Days":
        date_from = (datetime.now() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    elif filter_range == "Last 90 Days":
        date_from = (datetime.now() - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    elif filter_range == "This Year":
        date_from = f"{datetime.now().year}-01-01"

    txns = get_transactions(
        ticker=filter_ticker.strip().upper() if filter_ticker.strip() else None,
        txn_type=filter_type if filter_type != "All" else None,
        date_from=date_from,
    )

    if not txns.empty:
        st.caption(f"Showing {len(txns)} transaction(s)")

        display_txns = txns.copy()
        display_txns = display_txns.rename(columns={
            "ticker": "Ticker",
            "name": "Name",
            "type": "Type",
            "quantity": "Quantity",
            "price": "Price",
            "currency": "Currency",
            "fees": "Fees",
            "date": "Date",
            "broker_source": "Broker",
            "notes": "Notes",
        })

        # Format numbers
        if "Quantity" in display_txns.columns:
            display_txns["Quantity"] = display_txns["Quantity"].apply(lambda x: f"{x:,.4f}")
        if "Price" in display_txns.columns:
            display_txns["Price"] = display_txns["Price"].apply(lambda x: f"{x:,.4f}")
        if "Fees" in display_txns.columns:
            display_txns["Fees"] = display_txns["Fees"].apply(
                lambda x: f"{_base_ccy} {x:,.2f}" if x > 0 else "—")

        show_cols = ["Date", "Ticker", "Name", "Type", "Quantity", "Price", "Currency", "Fees", "Broker", "Notes"]
        show_cols = [c for c in show_cols if c in display_txns.columns]

        from core.data_engine import clean_nan
        render_responsive_table(clean_nan(display_txns[show_cols]))

        # Export transactions
        csv_data = txns.to_csv(index=False)
        st.download_button(
            "📥 Export Transactions (CSV)",
            data=csv_data,
            file_name=f"prosper_transactions_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        # Delete transaction
        st.divider()
        with st.expander("🗑️ Delete a Transaction"):
            txn_ids = txns["id"].tolist()
            txn_labels = [
                f"#{row['id']} — {row['date']} — {row['type']} {row['quantity']:.2f} × {row['ticker']} @ {row['price']:.2f}"
                for _, row in txns.iterrows()
            ]
            selected_txn = st.selectbox("Select transaction to delete", txn_labels)
            if st.button("🗑️ Delete Selected Transaction", type="secondary"):
                idx = txn_labels.index(selected_txn)
                delete_transaction(txn_ids[idx])
                st.success("Transaction deleted!")
                st.rerun()
    else:
        st.info("No transactions found matching your filters.")

    st.divider()
    st.caption("ℹ️ Realized P&L is calculated using FIFO (First In, First Out) accounting method.")
