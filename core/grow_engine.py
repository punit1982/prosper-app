"""
GROW v5.1 Engine
================
Runs the GROW framework (grow/GROW v5 1 CORE 04Sep2026.md + annexes) on one
ticker and returns two verdicts:

  • Durability score 0–100   — is this worth owning (contains no price)
  • Entry verdict            — STRONG BUY · BUY · HOLD · SELL · STRONG SELL,
                               computed from expected return vs required return,
                               with the four-level price ladder

This module replaces core/prosper_analysis.py as the analysis engine. The
PROSPER context builder is reused only to hand Claude a Tier-5 data snapshot
(aggregator data = confirmation only, per GROW §6.2); retrieval of filings is
done by Claude itself through server-side web search / web fetch tools.

Tiers
  screen    provider data only, no web retrieval, margin-room screen (cheap)
  standard  Sonnet 5 + web search/fetch, full two-verdict memo
  full      Opus 5 + deeper retrieval + technical appendix

Design notes
  • The framework text is sent as a cached system block (prompt caching) so a
    batch pays for it once, not per stock.
  • Position-blind (rule 13): holdings are never passed into the prompt.
  • Continuity (§11): the previous run's machine-readable result is passed back
    as PRIOR RUN so the model can produce the change table.
  • Rule 22: results are tagged framework="GROW v5.1"; legacy PROSPER rows are
    superseded, never mapped.
"""

import os
import re
import json
import time
import logging
from datetime import datetime
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from core.settings import (
    CLAUDE_DEFAULT_MODEL, CLAUDE_BEST_MODEL, CLAUDE_FAST_MODEL,
    CLAUDE_MODEL_PRIORITY, extract_text, get_api_key,
)

_log = logging.getLogger("prosper.grow")

GROW_VERSION = "GROW v5.1"
GROW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "grow")
GROW_CORE_FILE = "GROW v5 1 CORE 04Sep2026.md"
# Annex D is review-only and is never loaded during a run (per the CORE header).
GROW_RUNTIME_ANNEXES = [
    "GROW v5 1 ANNEX E ARCHETYPE LOOKUPS.md",
    "GROW v5 1 ANNEX A COMPANIES WITHOUT HISTORY.md",
    "GROW v5 1 ANNEX B SPECIAL MEASUREMENT BASES.md",
    "GROW v5 1 ANNEX C LIFE SCIENCES.md",
]

ENTRY_SCALE = ["STRONG SELL", "SELL", "HOLD", "BUY", "STRONG BUY"]
LAST_RAW_TEXT = ""  # raw model output of the most recent run (debugging aid)

