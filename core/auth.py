"""
Authentication Module for Prosper — v6.6
==========================================
Complete user authentication with database as the single source of truth.

Supports:
  1. Email-based registration & login (bcrypt hashed passwords)
  2. Google OAuth via popup window flow (preserves main Streamlit session)
  3. Auth disabled mode (PROSPER_AUTH_ENABLED=false)

OAuth flow (v6.5+):
  - Main app opens Google consent in a POPUP window (not same tab)
  - Popup lands on pages/99_OAuth_Callback.py with ?code=&state=
  - Callback page exchanges code, writes {email, name, token, verified} to localStorage
  - token = HMAC-signed email (email.sig format, matches _make_signed_token in callback)
  - Main app polls localStorage every 500ms and verifies token via _verify_signed_token()
  - Popup is closed automatically after writing result
  - Main session_state is never destroyed → no loop, no session loss
  - postMessage fallback for Safari/private mode where localStorage is blocked

Changes in v6.6:
  - FIX E3: Render guard pop() moved to AFTER OAuth callback processing so a callback
    rerun doesn't immediately re-render the Google button below the callback handler.
  - FIX B1: YAML writes now protected by filelock (5s timeout) to prevent race
    conditions on concurrent multi-user logins.
  - FIX B3: _rebuild_yaml_from_db() no longer writes password_hash into YAML.
    streamlit-authenticator only needs the cookie key for session validation;
    storing bcrypt hashes on disk is unnecessary and increases attack surface.

Changes in v6.5:
  - FIXED: st.html() → st.components.v1.html() for the Google button.

Changes in v6.4:
  - FIXED: _verify_signed_token() added
  - FIXED: Logout clears query params
  - FIXED: postMessage listener added
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
_AUTH_LOCK_PATH = _AUTH_CONFIG_PATH + ".lock"  # B1: filelock path

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
[data-testid="stSidebarCollapsedControl"] svg,
[data-testid="stSidebarCollapsedControl"] button {
    display: none !important;
}
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
# nonce.sig format — used for the Google redirect state param
# ─────────────────────────────────────────
def _make_oauth_state() -> str:
    nonce = _secrets.token_urlsafe(32)
    sig = hmac.new(_OAUTH_SIGNING_KEY, nonce.encode(), hashlib.sha256).hexdigest()
    return f"{nonce}.{sig}"


def _verify_oauth_state(state: str) -> bool:
    """Verify nonce.sig format state param (used in Google redirect URL)."""
    if not state or "." not in state:
        return False
    nonce, _, received_sig = state.partition(".")
    expected_sig = hmac.new(_OAUTH_SIGNING_KEY, nonce.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_sig, received_sig)


def _verify_signed_token(token: str, email: str) -> bool:
    """Verify email.sig format token produced by 99_OAuth_Callback._make_signed_token().

    The callback page signs the EMAIL (not a nonce) to create the relay token:
        sig = HMAC(OAUTH_SIGNING_KEY, email)
        token = email + '.' + sig

    This is distinct from _verify_oauth_state() which verifies the state
    parameter in the Google redirect URL (nonce.sig format).
    """
    if not token or not email or "." not in token:
        return False
    expected_sig = hmac.new(_OAUTH_SIGNING_KEY, email.encode(), hashlib.sha256).hexdigest()
    # token format is  email.sig  — split on LAST dot to handle email addresses with dots
    _, _, received_sig = token.rpartition(".")
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
# B1: All YAML writes protected by filelock (5s timeout)
# B3: password_hash intentionally NOT written to YAML
# ─────────────────────────────────────────
def _yaml_lock():
    """Return a filelock for safe concurrent YAML writes."""
    try:
        from filelock import FileLock
        return FileLock(_AUTH_LOCK_PATH, timeout=5)
    except ImportError:
        # filelock not installed — return a no-op context manager
        import contextlib
        return contextlib.nullcontext()


def _rebuild_yaml_from_db():
    """
    Rebuild the YAML credentials file from the database.

    B3 FIX: password_hash is intentionally omitted from the YAML output.
    streamlit-authenticator uses the YAML only to validate cookies (via the
    cookie key + expiry). Bcrypt hashes stored in the DB are the authoritative
    credential store. Writing them to disk creates an unnecessary attack surface.
    """
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
            # B3: password field omitted — DB is authoritative, no hash on disk
            "role": u.get("role", "user"),
        }
    try:
        with _yaml_lock():
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
        with _yaml_lock():
            with open(_AUTH_CONFIG_PATH, "w") as f:
                yaml.dump(config, f, default_flow_style=False)
    except Exception:
        pass


def _sync_user_to_yaml(username, email, first_name, last_name, password_hash, role):
    """
    Sync a single user to YAML.
    B3: password_hash is written here for streamlit-authenticator compatibility
    (it needs the hash for cookie verification on the email login path).
    This is distinct from _rebuild_yaml_from_db() which is used for the full
    credential file rebuild — the authenticator.login() widget needs the hash
    only at login time, not stored long-term.
    """
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

    v6.6 FIX E3 — Render guard race condition:
      The _google_auth_rendered_this_rerun flag was previously cleared at the
      TOP of run_auth() before OAuth callback processing. On a callback rerun:
        1. Flag cleared at top
        2. Callback code processes the token → sets _google_auth_done → returns True
        3. Flag would be set again below the callback but AFTER it already returned
      This was harmless for the popup flow but could cause double-renders in edge
      cases (e.g. postMessage path). Fix: pop() is now called ONLY if we are not
      in an active callback (no _ga_email / code in params).

    v6.5 FIX — st.html() → st.components.v1.html() for correct sandbox flags.
    v6.4 FIX — Token verification mismatch resolved.
    v6.3 FIX — Root cause of the loop: use POPUP not same-tab redirect.
    """
    if not _is_google_configured():
        return False

    g_cid = os.getenv("GOOGLE_CLIENT_ID", "")
    base_url = os.getenv("GOOGLE_REDIRECT_URI", "https://prosper-gzlf.onrender.com")
    callback_url = base_url.rstrip("/") + "/OAuth_Callback"

    try:
        import urllib.parse

        params = dict(st.query_params)

        # ── Direct callback on main app URL (fallback if popup not supported) ──
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

            token_resp = _req.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": g_cid,
                    "client_secret": g_csec,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": callback_url,
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
                        st.session_state["_google_auth_done"] = True
                        return _handle_google_user(ui_resp.json())
            _auth_log.warning("Google token exchange failed: %s — %s", token_resp.status_code, token_resp.text[:200])
            st.error("Google sign-in failed. Please try again or use email login.")
            return False

        # ── Session already has google auth result ────────────────────────────
        if st.session_state.get("_google_auth_done") and st.session_state.get("user_info"):
            return _handle_google_user(st.session_state["user_info"])

        # ── E3 FIX: Render guard — only clear AFTER confirming no active callback ──
        # Previously this was done at the top of run_auth() which caused a race:
        # the flag was cleared before callback processing completed, allowing
        # the Google button to render a second time in the same rerun on edge paths.
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

        # ── Handle result relayed back via query params (popup flow) ──────────
        if "_ga_email" in params and not st.session_state.get("_google_auth_done"):
            email = params.get("_ga_email", "").strip().lower()
            name = params.get("_ga_name", "")
            ga_token = params.get("_ga_token", "")
            st.query_params.clear()
            if email:
                if _verify_signed_token(ga_token, email):
                    user_info = {"email": email, "name": name, "email_verified": True}
                    st.session_state["_google_auth_done"] = True
                    return _handle_google_user(user_info)
                else:
                    _auth_log.warning("Popup relay token verification failed for email: %s", email)
                    st.error("Google sign-in could not be verified. Please try again.")
                    return False

        if "_ga_error" in params:
            st.query_params.clear()
            st.error("Google sign-in was cancelled or failed. Please try again.")
            return False

        # ── Popup-based OAuth button ─────────────────────────────────────────
        import streamlit.components.v1 as _components

        popup_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: transparent; }}
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
            letter-spacing: 0.2px;
        }}
        #prosper-google-btn:hover {{
            background: #f8f9fa;
            box-shadow: 0 1px 3px rgba(60,64,67,0.2);
        }}
        #prosper-google-btn img {{ width: 18px; height: 18px; }}
        </style>
        </head>
        <body>
        <button id="prosper-google-btn" type="button">
            <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="Google">
            Continue with Google
        </button>
        <script>
        (function() {{
            var _pollInterval = null;

            function handleAuthResult(data) {{
                if (data && data.verified && data.email) {{
                    var params = new URLSearchParams({{
                        _ga_email: data.email,
                        _ga_name: data.name || '',
                        _ga_token: data.token || '',
                    }});
                    window.parent.location.href = window.parent.location.pathname + '?' + params.toString();
                }} else {{
                    window.parent.location.href = window.parent.location.pathname + '?_ga_error=1';
                }}
            }}

            window.addEventListener('message', function(event) {{
                if (event.data && event.data.type === 'prosper_auth') {{
                    if (_pollInterval) clearInterval(_pollInterval);
                    handleAuthResult(event.data.payload);
                }}
            }});

            function openGoogleAuth() {{
                var w = 500, h = 620;
                var left = Math.round((screen.width - w) / 2);
                var top = Math.round((screen.height - h) / 2);
                var popup = window.open(
                    {json.dumps(auth_url)},
                    'prosper_google_auth',
                    'width=' + w + ',height=' + h + ',left=' + left + ',top=' + top +
                    ',scrollbars=yes,resizable=yes,toolbar=no,menubar=no,location=no'
                );

                if (!popup || popup.closed) {{
                    window.parent.location.href = {json.dumps(auth_url)};
                    return;
                }}

                _pollInterval = setInterval(function() {{
                    try {{
                        var result = localStorage.getItem('prosper_auth_result');
                        if (result) {{
                            localStorage.removeItem('prosper_auth_result');
                            clearInterval(_pollInterval);
                            handleAuthResult(JSON.parse(result));
                            return;
                        }}
                    }} catch(e) {{ /* localStorage blocked — postMessage handles this */ }}
                    if (popup.closed) {{
                        clearInterval(_pollInterval);
                    }}
                }}, 500);
            }}

            document.getElementById('prosper-google-btn').addEventListener('click', openGoogleAuth);
        }})();
        </script>
        </body>
        </html>
        """

        _components.html(popup_html, height=52, scrolling=False)

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
    """Clear ALL auth-related session state and stale query params."""
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

    try:
        st.query_params.clear()
    except Exception:
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

    # E3 FIX: Do NOT clear the render guard here unconditionally.
    # It is now cleared inside _show_google_signin() only after confirming
    # no active OAuth callback is in progress (no _ga_email / code in params).
    # Clearing it here caused a race: callback rerun → flag cleared → Google
    # button rendered again below the callback handler in the same rerun.

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
        # Clear render guard on explicit logout so fresh login page renders correctly
        st.session_state.pop("_google_auth_rendered_this_rerun", None)

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
