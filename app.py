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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stMetricValue, .stMetricLabel,
.stDataFrame, .stTextInput input, .stSelectbox select, .stButton button,
[data-testid="stSidebar"], [data-testid="stHeader"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
h1, h2, h3, h4, h5, h6 {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    letter-spacing: -0.5px;
}
[data-testid="stMetricValue"] {
    font-weight: 600 !important;
    font-size: clamp(1rem, 2.2vw, 1.8rem) !important;
    overflow: visible !important;
    text-overflow: unset !important;
    white-space: nowrap !important;
    word-break: keep-all !important;
    min-width: 0;
    line-height: 1.3 !important;
}
[data-testid="stMetricValue"] > div,
[data-testid="stMetricLabel"],
[data-testid="stMetricDelta"] {
    overflow: visible !important;
    text-overflow: unset !important;
    white-space: nowrap !important;
}
[data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
[data-testid="stMetric"],
[data-testid="metric-container"],
[data-testid="stMetric"] > div,
[data-testid="stMetric"] > div > div,
[data-testid="stMetric"] label,
[data-testid="stMetric"] label > div {
    overflow: visible !important;
    min-width: 0;
    text-overflow: unset !important;
}
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
    "Prosper": [
        st.Page("pages/00_Command_Center.py", title="Command Center", icon="🏠", default=True),
    ],
    "Portfolio": [
        st.Page("pages/2_Portfolio_Dashboard.py", title="Dashboard", icon="📊"),
        st.Page("pages/4_Portfolio_Summary.py", title="Summary", icon="🧩"),
        st.Page("pages/5_Performance.py", title="Performance", icon="📈"),
        st.Page("pages/18_Risk_Strategy.py", title="Risk & Strategy", icon="🏰"),
        st.Page("pages/22_Dividend_Dashboard.py", title="Dividends", icon="💰"),
        st.Page("pages/20_Earnings_Calendar.py", title="Earnings Calendar", icon="📅"),
    ],
    "Research & AI": [
        st.Page("pages/13_Research_Hub.py", title="Research Hub", icon="🔭"),
        st.Page("pages/18_Equity_Deep_Dive.py", title="Equity Deep Dive", icon="🔬"),
        st.Page("pages/7_Analyst_Consensus.py", title="Analyst Consensus", icon="🎯"),
        st.Page("pages/8_Sentiment.py", title="Sentiment", icon="💬"),
        st.Page("pages/23_Peer_Comparison.py", title="Peer Comparison", icon="🔍"),
        st.Page("pages/21_Technical_Analysis.py", title="Technical Analysis", icon="📉"),
        st.Page("pages/15_GROW_Analysis.py", title="GROW Engine", icon="🌱"),
        st.Page("pages/24_AI_Chat.py", title="Ask Prosper", icon="💬"),
    ],
    "News & Activity": [
        st.Page("pages/3_Portfolio_News.py", title="Portfolio News", icon="📰"),
        st.Page("pages/6_Market_News.py", title="Market News", icon="🌍"),
        st.Page("pages/12_Transaction_Log.py", title="Transactions", icon="📝"),
    ],
    "Settings": [
        st.Page("pages/0_Settings.py", title="Settings", icon="⚙️"),
        st.Page("pages/1_Upload_Portal.py", title="Upload Portal", icon="📤"),
        st.Page("pages/25_IBKR_Sync.py", title="IBKR Sync", icon="🔗"),
        st.Page("pages/17_User_Management.py", title="Users", icon="👥"),
        st.Page("pages/26_Onboarding.py", title="Onboarding", icon="🚀"),
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

# ── Mobile bottom navigation ───────────────────────────────────────────────
# Rendered BEFORE pg.run(), not after: 21 of the 24 pages call st.stop() on an
# empty state or a missing prerequisite, and st.stop() halts the whole script —
# so anything after pg.run() never renders on exactly the pages where the user
# most needs a way out. The bar is position:fixed, so DOM order costs nothing.
from core.ui_components import bottom_nav as _bottom_nav
_bottom_nav()

pg.run()

# ── Floating Chat Widget ───────────────────────────────────────────────────
# Skip on the full "Ask Prosper" chat page itself — that page already has its
# own st.chat_input(). Two independent chat widgets on one page, each with
# their own session-state and st.rerun() calls, is a plausible cause of the
# navigation feeling "stuck" there (reported: clicking any other sidebar link
# while on Ask Prosper keeps landing back on it).
_chat_key = os.getenv("ANTHROPIC_API_KEY", "")
if _chat_key and _chat_key != "your_anthropic_api_key_here" and pg.title != "Ask Prosper":
    st.markdown("""
    <style>
    div[data-testid="stPopover"]:last-of-type {
        position: fixed !important;
        bottom: 24px !important;
        right: 24px !important;
        z-index: 9999 !important;
    }
    div[data-testid="stPopover"]:last-of-type button {
        /* UX audit finding: this was the one hand-styled visual moment in
           the whole app, and it used a generic purple-to-indigo AI-product
           gradient (#667eea -> #764ba2) instead of Prosper's own color
           language. Replaced with the same blue already used for the
           "Recovery" FORTRESS regime (core/fortress.py REGIME_COLORS) —
           the app's own accent, not a borrowed one. */
        background: linear-gradient(135deg, #0984e3 0%, #0a6bb3 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 50px !important;
        padding: 12px 20px !important;
        font-weight: 600 !important;
        font-size: 0.9rem !important;
        box-shadow: 0 4px 15px rgba(9, 132, 227, 0.4) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    with st.popover("💬 Ask Prosper", use_container_width=False):
        st.markdown("**Ask Prosper AI**")
        st.caption("Quick questions about your portfolio")

        if "mini_chat" not in st.session_state:
            st.session_state["mini_chat"] = []

        for msg in st.session_state["mini_chat"][-6:]:
            role = "You" if msg["role"] == "user" else "Prosper"
            st.markdown(f"**{role}:** {msg['content']}")

        _q = st.text_input("Ask anything...", key="_mini_chat_input", label_visibility="collapsed")
        import time as _time
        _CHAT_COOLDOWN = 3
        _CHAT_MAX_MSGS = 30
        _last_chat = st.session_state.get("_mini_chat_last_ts", 0)
        if _q and (_time.time() - _last_chat) < _CHAT_COOLDOWN:
            st.warning("Please wait a moment before sending another message.")
            _q = None
        if _q and len(st.session_state.get("mini_chat", [])) >= _CHAT_MAX_MSGS:
            st.warning("Session chat limit reached. Clear chat or use the full chat page.")
            _q = None
        if _q:
            st.session_state["_mini_chat_last_ts"] = _time.time()
            _CHAT_HISTORY_CAP = 20
            st.session_state["mini_chat"].append({"role": "user", "content": _q[:2000]})
            if len(st.session_state["mini_chat"]) > _CHAT_HISTORY_CAP:
                st.session_state["mini_chat"] = st.session_state["mini_chat"][-_CHAT_HISTORY_CAP:]
            try:
                import anthropic
                from core.settings import call_claude, extract_text, SETTINGS, CLAUDE_DEFAULT_MODEL
                from core.settings import enriched_cache_key as _eck
                _enr = st.session_state.get(_eck(SETTINGS.get('base_currency', 'USD')))
                _ctx = "No portfolio loaded."
                if _enr is not None and not _enr.empty:
                    _tv = pd.to_numeric(_enr.get("market_value"), errors="coerce").sum()
                    _ctx = f"Portfolio: {len(_enr)} holdings, {SETTINGS.get('base_currency', 'USD')} {_tv:,.0f} total value."
                client = anthropic.Anthropic(api_key=_chat_key)
                msgs = [{"role": m["role"], "content": m["content"]} for m in st.session_state["mini_chat"][-6:]]
                # This call used to run with no loading indicator at all — the
                # popover just sat there looking frozen for the whole response
                # time, which read as "Ask Prosper takes ages" even when the
                # actual latency was normal.
                with st.spinner("Thinking..."):
                    resp = call_claude(
                        client,
                        system=f"You are Prosper AI, a concise investment assistant. {_ctx} Be brief (2-3 sentences max).",
                        messages=msgs,
                        max_tokens=300,
                        preferred_model=CLAUDE_DEFAULT_MODEL,
                    )
                st.session_state["mini_chat"].append({"role": "assistant", "content": extract_text(resp)})
                if len(st.session_state["mini_chat"]) > _CHAT_HISTORY_CAP:
                    st.session_state["mini_chat"] = st.session_state["mini_chat"][-_CHAT_HISTORY_CAP:]
                st.rerun()
            except Exception as e:
                fetch_failed("the assistant's reply", e)

        if st.session_state.get("mini_chat"):
            if st.button("Clear", key="_mini_clear"):
                st.session_state["mini_chat"] = []
                st.rerun()
        st.page_link("pages/24_AI_Chat.py", label="Open Full Chat →", icon="💬")