# Per-1M-token prices (USD) used for the cost estimate shown in the UI
_PRICES = {
    CLAUDE_FAST_MODEL:    {"in": 1.00, "out": 5.00,  "cache_read": 0.10, "cache_write": 1.25},
    CLAUDE_DEFAULT_MODEL: {"in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    CLAUDE_BEST_MODEL:    {"in": 5.00, "out": 25.00, "cache_read": 0.50, "cache_write": 6.25},
}
_WEB_SEARCH_PRICE = 0.01   # per search request

# NOTE: max_tokens must leave room for the model's own thinking (current models
# think by default and it counts against the output budget) PLUS the memo PLUS
# the JSON block. Too small a cap truncates before the JSON and the run is lost.
GROW_TIERS = {
    "screen": {
        "label": "Screen",
        "model": CLAUDE_DEFAULT_MODEL,
        "max_tokens": 8000,
        "thinking": {"type": "disabled"},   # fast + cheap; the screen is provisional by definition
        "effort": None,
        "web": False,
        "max_searches": 0,
        "description": "Margin-room screen on provider data only — no filings, short memo (~$0.10/stock)",
        "est_cost": 0.10,
    },
    "standard": {
        "label": "Standard GROW",
        "model": CLAUDE_DEFAULT_MODEL,
        "max_tokens": 32000,
        "thinking": {"type": "adaptive"},
        "effort": "high",
        "web": True,
        "max_searches": 12,
        "description": "Full two-verdict memo; Claude retrieves filings via web search (~$0.60/stock)",
        "est_cost": 0.60,
    },
    "full": {
        "label": "Full GROW",
        "model": CLAUDE_BEST_MODEL,
        "max_tokens": 48000,
        "thinking": {"type": "adaptive"},
        "effort": "xhigh",
        "web": True,
        "max_searches": 25,
        "description": "Opus 5, deeper retrieval, technical appendix printed (~$2.50/stock)",
        "est_cost": 2.50,
    },
}


# ─────────────────────────────────────────
# FRAMEWORK TEXT (cached in memory; sent as a cached system block)
# ─────────────────────────────────────────

@lru_cache(maxsize=1)
def load_framework_text() -> str:
    parts = []
    core_path = os.path.join(GROW_DIR, GROW_CORE_FILE)
    with open(core_path, "r", encoding="utf-8") as f:
        parts.append(f.read())
    for name in GROW_RUNTIME_ANNEXES:
        p = os.path.join(GROW_DIR, name)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                parts.append(f"\n\n<!-- ===== {name} ===== -->\n\n" + f.read())
    return "\n".join(parts)


def framework_available() -> bool:
    return os.path.exists(os.path.join(GROW_DIR, GROW_CORE_FILE))


# ─────────────────────────────────────────
# OUTPUT CONTRACT
# ─────────────────────────────────────────

_JSON_CONTRACT = """
{
  "ticker": "AAPL",
  "company": "Apple Inc.",
  "entity_line": "Apple Inc. · NASDAQ · one listing (AAPL)",
  "what_it_does": "3-5 plain sentences",
  "classification": {
    "archetype": "A2", "archetype_name": "Consumer brand", "gate": "Gate 9",
    "runner_up": "T1", "runner_up_entry": "HOLD",
    "basis": "M1", "stage": "S4", "profile": "P1",
    "regime_factor": 1.00, "valuation_date": "2030-12-31", "horizon_years": 4.32
  },
  "durability": {
    "score": 74, "band": "Strong",
    "available_weight": 100, "raw_over_available": 0.74,
    "integrity_level": "0", "integrity_multiplier": 1.00,
    "caps_applied": [],
    "criteria": [
      {"n": 1, "name": "Market pull", "score": 6, "weight": 6, "observable": "..."},
      {"n": 2, "name": "Product and customer evidence", "score": 8, "weight": 14, "observable": "..."},
      {"n": 3, "name": "Moat and bottleneck", "score": 8, "weight": 28, "observable": "..."},
      {"n": 4, "name": "Runway and optionality", "score": 6, "weight": 10, "observable": "..."},
      {"n": 5, "name": "Margin room", "score": 5, "weight": 12, "observable": "..."},
      {"n": 6, "name": "Economic engine", "score": 9, "weight": 10, "observable": "..."},
      {"n": 7, "name": "Traction", "score": 7, "weight": 6, "observable": "..."},
      {"n": 8, "name": "Operator credibility", "score": 8, "weight": 14, "observable": "..."}
    ]
  },
  "entry": {
    "verdict": "BUY",
    "price": 123.45, "price_date": "2026-09-05", "price_source": "...", "price_stale": false,
    "required_return": 0.114, "cagr_spot": 0.152, "excess_pts": 3.8,
    "central_value": 210.0,
    "ladder": {"strong_buy_below": 100.0, "buy_below": 135.0, "fair_high": 210.0, "reduce_above": 210.0},
    "stability": {"minus25": "HOLD", "central": "BUY", "plus25": "STRONG BUY", "unstable": true},
    "caps": [], "ceilings": [],
    "odds_clear_required": 0.58, "odds_lose_money": 0.22, "p10_return": -0.021, "p90_return": 0.334
  },
  "cases": {
    "break": {"price": 60.0, "return_pa": -0.15, "what_must_be_true": "..."},
    "bear":  {"price": 100.0, "return_pa": -0.04, "what_must_be_true": "..."},
    "base":  {"price": 210.0, "return_pa": 0.152, "what_must_be_true": "..."},
    "bull":  {"price": 300.0, "return_pa": 0.25, "what_must_be_true": "..."}
  },
  "driving_inputs": [
    {"input": "...", "value": "...", "class": "A", "source": "...", "moves_by": "..."}
  ],
  "confidence": "reasonably confident",
  "one_reason": {"criterion": "...", "what_would_prove_it_false": "..."},
  "break_triggers": [{"metric": "...", "threshold": "...", "effect_on_durability": "..."}],
  "failed_peer": {"name": "...", "why": "..."},
  "uncertainties": ["..."],
  "retrieval": {"retrieved": 31, "not_disclosed": 6, "not_reached": 0, "negative_logs": ["NOT FOUND — ..."]},
  "change_table": [{"input": "...", "from": "...", "to": "...", "document": "...", "date": "..."}],
  "provisional_rules_applied": [],
  "screen_only": false
}
"""

_APP_INSTRUCTIONS = """You are the GROW v5.1 engine running inside the Prosper investment app.
The complete framework (CORE + runtime annexes) is in the previous system block. Follow it exactly.

OPERATING RULES FOR THIS ENVIRONMENT
1. Trigger: the user message is `GROW <TICKER>` with an optional modifier. Run the nine steps of §3.
2. Retrieval: {retrieval_rule}
3. The DATA SNAPSHOT in the user message is Tier-5 aggregator data (confirmation only under §6.2). Never let it be the sole basis of a price-setting number. It does give you today's price with a timestamp; cross-check it against a second source when you can, and mark it stale per rule 6 if it is older than the last completed session.
4. Position-blind (rule 13): you are given no holding, cost basis or weight. Do not ask for one.
5. If the ticker could map to more than one listing, take the listing in the DATA SNAPSHOT (its exchange and currency), name the alternatives in `uncertainties`, and continue — this environment cannot stop and ask.
6. Always produce both verdicts (rule 1). The only permitted Entry words are STRONG BUY, BUY, HOLD, SELL, STRONG SELL (rule 22).
7. Where a PRIOR RUN is supplied, treat this as an update under §11: carry unchanged inputs, and fill `change_table` for every input that moved. If Durability moved, the table must not be empty.
8. Currency: all prices in the listing currency shown in the DATA SNAPSHOT.

OUTPUT — TWO PARTS, IN THIS ORDER
PART 1 — the memo in plain English, in the §10.2 order, as markdown. {memo_rule}
PART 2 — a single fenced ```json block, the LAST thing in your reply, matching this shape exactly (all keys present; use null where a value genuinely does not exist; rates as decimals, e.g. 0.114 for 11.4%):
{contract}
The JSON is machine-read: `durability.score` (0–100), `entry.verdict` (one of the five words), `entry.ladder` and `entry.price` are mandatory and must agree with the memo.
"""

_RETRIEVAL_WEB = (
    "You have web_search and web_fetch tools. Use them to work the §6 source ladder — primary filings first "
    "(SEC EDGAR / the exchange's filing system / the company's investor-relations site), then the company on the record, "
    "then aggregators for confirmation only. You have a budget of about {n} searches: spend them on the load-bearing "
    "Class A inputs (cover-page share count, debt schedule, guidance, forward book, the latest quarter). "
    "Every item ends as RETRIEVED, NOT DISCLOSED, or NOT REACHED — and every NOT REACHED must be listed in `uncertainties`."
)
_RETRIEVAL_SCREEN = (
    "This is a `screen` run (§1 modifier): no web retrieval is available. Work only from the DATA SNAPSHOT and what you "
    "already know. Score the margin-room construction of §3 step 5 first and honestly; mark every input you could not "
    "retrieve as NOT REACHED in `retrieval`, treat the result as provisional, set `screen_only` to true, and set confidence "
    "to \"this is a close call and I could be wrong\" unless the snapshot fully supports better."
)


def _system_blocks(tier: str) -> List[dict]:
    cfg = GROW_TIERS[tier]
    retrieval_rule = (
        _RETRIEVAL_WEB.format(n=cfg["max_searches"]) if cfg["web"] else _RETRIEVAL_SCREEN
    )
    memo_rule = (
        "Include the §10.2 appendix (section 11) in full."
        if tier == "full" else
        "Keep the memo tight: sections 1–9 of §10.2; the appendix may be summarised."
        if tier == "standard" else
        "Screen output: the two-answers block, the margin-room construction with its score, the driving inputs, "
        "and a one-paragraph reason. No full memo."
    )
    instructions = _APP_INSTRUCTIONS.format(
        retrieval_rule=retrieval_rule, memo_rule=memo_rule, contract=_JSON_CONTRACT,
    )
    return [
        {"type": "text", "text": load_framework_text(), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": instructions},
    ]


# ─────────────────────────────────────────
# DATA SNAPSHOT (Tier 5 — confirmation only)
# ─────────────────────────────────────────

def _fmt_money(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "n/a"
    if abs(v) >= 1e9:
        return f"{v/1e9:,.2f}bn"
    if abs(v) >= 1e6:
        return f"{v/1e6:,.1f}m"
    return f"{v:,.0f}"


def _financials_snapshot(ticker: str) -> str:
    """Compact multi-year P&L / cash-flow / balance-sheet lines from yfinance (if available)."""
    try:
        from core.data_engine import get_financials
        fin = get_financials(ticker) or {}
    except Exception:
        return ""
    lines = []

    def _rows(df, wanted: Dict[str, str], label: str):
        if df is None or getattr(df, "empty", True):
            return
        cols = list(df.columns)[:4]
        hdr = " | ".join(str(getattr(c, "year", c)) for c in cols)
        sub = []
        for key, name in wanted.items():
            if key in df.index:
                vals = [_fmt_money(df.loc[key, c]) for c in cols]
                sub.append(f"  {name}: " + " | ".join(vals))
        if sub:
            lines.append(f"{label} (columns: {hdr}):")
            lines.extend(sub)

    _rows(fin.get("income_annual"), {
        "Total Revenue": "Revenue", "Gross Profit": "Gross profit",
        "Operating Income": "Operating income", "Net Income": "Net income",
        "Basic Average Shares": "Basic avg shares", "Diluted Average Shares": "Diluted avg shares",
    }, "ANNUAL INCOME STATEMENT")
    _rows(fin.get("income_quarterly"), {
        "Total Revenue": "Revenue", "Gross Profit": "Gross profit",
        "Operating Income": "Operating income", "Net Income": "Net income",
    }, "QUARTERLY INCOME STATEMENT")
    _rows(fin.get("cashflow_annual"), {
        "Operating Cash Flow": "Operating cash flow", "Capital Expenditure": "Capex",
        "Free Cash Flow": "Free cash flow", "Issuance Of Capital Stock": "Stock issued",
        "Repurchase Of Capital Stock": "Buybacks",
    }, "ANNUAL CASH FLOW")
    _rows(fin.get("balance_annual"), {
        "Cash And Cash Equivalents": "Cash", "Total Debt": "Total debt",
        "Net Debt": "Net debt", "Ordinary Shares Number": "Shares outstanding",
        "Stockholders Equity": "Equity",
    }, "ANNUAL BALANCE SHEET")
    return "\n".join(lines)


def build_data_snapshot(ticker: str, info: dict = None, price_quote: dict = None) -> Tuple[str, int]:
    """Return (snapshot_text, data_fields) — aggregator data for confirmation only."""
    info = info or {}
    lines = [f"TICKER (as held in Prosper): {ticker}"]
    lines.append(f"Snapshot taken: {datetime.now().strftime('%Y-%m-%d %H:%M')} local time")
    lines.append(f"Company (aggregator): {info.get('longName') or info.get('shortName') or 'n/a'}")
    lines.append(f"Exchange: {info.get('exchange', 'n/a')} | Currency: {info.get('currency') or info.get('financialCurrency') or 'n/a'} "
                 f"| Country: {info.get('country', 'n/a')} | Quote type: {info.get('quoteType', 'EQUITY')}")
    lines.append(f"Sector: {info.get('sector', 'n/a')} | Industry: {info.get('industry', 'n/a')}")

    price = None
    src = "yfinance info"
    if price_quote and price_quote.get("price"):
        price = price_quote["price"]
        src = price_quote.get("source", "prosper price cache")
    else:
        price = info.get("currentPrice") or info.get("regularMarketPrice")
    if price:
        lines.append(f"Price (Tier 5, {src}): {price} — cross-check against a second source before use")
    if info.get("marketCap"):
        lines.append(f"Market cap: {_fmt_money(info['marketCap'])} | Enterprise value: {_fmt_money(info.get('enterpriseValue'))}")
    if info.get("sharesOutstanding"):
        lines.append(f"Shares outstanding (aggregator — confirm from filing cover page): {_fmt_money(info['sharesOutstanding'])}")

    ratios = []
    for key, label in [("trailingPE", "trailing P/E"), ("forwardPE", "forward P/E"),
                       ("priceToSalesTrailing12Months", "P/S"), ("enterpriseToEbitda", "EV/EBITDA"),
                       ("priceToBook", "P/B"), ("beta", "beta")]:
        v = info.get(key)
        if v is not None:
            try:
                ratios.append(f"{label} {float(v):.2f}")
            except (TypeError, ValueError):
                pass
    if ratios:
        lines.append("Multiples (aggregator): " + " | ".join(ratios))

    fund = []
    for key, label in [("totalRevenue", "Revenue TTM"), ("grossMargins", "Gross margin"),
                       ("operatingMargins", "Operating margin"), ("profitMargins", "Net margin"),
                       ("revenueGrowth", "Revenue growth (last q, y/y)"), ("earningsGrowth", "Earnings growth"),
                       ("returnOnEquity", "ROE"), ("operatingCashflow", "Operating cash flow TTM"),
                       ("freeCashflow", "Free cash flow TTM"), ("totalCash", "Cash"), ("totalDebt", "Total debt"),
                       ("ebitda", "EBITDA")]:
        v = info.get(key)
        if v is None:
            continue
        if key in ("grossMargins", "operatingMargins", "profitMargins", "revenueGrowth", "earningsGrowth", "returnOnEquity"):
            try:
                fund.append(f"{label} {float(v)*100:.1f}%")
            except (TypeError, ValueError):
                pass
        else:
            fund.append(f"{label} {_fmt_money(v)}")
    if fund:
        lines.append("Fundamentals TTM (aggregator): " + " | ".join(fund))

    if info.get("targetMeanPrice"):
        lines.append(f"Sell-side (aggregator): mean target {info['targetMeanPrice']} from {info.get('numberOfAnalystOpinions', '?')} analysts, "
                     f"consensus '{info.get('recommendationKey', 'n/a')}'")
    hi, lo = info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow")
    if hi and lo:
        lines.append(f"52-week range: {lo} – {hi}")

    # Finnhub analyst intelligence (reuse existing formatter)
    try:
        from core.prosper_analysis import _fetch_finnhub_analyst
        fh = _fetch_finnhub_analyst(ticker)
        if fh:
            lines.append("Analyst actions (Finnhub, aggregator):\n" + fh)
    except Exception:
        pass

    fin_txt = _financials_snapshot(ticker)
    if fin_txt:
        lines.append("")
        lines.append("FINANCIAL STATEMENTS (aggregator copy of the filings — confirm load-bearing figures in the filing itself):")
        lines.append(fin_txt)

    summary = info.get("longBusinessSummary", "")
    if summary:
        lines.append("")
        lines.append("Business description (aggregator): " + (summary[:600] + "…" if len(summary) > 600 else summary))

    data_fields = sum(1 for l in lines if ":" in l)
    return "\n".join(lines), data_fields


# ─────────────────────────────────────────
# TOOLS
# ─────────────────────────────────────────

def _web_tools_for(model: str, max_searches: int) -> List[dict]:
    """Server-side web tools. The 2026-02-09 variants need Opus/Sonnet 4.6+; Haiku 4.5 uses the basic ones."""
    if max_searches <= 0:
        return []
    if model == CLAUDE_FAST_MODEL:
        return [
            {"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches},
            {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": max_searches, "max_content_tokens": 30000},
        ]
    return [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_searches, "max_content_tokens": 40000},
    ]


# ─────────────────────────────────────────
# PARSING
# ─────────────────────────────────────────

def _extract_json_block(text: str) -> Optional[dict]:
    """Return the LAST fenced ```json block as a dict (or the last {...} object as a fallback)."""
    if not text:
        return None
    fences = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidates = list(reversed(fences))
    if not candidates:
        # fallback: last top-level object
        start = text.rfind("\n{")
        if start != -1:
            candidates.append(text[start:].strip())
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            # tolerate trailing commas
            try:
                return json.loads(re.sub(r",\s*([}\]])", r"\1", c))
            except json.JSONDecodeError:
                continue
    return None


def _strip_json_block(text: str) -> str:
    """Memo markdown = everything before the final JSON fence."""
    m = list(re.finditer(r"```(?:json)?\s*\{", text))
    if not m:
        return text.strip()
    return text[: m[-1].start()].rstrip()


def _f(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _normalise_verdict(v) -> str:
    s = str(v or "").strip().upper().replace("_", " ")
    s = re.sub(r"\s+", " ", s)
    return s if s in ENTRY_SCALE else "HOLD"


def _usage_cost(usage, model: str) -> Tuple[float, dict]:
    p = _PRICES.get(model, _PRICES[CLAUDE_DEFAULT_MODEL])
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    searches = 0
    stu = getattr(usage, "server_tool_use", None)
    if stu is not None:
        searches = (getattr(stu, "web_search_requests", 0) or 0)
    cost = (inp * p["in"] + out * p["out"] + cr * p["cache_read"] + cw * p["cache_write"]) / 1e6 + searches * _WEB_SEARCH_PRICE
    return cost, {"input_tokens": inp, "output_tokens": out, "cache_read": cr, "cache_write": cw, "web_searches": searches}


# ─────────────────────────────────────────
# §8 ENTRY RESOLVER — arithmetic, not judgement (deterministic, in Python)
# ─────────────────────────────────────────

_RUNG = {v: i for i, v in enumerate(ENTRY_SCALE)}  # STRONG SELL=0 … STRONG BUY=4


def _cap_at(verdict: str, ceiling: str) -> str:
    return ENTRY_SCALE[min(_RUNG[verdict], _RUNG[ceiling])]


def _verdict_from_numbers(cagr: float, req: float, bull_loses: bool) -> str:
    """§8.1 table."""
    if cagr < 0:
        return "STRONG SELL" if bull_loses else "SELL"
    excess = (cagr - req) * 100
    if excess >= 8:
        return "STRONG BUY"
    if excess >= 0:
        return "BUY"
    return "HOLD"


def _apply_caps(verdict: str, caps: List[str], ceilings: List[str], integrity_level: str) -> Tuple[str, List[str]]:
    """§8.4 caps then §8.5 ceilings (lowest wins). Returns (verdict, list of what bound)."""
    bound = []
    caps_u = " ".join(str(c).upper() for c in (caps or []))
    ceil_u = " ".join(str(c).upper() for c in (ceilings or []))
    lvl = str(integrity_level or "0").upper().strip()
    if "NO FORWARD ENGINE" in caps_u:
        v2 = _cap_at(verdict, "HOLD")
        if v2 != verdict:
            bound.append("NO FORWARD ENGINE → capped at HOLD")
        verdict = v2
    if "PAPER PROFITS" in caps_u:
        # "one rung down — STRONG BUY→BUY, BUY→HOLD, HOLD→HOLD"
        v2 = {"STRONG BUY": "BUY", "BUY": "HOLD"}.get(verdict, verdict)
        if v2 != verdict:
            bound.append("PAPER PROFITS → one rung down")
        verdict = v2
    ceiling = None
    if lvl.startswith("4") or "STRONG SELL" in ceil_u or "FRAUD" in ceil_u or "DISQUALIF" in ceil_u:
        ceiling = "STRONG SELL"
    elif lvl.startswith("3A") or lvl.startswith("3C") or "ACCOUNTING" in ceil_u or "LICENCE" in ceil_u or "LICENSE" in ceil_u:
        ceiling = "HOLD"
    elif lvl.startswith("3B") or "CONDUCT" in ceil_u:
        ceiling = "BUY"
    if ceiling:
        v2 = _cap_at(verdict, ceiling)
        if v2 != verdict:
            bound.append(f"integrity ceiling {ceiling}")
        verdict = v2
    return verdict, bound


def resolve_entry(price, central, bull_price, horizon_years, required_return,
                  caps=None, ceilings=None, integrity_level="0") -> Optional[dict]:
    """Compute the Entry verdict, price ladder and ±25% stability from the model's inputs.

    Returns None if the inputs are not usable (no price / central value / horizon / bar).
    Stability approximates the ±25% terminal-multiple stress as ±25% on the central value.
    """
    p, c, n, r = _f(price), _f(central), _f(horizon_years), _f(required_return)
    if not p or not c or p <= 0 or c <= 0 or not r or r <= 0:
        return None
    n = n if (n and n > 0) else 5.0
    n = max(0.5, n)
    b = _f(bull_price)
    cagr = (c / p) ** (1.0 / n) - 1.0
    bull_loses = (b is not None and b > 0 and b < p)
    raw = _verdict_from_numbers(cagr, r, bull_loses)
    verdict, bound = _apply_caps(raw, caps, ceilings, integrity_level)
    ladder = {
        "strong_buy_below": round(c / (1 + r + 0.08) ** n, 2),
        "buy_below": round(c / (1 + r) ** n, 2),
        "fair_high": round(c, 2),
        "reduce_above": round(c, 2),
    }
    words = {}
    for key, mult in (("minus25", 0.75), ("central", 1.0), ("plus25", 1.25)):
        cg = (c * mult / p) ** (1.0 / n) - 1.0
        v, _ = _apply_caps(_verdict_from_numbers(cg, r, bull_loses and mult <= 1.0), caps, ceilings, integrity_level)
        words[key] = v
    words["unstable"] = len({words["minus25"], words["central"], words["plus25"]}) > 1
    return {
        "verdict": verdict, "raw_verdict": raw, "bound": bound,
        "cagr_spot": round(cagr, 4), "excess_pts": round((cagr - r) * 100, 1),
        "required_return": r, "horizon_years": n, "central_value": c, "price": p,
        "ladder": ladder, "stability": words,
    }


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

def run_grow(
    ticker: str,
    tier: str = "standard",
    info: dict = None,
    price_quote: dict = None,
    prior: dict = None,
    modifier: str = "",
) -> Tuple[Optional[Dict], str]:
    """Run GROW on one ticker. Returns (result_dict, error_message); result is None on failure.

    The result dict is DB-ready for core.database.save_prosper_analysis().
    """
    if not framework_available():
        return None, "GROW framework files not found in the app's grow/ folder."
    api_key = get_api_key("ANTHROPIC_API_KEY")
    if not api_key or api_key.startswith("your_"):
        return None, "Anthropic API key not configured. Add ANTHROPIC_API_KEY on Render (Environment) or in your local .env."

    tier = tier if tier in GROW_TIERS else "standard"
    cfg = GROW_TIERS[tier]
    snapshot, data_fields = build_data_snapshot(ticker, info, price_quote)

    user_parts = [f"GROW {ticker}" + (f" {modifier}" if modifier else "") + (" screen" if tier == "screen" and "screen" not in modifier else "")]
    user_parts.append("\nDATA SNAPSHOT (Tier 5 — confirmation only):\n" + snapshot)
    if prior:
        try:
            prior_slim = {k: prior.get(k) for k in ("classification", "durability", "entry", "one_reason", "break_triggers", "driving_inputs") if prior.get(k)}
            prior_slim["analysis_date"] = prior.get("analysis_date")
            user_parts.append("\nPRIOR RUN (§11 continuity — update against this):\n```json\n" + json.dumps(prior_slim, default=str)[:12000] + "\n```")
        except Exception:
            pass
    user_msg = "\n".join(user_parts)

    try:
        import anthropic
    except ImportError:
        return None, "anthropic package not installed."

    client = anthropic.Anthropic(api_key=api_key, timeout=900.0, max_retries=1)
    system = _system_blocks(tier)
    models = [cfg["model"]] + [m for m in CLAUDE_MODEL_PRIORITY if m != cfg["model"]]

    t0 = time.time()
    total_cost = 0.0
    usage_tot = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0, "web_searches": 0}
    final_text = ""
    model_used = None
    last_error = None
    last_stop = None

    for model in models:
        tools = _web_tools_for(model, cfg["max_searches"] if cfg["web"] else 0)
        messages = [{"role": "user", "content": user_msg}]
        kwargs = {"model": model, "max_tokens": cfg["max_tokens"], "system": system, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        # Thinking / effort. Haiku 4.5 (last-resort fallback) takes neither "adaptive"
        # nor effort, so only the current-generation models get them.
        if model != CLAUDE_FAST_MODEL:
            if cfg.get("thinking"):
                kwargs["thinking"] = cfg["thinking"]
            if cfg.get("effort"):
                kwargs["extra_body"] = {"output_config": {"effort": cfg["effort"]}}
        try:
            texts = []
            for _turn in range(8):  # web tools may return pause_turn; continue up to 8 times
                # Streamed so large max_tokens never trips the SDK's request-time limit
                with client.messages.stream(**kwargs) as stream:
                    resp = stream.get_final_message()
                c, u = _usage_cost(resp.usage, model)
                total_cost += c
                for k in usage_tot:
                    usage_tot[k] += u.get(k, 0)
                texts.append(extract_text(resp))
                last_stop = getattr(resp, "stop_reason", "")
                if last_stop == "pause_turn":
                    messages.append({"role": "assistant", "content": resp.content})
                    continue
                break
            final_text = "\n".join(t for t in texts if t)
            model_used = model
            break
        except Exception as e:  # model fallback on 404 only; everything else propagates
            err = str(e)
            status = getattr(e, "status_code", None)
            if status == 404 or "not_found" in err or "404" in err:
                last_error = e
                continue
            _log.exception("GROW run failed for %s", ticker)
            return None, f"GROW run failed: {err[:300]}"

    if model_used is None:
        return None, f"No Claude model accessible with your API key. Last error: {last_error}"

    elapsed = time.time() - t0
    global LAST_RAW_TEXT
    LAST_RAW_TEXT = final_text  # kept for debugging a failed parse
    data = _extract_json_block(final_text)
    if not data or not isinstance(data, dict):
        _log.warning("GROW %s: no JSON block. stop_reason=%s, chars=%d, tail=%r",
                     ticker, last_stop, len(final_text), final_text[-300:])
        if last_stop == "max_tokens":
            return None, (f"GROW ran out of output budget before finishing (stop_reason=max_tokens after "
                          f"{usage_tot['output_tokens']} tokens). Try the run again or a deeper tier.")
        return None, "GROW finished but the machine-readable block could not be parsed. Try again."

    dur = data.get("durability") or {}
    ent = data.get("entry") or {}
    ladder = ent.get("ladder") or {}
    cls = data.get("classification") or {}
    cases = data.get("cases") or {}

    durability = _f(dur.get("score"))
    if durability is None:
        return None, "GROW output had no Durability score (rule 20) — run rejected. Try again."
    durability = max(0.0, min(100.0, durability))
    model_verdict = _normalise_verdict(ent.get("verdict"))
    price = _f(ent.get("price")) or _f((price_quote or {}).get("price")) or _f((info or {}).get("currentPrice"))
    buy_below = _f(ladder.get("buy_below"))
    strong_buy_below = _f(ladder.get("strong_buy_below"))
    fair_high = _f(ladder.get("fair_high"))
    reduce_above = _f(ladder.get("reduce_above")) or fair_high
    cagr = _f(ent.get("cagr_spot"))
    req = _f(ent.get("required_return"))
    excess = _f(ent.get("excess_pts"))
    if excess is None and cagr is not None and req is not None:
        excess = round((cagr - req) * 100, 1)
    stability = ent.get("stability") or {}
    verdict = model_verdict
    arithmetic_note = None

    # §8 is arithmetic: recompute verdict + ladder + stability from the model's own
    # inputs (central case, horizon, required return). The model's figures stay in
    # grow_json for the record; any disagreement is written into the uncertainties.
    central = _f(ent.get("central_value")) or _f((cases.get("base") or {}).get("price"))
    bull_price = _f((cases.get("bull") or {}).get("price"))
    resolved = resolve_entry(
        price, central, bull_price, cls.get("horizon_years"), req,
        caps=ent.get("caps"), ceilings=ent.get("ceilings"), integrity_level=dur.get("integrity_level"),
    )
    if resolved:
        if resolved["verdict"] != model_verdict:
            arithmetic_note = (
                f"Entry recomputed by arithmetic (§8.1): {central:,.2f} central value at {resolved['horizon_years']:.2f} years "
                f"from {price:,.2f} is {resolved['cagr_spot']*100:.1f}% a year against a {req*100:.1f}% bar "
                f"→ {resolved['verdict']}; the model had written {model_verdict}."
            )
        verdict = resolved["verdict"]
        cagr = resolved["cagr_spot"]
        excess = resolved["excess_pts"]
        strong_buy_below = resolved["ladder"]["strong_buy_below"]
        buy_below = resolved["ladder"]["buy_below"]
        fair_high = resolved["ladder"]["fair_high"]
        reduce_above = resolved["ladder"]["reduce_above"]
        stability = resolved["stability"]
        if resolved["bound"]:
            arithmetic_note = (arithmetic_note + " " if arithmetic_note else "") + "Bound by: " + "; ".join(resolved["bound"]) + "."

    one_reason = data.get("one_reason") or {}
    if isinstance(one_reason, str):
        one_reason = {"criterion": one_reason, "what_would_prove_it_false": ""}
    triggers = data.get("break_triggers") or []
    band = dur.get("band") or (
        "Exceptional" if durability >= 85 else "Strong" if durability >= 70 else
        "Conditional" if durability >= 55 else "Weak" if durability >= 40 else "Not durable"
    )
    thesis = f"Durability {durability:.0f} ({band}) · Entry {verdict}"
    if buy_below:
        thesis += f" · buy below {buy_below:,.2f}"
    if one_reason.get("criterion"):
        thesis += f" — {str(one_reason['criterion'])[:160]}"

    memo_md = _strip_json_block(final_text)
    confidence = str(data.get("confidence") or "").strip() or None
    conviction = ("HIGH" if confidence and "confident" in confidence.lower() and "reasonably" not in confidence.lower()
                  else "MEDIUM" if confidence and "reasonably" in confidence.lower() else "LOW")

    result = {
        # ── GROW fields ──
        "framework": GROW_VERSION,
        "durability": durability,
        "durability_band": band,
        "entry_verdict": verdict,
        "buy_below": buy_below,
        "strong_buy_below": strong_buy_below,
        "fair_high": fair_high,
        "reduce_above": reduce_above,
        "cagr_spot": cagr,
        "required_return": req,
        "excess_pts": excess,
        "price_at_run": price,
        "confidence": confidence,
        "memo_md": memo_md,
        "screen_only": bool(data.get("screen_only")) or tier == "screen",
        "classification": cls,
        "cases": cases,
        "stability": stability,
        "entry_resolved": resolved,
        "model_entry_verdict": model_verdict,
        "one_reason": one_reason,
        "break_triggers": triggers,
        "driving_inputs": data.get("driving_inputs") or [],
        "failed_peer": data.get("failed_peer"),
        "uncertainties": ([arithmetic_note] if arithmetic_note else []) + list(data.get("uncertainties") or []),
        "retrieval": data.get("retrieval") or {},
        "change_table": data.get("change_table") or [],
        "what_it_does": data.get("what_it_does") or "",
        "company": data.get("company") or (info or {}).get("longName") or "",
        # ── legacy-compatible fields (other pages read these) ──
        "rating": verdict,
        "score": durability,
        "archetype": cls.get("archetype") or "",
        "archetype_name": cls.get("archetype_name") or "",
        "conviction": conviction,
        "thesis": thesis,
        "env_net": None,
        "fair_value_base": buy_below,
        "fair_value_bear": strong_buy_below,
        "fair_value_bull": reduce_above,
        "upside_pct": round(cagr * 100, 1) if cagr is not None else None,   # expected return per year, %
        "score_breakdown": {str(c.get("n", i + 1)): c for i, c in enumerate(dur.get("criteria") or [])},
        "key_risks": [f"{t.get('metric')}: {t.get('threshold')} → {t.get('effect_on_durability')}" for t in triggers if isinstance(t, dict)],
        "key_catalysts": [],
        # ── run metadata ──
        "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        "model_used": tier,
        "model_id": model_used,
        "cost_estimate": round(total_cost, 4),
        "elapsed_seconds": round(elapsed, 1),
        "data_fields": data_fields,
        "data_quality_warning": "LOW" if (tier == "screen" or data_fields < 6) else None,
        **usage_tot,
    }
    result["full_response"] = {k: v for k, v in result.items() if k not in ("memo_md",)}
    result["full_response"]["grow_json"] = data
    return result, ""


def run_grow_batch(tickers: list, tier: str = "screen", info_map: dict = None,
                   price_map: dict = None, progress_callback=None) -> Dict[str, dict]:
    """Sequential batch (rate-limit friendly). Returns {ticker: result}."""
    info_map = info_map or {}
    price_map = price_map or {}
    results = {}
    total = len(tickers)
    for i, t in enumerate(tickers):
        if progress_callback:
            progress_callback(t, i, total)
        res, _err = run_grow(t, tier=tier, info=info_map.get(t, {}), price_quote=price_map.get(t))
        if res:
            results[t] = res
        if i < total - 1:
            time.sleep(0.5)
    return results
