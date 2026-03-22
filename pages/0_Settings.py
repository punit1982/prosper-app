"""
Settings & Configuration
========================
Consolidated settings page — all preferences in one place.
Sections: Display, Data, Dashboard, API Keys, Data Management, About.
"""

import os
import streamlit as st
from core.settings import SETTINGS, save_user_settings, get_defaults, load_user_settings

st.header("⚙️ Settings & Configuration")

# Reload current saved settings (not the cached import-time snapshot)
current = load_user_settings()
defaults = get_defaults()

# ─────────────────────────────────────────
# DISPLAY SETTINGS
# ─────────────────────────────────────────
st.subheader("🖥️ Display & Appearance")

col_disp1, col_disp2 = st.columns(2)

with col_disp1:
    currency_options = ["USD", "AED", "EUR", "GBP", "INR", "SGD", "HKD", "AUD", "CAD", "JPY", "CHF",
                        "SAR", "KWD", "QAR", "BHD", "OMR", "ZAR", "MYR", "KRW", "BRL"]
    current_base = current.get("base_currency", "USD")
    base_idx = currency_options.index(current_base) if current_base in currency_options else 0
    base_currency = st.selectbox(
        "Base Currency",
        currency_options,
        index=base_idx,
        help="All portfolio values will be converted and displayed in this currency.",
    )

with col_disp2:
    number_format = st.selectbox(
        "Number Format",
        ["Compact (1.2M, 45K)", "Full (1,200,000)"],
        index=0 if current.get("number_format", "compact") == "compact" else 1,
        help="How large numbers are displayed across the app.",
    )

st.divider()

# ─────────────────────────────────────────
# DATA REFRESH
# ─────────────────────────────────────────
st.subheader("🔄 Data Refresh")

col_r1, col_r2 = st.columns(2)

with col_r1:
    refresh_options = {
        "1 minute":   60,
        "2 minutes":  120,
        "5 minutes":  300,
        "10 minutes": 600,
        "15 minutes": 900,
    }
    current_ttl = current.get("price_cache_ttl_seconds", 300)
    ttl_labels = list(refresh_options.keys())
    ttl_values = list(refresh_options.values())
    ttl_idx = ttl_values.index(current_ttl) if current_ttl in ttl_values else 2
    price_refresh = st.selectbox(
        "Price Refresh Interval",
        ttl_labels,
        index=ttl_idx,
        help="How often to auto-refresh live stock prices.",
    )

with col_r2:
    parse_ttl = st.slider(
        "Parse Cache Duration (days)",
        min_value=7, max_value=365, value=current.get("parse_cache_ttl_days", 90),
        help="How long to keep cached screenshot parse results.",
    )

col_c1, col_c2 = st.columns(2)
with col_c1:
    parse_cache = st.checkbox(
        "Enable Screenshot Parse Cache",
        value=current.get("parse_cache_enabled", True),
        help="Cache AI-parsed screenshots so the same image doesn't cost another API call.",
    )
with col_c2:
    fetch_metrics = st.checkbox(
        "Auto-Fetch Health Metrics (P/E, ROE, D/E)",
        value=current.get("fetch_key_metrics", True),
        help="Automatically fetch fundamental metrics.",
    )

st.divider()

# ─────────────────────────────────────────
# DASHBOARD PREFERENCES (consolidated from sidebar)
# ─────────────────────────────────────────
st.subheader("📊 Dashboard Preferences")
st.caption("Toggle which columns and features appear on the Portfolio Dashboard.")

col_d1, col_d2, col_d3 = st.columns(3)

with col_d1:
    st.markdown("**Table Columns**")
    show_day_gain   = st.checkbox("Day Gain / Loss",  value=current.get("pref_dash_show_day_gain", True), key="s_day_gain")
    show_unrealized = st.checkbox("Unrealized P&L",   value=current.get("pref_dash_show_unrealized", True), key="s_unrealized")
    show_extended   = st.checkbox("Extended Metrics (52W, PE, Target)", value=current.get("pref_dash_show_extended", False), key="s_extended")
    show_growth     = st.checkbox("Growth & Financials", value=current.get("pref_dash_show_growth", False), key="s_growth")

with col_d2:
    st.markdown("**Additional Columns**")
    show_broker     = st.checkbox("Broker Source", value=current.get("pref_dash_show_broker", False), key="s_broker")
    show_prosper    = st.checkbox("Prosper AI Score", value=current.get("pref_dash_show_prosper", False), key="s_prosper")
    auto_ext = st.checkbox("Auto-load Extended Metrics", value=current.get("pref_dash_auto_extended", False),
                            help="Automatically fetch extended data when prices load", key="s_auto_ext")

