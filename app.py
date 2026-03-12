"""
Prosper — AI-Native Investment Operating System
Main entrypoint: page config, DB init, and navigation.
"""

import os
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv
from core.database import init_db, get_all_holdings, save_nav_snapshot, get_nav_snapshot_exists_today, get_total_realized_pnl

# Load .env from the same directory as app.py — works regardless of cwd
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_env_path, override=True)

st.set_page_config(
    page_title="Prosper",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

# ── Global currency filter (visible on every page) ────────────────────────────
_holdings_for_filter = get_all_holdings()
if not _holdings_for_filter.empty:
    _currencies = sorted(_holdings_for_filter["currency"].dropna().unique().tolist())
    with st.sidebar:
        st.session_state["global_currency_filter"] = st.selectbox(
            "🌐 Filter by Currency",
            ["All"] + _currencies,
            index=0,
            key="_currency_filter_widget",
        )
else:
    st.session_state.setdefault("global_currency_filter", "All")

# ── NAV Auto-Snapshot — save daily portfolio value ─────────────────────────────
# Runs once per day per base currency. Uses enriched data from session_state if available.
from core.settings import SETTINGS as _snap_settings
_snap_base = _snap_settings.get("base_currency", "USD")
_snap_cache_key = f"enriched_{_snap_base}"

if not get_nav_snapshot_exists_today(_snap_base):
    _snap_enriched = st.session_state.get(_snap_cache_key)
    if _snap_enriched is not None and not _snap_enriched.empty:
        try:
            import pandas as _snap_pd
            _total_val = _snap_pd.to_numeric(_snap_enriched.get("market_value"), errors="coerce").dropna().sum()
            _total_cost = _snap_pd.to_numeric(_snap_enriched.get("cost_basis"), errors="coerce").dropna().sum()
            _unrealized = _snap_pd.to_numeric(_snap_enriched.get("unrealized_pnl"), errors="coerce").dropna().sum()
            _realized = get_total_realized_pnl()

            if _total_val > 0:
                save_nav_snapshot(
                    date=datetime.now().strftime("%Y-%m-%d"),
                    total_value=float(_total_val),
                    total_cost=float(_total_cost) if _total_cost > 0 else None,
                    unrealized_pnl=float(_unrealized) if _unrealized != 0 else None,
                    realized_pnl=float(_realized) if _realized != 0 else None,
                    holdings_count=len(_snap_enriched),
                    base_currency=_snap_base,
                )
        except Exception:
            pass  # Silently skip if snapshot fails — non-critical

# ── Navigation — grouped into sections ─────────────────────────────────────────
pg = st.navigation({
    "Main": [
        st.Page("pages/home.py",                 title="Home",                icon="🏠", default=True),
        st.Page("pages/1_Upload_Portal.py",      title="Upload Portal",       icon="📤"),
        st.Page("pages/2_Portfolio_Dashboard.py", title="Portfolio Dashboard", icon="📊"),
    ],
    "Analysis": [
        st.Page("pages/4_Portfolio_Summary.py",  title="Portfolio Summary",   icon="🧩"),
        st.Page("pages/5_Performance.py",        title="Performance",         icon="📈"),
        st.Page("pages/7_Analyst_Consensus.py",  title="Analyst Consensus",   icon="🎯"),
        st.Page("pages/8_Sentiment.py",          title="Sentiment",           icon="💬"),
    ],
    "News": [
        st.Page("pages/3_Portfolio_News.py",     title="Portfolio News",      icon="📰"),
        st.Page("pages/6_Market_News.py",        title="Market News",         icon="🌍"),
    ],
    "Ownership": [
        st.Page("pages/9_Insider_Activity.py",   title="Insider Activity",    icon="👤"),
        st.Page("pages/10_Institutional.py",     title="Institutional",       icon="🏛️"),
    ],
    "Trading": [
        st.Page("pages/12_Transaction_Log.py",   title="Transaction Log",     icon="📝"),
        st.Page("pages/14_Watchlist.py",         title="Watchlist",           icon="👁️"),
        st.Page("pages/13_Export.py",            title="Export Reports",      icon="📥"),
    ],
    "Settings": [
        st.Page("pages/0_Settings.py",           title="Settings",            icon="⚙️"),
    ],
})

pg.run()
