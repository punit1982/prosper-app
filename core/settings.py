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
    Load user settings from JSON file and merge with defaults.
    User settings override defaults. Missing keys fall back to defaults.
    """
    settings = dict(_DEFAULTS)
    try:
        if os.path.exists(_SETTINGS_PATH):
            with open(_SETTINGS_PATH, "r") as f:
                user = json.load(f)
            if isinstance(user, dict):
                settings.update(user)
    except (json.JSONDecodeError, IOError, OSError):
        pass  # Corrupted or unreadable — use defaults
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

    # Write back
    os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
    with open(_SETTINGS_PATH, "w") as f:
        json.dump(existing, f, indent=2)


def get_defaults() -> dict:
    """Return a copy of the default settings."""
    return dict(_DEFAULTS)


def get_api_key(key_name: str) -> str:
    """
    Get an API key by name, checking multiple sources:
    1. os.environ / .env file  (local development)
    2. st.secrets              (Streamlit Cloud deployment)
    Returns empty string if not found anywhere.
    """
    # 1. Environment variable (works locally with .env)
    val = os.getenv(key_name, "")
    if val:
        return val

    # 2. Streamlit Cloud secrets — try multiple access patterns
    try:
        import streamlit as st
        # Pattern A: direct key access (most reliable)
        try:
            val = st.secrets[key_name]
            if val:
                return str(val)
        except KeyError:
            pass
        # Pattern B: .get() fallback
        try:
            val = st.secrets.get(key_name, "")
            if val:
                return str(val)
        except Exception:
            pass
        # Pattern C: check nested [secrets] table (some Streamlit versions)
        try:
            val = st.secrets["secrets"][key_name]
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
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-haiku-20240307",
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
