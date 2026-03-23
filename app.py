"""
Prosper — AI-Native Investment Operating System
Main entrypoint: page config, DB init, authentication, and navigation.
v5.4 — Multi-user auth, user-scoped portfolios, Cloud SSO support
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

# Import user-scoped portfolio helper (created by another agent in database.py)
try:
    from core.database import get_or_create_user_portfolios
except ImportError:
    # Fallback: if function doesn't exist yet, delegate to get_all_portfolios
    def get_or_create_user_portfolios(user_id):
        return get_all_portfolios()

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
# 3-tier auth:
#   (1) Streamlit Cloud native (st.context.user) — platform handles SSO
#   (2) streamlit-authenticator (local YAML-based login)
#   (3) Auth disabled — user_id = "default", everything works as before
# Set PROSPER_AUTH_ENABLED=false in .env to skip all auth.

_is_cloud = bool(
    os.getenv("STREAMLIT_SHARING_MODE") or os.getenv("IS_STREAMLIT_CLOUD")
    or os.path.exists("/mount/src") or os.path.exists("/home/adminuser")
)

AUTH_ENABLED = os.getenv("PROSPER_AUTH_ENABLED", "true").lower() in ("true", "1", "yes")
# Auth works everywhere — Cloud users get YAML-based login just like local

_auth_method = None  # Track which auth method is active
_is_authenticated = False  # Gate for navigation rendering


def _do_logout():
    """Clear ALL session state keys related to user data on logout."""
    _keys_to_clear = []
    for _k in list(st.session_state.keys()):
        if (_k.startswith("enriched_") or _k.startswith("_prosper_holdings_cache")
                or _k in ("extended_df", "last_refresh_time", "active_portfolio_id",
                          "user_id", "mini_chat", "global_currency_filter",
                          "authentication_status", "username", "name", "logout")):
            _keys_to_clear.append(_k)
    for _k in _keys_to_clear:
        try:
            del st.session_state[_k]
        except KeyError:
            pass


# ── Tier 0: Cloud user detection (runs regardless of AUTH_ENABLED) ────────
# On Streamlit Cloud with viewer auth enabled, st.context.user has the email.
# We always try to grab this so user_id is set even when AUTH_ENABLED=False on Cloud.
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

_cloud_email = None
if _cloud_user:
    _cloud_email = getattr(_cloud_user, "email", None)
    # Some versions return a dict-like object
    if _cloud_email is None and isinstance(_cloud_user, dict):
        _cloud_email = _cloud_user.get("email")
    # Treat anonymous/empty as no user
    if _cloud_email and _cloud_email.lower() in ("", "anonymous", "null", "none"):
        _cloud_email = None

if _cloud_email:
    # Cloud SSO detected — user is authenticated by the platform
    st.session_state["user_id"] = _cloud_email
    _auth_method = "cloud"
    _is_authenticated = True
    with st.sidebar:
        st.markdown(f"👤 **{_cloud_email}**")
        if st.button("Logout", key="cloud_logout"):
            _do_logout()
            st.rerun()
        st.divider()

elif AUTH_ENABLED:
    # ── Tier 1: Check if Cloud SSO provided a user (even when running locally
    #    behind a proxy that sets st.context.user) ────────────────────────────
    if _cloud_email:
        st.session_state["user_id"] = _cloud_email
        _auth_method = "cloud"
        _is_authenticated = True
    else:
        # ── Tier 2: streamlit-authenticator (local/fallback) ──────────────
        try:
            import yaml
            import streamlit_authenticator as stauth

            _auth_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_config.yaml")

            # ── First-run setup: create auth_config.yaml if missing or empty ──
            _need_first_run_setup = False
            _auth_config = None

            if os.path.exists(_auth_config_path):
                with open(_auth_config_path) as _f:
                    _auth_config = yaml.safe_load(_f)
                # Check if there are ANY users configured
                _existing_usernames = (_auth_config or {}).get("credentials", {}).get("usernames", {})
                if not _existing_usernames:
                    _need_first_run_setup = True
            else:
                _need_first_run_setup = True

            # ── Restore users from database if YAML is empty/missing (post-redeploy) ──
            if _need_first_run_setup:
                try:
                    from core.database import get_all_users as _db_get_all_users
                    _db_users = _db_get_all_users()
                    if _db_users:
                        _restored_config = {
                            "credentials": {"usernames": {}},
                            "cookie": {
                                "name": "prosper_auth",
                                "key": f"prosper_auth_cookie_key_{datetime.now().strftime('%Y')}",
                                "expiry_days": 30,
                            },
                        }
                        for _dbu in _db_users:
                            _restored_config["credentials"]["usernames"][_dbu["username"]] = {
                                "email": _dbu.get("email", ""),
                                "first_name": _dbu.get("first_name", ""),
                                "last_name": _dbu.get("last_name", ""),
                                "password": _dbu.get("password_hash", ""),
                                "role": _dbu.get("role", "user"),
                            }
                        with open(_auth_config_path, "w") as _wf:
                            yaml.dump(_restored_config, _wf, default_flow_style=False)
                        _auth_config = _restored_config
                        _need_first_run_setup = False
                except Exception:
                    pass  # DB not available — proceed with first-run setup

            if _need_first_run_setup:
                # ── First-run: try Google sign-in first, then fall back to form ──
                _pad_l, _setup_col, _pad_r = st.columns([1, 2, 1])
                with _setup_col:
                    st.markdown(
                        "<div style='text-align:center;margin-top:2rem'>"
                        "<h1 style='font-size:2.5rem;margin-bottom:0;letter-spacing:-1px'>Prosper</h1>"
                        "<p style='color:#888;margin-top:4px;font-size:1.1rem'>AI-Native Investment Operating System</p>"
                        "</div>",
                        unsafe_allow_html=True,
                    )

                    # ── Google Sign-In on first-run page ──
                    _g_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
                    _g_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
                    try:
                        if not _g_client_id and hasattr(st, "secrets"):
                            _g_client_id = st.secrets.get("GOOGLE_CLIENT_ID", "")
                            _g_client_secret = st.secrets.get("GOOGLE_CLIENT_SECRET", "")
                    except Exception:
                        pass

                    _google_setup_done = False
                    if _g_client_id and _g_client_secret:
                        try:
                            from streamlit_google_auth import Authenticate as GoogleAuth
                            _g_redirect = os.getenv("GOOGLE_REDIRECT_URI", "https://prosper-app.streamlit.app")
                            try:
                                if hasattr(st, "secrets"):
                                    _g_redirect = st.secrets.get("GOOGLE_REDIRECT_URI", _g_redirect)
                            except Exception:
                                pass
                            _google_auth = GoogleAuth(
                                secret=_g_client_secret, client_id=_g_client_id,
                                redirect_uri=_g_redirect,
                            )
                            _google_auth.check()
                            if st.session_state.get("connected"):
                                _g_email = st.session_state.get("user_info", {}).get("email", "")
                                _g_name = st.session_state.get("user_info", {}).get("name", "")
                                if _g_email:
                                    _g_username = _g_email.split("@")[0].lower().replace(".", "_")
                                    _g_hash = stauth.Hasher.hash(_g_email)
                                    _new_config = {
                                        "credentials": {"usernames": {
                                            _g_username: {
                                                "email": _g_email,
                                                "first_name": (_g_name.split()[0] if _g_name else _g_email.split("@")[0]).title(),
                                                "last_name": (" ".join(_g_name.split()[1:]) if _g_name else ""),
                                                "password": _g_hash, "role": "admin",
                                            }
                                        }},
                                        "cookie": {"name": "prosper_auth",
                                                    "key": f"prosper_auth_cookie_key_{datetime.now().strftime('%Y')}",
                                                    "expiry_days": 30},
                                    }
                                    with open(_auth_config_path, "w") as _wf:
                                        yaml.dump(_new_config, _wf, default_flow_style=False)
                                    try:
                                        from core.database import create_user as _db_cr
                                        _db_cr(_g_username, _g_email, _new_config["credentials"]["usernames"][_g_username]["first_name"],
                                               _new_config["credentials"]["usernames"][_g_username]["last_name"], _g_hash, "admin")
                                    except Exception:
                                        pass
                                    st.session_state["authentication_status"] = True
                                    st.session_state["username"] = _g_username
                                    st.session_state["name"] = _g_name or _g_email.split("@")[0].title()
                                    st.session_state["user_id"] = _g_email
                                    _google_setup_done = True
                                    st.rerun()
                        except ImportError:
                            pass
                        except Exception:
                            pass

                    if not _google_setup_done:
                        st.markdown("---")
                        st.markdown(
                            "<p style='text-align:center;color:#aaa;font-size:0.9rem'>"
                            "Create your account to get started</p>",
                            unsafe_allow_html=True,
                        )

                        with st.form("first_run_setup", clear_on_submit=False):
                            _setup_c1, _setup_c2 = st.columns(2)
                            with _setup_c1:
                                _setup_first = st.text_input("First Name", key="_setup_first")
                            with _setup_c2:
                                _setup_last = st.text_input("Last Name", key="_setup_last")
                            _setup_email = st.text_input("Email", placeholder="you@example.com", key="_setup_email")
                            _setup_pw = st.text_input("Password (min 6 characters)", type="password", key="_setup_pw")
                            _setup_pw2 = st.text_input("Confirm Password", type="password", key="_setup_pw2")
                            _setup_submit = st.form_submit_button("Create Account & Sign In", type="primary", use_container_width=True)

                            if _setup_submit:
                                _setup_errors = []
                                if not _setup_email or "@" not in _setup_email:
                                    _setup_errors.append("Valid email address required.")
                                if not _setup_first.strip():
                                    _setup_errors.append("First name required.")
                                if not _setup_pw or len(_setup_pw) < 6:
                                    _setup_errors.append("Password must be at least 6 characters.")
                                if _setup_pw != _setup_pw2:
                                    _setup_errors.append("Passwords do not match.")

                                # Derive username from email
                                _setup_username = _setup_email.split("@")[0].lower().replace(".", "_").replace("-", "_") if _setup_email else ""

                                if _setup_errors:
                                    for _e in _setup_errors:
                                        st.error(_e)
                                else:
                                    _hashed_pw = stauth.Hasher.hash(_setup_pw)
                                    _new_config = {
                                        "credentials": {"usernames": {
                                            _setup_username: {
                                                "email": _setup_email.strip(),
                                                "first_name": _setup_first.strip(),
                                                "last_name": (_setup_last.strip() if '_setup_last' in dir() else ""),
                                                "password": _hashed_pw, "role": "admin",
                                            }
                                        }},
                                        "cookie": {"name": "prosper_auth",
                                                    "key": f"prosper_auth_cookie_key_{datetime.now().strftime('%Y')}",
                                                    "expiry_days": 30},
                                    }
                                    with open(_auth_config_path, "w") as _wf:
                                        yaml.dump(_new_config, _wf, default_flow_style=False)
                                    try:
                                        from core.database import create_user as _db_cr2
                                        _db_cr2(_setup_username, _setup_email.strip(),
                                                _setup_first.strip(), "", _hashed_pw, "admin")
                                    except Exception:
                                        pass
                                    # Auto-login
                                    st.session_state["authentication_status"] = True
                                    st.session_state["username"] = _setup_username
                                    st.session_state["name"] = _setup_first.strip()
                                    st.session_state["user_id"] = _setup_email.strip()
                                    st.balloons()
                                    st.success(f"Welcome to Prosper, **{_setup_first.strip()}**!")
                                    import time; time.sleep(1.5)
                                    st.rerun()

                st.stop()

            # ── Normal YAML-based login ───────────────────────────────────
            authenticator = stauth.Authenticate(
                _auth_config["credentials"],
                _auth_config["cookie"]["name"],
                _auth_config["cookie"]["key"],
                _auth_config["cookie"]["expiry_days"],
            )

            if st.session_state.get("authentication_status") not in (True,):
                # ── Login page — NO sidebar navigation visible ────────────
                _pad_l, _login_col, _pad_r = st.columns([1, 2, 1])
                with _login_col:
                    st.markdown(
                        "<div style='text-align:center;margin-top:2rem'>"
                        "<h1 style='font-size:2.5rem;margin-bottom:0;letter-spacing:-1px'>Prosper</h1>"
                        "<p style='color:#888;margin-top:4px;font-size:1.1rem'>AI-Native Investment Operating System</p>"
                        "</div>",
                        unsafe_allow_html=True,
                    )

                    # ── Google Sign-In (real OAuth via streamlit-google-auth) ──
                    _google_client_id = os.getenv("GOOGLE_CLIENT_ID") or st.secrets.get("GOOGLE_CLIENT_ID", "") if hasattr(st, "secrets") else os.getenv("GOOGLE_CLIENT_ID", "")
                    _google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET") or st.secrets.get("GOOGLE_CLIENT_SECRET", "") if hasattr(st, "secrets") else os.getenv("GOOGLE_CLIENT_SECRET", "")
                    _google_available = bool(_google_client_id and _google_client_secret)

                    if _google_available:
                        try:
                            from streamlit_google_auth import Authenticate as GoogleAuth
                            _google_auth = GoogleAuth(
                                secret=_google_client_secret,
                                client_id=_google_client_id,
                                redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", st.secrets.get("GOOGLE_REDIRECT_URI", "https://prosper-app.streamlit.app") if hasattr(st, "secrets") else "http://localhost:8501"),
                            )
                            _google_auth.check()
                            if st.session_state.get("connected"):
                                _g_email = st.session_state.get("user_info", {}).get("email", "")
                                _g_name = st.session_state.get("user_info", {}).get("name", "")
                                if _g_email:
                                    _g_username = _g_email.split("@")[0].lower().replace(".", "_")
                                    # Auto-register Google user if needed
                                    _existing_users = _auth_config.get("credentials", {}).get("usernames", {})
                                    if _g_username not in _existing_users:
                                        _g_hash = stauth.Hasher.hash(_g_email)
                                        _auth_config["credentials"]["usernames"][_g_username] = {
                                            "email": _g_email, "first_name": _g_name.split()[0] if _g_name else "",
                                            "last_name": " ".join(_g_name.split()[1:]) if _g_name else "",
                                            "password": _g_hash, "role": "user",
                                        }
                                        with open(_auth_config_path, "w") as _wf:
                                            yaml.dump(_auth_config, _wf, default_flow_style=False)
                                        try:
                                            from core.database import create_user as _db_create_user
                                            _db_create_user(_g_username, _g_email,
                                                           _g_name.split()[0] if _g_name else "", "", _g_hash, "user")
                                        except Exception:
                                            pass
                                    st.session_state["authentication_status"] = True
                                    st.session_state["username"] = _g_username
                                    st.session_state["name"] = _g_name or _g_email.split("@")[0].title()
                                    st.rerun()
                        except ImportError:
                            _google_available = False
                        except Exception:
                            _google_available = False

                    # Also handle Cloud SSO auto-login
                    if _cloud_email:
                        _g_username = _cloud_email.split("@")[0].lower().replace(".", "_")
                        st.session_state["authentication_status"] = True
                        st.session_state["username"] = _g_username
                        st.session_state["name"] = _cloud_email.split("@")[0].title()
                        st.session_state["user_id"] = _cloud_email
                        st.rerun()

                    st.markdown("---")
                    st.markdown(
                        "<p style='text-align:center;margin:0.5rem 0;color:#aaa;font-size:0.9rem'>"
                        "Sign in with email or create an account</p>",
                        unsafe_allow_html=True,
                    )

                    _login_tab, _register_tab = st.tabs(["Sign In", "Create Account"])

                    with _login_tab:
                        authenticator.login()
                        if st.session_state.get("authentication_status") is False:
                            # Try to restore user from database (in case YAML was reset on redeploy)
                            _login_recovered = False
                            try:
                                from core.database import get_all_users as _db_get_users_login
                                _db_users_login = _db_get_users_login()
                                if _db_users_login:
                                    _yaml_updated = False
                                    for _dbu in _db_users_login:
                                        if _dbu["username"] not in _auth_config.get("credentials", {}).get("usernames", {}):
                                            _auth_config.setdefault("credentials", {}).setdefault("usernames", {})[_dbu["username"]] = {
                                                "email": _dbu.get("email", ""),
                                                "first_name": _dbu.get("first_name", ""),
                                                "last_name": _dbu.get("last_name", ""),
                                                "password": _dbu.get("password_hash", ""),
                                                "role": _dbu.get("role", "user"),
                                            }
                                            _yaml_updated = True
                                    if _yaml_updated:
                                        with open(_auth_config_path, "w") as _wf:
                                            yaml.dump(_auth_config, _wf, default_flow_style=False)
                                        st.info("Your account was found. Please try signing in again.")
                                        _login_recovered = True
                            except Exception:
                                pass
                            if not _login_recovered:
                                st.error("Invalid username or password. Check your credentials or create a new account.")

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
                                    _reg_errors.append("An account with this email already exists. Please sign in.")

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
                                    # Also save to database for persistence across redeployments
                                    try:
                                        from core.database import create_user as _db_create_user
                                        _db_create_user(
                                            _reg_username, _reg_email.strip(),
                                            _reg_first.strip(), _reg_last.strip(),
                                            _hashed_pw, "user"
                                        )
                                    except Exception:
                                        pass  # DB save is best-effort
                                    # Auto-login after registration
                                    st.session_state["authentication_status"] = True
                                    st.session_state["username"] = _reg_username
                                    st.session_state["name"] = f"{_reg_first.strip()} {_reg_last.strip()}"
                                    st.balloons()
                                    st.success(
                                        f"Welcome to Prosper, **{_reg_first.strip()}**! "
                                        f"Your account has been created and you're now signed in."
                                    )
                                    import time; time.sleep(2)
                                    st.rerun()

                # Stop here — no navigation, no sidebar pages
                st.stop()

            # ── Authenticated via local YAML ──────────────────────────────
            _auth_method = "local"
            _is_authenticated = True
            st.session_state["user_id"] = st.session_state.get("username", "default")
            with st.sidebar:
                st.markdown(f"👤 **{st.session_state.get('name', 'User')}**")
                try:
                    authenticator.logout("Logout", "sidebar", key="sidebar_logout")
                except Exception:
                    pass
                # Fallback logout button in case authenticator version doesn't render one
                if st.button("Sign Out", key="manual_logout"):
                    st.session_state["authentication_status"] = None
                    _do_logout()
                    st.rerun()
                st.divider()

        except ImportError:
            # streamlit-authenticator not installed — disable auth
            AUTH_ENABLED = False
            _is_authenticated = True
            st.session_state.setdefault("user_id", "default")
        except Exception as auth_err:
            st.warning(f"Authentication error: {auth_err}. Running without login.")
            AUTH_ENABLED = False
            _is_authenticated = True
            st.session_state.setdefault("user_id", "default")

else:
    # Auth disabled — backward compatible, everything works as before
    _is_authenticated = True
    st.session_state.setdefault("user_id", "default")

# ── Onboarding Check — redirect new users to setup wizard ─────────────────────
if _is_authenticated:
    if "onboarding_complete" not in st.session_state:
        # Check persistent user preferences for onboarding status
        from core.settings import load_user_settings as _load_onb_settings
        _onb_prefs = _load_onb_settings()
        if _onb_prefs.get("onboarding_complete", False):
            st.session_state["onboarding_complete"] = True

    if not st.session_state.get("onboarding_complete", False):
        # User has not completed onboarding — show only the onboarding page
        _onb_pg = st.navigation(
            [st.Page("pages/26_Onboarding.py", title="Setup Wizard", icon="🚀", default=True)],
            position="hidden",
        )
        _onb_pg.run()
        st.stop()

# ── Portfolio Selector (user-scoped) ───────────────────────────────────────────
_current_user_id = st.session_state.get("user_id", "default")
_portfolios_df = get_or_create_user_portfolios(_current_user_id)
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
        st.Page("pages/25_IBKR_Sync.py",         title="IBKR Sync",          icon="🔗"),
        st.Page("pages/17_User_Management.py",   title="Users",               icon="👥"),
        st.Page("pages/26_Onboarding.py",        title="Onboarding",          icon="🚀"),
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
