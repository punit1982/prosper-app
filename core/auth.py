"""
Authentication Module for Prosper
==================================
Complete user authentication with database as the single source of truth.

Supports:
  1. Email-based registration & login (bcrypt hashed passwords)
  2. Google OAuth via streamlit-google-auth
  3. Auth disabled mode (PROSPER_AUTH_ENABLED=false)

All user data is stored in the Turso/SQLite database.
A local YAML cache is rebuilt from the DB on every cold start
(required by streamlit-authenticator for cookie-based sessions).

Usage in app.py:
    from core.auth import run_auth, do_logout
    auth_result = run_auth()
    if not auth_result["authenticated"]:
        st.stop()
"""

import os
import re
import json
import secrets as _secrets
import logging as _logging
from datetime import datetime
from typing import Dict, Any, Optional

import streamlit as st

_auth_log = _logging.getLogger("prosper.auth")

# ─────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AUTH_CONFIG_PATH = os.path.join(_APP_DIR, "auth_config.yaml")
_GOOGLE_CREDS_PATH = os.path.join(_APP_DIR, "google_credentials.json")

_COOKIE_NAME = "prosper_auth"
_COOKIE_KEY = os.getenv("PROSPER_COOKIE_SECRET", "")
if not _COOKIE_KEY:
    _COOKIE_KEY = _secrets.token_hex(32)
    _auth_log.warning(
        "PROSPER_COOKIE_SECRET not set — using random key. "
        "Sessions will not persist across restarts."
    )
_COOKIE_EXPIRY_DAYS = 30

_GOOGLE_COOKIE_KEY = os.getenv("PROSPER_GOOGLE_COOKIE_SECRET", "")
if not _GOOGLE_COOKIE_KEY:
    _GOOGLE_COOKIE_KEY = _secrets.token_hex(32)

_HIDE_SIDEBAR_CSS = (
    '<style>'
    '[data-testid="stSidebar"]{display:none !important;}'
    '[data-testid="stSidebarCollapsedControl"]{display:none !important;}'
    '[data-testid="stNavigation"]{display:none !important;}'
    '[role="tablist"]{display:none !important;}'
    '</style>'
)

_HEADER_HTML = (
    "<div style='text-align:center;margin-top:2rem'>"
    "<h1 style='font-size:2.5rem;margin-bottom:0;letter-spacing:-1px'>Prosper</h1>"
    "<p style='color:#888;margin-top:4px;font-size:1.1rem'>AI-Native Investment Operating System</p>"
    "</div>"
)

_MIN_PASSWORD_LENGTH = 8


# ─────────────────────────────────────────
# PASSWORD VALIDATION
# ─────────────────────────────────────────
def validate_password(pw: str) -> list:
    """Return list of error strings. Empty = valid."""
    errors = []
    if len(pw) < _MIN_PASSWORD_LENGTH:
        errors.append(f"At least {_MIN_PASSWORD_LENGTH} characters")
    if not re.search(r"[A-Z]", pw):
        errors.append("At least one uppercase letter (A-Z)")
    if not re.search(r"\d", pw):
        errors.append("At least one number (0-9)")
    return errors


def _hash_password(pw: str) -> str:
    """Hash password using bcrypt (streamlit-authenticator's Hasher.hash no longer works)."""
    import bcrypt
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    try:
        import bcrypt
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ─────────────────────────────────────────
# DATABASE HELPERS (single source of truth)
# ─────────────────────────────────────────
def _db_get_all_users() -> list:
    try:
        from core.database import get_all_users
        return get_all_users()
    except Exception:
        return []


def _db_get_user(username: str) -> Optional[dict]:
    try:
        from core.database import get_user_by_username
        return get_user_by_username(username)
    except Exception:
        return None


def _db_get_user_by_email(email: str) -> Optional[dict]:
    try:
        from core.database import get_user_by_email
        return get_user_by_email(email)
    except Exception:
        return None


def _db_create_user(username, email, first_name, last_name, password_hash, role="user"):
    try:
        from core.database import create_user
        return create_user(username, email, first_name, last_name, password_hash, role)
    except Exception as e:
        # If duplicate, silently succeed
        if "UNIQUE" in str(e).upper() or "duplicate" in str(e).lower():
            return username
        raise


