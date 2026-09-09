"""
Prosper — AI-Native Investment Operating System
Main entrypoint: page config, DB init, authentication, and navigation.
v6.5 — Fix: init_db() deferred after auth so login page renders instantly.
"""

import os
from datetime import datetime

import streamlit as st
import pandas as pd
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_env_path, override=True)

# ── Page Config (must be FIRST Streamlit command) ────────────────────────────
st.set_page_config(
    page_title="Prosper",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",  # Sidebar starts hidden — no flash
)

# ── SIDEBAR HIDE — injected immediately after set_page_config ────────────────
# Must happen before ANYTHING else renders (DB init, auth, imports).
from core.auth import SIDEBAR_HIDE_CSS as _SIDEBAR_HIDE_CSS
_is_authed_early = st.session_state.get("authentication_status") is True
if not _is_authed_early:
    st.html(_SIDEBAR_HIDE_CSS)

# v7.0.1 FIX: the "Continue with Google" render guard is a PER-SCRIPT-RUN guard
# (it stops the button rendering twice in one run). v6.6 stopped clearing it, so
# after the first rerun of a session — typing in the login form, a widget click,
# the cookie check — the Google button silently vanished for good. Clear it here,
# at the top of every run; the OAuth callback branches inside
# _show_google_signin() are evaluated before the guard, so nothing is lost.
st.session_state.pop("_google_auth_rendered_this_rerun", None)

# ── Global Styling ───────────────────────────────────────────────────────────
# The mobile design system ships app-wide from here, so every page — including
# the ones never individually converted (Settings, Upload Portal, IBKR Sync,
# Users, News) — gets the 44px tap targets, reclaimed block padding, hidden
# Plotly modebar and faded tab strips without needing to be edited.
from core.ui_components import mobile_shell as _mobile_shell
_mobile_shell()


st.markdown("""
<style>
/* One face, loaded once. This block imported Inter and forced it onto every
   element with !important, while core/ledger_ui declares IBM Plex Sans as the
   product face — so two families fought over the same nodes and which one won
   depended on emission order. Plex is also already the chart font
   (ui_components._CHART_FONT), so this makes the interface and the charts
   agree instead of disagreeing. */
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stDataFrame,
.stTextInput input, .stSelectbox select, .stButton button,
[data-testid="stSidebar"], [data-testid="stHeader"] {
    font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
h1, h2, h3, h4, h5, h6 {
    font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    letter-spacing: -0.02em;
}
/* The st.metric block that stood here is gone (P2-9, done properly this
   time). It carried twelve overflow and sizing rules for a widget the app no
   longer calls — all 23 remaining .metric() calls moved to stat_row / kv in
   Push 18. It was also the last thing in app.py competing with the design
   system for the same selectors.

   Reverted once before, in Phase 2, because the grep that declared st.metric
   dead missed `colN.metric(...)` on column objects. Verified by count this
   time: zero .metric( call sites in pages/ or core/. */
[data-testid="stColumn"],
[data-testid="stColumn"] > div,
[data-testid="stHorizontalBlock"] > div {
    overflow: visible !important;
}
.stDataFrame { overflow-x: auto; }
@media (max-width: 768px) {
    [data-testid="stSidebar"] { min-width: 180px !important; max-width: 220px !important; }
    .stDataFrame { font-size: 0.75rem; }
    h1 { font-size: 1.4rem !important; }
    h2 { font-size: 1.2rem !important; }
    h3 { font-size: 1.05rem !important; }
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 4px !important; }
    [data-testid="stMetricValue"] { font-size: 1rem !important; }
    .js-plotly-plot { max-width: 100vw !important; overflow: hidden; }
    button[data-baseweb="tab"] { font-size: 0.8rem !important; padding: 4px 8px !important; }
}
</style>
""", unsafe_allow_html=True)

# ── Navigation & Auth ────────────────────────────────────────────────────────
# v6.5: run_auth() BEFORE init_db() so the login page renders instantly.
# init_db() can take 2-4s on cold start — deferring it means the login UI
# is visible immediately rather than after a blank loading screen.
from core.auth import run_auth as _run_auth

_is_authed = st.session_state.get("authentication_status") is True

