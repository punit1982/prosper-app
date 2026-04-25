"""
Authentication Module for Prosper — v6.3
==========================================
Complete user authentication with database as the single source of truth.

Supports:
  1. Email-based registration & login (bcrypt hashed passwords)
  2. Google OAuth via popup window flow (preserves main Streamlit session)
  3. Auth disabled mode (PROSPER_AUTH_ENABLED=false)

OAuth flow (v6.3):
  - Main app opens Google consent in a POPUP window (not same tab)
  - Popup lands on pages/99_OAuth_Callback.py with ?code=&state=
  - Callback page exchanges code, writes {email, name, status} to localStorage
  - Main app polls localStorage every 500ms and logs the user in
  - Popup is closed automatically after writing result
  - Main session_state is never destroyed → no loop, no session loss
"""

import os
import re
import json
import hashlib
import hmac
import secrets as _secrets
import logging as _logging
from datetime import datetime
from typing import Dict, Any, Optional

import streamlit as st

_auth_log = _logging.getLogger("prosper.auth")


def _is_production() -> bool:
    return (
        os.getenv("PROSPER_ENV", "").lower() == "production"
        or bool(os.getenv("RENDER"))
    )


_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AUTH_CONFIG_PATH = os.path.join(_APP_DIR, "auth_config.yaml")

