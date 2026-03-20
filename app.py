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
# 3-tier auth: (1) Streamlit Cloud native → (2) streamlit-authenticator fallback → (3) disabled
# Set PROSPER_AUTH_ENABLED=false in .env to skip all auth.

AUTH_ENABLED = os.getenv("PROSPER_AUTH_ENABLED", "true").lower() in ("true", "1", "yes")
_auth_method = None  # Track which auth method is active

if AUTH_ENABLED:
    # ── Tier 1: Streamlit Cloud built-in auth (Google/GitHub SSO) ─────────
    _cloud_user = None
    try:
        _cloud_user = st.context.user if hasattr(st, "context") and hasattr(st.context, "user") else None
    except Exception:
        pass
    if _cloud_user is None:
        try:
            _cloud_user = st.experimental_user if hasattr(st, "experimental_user") else None
        except Exception:
            pass

    if _cloud_user and getattr(_cloud_user, "email", None):
        # Authenticated via Streamlit Cloud
        _auth_method = "cloud"
        with st.sidebar:
            st.markdown(f"👤 **{_cloud_user.email}**")
            st.divider()
    else:
        # ── Tier 2: streamlit-authenticator (local/fallback) ──────────────
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

                if st.session_state.get("authentication_status") not in (True,):
                    # Modern centered login page with registration + social auth
                    _pad_l, _login_col, _pad_r = st.columns([1, 2, 1])
                    with _login_col:
                        st.markdown(
                            "<div style='text-align:center;margin-top:2rem'>"
                            "<h1 style='font-size:2.5rem;margin-bottom:0;letter-spacing:-1px'>Prosper</h1>"
                            "<p style='color:#888;margin-top:4px;font-size:1.1rem'>AI-Native Investment Operating System</p>"
                            "</div>",
                            unsafe_allow_html=True,
                        )

                        # ── Social Login Buttons ──
                        st.markdown(
                            "<div style='margin:1.5rem 0 0.5rem 0'>"
                            "<style>"
                            ".social-btn { display:flex; align-items:center; justify-content:center; gap:10px; "
                            "padding:10px 16px; border-radius:8px; font-weight:600; font-size:0.95rem; "
                            "cursor:pointer; width:100%; margin-bottom:10px; border:1px solid rgba(255,255,255,0.15); "
                            "text-decoration:none; color:#eee; transition:background 0.2s; }"
                            ".social-btn:hover { background:rgba(255,255,255,0.08) !important; }"
                            ".social-btn-google { background:rgba(66,133,244,0.12); }"
                            ".social-btn-github { background:rgba(255,255,255,0.05); }"
                            "</style>"
                            "</div>",
                            unsafe_allow_html=True,
                        )

                        # Google button
                        _google_client = os.getenv("GOOGLE_CLIENT_ID", "")
                        _github_client = os.getenv("GITHUB_CLIENT_ID", "")

                        _g1, _g2 = st.columns(2)
                        with _g1:
                            if st.button("Continue with Google", key="_google_login", use_container_width=True, type="secondary"):
                                if _google_client:
                                    st.session_state["_pending_oauth"] = "google"
                                    st.rerun()
                                else:
                                    st.info("Google login available on Streamlit Cloud or configure GOOGLE_CLIENT_ID in .env")
                        with _g2:
                            if st.button("Continue with GitHub", key="_github_login", use_container_width=True, type="secondary"):
                                if _github_client:
                                    st.session_state["_pending_oauth"] = "github"
                                    st.rerun()
                                else:
                                    st.info("GitHub login available on Streamlit Cloud or configure GITHUB_CLIENT_ID in .env")

                        st.markdown(
                            "<div style='text-align:center;margin:12px 0;color:#555;font-size:0.85rem'>"
                            "--- or sign in with your account ---</div>",
                            unsafe_allow_html=True,
                        )

                        _login_tab, _register_tab = st.tabs(["Sign In", "Create Account"])

                        with _login_tab:
                            authenticator.login()
                            if st.session_state.get("authentication_status") is False:
                                st.error("Invalid credentials.")

                        with _register_tab:
                            st.markdown("##### Create your Prosper account")
                            with st.form("register_form", clear_on_submit=True):
                                _reg_c1, _reg_c2 = st.columns(2)
                                with _reg_c1:
                                    _reg_first = st.text_input("First Name", key="_reg_first")
                                with _reg_c2:
                                    _reg_last = st.text_input("Last Name", key="_reg_last")
                                _reg_email = st.text_input("Email", placeholder="you@example.com", key="_reg_email")
                                _reg_pw = st.text_input("Password (min 6 characters)", type="password", key="_reg_pw")
                                _reg_pw2 = st.text_input("Confirm Password", type="password", key="_reg_pw2")
                                _reg_submit = st.form_submit_button("Create Account", type="primary", use_container_width=True)

                                if _reg_submit:
                                    _reg_errors = []
                                    if not _reg_email or "@" not in _reg_email:
                                        _reg_errors.append("Valid email address required.")
                                    if not _reg_first.strip() or not _reg_last.strip():
                                        _reg_errors.append("First and last name required.")
                                    if not _reg_pw or len(_reg_pw) < 6:
                                        _reg_errors.append("Password must be at least 6 characters.")
                                    if _reg_pw != _reg_pw2:
                                        _reg_errors.append("Passwords do not match.")

                                    # Derive username from email
                                    _reg_username = _reg_email.split("@")[0].lower().replace(".", "_").replace("-", "_").replace("+", "_") if _reg_email else ""
                                    _existing_users = _auth_config.get("credentials", {}).get("usernames", {})
                                    if _reg_username in _existing_users:
                                        _reg_errors.append(f"An account with this email already exists. Please sign in.")

                                    if _reg_errors:
                                        for _e in _reg_errors:
                                            st.error(_e)
                                    else:
                                        _hashed_pw = stauth.Hasher.hash(_reg_pw)
                                        _auth_config["credentials"]["usernames"][_reg_username] = {
                                            "email": _reg_email.strip(),
                                            "first_name": _reg_first.strip(),
                                            "last_name": _reg_last.strip(),
                                            "password": _hashed_pw,
                                            "role": "user",
                                        }
                                        with open(_auth_config_path, "w") as _wf:
                                            yaml.dump(_auth_config, _wf, default_flow_style=False)
                                        st.success(
                                            f"✅ Account created! Your username is **{_reg_username}**\n\n"
                                            f"Switch to the **Sign In** tab to log in."
                                        )

                    st.stop()

                # Authenticated — show user in sidebar
                _auth_method = "local"
                with st.sidebar:
                    st.markdown(f"👤 **{st.session_state.get('name', 'User')}**")
                    authenticator.logout("Logout", "sidebar")
                    st.divider()
            else:
                AUTH_ENABLED = False
        except ImportError:
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

