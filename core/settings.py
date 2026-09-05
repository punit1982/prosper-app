"""
Prosper App Settings
====================
Manages app configuration with persistent, PER-USER preferences.

Storage:
  • Database  (user_preferences table, keyed by user_id) — survives Render redeploys
  • Local file (~/prosper_data/user_settings.json)       — fast path for single-user/local

v6.7 changes (audit):
  • SETTINGS is now a per-session proxy instead of one module-level dict shared by
    every logged-in user. Previously user A changing base currency changed it for
    user B, and saved preferences were NOT loaded at startup (they reverted to
    defaults after every restart/redeploy).
  • Claude model IDs updated to the current generation; retired IDs 404.
  • extract_text() helper — current Claude models can return thinking blocks
    before the text block, so `response.content[0].text` is no longer safe.
"""

import os
import json
from typing import Any, Dict, Iterator

# ─────────────────────────────────────────
# DEFAULTS — fallback values if no user settings exist
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

_SESSION_KEY = "_prosper_settings"
_SESSION_LOADED_KEY = "_prosper_settings_loaded_for"


def _session_state():
    """Return st.session_state if we're inside a running Streamlit script, else None."""
    try:
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is None:
            return None
        return st.session_state
    except Exception:
        return None


def _current_user_id() -> str:
    ss = _session_state()
    try:
        uid = (ss.get("user_id") if ss is not None else None) or "default"
        return str(uid).strip() or "default"
    except Exception:
        return "default"


def _read_settings_file() -> dict:
    try:
        if os.path.exists(_SETTINGS_PATH):
            with open(_SETTINGS_PATH, "r") as f:
                user = json.load(f)
            if isinstance(user, dict):
                return user
    except (json.JSONDecodeError, IOError, OSError):
        pass
    return {}


def _read_settings_db(user_id: str) -> dict:
    try:
        from core.database import get_user_settings_db
        db_settings = get_user_settings_db(user_id)
        return db_settings if isinstance(db_settings, dict) else {}
    except Exception:
        return {}


def _load_user_overrides(user_id: str = None) -> dict:
    """Return ONLY the user's saved overrides (not merged with defaults).

    Order:
      • Logged-in user (user_id != 'default'): database first (per-user, survives
        redeploys), then local file as a fallback.
      • Legacy/local single-user mode: local file first, then database.
    """
    user_id = user_id or _current_user_id()
    if user_id != "default":
        overrides = _read_settings_db(user_id)
        if overrides:
            return overrides
        return _read_settings_file()
    overrides = _read_settings_file()
    if overrides:
        return overrides
    return _read_settings_db(user_id)


def load_user_settings() -> dict:
    """Return the effective settings for the current user (defaults + overrides)."""
    settings = dict(_DEFAULTS)
    settings.update(_load_user_overrides())
    return settings


def save_user_settings(updates: dict):
    """Persist preference overrides for the current user (file + database)."""
    if not updates:
        return
    user_id = _current_user_id()

    existing = _load_user_overrides(user_id)
    existing.update(updates)

    # Write to local file (best-effort — may fail on ephemeral filesystem)
    try:
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        with open(_SETTINGS_PATH, "w") as f:
            json.dump(existing, f, indent=2, default=str)
    except OSError:
        pass  # Ephemeral filesystem (Render free tier) — DB is the fallback

    # Persist to database (per-user, survives redeploys)
    try:
        from core.database import save_user_settings_db
        save_user_settings_db(user_id, existing)
    except Exception:
        pass  # DB save is best-effort

    # Update the live settings so all code sees new values immediately
    SETTINGS.update(updates)


def reset_user_settings():
    """Delete all saved overrides for the current user (file + database)."""
    try:
        if os.path.exists(_SETTINGS_PATH):
            os.remove(_SETTINGS_PATH)
    except OSError:
        pass
    try:
        from core.database import save_user_settings_db
        save_user_settings_db(_current_user_id(), {})
    except Exception:
        pass
    SETTINGS.replace(dict(_DEFAULTS))


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


# ─────────────────────────────────────────
# CLAUDE MODELS — single source of truth
# ─────────────────────────────────────────
# Current-generation model IDs. Older IDs (claude-3-5-haiku-*, claude-sonnet-4-2025*,
# claude-opus-4-1-*) are retired and return 404 — every AI feature silently failed.
CLAUDE_DEFAULT_MODEL = "claude-sonnet-5"    # everyday: screenshot parsing, chat, briefings
CLAUDE_BEST_MODEL    = "claude-opus-5"      # deepest reasoning (fallback / full analysis)
CLAUDE_FAST_MODEL    = "claude-haiku-4-5"   # cheapest: one-line news/analyst summaries