_ALLOWED_USER_FIELDS = {"email", "first_name", "last_name", "password_hash", "role"}


def _db_update_user(username, **fields):
    """Update user fields in the database. Only whitelisted column names accepted."""
    # Sanitize: only allow known column names (prevents SQL injection via field names)
    safe_fields = {k: v for k, v in fields.items() if k in _ALLOWED_USER_FIELDS}
    if not safe_fields:
        return

    from core.db_connector import get_connection
    conn = None
    try:
        conn = get_connection()
        set_clauses = []
        values = []
        for key, val in safe_fields.items():
            set_clauses.append(f"{key} = ?")
            values.append(val)
        values.append(username)
        conn.execute(
            f"UPDATE users SET {', '.join(set_clauses)} WHERE username = ?",
            tuple(values),
        )
        conn.commit()
    except Exception as e:
        import logging
        logging.getLogger("prosper.auth").warning(f"Failed to update user {username}: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _db_delete_user(username: str):
    """Delete a user from the database. Raises on failure so caller knows."""
    from core.database import delete_user
    delete_user(username)


# ─────────────────────────────────────────
# YAML CACHE (rebuilt from DB, used by
# streamlit-authenticator for cookie auth)
# ─────────────────────────────────────────
def _rebuild_yaml_from_db():
    """Rebuild auth_config.yaml from the database. Called on every cold start."""
    import yaml
    users = _db_get_all_users()
    config = {
        "credentials": {"usernames": {}},
        "cookie": {
            "name": _COOKIE_NAME,
            "key": _COOKIE_KEY,
            "expiry_days": _COOKIE_EXPIRY_DAYS,
        },
    }
    for u in users:
        config["credentials"]["usernames"][u["username"]] = {
            "email": u.get("email", ""),
            "first_name": u.get("first_name", ""),
            "last_name": u.get("last_name", ""),
            "password": u.get("password_hash", ""),
            "role": u.get("role", "user"),
        }
    try:
        with open(_AUTH_CONFIG_PATH, "w") as f:
            yaml.dump(config, f, default_flow_style=False)
    except Exception:
        pass
    return config


def _load_yaml_config() -> Optional[dict]:
    """Load auth_config.yaml."""
    try:
        import yaml
        if not os.path.exists(_AUTH_CONFIG_PATH):
            return None
        with open(_AUTH_CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        return config if config else None
    except Exception:
        return None


def _save_yaml_config(config: dict):
    """Write auth_config.yaml."""
    try:
        import yaml
        with open(_AUTH_CONFIG_PATH, "w") as f:
            yaml.dump(config, f, default_flow_style=False)
    except Exception:
        pass


def _sync_user_to_yaml(username, email, first_name, last_name, password_hash, role):
    """Add or update a single user in the YAML cache."""
    config = _load_yaml_config()
    if not config:
        config = {
            "credentials": {"usernames": {}},
            "cookie": {"name": _COOKIE_NAME, "key": _COOKIE_KEY, "expiry_days": _COOKIE_EXPIRY_DAYS},
        }
    config.setdefault("credentials", {}).setdefault("usernames", {})[username] = {
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "password": password_hash,
        "role": role,
    }
    _save_yaml_config(config)
    return config


# ─────────────────────────────────────────
# GOOGLE OAUTH — manual implementation
# No dependency on streamlit-google-auth (which hardcodes key='init' causing
# duplicate widget key conflicts with streamlit-authenticator).
# Uses only 'requests' (already in requirements) + standard OAuth2 endpoints.
# ─────────────────────────────────────────
def _build_google_creds_file():
    """No-op — kept for API compatibility. Manual flow uses env vars directly."""
    pass


def _is_google_configured() -> bool:
    """Check if Google OAuth env vars are set."""
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def _handle_google_user(user_info: dict) -> bool:
    """Process authenticated Google user — create/sync DB record and set session state."""
    g_email = user_info.get("email", "")
    g_name = user_info.get("name", "")
    if not g_email:
        return False

    g_username = g_email.split("@")[0].lower().replace(".", "_").replace("-", "_")
    g_hash = _hash_password(g_email)
    first_name = (g_name.split()[0] if g_name else g_email.split("@")[0]).title()
    last_name = " ".join(g_name.split()[1:]) if g_name and len(g_name.split()) > 1 else ""

    existing = _db_get_all_users()
    role = "admin" if not existing else "user"

    try:
        _db_create_user(g_username, g_email, first_name, last_name, g_hash, role)
    except Exception:
        pass

    _sync_user_to_yaml(g_username, g_email, first_name, last_name, g_hash, role)

    st.session_state["authentication_status"] = True
    st.session_state["username"] = g_username
    st.session_state["name"] = g_name or first_name
    st.session_state["user_id"] = g_email
    st.session_state["auth_method"] = "google"
    return True


def _show_google_signin() -> bool:
    """Show Google sign-in button using manual OAuth2 redirect flow.

    Flow:
      1. User clicks "Continue with Google" → redirected to Google consent
      2. Google redirects back with ?code=... in URL
      3. We exchange the code for an access token (server-side POST)
      4. We fetch the user's profile and create/sync the account

    Uses only 'requests' — no streamlit-google-auth dependency, no key='init' conflict.
    """
    # Guard: only render once per rerun cycle
    if st.session_state.get("_google_auth_rendered_this_rerun"):
        return False

    if not _is_google_configured():
        return False

    st.session_state["_google_auth_rendered_this_rerun"] = True

    g_cid = os.getenv("GOOGLE_CLIENT_ID", "")
    g_csec = os.getenv("GOOGLE_CLIENT_SECRET", "")
    redirect = os.getenv("GOOGLE_REDIRECT_URI", "https://prosper-gzlf.onrender.com")

    try:
        import urllib.parse
        import requests as _req

        # ── Step 1: Handle OAuth callback (code in URL params) ──
        params = dict(st.query_params)
        if "code" in params and not st.session_state.get("_google_auth_done"):
            code = params["code"]
            # Clear the code from URL immediately to prevent reuse
            st.query_params.clear()

            token_resp = _req.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": g_cid,
                    "client_secret": g_csec,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect,
                },
                timeout=10,
            )
            if token_resp.status_code == 200:
                access_token = token_resp.json().get("access_token", "")
                if access_token:
                    ui_resp = _req.get(
                        "https://www.googleapis.com/oauth2/v2/userinfo",
                        headers={"Authorization": f"Bearer {access_token}"},
                        timeout=10,
                    )
                    if ui_resp.status_code == 200:
                        user_info = ui_resp.json()
                        st.session_state["_google_auth_done"] = True
                        st.session_state["connected"] = True
                        st.session_state["user_info"] = user_info
                        return _handle_google_user(user_info)
            else:
                _auth_log.warning(f"Google token exchange failed ({token_resp.status_code}): {token_resp.text[:200]}")

        # ── Step 2: Already authenticated this session ──
        if st.session_state.get("connected") and st.session_state.get("user_info"):
            return _handle_google_user(st.session_state["user_info"])

        # ── Step 3: Show the sign-in button ──
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": g_cid,
            "redirect_uri": redirect,
            "scope": "openid email profile",
            "response_type": "code",
            "access_type": "offline",
            "prompt": "select_account",
        })
        st.link_button("🔑 Continue with Google", auth_url, use_container_width=True)

    except Exception as google_err:
        _auth_log.warning(f"Google sign-in error: {google_err}")
        st.warning(f"Google sign-in error: {google_err}")
        st.caption("Please use email login, or check Google OAuth configuration.")

    return False


