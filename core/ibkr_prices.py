"""
IBKR daily price backfill
=========================
Some holdings have no free live quote and never will:

  · UAE (ADX/DFM) — Mubasher is the only free source and it sits behind
    Cloudflare, which 403s datacenter IPs, so the scrape works from a laptop
    and fails from Render (see HANDOFF v7.15).
  · European and offshore FUNDS — yfinance has no coverage, Twelve Data gates
    them behind a paid plan, Finnhub does not carry them.
  · Thinly-traded or suspended lines.

IBKR already knows what all of these are worth: every Flex Query position
carries a `markPrice`. This module pulls that once a day and writes it into
the same `price_cache` the rest of the app reads, so those holdings show a
real value instead of a dash.

**This uses the Flex Query WEB SERVICE (token + query id), not the IBKR MCP
connector.** The MCP connector authenticates as the user's own Claude
connector and cannot be called by the deployed app — only a Flex token can,
which is why the refresh is built on that.

Prices from here are marked `source="ibkr"` and are a *broker mark*, not a
live quote: they are the previous close for most markets. They are only used
where nothing better exists.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Dict, List, Optional

logger = logging.getLogger("prosper.ibkr_prices")

_STATE_KEY = "ibkr_price_refresh_date"
_STATIC_STATE_KEY = "ibkr_static_marks_applied"
_STATIC_MARKS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ibkr_marks.json"
)

# Flex reports carry more than equities; for PRICING purposes we want every
# category that can hold a position, not just STK. core.ibkr_client
# parse_positions() deliberately filters to STK because it feeds the holdings
# table — funds there would collide with the screenshot parser's own rows.
_PRICEABLE_CATEGORIES = {"STK", "FUND", "ETF", "BOND"}


def _credentials() -> tuple[Optional[str], Optional[str]]:
    """(token, query_id) if both are configured and not placeholders."""
    try:
        from core.settings import get_api_key, load_user_settings
        token = (get_api_key("IBKR_FLEX_TOKEN") or "").strip()
        if not token or "your_" in token.lower():
            return None, None
        qid = str(load_user_settings().get("ibkr_flex_query_id", "") or "").strip()
        return (token, qid) if qid else (None, None)
    except Exception:
        return None, None


def is_configured() -> bool:
    return all(_credentials())


def _parse_marks(xml_string: str) -> Dict[str, float]:
    """{ticker: markPrice} for every priceable position in a Flex report."""
    import xml.etree.ElementTree as ET
    from core.ibkr_client import _apply_exchange_suffix, _safe_float

    marks: Dict[str, float] = {}
    root = ET.fromstring(xml_string)
    for pos in root.iter("OpenPosition"):
        if pos.get("assetCategory", "") not in _PRICEABLE_CATEGORIES:
            continue
        symbol = (pos.get("symbol") or "").strip()
        if not symbol:
            continue
        ticker = _apply_exchange_suffix(symbol, (pos.get("listingExchange") or "").strip())
        mark = _safe_float(pos.get("markPrice", "0"))
        if mark > 0:
            marks[ticker] = mark
    return marks


def refresh_prices(only_missing: bool = True) -> Dict:
    """Fetch IBKR marks and write them into price_cache.

    ``only_missing`` (default) writes a mark only where the live cascade has
    no price — IBKR's mark is a previous close, so it must never overwrite a
    genuinely live quote. Set False to write every mark (used by the manual
    button on the IBKR Sync page).

    Returns {"ok", "written", "fetched", "skipped_live", "error"}.
    """
    out = {"ok": False, "written": 0, "fetched": 0, "skipped_live": 0, "error": None}
    token, qid = _credentials()
    if not token:
        out["error"] = "not_configured"
        return out

    try:
        from core.ibkr_client import request_flex_report, fetch_flex_report
        ref = request_flex_report(token, qid)
        xml_data = fetch_flex_report(token, ref)
        marks = _parse_marks(xml_data)
        out["fetched"] = len(marks)
    except Exception as e:
        logger.warning("IBKR price refresh failed: %s", e)
        out["error"] = "fetch_failed"
        return out

    if not marks:
        out["ok"] = True
        return out

    try:
        from core.database import get_price_cache, save_price_cache
        existing = get_price_cache(list(marks.keys())) if only_missing else {}
        payload: Dict[str, dict] = {}
        for ticker, mark in marks.items():
            if only_missing:
                have = existing.get(ticker) or {}
                if have.get("price"):
                    out["skipped_live"] += 1
                    continue
            payload[ticker] = {
                "price": mark,
                "change": None,
                "changesPercentage": None,
                "source": "ibkr",
            }
        if payload:
            save_price_cache(payload)
        out["written"] = len(payload)
        out["ok"] = True
    except Exception as e:
        logger.warning("IBKR price refresh could not write cache: %s", e)
        out["error"] = "write_failed"
    return out


def load_static_marks() -> Dict:
    """Load data/ibkr_marks.json — a committed snapshot of IBKR's mark price for
    every position, refreshed by hand with scripts/refresh_ibkr_marks.py.

    This is the fallback for when the Flex Query web service is not configured
    (it never has been on Render). Returns {} if the file is missing or bad.
    """
    try:
        with open(_STATIC_MARKS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        marks = data.get("marks") or {}
        return data if isinstance(marks, dict) and marks else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning("Could not read %s: %s", _STATIC_MARKS_PATH, e)
        return {}


def apply_static_marks_to_holdings() -> Optional[Dict]:
    """Write the committed IBKR marks into holdings.last_known_price, once per
    day (or whenever data/ibkr_marks.json changes).

    last_known_price is the durable fallback the price cascade already uses
    (core/cio_engine.py) for holdings no live quote API can price — UAE ADX/DFM
    lines, offshore funds, suspended tickers. Nothing else back-fills it, so
    without this those holdings show no value until a manual IBKR Sync.

    Never raises. Returns {"applied", "as_of", "updated"} on the run that did
    the work, else None.
    """
    try:
        data = load_static_marks()
        if not data:
            return None
        marks = data.get("marks", {})
        as_of = str(data.get("as_of", ""))

        from core.database import get_fortress_state, save_fortress_state
        # Re-apply when the snapshot file changes, not only once per day.
        stamp = f"{date.today().isoformat()}|{as_of}"
        if get_fortress_state(_STATIC_STATE_KEY) == stamp:
            return None
        save_fortress_state(_STATIC_STATE_KEY, stamp)

        from core.database import backfill_last_known_prices
        updated = backfill_last_known_prices(marks)
        result = {"applied": True, "as_of": as_of, "marks": len(marks), "updated": updated}
        logger.info("IBKR static marks applied: %s", result)
        return result
    except Exception as e:
        logger.warning("apply_static_marks_to_holdings skipped: %s", e)
        return None


def maybe_daily_refresh() -> Optional[Dict]:
    """Run :func:`refresh_prices` at most once per calendar day.

    Called on every script run; the date stamp lives in ``fortress_state`` so
    it is shared across sessions and survives a Render restart — otherwise
    every cold start would re-trigger the Flex request, and IBKR rate-limits
    Flex report generation hard.

    Returns the refresh result on the run that actually did the work, else
    None. Never raises: a broker outage must not take the app down.
    """
    try:
        if not is_configured():
            return None
        from core.database import get_fortress_state, save_fortress_state
        today = date.today().isoformat()
        if get_fortress_state(_STATE_KEY) == today:
            return None
        # Stamp BEFORE the fetch, not after: a Flex request that times out
        # would otherwise be retried on every rerun for the rest of the day.
        save_fortress_state(_STATE_KEY, today)
        result = refresh_prices(only_missing=True)
        logger.info("IBKR daily price refresh: %s", result)
        return result
    except Exception as e:
        logger.warning("IBKR daily price refresh skipped: %s", e)
        return None