# D5: fallback ladder. Imported by core/screenshot_parser.py and any other caller so a
# new Claude release only requires one edit, not N.
CLAUDE_MODEL_PRIORITY = [
    CLAUDE_DEFAULT_MODEL,
    CLAUDE_BEST_MODEL,
    CLAUDE_FAST_MODEL,
]


def extract_text(response) -> str:
    """Return the concatenated text of a Claude response.

    Current models may return a `thinking` block BEFORE the `text` block, so
    `response.content[0].text` raises AttributeError. Always use this helper.
    """
    parts = []
    try:
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", "") == "text":
                parts.append(block.text)
    except Exception:
        pass
    if parts:
        return "".join(parts)
    # Last resort — legacy shape
    try:
        return response.content[0].text
    except Exception:
        return ""


def call_claude(client, messages, max_tokens=1024, preferred_model=None, system=None):
    """
    Call Claude API with automatic model fallback.
    Tries multiple model IDs until one works — handles retired IDs / API tiers.
    Returns the API response object (use extract_text() to read it).
    Raises Exception if ALL models fail.
    """
    preferred_model = preferred_model or CLAUDE_DEFAULT_MODEL
    models_to_try = [preferred_model] + [m for m in CLAUDE_MODEL_PRIORITY if m != preferred_model]

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
            status = getattr(e, "status_code", None)
            if status == 404 or "404" in err_str or "not_found" in err_str:
                last_error = e
                continue  # try next model
            raise  # non-404 errors should propagate immediately

    raise Exception(
        f"No Claude model accessible with your API key. "
        f"Verify billing at console.anthropic.com. Last error: {last_error}"
    )


# ─────────────────────────────────────────
# LIVE SETTINGS — per-session proxy
# ─────────────────────────────────────────
class _SettingsProxy:
    """Dict-like view of the current user's settings.

    Inside a Streamlit session the data lives in st.session_state, so each
    logged-in user has their own copy. Outside a session (tests, scripts) it
    falls back to a module-level dict.
    """

    def __init__(self):
        self._fallback: Dict[str, Any] = dict(_DEFAULTS)

    def _store(self) -> Dict[str, Any]:
        ss = _session_state()
        if ss is None:
            return self._fallback
        try:
            if _SESSION_KEY not in ss:
                ss[_SESSION_KEY] = dict(_DEFAULTS)
            return ss[_SESSION_KEY]
        except Exception:
            return self._fallback

    # dict interface
    def get(self, key, default=None):
        return self._store().get(key, default)

    def __getitem__(self, key):
        return self._store()[key]

    def __setitem__(self, key, value):
        self._store()[key] = value

    def __delitem__(self, key):
        del self._store()[key]

    def __contains__(self, key):
        return key in self._store()

    def __iter__(self) -> Iterator[str]:
        return iter(self._store())

    def __len__(self):
        return len(self._store())

    def keys(self):
        return self._store().keys()

    def values(self):
        return self._store().values()

    def items(self):
        return self._store().items()

    def update(self, *args, **kwargs):
        self._store().update(*args, **kwargs)

    def setdefault(self, key, default=None):
        return self._store().setdefault(key, default)

    def pop(self, key, *default):
        return self._store().pop(key, *default)

    def copy(self) -> Dict[str, Any]:
        return dict(self._store())

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._store())

    def replace(self, new_values: Dict[str, Any]):
        store = self._store()
        store.clear()
        store.update(new_values)

    def __repr__(self):
        return f"SETTINGS({self._store()!r})"


SETTINGS = _SettingsProxy()


def ensure_settings_loaded(force: bool = False) -> None:
    """Load the current user's saved preferences into SETTINGS once per session.

    Call after authentication (app.py). Cheap to call repeatedly — it only does
    work the first time per session, or when the logged-in user changes.
    """
    ss = _session_state()
    user_id = _current_user_id()
    if ss is not None and not force:
        try:
            if ss.get(_SESSION_LOADED_KEY) == user_id:
                return
        except Exception:
            pass
    merged = dict(_DEFAULTS)
    merged.update(_load_user_overrides(user_id))
    SETTINGS.replace(merged)
    if ss is not None:
        try:
            ss[_SESSION_LOADED_KEY] = user_id
        except Exception:
            pass


def enriched_cache_key(currency: str) -> str:
    """Return the session-state key for enriched portfolio data.

    Includes portfolio_id so switching portfolios doesn't serve stale data.
    Centralised here so the format is defined in exactly one place.
    """
    import streamlit as st
    pid = st.session_state.get("active_portfolio_id", 1)
    return f"enriched_{pid}_{currency}"
