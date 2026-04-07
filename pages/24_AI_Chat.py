"""
AI Chat — Ask Prosper
=====================
Query your portfolio, holdings, and market data using natural language.
"""

import streamlit as st
import pandas as pd
from core.database import get_all_holdings, get_all_prosper_analyses
from core.settings import SETTINGS, get_api_key, enriched_cache_key

st.header("Ask Prosper")
st.caption("Chat with your portfolio — ask about holdings, performance, allocations, or any stock.")

# ── Check API key ──
api_key = get_api_key("ANTHROPIC_API_KEY")
if not api_key or api_key == "your_anthropic_api_key_here":
    st.warning("Set your **ANTHROPIC_API_KEY** in Settings or .env to use AI Chat.")
    st.stop()

# ── Build portfolio context ──
base_currency = SETTINGS.get("base_currency", "USD")
enriched = st.session_state.get(enriched_cache_key(base_currency))
holdings = get_all_holdings()

_portfolio_summary = "No portfolio data loaded yet. Visit the Dashboard first to load live prices."
if enriched is not None and not enriched.empty:
    total_mv = pd.to_numeric(enriched.get("market_value"), errors="coerce").sum()
    total_pnl = pd.to_numeric(enriched.get("unrealized_pnl"), errors="coerce").sum()
    total_cost = pd.to_numeric(enriched.get("cost_basis"), errors="coerce").sum()
    pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    # Top holdings
    _top = enriched.nlargest(10, "market_value")[["ticker", "name", "market_value", "unrealized_pnl_pct"]].copy()
    _top["weight"] = (_top["market_value"] / total_mv * 100).round(1)
    _top_str = _top.to_string(index=False)

    _portfolio_summary = (
        f"Portfolio: {len(enriched)} holdings, Total Value: {base_currency} {total_mv:,.0f}, "
        f"Total Cost: {base_currency} {total_cost:,.0f}, Unrealized P&L: {base_currency} {total_pnl:,.0f} ({pnl_pct:+.1f}%)\n\n"
        f"Top 10 holdings:\n{_top_str}"
    )

    # Add sector breakdown if available
    _t_col = "ticker_resolved" if "ticker_resolved" in enriched.columns else "ticker"
    if "sector" in enriched.columns:
        _sectors = enriched.groupby("sector")["market_value"].sum().sort_values(ascending=False)
        _sec_str = "\n".join(f"  {s}: {v/total_mv*100:.1f}%" for s, v in _sectors.head(8).items())
        _portfolio_summary += f"\n\nSector allocation:\n{_sec_str}"

# Add Prosper analyses if available
_analyses = get_all_prosper_analyses()
_analysis_context = ""
if not _analyses.empty:
    _an = _analyses[["ticker", "rating", "score", "archetype_name", "thesis"]].head(20)
    _analysis_context = f"\n\nProsper AI analyses (recent):\n{_an.to_string(index=False)}"


# ── System prompt ──
SYSTEM_PROMPT = f"""You are Prosper AI, an investment assistant embedded in the Prosper portfolio management app.
You help users understand their portfolio, make informed investment decisions, and answer questions about stocks.

Current portfolio data:
{_portfolio_summary}
{_analysis_context}

Guidelines:
- Be concise and direct. Use bullet points for lists.
- When discussing specific holdings, reference the portfolio data above.
- For questions about stocks not in the portfolio, provide general knowledge.
- Never give specific buy/sell advice — frame as analysis, not recommendations.
- If asked about data you don't have, suggest which Prosper page to visit.
- Use {base_currency} as the default currency.
"""

# ── Chat history ──
_CHAT_MAX_MSGS = 40  # Keep last 40 messages (20 exchanges) to prevent memory bloat
if "chat_messages" not in st.session_state:
    st.session_state["chat_messages"] = []
elif len(st.session_state["chat_messages"]) > _CHAT_MAX_MSGS:
    st.session_state["chat_messages"] = st.session_state["chat_messages"][-_CHAT_MAX_MSGS:]

# Create separate container for chat to prevent sidebar click hijacking
chat_container = st.container()

with chat_container:
    # Display chat history
    for msg in st.session_state["chat_messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# Chat input (outside container to allow sidebar navigation)
if prompt := st.chat_input("Ask about your portfolio, a stock, or market conditions..."):
    # Add user message
    st.session_state["chat_messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                import anthropic
                from core.settings import call_claude

                client = anthropic.Anthropic(api_key=api_key)

                # Build messages for API
                _api_messages = []
                for m in st.session_state["chat_messages"]:
                    _api_messages.append({"role": m["role"], "content": m["content"]})

                response = call_claude(
                    client,
                    system=SYSTEM_PROMPT,
                    messages=_api_messages,
                    max_tokens=1000,
                    preferred_model="claude-sonnet-4-20250514",
                )
                reply = response.content[0].text
                st.markdown(reply)
                st.session_state["chat_messages"].append({"role": "assistant", "content": reply})
            except Exception as e:
                st.error(f"Chat error: {e}")

# Clear chat button
if st.session_state.get("chat_messages"):
    if st.button("Clear Chat", key="_clear_chat"):
        st.session_state["chat_messages"] = []
        st.rerun()
