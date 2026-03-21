"""
Prosper — AI-Native Investment Operating System
Main entrypoint: page config, DB init, authentication, and navigation.
v5.3 — Multi-portfolio, AI Chat, resolved ticker fixes
"""

import os
from datetime import datetime
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from core.database import init_db, get_all_holdings, save_nav_snapshot, get_nav_snapshot_exists_today, get_total_realized_pnl
try:
    from core.database import get_all_portfolios, create_portfolio, get_active_portfolio_id
except ImportError:
    # Fallback if database.py hasn't been updated yet (stale cache)
    def get_all_portfolios():
        import pandas as _pd
        return _pd.DataFrame({"id": [1], "name": ["Main Portfolio"], "description": [""]})
    def create_portfolio(name, description=""):
        return 1
    def get_active_portfolio_id():
        return 1

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

# ── Modern Font + Global Styling ─────────────────────────────────────────────
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
/* Tighter metric cards — NEVER truncate values */
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
[data-testid="stMetricValue"] > div {
    overflow: visible !important;
    text-overflow: unset !important;
    white-space: nowrap !important;
}
[data-testid="stMetricLabel"] {
    overflow: visible !important;
    text-overflow: unset !important;
    white-space: nowrap !important;
    font-size: 0.8rem !important;
}
[data-testid="stMetricDelta"] {
    overflow: visible !important;
    text-overflow: unset !important;
    white-space: nowrap !important;
}
/* Ensure metric containers and ALL parents don't clip content */
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
/* Column containers must not clip */
[data-testid="stColumn"],
[data-testid="stColumn"] > div,
[data-testid="stHorizontalBlock"] > div {
    overflow: visible !important;
}
/* Scrollable dataframes on all screens */
.stDataFrame { overflow-x: auto; }
/* Mobile responsive */
@media (max-width: 768px) {
    [data-testid="stSidebar"] { min-width: 180px !important; max-width: 220px !important; }
    .stDataFrame { font-size: 0.75rem; }
    h1 { font-size: 1.4rem !important; }
    h2 { font-size: 1.2rem !important; }
    h3 { font-size: 1.05rem !important; }
    /* Stack metric columns vertically */
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 4px !important; }
    [data-testid="stMetricValue"] { font-size: 1rem !important; overflow: visible !important; text-overflow: unset !important; white-space: nowrap !important; }
    [data-testid="stMetricValue"] > div { overflow: visible !important; text-overflow: unset !important; white-space: nowrap !important; }
    [data-testid="stMetricLabel"] { font-size: 0.7rem !important; overflow: visible !important; text-overflow: unset !important; white-space: nowrap !important; }
    /* Plotly charts: ensure they don't overflow */
    .js-plotly-plot { max-width: 100vw !important; overflow: hidden; }
    /* Tabs: smaller text */
    button[data-baseweb="tab"] { font-size: 0.8rem !important; padding: 4px 8px !important; }
}
</style>
""", unsafe_allow_html=True)

# ── Authentication ────────────────────────────────────────────────────────────
# 3-tier auth: (1) Streamlit Cloud native → (2) streamlit-authenticator fallback → (3) disabled
# Set PROSPER_AUTH_ENABLED=false in .env to skip all auth.
# Default: disabled on Streamlit Cloud (use Cloud's built-in auth), enabled locally

_is_cloud = os.getenv("STREAMLIT_SHARING_MODE") or os.getenv("IS_STREAMLIT_CLOUD") or os.path.exists("/mount/src")
_auth_default = "false" if _is_cloud else "true"
AUTH_ENABLED = os.getenv("PROSPER_AUTH_ENABLED", _auth_default).lower() in ("true", "1", "yes")
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


# ── Portfolio Selector ─────────────────────────────────────────────────────────
_portfolios_df = get_all_portfolios()
if not _portfolios_df.empty:
    _pf_names = _portfolios_df["name"].tolist()
    _pf_ids = _portfolios_df["id"].tolist()
    _current_pid = get_active_portfolio_id()
    _current_idx = _pf_ids.index(_current_pid) if _current_pid in _pf_ids else 0

    with st.sidebar:
        _selected_pf = st.selectbox(
            "Portfolio",
            _pf_names,
            index=_current_idx,
            key="_portfolio_selector",
        )
        _new_pid = _pf_ids[_pf_names.index(_selected_pf)]
        if _new_pid != st.session_state.get("active_portfolio_id"):
            st.session_state["active_portfolio_id"] = _new_pid
            # Clear cached data for old portfolio
            for _k in list(st.session_state.keys()):
                if _k.startswith("enriched_") or _k.startswith("_prosper_holdings_cache") or _k in ("extended_df", "last_refresh_time"):
                    del st.session_state[_k]
            st.rerun()

        with st.expander("Manage Portfolios", expanded=False):
            _new_pf_name = st.text_input("New portfolio name", key="_new_pf_name", placeholder="e.g. Retirement Fund")
            if st.button("Create", key="_create_pf_btn", use_container_width=True) and _new_pf_name.strip():
                try:
                    _new_id = create_portfolio(_new_pf_name.strip())
                    st.session_state["active_portfolio_id"] = _new_id
                    st.success(f"Created: {_new_pf_name.strip()}")
                    st.rerun()
                except Exception as _pf_err:
                    st.error(f"Could not create: {_pf_err}")

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
    "AI": [
        st.Page("pages/24_AI_Chat.py",           title="Ask Prosper",         icon="💬"),
    ],
    "Settings": [
        st.Page("pages/0_Settings.py",           title="Settings",            icon="⚙️"),
        st.Page("pages/1_Upload_Portal.py",      title="Upload Portal",       icon="📤"),
        st.Page("pages/17_User_Management.py",   title="Users",               icon="👥"),
    ],
})

pg.run()

# ── Floating "Ask Prosper" Chat Widget (appears on every page) ────────────────
# Uses a popover anchored to bottom-right corner via CSS
_chat_api_key = os.getenv("ANTHROPIC_API_KEY", "")
if _chat_api_key and _chat_api_key != "your_anthropic_api_key_here":
    # Floating button CSS
    st.markdown("""
    <style>
    /* Position the last popover as floating bottom-right chat button */
    div[data-testid="stPopover"]:last-of-type {
        position: fixed !important;
        bottom: 24px !important;
        right: 24px !important;
        z-index: 9999 !important;
    }
    div[data-testid="stPopover"]:last-of-type button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 50px !important;
        padding: 12px 20px !important;
        font-weight: 600 !important;
        font-size: 0.9rem !important;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4) !important;
    }
    div[data-testid="stPopover"]:last-of-type button:hover {
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6) !important;
        transform: translateY(-1px);
    }
    </style>
    """, unsafe_allow_html=True)

    with st.popover("💬 Ask Prosper", use_container_width=False):
        st.markdown("**Ask Prosper AI**")
        st.caption("Quick questions about your portfolio")

        # Initialize mini chat
        if "mini_chat" not in st.session_state:
            st.session_state["mini_chat"] = []

        # Show last 3 messages
        for msg in st.session_state["mini_chat"][-6:]:
            if msg["role"] == "user":
                st.markdown(f"**You:** {msg['content']}")
            else:
                st.markdown(f"**Prosper:** {msg['content']}")

        _q = st.text_input("Ask anything...", key="_mini_chat_input", label_visibility="collapsed")
        if _q:
            st.session_state["mini_chat"].append({"role": "user", "content": _q})
            try:
                import anthropic
                from core.settings import call_claude, SETTINGS as _s

                _base = _s.get("base_currency", "USD")
                _enr = st.session_state.get(f"enriched_{_base}")
                _ctx = "No portfolio loaded."
                if _enr is not None and not _enr.empty:
                    _tv = pd.to_numeric(_enr.get("market_value"), errors="coerce").sum()
                    _ctx = f"Portfolio: {len(_enr)} holdings, {_base} {_tv:,.0f} total value."

                _client = anthropic.Anthropic(api_key=_chat_api_key)
                _msgs = [{"role": m["role"], "content": m["content"]} for m in st.session_state["mini_chat"][-6:]]
                _resp = call_claude(
                    _client,
                    system=f"You are Prosper AI, a concise investment assistant. {_ctx} Be brief (2-3 sentences max).",
                    messages=_msgs,
                    max_tokens=300,
                    preferred_model="claude-sonnet-4-20250514",
                )
                _reply = _resp.content[0].text
                st.session_state["mini_chat"].append({"role": "assistant", "content": _reply})
                st.rerun()
            except Exception as _e:
                st.error(f"Error: {str(_e)[:80]}")

        if st.session_state.get("mini_chat"):
            if st.button("Clear", key="_mini_clear"):
                st.session_state["mini_chat"] = []
                st.rerun()
        st.page_link("pages/24_AI_Chat.py", label="Open Full Chat →", icon="💬")
