"""
IBKR Flex Query Client
======================
HTTP client for Interactive Brokers Flex Query API.

The Flex Query API works in two sequential HTTP calls:
  1. SendRequest  -- submit query, receive a reference code
  2. GetStatement -- poll with reference code until the report is ready

Parses <OpenPosition> elements from the XML response into
a list of position dicts compatible with Prosper's holdings schema.
"""

import time
import logging
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# IBKR API Endpoints
# ─────────────────────────────────────────
_BASE = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService"
SEND_URL = f"{_BASE}.SendRequest"
GET_URL = f"{_BASE}.GetStatement"

# ─────────────────────────────────────────
# Exchange-to-yfinance suffix mapping
# ─────────────────────────────────────────
EXCHANGE_SUFFIX: Dict[str, str] = {
    "NASDAQ": "",   "NYSE": "",    "ARCA": "",    "AMEX": "",    "BATS": "",
    "SBF": ".PA",   "IBIS": ".DE", "FWB": ".F",   "XETRA": ".DE",
    "LSE": ".L",    "LSEETF": ".L",
    "EBS": ".SW",   "SWX": ".SW",  "VIRTX": ".SW",
    "NSE": ".NS",   "BSE": ".BO",
    "ASX": ".AX",
    "SEHK": ".HK",  "HKSE": ".HK",
    "SGX": ".SI",
    "TSE": ".TO",   "VENTURE": ".V",
    "ADX": ".AE",   "DFM": ".AE",
    "ENEXT.BE": ".BR", "AEB": ".AS",
    "MEXI": ".MX",  "BVL": ".LS",
    "KSE": ".KS",   "TSEJ": ".T",
}

# ─────────────────────────────────────────
# IBKR error codes with human-readable messages
# ─────────────────────────────────────────
IBKR_ERRORS: Dict[str, str] = {
    "1018": "Token is invalid or expired. Please generate a new Flex Query token in IBKR Account Management.",
    "1019": "Query ID is invalid. Please verify the Flex Query ID in IBKR Account Management.",
    "1020": "Too many requests. IBKR rate-limits Flex Queries -- please wait a few minutes and try again.",
    "1012": "Flex Query has no data for the requested period or account.",
}