if not _is_authed:
    # v7.0.3 FIX: the Google popup lands on /OAuth_Callback, which was never registered
    # with st.navigation → "Page not found" and the sign-in could never complete.
    _oauth_page = st.Page("pages/99_OAuth_Callback.py", title="Signing in…", url_path="OAuth_Callback")
    pg = st.navigation(
        [st.Page("pages/00_Command_Center.py", default=True), _oauth_page],
        position="hidden",
    )
    if getattr(pg, "url_path", "") == "OAuth_Callback":
        pg.run()
        st.stop()
    _run_auth()
    if st.session_state.get("authentication_status") is True:
        st.rerun()
    st.stop()

# ── Database Init (deferred — only runs after login) ─────────────────────────
from core.database import (
    init_db,
    get_all_holdings,
    save_nav_snapshot,
    get_nav_snapshot_exists_today,
    get_total_realized_pnl,
)
from core.database import get_all_portfolios, create_portfolio, get_active_portfolio_id
from core.ui_errors import unexpected, fetch_failed
from core.database import get_or_create_user_portfolios

init_db()

# ── Authenticated ─────────────────────────────────────────────────────────────
_run_auth()

# ── Load this user's saved preferences into SETTINGS (once per session) ──────
# v6.7 FIX: previously saved preferences (base currency, columns, …) were never
# loaded at startup, so every restart/redeploy silently reverted to defaults.
from core.settings import ensure_settings_loaded as _ensure_settings_loaded
_ensure_settings_loaded()

# Phase 3 design system (core/ledger_ui.py): tokens + ruled components.
#
# MUST come after _ensure_settings_loaded(). design_shell() reads the user's
# theme from SETTINGS, and when it ran before the load it always saw an empty
# proxy and fell back to light — so the dark toggle silently did nothing. Found
# in the preview harness; no headless test can see it, because the bug is in
# the ORDER of two calls that both succeed.
#
# Still before pg.run(), which is the other constraint: 21 of the 24 pages call
# st.stop(), so anything after pg.run() never renders on exactly those pages.
from core.ledger_ui import design_shell as _design_shell
_design_shell()

# ── Onboarding Check ────────────────────────────────────────────────────────
if "onboarding_complete" not in st.session_state:
    from core.settings import load_user_settings
    prefs = load_user_settings()
    if prefs.get("onboarding_complete", False):
        st.session_state["onboarding_complete"] = True

if not st.session_state.get("onboarding_complete", False):
    _existing_holdings = get_all_holdings()
    if not _existing_holdings.empty:
        st.session_state["onboarding_complete"] = True
        from core.settings import save_user_settings
        save_user_settings({"onboarding_complete": True})

if not st.session_state.get("onboarding_complete", False):
    pg = st.navigation(
        [st.Page("pages/26_Onboarding.py", title="Setup Wizard", icon="🚀", default=True)],
        position="hidden",
    )
    pg.run()
    st.stop()

# ── Portfolio Selector ──────────────────────────────────────────────────────
_user_id = st.session_state.get("user_id", "default")
_portfolios = get_or_create_user_portfolios(_user_id)

if not _portfolios.empty:
    _names = _portfolios["name"].tolist()
    _ids = _portfolios["id"].tolist()
    _active = get_active_portfolio_id()
    _idx = _ids.index(_active) if _active in _ids else 0

    with st.sidebar:
        _sel = st.selectbox("Portfolio", _names, index=_idx, key="_portfolio_selector")
        _new_id = _ids[_names.index(_sel)]
        if _new_id != st.session_state.get("active_portfolio_id"):
            st.session_state["active_portfolio_id"] = _new_id
            _clear_prefixes = ("enriched_", "_prosper_holdings_cache", "sentiment_data_", "_de_")
            _clear_exact = {"extended_df", "last_refresh_time", "summary_info_map",
                            "portfolio_returns_cache", "portfolio_returns_ts",
                            "chat_messages", "mini_chat"}
            for k in list(st.session_state.keys()):
                if any(k.startswith(p) for p in _clear_prefixes) or k in _clear_exact:
                    del st.session_state[k]
            st.rerun()

        with st.expander("Manage Portfolios", expanded=False):
            _new_name = st.text_input("New portfolio name", key="_new_pf_name", placeholder="e.g. Retirement Fund")
            if st.button("Create", key="_create_pf_btn", use_container_width=True) and _new_name.strip():
                try:
                    new_id = create_portfolio(_new_name.strip())
                    st.session_state["active_portfolio_id"] = new_id
                    st.success(f"Created: {_new_name.strip()}")
                    st.rerun()
                except Exception as e:
                    unexpected("the new portfolio", e)