with col_d3:
    st.markdown("**News & Sentiment**")
    auto_mkt_summary = st.checkbox("Auto AI Summaries (Market News)",
                                    value=current.get("pref_mkt_auto_summary", False), key="s_mkt_summary")
    auto_port_summary = st.checkbox("Auto AI Summaries (Portfolio News)",
                                     value=current.get("pref_port_auto_summary", False), key="s_port_summary")

st.divider()

# ─────────────────────────────────────────
# API STATUS
# ─────────────────────────────────────────
st.subheader("🔑 API Keys & Integrations")
st.caption("Shows which API keys are configured (via .env or Streamlit secrets). Keys are never displayed for security.")

from core.settings import get_api_key

required_apis = {
    "Anthropic (Claude AI — required)":     get_api_key("ANTHROPIC_API_KEY"),
}
optional_apis = {
    "Finnhub (quotes, analyst data)":       get_api_key("FINNHUB_API_KEY"),
    "Twelve Data (UAE/DFM quotes)":         get_api_key("TWELVE_DATA_API_KEY"),
    "Serper / Google Search (news + analysis)": get_api_key("SERPER_API_KEY"),
    "Financial Modeling Prep":              get_api_key("FMP_API_KEY"),
    "IBKR Flex Token (broker sync)":        get_api_key("IBKR_FLEX_TOKEN"),
}

st.markdown("**Required:**")
for name, key in required_apis.items():
    placeholder = "your_" in key.lower() if key else True
    configured = bool(key) and not placeholder
    icon = "✅" if configured else "❌"
    status = "Configured" if configured else "Not configured"
    st.markdown(f"{icon} **{name}** — {status}")

st.markdown("**Optional (enhance features):**")
for name, key in optional_apis.items():
    placeholder = "your_" in key.lower() if key else True
    configured = bool(key) and not placeholder
    icon = "✅" if configured else "⚪"
    status = "Configured" if configured else "Not set (optional)"
    st.markdown(f"{icon} **{name}** — {status}")

with st.expander("💡 How to add API keys on Streamlit Cloud"):
    st.markdown("""
**On Streamlit Cloud** → go to your app → ⋮ menu → **Settings** → **Secrets** and paste:
```toml
ANTHROPIC_API_KEY = "sk-ant-..."
FMP_API_KEY = "..."
FINNHUB_API_KEY = "..."
SERPER_API_KEY = "..."
TWELVE_DATA_API_KEY = "..."
PROSPER_AUTH_ENABLED = "true"
```
Each line must be in `KEY = "value"` format (with quotes around the value).

**Locally**: add keys to your `.env` file and restart the app:
- **Finnhub**: Free at [finnhub.io](https://finnhub.io/) — improves analyst data & company news
- **Twelve Data**: Free at [twelvedata.com](https://twelvedata.com/) — UAE/DFM stock quotes
- **Serper**: Free (2.5K/month) at [serper.dev](https://serper.dev/) — Google-powered news + analysis context for Prosper AI
- **FMP**: Free at [financialmodelingprep.com](https://financialmodelingprep.com/) — additional financial data
    """)

st.divider()

# ─────────────────────────────────────────
# DATA MANAGEMENT
# ─────────────────────────────────────────
st.subheader("🗄️ Data Management")

col_m1, col_m2, col_m3 = st.columns(3)

with col_m1:
    if st.button("🗑️ Clear Price Cache", use_container_width=True,
                  help="Forces re-fetching all prices on next load."):
        from core.database import _get_connection
        from core.cio_engine import clear_failed_tickers
        clear_failed_tickers()
        conn = _get_connection()
        conn.execute("DELETE FROM price_cache WHERE ticker NOT LIKE 'FX_%'")
        conn.execute("DELETE FROM ticker_cache")  # Also clear resolution cache
        conn.commit()
        conn.close()
        for key in list(st.session_state.keys()):
            if key.startswith("enriched_") or key.startswith("_de_resolved_") or key in ("last_refresh_time", "extended_df", "summary_info_map"):
                del st.session_state[key]
        st.success("Price + ticker resolution cache cleared!")

with col_m2:
    if st.button("🗑️ Clear Parse Cache", use_container_width=True,
                  help="Forces re-parsing all screenshots on next upload."):
        from core.database import clear_parse_cache
        clear_parse_cache()
        st.success("Parse cache cleared!")

with col_m3:
    if st.button("🗑️ Clear News Cache", use_container_width=True,
                  help="Forces re-fetching news articles."):
        from core.database import _get_connection
        conn = _get_connection()
        conn.execute("DELETE FROM news_cache")
        conn.commit()
        conn.close()
        st.success("News cache cleared!")

st.divider()

# ─────────────────────────────────────────
# ABOUT
# ─────────────────────────────────────────
st.subheader("ℹ️ About Prosper")

