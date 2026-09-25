"""
PROSPER v5.13.1 Engine
======================
Runs PROSPER v5.13.1 (prosper_framework/PROSPER v5.13.1 MODEL-AGNOSTIC.md) on one ticker and
returns the PROSPER CARD: a 0–100 score, one call (STRONG BUY · BUY · ACCUMULATE ON DIPS · HOLD ·
TRIM · SELL · AVOID), bear / base / bull over three years, the printed reward:risk ratio and the
action prices.

This replaced core/grow_engine.py (GROW v5.1) on 25-Sep-2026. GROW is archived under
docs/archive/grow_v5_1/ and its verdicts are superseded, never mapped (P9: "a different
framework's levels are not a prior run").

The split that made GROW trustworthy is kept
--------------------------------------------
Claude supplies the JUDGEMENT — the five dimension scores, the three cases and their anchors,
the integrity classification, the catalysts. Python supplies every NUMBER a decision reads, in
`resolve_card()`, and OVERRIDES the model's arithmetic:

  * the score Q from the dimension weights, compared with the band edges unrounded (§B3)
  * the ratio, exactly as P3 prints it: (bull − spot) ÷ (spot − stressed bear)
  * D5 clamped into the band its ratio implies; D4 capped by the P4 dilution test and
    docked by the P11 reporting-control flag; D2 held inside its AI-class ceiling (§B11)
  * the hard caps, down only: D5 <3, the D5-BUY-GATE, STRONG BUY ≥3×, F-INT, the Conduct
    Treatment, D2 <4 with AI-V/X, blow-off, the microcap kill-switch
  * the re-entry price, (bull + 2 × bear) ÷ 3, and the probability-weighted 36-month return

So a card imported from a chat window (scripts/prosper_import.py) and one produced through the
API cannot disagree on a number: both go through assemble_result().

Tiers (search budgets are the framework's own, §A "SEARCH BUDGETS")
  screen    provider data only, no web — provisional by construction
  delta     ≤6 searches against the prior card (needs a prior PROSPER run)
  standard  ≤12 searches — a new Core name
  full      Opus, ≤12 searches, plus the dense memo and the scorecard (`memo` + `detail`)

Position-blind (P1): holdings, cost basis and weights are never passed into the prompt.
"""

import json
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from core.framework_version import FRAMEWORK_VERSION, is_current
from core.settings import (
    CLAUDE_BEST_MODEL, CLAUDE_DEFAULT_MODEL, CLAUDE_FAST_MODEL,
    CLAUDE_MODEL_PRIORITY, extract_text, get_api_key,
)

_log = logging.getLogger("prosper.engine")

PROSPER_VERSION = FRAMEWORK_VERSION
FRAMEWORK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "prosper_framework")
FRAMEWORK_FILE = "PROSPER v5.13.1 MODEL-AGNOSTIC.md"
LAST_RAW_TEXT = ""  # raw model output of the most recent run (debugging aid)

# ─────────────────────────────────────────
# THE FRAMEWORK'S NUMBERS — kept in exact step with the .md by prosper_verify.py
# ─────────────────────────────────────────

# §B3 Core, §B9 Token (same weights)
CORE_WEIGHTS = {"d1": 0.25, "d2": 0.25, "d3": 0.20, "d4": 0.15, "d5": 0.15}
# §B6 Income / UAE / REIT / bank / utility
INCOME_WEIGHTS = {"d1": 0.10, "d2": 0.30, "d3": 0.15, "d4": 0.15, "d5": 0.15,
                  "d6": 0.10, "d7": 0.05}
# §B8 Microcap Stage 2 pillars
MICROCAP_WEIGHTS = {"p1": 0.20, "p2": 0.25, "p3": 0.18, "p4": 0.10, "p5": 0.12, "s6": 0.15}
# §B7 Distressed sleeve
DISTRESSED_WEIGHTS = {"s1": 0.40, "s2": 0.30, "s3": 0.30}

# §B3 bands — lower edge, compared UNROUNDED ("64.5 is HOLD, not BUY")
Q_BANDS = [(80.0, "STRONG BUY"), (65.0, "BUY"), (50.0, "HOLD"), (35.0, "TRIM"), (0.0, "SELL")]

# §B3 D5 — ratio floor → permitted score range
D5_BANDS = [(5.0, 9, 10), (3.0, 7, 8), (2.0, 5, 6), (1.0, 3, 4), (-math.inf, 0, 2)]

# §A REGIME OF RECORD — starter multiplier
REGIME_MULTIPLIER = {"Green": 1.00, "Low-Amber": 0.75, "Amber": 0.50, "High-Amber": 0.25, "Red": 0.00}

# §B11 — D2 ceiling by AI class; AI-A is a floor
AI_D2_CEILING = {"AI-P": 7, "AI-V": 5, "AI-X": 3}
AI_D2_FLOOR = {"AI-A": 8}

# The call scale, strongest first. Hard caps only ever move a call DOWN this list.
ACTION_SCALE = ["STRONG BUY", "BUY", "ACCUMULATE ON DIPS", "HOLD", "TRIM", "SELL", "AVOID"]
_RANK = {a: i for i, a in enumerate(ACTION_SCALE)}
BUYING_CALLS = ("STRONG BUY", "BUY", "ACCUMULATE ON DIPS")
REDUCING_CALLS = ("TRIM", "SELL", "AVOID")

ROUTES = {
    "CORE": "Core",
    "QOS": "Quality on sale (Core)",
    "INCOME": "Income / value lens",
    "MICROCAP": "Microcap lens",
    "DISTRESSED": "Distressed sleeve",
    "TOKEN": "Token / network lens",
}

DILUTION_CAGR_LIMIT = 0.10       # P4: >10%/yr over 3 years → D4 at most 4
QOS_MIN_DRAWDOWN_PCT = 40.0      # §B5 gate 2
CONDUCT_MIN_BREAK_WEIGHT = 0.10  # P10: break case weighted ≥10%
VALID_DAYS = 90                  # §A step 13
VALID_DAYS_SHORT = 60            # token / pre-revenue / microcap

