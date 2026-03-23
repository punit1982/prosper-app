"""
Screenshot Parser
=================
Reads brokerage screenshots using Claude Vision AI and extracts holdings.

Accuracy improvements (v2):
- Highly explicit field definitions — Claude now cannot confuse quantity vs price vs value
- Broker-specific column name hints (Zerodha, IBKR, HSBC, Tiger, etc.)
- Markdown JSON stripping (handles Claude wrapping response in code blocks)
- Parse cache: same image → instant result, zero API cost
- Clear error reporting: real error messages, never a vague "failed"
"""

from typing import List, Dict, Union, Optional
import hashlib
import os
import base64
import json
import re

# Return type: list of holdings on success, error string on failure
ParseResult = Union[List[Dict], str]


def parse_brokerage_image(image_bytes: bytes, media_type: str) -> ParseResult:
    """
    Parse a brokerage screenshot and extract holdings.

    Flow:
    1. Hash the image → check parse cache → return instantly if cached
    2. If no cache: call Claude Vision API with an accurate extraction prompt
    3. Save result to cache for next time
    4. Return list of holdings or a human-readable error string

    Returns:
        List of dicts on success: [{"ticker", "name", "quantity", "avg_cost", "currency"}, ...]
        String on failure: human-readable error message.
    """
    from core.settings import SETTINGS
    from core.database import get_cached_parse, save_parse_cache

    cache_enabled = SETTINGS.get("parse_cache_enabled", True)
    image_hash = hashlib.sha256(image_bytes).hexdigest()

    # --- Step 1: Check parse cache ---
    if cache_enabled:
        ttl_days = SETTINGS.get("parse_cache_ttl_days", 90)
        cached = get_cached_parse(image_hash, ttl_days=ttl_days)
        if cached is not None:
            return cached  # Cache hit — instant, free

    # --- Step 2: Check API key (env var OR Streamlit Cloud secrets) ---
    from core.settings import get_api_key
    api_key = get_api_key("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your_anthropic_api_key_here":
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Please add it in Settings → Environment Variables "
            "on your Render dashboard, or in your local .env file."
        )

    # --- Step 3: Call Claude Vision ---
    result = _claude_vision_parse(image_bytes, media_type, api_key)

    # --- Step 4: Cache the result if successful ---
    if cache_enabled and isinstance(result, list):
        save_parse_cache(image_hash, result)

    return result


