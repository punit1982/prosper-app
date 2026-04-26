"""
yfinance Resilience Layer — Prosper
====================================
Wraps yfinance calls with:
  1. Retry logic (tenacity) — 3 attempts with exponential backoff
  2. Circuit-breaker pattern — after 5 consecutive failures, skips
     yfinance for 5 minutes and falls back to cached last-known value
  3. Multi-source fallback cascade:
       yfinance → Twelve Data → Finnhub → cached last-known value → None

This prevents the entire app from hanging or showing errors when
yfinance has an outage (which happens ~monthly).

Usage:
    from core.yf_resilience import safe_get_price, safe_get_history

    price = safe_get_price("AAPL")          # float or None
    hist  = safe_get_history("AAPL", "1y")  # pd.DataFrame or empty DataFrame
"""

import time
import logging
import pandas as pd
import streamlit as st
from typing import Optional

_log = logging.getLogger("prosper.yf_resilience")

# ── Circuit-breaker state (in-memory, per Render worker) ─────────────────
_CB_FAILURE_THRESHOLD = 5       # failures before opening the circuit
_CB_RECOVERY_SECONDS  = 300     # 5 minutes before retrying

_cb_state = {
    "failures": 0,
    "open_since": None,   # timestamp when circuit opened
    "last_error": None,
}


def _circuit_open() -> bool:
    """Returns True if the circuit breaker is open (yfinance should be skipped)."""
    if _cb_state["open_since"] is None:
        return False
    elapsed = time.time() - _cb_state["open_since"]
    if elapsed > _CB_RECOVERY_SECONDS:
        # Half-open: allow one probe request
        _log.info("yfinance circuit breaker: half-open probe after %.0fs", elapsed)
        return False
    return True


def _record_success():
    _cb_state["failures"] = 0
    _cb_state["open_since"] = None
    _cb_state["last_error"] = None


def _record_failure(err):
    _cb_state["failures"] += 1
    _cb_state["last_error"] = str(err)[:200]
    if _cb_state["failures"] >= _CB_FAILURE_THRESHOLD:
        if _cb_state["open_since"] is None:
            _cb_state["open_since"] = time.time()
            _log.warning(
                "yfinance circuit breaker OPENED after %d failures. Last error: %s",
                _cb_state["failures"], _cb_state["last_error"]
            )


# ── Cached last-known prices (survives within Render worker lifetime) ─────
_last_known: dict = {}


def _cache_last_known(ticker: str, price: float):
    if price and price > 0:
        _last_known[ticker] = {"price": price, "ts": time.time()}


def _get_last_known(ticker: str) -> Optional[float]:
    entry = _last_known.get(ticker)
    if entry and (time.time() - entry["ts"]) < 3600:  # stale after 1h
        return entry["price"]
    return None


# ── Retry decorator (tenacity) ────────────────────────────────────────────
def _make_retry():
    try:
        from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
        return retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )
    except ImportError:
        # tenacity not installed — return identity decorator
        def _noop(fn):
            return fn
        return _noop


# ── Core price fetch ──────────────────────────────────────────────────────
def safe_get_price(ticker: str, currency: str = "USD") -> Optional[float]:
    """
    Get current price for ticker with full resilience.

    Cascade:
      1. yfinance fast_info.last_price  (3 retries, circuit-breaker)
      2. Twelve Data (UAE/non-US tickers)
      3. Finnhub quote
      4. Last-known cached price (< 1h old)
      5. None
    """
    # ── 1. yfinance ───────────────────────────────────────────────────────
    if not _circuit_open():
        try:
            retry_deco = _make_retry()

            @retry_deco
            def _yf_price():
                import yfinance as yf
                p = yf.Ticker(ticker).fast_info.last_price
                if p is None:
                    raise ValueError(f"yfinance returned None price for {ticker}")
                return float(p)

            price = _yf_price()
            _record_success()
            _cache_last_known(ticker, price)
            return price
        except Exception as e:
            _record_failure(e)
            _log.warning("yfinance price failed for %s: %s", ticker, e)

    # ── 2. Twelve Data (good for UAE / non-US tickers) ────────────────────
    try:
        from core.twelve_data_client import get_price as td_price, is_configured as td_ok
        if td_ok():
            p = td_price(ticker)
            if p and p > 0:
                _cache_last_known(ticker, p)
                return float(p)
    except Exception as e:
        _log.debug("Twelve Data price failed for %s: %s", ticker, e)

    # ── 3. Finnhub ────────────────────────────────────────────────────────
    try:
        from core.finnhub_client import quote as fh_quote, is_configured as fh_ok
        if fh_ok():
            q = fh_quote(ticker)
            if q and q.get("c", 0) > 0:
                p = float(q["c"])
                _cache_last_known(ticker, p)
                return p
    except Exception as e:
        _log.debug("Finnhub price failed for %s: %s", ticker, e)

    # ── 4. Last-known cached price ────────────────────────────────────────
    last = _get_last_known(ticker)
    if last:
        _log.info("Using last-known cached price for %s: %.4f", ticker, last)
        return last

    return None


# ── History fetch ─────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False, max_entries=200)
def safe_get_history(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Get OHLCV history with retries and graceful empty-DataFrame fallback.
    Cached 1h via @st.cache_data (survives page switches).

    Returns pd.DataFrame (may be empty if all sources fail).
    """
    if not _circuit_open():
        try:
            retry_deco = _make_retry()

            @retry_deco
            def _yf_hist():
                import yfinance as yf
                df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
                if df is None or df.empty:
                    raise ValueError(f"yfinance returned empty history for {ticker}")
                return df

            df = _yf_hist()
            _record_success()
            return df
        except Exception as e:
            _record_failure(e)
            _log.warning("yfinance history failed for %s (%s/%s): %s", ticker, period, interval, e)

    # Graceful fallback — return empty DataFrame with expected columns
    _log.warning("Returning empty history DataFrame for %s (all sources failed)", ticker)
    return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])


def get_circuit_status() -> dict:
    """Return circuit-breaker status for health/debug display."""
    open_for = None
    if _cb_state["open_since"]:
        open_for = round(time.time() - _cb_state["open_since"])
    return {
        "open": _circuit_open(),
        "failures": _cb_state["failures"],
        "open_for_seconds": open_for,
        "last_error": _cb_state["last_error"],
        "threshold": _CB_FAILURE_THRESHOLD,
        "recovery_seconds": _CB_RECOVERY_SECONDS,
    }
