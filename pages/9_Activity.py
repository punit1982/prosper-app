"""
Activity — what happened, and what is coming.

Replaces four top-level destinations: Portfolio News, Market News, Earnings
Calendar and Transactions. They were four answers to one question, and the
split was arbitrary enough that Portfolio News carried a caption telling the
user to go to Market News for fund coverage.

The slice is chosen with st.segmented_control, NOT st.tabs. Streamlit tabs are
eager — every hidden tab is built and shipped on every render — and one of
these slices fans out to a news API. A segmented control renders exactly the
one asked for, which is the same reason the Dashboard's region picker stopped
being a tab strip (P2-4).
"""

import streamlit as st

from core.ui_components import page_header
from core import activity_views as views

page_header("Activity", "News, earnings and the ledger")

_SLICES = {
    "Portfolio news": ("portfolio_news", "Headlines on the names you own"),
    "Market news":    ("market_news",    "The wider tape"),
    "Earnings":       ("earnings",       "What reports next, and what you hold into it"),
    "Transactions":   ("transactions",   "Every buy and sell, and what it actually earned"),
}

# Deep-linkable: another page can set activity_slice before switching here, so
# an earnings card on the Command Center can open the right slice rather than
# the default one.
_pending = st.session_state.pop("activity_slice", None)
if _pending in _SLICES:
    st.session_state["activity_pick"] = _pending

_pick = st.segmented_control(
    "Activity", list(_SLICES), key="activity_pick", label_visibility="collapsed",
) or "Portfolio news"

_fn, _sub = _SLICES[_pick]
st.caption(_sub)

getattr(views, _fn)()