# Per-1M-token prices (USD) used for the cost estimate shown in the UI
_PRICES = {
    CLAUDE_FAST_MODEL:    {"in": 1.00, "out": 5.00,  "cache_read": 0.10, "cache_write": 1.25},
    CLAUDE_DEFAULT_MODEL: {"in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    CLAUDE_BEST_MODEL:    {"in": 5.00, "out": 25.00, "cache_read": 0.50, "cache_write": 6.25},
}
_WEB_SEARCH_PRICE = 0.01   # per search request

# max_tokens must leave room for the model's own thinking (it is billed as output and competes
# with the card for the same ceiling — a GROW run once died at stop_reason=max_tokens having
# written 269 characters) PLUS the card PLUS the JSON block.
PROSPER_TIERS = {
    "screen": {
        "label": "Screen",
        "model": CLAUDE_DEFAULT_MODEL,
        "max_tokens": 10000,
        "thinking": {"type": "disabled"},
        "effort": None,
        "web": False,
        "max_searches": 0,
        "memo": False,
        "description": "Card from provider data only — no live searches, provisional (~$0.10/stock)",
        "est_cost": 0.10,
    },
    "delta": {
        "label": "Delta",
        "model": CLAUDE_DEFAULT_MODEL,
        "max_tokens": 24000,
        "thinking": {"type": "adaptive"},
        "effort": "high",
        "web": True,
        "max_searches": 6,
        "fetch_content_tokens": 18000,
        "memo": False,
        "description": "Re-run against the last card — ≤6 searches, change table printed (~$0.50/stock)",
        "est_cost": 0.50,
    },
    "standard": {
        "label": "Standard",
        "model": CLAUDE_DEFAULT_MODEL,
        "max_tokens": 32000,
        "thinking": {"type": "adaptive"},
        "effort": "high",
        "web": True,
        "max_searches": 12,
        "fetch_content_tokens": 18000,
        "memo": False,
        "description": "Full run for a new name — ≤12 searches, full 9-section card (~$1.00 and 3–6 min)",
        "est_cost": 1.00,
    },
    "full": {
        "label": "Full + memo",
        "model": CLAUDE_BEST_MODEL,
        "max_tokens": 48000,
        "thinking": {"type": "adaptive"},
        "effort": "high",
        "web": True,
        "max_searches": 12,
        "fetch_content_tokens": 30000,
        "memo": True,
        "description": "Opus, ≤12 searches, card plus the dense memo and scorecard (~$3.50 and 8–12 min)",
        "est_cost": 3.50,
    },
}
BATCH_MAX_SEARCHES = 6   # §A: "Batch — one macro/regime scan, then ≤6 per name"


# ─────────────────────────────────────────
# FRAMEWORK TEXT (cached in memory; sent as a cached system block)
# ─────────────────────────────────────────

@lru_cache(maxsize=1)
def load_framework_text() -> str:
    with open(os.path.join(FRAMEWORK_DIR, FRAMEWORK_FILE), "r", encoding="utf-8") as f:
        return f.read()


def framework_available() -> bool:
    return os.path.exists(os.path.join(FRAMEWORK_DIR, FRAMEWORK_FILE))


# ─────────────────────────────────────────
# OUTPUT CONTRACT
# ─────────────────────────────────────────

_JSON_CONTRACT = """
{
  "ticker": "AAPL",
  "company": "Apple Inc.",
  "line": "NASDAQ · USD · primary line (no ADR/local spread)",
  "no_rating_reason": null,
  "price": {"value": 231.50, "basis": "LAST CLOSE", "time": "2026-09-24 16:00 ET",
            "source": "snapshot [EXCHANGE]", "cross_check": "named second source, or null",
            "single_source": false},
  "week52_high": 260.10,
  "regime": {"state": "Amber",
             "inputs": {"vix": "...", "spx_vs_200dma": "...", "hy_oas": "...",
                        "real_10y": "...", "dollar": "...", "brent": "..."},
             "unavailable": []},
  "route": "CORE",
  "what_they_do": "2-3 plain sentences",
  "scores": {
    "d1": {"score": 8, "why": "..."},
    "d2": {"score": 8, "why": "..."},
    "d3": {"score": 6, "why": "..."},
    "d4": {"score": 7, "why": "... (the score BEFORE any reporting-control penalty)"},
    "d5": {"score": 6, "why": "..."},
    "d6": null,
    "d7": null
  },
  "microcap": null,
  "distressed": null,
  "dilution": {"shares_3y_ago": 15900000000, "shares_now": 15100000000, "years": 3,
               "source": "10-K cover pages FY2023 / FY2026"},
  "ai_class": "AI-N",
  "rr_gate": {"status": "UNCONFIRMED", "bonus": 0, "evidence": "..."},
  "qos": {"down_on_sentiment_not_fundamentals": false},
  "integrity": {"type": "NONE", "detail": "", "restatement_direction": null,
                "direction_source": null, "material_weakness": false,
                "litigation_search": "the P6 search string, and what it found"},
  "legal_cost_per_share": null,
  "cases": {
    "break": null,
    "bear": {"price": 180.0, "weight": 0.25, "why": "plain reason"},
    "base": {"price": 260.0, "weight": 0.50, "why": "plain reason"},
    "bull": {"price": 340.0, "weight": 0.25, "why": "plain reason"}
  },
  "horizon_label": "Sep-2029",
  "dividends_per_share_3y": 3.10,
  "anchors": [{"case": "bear", "revenue_or_ebitda": "...", "margin": "...",
               "exit_multiple": "...", "multiple_range": "own 3-yr range / named peers",
               "diluted_shares": "...", "source": "...", "date": "..."}],
  "change_table": [{"input": "...", "old": "...", "new": "...", "fact": "...", "doc": "...", "date": "..."}],
  "entry_driver": "FIRST RUN",
  "catalysts": [{"event": "...", "date": "30-Oct-2026", "impact": "what it proves or breaks"}],
  "action_prices": {"buy_zone_low": 190.0, "buy_zone_high": 205.0, "add": "$X or event",
                    "take_profit": [300.0, 320.0, 340.0], "walk_away": "price or fact"},
  "rating": "BUY",
  "do_this": "one line",
  "confidence": "Medium",
  "confidence_raise": "what would raise it",
  "why": {"for": "...", "against": "...", "tips": "..."},
  "prove_wrong": [{"fact": "a number the company reports", "effect": "what it does to the call"}],
  "unverified": "one line",
  "conviction_target_pct": 3,
  "pre_revenue": false
}
"""

_CONTRACT_NOTES = """Field rules for the JSON block:
- `route`: CORE, QOS, INCOME, MICROCAP, DISTRESSED or TOKEN (step 5 routing table).
- `scores`: 0-10 integers. d6/d7 only on INCOME (else null). On MICROCAP fill `microcap` =
  {"kill_switch": null or the switch that fired, "pillars": {"p1":..,"p2":..,"p3":..,"p4":..,"p5":..,"s6":..},
   "s6_lifting_weak_pillars": false} and still give d1-d5 your best reading. On DISTRESSED fill
  `distressed` = {"s1":..,"s2":..,"s3":..}.
- `integrity.type`: NONE, ACCOUNTS (P10 accounts → F-INT), CONDUCT (P10 Conduct Treatment) or
  REPORTING_CONTROL (P11 flag). `restatement_direction`: FLATTERING, CONSERVATIVE,
  RECLASSIFICATION or null. Under CONDUCT, `cases.break` is mandatory with weight ≥0.10 and
  `legal_cost_per_share` = {"bull":..,"base":..,"bear":..,"break":..} (already deducted in each price).
- `cases.*.price`: per-share value at the horizon in the listing currency; weights sum to 1.
- `rr_gate.status`: CONFIRMED, UNCONFIRMED, BLOW-OFF or N/A; `bonus` 2-4 only when CONFIRMED.
- `ai_class`: AI-A, AI-N, AI-P, AI-V or AI-X.
- `entry_driver`: FIRST RUN, UNCHANGED, FACT, PER-SHARE or METHOD (P9 entry line).
- `catalysts[].date`: DD-Mmm-YYYY from company IR, or "not yet announced" (P5).
- `rating`: STRONG BUY, BUY, ACCUMULATE ON DIPS, HOLD, TRIM, SELL or AVOID.
- `no_rating_reason`: null, unless reconciliation (step 4) is impossible — then say why and the
  app records the name as not rated (the other fields may be null).
- Rates and weights as decimals. Use null where a value genuinely does not exist."""

_APP_INSTRUCTIONS = """You are the PROSPER v5.13.1 engine running inside the Prosper investment app.
The complete framework is in the previous system block. Follow it exactly. Today is {today}.

PLATFORM ADAPTER (PART 0) — what this environment has
- Web search / page fetch: {retrieval_rule}
- Live market data: NO broker tool here. The price in the DATA SNAPSHOT comes from the app's own
  quote pipeline with its source and time; quote it with basis and time, tag it [EXCHANGE] (or
  [LOW CONF] if the snapshot says it is stale), and cross-check it once if you can search.
  Never quote a search-snippet price as [FACT]. Moving averages: only from daily closes you can
  actually see; otherwise say they could not be computed.
- Code execution: NO. The app recomputes Q, the ratio, D5, the caps, the re-entry price and the
  probability-weighted return in Python from YOUR inputs and overrides your arithmetic. Get the
  inputs right (scores, case prices, weights, integrity type, AI class); still show the P3
  formula with numbers in the card.
- Knowledge base: the prior card, when one exists, is supplied below as PRIOR RUN. None supplied
  means this is a first run — say so in the change table (P9).
- File write: NO — and not needed. The app saves the card and the anchor log itself (P7). Do NOT
  output the cards file as a code block.
- Portfolio: you are given no holding, cost basis or weight (P1). Do not ask for one; there is no
  `position` add-on in this environment.
- Regime of record (P8): {regime_rule}

OTHER RULES FOR THIS ENVIRONMENT
1. Trigger: the user message is `Prosper <TICKER>` or `delta <TICKER>`. Run THE RUN, steps 1-13.
2. The DATA SNAPSHOT has two parts that do NOT carry equal weight. A section headed
   "SEC EDGAR XBRL — PRIMARY FILING DATA" is as-filed XBRL with accession numbers: treat it as a
   named primary document (cite the accession number) and do not re-retrieve those figures —
   spend searches on what XBRL cannot carry (guidance, IR earnings dates, litigation, estimate
   revisions, competitive position). Everything below the divider is aggregator data:
   confirmation only, never the sole basis of a number.
3. If the ticker could map to more than one listing, take the one in the snapshot, name the
   alternatives in section 9, and continue — this environment cannot stop and ask.
4. All prices in the listing currency shown in the snapshot.
5. P9 anchor lock: where a PRIOR RUN is supplied, carry every anchor that no named company fact
   has moved. The share price is never a fact. Print the change table even when nothing changed.

OUTPUT — TWO PARTS, IN THIS ORDER
PART 1 — {memo_rule}
PART 2 — a single fenced ```json block, the LAST thing in your reply, matching this shape exactly
(all keys present):
{contract}
{notes}
"""

_RETRIEVAL_WEB = (
    "YES — web_search and web_fetch, budget about {n} searches (§A search budgets; the mandatory "
    "scans — price cross-check, news, R1-E reconciliation, estimate revisions, the P6 litigation "
    "search — are never skipped to hit the budget). Primary documents first: the filing system, "
    "company IR (earnings dates from IR only, P5), then named sources; aggregators confirm only."
)
_RETRIEVAL_SCREEN = (
    "NO — this is a `screen` run. Work only from the DATA SNAPSHOT and what you already know; tag "
    "everything not in the snapshot [LOW CONF]. If the snapshot lacks a price or the latest results, "
    "set `no_rating_reason` rather than rate (PART 0). Otherwise produce a provisional card, set "
    "confidence to Low, and list in section 9 every mandatory scan you could not run (news, IR "
    "catalyst dates, litigation, estimate revisions)."
)
_REGIME_WEB = ("search FRED by series ID (DFII10, DTWEXBGS, DCOILBRENTEU, BAMLH0A0HYM2) and "
               "Cboe/S&P official pages for VIX and the S&P 500; never web-triangulate. Print the "
               "five inputs and the state.")
_REGIME_SCREEN = ("no live series are reachable on a screen run — give your best state, list every "
                  "input under `regime.unavailable`, and say so in section 9.")


def _system_blocks(tier: str, max_searches: int = None, has_edgar: bool = False,
                   regime_hint: dict = None) -> List[dict]:
    cfg = PROSPER_TIERS[tier]
    n = max_searches if max_searches is not None else cfg["max_searches"]
    retrieval_rule = _RETRIEVAL_WEB.format(n=n) if cfg["web"] else _RETRIEVAL_SCREEN
    if has_edgar:
        retrieval_rule += (" The statement-level figures are ALREADY SUPPLIED as as-filed SEC XBRL "
                           "in the snapshot, with accession numbers — do not re-retrieve them.")
    if regime_hint and regime_hint.get("state"):
        regime_rule = ("ALREADY ESTABLISHED for this batch (one macro scan per batch, §A): "
                       f"{json.dumps(regime_hint, default=str)[:900]}. Use it; do not re-scan.")
    else:
        regime_rule = _REGIME_WEB if cfg["web"] else _REGIME_SCREEN
    if cfg.get("memo"):
        memo_rule = ("the PROSPER CARD (§B13, all 9 sections, PS order, plain English), then the "
                     "`memo` (§B13 dense memo, ≤2,000 words) and the `detail` scorecard.")
    else:
        memo_rule = ("the PROSPER CARD exactly as the §B13 template lays it out — all 9 sections, "
                     "plain English, no codes, tags inline on numbers. No memo.")
    instructions = _APP_INSTRUCTIONS.format(
        today=datetime.now().strftime("%d-%b-%Y"), retrieval_rule=retrieval_rule,
        regime_rule=regime_rule, memo_rule=memo_rule,
        contract=_JSON_CONTRACT.strip(), notes=_CONTRACT_NOTES,
    )
    return [
        {"type": "text", "text": load_framework_text(), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": instructions},
    ]


# ─────────────────────────────────────────
# DATA SNAPSHOT
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
    """Compact multi-year P&L / cash-flow / balance-sheet lines from the aggregator (if available)."""
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


def _price_line(price_quote: dict, info: dict) -> Tuple[Optional[float], str]:
    """The price, with the basis and time P2 asks to be stated."""
    pq = price_quote or {}
    price = pq.get("price") or info.get("currentPrice") or info.get("regularMarketPrice")
    if not price:
        return None, ""
    src = pq.get("source") or ("aggregator info" if not pq else "prosper price cache")
    bits = [f"source {src}"]
    if pq.get("latency"):
        bits.append(f"basis {pq['latency']}")
    ts = pq.get("fetched_at")
    try:
        if ts and float(ts) > 1e9:
            bits.append("fetched " + datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M"))
    except (TypeError, ValueError):
        pass
    if pq.get("asof"):
        bits.append(f"as of {pq['asof']}")
    if pq.get("quote_currency"):
        bits.append(f"currency {pq['quote_currency']}")
    return price, f"Price: {price} ({'; '.join(bits)}) — the app's quote pipeline, not a broker feed"


def build_data_snapshot(ticker: str, info: dict = None, price_quote: dict = None,
                        edgar: dict = None) -> Tuple[str, int]:
    """Return (snapshot_text, data_fields).

    Two tiers of evidence, kept visibly separate. When `edgar` is supplied it holds as-filed XBRL
    figures with accession numbers — a named primary document — not the aggregator data that
    makes up the rest of this block. If the model is told as-filed XBRL is aggregator data it
    re-fetches it, and the entire saving evaporates.
    """
    info = info or {}
    lines = [f"TICKER (as held in Prosper): {ticker}"]
    lines.append(f"Snapshot taken: {datetime.now().strftime('%Y-%m-%d %H:%M')} local time")
    lines.append(f"Company (aggregator): {info.get('longName') or info.get('shortName') or 'n/a'}")
    lines.append(f"Exchange: {info.get('exchange', 'n/a')} | Currency: {info.get('currency') or info.get('financialCurrency') or 'n/a'} "
                 f"| Country: {info.get('country', 'n/a')} | Quote type: {info.get('quoteType', 'EQUITY')}")
    lines.append(f"Sector: {info.get('sector', 'n/a')} | Industry: {info.get('industry', 'n/a')}")

    _price, pline = _price_line(price_quote, info)
    if pline:
        lines.append(pline)
    if info.get("marketCap"):
        lines.append(f"Market cap: {_fmt_money(info['marketCap'])} | Enterprise value: {_fmt_money(info.get('enterpriseValue'))}")
    if info.get("sharesOutstanding"):
        lines.append(f"Shares outstanding (aggregator — confirm from the filing cover page, P4): {_fmt_money(info['sharesOutstanding'])}")

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
                     f"consensus '{info.get('recommendationKey', 'n/a')}' — input to the above-Street-target flag (§B4)")
    hi, lo = info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow")
    if hi and lo:
        lines.append(f"52-week range: {lo} – {hi}")

    try:
        from core.finnhub_client import _fetch_finnhub_analyst
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

    if edgar and edgar.get("text"):
        lines.insert(0, edgar["text"])
        lines.insert(1, "")
        lines.insert(2, "─" * 78)
        lines.insert(3, "Everything BELOW this line is aggregator data — confirmation only, "
                        "never the quoted number.")
        lines.insert(4, "─" * 78)

    data_fields = sum(1 for l in lines if ":" in l)
    return "\n".join(lines), data_fields


# ─────────────────────────────────────────
# TOOLS
# ─────────────────────────────────────────

def _web_tools_for(model: str, max_searches: int, content_tokens: int = 18000) -> List[dict]:
    """Server-side web tools. `content_tokens` caps how much of each fetched page is pulled in —
    the single largest cost lever (measured on GROW: 25 fetches × 40k tokens ≈ 1M input tokens)."""
    if max_searches <= 0:
        return []
    if model == CLAUDE_FAST_MODEL:
        return [
            {"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches},
            {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": max_searches,
             "max_content_tokens": min(content_tokens, 30000)},
        ]
    return [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_searches,
         "max_content_tokens": content_tokens},
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
        start = text.rfind("\n{")
        if start != -1:
            candidates.append(text[start:].strip())
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            try:
                return json.loads(re.sub(r",\s*([}\]])", r"\1", c))
            except json.JSONDecodeError:
                continue
    return None


def _strip_json_block(text: str) -> str:
    """The card/memo markdown = everything before the final JSON fence, minus the model's
    between-search narration ("I'll start by pulling the 10-K…") before the card begins."""
    m = list(re.finditer(r"```(?:json)?\s*\{", text or ""))
    memo = text[: m[-1].start()].rstrip() if m else (text or "").strip()
    starts = [x.start() for x in (re.search(r"^#{1,3} ", memo, flags=re.M),
                                  re.search(r"^═{5,}", memo, flags=re.M)) if x]
    if starts and min(starts) > 0:
        memo = memo[min(starts):]
    return memo.strip()


def _f(v) -> Optional[float]:
    try:
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, str):
            v = v.replace(",", "").replace("$", "").strip()
        f = float(v)
        return None if (f != f or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _int_score(v) -> Optional[float]:
    """A 0-10 dimension score from either `8` or `{"score": 8, ...}`."""
    if isinstance(v, dict):
        v = v.get("score")
    f = _f(v)
    return None if f is None else max(0.0, min(10.0, f))


def normalise_call(v) -> str:
    s = re.sub(r"\s+", " ", str(v or "").strip().upper().replace("_", " ").replace("-", " "))
    aliases = {"ACCUMULATE": "ACCUMULATE ON DIPS", "ACCUMULATE ON WEAKNESS": "ACCUMULATE ON DIPS",
               "HOLD/WATCHLIST": "HOLD", "HOLD / WATCHLIST": "HOLD", "WATCHLIST": "HOLD",
               "SELL/AVOID": "SELL", "SELL / AVOID": "SELL", "EXIT": "SELL", "SELL/EXIT": "SELL",
               "STRONG SELL": "SELL", "REDUCE": "TRIM"}
    s = aliases.get(s, s)
    return s if s in _RANK else ""


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
# THE RESOLVER — arithmetic, not judgement (deterministic, in Python)
# ─────────────────────────────────────────

def band_for(q: float) -> str:
    """§B3 band, compared with the edges UNROUNDED."""
    for edge, word in Q_BANDS:
        if q >= edge:
            return word
    return "SELL"


def _band_index(q: float) -> int:
    for i, (edge, _w) in enumerate(Q_BANDS):
        if q >= edge:
            return i
    return len(Q_BANDS) - 1


def d5_range(ratio: Optional[float]) -> Tuple[int, int]:
    if ratio is None:
        return (0, 10)
    for floor, lo, hi in D5_BANDS:
        if ratio >= floor:
            return (lo, hi)
    return (0, 2)


def reward_risk(bull: float, spot: float, bear: float) -> Optional[float]:
    """P3, exactly: (bull − spot) ÷ (spot − stressed bear). +inf when spot is at or below the
    stressed bear (nothing to lose to it); None when an input is missing."""
    if bull is None or spot is None or bear is None or spot <= 0:
        return None
    downside = spot - bear
    if downside <= 0:
        return math.inf
    return (bull - spot) / downside


def price_for_ratio(bull: float, bear: float, k: float) -> Optional[float]:
    """The spot at which the P3 ratio equals k: (bull + k × bear) ÷ (1 + k).
    k=2 is the D5 gate's re-entry line, (bull + 2 × bear) ÷ 3."""
    if bull is None or bear is None:
        return None
    return (bull + k * bear) / (1.0 + k)


def _fmt_ratio(r: Optional[float]) -> str:
    if r is None:
        return "—"
    if math.isinf(r):
        return "no downside to the bear"
    return f"{r:.2f}×"


def _cap(call: str, ceiling: str) -> str:
    return ACTION_SCALE[max(_RANK[call], _RANK[ceiling])]


def _parse_catalyst_date(s) -> Optional[datetime]:
    s = str(s or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%B-%Y", "%b %d, %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def resolve_card(data: dict, spot: float, *, run_date: datetime = None) -> dict:
    """Recompute every number a decision reads from the model's own inputs.

    Returns a dict with the final call and a list of `gates` (what bound, in plain words, and
    what releases it) and `adjustments` (every place Python changed a model input, and why).
    Never raises on a malformed payload: missing inputs are reported, not invented.
    """
    run_date = run_date or datetime.now()
    adjustments: List[str] = []
    gates: List[dict] = []
    flags: List[str] = []

    route = str(data.get("route") or "CORE").strip().upper().replace(" ", "_")
    if route not in ROUTES:
        adjustments.append(f"route {route!r} is not one the framework defines — scored as CORE")
        route = "CORE"

    integ = data.get("integrity") or {}
    itype = str(integ.get("type") or "NONE").strip().upper().replace("-", "_").replace(" ", "_")
    direction = str(integ.get("restatement_direction") or "").strip().upper()
    # P11: a restatement whose direction is not verifiable from a named source is FLATTERING.
    if itype == "REPORTING_CONTROL":
        if direction == "FLATTERING":
            adjustments.append("P11: the restatement flattered the original accounts — that is an "
                               "accounts matter (F-INT), not a reporting-control flag")
            itype = "ACCOUNTS"
        elif not str(integ.get("direction_source") or "").strip():
            adjustments.append("P11: no named source for the restatement's direction — treated as "
                               "FLATTERING until verified, so F-INT applies")
            itype = "ACCOUNTS"
    conduct = itype == "CONDUCT"
    accounts = itype in ("ACCOUNTS", "F_INT", "FINT")
    reporting_flag = itype == "REPORTING_CONTROL"

    # ── cases ──
    cases_in = data.get("cases") or {}
    cases = {}
    for key in ("break", "bear", "base", "bull"):
        c = cases_in.get(key)
        if isinstance(c, dict) and _f(c.get("price")) is not None:
            cases[key] = {"price": _f(c.get("price")), "weight": _f(c.get("weight")),
                          "why": str(c.get("why") or c.get("what_must_be_true") or "")}
    if conduct and "break" not in cases:
        flags.append("Conduct Treatment needs a break case (P10) and the run supplied none — "
                     "the bear case stands in as the downside")
    bear = (cases.get("bear") or {}).get("price")
    base = (cases.get("base") or {}).get("price")
    bull = (cases.get("bull") or {}).get("price")
    brk = (cases.get("break") or {}).get("price")
    stressed_bear = brk if (conduct and brk is not None) else bear
    if bull is not None and bear is not None and bull < bear:
        flags.append(f"the bull case ({bull:,.2f}) sits below the bear case ({bear:,.2f}) — check the cases")

    ratio = reward_risk(bull, spot, stressed_bear)
    reentry = price_for_ratio(bull, stressed_bear, 2.0)
    line_3x = price_for_ratio(bull, stressed_bear, 3.0)
    line_1x = price_for_ratio(bull, stressed_bear, 1.0)

    # ── probability weights (P10: break ≥10% under the Conduct Treatment) ──
    present = [k for k in ("break", "bear", "base", "bull") if k in cases and not (k == "break" and not conduct)]
    weights = {k: cases[k]["weight"] for k in present}
    if present and any(w is None for w in weights.values()):
        default = {"bear": 0.25, "base": 0.50, "bull": 0.25, "break": 0.10}
        weights = {k: (w if w is not None else default[k]) for k, w in weights.items()}
        adjustments.append("case weights missing — assumed 25/50/25 (break 10%)")
    if conduct and "break" in weights and weights["break"] < CONDUCT_MIN_BREAK_WEIGHT:
        others = sum(v for k, v in weights.items() if k != "break") or 1.0
        scale = (1.0 - CONDUCT_MIN_BREAK_WEIGHT) / others
        weights = {k: (CONDUCT_MIN_BREAK_WEIGHT if k == "break" else v * scale) for k, v in weights.items()}
        adjustments.append("P10: break case raised to a 10% weight, taken from the other cases")
    tot = sum(v for v in weights.values() if v and v > 0)
    if tot > 0:
        if abs(tot - 1.0) > 0.011:
            adjustments.append(f"case weights summed to {tot:.2f} — rescaled to 1")
        weights = {k: max(0.0, v) / tot for k, v in weights.items()}
    divs = _f(data.get("dividends_per_share_3y")) or 0.0
    pw_return = None
    if spot and weights:
        pw_return = sum(w * ((cases[k]["price"] + divs) / spot - 1.0) for k, w in weights.items())
    pw_return_pa = ((1.0 + pw_return) ** (1.0 / 3.0) - 1.0) if (pw_return is not None and pw_return > -1) else None

    # ── dimension scores ──
    scores_in = data.get("scores") or {}
    raw = {k: _int_score(scores_in.get(k)) for k in ("d1", "d2", "d3", "d4", "d5", "d6", "d7")}
    final = dict(raw)

    # §B11 — D2 inside the AI-class ceiling / floor
    ai = str(data.get("ai_class") or "AI-N").strip().upper().replace("_", "-")
    if final["d2"] is not None:
        if ai in AI_D2_CEILING and final["d2"] > AI_D2_CEILING[ai]:
            adjustments.append(f"moat score {final['d2']:g} held to the {ai} ceiling of {AI_D2_CEILING[ai]}")
            final["d2"] = float(AI_D2_CEILING[ai])
        if ai in AI_D2_FLOOR and final["d2"] < AI_D2_FLOOR[ai]:
            adjustments.append(f"moat score {final['d2']:g} raised to the {ai} floor of {AI_D2_FLOOR[ai]}")
            final["d2"] = float(AI_D2_FLOOR[ai])

    # P4 — chronic dilution, objectively
    dil = data.get("dilution") or {}
    s0, s1, yrs = _f(dil.get("shares_3y_ago")), _f(dil.get("shares_now")), _f(dil.get("years")) or 3.0
    dilution_cagr = None
    if s0 and s1 and s0 > 0 and yrs > 0:
        dilution_cagr = (s1 / s0) ** (1.0 / yrs) - 1.0
        if dilution_cagr > DILUTION_CAGR_LIMIT and final["d4"] is not None and final["d4"] > 4:
            adjustments.append(f"P4: diluted shares grew {dilution_cagr*100:.1f}% a year "
                               f"({s0:,.0f} → {s1:,.0f}) — capital score capped at 4")
            final["d4"] = 4.0
    # P11 — reporting-control flag: −1, or −2 with a material weakness
    if reporting_flag and final["d4"] is not None:
        pen = 2.0 if integ.get("material_weakness") else 1.0
        final["d4"] = max(0.0, final["d4"] - pen)
        adjustments.append(f"P11 reporting-control flag: capital score −{pen:g}"
                           + (" (material weakness)" if pen == 2 else ""))

    # D5 — clamped into the band its printed ratio implies
    if ratio is not None and route not in ("DISTRESSED",):
        lo, hi = d5_range(ratio)
        if final["d5"] is None:
            final["d5"] = float(lo)
            adjustments.append(f"asymmetry score set to {lo} from the {_fmt_ratio(ratio)} ratio")
        elif not (lo <= final["d5"] <= hi):
            new = float(min(max(final["d5"], lo), hi))
            adjustments.append(f"asymmetry score {final['d5']:g} moved to {new:g}: the printed ratio "
                               f"is {_fmt_ratio(ratio)}, which scores {lo}–{hi}")
            final["d5"] = new

    # ── Q ──
    missing = []
    micro = data.get("microcap") or {}
    distressed = data.get("distressed") or {}
    if route == "MICROCAP" and isinstance(micro, dict) and micro.get("pillars"):
        pil = {k: _int_score((micro.get("pillars") or {}).get(k)) for k in MICROCAP_WEIGHTS}
        missing = [k for k, v in pil.items() if v is None]
        q = sum(MICROCAP_WEIGHTS[k] * (pil[k] or 0.0) for k in MICROCAP_WEIGHTS) * 10.0
        weights_used = "MICROCAP"
    elif route == "DISTRESSED" and isinstance(distressed, dict) and any(distressed.get(k) is not None for k in DISTRESSED_WEIGHTS):
        sv = {k: _int_score(distressed.get(k)) for k in DISTRESSED_WEIGHTS}
        missing = [k for k, v in sv.items() if v is None]
        q = sum(DISTRESSED_WEIGHTS[k] * (sv[k] or 0.0) for k in DISTRESSED_WEIGHTS) * 10.0
        weights_used = "DISTRESSED"
    else:
        w = INCOME_WEIGHTS if route == "INCOME" else CORE_WEIGHTS
        missing = [k for k in w if final.get(k) is None]
        q = sum(w[k] * (final.get(k) or 0.0) for k in w) * 10.0
        weights_used = "INCOME" if route == "INCOME" else "CORE"
        if route in ("MICROCAP", "DISTRESSED"):
            adjustments.append(f"{ROUTES[route]} scores missing — scored on the Core weights")
    if missing:
        flags.append("dimension score(s) missing and counted as 0: " + ", ".join(missing))
    q_raw = q

    # §B4 — RR gate: a bounded +2 to +4 bonus, never more than one band
    rr = data.get("rr_gate") or {}
    rr_status = str(rr.get("status") or "N/A").strip().upper()
    bonus = 0.0
    if rr_status == "CONFIRMED" and route in ("CORE", "QOS", "INCOME", "TOKEN"):
        bonus = min(4.0, max(2.0, _f(rr.get("bonus")) or 2.0))
        if _band_index(q + bonus) < _band_index(q) - 1:          # lower index = higher band
            bonus = 0.0
            adjustments.append("re-rating bonus withheld: it would have lifted the name more than one band")
    q = min(100.0, q + bonus)

    call = band_for(q)
    base_call = call

    # §B5 — Quality on Sale: all five → STRONG BUY regardless of Q
    week_hi = _f(data.get("week52_high"))
    pct_off = ((week_hi - spot) / week_hi * 100.0) if (week_hi and spot and week_hi > 0) else None
    catalysts = [c for c in (data.get("catalysts") or []) if isinstance(c, dict)]
    dated = [c for c in catalysts if _parse_catalyst_date(c.get("date"))]
    qos_checks = {
        "moat intact (D2 ≥7)": (final["d2"] or 0) >= 7,
        "down >40% from the 52-week high": pct_off is not None and pct_off > QOS_MIN_DRAWDOWN_PCT,
        "on sentiment, not fundamentals": bool((data.get("qos") or {}).get("down_on_sentiment_not_fundamentals")),
        "not distressed": route != "DISTRESSED",
        "asymmetry ≥5×": ratio is not None and ratio >= 5.0,
        "a dated catalyst": bool(dated),
    }
    qos = route in ("CORE", "QOS") and all(qos_checks.values())
    if qos and _RANK[call] > _RANK["STRONG BUY"]:
        adjustments.append("Quality on Sale: all five gates fire — STRONG BUY regardless of the score")
        call = "STRONG BUY"
    if route == "QOS" and not qos:
        failed = [k for k, v in qos_checks.items() if not v]
        adjustments.append("routed as Quality on Sale but not every gate fires (" + "; ".join(failed)
                           + ") — rated on the Core score")

    def bind(ceiling: str, rule: str, why: str, release: str = ""):
        nonlocal call
        new = _cap(call, ceiling)
        if new != call:
            gates.append({"rule": rule, "from": call, "to": new, "why": why, "release": release})
            call = new

    rb, re2 = (f"{reentry:,.2f}" if reentry is not None else "—"), reentry
    # Hard caps — after Q, override the band, DOWN only (§A HARD CAPS)
    if route != "DISTRESSED":
        d5 = final.get("d5")
        if d5 is not None and d5 < 3:
            bind("HOLD", "D5 <3",
                 f"less than $1 to gain for each $1 at risk ({_fmt_ratio(ratio)})",
                 f"price at or below {line_1x:,.2f}, where the ratio reaches 1×" if line_1x else "")
        if ratio is None or ratio < 2.0:
            bind("ACCUMULATE ON DIPS", "D5-BUY-GATE",
                 f"a buy needs at least $2 of upside per $1 of downside; today it is {_fmt_ratio(ratio)}",
                 f"price at or below {rb} = (bull + 2 × bear) ÷ 3" if re2 is not None else
                 "a complete bear/bull pair to compute the ratio")
        if call == "STRONG BUY" and (ratio is None or ratio < 3.0):
            bind("BUY", "STRONG BUY needs ≥3×",
                 f"strong buy needs $3 of upside per $1 of downside; today it is {_fmt_ratio(ratio)}",
                 f"price at or below {line_3x:,.2f}" if line_3x is not None else "")
    if rr_status == "BLOW-OFF":
        bind("HOLD", "OR-5 blow-off", "a vertical move above fair value — scale out into the spike, don't add",
             "the spike cools and estimates catch up")
    if ai == "AI-X":
        bind("HOLD", "AI-X", "over 60% of revenue is exposed to AI substitution", "a successful pivot, re-tested")
    if (final["d2"] is not None and final["d2"] < 4) and ai in ("AI-V", "AI-X"):
        bind("HOLD", "D2 <4 and AI-V/X", "a weak moat in a business AI can replace", "")
    if route == "MICROCAP" and micro.get("s6_lifting_weak_pillars"):
        bind("HOLD", "Microcap S6", "sentiment is doing the lifting for a weak product/traction case", "")
    if conduct:
        bind("HOLD", "Conduct Treatment",
             "an open conduct/compliance matter — hold, don't add, until the regulator resolves it",
             "a settlement with no monitor or business restriction")
        if ratio is not None and ratio < 1.0:
            bind("SELL", "Conduct break-case ratio <1×",
                 f"with the break case as the downside the ratio is {_fmt_ratio(ratio)} — sell, not hold",
                 "")
    if accounts:
        bind("SELL", "F-INT",
             "an evidence-backed accounting-integrity problem (reported numbers in question)",
             "a credible verifiable rebuttal, dismissal, or clean audited accounts after the probe")
    if route == "MICROCAP" and micro.get("kill_switch"):
        bind("AVOID", "Microcap kill-switch", f"kill-switch fired: {micro.get('kill_switch')}", "")

    # ── deterministic ladder the rest of the app reads ──
    ap = data.get("action_prices") or {}
    bz_lo, bz_hi = _f(ap.get("buy_zone_low")), _f(ap.get("buy_zone_high"))
    tps = [x for x in (_f(t) for t in (ap.get("take_profit") or [])) if x is not None]
    buy_below = reentry
    if bz_hi is not None and (buy_below is None or bz_hi < buy_below):
        buy_below = bz_hi
    fair_high = tps[0] if tps else base

    # §B13 consistency checks
    if call in ("STRONG BUY", "BUY") and bz_lo is not None and bz_lo > spot:
        flags.append(f"a buy call should name a buy zone at or below today's price; the zone starts at {bz_lo:,.2f}")
    if not dated:
        flags.append("no catalyst carries a date (P5) — 'execution' is not a catalyst")
    if not (data.get("prove_wrong") or []):
        flags.append("section 8 names no reported number that would prove the call wrong")

    regime = data.get("regime") or {}
    state = str(regime.get("state") or "").strip()
    state = next((s for s in REGIME_MULTIPLIER if s.lower() == state.lower()), state or None)
    mult = REGIME_MULTIPLIER.get(state) if state else None
    target = _f(data.get("conviction_target_pct"))
    starter = round(target * mult, 2) if (target is not None and mult is not None) else None

    short = route in ("MICROCAP", "TOKEN") or bool(data.get("pre_revenue"))
    valid_until = (run_date + timedelta(days=VALID_DAYS_SHORT if short else VALID_DAYS)).strftime("%Y-%m-%d")

    return {
        "route": route, "weights_used": weights_used,
        "scores_raw": raw, "scores": final,
        "q_raw": round(q_raw, 1), "rr_status": rr_status, "rr_bonus": bonus,
        "q": round(q, 1), "q_unrounded": q, "band_call": base_call, "call": call,
        "gates": gates, "adjustments": adjustments, "flags": flags,
        "ai_class": ai, "integrity_type": itype, "conduct": conduct, "accounts": accounts,
        "reporting_flag": reporting_flag,
        "spot": spot, "bear": bear, "base": base, "bull": bull, "break": brk,
        "stressed_bear": stressed_bear, "ratio": ratio, "ratio_text": _fmt_ratio(ratio),
        "reentry": reentry, "line_3x": line_3x, "line_1x": line_1x,
        "weights": weights, "dividends_per_share_3y": divs,
        "pw_return": pw_return, "pw_return_pa": pw_return_pa,
        "pct_off_high": pct_off, "qos": qos, "qos_checks": qos_checks,
        "dilution_cagr": dilution_cagr,
        "buy_zone_low": bz_lo, "buy_zone_high": bz_hi, "take_profit": tps,
        "buy_below": buy_below, "fair_high": fair_high,
        "regime_state": state, "regime_multiplier": mult,
        "conviction_target_pct": target, "starter_pct": starter,
        "valid_until": valid_until,
    }


def ratio_formula(r: dict, ccy: str = "") -> str:
    """P3, printed with the numbers substituted."""
    b, s, sb = r.get("bull"), r.get("spot"), r.get("stressed_bear")
    if b is None or s is None or sb is None:
        return "reward:risk cannot be computed — a case price is missing"
    up, down = b - s, s - sb
    txt = f"({b:,.2f} − {s:,.2f}) ÷ ({s:,.2f} − {sb:,.2f}) = {up:,.2f} ÷ {down:,.2f} = {r.get('ratio_text')}"
    return txt


def _default_do_this(r: dict) -> str:
    """The section-2 instruction when Python's call differs from the model's words."""
    c = r["call"]
    re2 = r.get("reentry")
    if c in ("STRONG BUY", "BUY"):
        top = r.get("buy_zone_high") or r.get("spot")
        return f"Buy now up to {top:,.2f}" if top else "Buy"
    if c == "ACCUMULATE ON DIPS":
        return f"Wait for {re2:,.2f} or lower" if re2 else "Wait for a lower price"
    if c == "HOLD":
        return "Hold, don't add" if (r.get("conduct") or r.get("ratio") is None or (r.get("ratio") or 0) < 2) else "Hold"
    if c == "TRIM":
        tp = (r.get("take_profit") or [None])[0]
        return f"Sell a quarter at {tp:,.2f}" if tp else "Trim"
    if c == "SELL":
        return "Sell"
    return "Avoid — do not buy"


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

def _prior_slim(prior: dict) -> Optional[dict]:
    """The prior card for P9, or None when the prior row was written by another framework."""
    if not prior or not is_current(prior.get("framework")):
        return None
    full = prior.get("full_response") or {}
    if isinstance(full, str):
        try:
            full = json.loads(full)
        except Exception:
            full = {}
    pj = (full or {}).get("prosper_json") or {}
    res = (full or {}).get("resolved") or {}
    slim = {k: pj.get(k) for k in ("cases", "anchors", "scores", "route", "ai_class", "integrity",
                                   "action_prices", "catalysts", "dilution", "rr_gate") if pj.get(k)}
    slim["analysis_date"] = prior.get("analysis_date")
    slim["price_at_run"] = prior.get("price_at_run")
    slim["q"] = res.get("q")
    slim["call"] = res.get("call")
    slim["reentry"] = res.get("reentry")
    return slim


def assemble_result(ticker: str, data: dict, memo_text: str = "", *, tier: str = "standard",
                    info: dict = None, price_quote: dict = None, model_id: str = "",
                    cost: float = 0.0, elapsed: float = 0.0, data_fields: int = 0,
                    usage: dict = None, prior: dict = None) -> Tuple[Optional[dict], str]:
    """Turn a parsed PROSPER JSON block into the DB-ready result.

    Shared by every producer — the API path in run_prosper() and the chat-window import in
    scripts/prosper_import.py — so the resolver runs HERE and the two cannot drift.
    """
    info = info or {}
    if not isinstance(data, dict):
        return None, "PROSPER output had no machine-readable block — run rejected."
    nrr = data.get("no_rating_reason")
    if nrr:
        return None, f"Not rated — {str(nrr)[:300]} (step 4: no reconciliation = no rating)."

    price_obj = data.get("price") if isinstance(data.get("price"), dict) else {"value": data.get("price")}
    spot = _f((price_quote or {}).get("price")) or _f(price_obj.get("value")) or _f(info.get("currentPrice"))
    if not spot or spot <= 0:
        return None, "No price to rate against (step 1) — run rejected."
    micro_kill = bool(((data.get("microcap") or {}).get("kill_switch")))
    cases = data.get("cases") or {}
    if not micro_kill and not all(_f((cases.get(k) or {}).get("price")) is not None for k in ("bear", "base", "bull")):
        return None, "The run did not produce a bear, base and bull price (step 9) — run rejected."

    data = dict(data)
    if _f(data.get("week52_high")) is None and _f(info.get("fiftyTwoWeekHigh")) is not None:
        data["week52_high"] = _f(info.get("fiftyTwoWeekHigh"))
    r = resolve_card(data, spot)
    model_call = normalise_call(data.get("rating"))
    call = r["call"]
    uncertainties = []
    if model_call and model_call != call:
        uncertainties.append(
            f"Call recomputed by the framework's arithmetic: score {r['q']:.1f}, ratio "
            f"{r['ratio_text']} → {call}; the model had written {model_call}.")
    uncertainties += [f"Adjusted: {a}" for a in r["adjustments"]]
    uncertainties += [f"Check: {f}" for f in r["flags"]]

    # P9 — the anchors are frozen between results
    prior_slim = _prior_slim(prior) if prior else None
    change_table = [c for c in (data.get("change_table") or []) if isinstance(c, dict)]
    entry_line = None
    if prior_slim:
        pc = prior_slim.get("cases") or {}
        moved = []
        for k in ("bear", "base", "bull"):
            old, new = _f((pc.get(k) or {}).get("price")), r.get(k)
            if old and new and abs(new - old) / old > 0.005:
                moved.append(f"{k} {old:,.2f} → {new:,.2f}")
        if moved and not any(str(c.get("fact") or "").strip() for c in change_table):
            uncertainties.append("P9: case values moved (" + "; ".join(moved) + ") with no company fact "
                                 "named in the change table — the share price is never a fact.")
        old_re = _f(prior_slim.get("reentry"))
        if old_re is not None and r.get("reentry") is not None:
            entry_line = {"old": round(old_re, 2), "new": round(r["reentry"], 2),
                          "driver": str(data.get("entry_driver") or "").upper() or "UNSTATED"}
            if entry_line["driver"] == "METHOD":
                uncertainties.append("P9: the entry level moved on a METHOD change — that needs PS "
                                     f"approval; until then both levels stand ({old_re:,.2f} and {r['reentry']:,.2f}).")
    elif prior and prior.get("framework") and not is_current(prior.get("framework")):
        uncertainties.append(f"First {PROSPER_VERSION} run. The earlier {prior.get('framework')} levels "
                             "are context only, not a prior run (P9).")

    do_this = str(data.get("do_this") or "").strip()
    if not do_this or (model_call and model_call != call):
        do_this = _default_do_this(r)

    conf = str(data.get("confidence") or "").strip().title() or "Low"
    if tier == "screen":
        conf = "Low"
    conviction = {"High": "HIGH", "Medium": "MEDIUM", "Low": "LOW"}.get(conf, "LOW")

    thesis = f"Score {r['q']:.1f} · {call} · reward:risk {r['ratio_text']}"
    if r.get("buy_below") is not None:
        thesis += f" · buy below {r['buy_below']:,.2f}"
    thesis += f" — {do_this}"
    why = data.get("why") or {}
    if isinstance(why, dict) and why.get("tips"):
        thesis += f". {str(why['tips'])[:160]}"

    prove_wrong = [p for p in (data.get("prove_wrong") or []) if p]
    catalysts = [c for c in (data.get("catalysts") or []) if isinstance(c, dict)]
    memo_md = _strip_json_block(memo_text or "")

    run_date = datetime.now().strftime("%Y-%m-%d")
    result = {
        "framework": PROSPER_VERSION,
        "ticker": ticker.upper(),
        "company": data.get("company") or info.get("longName") or "",
        "line": data.get("line") or "",
        "what_it_does": data.get("what_they_do") or "",
        "q_score": r["q"],
        "entry_verdict": call,
        "model_call": model_call or None,
        "do_this": do_this,
        "reward_risk": (None if r["ratio"] is None else (999.0 if math.isinf(r["ratio"]) else round(r["ratio"], 3))),
        "reentry_price": None if r["reentry"] is None else round(r["reentry"], 2),
        "bear_price": r["bear"], "base_price": r["base"], "bull_price": r["bull"],
        "break_price": r["break"] if r["conduct"] else None,
        "prob_weighted_return": None if r["pw_return"] is None else round(r["pw_return"], 4),
        "buy_zone_low": r["buy_zone_low"], "buy_zone_high": r["buy_zone_high"],
        "walk_away": str((data.get("action_prices") or {}).get("walk_away") or "") or None,
        "regime_state": r["regime_state"],
        "starter_pct": r["starter_pct"],
        "valid_until": r["valid_until"],
        "no_adds": 1.0 if (r["conduct"] or call in REDUCING_CALLS) else 0.0,
        # the ladder the Options Desk's Rule 1 reads (harvest/HARVEST_v1_DOCTRINE.md)
        "buy_below": None if r["buy_below"] is None else round(r["buy_below"], 2),
        "strong_buy_below": None if r["line_3x"] is None else round(r["line_3x"], 2),
        "fair_high": None if r["fair_high"] is None else round(r["fair_high"], 2),
        "reduce_above": None if r["fair_high"] is None else round(r["fair_high"], 2),
        "cagr_spot": None if r["pw_return_pa"] is None else round(r["pw_return_pa"], 4),
        "required_return": None,
        "price_at_run": spot,
        "confidence": conf,
        "memo_md": memo_md,
        "screen_only": tier == "screen",
        "resolved": r,
        "entry_line": entry_line,
        "change_table": change_table,
        "catalysts": catalysts,
        "prove_wrong": prove_wrong,
        "uncertainties": uncertainties,
        # ── columns other pages read ──
        "rating": call,
        "score": r["q"],
        "durability": None,
        "archetype": r["route"],
        "archetype_name": ROUTES.get(r["route"], r["route"]),
        "conviction": conviction,
        "thesis": thesis,
        "env_net": None,
        "fair_value_bear": r["stressed_bear"],
        "fair_value_base": r["base"],
        "fair_value_bull": r["bull"],
        "upside_pct": None if r["pw_return"] is None else round(r["pw_return"] * 100, 1),   # 3-yr, %
        "score_breakdown": r["scores"],
        "key_risks": [f"{p.get('fact')}: {p.get('effect')}" if isinstance(p, dict) else str(p) for p in prove_wrong],
        "key_catalysts": [f"{c.get('event')} — {c.get('date')}" for c in catalysts],
        # ── run metadata ──
        "analysis_date": run_date,
        "model_used": tier,
        "model_id": model_id,
        "cost_estimate": round(cost, 4),
        "elapsed_seconds": round(elapsed, 1),
        "data_fields": data_fields,
        "data_quality_warning": "LOW" if (tier == "screen" or data_fields < 6) else None,
        **(usage or {}),
    }
    result["card_md"] = card_text(result, data)
    result["full_response"] = {k: v for k, v in result.items() if k not in ("memo_md", "card_md")}
    result["full_response"]["prosper_json"] = data
    return result, ""


def run_prosper(
    ticker: str,
    tier: str = "standard",
    info: dict = None,
    price_quote: dict = None,
    prior: dict = None,
    max_searches: int = None,
    regime_hint: dict = None,
) -> Tuple[Optional[Dict], str]:
    """Run PROSPER on one ticker. Returns (result_dict, error_message); result is None on failure.

    `prior` is the ticker's saved row; it is only passed to the model when it was written by
    PROSPER v5.13.1 (P9). `max_searches` overrides the tier budget (batch runs use 6).
    `regime_hint` carries the regime established earlier in the same batch.
    """
    if not framework_available():
        return None, "PROSPER framework file not found in the app's prosper_framework/ folder."
    api_key = get_api_key("ANTHROPIC_API_KEY")
    if not api_key or api_key.startswith("your_"):
        return None, "Anthropic API key not configured. Add ANTHROPIC_API_KEY on Render (Environment) or in your local .env."

    tier = tier if tier in PROSPER_TIERS else "standard"
    prior_slim = _prior_slim(prior)
    if tier == "delta" and not prior_slim:
        tier = "standard"                 # a delta needs a prior card; without one it is a first run
    cfg = dict(PROSPER_TIERS[tier])
    if max_searches is not None and cfg["web"]:
        cfg["max_searches"] = max(1, min(cfg["max_searches"], int(max_searches)))

    edgar = None
    if cfg.get("web"):
        try:
            from core import edgar_client
            edgar = edgar_client.filing_snapshot(ticker)
        except Exception:
            edgar = None

    snapshot, data_fields = build_data_snapshot(ticker, info, price_quote, edgar=edgar)
    trigger = f"delta {ticker}" if tier == "delta" else f"Prosper {ticker}"
    if tier == "full":
        trigger += " memo detail"
    user_parts = [trigger, "\nDATA SNAPSHOT:\n" + snapshot]
    if prior_slim:
        user_parts.append("\nPRIOR RUN (P9 — anchors frozen unless a named company fact moved them):\n```json\n"
                          + json.dumps(prior_slim, default=str)[:12000] + "\n```")
    elif prior and prior.get("framework"):
        user_parts.append(f"\nNo prior {PROSPER_VERSION} card exists. A {prior.get('framework')} "
                          "run exists but is a different framework — context only, not a prior run (P9).")
    user_msg = "\n".join(user_parts)

    try:
        import anthropic
    except ImportError:
        return None, "anthropic package not installed."

    client = anthropic.Anthropic(api_key=api_key, timeout=900.0, max_retries=1)
    system = _system_blocks(tier, max_searches=cfg["max_searches"], has_edgar=bool(edgar),
                            regime_hint=regime_hint)
    models = [cfg["model"]] + [m for m in CLAUDE_MODEL_PRIORITY if m != cfg["model"]]

    t0 = time.time()
    total_cost = 0.0
    usage_tot = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0, "web_searches": 0}
    final_text = ""
    model_used = None
    last_error = None
    last_stop = None

    for model in models:
        tools = _web_tools_for(model, cfg["max_searches"] if cfg["web"] else 0,
                               cfg.get("fetch_content_tokens", 18000))
        messages = [{"role": "user", "content": user_msg}]
        kwargs = {"model": model, "max_tokens": cfg["max_tokens"], "system": system, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        if model != CLAUDE_FAST_MODEL:
            if cfg.get("thinking"):
                kwargs["thinking"] = cfg["thinking"]
            if cfg.get("effort"):
                kwargs["extra_body"] = {"output_config": {"effort": cfg["effort"]}}
        try:
            texts = []
            for _turn in range(8):  # web tools may return pause_turn; continue up to 8 times
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
            _log.exception("PROSPER run failed for %s", ticker)
            return None, f"PROSPER run failed: {err[:300]}"

    if model_used is None:
        return None, f"No Claude model accessible with your API key. Last error: {last_error}"

    elapsed = time.time() - t0
    global LAST_RAW_TEXT
    LAST_RAW_TEXT = final_text
    data = _extract_json_block(final_text)
    if not data or not isinstance(data, dict):
        _log.warning("PROSPER %s: no JSON block. stop_reason=%s, chars=%d, tail=%r",
                     ticker, last_stop, len(final_text), final_text[-300:])
        if last_stop == "max_tokens":
            return None, (f"PROSPER ran out of output budget before finishing (stop_reason=max_tokens after "
                          f"{usage_tot['output_tokens']} tokens). Try the run again.")
        return None, "PROSPER finished but the machine-readable block could not be parsed. Try again."

    return assemble_result(
        ticker, data, final_text, tier=tier, info=info, price_quote=price_quote,
        model_id=model_used, cost=total_cost, elapsed=elapsed,
        data_fields=data_fields, usage=usage_tot, prior=prior)


# ─────────────────────────────────────────
# THE CARD, AS TEXT (P7 — the saved deliverable)
# ─────────────────────────────────────────

def _m(v, nd=2) -> str:
    f = _f(v)
    return "—" if f is None else f"{f:,.{nd}f}"


def _pct_vs(v, spot) -> str:
    f = _f(v)
    if f is None or not spot:
        return "—"
    return f"{(f / spot - 1) * 100:+.0f}%"


def card_text(result: dict, data: dict = None) -> str:
    """The §B13 PROSPER CARD, filled with the RESOLVED numbers (not the model's arithmetic)."""
    data = data or ((result.get("full_response") or {}).get("prosper_json") or {})
    r = result.get("resolved") or ((result.get("full_response") or {}).get("resolved") or {})
    spot = result.get("price_at_run")
    ccy_line = result.get("line") or ""
    price_obj = data.get("price") if isinstance(data.get("price"), dict) else {}
    basis = price_obj.get("basis") or ("LAST CLOSE" if result.get("screen_only") else "LIVE/LAST CLOSE")
    rule = "═" * 43
    off = r.get("pct_off_high")
    mult = r.get("regime_multiplier")
    lines = [rule,
             f"{result.get('company') or ''} ({result.get('ticker') or ''}{' · ' + ccy_line if ccy_line else ''}) · "
             f"{_m(spot)} ({basis} · {price_obj.get('time') or result.get('analysis_date')})",
             (f"{off:.0f}% off 52-wk high" if off is not None else "52-wk high n/a")
             + f" · Market mood: {r.get('regime_state') or 'not established'}"
             + (f" (new buys at {mult*100:.0f}% size)" if mult is not None else ""),
             rule,
             "1 WHAT THEY DO", f"  {result.get('what_it_does') or '—'}", "",
             "2 RATING & RECOMMENDATION",
             f"  {_m(result.get('q_score'), 1)}/100 — {result.get('entry_verdict')}",
             f"  Do this: {result.get('do_this')}",
             f"  Confidence: {result.get('confidence')} — {data.get('confidence_raise') or ''}".rstrip(" —")]
    for g in r.get("gates") or []:
        lines.append(f"  Held back: {g['why']}." + (f" Released at {g['release']}." if g.get("release") else ""))
    why = data.get("why") or {}
    lines += ["", "3 WHY (plain English)",
              f"  + {why.get('for') or '—'}", f"  − {why.get('against') or '—'}", f"  = {why.get('tips') or '—'}"]
    integ = data.get("integrity") or {}
    if r.get("integrity_type") not in (None, "NONE") and integ.get("detail"):
        lines.append(f"  Legal/accounting: {integ.get('detail')}"
                     + (f" [source: {integ.get('direction_source')}]" if integ.get("direction_source") else ""))
    cases = data.get("cases") or {}
    lines += ["", f"4 BEAR · BASE · BULL (3 years, {data.get('horizon_label') or '—'})"]
    w = r.get("weights") or {}
    if r.get("conduct") and r.get("break") is not None:
        lines.append(f"  Break {_m(r['break'])} ({_pct_vs(r['break'], spot)}, {w.get('break', 0)*100:.0f}%) — "
                     f"if {(cases.get('break') or {}).get('why') or 'the worst credible legal outcome'}")
    for k, label in (("bear", "Bear"), ("base", "Base"), ("bull", "Bull")):
        lines.append(f"  {label}  {_m(r.get(k))} ({_pct_vs(r.get(k), spot)}) — if {(cases.get(k) or {}).get('why') or '—'}")
    lines += ["", "5 ASYMMETRY", f"  {ratio_formula(r)}"]
    ratio = r.get("ratio")
    if ratio is not None and not math.isinf(ratio):
        lines.append(f"  → For every $1 you could lose, you could make ${max(ratio, 0):,.2f}.")
    pw = r.get("pw_return")
    lines.append(f"  Probability-weighted 3-yr return: {pw*100:+.0f}%." if pw is not None else
                 "  Probability-weighted 3-yr return: —.")
    if r.get("reentry") is not None:
        lines.append(f"  Buy-worthy only at ≥2×; that happens at {_m(r['reentry'])} = (bull + 2×bear) ÷ 3.")
    lines += ["", "6 CATALYSTS (dated, next 12 months — most important first)"]
    cats = result.get("catalysts") or []
    lines += [f"  {c.get('event')} — {c.get('date') or 'date not yet announced'} — {c.get('impact') or ''}" for c in cats] or ["  —"]
    ap = data.get("action_prices") or {}
    tps = r.get("take_profit") or []
    lines += ["", "7 ACTION PRICES",
              f"  Buy zone {_m(r.get('buy_zone_low'))}–{_m(r.get('buy_zone_high'))} · Add {ap.get('add') or '—'} · "
              f"Take profits {' · '.join(_m(t) for t in tps[:3]) or '—'} (¼ · ½ · most)",
              f"  Walk away if {ap.get('walk_away') or '—'}"]
    lines += ["", "8 WHAT WOULD PROVE US WRONG"]
    pws = result.get("prove_wrong") or []
    lines += [f"  {p.get('fact')} → {p.get('effect')}" if isinstance(p, dict) else f"  {p}" for p in pws] or ["  —"]
    unv = str(data.get("unverified") or "").strip()
    lines += ["", "9 WHAT WE COULDN'T VERIFY", f"  {unv or '—'}", rule]
    return "\n".join(lines)


def cards_file(results: List[dict], label: str = "BOOK") -> Tuple[str, str]:
    """P7 — the saved cards file: master table, regime, anchor log, and every card.
    Returns (filename, markdown)."""
    today = datetime.now().strftime("%d%b%Y")
    fname = f"{PROSPER_VERSION} CARDS {label} {today}.md"
    rows = ["| Ticker | Score | Price | Call | Buy zone | Asymmetry | Next catalyst |",
            "|---|---|---|---|---|---|---|"]
    regimes = set()
    anchors = []
    cards = []
    for res in results:
        r = res.get("resolved") or ((res.get("full_response") or {}).get("resolved") or {})
        pj = (res.get("full_response") or {}).get("prosper_json") or {}
        cat = next(iter(res.get("catalysts") or ((res.get("full_response") or {}).get("catalysts") or [])), {}) or {}
        rows.append(f"| {res.get('ticker')} | {_m(res.get('q_score'), 1)} | {_m(res.get('price_at_run'))} | "
                    f"{res.get('entry_verdict')} | {_m(r.get('buy_zone_low'))}–{_m(r.get('buy_zone_high'))} | "
                    f"{r.get('ratio_text') or '—'} | {cat.get('event') or '—'} {cat.get('date') or ''} |")
        if r.get("regime_state"):
            regimes.add(r["regime_state"])
        for a in pj.get("anchors") or []:
            if isinstance(a, dict):
                anchors.append(f"| {res.get('ticker')} | {a.get('case')} | {a.get('revenue_or_ebitda')} | "
                               f"{a.get('margin')} | {a.get('exit_multiple')} | {a.get('diluted_shares')} | "
                               f"{a.get('source')} | {a.get('date')} |")
        cards.append("```\n" + (res.get("card_md") or card_text(res, pj)) + "\n```")
    md = [f"# {fname[:-3]}", "", f"Regime of record: {', '.join(sorted(regimes)) or 'not established'}", "",
          "## Master table", "", *rows, "", "## Anchor log (P9)", "",
          "| Ticker | Case | Revenue/EBITDA | Margin | Exit multiple | Diluted shares | Source | Date |",
          "|---|---|---|---|---|---|---|---|", *anchors, "", "## Cards", "", *cards]
    return fname, "\n".join(md)


def run_prosper_batch(tickers: list, tier: str = "screen", info_map: dict = None,
                      price_map: dict = None, prior_map: dict = None,
                      progress_callback=None) -> Dict[str, dict]:
    """Sequential batch (rate-limit friendly). §A: one regime scan, then ≤6 searches a name."""
    info_map, price_map, prior_map = info_map or {}, price_map or {}, prior_map or {}
    results, regime = {}, None
    total = len(tickers)
    for i, t in enumerate(tickers):
        if progress_callback:
            progress_callback(t, i, total)
        res, _err = run_prosper(t, tier=tier, info=info_map.get(t, {}), price_quote=price_map.get(t),
                                prior=prior_map.get(t), max_searches=BATCH_MAX_SEARCHES,
                                regime_hint=regime)
        if res:
            results[t] = res
            if regime is None and res.get("regime_state"):
                regime = ((res.get("full_response") or {}).get("prosper_json") or {}).get("regime")
        if i < total - 1:
            time.sleep(0.5)
    return results
