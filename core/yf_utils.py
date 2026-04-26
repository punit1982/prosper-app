"""
yfinance Utilities — Single Source of Truth
=============================================
ALL yfinance data must pass through these functions to prevent:
  1. MultiIndex columns from yf.download() (Python 3.14+ / yfinance 0.2.54+)
  2. Duplicate column names
  3. Timezone-aware vs naive index mismatches
  4. 1-dimensional data requirements for optimization

This module is imported by data_engine.py, portfolio_optimizer.py,
and any page that touches yfinance directly.

Changes in v1.1:
  - safe_ticker_history() now falls back to Twelve Data when both yfinance
    approaches fail. This covers UAE stocks (.AE suffix) and any symbol
    that yfinance can't resolve. Falls back silently — callers see a clean
    DataFrame with no exception raised.
"""

import pandas as pd
from typing import Optional
import logging as _log

_yf_log = _log.getLogger("prosper.yf_utils")


def sanitize_history(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """
    Sanitize yfinance history DataFrame.

    Guarantees:
      - Flat (non-MultiIndex) columns
      - No duplicate column names
      - Timezone-naive DatetimeIndex
      - Empty DataFrame (not None) on failure

    Call this on EVERY yfinance history result before using it.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # 1. Flatten MultiIndex columns from yf.download()
    #    e.g. ("Close", "AAPL") → "Close"
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df = df.droplevel(level=1, axis=1)
        except Exception:
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

    # 2. Remove duplicate columns (can happen after flattening)
    df = df.loc[:, ~df.columns.duplicated()]

    # 3. Make index timezone-naive to prevent join errors
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    return df


def safe_download(
    tickers,
    period: str = "1y",
    auto_adjust: bool = True,
    progress: bool = False,
    **kwargs,
) -> pd.DataFrame:
    """
    Wrapper around yf.download() that always returns sanitized data.

    For a single ticker: returns flat DataFrame with columns like Close, Open, etc.
    For multiple tickers: returns sanitized DataFrame (caller must handle multi-ticker format).
    """
    import yfinance as yf

    try:
        data = yf.download(
            tickers,
            period=period,
            auto_adjust=auto_adjust,
            progress=progress,
            **kwargs,
        )
        return sanitize_history(data)
    except Exception:
        return pd.DataFrame()


def _twelve_data_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """
    Attempt to fetch OHLCV history from Twelve Data as a yfinance fallback.

    Maps yfinance period strings ("1y", "6mo", "3mo", "1mo") to Twelve Data
    outputsize parameter. Returns a sanitized DataFrame with Close column,
    or empty DataFrame if Twelve Data is not configured or the symbol fails.

    This is a last-resort fallback — it consumes API credits, so it is only
    called when both yfinance approaches have already failed.
    """
    try:
        from core.twelve_data_client import _api_key, _rate_limit, BASE_URL
        import requests

        key = _api_key()
        if not key:
            return pd.DataFrame()

        # Map period → approximate outputsize (number of daily bars)
        period_map = {
            "1d": 2, "5d": 5, "1mo": 30, "3mo": 90,
            "6mo": 180, "1y": 365, "2y": 730, "5y": 1825,
        }
        outputsize = period_map.get(period, 365)

        # Twelve Data expects symbols in "TICKER:EXCHANGE" format for UAE stocks.
        # For US stocks, plain ticker works fine.
        _rate_limit()
        resp = requests.get(
            f"{BASE_URL}/time_series",
            params={
                "symbol": ticker,
                "interval": "1day",
                "outputsize": outputsize,
                "apikey": key,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return pd.DataFrame()

        data = resp.json()
        if isinstance(data, dict) and data.get("code") in (400, 404, 429):
            return pd.DataFrame()

        values = data.get("values", [])
        if not values:
            return pd.DataFrame()

        rows = []
        for v in values:
            try:
                rows.append({
                    "Date": pd.to_datetime(v["datetime"]),
                    "Open": float(v.get("open", 0)),
                    "High": float(v.get("high", 0)),
                    "Low": float(v.get("low", 0)),
                    "Close": float(v.get("close", 0)),
                    "Volume": float(v.get("volume", 0)),
                })
            except (KeyError, ValueError, TypeError):
                continue

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).set_index("Date").sort_index()
        _yf_log.debug("Twelve Data fallback: %s rows for %s", len(df), ticker)
        return df

    except Exception as e:
        _yf_log.debug("Twelve Data fallback failed for %s: %s", ticker, e)
        return pd.DataFrame()


def safe_ticker_history(
    ticker: str,
    period: str = "1y",
    auto_adjust: bool = True,
) -> pd.DataFrame:
    """
    Fetch history for a single ticker with automatic fallback chain.

    Fallback order:
      1. yf.download() — preferred, handles Python 3.14 MultiIndex correctly
      2. Ticker.history() — legacy yfinance path
      3. Twelve Data time_series — for UAE stocks and any symbol yfinance can't resolve

    Always returns sanitized DataFrame. Never raises.
    """
    import yfinance as yf

    # Approach 1: yf.download (preferred)
    try:
        data = yf.download(ticker, period=period, auto_adjust=auto_adjust, progress=False)
        result = sanitize_history(data)
        if not result.empty:
            return result
    except Exception:
        pass

    # Approach 2: Ticker.history (legacy fallback)
    try:
        hist = yf.Ticker(ticker).history(period=period, auto_adjust=auto_adjust)
        result = sanitize_history(hist)
        if not result.empty:
            return result
    except Exception:
        pass

    # Approach 3: Twelve Data fallback (UAE stocks + any symbol yfinance can't cover)
    _yf_log.debug("yfinance failed for %s — trying Twelve Data fallback", ticker)
    return _twelve_data_history(ticker, period=period)


def extract_close_series(df: pd.DataFrame, ticker: str = "") -> pd.Series:
    """
    Extract a clean Close price Series from a history DataFrame.

    Handles:
      - DataFrame with "Close" column → Series
      - DataFrame where Close is itself a DataFrame (multi-ticker remnant) → first column
      - Already a Series → return as-is

    Returns an empty Series on failure.
    """
    if df is None or df.empty:
        return pd.Series(dtype=float, name=ticker or "Close")

    if isinstance(df, pd.Series):
        return df

    if "Close" not in df.columns:
        if len(df.columns) == 1:
            return df.iloc[:, 0].rename(ticker or "Close")
        return pd.Series(dtype=float, name=ticker or "Close")

    close = df["Close"]

    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    return close.rename(ticker or "Close")


def clean_nan(value, default=None):
    """
    Convert NaN/None/inf to a default value.
    Works with pandas 2.x+ (no deprecated is_extension_array_dtype).
    """
    if value is None:
        return default
    try:
        import math
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return default
    except (TypeError, ValueError):
        pass
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return value