# ── Navigation — 5 focused sections ──────────────────────────────────────────
pg = st.navigation({
    "Prosper": [
        st.Page("pages/00_Command_Center.py",    title="Command Center",      icon="🏠", default=True),
    ],
    "Portfolio": [
        st.Page("pages/2_Portfolio_Dashboard.py",  title="Dashboard",          icon="📊"),
        st.Page("pages/18_Risk_Strategy.py",       title="Risk & Strategy",    icon="🏰"),
        st.Page("pages/4_Portfolio_Summary.py",     title="Summary",            icon="🧩"),
        st.Page("pages/5_Performance.py",           title="Performance",        icon="📈"),
    ],
    "Research": [
        st.Page("pages/18_Equity_Deep_Dive.py",    title="Equity Deep Dive",   icon="🔬"),
        st.Page("pages/7_Analyst_Consensus.py",    title="Analyst Consensus",  icon="🎯"),
        st.Page("pages/8_Sentiment.py",            title="Sentiment",          icon="💬"),
        st.Page("pages/15_Prosper_AI_Analysis.py",  title="Prosper AI",         icon="🤖"),
        st.Page("pages/23_Peer_Comparison.py",      title="Peer Comparison",    icon="🔍"),
        st.Page("pages/21_Technical_Analysis.py",   title="Technical Analysis", icon="📉"),
    ],
    "Income & Calendar": [
        st.Page("pages/22_Dividend_Dashboard.py", title="Dividends",           icon="💰"),
        st.Page("pages/20_Earnings_Calendar.py",  title="Earnings Calendar",   icon="📅"),
    ],
    "News & Activity": [
        st.Page("pages/3_Portfolio_News.py",      title="Portfolio News",      icon="📰"),
        st.Page("pages/6_Market_News.py",         title="Market News",         icon="🌍"),
        st.Page("pages/12_Transaction_Log.py",   title="Transactions",        icon="📝"),
    ],
    "Settings": [
        st.Page("pages/0_Settings.py",           title="Settings",            icon="⚙️"),
        st.Page("pages/1_Upload_Portal.py",      title="Upload Portal",       icon="📤"),
        st.Page("pages/17_User_Management.py",   title="Users",               icon="👥"),
    ],
})

pg.run()
