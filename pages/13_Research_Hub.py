"""
Research Hub
============
One entry point for single-stock research — see the UI/UX audit finding
*"Five pages ask the same question about a stock"*. Peer Comparison,
Analyst Consensus, Sentiment, Technical Analysis and Equity Deep Dive
were five sibling pages with nothing telling a non-technical investor
which to open first or how they relate.

This page does no data fetching — it is pure orientation + navigation,
so it loads instantly.
"""

import streamlit as st

st.header("🔭 Research Hub")
st.caption(
    "Everything Prosper can tell you about a single stock, in the order "
    "that usually makes sense. Start at the top and drill down only where "
    "you need more."
)

# Optional: remember the last ticker the user was looking at, so the
# research pages can offer it as a default later. Purely a convenience —
# each page still has its own picker.
try:
    from core.database import get_all_holdings
    _holdings = get_all_holdings()
    _tickers = sorted(_holdings["ticker"].dropna().unique().tolist(), key=str.upper) if not _holdings.empty else []
except Exception:
    _tickers = []

if _tickers:
    _prev = st.session_state.get("research_ticker")
    _idx = _tickers.index(_prev) + 1 if _prev in _tickers else 0
    _pick = st.selectbox(
        "Stock you're researching",
        ["—"] + _tickers,
        index=_idx,
        help="Sets the default ticker where a research page supports it.",
    )
    st.session_state["research_ticker"] = None if _pick == "—" else _pick

st.divider()

_STEPS = [
    ("🔬", "Equity Deep Dive", "pages/18_Equity_Deep_Dive.py",
     "The 360° view — identity, price, chart, fundamentals, analyst, sentiment, "
     "ownership and a technical snapshot on one page. **Open this first.** "
     "Use the pages below only when you want more depth on one dimension."),
    ("🔍", "Peer Comparison", "pages/23_Peer_Comparison.py",
     "How the valuation and quality metrics stack up against comparable companies — "
     "is it cheap or expensive *relative to its peers*, not just in absolute terms."),
    ("🎯", "Analyst Consensus", "pages/7_Analyst_Consensus.py",
     "What professional analysts rate it, their price targets, and how those "
     "ratings have shifted over time."),
    ("💬", "Sentiment", "pages/8_Sentiment.py",
     "The tone of recent news and social chatter — a read on the current mood "
     "around the stock, not its fundamentals."),
    ("📉", "Technical Analysis", "pages/21_Technical_Analysis.py",
     "Price patterns, moving averages, MACD, RSI and Bollinger Bands — for timing "
     "an entry once you've decided you want to own it."),
]

for icon, title, path, desc in _STEPS:
    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown(f"### {icon} {title}")
            st.markdown(desc)
        with c2:
            st.page_link(path, label="Open", icon="↗️", use_container_width=True)

st.divider()
st.markdown("#### When you're ready to decide")
d1, d2 = st.columns(2)
with d1:
    st.page_link("pages/15_GROW_Analysis.py", label="🌱 GROW Engine — full durability + entry verdict",
                 use_container_width=True)
with d2:
    st.page_link("pages/24_AI_Chat.py", label="💬 Ask Prosper — ask a question in plain English",
                 use_container_width=True)
