"""
Settings
========
User preferences for display, data refresh, columns, and API status.
All changes are saved persistently and survive app restarts.
"""

import os
import streamlit as st
from core.settings import SETTINGS, save_user_settings, get_defaults, load_user_settings

st.header("⚙️ Settings")

# Reload current saved settings (not the cached import-time snapshot)
current = load_user_settings()
defaults = get_defaults()

# ─────────────────────────────────────────
# DISPLAY SETTINGS
# ─────────────────────────────────────────
st.subheader("🖥️ Display")

currency_options = ["USD", "AED", "EUR", "GBP", "INR", "SGD", "HKD", "AUD", "CAD", "JPY", "CHF"]
current_base = current.get("base_currency", "USD")
base_idx = currency_options.index(current_base) if current_base in currency_options else 0

base_currency = st.selectbox(
    "Base Currency",
    currency_options,
    index=base_idx,
    help="All portfolio values will be converted and displayed in this currency.",
)

st.divider()

# ─────────────────────────────────────────
# DATA REFRESH
# ─────────────────────────────────────────
st.subheader("🔄 Data Refresh")

refresh_options = {
    "1 minute":   60,
    "2 minutes":  120,
    "5 minutes":  300,
    "10 minutes": 600,
    "15 minutes": 900,
}
current_ttl = current.get("price_cache_ttl_seconds", 300)
# Find closest match
ttl_labels = list(refresh_options.keys())
ttl_values = list(refresh_options.values())
ttl_idx = ttl_values.index(current_ttl) if current_ttl in ttl_values else 2  # default 5 min

price_refresh = st.selectbox(
    "Price Refresh Interval",
    ttl_labels,
    index=ttl_idx,
    help="How often to auto-refresh live stock prices. Lower = more API calls.",
)

col1, col2 = st.columns(2)
with col1:
    parse_cache = st.checkbox(
        "Enable Screenshot Parse Cache",
        value=current.get("parse_cache_enabled", True),
        help="Cache AI-parsed screenshots so the same image doesn't cost another API call.",
    )
with col2:
    fetch_metrics = st.checkbox(
        "Fetch Health Metrics (P/E, ROE, D/E)",
        value=current.get("fetch_key_metrics", True),
        help="Fetches fundamental metrics. Uses extra API calls per stock.",
    )

parse_ttl = st.slider(
    "Parse Cache Duration (days)",
    min_value=7, max_value=365, value=current.get("parse_cache_ttl_days", 90),
    help="How long to keep cached screenshot parse results before re-parsing.",
)

st.divider()

# ─────────────────────────────────────────
# COLUMN VISIBILITY
# ─────────────────────────────────────────
st.subheader("📊 Dashboard Column Visibility")
st.caption("Toggle which columns appear on the Portfolio Dashboard table.")

col_a, col_b, col_c = st.columns(3)

with col_a:
    st.markdown("**Core Columns**")
    col_name          = st.checkbox("Company Name",      value=current.get("col_name", True))
    col_qty           = st.checkbox("Quantity",           value=current.get("col_qty", True))
    col_avg_cost      = st.checkbox("Avg Buy Price",     value=current.get("col_avg_cost", True))
    col_current_price = st.checkbox("Current Price",     value=current.get("col_current_price", True))
    col_currency      = st.checkbox("Currency",          value=current.get("col_currency", True))

with col_b:
    st.markdown("**Performance**")
    col_day_gain      = st.checkbox("Today's P&L",       value=current.get("col_day_gain", True))
    col_day_gain_pct  = st.checkbox("Today's P&L %",     value=current.get("col_day_gain_pct", True))
    col_market_value  = st.checkbox("Market Value",      value=current.get("col_market_value", True))
    col_unrealized    = st.checkbox("Unrealized P&L",    value=current.get("col_unrealized_pnl", True))
    col_pnl_pct       = st.checkbox("Return %",          value=current.get("col_pnl_pct", True))

with col_c:
    st.markdown("**Fundamentals**")
    col_pe            = st.checkbox("P/E Ratio",         value=current.get("col_pe_ratio", True))
    col_roic          = st.checkbox("ROE / ROIC",        value=current.get("col_roic", False))
    col_de            = st.checkbox("Debt / Equity",     value=current.get("col_debt_equity", False))
    col_broker        = st.checkbox("Broker Source",     value=current.get("col_broker", False))

st.divider()

# ─────────────────────────────────────────
# API STATUS
# ─────────────────────────────────────────
st.subheader("🔑 API Status")
st.caption("Shows which API keys are configured in your .env file.")

apis = {
    "Anthropic (Claude AI)":    os.getenv("ANTHROPIC_API_KEY", ""),
    "Financial Modeling Prep":  os.getenv("FMP_API_KEY", ""),
    "Finnhub":                  os.getenv("FINNHUB_API_KEY", ""),
    "Twelve Data (UAE)":        os.getenv("TWELVE_DATA_API_KEY", ""),
}

for name, key in apis.items():
    placeholder = "your_" in key.lower() if key else True
    configured = bool(key) and not placeholder
    icon = "✅" if configured else "❌"
    st.markdown(f"{icon} **{name}** — {'Configured' if configured else 'Not configured'}")

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
        conn = _get_connection()
        conn.execute("DELETE FROM price_cache WHERE ticker NOT LIKE 'FX_%'")
        conn.commit()
        conn.close()
        # Clear session state price data
        for key in list(st.session_state.keys()):
            if key.startswith("enriched_") or key in ("last_refresh_time", "extended_df"):
                del st.session_state[key]
        st.success("Price cache cleared!")

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
# SAVE BUTTON
# ─────────────────────────────────────────
if st.button("💾 Save Settings", type="primary", use_container_width=True):
    updates = {
        "base_currency":           base_currency,
        "price_cache_ttl_seconds": refresh_options[price_refresh],
        "parse_cache_enabled":     parse_cache,
        "parse_cache_ttl_days":    parse_ttl,
        "fetch_key_metrics":       fetch_metrics,
        "col_name":                col_name,
        "col_qty":                 col_qty,
        "col_avg_cost":            col_avg_cost,
        "col_current_price":       col_current_price,
        "col_day_gain":            col_day_gain,
        "col_day_gain_pct":        col_day_gain_pct,
        "col_market_value":        col_market_value,
        "col_unrealized_pnl":      col_unrealized,
        "col_pnl_pct":             col_pnl_pct,
        "col_pe_ratio":            col_pe,
        "col_roic":                col_roic,
        "col_debt_equity":         col_de,
        "col_currency":            col_currency,
        "col_broker":              col_broker,
    }
    save_user_settings(updates)

    # Update the live SETTINGS dict so the app reflects changes immediately
    SETTINGS.update(updates)

    # Invalidate enriched cache if currency changed
    if base_currency != current.get("base_currency"):
        for key in list(st.session_state.keys()):
            if key.startswith("enriched_") or key in ("last_refresh_time", "extended_df"):
                del st.session_state[key]

    st.success("✅ Settings saved! Changes take effect immediately.")
    st.balloons()

st.divider()
st.caption("ℹ️ Settings are saved to `~/prosper_data/user_settings.json` and persist across restarts.")

# Reset to defaults button
if st.button("↩️ Reset to Defaults", type="secondary"):
    import os as _os
    settings_path = _os.path.expanduser("~/prosper_data/user_settings.json")
    if _os.path.exists(settings_path):
        _os.remove(settings_path)
    SETTINGS.update(get_defaults())
    st.success("Settings reset to defaults. Refresh the page to see changes.")
    st.rerun()
