"""
Prosper — Google OAuth Callback Handler
========================================
This page handles the Google OAuth redirect.

Flow:
  1. User clicks 'Continue with Google' in the POPUP window opened by auth.py
  2. Google redirects the popup browser to this page with ?code=&state=
  3. This page exchanges the code for a token server-side
  4. Writes the auth result to localStorage so the MAIN window can read it
  5. Closes the popup automatically

This approach preserves the main Streamlit session (no session_state loss).
The redirect_uri registered in Google Console must be:
  https://prosper-gzlf.onrender.com/OAuth_Callback

IMPORTANT: Also keep the base URL registered:
  https://prosper-gzlf.onrender.com
for fallback direct-tab OAuth.

v6.5 FIX:
  All st.html() calls replaced with st.components.v1.html().
  st.html() renders in a sandboxed iframe WITHOUT allow-same-origin,
  so localStorage.setItem() throws SecurityError and window.close() silently
  fails — the popup stays open forever and the main window never gets the
  auth result. st.components.v1.html() has the correct sandbox flags.
"""
import os
import json
import hashlib
import hmac
import secrets as _secrets

import streamlit as st
import streamlit.components.v1 as _components

st.set_page_config(
    page_title="Prosper — Signing in...",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Hide sidebar and ALL chrome — this is a bare callback page
st.markdown("""
<style>
[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stNavigation"],
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
header, footer { display: none !important; }
.main .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

# ── Load signing key (same as auth.py) ───────────────────────────────────────
_COOKIE_KEY = os.getenv("PROSPER_COOKIE_SECRET", "")
if not _COOKIE_KEY:
    _COOKIE_KEY = "dev-placeholder"
_OAUTH_SIGNING_KEY = _COOKIE_KEY.encode()


def _verify_oauth_state(state: str) -> bool:
    if not state or "." not in state:
        return False
    nonce, _, received_sig = state.partition(".")
    expected_sig = hmac.new(_OAUTH_SIGNING_KEY, nonce.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_sig, received_sig)


def _make_signed_token(email: str) -> str:
    """Create a short-lived HMAC token for the email, used to verify the localStorage relay."""
    sig = hmac.new(_OAUTH_SIGNING_KEY, email.encode(), hashlib.sha256).hexdigest()
    return f"{email}.{sig}"


def _close_popup_html(result_json: str, delay_ms: int = 800) -> str:
    """Return a full HTML page that writes to localStorage and closes the popup.
    Uses st.components.v1.html() — NOT st.html() — so localStorage works.
    """
    return f"""
    <!DOCTYPE html>
    <html>
    <head><style>body{{margin:0;padding:0;background:transparent;}}</style></head>
    <body>
    <script>
    (function() {{
        var result = {result_json};
        try {{
            localStorage.setItem('prosper_auth_result', JSON.stringify(result));
        }} catch(e) {{
            // localStorage blocked (Safari ITP) — relay via postMessage to opener
            if (window.opener) {{
                window.opener.postMessage({{ type: 'prosper_auth', payload: result }}, '*');
            }}
        }}
        setTimeout(function() {{
            try {{ window.close(); }} catch(e) {{}}
            // If window.close() blocked, redirect to app root
            setTimeout(function() {{ window.location.href = '/'; }}, 500);
        }}, {delay_ms});
    }})();
    </script>
    </body>
    </html>
    """


params = dict(st.query_params)
code = params.get("code", "")
state = params.get("state", "")
error = params.get("error", "")

g_cid = os.getenv("GOOGLE_CLIENT_ID", "")
g_csec = os.getenv("GOOGLE_CLIENT_SECRET", "")
base_url = os.getenv("GOOGLE_REDIRECT_URI", "https://prosper-gzlf.onrender.com")
callback_url = base_url.rstrip("/") + "/OAuth_Callback"

if error:
    st.markdown("""
    <div style='text-align:center;padding:2rem'>
        <div style='font-size:2rem'>❌</div>
        <h3>Sign-in cancelled</h3>
        <p style='color:#888'>Closing this window...</p>
    </div>
    """, unsafe_allow_html=True)
    _components.html(
        _close_popup_html(json.dumps({"verified": False, "error": "cancelled"})),
        height=0,
        scrolling=False,
    )
    st.stop()

elif code and state:
    if not _verify_oauth_state(state):
        st.markdown("""
        <div style='text-align:center;padding:2rem'>
            <div style='font-size:2rem'>🔒</div>
            <h3>Security check failed</h3>
            <p style='color:#888'>The request could not be verified. Please try again.</p>
        </div>
        """, unsafe_allow_html=True)
        _components.html(
            _close_popup_html(json.dumps({"verified": False, "error": "hmac_fail"}), delay_ms=1500),
            height=0,
            scrolling=False,
        )
        st.stop()

    # Exchange code for token
    st.markdown("""
    <div style='text-align:center;padding:3rem'>
        <div style='font-size:2rem'>⏳</div>
        <h3 style='font-weight:500'>Signing you in...</h3>
        <p style='color:#888;font-size:0.9rem'>Please wait, do not close this window.</p>
    </div>
    """, unsafe_allow_html=True)

    try:
        import requests as _req

        token_resp = _req.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": g_cid,
                "client_secret": g_csec,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": callback_url,
            },
            timeout=12,
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
                    email = (user_info.get("email") or "").strip().lower()
                    name = user_info.get("name") or ""
                    verified = user_info.get("email_verified") is True

                    if email and verified:
                        auth_token = _make_signed_token(email)
                        result_payload = {
                            "verified": True,
                            "email": email,
                            "name": name,
                            "token": auth_token,
                        }
                        st.markdown("""
                        <div style='text-align:center;padding:3rem'>
                            <div style='font-size:2.5rem'>✅</div>
                            <h3 style='font-weight:500'>Signed in!</h3>
                            <p style='color:#888'>Closing this window...</p>
                        </div>
                        """, unsafe_allow_html=True)
                        # v6.5 FIX: st.components.v1.html() — localStorage works here
                        _components.html(
                            _close_popup_html(json.dumps(result_payload), delay_ms=800),
                            height=0,
                            scrolling=False,
                        )
                        st.stop()

        err_detail = token_resp.text[:200] if token_resp.status_code != 200 else "No access token returned"
        st.markdown(f"""
        <div style='text-align:center;padding:2rem'>
            <div style='font-size:2rem'>⚠️</div>
            <h3>Sign-in failed</h3>
            <p style='color:#888'>Could not complete Google authentication.<br>
            <small>{err_detail}</small></p>
        </div>
        """, unsafe_allow_html=True)
        _components.html(
            _close_popup_html(json.dumps({"verified": False, "error": "token_exchange_failed"}), delay_ms=2500),
            height=0,
            scrolling=False,
        )

    except Exception as exc:
        st.error(f"Authentication error: {exc}")
        _components.html(
            _close_popup_html(json.dumps({"verified": False, "error": "exception"}), delay_ms=2500),
            height=0,
            scrolling=False,
        )

else:
    st.markdown("""
    <div style='text-align:center;padding:3rem'>
        <h2>Prosper</h2>
        <p style='color:#888'>This page handles Google sign-in callbacks.</p>
        <p><a href='/'>← Back to Prosper</a></p>
    </div>
    """, unsafe_allow_html=True)
