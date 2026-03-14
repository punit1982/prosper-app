"""
Prosper — AI-Native Investment Operating System
Main entrypoint: page config, DB init, authentication, and navigation.
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

# ── Authentication ────────────────────────────────────────────────────────────
# Uses streamlit-authenticator for email/password login.
# Auth can be disabled by setting PROSPER_AUTH_ENABLED=false in .env

AUTH_ENABLED = os.getenv("PROSPER_AUTH_ENABLED", "true").lower() in ("true", "1", "yes")

if AUTH_ENABLED:
    try:
        import yaml
        import streamlit_authenticator as stauth

        _auth_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_config.yaml")

        if os.path.exists(_auth_config_path):
            with open(_auth_config_path) as _f:
                _auth_config = yaml.safe_load(_f)

            authenticator = stauth.Authenticate(
                _auth_config["credentials"],
                _auth_config["cookie"]["name"],
                _auth_config["cookie"]["key"],
                _auth_config["cookie"]["expiry_days"],
            )

            authenticator.login()

            if st.session_state.get("authentication_status") is None:
                st.info("Please enter your credentials to access Prosper.")
                st.caption("Default login: **admin** / **prosper2026**")

                # Registration form
                with st.expander("📝 New User? Register Here"):
                    try:
                        email, username, name = authenticator.register_user(pre_authorization=False)
                        if email:
                            # Save updated credentials back to YAML
                            with open(_auth_config_path, "w") as _wf:
                                yaml.dump(_auth_config, _wf, default_flow_style=False)
                            st.success(f"User **{username}** registered successfully! You can now log in.")
                    except Exception as reg_err:
                        st.error(str(reg_err))

                st.stop()

            elif st.session_state.get("authentication_status") is False:
                st.error("Invalid username or password.")
                st.stop()

            # User is authenticated — show logout in sidebar
            with st.sidebar:
                st.markdown(f"👤 **{st.session_state.get('name', 'User')}**")
                authenticator.logout("Logout", "sidebar")
                st.divider()

        else:
            # No auth config file — skip authentication
            AUTH_ENABLED = False

    except ImportError:
        # streamlit-authenticator not installed — skip authentication
        AUTH_ENABLED = False
    except Exception as auth_err:
        st.warning(f"Authentication error: {auth_err}. Running without login.")
        AUTH_ENABLED = False


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

# ── Navigation — grouped into 4 clean sections ───────────────────────────────
pg = st.navigation({
    "Portfolio": [
        st.Page("pages/1_Upload_Portal.py",      title="Upload Portal",       icon="📤"),
        st.Page("pages/2_Portfolio_Dashboard.py", title="Portfolio Dashboard", icon="📊", default=True),
        st.Page("pages/4_Portfolio_Summary.py",   title="Portfolio Summary",   icon="🧩"),
        st.Page("pages/5_Performance.py",         title="Performance",         icon="📈"),
    ],
    "Research": [
        st.Page("pages/7_Analyst_Consensus.py",    title="Analyst Consensus",  icon="🎯"),
        st.Page("pages/8_Sentiment.py",            title="Sentiment",          icon="💬"),
        st.Page("pages/18_Equity_Deep_Dive.py",    title="Equity Deep Dive",   icon="🔬"),
        st.Page("pages/15_Prosper_AI_Analysis.py",  title="Prosper AI",         icon="🤖"),
    ],
    "Activity": [
        st.Page("pages/12_Transaction_Log.py",   title="Transaction Log",     icon="📝"),
        st.Page("pages/3_Portfolio_News.py",      title="Portfolio News",      icon="📰"),
        st.Page("pages/6_Market_News.py",         title="Market News",         icon="🌍"),
    ],
    "Settings": [
        st.Page("pages/0_Settings.py",           title="Settings",            icon="⚙️"),
        st.Page("pages/17_User_Management.py",   title="User Management",    icon="👥"),
    ],
})

pg.run()
