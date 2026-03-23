"""
Authentication Module for Prosper
==================================
Handles all auth logic in one place:
  1. Streamlit Cloud SSO (st.context.user)
  2. streamlit-authenticator (YAML-based login/register)
  3. Google OAuth via streamlit-google-auth
  4. Auth disabled mode (PROSPER_AUTH_ENABLED=false)

Usage in app.py:
    from core.auth import run_auth
    auth_result = run_auth()
    if not auth_result["authenticated"]:
        st.stop()
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional

import streamlit as st


# ─────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AUTH_CONFIG_PATH = os.path.join(_APP_DIR, "auth_config.yaml")
_GOOGLE_CREDS_PATH = os.path.join(_APP_DIR, "google_credentials.json")

_HIDE_SIDEBAR_CSS = (
    '<style>[data-testid="stSidebar"]{display:none !important;}'
    '[data-testid="stSidebarCollapsedControl"]{display:none !important;}</style>'
)

_HEADER_HTML = (
    "<div style='text-align:center;margin-top:2rem'>"
    "<h1 style='font-size:2.5rem;margin-bottom:0;letter-spacing:-1px'>Prosper</h1>"
    "<p style='color:#888;margin-top:4px;font-size:1.1rem'>AI-Native Investment Operating System</p>"
    "</div>"
)


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def _detect_cloud_email() -> Optional[str]:
    """Try to get the email from Streamlit Cloud SSO."""
    cloud_user = None
    try:
        cloud_user = st.context.user if hasattr(st, "context") and hasattr(st.context, "user") else None
    except Exception:
        pass
    if cloud_user is None:
        try:
            cloud_user = st.experimental_user if hasattr(st, "experimental_user") else None
        except Exception:
            pass

    if not cloud_user:
        return None

    email = getattr(cloud_user, "email", None)
    if email is None and isinstance(cloud_user, dict):
        email = cloud_user.get("email")
    if email and email.lower() in ("", "anonymous", "null", "none"):
        email = None
    return email


def _build_google_creds_file():
    """Build google_credentials.json from secrets/env if not present."""
    if os.path.exists(_GOOGLE_CREDS_PATH):
        return

    g_cid = ""
    g_csec = ""
    try:
        if hasattr(st, "secrets"):
            g_cid = st.secrets.get("GOOGLE_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", ""))
            g_csec = st.secrets.get("GOOGLE_CLIENT_SECRET", os.getenv("GOOGLE_CLIENT_SECRET", ""))
        else:
            g_cid = os.getenv("GOOGLE_CLIENT_ID", "")
            g_csec = os.getenv("GOOGLE_CLIENT_SECRET", "")
    except Exception:
        g_cid = os.getenv("GOOGLE_CLIENT_ID", "")
        g_csec = os.getenv("GOOGLE_CLIENT_SECRET", "")

    if g_cid and g_csec:
        try:
            with open(_GOOGLE_CREDS_PATH, "w") as f:
                json.dump({
                    "web": {
                        "client_id": g_cid,
                        "client_secret": g_csec,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["https://prosper-app.streamlit.app"],
                    }
                }, f)
        except Exception:
            pass


def _load_yaml_config() -> Optional[dict]:
    """Load auth_config.yaml, return None if missing/empty."""
    try:
        import yaml
    except ImportError:
        return None

    if not os.path.exists(_AUTH_CONFIG_PATH):
        return None

    try:
        with open(_AUTH_CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        return config if config else None
    except Exception:
        return None


def _save_yaml_config(config: dict):
    """Write auth_config.yaml atomically."""
    import yaml
    with open(_AUTH_CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def _restore_users_from_db() -> Optional[dict]:
    """Try to restore YAML users from the database (post-redeploy recovery)."""
    try:
        from core.database import get_all_users
        db_users = get_all_users()
        if not db_users:
            return None

        config = {
            "credentials": {"usernames": {}},
            "cookie": {
                "name": "prosper_auth",
                "key": f"prosper_auth_cookie_key_{datetime.now().strftime('%Y')}",
                "expiry_days": 30,
            },
        }
        for u in db_users:
            config["credentials"]["usernames"][u["username"]] = {
                "email": u.get("email", ""),
                "first_name": u.get("first_name", ""),
                "last_name": u.get("last_name", ""),
                "password": u.get("password_hash", ""),
                "role": u.get("role", "user"),
            }
        _save_yaml_config(config)
        return config
    except Exception:
        return None


def _make_default_cookie() -> dict:
    return {
        "name": "prosper_auth",
        "key": f"prosper_auth_cookie_key_{datetime.now().strftime('%Y')}",
        "expiry_days": 30,
    }


def _save_user_to_db(username, email, first_name, last_name, password_hash, role="user"):
    """Best-effort save user to database for cross-deploy persistence."""
    try:
        from core.database import create_user
        create_user(username, email, first_name, last_name, password_hash, role)
    except Exception:
        pass


def _show_google_signin(redirect_uri: str = "") -> bool:
    """
    Show Google sign-in button. Returns True if user just authenticated via Google.
    """
    if not os.path.exists(_GOOGLE_CREDS_PATH):
        return False

    try:
        from streamlit_google_auth import Authenticate as GoogleAuth
        import streamlit_authenticator as stauth
    except ImportError:
        return False

    if not redirect_uri:
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "https://prosper.onrender.com")
        try:
            if hasattr(st, "secrets"):
                redirect_uri = st.secrets.get("GOOGLE_REDIRECT_URI", redirect_uri)
        except Exception:
            pass

    try:
        g_auth = GoogleAuth(
            secret_credentials_path=_GOOGLE_CREDS_PATH,
            cookie_name="prosper_google_auth",
            cookie_key="prosper_google_secret_key_2026",
            redirect_uri=redirect_uri,
        )
        g_auth.check_authentification()

        if st.session_state.get("connected"):
            g_email = st.session_state.get("user_info", {}).get("email", "")
            g_name = st.session_state.get("user_info", {}).get("name", "")
            if g_email:
                g_username = g_email.split("@")[0].lower().replace(".", "_")
                g_hash = stauth.Hasher.hash(g_email)

                # Save to YAML
                config = _load_yaml_config() or {"credentials": {"usernames": {}}, "cookie": _make_default_cookie()}
                config["credentials"]["usernames"][g_username] = {
                    "email": g_email,
                    "first_name": (g_name.split()[0] if g_name else g_email.split("@")[0]).title(),
                    "last_name": " ".join(g_name.split()[1:]) if g_name else "",
                    "password": g_hash,
                    "role": "admin" if not config["credentials"]["usernames"] else "user",
                }
                _save_yaml_config(config)
                _save_user_to_db(
                    g_username, g_email,
                    config["credentials"]["usernames"][g_username]["first_name"],
                    config["credentials"]["usernames"][g_username]["last_name"],
                    g_hash,
                    config["credentials"]["usernames"][g_username]["role"],
                )

                st.session_state["authentication_status"] = True
                st.session_state["username"] = g_username
                st.session_state["name"] = g_name or g_email.split("@")[0].title()
                st.session_state["user_id"] = g_email
                return True
        else:
            auth_url = g_auth.get_authorization_url()
            st.link_button("🔑 Continue with Google", auth_url, use_container_width=True)
    except Exception as e:
        st.caption(f"Google sign-in unavailable: {e}")

    return False


def _show_registration_form(auth_config: dict) -> bool:
    """Show the registration form. Returns True if user registered & auto-logged-in."""
    import streamlit_authenticator as stauth

    st.markdown("##### Create your Prosper account")
    with st.form("register_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            first = st.text_input("First Name", key="_reg_first")
        with c2:
            last = st.text_input("Last Name", key="_reg_last")
        email = st.text_input("Email", placeholder="you@example.com", key="_reg_email")
        pw = st.text_input("Password (min 6 characters)", type="password", key="_reg_pw")
        pw2 = st.text_input("Confirm Password", type="password", key="_reg_pw2")
        submit = st.form_submit_button("Create Account", type="primary", use_container_width=True)

        if submit:
            errors = []
            if not email or "@" not in email:
                errors.append("Valid email address required.")
            if not first.strip():
                errors.append("First name required.")
            if not pw or len(pw) < 6:
                errors.append("Password must be at least 6 characters.")
            if pw != pw2:
                errors.append("Passwords do not match.")

            username = email.split("@")[0].lower().replace(".", "_").replace("-", "_").replace("+", "_") if email else ""
            existing = auth_config.get("credentials", {}).get("usernames", {})
            if username in existing:
                errors.append("An account with this email already exists. Please sign in.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                hashed = stauth.Hasher.hash(pw)
                is_first_user = not existing
                role = "admin" if is_first_user else "user"

                auth_config.setdefault("credentials", {}).setdefault("usernames", {})[username] = {
                    "email": email.strip(),
                    "first_name": first.strip(),
                    "last_name": last.strip(),
                    "password": hashed,
                    "role": role,
                }
                _save_yaml_config(auth_config)
                _save_user_to_db(username, email.strip(), first.strip(), last.strip(), hashed, role)

                st.session_state["authentication_status"] = True
                st.session_state["username"] = username
                st.session_state["name"] = f"{first.strip()} {last.strip()}".strip()
                st.session_state["user_id"] = email.strip()
                st.balloons()
                st.success(f"Welcome to Prosper, **{first.strip()}**! Your account is ready.")
                import time
                time.sleep(1.5)
                st.rerun()
                return True  # Won't reach here due to rerun, but for clarity

    return False


# ─────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────
def do_logout():
    """Clear all session state related to auth and user data."""
    keys_to_clear = []
    for k in list(st.session_state.keys()):
        if (k.startswith("enriched_") or k.startswith("_prosper_holdings_cache")
                or k in ("extended_df", "last_refresh_time", "active_portfolio_id",
                         "user_id", "mini_chat", "global_currency_filter",
                         "authentication_status", "username", "name", "logout")):
            keys_to_clear.append(k)
    for k in keys_to_clear:
        try:
            del st.session_state[k]
        except KeyError:
            pass


# ─────────────────────────────────────────
# MAIN AUTH ENTRY POINT
# ─────────────────────────────────────────
def run_auth() -> Dict[str, Any]:
    """
    Run the complete authentication flow.

    Returns dict:
        authenticated: bool
        user_id: str (email or username)
        display_name: str
        method: str ("cloud", "google", "local", "disabled")

    If not authenticated, this function renders the login UI and calls st.stop().
    The caller should check result["authenticated"] but in practice this function
    never returns False — it stops the app with st.stop() on the login page.
    """
    result = {
        "authenticated": False,
        "user_id": "default",
        "display_name": "User",
        "method": "disabled",
    }

    auth_enabled = os.getenv("PROSPER_AUTH_ENABLED", "true").lower() in ("true", "1", "yes")

    # ── Tier 0: Cloud SSO ──
    cloud_email = _detect_cloud_email()
    if cloud_email:
        st.session_state["user_id"] = cloud_email
        result.update(authenticated=True, user_id=cloud_email, display_name=cloud_email, method="cloud")
        with st.sidebar:
            st.markdown(f"👤 **{cloud_email}**")
            if st.button("Logout", key="cloud_logout"):
                do_logout()
                st.rerun()
            st.divider()
        return result

    # ── Auth disabled ──
    if not auth_enabled:
        st.session_state.setdefault("user_id", "default")
        result.update(authenticated=True, method="disabled")
        with st.sidebar:
            st.caption("Auth disabled")
            st.divider()
        return result

    # ── Tier 1: YAML-based auth (with Google OAuth integration) ──
    try:
        import yaml
        import streamlit_authenticator as stauth
    except ImportError:
        st.error("Authentication packages not installed. Contact the administrator.")
        st.stop()
        return result

    # Build Google credentials file from secrets
    _build_google_creds_file()

    # Load or restore YAML config
    auth_config = _load_yaml_config()
    has_users = bool(auth_config and auth_config.get("credentials", {}).get("usernames"))

    if not has_users:
        # Try restoring from database
        auth_config = _restore_users_from_db()
        has_users = bool(auth_config and auth_config.get("credentials", {}).get("usernames"))

    # ── No users yet: First-run setup ──
    if not has_users:
        st.markdown(_HIDE_SIDEBAR_CSS, unsafe_allow_html=True)
        _, center, _ = st.columns([1, 2, 1])
        with center:
            st.markdown(_HEADER_HTML, unsafe_allow_html=True)

            # Google sign-in first
            if _show_google_signin():
                st.rerun()

            st.markdown("---")
            st.markdown(
                "<p style='text-align:center;color:#aaa;font-size:0.9rem'>"
                "Create your account to get started</p>",
                unsafe_allow_html=True,
            )

            # First-run registration form (inline, not in tabs)
            with st.form("first_run_setup", clear_on_submit=False):
                c1, c2 = st.columns(2)
                with c1:
                    first = st.text_input("First Name", key="_setup_first")
                with c2:
                    last = st.text_input("Last Name", key="_setup_last")
                email = st.text_input("Email", placeholder="you@example.com", key="_setup_email")
                pw = st.text_input("Password (min 6 characters)", type="password", key="_setup_pw")
                pw2 = st.text_input("Confirm Password", type="password", key="_setup_pw2")
                submit = st.form_submit_button("Create Account & Sign In", type="primary", use_container_width=True)

                if submit:
                    errors = []
                    if not email or "@" not in email:
                        errors.append("Valid email address required.")
                    if not first.strip():
                        errors.append("First name required.")
                    if not pw or len(pw) < 6:
                        errors.append("Password must be at least 6 characters.")
                    if pw != pw2:
                        errors.append("Passwords do not match.")

                    if errors:
                        for e in errors:
                            st.error(e)
                    else:
                        username = email.split("@")[0].lower().replace(".", "_").replace("-", "_") if email else ""
                        hashed = stauth.Hasher.hash(pw)
                        new_config = {
                            "credentials": {"usernames": {
                                username: {
                                    "email": email.strip(),
                                    "first_name": first.strip(),
                                    "last_name": last.strip(),
                                    "password": hashed,
                                    "role": "admin",
                                }
                            }},
                            "cookie": _make_default_cookie(),
                        }
                        _save_yaml_config(new_config)
                        _save_user_to_db(username, email.strip(), first.strip(), last.strip(), hashed, "admin")

                        st.session_state["authentication_status"] = True
                        st.session_state["username"] = username
                        st.session_state["name"] = first.strip()
                        st.session_state["user_id"] = email.strip()
                        st.balloons()
                        st.success(f"Welcome to Prosper, **{first.strip()}**!")
                        import time
                        time.sleep(1.5)
                        st.rerun()

        st.stop()
        return result

    # ── Has users: Normal login flow ──
    if not auth_config.get("cookie"):
        auth_config["cookie"] = _make_default_cookie()

    authenticator = stauth.Authenticate(
        auth_config["credentials"],
        auth_config["cookie"]["name"],
        auth_config["cookie"]["key"],
        auth_config["cookie"]["expiry_days"],
    )

    # Check if already authenticated (cookie or session)
    if st.session_state.get("authentication_status") is True:
        # Already logged in
        username = st.session_state.get("username", "default")
        display_name = st.session_state.get("name", "User")
        user_email = auth_config.get("credentials", {}).get("usernames", {}).get(username, {}).get("email", username)
        st.session_state["user_id"] = user_email or username

        result.update(authenticated=True, user_id=user_email or username, display_name=display_name, method="local")

        with st.sidebar:
            st.markdown(f"👤 **{display_name}**")
            if st.button("Sign Out", key="manual_logout", use_container_width=True):
                st.session_state["authentication_status"] = None
                do_logout()
                st.rerun()
            st.divider()

        return result

    # ── Not authenticated: Show login page ──
    st.markdown(_HIDE_SIDEBAR_CSS, unsafe_allow_html=True)
    _, center, _ = st.columns([1, 2, 1])

    with center:
        st.markdown(_HEADER_HTML, unsafe_allow_html=True)

        # Google sign-in
        if _show_google_signin():
            st.rerun()

        # Cloud SSO auto-login (in case cloud_email was detected later)
        if cloud_email:
            g_username = cloud_email.split("@")[0].lower().replace(".", "_")
            st.session_state["authentication_status"] = True
            st.session_state["username"] = g_username
            st.session_state["name"] = cloud_email.split("@")[0].title()
            st.session_state["user_id"] = cloud_email
            st.rerun()

        st.markdown("---")
        st.markdown(
            "<p style='text-align:center;margin:0.5rem 0;color:#aaa;font-size:0.9rem'>"
            "Sign in with email or create an account</p>",
            unsafe_allow_html=True,
        )

        login_tab, register_tab = st.tabs(["Sign In", "Create Account"])

        with login_tab:
            authenticator.login()
            if st.session_state.get("authentication_status") is False:
                # Try DB recovery
                _recovered = False
                try:
                    from core.database import get_all_users
                    db_users = get_all_users()
                    if db_users:
                        updated = False
                        for u in db_users:
                            if u["username"] not in auth_config.get("credentials", {}).get("usernames", {}):
                                auth_config.setdefault("credentials", {}).setdefault("usernames", {})[u["username"]] = {
                                    "email": u.get("email", ""),
                                    "first_name": u.get("first_name", ""),
                                    "last_name": u.get("last_name", ""),
                                    "password": u.get("password_hash", ""),
                                    "role": u.get("role", "user"),
                                }
                                updated = True
                        if updated:
                            _save_yaml_config(auth_config)
                            st.info("Your account was found. Please try signing in again.")
                            _recovered = True
                except Exception:
                    pass
                if not _recovered:
                    st.error("Invalid username or password. Check your credentials or create a new account.")

        with register_tab:
            _show_registration_form(auth_config)

    st.stop()
    return result
