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
"""

import pandas as pd
from typing import Optional


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
        # Try dropping the ticker level (level=1)
        try:
            df = df.droplevel(level=1, axis=1)
        except Exception:
            # If that fails, just take the first level
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


def safe_ticker_history(
    ticker: str,
    period: str = "1y",
    auto_adjust: bool = True,
) -> pd.DataFrame:
    """
    Fetch history for a single ticker with automatic fallback.

    Tries yf.download() first (more reliable), falls back to Ticker.history().
    Always returns sanitized DataFrame.
    """
    import yfinance as yf

    # Approach 1: yf.download (preferred — handles Python 3.14 better)
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

    return pd.DataFrame()


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
        # Maybe the DataFrame only has one column
        if len(df.columns) == 1:
            return df.iloc[:, 0].rename(ticker or "Close")
        return pd.Series(dtype=float, name=ticker or "Close")

    close = df["Close"]

    # Guard: if Close is a DataFrame (multi-ticker remnant), take first column
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
