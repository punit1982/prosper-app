"""
Startup Checks — Prosper
========================
Runs once at application boot to validate required environment variables
and configuration. Fails fast with actionable error messages so issues
are caught at startup, not mid-request.

Usage (call from Prosper.py before any other imports):
    from core.startup_checks import run_startup_checks
    run_startup_checks()
"""

import os
import logging

_log = logging.getLogger("prosper.startup")

# ── Required env vars in production ───────────────────────────────────────
# Each entry: (env_var_name, description, is_required_in_production)
_REQUIRED_ENV_VARS = [
    ("PROSPER_COOKIE_SECRET",        "Session cookie signing key (32-char hex)",       True),
    ("PROSPER_GOOGLE_COOKIE_SECRET", "Google OAuth cookie signing key (32-char hex)",   True),
]

# ── Optional but warned-about env vars ────────────────────────────────────
_OPTIONAL_ENV_VARS = [
    ("GOOGLE_CLIENT_ID",     "Google OAuth — sign-in with Google will be disabled"),
    ("GOOGLE_CLIENT_SECRET", "Google OAuth — sign-in with Google will be disabled"),
    ("ANTHROPIC_API_KEY",    "AI features (chat, summaries) will be disabled"),
    ("FINNHUB_API_KEY",      "Finnhub analyst data will be unavailable"),
    ("SERPER_API_KEY",       "Web-search-based news enrichment will be disabled"),
    ("TURSO_DATABASE_URL",   "Will fall back to local SQLite — data not persisted on Render"),
    ("TURSO_AUTH_TOKEN",     "Will fall back to local SQLite — data not persisted on Render"),
]


def _is_production() -> bool:
    return (
        os.getenv("PROSPER_ENV", "").lower() == "production"
        or bool(os.getenv("RENDER"))
    )


def run_startup_checks(raise_on_error: bool = True) -> list:
    """
    Validate environment configuration at startup.

    Returns a list of warning strings (non-fatal issues).
    Raises RuntimeError on fatal missing required vars in production
    (unless raise_on_error=False — useful in tests).
    """
    errors = []
    warnings = []
    is_prod = _is_production()

    # ── Required checks ───────────────────────────────────────────────────
    for var, description, required_in_prod in _REQUIRED_ENV_VARS:
        value = os.getenv(var, "")
        if not value:
            if required_in_prod and is_prod:
                msg = (
                    f"FATAL: Required env var '{var}' is not set in production.\n"
                    f"  Purpose: {description}\n"
                    f"  Fix: Set this in your Render environment variables.\n"
                    f"  Generate: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
                errors.append(msg)
                _log.critical(msg)
            else:
                warn = f"WARNING: '{var}' not set — using ephemeral dev key. ({description})"
                warnings.append(warn)
                _log.warning(warn)
        elif len(value) < 32:
            warn = f"WARNING: '{var}' looks too short ({len(value)} chars) — recommend 32+ char hex."
            warnings.append(warn)
            _log.warning(warn)

    # ── Optional checks ───────────────────────────────────────────────────
    for var, impact in _OPTIONAL_ENV_VARS:
        if not os.getenv(var, ""):
            warn = f"INFO: '{var}' not set — {impact}"
            warnings.append(warn)
            _log.info(warn)

    # ── Database connectivity pre-check ──────────────────────────────────
    turso_url = os.getenv("TURSO_DATABASE_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    if is_prod and (not turso_url or not turso_token):
        warn = (
            "WARNING: TURSO_DATABASE_URL or TURSO_AUTH_TOKEN not set. "
            "Data will use local SQLite and will NOT persist across Render restarts."
        )
        warnings.append(warn)
        _log.warning(warn)

    # ── Raise on fatal errors ─────────────────────────────────────────────
    if errors and raise_on_error:
        raise RuntimeError(
            "Prosper startup failed — missing required configuration:\n\n"
            + "\n\n".join(errors)
        )

    return warnings


def check_and_display_warnings():
    """
    Run checks and display any warnings in the Streamlit UI (dev mode only).
    Silent in production — errors are fatal before UI renders.
    """
    import streamlit as st
    try:
        warnings = run_startup_checks(raise_on_error=_is_production())
        if warnings and not _is_production():
            with st.sidebar:
                with st.expander("⚠️ Config Warnings", expanded=False):
                    for w in warnings:
                        if w.startswith("WARNING"):
                            st.warning(w, icon="⚠️")
                        elif w.startswith("INFO"):
                            st.info(w, icon="ℹ️")
    except RuntimeError as e:
        import streamlit as st
        st.error(str(e))
        st.stop()