# ── Currency Filter ─────────────────────────────────────────────────────────
_holdings = get_all_holdings()
if not _holdings.empty:
    _currencies = sorted(_holdings["currency"].dropna().unique().tolist())
    with st.sidebar:
        st.session_state["global_currency_filter"] = st.selectbox(
            "🌐 Filter by Currency",
            ["All"] + _currencies,
            index=0,
            key="_currency_filter_widget",
        )
else:
    st.session_state.setdefault("global_currency_filter", "All")

# ── NAV Auto-Snapshot ───────────────────────────────────────────────────────
from core.settings import SETTINGS as _settings, enriched_cache_key as _enriched_cache_key

_base = _settings.get("base_currency", "USD")
_cache_key = _enriched_cache_key(_base)

if not get_nav_snapshot_exists_today(_base):
    _enriched = st.session_state.get(_cache_key)
    if _enriched is not None and not _enriched.empty:
        try:
            total_val = pd.to_numeric(_enriched.get("market_value"), errors="coerce").dropna().sum()
            total_cost = pd.to_numeric(_enriched.get("cost_basis"), errors="coerce").dropna().sum()
            unrealized = pd.to_numeric(_enriched.get("unrealized_pnl"), errors="coerce").dropna().sum()
            realized = get_total_realized_pnl()
            if total_val > 0:
                save_nav_snapshot(
                    date=datetime.now().strftime("%Y-%m-%d"),
                    total_value=float(total_val),
                    total_cost=float(total_cost) if total_cost > 0 else None,
                    unrealized_pnl=float(unrealized) if unrealized != 0 else None,
                    realized_pnl=float(realized) if realized != 0 else None,
                    holdings_count=len(_enriched),
                    base_currency=_base,
                )
        except Exception as nav_err:
            import logging
            logging.getLogger("prosper").warning(f"NAV snapshot failed: {nav_err}")