def _mock_parse() -> List[Dict]:
    """Return sample holdings for demo/testing when no API key is set."""
    return [
        {"ticker": "AAPL",        "name": "Apple Inc",            "quantity": 50,  "avg_cost": 178.50, "currency": "USD"},
        {"ticker": "MSFT",        "name": "Microsoft Corporation", "quantity": 30,  "avg_cost": 342.00, "currency": "USD"},
        {"ticker": "RELIANCE.NS", "name": "Reliance Industries",   "quantity": 100, "avg_cost": 2450.0, "currency": "INR"},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT — v2: highly explicit to prevent quantity / price / value confusion
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACTION_PROMPT = """You are analyzing a brokerage account screenshot or portfolio statement.
Your task: extract EVERY stock or fund holding visible in the image.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIELD DEFINITIONS — READ CAREFULLY BEFORE EXTRACTING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ticker  — The stock/ETF symbol shown on the screen.
   • Include the exchange suffix when visible:
       .NS  = NSE India    (e.g. RELIANCE.NS)
       .BO  = BSE India    (e.g. TATASTEEL.BO)
       .AE  = Dubai DFM    (e.g. EMAAR.AE)
       .HK  = Hong Kong    (e.g. 0700.HK)
       .SI  = Singapore SGX (e.g. D05.SI, S08.SI)
       .SW  = Swiss SIX     (e.g. SREN.SW, IEDY.SW)
       .L   = London LSE    (e.g. SHEL.L)
   • No suffix for US stocks (NYSE/NASDAQ) (e.g. AAPL, MSFT, NVDA)
   • IBKR shows exchange as SGX, EBS, NASDAQ.NMS, NYSE — map these:
       SGX → .SI suffix     EBS → .SW suffix
       NASDAQ.NMS or NYSE → no suffix (US stock)

2. name — The full company or fund name as printed on the screen.

3. quantity — ⚠️ THE NUMBER OF SHARES / UNITS YOU CURRENTLY HOLD.
   ────────────────────────────────────────────────────────────
   ✅ CORRECT: the column labelled "Qty", "Quantity", "Units",
      "No. of Shares", "Shares", "Holdings", "Position"
   ❌ WRONG — DO NOT use these columns for quantity:
      • "LTP" / "Last Price" / "Current Price" / "Market Price"
      • "Current Value" / "Market Value" / "Portfolio Value"
      • "Invested Value" / "Total Investment" / "Cost"
      • "P&L" / "Gain" / "Return"
   ────────────────────────────────────────────────────────────
   Typical range: 1 – 100,000 shares.
   If a row shows "100 shares" and a price of "₹1,350", quantity = 100.

4. avg_cost — ⚠️ YOUR AVERAGE PURCHASE PRICE PER SINGLE SHARE/UNIT.
   ────────────────────────────────────────────────────────────
   ✅ CORRECT: columns labelled "Avg. Cost", "Avg Price",
      "Average Price", "Buy Avg", "Purchase Price", "WAC"
   ❌ WRONG — DO NOT use these for avg_cost:
      • "LTP" / "Current Price" / "Market Price"
      • "Current Value" / "Market Value"
      • "Total Invested" / "Invested Amount"
      • "P&L" / "Gain"
   ────────────────────────────────────────────────────────────
   avg_cost × quantity should roughly equal the total invested amount shown.
   If total invested = ₹135,000 and quantity = 100, avg_cost = 1,350.

5. currency — The currency of avg_cost.
   USD for US stocks, INR for India, AED for UAE, HKD for Hong Kong,
   GBP for UK, EUR for Europe, SGD for Singapore.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMMON BROKER COLUMN LAYOUTS (for reference)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Zerodha:   Instrument | Qty | Avg. cost | LTP | Cur. val | P&L
IBKR:      Instrument | Position | Cst Bss (total cost) | Avg Price | Unrlzd P&L | Unrlzd P&L %
   Note for IBKR: "Position" = quantity, "Avg Price" = avg_cost, "Cst Bss" = total cost basis (NOT avg_cost).
   Positions may show "1.00K" meaning 1,000 shares, "20.0K" meaning 20,000 shares.
HSBC:      Stock | Units | Avg Unit Cost | Current Price | Market Value
Tiger:     Stock | Position | Avg Cost | Last Price | Market Value
Groww:     Holding | Units | Avg Buy Price | Current Price | Current Value

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY a JSON array. No markdown, no explanation, no code blocks.

[
  {"ticker": "AAPL", "name": "Apple Inc", "quantity": 100, "avg_cost": 150.25, "currency": "USD"},
  {"ticker": "RELIANCE.NS", "name": "Reliance Industries", "quantity": 50, "avg_cost": 2450.00, "currency": "INR"},
  {"ticker": "EMAAR.AE", "name": "Emaar Properties", "quantity": 1000, "avg_cost": 7.80, "currency": "AED"}
]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CASH & MARGIN BALANCES — ALSO EXTRACT THESE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
If you see cash balances, margin balances, or debit amounts on the screen,
include them as entries with:
  ticker = "CASH" (for positive cash) or "MARGIN" (for margin/debit)
  name = the label shown (e.g. "Settled Cash", "Margin Debit", "Net Cash Balance")
  quantity = the amount (positive for cash, negative for margin debt)
  avg_cost = 1 (always 1 for cash entries)
  currency = the currency of the cash balance

Example: {"ticker": "CASH", "name": "Settled Cash Balance", "quantity": 50000, "avg_cost": 1, "currency": "USD"}
Example: {"ticker": "MARGIN", "name": "Margin Debit Balance", "quantity": -25000, "avg_cost": 1, "currency": "USD"}

If you cannot read the image or find portfolio data, return:
{"error": "Short description of the problem (e.g. image is blurry, no holdings table found)"}

ONLY valid JSON. Nothing else."""


def _claude_vision_parse(image_bytes: bytes, media_type: str, api_key: str) -> ParseResult:
    """Send image to Claude Vision API and return structured holdings."""
    try:
        import anthropic
    except ImportError:
        return "The 'anthropic' package is not installed. Run: pip install anthropic"

    client = anthropic.Anthropic(api_key=api_key)
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    # Try models in order — different API tiers/regions support different models
    _MODELS_TO_TRY = [
        "claude-sonnet-4-5-20250514",
        "claude-haiku-4-5-20250514",
        "claude-3-5-sonnet-20241022",
    ]

    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_data,
            },
        },
        {"type": "text", "text": _EXTRACTION_PROMPT},
    ]

    response = None
    last_error = None
    for model in _MODELS_TO_TRY:
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": content}],
            )
            break  # success
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "not_found" in err_str:
                last_error = err_str
                continue  # try next model
            return f"Claude API call failed: {e}"

    if response is None:
        return (
            f"No Claude model is accessible with your API key. "
            f"Please verify your key at console.anthropic.com has billing enabled. "
            f"Last error: {last_error}"
        )

    # --- Parse the response ---
    result_text = response.content[0].text

    # Strip markdown code blocks if Claude wrapped the JSON
    cleaned = result_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        return f"Claude returned unexpected text (not JSON):\n{result_text[:400]}"

    if isinstance(result, dict) and "error" in result:
        return f"Claude could not read the image: {result['error']}"

    if not isinstance(result, list):
        return f"Unexpected response format from Claude: {type(result).__name__}"

    return result