_COOKIE_NAME = "prosper_auth"
_COOKIE_KEY = os.getenv("PROSPER_COOKIE_SECRET", "")
if not _COOKIE_KEY:
    if _is_production():
        raise RuntimeError(
            "PROSPER_COOKIE_SECRET is required in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    _COOKIE_KEY = _secrets.token_hex(32)
    _auth_log.warning("PROSPER_COOKIE_SECRET not set — using ephemeral dev key.")
_COOKIE_EXPIRY_DAYS = 30

_GOOGLE_COOKIE_KEY = os.getenv("PROSPER_GOOGLE_COOKIE_SECRET", "")
if not _GOOGLE_COOKIE_KEY:
    if _is_production():
        raise RuntimeError("PROSPER_GOOGLE_COOKIE_SECRET is required in production.")
    _GOOGLE_COOKIE_KEY = _secrets.token_hex(32)

_OAUTH_SIGNING_KEY = os.getenv("PROSPER_COOKIE_SECRET", _COOKIE_KEY).encode()

# ── Sidebar hide CSS — injected as early as possible ───────────────────────
# Targets every possible Streamlit sidebar element across versions.
SIDEBAR_HIDE_CSS = """
<style>
/* Hide sidebar and all its controls before login */
[data-testid="stSidebar"],
[data-testid="stSidebarNav"],
[data-testid="stSidebarNavItems"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stNavigation"],
[data-testid="collapsedControl"],
button[kind="header"],
.st-emotion-cache-1cypcdb,
.st-emotion-cache-eczf16,
.st-emotion-cache-po3dy8,
section[data-testid="stSidebar"] {
    display: none !important;
    visibility: hidden !important;
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    position: fixed !important;
    left: -9999px !important;
    z-index: -9999 !important;
    pointer-events: none !important;
    opacity: 0 !important;
}
/* Also hide the hamburger/collapse toggle button */
[data-testid="stSidebarCollapsedControl"] svg,
[data-testid="stSidebarCollapsedControl"] button {
    display: none !important;
}
/* Ensure main content takes full width */
.main .block-container {
    max-width: 100% !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
}
</style>
"""

_HEADER_HTML = (
    "<div style='text-align:center;margin-top:3rem;margin-bottom:0.5rem'>"
    "<div style='font-size:2.8rem;font-weight:700;letter-spacing:-1.5px;"
    "background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);"
    "-webkit-background-clip:text;-webkit-text-fill-color:transparent;"
    "background-clip:text'>Prosper</div>"
    "<p style='color:#888;margin-top:6px;font-size:1rem;letter-spacing:0.3px'>"
    "AI-Native Investment Operating System</p>"
    "</div>"
)

_MIN_PASSWORD_LENGTH = 8


# ─────────────────────────────────────────
# OAUTH STATE — HMAC-signed, session-independent
# ─────────────────────────────────────────
def _make_oauth_state() -> str:
    nonce = _secrets.token_urlsafe(32)
    sig = hmac.new(_OAUTH_SIGNING_KEY, nonce.encode(), hashlib.sha256).hexdigest()
    return f"{nonce}.{sig}"


def _verify_oauth_state(state: str) -> bool:
    if not state or "." not in state:
        return False
    nonce, _, received_sig = state.partition(".")
    expected_sig = hmac.new(_OAUTH_SIGNING_KEY, nonce.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_sig, received_sig)


# ─────────────────────────────────────────
# PASSWORD HELPERS
# ─────────────────────────────────────────
def validate_password(pw: str) -> list:
    errors = []
    if len(pw) < _MIN_PASSWORD_LENGTH:
        errors.append(f"At least {_MIN_PASSWORD_LENGTH} characters")
    if not re.search(r"[A-Z]", pw):
        errors.append("At least one uppercase letter (A-Z)")
    if not re.search(r"\d", pw):
        errors.append("At least one number (0-9)")
    return errors


def _hash_password(pw: str) -> str:
    import bcrypt
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_password(plain: str, hashed: str) -> bool:
    try:
        import bcrypt
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ─────────────────────────────────────────
# DATABASE HELPERS
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
        if "UNIQUE" in str(e).upper() or "duplicate" in str(e).lower():
            return username
        raise


_ALLOWED_USER_FIELDS = {"email", "first_name", "last_name", "password_hash", "role"}


def _db_update_user(username, **fields):
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
        _auth_log.warning(f"Failed to update user {username}: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _db_delete_user(username: str):
    from core.database import delete_user
    delete_user(username)


# ─────────────────────────────────────────
# YAML CACHE
# ─────────────────────────────────────────
def _rebuild_yaml_from_db():
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
    try:
        import yaml
        with open(_AUTH_CONFIG_PATH, "w") as f:
            yaml.dump(config, f, default_flow_style=False)
    except Exception:
        pass


def _sync_user_to_yaml(username, email, first_name, last_name, password_hash, role):
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
# GOOGLE OAUTH HELPERS
# ─────────────────────────────────────────
def _build_google_creds_file():
    pass


def _is_google_configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def _unique_username_from_email(email: str) -> str:
    base = re.sub(r"[^a-z0-9]", "_", email.split("@")[0].lower()).strip("_") or "user"
    if not _db_get_user(base):
        return base
    suffix = hashlib.sha256(email.encode("utf-8")).hexdigest()[:8]
    return f"{base}_{suffix}"


def _handle_google_user(user_info: dict) -> bool:
    """Process authenticated Google profile and populate session_state."""
    g_email = (user_info.get("email") or "").strip().lower()
    g_name = user_info.get("name") or ""
    if not g_email:
        return False
    if user_info.get("email_verified") is not True:
        _auth_log.warning("Rejected Google login for unverified email: %s", g_email)
        return False

    existing_user = _db_get_user_by_email(g_email)

    if existing_user:
        username = existing_user.get("username") or _unique_username_from_email(g_email)
        first_name = existing_user.get("first_name") or g_email.split("@")[0]
    else:
        username = _unique_username_from_email(g_email)
        first_name = (g_name.split()[0] if g_name else g_email.split("@")[0]).title()
        last_name = " ".join(g_name.split()[1:]) if len(g_name.split()) > 1 else ""
        random_pw_hash = _hash_password(_secrets.token_urlsafe(32))

        try:
            from core.database import users_query_succeeded as _users_ok
            db_ok = _users_ok()
        except Exception:
            db_ok = False
        existing = _db_get_all_users() if db_ok else None
        role = "admin" if (db_ok and existing == []) else "user"

        try:
            _db_create_user(username, g_email, first_name, last_name, random_pw_hash, role)
        except Exception:
            _auth_log.exception("Failed to create Google OAuth user")
            return False
        _sync_user_to_yaml(username, g_email, first_name, last_name, random_pw_hash, role)

    st.session_state["authentication_status"] = True
    st.session_state["username"] = username
    st.session_state["name"] = g_name or first_name
    st.session_state["user_id"] = g_email
    st.session_state["auth_method"] = "google"
    return True


def _show_google_signin() -> bool:
    """Show Google sign-in using a POPUP window.

    v6.3 FIX — Root cause of the loop:
      st.link_button() navigated the SAME browser tab to Google.
      When Google redirected back, Streamlit created a brand-new WebSocket
      session. The code exchange succeeded and set session_state, but then
      st.rerun() created yet another new session (session_state wiped again),
      causing an infinite auth → session_loss → auth loop with no error shown.

    Solution:
      1. JavaScript opens Google consent in a POPUP (window.open).
      2. The MAIN Streamlit session stays alive with its session_state intact.
      3. Popup lands on pages/99_OAuth_Callback.py which does the code exchange
         server-side and writes {prosper_auth_result: {email, name, verified}}
         into localStorage.
      4. Main app polls localStorage every 500ms via a JS component.
      5. On result detected → call _handle_google_user() → st.rerun() → logged in.
    """
    if not _is_google_configured():
        return False

    g_cid = os.getenv("GOOGLE_CLIENT_ID", "")
    base_url = os.getenv("GOOGLE_REDIRECT_URI", "https://prosper-gzlf.onrender.com")
    # Callback page URL — Streamlit multi-page apps use this path pattern
    callback_url = base_url.rstrip("/") + "/OAuth_Callback"

    try:
        import urllib.parse

        # ── Check if popup wrote result to localStorage ──────────────────────
        # We use a hidden HTML component to read localStorage and signal back.
        # Streamlit components can't directly read localStorage, so we use
        # st.query_params as a relay: the callback page sets ?auth_done=1
        # which triggers a rerun with the result in session_state.
        params = dict(st.query_params)

        # Direct callback on main app URL (fallback if popup not supported)
        if "code" in params and not st.session_state.get("_google_auth_done"):
            received_state = params.get("state", "")
            if not _verify_oauth_state(received_state):
                st.query_params.clear()
                _auth_log.warning("OAuth direct callback: HMAC failed. state=%s", received_state[:16] if received_state else "NONE")
                st.error("Authentication could not be verified. Please try again.")
                return False

            import requests as _req
            code = params["code"]
            st.query_params.clear()
            g_csec = os.getenv("GOOGLE_CLIENT_SECRET", "")
            # Try callback URL first (popup target), fallback to base_url
            redirect_used = callback_url
            token_resp = _req.post(
                "https://oauth2.googleapis.com/token",
                data={"client_id": g_cid, "client_secret": g_csec,
                      "code": code, "grant_type": "authorization_code",
                      "redirect_uri": redirect_used},
                timeout=10,
            )
            if token_resp.status_code != 200:
                # retry with base url as redirect
                redirect_used = base_url
                token_resp = _req.post(
                    "https://oauth2.googleapis.com/token",
                    data={"client_id": g_cid, "client_secret": g_csec,
                          "code": code, "grant_type": "authorization_code",
                          "redirect_uri": redirect_used},
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
                        st.session_state["_google_auth_done"] = True
                        return _handle_google_user(ui_resp.json())
            _auth_log.warning("Google token exchange failed: %s", token_resp.status_code)
            st.error("Google sign-in failed. Please try again or use email login.")
            return False

        # ── Session already has google auth result ────────────────────────────
        if st.session_state.get("_google_auth_done") and st.session_state.get("user_info"):
            return _handle_google_user(st.session_state["user_info"])

        # ── Render guard ──────────────────────────────────────────────────────
        if st.session_state.get("_google_auth_rendered_this_rerun"):
            return False
        st.session_state["_google_auth_rendered_this_rerun"] = True

        # ── Build auth URL targeting the callback page ───────────────────────
        new_state = _make_oauth_state()
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": g_cid,
            "redirect_uri": callback_url,
            "scope": "openid email profile",
            "response_type": "code",
            "access_type": "offline",
            "prompt": "select_account",
            "state": new_state,
        })

        # ── Popup-based OAuth button ─────────────────────────────────────────
        # Opens Google in a popup so main Streamlit session is preserved.
        # The callback page writes the auth result to localStorage and closes.
        # We poll localStorage and relay via query_params.
        popup_js = f"""
        <script>
        (function() {{
            var _prosperPollInterval = null;

            function openGoogleAuth() {{
                var w = 500, h = 620;
                var left = (screen.width - w) / 2;
                var top = (screen.height - h) / 2;
                var popup = window.open(
                    {json.dumps(auth_url)},
                    'prosper_google_auth',
                    'width=' + w + ',height=' + h + ',left=' + left + ',top=' + top +
                    ',scrollbars=yes,resizable=yes,toolbar=no,menubar=no,location=no'
                );

                if (!popup || popup.closed) {{
                    // Popup blocked — fallback to same-tab redirect
                    window.location.href = {json.dumps(auth_url)};
                    return;
                }}

                // Poll localStorage for result written by callback page
                _prosperPollInterval = setInterval(function() {{
                    try {{
                        var result = localStorage.getItem('prosper_auth_result');
                        if (result) {{
                            localStorage.removeItem('prosper_auth_result');
                            clearInterval(_prosperPollInterval);
                            // Relay via URL so Streamlit sees it on rerun
                            var data = JSON.parse(result);
                            if (data.verified && data.email) {{
                                // Encode user info in query params for the main app
                                var params = new URLSearchParams({{
                                    _ga_email: data.email,
                                    _ga_name: data.name || '',
                                    _ga_token: data.token || '',
                                }});
                                window.location.href = window.location.pathname + '?' + params.toString();
                            }} else {{
                                // Auth failed
                                window.location.href = window.location.pathname + '?_ga_error=1';
                            }}
                        }}
                        // Also check if popup was closed without completing
                        if (popup.closed) {{
                            clearInterval(_prosperPollInterval);
                        }}
                    }} catch(e) {{ /* cross-origin or storage error, ignore */ }}
                }}, 600);
            }}

            // Auto-attach to button after render
            document.addEventListener('DOMContentLoaded', function() {{
                var btn = document.getElementById('prosper-google-btn');
                if (btn) btn.addEventListener('click', openGoogleAuth);
            }});
            // Also try immediately (Streamlit may have already loaded DOM)
            setTimeout(function() {{
                var btn = document.getElementById('prosper-google-btn');
                if (btn) btn.addEventListener('click', openGoogleAuth);
            }}, 100);
        }})();
        </script>
        <style>
        #prosper-google-btn {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            width: 100%;
            padding: 11px 16px;
            background: #fff;
            color: #3c4043;
            border: 1px solid #dadce0;
            border-radius: 6px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            font-family: 'Google Sans', Roboto, Arial, sans-serif;
            transition: background 0.2s, box-shadow 0.2s;
            margin: 0;
            letter-spacing: 0.2px;
        }}
        #prosper-google-btn:hover {{
            background: #f8f9fa;
            box-shadow: 0 1px 3px rgba(60,64,67,0.2);
        }}
        #prosper-google-btn img {{ width: 18px; height: 18px; }}
        </style>
        <button id="prosper-google-btn" type="button">
            <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="Google">
            Continue with Google
        </button>
        """

        # ── Handle result relayed back via query params ───────────────────────
        if "_ga_email" in params and not st.session_state.get("_google_auth_done"):
            email = params.get("_ga_email", "")
            name = params.get("_ga_name", "")
            ga_token = params.get("_ga_token", "")
            st.query_params.clear()
            if email:
                # Verify the token is a valid HMAC-signed state (used as auth token)
                if _verify_oauth_state(ga_token):
                    user_info = {"email": email, "name": name, "email_verified": True}
                    st.session_state["_google_auth_done"] = True
                    return _handle_google_user(user_info)
                else:
                    st.error("Google sign-in could not be verified. Please try again.")
                    return False

        if "_ga_error" in params:
            st.query_params.clear()
            st.error("Google sign-in was cancelled or failed. Please try again.")
            return False

        st.html(popup_js)

    except Exception as google_err:
        _auth_log.warning("Google sign-in error: %s", google_err)
        st.warning(f"Google sign-in unavailable: {google_err}")
        st.caption("Please use email login below.")

    return False


# ─────────────────────────────────────────
# REGISTRATION FORM
# ─────────────────────────────────────────
def _show_registration_form(is_first_user: bool = False) -> bool:
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

            username = _unique_username_from_email(email.strip().lower()) if email else ""
            account_exists = bool(
                (username and _db_get_user(username))
                or (email and _db_get_user_by_email(email.strip()))
            )
            if account_exists:
                errors.append("Could not register that account. If you already have one, please sign in.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                hashed = _hash_password(pw)
                try:
                    from core.database import users_query_succeeded as _users_ok
                    db_ok = _users_ok()
                except Exception:
                    db_ok = False
                existing = _db_get_all_users() if db_ok else None
                role = "admin" if ((is_first_user or existing == []) and db_ok) else "user"

                _db_create_user(username, email.strip(), first.strip(), last.strip(), hashed, role)
                _sync_user_to_yaml(username, email.strip(), first.strip(), last.strip(), hashed, role)

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
    """Clear ALL auth-related session state."""
    _auth_keys = {
        "authentication_status", "username", "name", "logout",
        "user_id", "auth_method", "connected", "user_info",
        "_google_auth_rendered", "_google_auth_done",
        "_google_auth_rendered_this_rerun",
        "_oauth_state_pending",
        "FormSubmitter:Login-Login", "FormSubmitter:Login-Submit",
    }
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

    st.session_state["authentication_status"] = None
    st.session_state["logout"] = True


# ─────────────────────────────────────────
# MAIN AUTH ENTRY POINT
# ─────────────────────────────────────────
def run_auth() -> Dict[str, Any]:
    result = {
        "authenticated": False,
        "user_id": "default",
        "display_name": "User",
        "method": "disabled",
    }

    st.session_state.pop("_google_auth_rendered_this_rerun", None)

    auth_enabled = os.getenv("PROSPER_AUTH_ENABLED", "true").lower() in ("true", "1", "yes")

    if not auth_enabled:
        st.session_state.setdefault("user_id", "default")
        result.update(authenticated=True, method="disabled")
        with st.sidebar:
            st.caption("🔓 Auth disabled (dev mode)")
            st.divider()
        return result

    if st.session_state.get("logout") is True:
        st.session_state["logout"] = False
        st.session_state["authentication_status"] = None

    try:
        import yaml
        import streamlit_authenticator as stauth
    except ImportError:
        st.error("Authentication packages not installed. Contact the administrator.")
        st.stop()
        return result

    _build_google_creds_file()

    db_users = _db_get_all_users()
    if db_users:
        auth_config = _rebuild_yaml_from_db()
    else:
        auth_config = _load_yaml_config()

    has_users = bool(
        auth_config
        and auth_config.get("credentials", {}).get("usernames")
    )

    if not has_users:
        _, center, _ = st.columns([1, 2, 1])
        with center:
            st.markdown(_HEADER_HTML, unsafe_allow_html=True)
            st.markdown("")
            if _show_google_signin():
                st.rerun()
            st.markdown(
                "<div style='text-align:center;margin:1rem 0'>"
                "<span style='color:#aaa;font-size:0.9rem'>─── or ───</span></div>",
                unsafe_allow_html=True,
            )
            _show_registration_form(is_first_user=True)
        st.stop()
        return result

    if not auth_config.get("cookie"):
        auth_config["cookie"] = {
            "name": _COOKIE_NAME,
            "key": _COOKIE_KEY,
            "expiry_days": _COOKIE_EXPIRY_DAYS,
        }

    authenticator = stauth.Authenticate(
        auth_config["credentials"],
        auth_config["cookie"]["name"],
        auth_config["cookie"]["key"],
        auth_config["cookie"]["expiry_days"],
    )

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

        with st.sidebar:
            st.markdown(f"👤 **{display_name}**")
            st.caption(f"_{user_email}_" if user_email != username else "")
            if st.button("🚪 Sign Out", key="sidebar_logout", use_container_width=True):
                try:
                    authenticator.logout(location="unrendered")
                except Exception:
                    pass
                do_logout()
                st.rerun()
            st.divider()

        return result

    # ── Not authenticated: Show login page ──
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.markdown(_HEADER_HTML, unsafe_allow_html=True)
        st.markdown("")

        if _show_google_signin():
            st.rerun()

        st.markdown(
            "<div style='text-align:center;margin:0.8rem 0'>"
            "<span style='color:#aaa;font-size:0.9rem'>─── or sign in with email ───</span></div>",
            unsafe_allow_html=True,
        )

        authenticator.login()
        if st.session_state.get("authentication_status") is True:
            username = st.session_state.get("username", "")
            user_data = auth_config.get("credentials", {}).get("usernames", {}).get(username, {})
            st.session_state["user_id"] = user_data.get("email", username)
            st.session_state["auth_method"] = "email"
            st.rerun()
        elif st.session_state.get("authentication_status") is False:
            st.error("Invalid username or password.")
            st.caption("Forgot your password? Contact an administrator or create a new account.")

        st.markdown("")
        with st.expander("👤 Create New Account", expanded=False):
            _show_registration_form(is_first_user=False)

    st.stop()
    return result
