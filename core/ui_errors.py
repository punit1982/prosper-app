"""
Canonical error / empty-state copy
==================================
One voice for every "this didn't work" or "there's nothing here yet"
moment in the app. See the UI/UX audit finding *"Error and empty-state
copy has no single voice"* — some failures spoke plainly, others dumped
the raw Python exception at a non-technical investor.

Four templates, picked by *what the user should do next*:

  1. empty_state()   — nothing to show yet; the user has an action to take
  2. fetch_failed()  — a live data source didn't answer; retrying may help
  3. fetch_pending() — a live data source is flaky; it usually self-heals,
                       so just wait rather than hammering retry
  4. unsupported()   — permanently not available for this holding / market
                       / plan tier; retrying will never help

The real exception is always sent to the logger (label
``prosper.ui``); it is never rendered. For code paths that must *return*
a string rather than draw a widget, use ``safe_message()``.
"""
from __future__ import annotations

import logging
from typing import Optional

import streamlit as st

_log = logging.getLogger("prosper.ui")


def empty_state(what: str, *, action: str = "Upload your portfolio to get started.") -> None:
    """Nothing to display yet — and the user is the one who unblocks it.

    ``what`` is a short noun phrase ("holdings", "dividend history").
    ``action`` is the single next step, phrased as an instruction.
    """
    st.info(f"No {what} yet. {action}")


def fetch_failed(what: str, exc: Optional[BaseException] = None) -> None:
    """A live fetch failed in a way a retry might fix (timeout, transient
    5xx, rate-limit). Logs the real cause, shows a calm retry prompt."""
    if exc is not None:
        _log.warning("fetch failed: %s", what, exc_info=exc)
    st.warning(
        f"Couldn't load {what} right now — the data source didn't respond. "
        "Try again in a moment."
    )


def fetch_pending(what: str, exc: Optional[BaseException] = None) -> None:
    """A live source is intermittently down but tends to recover on its
    own. Tell the user to wait rather than retry in a loop."""
    if exc is not None:
        _log.warning("fetch pending (source flaky): %s", what, exc_info=exc)
    st.info(
        f"{what.capitalize()} is temporarily unavailable from the data provider. "
        "This usually clears within a few minutes — check back shortly."
    )


def unsupported(what: str, *, reason: str = "") -> None:
    """This will never work for the current holding / market / plan — say
    so plainly instead of showing an error every time."""
    tail = f" {reason}" if reason else ""
    st.info(f"{what.capitalize()} isn't available here.{tail}")


def unexpected(what: str, exc: BaseException) -> None:
    """Catch-all for a genuine bug in our own code (not a data-source
    problem). Logs the full traceback, shows one reassuring line."""
    _log.exception("unexpected error while loading %s", what, exc_info=exc)
    st.error(
        f"Something went wrong while loading {what}. It's been logged. "
        "Try again, and if it keeps happening let support know."
    )


def safe_message(what: str, exc: Optional[BaseException] = None) -> str:
    """Return-a-string variant, for functions that hand back copy instead
    of drawing a widget (AI briefings, one-line summaries). Logs the real
    exception, returns a fixed, user-safe sentence."""
    if exc is not None:
        _log.warning("could not produce %s", what, exc_info=exc)
    return (
        f"{what.capitalize()} is unavailable right now — the data source or model "
        "didn't respond. Try again in a moment."
    )