# ─────────────────────────────────────────
# REGISTRATION FORM
# ─────────────────────────────────────────
def _show_registration_form(is_first_user: bool = False) -> bool:
    """Show registration form. Returns True if user registered & auto-logged-in."""
    label = "Create your Prosper account" if is_first_user else "Create Account"
    st.markdown(f"##### {label}")

    st.markdown(
        "<p style='color:#888;font-size:0.85rem'>"
        "Password: min 8 chars, 1 uppercase, 1 number</p>",
        unsafe_allow_html=True,
    )

    with st.form("register_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            first = st.text_input("First Name", key="_reg_first")
        with c2:
            last = st.text_input("Last Name", key="_reg_last")
        email = st.text_input("Email", placeholder="you@example.com", key="_reg_email")
        pw = st.text_input("Password", type="password", key="_reg_pw")
        pw2 = st.text_input("Confirm Password", type="password", key="_reg_pw2")
        btn_label = "Create Account & Sign In" if is_first_user else "Create Account"
        submit = st.form_submit_button(btn_label, type="primary", use_container_width=True)

        if submit:
            errors = []
            if not email or "@" not in email:
                errors.append("Valid email address required.")
            if not first.strip():
                errors.append("First name required.")
            pw_errors = validate_password(pw) if pw else ["Password is required."]
            errors.extend(pw_errors)
            if pw != pw2:
                errors.append("Passwords do not match.")

            username = email.split("@")[0].lower().replace(".", "_").replace("-", "_").replace("+", "_") if email else ""

            # Check DB for existing user (source of truth)
            if username and _db_get_user(username):
                errors.append("An account with this email already exists. Please sign in.")
            if email and _db_get_user_by_email(email.strip()):
                errors.append("This email is already registered. Please sign in.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                hashed = _hash_password(pw)
                existing = _db_get_all_users()
                role = "admin" if (is_first_user or not existing) else "user"

                # Save to DB (source of truth)
                _db_create_user(username, email.strip(), first.strip(), last.strip(), hashed, role)

                # Sync to YAML cache
                _sync_user_to_yaml(username, email.strip(), first.strip(), last.strip(), hashed, role)

                # Auto-login
                st.session_state["authentication_status"] = True
                st.session_state["username"] = username
                st.session_state["name"] = f"{first.strip()} {last.strip()}".strip()
                st.session_state["user_id"] = email.strip()
                st.session_state["auth_method"] = "email"
                st.balloons()
                st.success(f"Welcome to Prosper, **{first.strip()}**! Your account is ready.")
                st.rerun()
                return True

    return False


# ─────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────
def do_logout():
    """Clear ALL auth-related session state including authenticator cookie state."""
    # Keys that streamlit-authenticator / Google auth uses internally
    _auth_keys = {
        "authentication_status", "username", "name", "logout",
        "user_id", "auth_method", "connected", "user_info",
        "_google_auth_rendered",
        "FormSubmitter:Login-Login", "FormSubmitter:Login-Submit",
    }
    # App-specific keys to clear
    _app_keys = {
        "mini_chat", "global_currency_filter", "active_portfolio_id",
        "onboarding_complete",
    }

    keys_to_clear = set()
    for k in list(st.session_state.keys()):
        if k in _auth_keys or k in _app_keys:
            keys_to_clear.add(k)
        elif k.startswith("enriched_") or k.startswith("_prosper_holdings_cache"):
            keys_to_clear.add(k)
        elif k in ("extended_df", "last_refresh_time"):
            keys_to_clear.add(k)

    for k in keys_to_clear:
        try:
            del st.session_state[k]
        except KeyError:
            pass

    # Force authenticator to recognize logout
    st.session_state["authentication_status"] = None
    st.session_state["logout"] = True


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
        method: str ("google", "email", "disabled")

    If not authenticated, renders login UI and calls st.stop().
    """
    result = {
        "authenticated": False,
        "user_id": "default",
        "display_name": "User",
        "method": "disabled",
    }

    # Reset per-rerun flag so Google auth widget can render fresh each rerun
    st.session_state.pop("_google_auth_rendered_this_rerun", None)

    auth_enabled = os.getenv("PROSPER_AUTH_ENABLED", "true").lower() in ("true", "1", "yes")

    # ── Auth disabled ──
    if not auth_enabled:
        st.session_state.setdefault("user_id", "default")
        result.update(authenticated=True, method="disabled")
        with st.sidebar:
            st.caption("🔓 Auth disabled (dev mode)")
            st.divider()
        return result

    # ── Check for logout request ──
    if st.session_state.get("logout") is True:
        st.session_state["logout"] = False
        st.session_state["authentication_status"] = None

    # ── Load dependencies ──
    try:
        import yaml
        import streamlit_authenticator as stauth
    except ImportError:
        st.error("Authentication packages not installed. Contact the administrator.")
        st.stop()
        return result

    # Build Google credentials file from env vars
    _build_google_creds_file()

    # ── Rebuild YAML cache from DB (handles redeploys) ──
    db_users = _db_get_all_users()
    if db_users:
        auth_config = _rebuild_yaml_from_db()
    else:
        auth_config = _load_yaml_config()

    has_users = bool(
        auth_config
        and auth_config.get("credentials", {}).get("usernames")
    )

    # ── No users yet: First-run setup ──
    if not has_users:
        st.markdown(_HIDE_SIDEBAR_CSS, unsafe_allow_html=True)
        _, center, _ = st.columns([1, 2, 1])
        with center:
            st.markdown(_HEADER_HTML, unsafe_allow_html=True)
            st.markdown("")

            # Google sign-in first
            if _show_google_signin():
                st.rerun()

            st.markdown(
                "<div style='text-align:center;margin:1rem 0'>"
                "<span style='color:#555'>─── or ───</span></div>",
                unsafe_allow_html=True,
            )

            _show_registration_form(is_first_user=True)

        st.stop()
        return result

    # ── Has users: Ensure YAML config has cookie section ──
    if not auth_config.get("cookie"):
        auth_config["cookie"] = {
            "name": _COOKIE_NAME,
            "key": _COOKIE_KEY,
            "expiry_days": _COOKIE_EXPIRY_DAYS,
        }

    # Create authenticator instance
    authenticator = stauth.Authenticate(
        auth_config["credentials"],
        auth_config["cookie"]["name"],
        auth_config["cookie"]["key"],
        auth_config["cookie"]["expiry_days"],
    )

    # ── Already authenticated (cookie or session) ──
    if st.session_state.get("authentication_status") is True:
        username = st.session_state.get("username", "default")
        display_name = st.session_state.get("name", "User")
        user_data = auth_config.get("credentials", {}).get("usernames", {}).get(username, {})
        user_email = user_data.get("email", username)
        st.session_state.setdefault("user_id", user_email or username)

        result.update(
            authenticated=True,
            user_id=user_email or username,
            display_name=display_name,
            method=st.session_state.get("auth_method", "email"),
        )

        # Sidebar user info + logout
        with st.sidebar:
            st.markdown(f"👤 **{display_name}**")
            st.caption(f"_{user_email}_" if user_email != username else "")
            if st.button("🚪 Sign Out", key="sidebar_logout", use_container_width=True):
                # Use authenticator's logout to clear cookie
                try:
                    authenticator.logout(location="unrendered")
                except Exception:
                    pass
                do_logout()
                st.rerun()
            st.divider()

        return result

    # ── Not authenticated: Show login page ──
    st.markdown(_HIDE_SIDEBAR_CSS, unsafe_allow_html=True)
    _, center, _ = st.columns([1, 2, 1])

    with center:
        st.markdown(_HEADER_HTML, unsafe_allow_html=True)
        st.markdown("")

        # Google sign-in
        if _show_google_signin():
            st.rerun()

        st.markdown(
            "<div style='text-align:center;margin:0.8rem 0'>"
            "<span style='color:#555'>─── or sign in with email ───</span></div>",
            unsafe_allow_html=True,
        )

        # ── Email sign-in (primary action) ──
        authenticator.login()
        if st.session_state.get("authentication_status") is True:
            # Login succeeded — set user_id and rerun to show the app
            username = st.session_state.get("username", "")
            user_data = auth_config.get("credentials", {}).get("usernames", {}).get(username, {})
            st.session_state["user_id"] = user_data.get("email", username)
            st.session_state["auth_method"] = "email"
            st.rerun()
        elif st.session_state.get("authentication_status") is False:
            st.error("Invalid username or password.")
            st.caption("Forgot your password? Contact an administrator or create a new account.")

        # ── Registration form (secondary action) ──
        st.markdown("")
        with st.expander("👤 Create New Account", expanded=False):
            _show_registration_form(is_first_user=False)

    st.stop()
    return result
