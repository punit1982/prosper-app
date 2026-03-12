"""
Home page — shown when the user lands on the app.
Navigation label: "Home"  (set via st.navigation in app.py)
"""

import streamlit as st
import os

# ── API Key Status ──────────────────────────────────────────────────
anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

if not anthropic_key or anthropic_key == "your_anthropic_api_key_here":
    st.warning(
        "**Anthropic API key not configured.** "
        "Add your key to the `.env` file to enable screenshot parsing.  \n"
        "Get your key at: https://console.anthropic.com/"
    )

# ── Welcome ─────────────────────────────────────────────────────────
st.title("Welcome to Prosper 📈")
st.markdown("**Your AI-native investment operating system.**")

st.markdown(
    """
Use the sidebar to navigate:

- **Upload Portal** — Drop in a brokerage screenshot and Claude will extract your holdings automatically.
- **Portfolio Dashboard** — See your full portfolio with live prices, P&L, and health metrics.
"""
)

st.divider()

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("### 📸 Upload")
    st.caption(
        "Supports screenshots from IBKR, Zerodha, HSBC, Tiger Brokers, and more. "
        "Claude reads the image and extracts Ticker, Quantity, and Average Cost."
    )
with col2:
    st.markdown("### 🔍 Review")
    st.caption(
        "Before saving, you get an editable table to review and correct the AI-extracted data. "
        "No bad data ever slips through without your sign-off."
    )
with col3:
    st.markdown("### 📊 Analyse")
    st.caption(
        "The Portfolio Dashboard shows live prices, today's gain/loss, unrealized P&L, "
        "and health metrics (P/E, ROIC, Debt/Equity) — all in your chosen base currency."
    )