# ── Full Navigation ──────────────────────────────────────────────────────────
pg = st.navigation({
    "Today": [
        st.Page("pages/00_Command_Center.py", title="Today", icon="🏠", default=True),
    ],
    "Portfolio": [
        st.Page("pages/2_Portfolio_Dashboard.py", title="Holdings", icon="📊"),
        st.Page("pages/4_Portfolio_Summary.py", title="Allocation", icon="🧩"),
        st.Page("pages/5_Performance.py", title="Performance", icon="📈"),
        st.Page("pages/18_Risk_Strategy.py", title="Risk", icon="🏰"),
        st.Page("pages/22_Dividend_Dashboard.py", title="Income", icon="💰"),
    ],
    # Split by what the page is FOR, not by what it is made of.
    #
    # "Decide" holds the four surfaces that produce an action: a Durability score and
    # price ladder, an options ticket, a single-name workup, and the assistant.
    #
    # "Signals" holds the rest. GROW §6.2 is explicit that aggregator data — analyst
    # consensus, headline sentiment, screen-derived technicals, peer multiples — is
    # Tier 5, confirmation only, and never price-setting. They sat beside GROW in one
    # undifferentiated "Research & AI" list of nine, which invites reading a sell-side
    # target as if it carried the same weight as the framework's own arithmetic. The
    # group name now says what they are.
    "Decide": [
        st.Page("pages/15_GROW_Analysis.py", title="Evaluate", icon="🌱"),
        st.Page("pages/19_Options_Desk.py", title="Options", icon="🌾"),
        st.Page("pages/18_Equity_Deep_Dive.py", title="Security", icon="🔬"),
        st.Page("pages/24_AI_Chat.py", title="Ask", icon="💬"),
    ],
    # These four were siblings of Security in a flat list of nine, which is
    # what made "which do I open first?" a real question and spawned Research
    # Hub — a page whose entire content was an answer to it.
    #
    # They are NOT merged into Security as tabs, deliberately. Streamlit tabs
    # are eager: every hidden tab is built and shipped on every render, and
    # these are 549 / 434 / 272 lines against Security's 57 / 89 / 162-line
    # summaries of the same ground. Folding them in would render four deep
    # analyses on every visit to a page most visits never drill past — on a
    # 512MiB / 0.15vCPU instance that is a real regression, not a tidy-up.
    #
    # Instead Security is the entry point and publishes `research_ticker`, and
    # each of its thin tabs links here for the full version, arriving on the
    # same stock. The group name says the relationship.
    "Security — full analysis": [
        st.Page("pages/7_Analyst_Consensus.py", title="Analyst Consensus", icon="🎯"),
        st.Page("pages/8_Sentiment.py", title="Sentiment", icon="💬"),
        st.Page("pages/23_Peer_Comparison.py", title="Peer Comparison", icon="🔍"),
        st.Page("pages/21_Technical_Analysis.py", title="Technical Analysis", icon="📉"),
    ],
    # Portfolio News, Market News, Earnings and Transactions were four
    # destinations answering one question — what happened, and does it touch
    # me? They are one page now, sliced by a segmented control. Portfolio News
    # used to carry a caption pointing at Market News for fund coverage, which
    # was the product admitting the split was arbitrary.
    "Activity": [
        st.Page("pages/9_Activity.py", title="Activity", icon="📰"),
    ],
    "Settings": [
        st.Page("pages/0_Settings.py", title="Settings", icon="⚙️"),
        st.Page("pages/1_Upload_Portal.py", title="Add holdings", icon="📤"),
        st.Page("pages/25_IBKR_Sync.py", title="Connections", icon="🔗"),
        st.Page("pages/17_User_Management.py", title="Account & access", icon="👥"),
        st.Page("pages/26_Onboarding.py", title="Setup", icon="🚀"),
    ],
})

# ── IBKR daily price backfill ──────────────────────────────────────────────
# First authenticated run of each calendar day, pull IBKR's own mark price for
# every position and write it into price_cache where nothing live exists.
# This is what puts a number on the UAE (ADX/DFM), European fund and offshore
# lines that no free quote API covers — see core/ibkr_prices for why it uses
# the Flex Query web service and not the IBKR MCP connector.
try:
    from core.ibkr_prices import maybe_daily_refresh as _ibkr_daily
    _ibkr_daily()
except Exception:
    pass

# Committed IBKR mark snapshot (data/ibkr_marks.json, refreshed by hand with
# scripts/refresh_ibkr_marks.py). Writes those marks into
# holdings.last_known_price once a day so UAE / fund / suspended lines that no
# free quote API can reach still show a value. Independent of the Flex web
# service above — this is the path that actually runs today.
try:
    from core.ibkr_prices import apply_static_marks_to_holdings as _ibkr_static
    _ibkr_static()
except Exception:
    pass

# ── Mobile bottom navigation ───────────────────────────────────────────────
# Rendered BEFORE pg.run(), not after: 21 of the 24 pages call st.stop() on an
# empty state or a missing prerequisite, and st.stop() halts the whole script —
# so anything after pg.run() never renders on exactly the pages where the user
# most needs a way out. The bar is position:fixed, so DOM order costs nothing.
from core.ui_components import bottom_nav as _bottom_nav
_bottom_nav()

# Reload if the socket dies while the tab is backgrounded — the "Connecting…" hang that
# only happens on phones. Rendered before pg.run() for the same reason bottom_nav is:
# 21 of the 24 pages call st.stop(), which halts the whole script.
from core.ui_components import connection_watchdog as _conn_watchdog
_conn_watchdog()

pg.run()

# The floating "Ask Prosper" popover was removed here (Phase 3, P3-1).
# It rendered AFTER pg.run() with position:fixed bottom/right, so it (a)
# overlapped the bottom nav bar, (b) duplicated that bar's 5th slot, which
# already opens pages/24_AI_Chat.py, and (c) silently vanished on the 21
# pages that call st.stop(). One route to the assistant, not two.