class IBKRError(Exception):
    """Raised when the IBKR Flex Query API returns an error."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"IBKR Error {code}: {message}")


# ─────────────────────────────────────────
# Step 1: Request the report
# ─────────────────────────────────────────

def request_flex_report(token: str, query_id: str) -> str:
    """
    Send a Flex Query request to IBKR and return the reference code.

    Args:
        token:    Flex Query token from IBKR Account Management.
        query_id: Flex Query ID configured in IBKR.

    Returns:
        Reference code string used to fetch the completed report.

    Raises:
        IBKRError: If IBKR returns an error status.
        requests.RequestException: On network failure.
    """
    resp = requests.post(SEND_URL, params={"t": token, "q": query_id, "v": "3"}, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)

    status = root.findtext("Status", "").strip()
    error_code = root.findtext("ErrorCode", "").strip()

    if status != "Success":
        message = root.findtext("ErrorMessage", "Unknown error").strip()
        friendly = IBKR_ERRORS.get(error_code, message)
        raise IBKRError(error_code, friendly)

    ref_code = root.findtext("ReferenceCode", "").strip()
    if not ref_code:
        raise IBKRError("0", "IBKR returned Success but no ReferenceCode was found in the response.")

    logger.info("IBKR SendRequest OK -- reference code: %s", ref_code)
    return ref_code


# ─────────────────────────────────────────
# Step 2: Poll for the finished report
# ─────────────────────────────────────────

def fetch_flex_report(token: str, reference_code: str,
                      max_retries: int = 10, delay: float = 3.0) -> str:
    """
    Poll IBKR until the Flex report is ready, then return the raw XML.

    Args:
        token:          Flex Query token.
        reference_code: Reference code from request_flex_report().
        max_retries:    How many times to poll before giving up.
        delay:          Seconds to wait between retries.

    Returns:
        Raw XML string of the completed Flex statement.

    Raises:
        IBKRError: If IBKR returns an error or report never becomes ready.
    """
    for attempt in range(1, max_retries + 1):
        resp = requests.post(GET_URL, params={"t": token, "q": reference_code, "v": "3"}, timeout=60)
        resp.raise_for_status()

        xml_text = resp.text

        # Quick check: if the response is a full FlexQueryResponse, it's ready
        if "<FlexQueryResponse" in xml_text or "<OpenPosition" in xml_text:
            logger.info("IBKR GetStatement ready on attempt %d", attempt)
            return xml_text

        # Otherwise parse as status envelope
        try:
            root = ET.fromstring(xml_text)
            status = root.findtext("Status", "").strip()
            error_code = root.findtext("ErrorCode", "").strip()

            if status == "Warn":
                # Report still generating -- retry
                logger.info("IBKR report generating (attempt %d/%d), waiting %.1fs...",
                            attempt, max_retries, delay)
                time.sleep(delay)
                continue

            if status == "Success":
                # Shouldn't happen without position data, but return what we got
                return xml_text

            # Error
            message = root.findtext("ErrorMessage", "Unknown error").strip()
            friendly = IBKR_ERRORS.get(error_code, message)
            raise IBKRError(error_code, friendly)

        except ET.ParseError:
            # Non-XML response -- possibly the raw statement
            return xml_text

    raise IBKRError("TIMEOUT", f"IBKR report was not ready after {max_retries} attempts ({max_retries * delay:.0f}s). Try again later.")


# ─────────────────────────────────────────
# XML Parsing
# ─────────────────────────────────────────

def _apply_exchange_suffix(symbol: str, listing_exchange: str) -> str:
    """Append yfinance-compatible suffix based on the listing exchange."""
    suffix = EXCHANGE_SUFFIX.get(listing_exchange, "")
    if suffix and not symbol.endswith(suffix):
        return symbol + suffix
    return symbol


def parse_positions(xml_string: str) -> List[Dict]:
    """
    Parse <OpenPosition> elements from IBKR Flex Query XML.

    Filters to assetCategory="STK" only (skips options, futures, forex, etc.).

    Returns:
        List of dicts with keys: ticker, name, quantity, avg_cost, currency,
        market_price, market_value, unrealized_pnl, asset_category
    """
    root = ET.fromstring(xml_string)
    positions = []
    skipped = []

    for pos in root.iter("OpenPosition"):
        asset_cat = pos.get("assetCategory", "")
        if asset_cat != "STK":
            skipped.append(f"{pos.get('symbol', '?')} ({asset_cat})")
            continue

        symbol = pos.get("symbol", "").strip()
        exchange = pos.get("listingExchange", "").strip()
        ticker = _apply_exchange_suffix(symbol, exchange)

        positions.append({
            "ticker":          ticker,
            "name":            pos.get("description", "").strip(),
            "quantity":        _safe_float(pos.get("position", "0")),
            "avg_cost":        _safe_float(pos.get("costBasisPrice", "0")),
            "currency":        pos.get("currency", "USD").strip(),
            "market_price":    _safe_float(pos.get("markPrice", "0")),
            "market_value":    _safe_float(pos.get("positionValue", "0")),
            "unrealized_pnl":  _safe_float(pos.get("fifoPnlUnrealized", "0")),
            "asset_category":  asset_cat,
        })

    if skipped:
        logger.info("Skipped %d non-STK positions: %s", len(skipped), ", ".join(skipped[:10]))

    logger.info("Parsed %d stock positions from IBKR Flex Query", len(positions))
    return positions


def _safe_float(val: str) -> float:
    """Convert string to float, returning 0.0 on failure."""
    try:
        return float(val) if val else 0.0
    except (ValueError, TypeError):
        return 0.0


# ─────────────────────────────────────────
# High-level convenience function
# ─────────────────────────────────────────

def get_ibkr_positions(token: str, query_id: str) -> List[Dict]:
    """
    End-to-end: request a Flex report, wait for it, parse stock positions.

    Args:
        token:    IBKR Flex Query token.
        query_id: IBKR Flex Query ID.

    Returns:
        List of position dicts ready for Prosper's holdings table.
    """
    ref_code = request_flex_report(token, query_id)
    xml_data = fetch_flex_report(token, ref_code)
    return parse_positions(xml_data)
