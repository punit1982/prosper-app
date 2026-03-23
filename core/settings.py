"""
Prosper App Settings
====================
Manages app configuration with persistent user preferences.
Settings are stored in ~/prosper_data/user_settings.json and
merged on top of defaults at startup.
"""

import os
import json

# ─────────────────────────────────────────
# DEFAULTS — fallback values if no user settings file exists
# ─────────────────────────────────────────
_DEFAULTS = {

    # ── Display ──
    "base_currency": os.getenv("BASE_CURRENCY", "USD"),

    # ── API Efficiency ──
    "parse_cache_enabled": True,
    "parse_cache_ttl_days": 90,
    "price_cache_ttl_seconds": 300,
    "fetch_key_metrics": True,

    # ── FMP API ──
    "fmp_batch_size": 50,
    "fmp_timeout": 10,

    # ── Portfolio Table Columns ──
    "col_name":            True,
    "col_qty":             True,
    "col_avg_cost":        True,
    "col_current_price":   True,
    "col_day_gain":        True,
    "col_day_gain_pct":    True,
    "col_market_value":    True,
    "col_unrealized_pnl":  True,
    "col_pnl_pct":         True,
    "col_pe_ratio":        True,
    "col_roic":            False,
    "col_debt_equity":     False,
    "col_currency":        True,
    "col_broker":          False,

    # ── Dashboard Preferences (persisted per-screen) ──
    "pref_dash_show_day_gain":     True,
    "pref_dash_show_unrealized":   True,
    "pref_dash_show_extended":     False,
    "pref_dash_show_growth":       False,
    "pref_dash_show_broker":       False,
    "pref_dash_auto_extended":     False,

    # ── Performance Page Preferences ──
    "pref_perf_period":      "1y",
    "pref_perf_benchmarks":  ["S&P 500", "Nasdaq 100", "Nifty 50", "Sensex"],

    # ── News Preferences ──
    "pref_news_auto_summary":  False,
    "pref_news_max_articles":  30,
    "pref_mkt_auto_summary":   False,
}

# Path to persistent user settings file
_SETTINGS_PATH = os.path.expanduser("~/prosper_data/user_settings.json")


def load_user_settings() -> dict:
    """
    Load user settings: try local JSON file first, then database, then defaults.
    This ensures settings survive Render redeploys (DB) and work fast locally (file).
    """
    settings = dict(_DEFAULTS)

    # 1. Try local file (fast, works when filesystem persists)
    loaded_from_file = False
    try:
        if os.path.exists(_SETTINGS_PATH):
            with open(_SETTINGS_PATH, "r") as f:
                user = json.load(f)
            if isinstance(user, dict) and user:
                settings.update(user)
                loaded_from_file = True
    except (json.JSONDecodeError, IOError, OSError):
        pass

    # 2. If no local file, try database (survives redeploys)
    if not loaded_from_file:
        try:
            import streamlit as st
            user_id = st.session_state.get("user_id", "default")
            from core.database import get_user_settings_db
            db_settings = get_user_settings_db(user_id)
            if db_settings:
                settings.update(db_settings)
        except Exception:
            pass  # DB not available yet — use defaults

    return settings


def save_user_settings(updates: dict):
    """
    Save user preference overrides to JSON file.
    Only saves keys that differ from defaults to keep the file clean.
    """
    # Load existing user overrides (not merged with defaults)
    existing = {}
    try:
        if os.path.exists(_SETTINGS_PATH):
            with open(_SETTINGS_PATH, "r") as f:
                existing = json.load(f)
    except (json.JSONDecodeError, IOError, OSError):
        pass

    # Merge new updates
    existing.update(updates)

    # Write to local file (best-effort — may fail on ephemeral filesystem)
    try:
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        with open(_SETTINGS_PATH, "w") as f:
            json.dump(existing, f, indent=2)
    except OSError:
        pass  # Ephemeral filesystem (Render free tier) — DB is the fallback

    # Also persist to database (survives redeploys)
    try:
        import streamlit as st
        user_id = st.session_state.get("user_id", "default")
        from core.database import save_user_settings_db
        save_user_settings_db(user_id, existing)
    except Exception:
        pass  # DB save is best-effort

    # Update the module-level SETTINGS dict so all code sees new values immediately
    global SETTINGS
    SETTINGS.update(updates)


def get_defaults() -> dict:
    """Return a copy of the default settings."""
    return dict(_DEFAULTS)


def get_api_key(key_name: str) -> str:
    """
    Get an API key by name from environment variables.
    On Render/Docker, all secrets are env vars.
    Falls back to Streamlit secrets only if a secrets.toml file exists.
    """
    # 1. Environment variable (primary — Render, Docker, local .env)
    val = os.getenv(key_name, "")
    if val:
        return val

    # 2. Streamlit secrets (only if secrets.toml actually exists)
    secrets_paths = [
        os.path.expanduser("~/.streamlit/secrets.toml"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".streamlit", "secrets.toml"),
    ]
    if any(os.path.exists(p) for p in secrets_paths):
        try:
            import streamlit as st
            try:
                val = st.secrets[key_name]
                if val:
                    return str(val)
            except (KeyError, Exception):
                pass
        except Exception:
            pass

    return ""


def call_claude(client, messages, max_tokens=1024, preferred_model="claude-sonnet-4-5", system=None):
    """
    Call Claude API with automatic model fallback.
    Tries multiple model IDs until one works — handles different API tiers/regions.
    Returns the API response object.
    Raises Exception if ALL models fail.
    """
    _FALLBACK_MODELS = [
        "claude-sonnet-4-5-20250514",
        "claude-haiku-4-5-20250514",
        "claude-3-5-sonnet-20241022",
    ]

    # Put the preferred model first, deduplicate
    models_to_try = [preferred_model] + [m for m in _FALLBACK_MODELS if m != preferred_model]

    _extra = {}
    if system:
        _extra["system"] = system

    last_error = None
    for model in models_to_try:
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                **_extra,
            )
            return response
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "not_found" in err_str:
                last_error = e
                continue  # try next model
            raise  # non-404 errors should propagate immediately

    raise Exception(
        f"No Claude model accessible with your API key. "
        f"Verify billing at console.anthropic.com. Last error: {last_error}"
    )


# ─────────────────────────────────────────
# LIVE SETTINGS — loaded once at import time, updated when user saves
# ─────────────────────────────────────────
SETTINGS = load_user_settings()