# Show database backend info (session-cached to avoid slow HTTP pings on every load)
try:
    if "_db_info_cache" not in st.session_state:
        from core.db_connector import get_db_info
        st.session_state["_db_info_cache"] = get_db_info()
    db_info = st.session_state["_db_info_cache"]
    db_icon = "☁️" if db_info["persistent"] else "💾"
    db_label = db_info["backend"]
    db_persistent = "✅ Persistent (survives reboots)" if db_info["persistent"] else "⚠️ Local only (lost on Streamlit Cloud reboot)"
except Exception:
    db_info = {}
    db_label = "SQLite (Local)"
    db_icon = "💾"
    db_persistent = "⚠️ Local only"

st.markdown(f"""
**Prosper** is an AI-native investment operating system for high-net-worth individuals
and institutional portfolio management.

- **Version:** 5.1 (Command Center + Optimizer + Turso)
- **Stack:** Python + Streamlit + Claude AI
- **Database:** {db_icon} {db_label} — {db_persistent}
- **Data:** yfinance, Finnhub, Twelve Data, RSS feeds (CNBC, Reuters, MarketWatch, Motley Fool)
""")

# Show Turso diagnostic details
try:
    if db_info.get("persistent"):
        with st.expander("☁️ Turso Connection Details"):
            if db_info.get("connected"):
                st.success(f"✅ Connected — {db_info.get('status', 'OK')}")
            else:
                st.error(f"❌ Not connected — {db_info.get('status', 'Error')}")
                if db_info.get("error"):
                    st.code(db_info["error"])
            st.caption(f"**URL:** `{db_info.get('url', '?')}`")
            st.caption(f"**Pipeline:** `{db_info.get('pipeline_url', '?')}`")
            st.caption(f"**Token:** `{db_info.get('token_preview', '?')}`")
    elif not db_info.get("persistent"):
        # Show why Turso isn't active
        if db_info.get("turso_url_found") or db_info.get("turso_token_found"):
            st.warning(
                f"Turso secrets partially configured: "
                f"URL={'✅' if db_info.get('turso_url_found') else '❌'} "
                f"Token={'✅' if db_info.get('turso_token_found') else '❌'}"
            )
except Exception:
    pass

# Turso setup instructions
if not db_info.get("persistent", False):
    with st.expander("☁️ Enable Cloud Database (Turso) — recommended for Streamlit Cloud"):
        st.markdown("""
**To make your data persistent (survive reboots):**

1. Go to [turso.tech](https://turso.tech) and create a free account
2. Create a database: `turso db create prosper`
3. Get your database URL: `turso db show prosper --url`
4. Create an auth token: `turso db tokens create prosper`
5. Add these to your Streamlit Cloud secrets (Settings → Secrets):

```toml
TURSO_DATABASE_URL = "libsql://prosper-yourname.turso.io"
TURSO_AUTH_TOKEN = "your-auth-token-here"
```

6. Redeploy — Prosper will automatically use Turso for all data storage.

**Free tier:** 9GB storage, 500M row reads/month, 25M row writes/month.
""")

st.divider()

# ─────────────────────────────────────────
# SAVE BUTTON
# ─────────────────────────────────────────
if st.button("💾 Save Settings", type="primary", use_container_width=True):
    updates = {
        "base_currency":           base_currency,
        "number_format":           "compact" if "Compact" in number_format else "full",
        "price_cache_ttl_seconds": refresh_options[price_refresh],
        "parse_cache_enabled":     parse_cache,
        "parse_cache_ttl_days":    parse_ttl,
        "fetch_key_metrics":       fetch_metrics,
        "pref_dash_show_day_gain":    show_day_gain,
        "pref_dash_show_unrealized":  show_unrealized,
        "pref_dash_show_extended":    show_extended,
        "pref_dash_show_growth":      show_growth,
        "pref_dash_show_broker":      show_broker,
        "pref_dash_show_prosper":     show_prosper,
        "pref_dash_auto_extended":    auto_ext,
        "pref_mkt_auto_summary":      auto_mkt_summary,
        "pref_port_auto_summary":     auto_port_summary,
    }
    save_user_settings(updates)
    SETTINGS.update(updates)

    # Invalidate enriched cache if currency changed
    if base_currency != current.get("base_currency"):
        for key in list(st.session_state.keys()):
            if key.startswith("enriched_") or key in ("last_refresh_time", "extended_df"):
                del st.session_state[key]

    st.success("✅ Settings saved! Changes take effect immediately.")
    st.balloons()

# Reset to defaults button
if st.button("↩️ Reset to Defaults", type="secondary"):
    import os as _os
    settings_path = _os.path.expanduser("~/prosper_data/user_settings.json")
    if _os.path.exists(settings_path):
        _os.remove(settings_path)
    SETTINGS.update(get_defaults())
    st.success("Settings reset to defaults. Refresh the page to see changes.")
    st.rerun()

st.caption("ℹ️ Settings are saved to `~/prosper_data/user_settings.json` and persist across restarts.")
