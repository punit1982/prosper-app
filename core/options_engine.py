"""
HARVEST v1.0 — the Options Desk engine
======================================
Turns option chains into at most five specific, tradeable orders a day.

Architecture — the same split that makes GROW work
--------------------------------------------------
GROW lets Claude reason about a business, then `resolve_entry()` recomputes the verdict and the
price ladder in Python and **overrides the model's own arithmetic**. Harvest does the same:

    Layer 2  generate_candidates()  pure Python. Walks the chain, applies every doctrine gate,
                                    scores what survives. ~180,000 contracts -> ~20 finalists.
    Layer 3  select_slate()         ONE Claude call. Sees a 20-row table, never a chain. Chooses
                                    which ideas fit the portfolio today and writes the reasoning.
    Layer 4  resolve_order()        pure Python. Recomputes every number on the ticket — limit
                                    price, contract count, collateral, breakeven, max loss,
                                    exits — and overrides whatever the model wrote.

The model is therefore incapable of putting a wrong number on a ticket. It can only pick badly
from a set of pre-validated, pre-priced candidates, and its picks are re-checked against the caps
before anything is shown.

Token economics
---------------
A day's chains across ~110 names are roughly 180,000 contracts. Sending that to a model is
unthinkable at any price and would produce worse answers, because a language model doing
arithmetic over 180,000 rows is the least reliable possible way to compute a delta-weighted yield.
Instead: doctrine as a cached system block (~4k tokens, billed at the cache-read rate after the
first call), ~3k tokens of candidates and portfolio context in, ~1.5k out. About **$0.02 a day**.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from core import options_data as od
from core import vol_metrics as vm
from harvest import universe as agu

_log = logging.getLogger("prosper.harvest.engine")

HARVEST_VERSION = "HARVEST v1.0"

# ─────────────────────────────────────────────────────────────────────────────
# Doctrine constants — every number here traces to a numbered rule
# ─────────────────────────────────────────────────────────────────────────────

DTE_MIN, DTE_MAX = 25, 50                 # theta per unit of gamma, on a manageable monthly cycle
SHORT_DELTA_MIN, SHORT_DELTA_MAX = 0.15, 0.35
LONG_PUT_DELTA_MIN, LONG_PUT_DELTA_MAX = 0.15, 0.40
MAX_PROTECTION_COST_PCT_PER_MONTH = 2.5   # of protected notional — see _protective_put_candidates

MIN_OPEN_INTEREST = 100                   # somebody else is in this strike; you can get out
MAX_SPREAD_PCT = 15.0                     # of mid
MIN_BID = 0.05                            # below this, commission eats the trade
MIN_NET_CREDIT = 75.0                     # R: not worth the attention it costs

CALL_WRITE_CAP = 0.50                     # R5 — never write against the whole position
CALL_WRITE_CAP_HIGH_CONVICTION = 0.33     # R5 — GROW BUY or better
COLLATERAL_CAP = 0.60                     # R4 — share of the liquid ledger committed to short puts
SECTOR_CONCENTRATION_CAP = 0.25           # R7

TBILL_YIELD_PCT = 4.0                     # R3 — opportunity cost of the collateral
TBILL_SPREAD_HURDLE_PCT = 3.0             # R3 — a short put must beat T-bill + 300bp
FUNDING_COST_PCT = 1.5                    # R0/R3 — CHF/JPY/SGD carry

# R2 thresholds live in vol_metrics (they belong with the signal that produces them) and are
# re-exported here so the gates and their explanations quote one number, not two.
SELL_VRP_FLOOR = vm.SELL_VRP_FLOOR
BUY_VRP_CEILING = vm.BUY_VRP_CEILING

GROW_STALE_DAYS = 90                      # R1
PROFIT_TARGET_FRAC = 0.65                 # R8 — buy to close at 65% of max profit
ROLL_DTE_TRIGGER = 14                     # R8

CONTRACT_MULTIPLIER = 100
COMMISSION_PER_CONTRACT = 0.65            # IBKR tiered, typical US equity option

STRATEGIES = ("covered_call", "cash_secured_put", "protective_put", "put_credit_spread")


def configure(settings=None) -> dict:
    """Pull the user-tunable doctrine numbers out of SETTINGS into this module.

    The constants above are defaults, not policy. The T-bill yield moves, the funding cost on the
    CHF/JPY/SGD borrowings moves, and the collateral ledger definitely moves — hard-coding them
    would mean the R3 hurdle silently drifts away from reality. Called once at the top of a scan.
    Returns the resolved values so the caller can log what it actually ran with.
    """
    global TBILL_YIELD_PCT, FUNDING_COST_PCT
    if settings is None:
        try:
            from core.settings import SETTINGS as settings
        except Exception:
            return {"tbill_yield_pct": TBILL_YIELD_PCT, "funding_cost_pct": FUNDING_COST_PCT}
    try:
        TBILL_YIELD_PCT = float(settings.get("harvest_tbill_yield_pct", TBILL_YIELD_PCT))
        FUNDING_COST_PCT = float(settings.get("harvest_funding_cost_pct", FUNDING_COST_PCT))
    except (TypeError, ValueError):
        pass
    return {"tbill_yield_pct": TBILL_YIELD_PCT, "funding_cost_pct": FUNDING_COST_PCT}


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────

def _f(v) -> Optional[float]:
    try:
        if v is None:
            return None
        x = float(v)
        return None if (math.isnan(x) or math.isinf(x)) else x
    except (TypeError, ValueError):
        return None


def _annualise(pct_return: float, dte: int) -> float:
    """Simple (not compounded) annualisation. Compounding a 40-day premium yield to an APY
    overstates a strategy nobody actually runs 9x a year at the same vol — the honest number is
    the one you can compare to a T-bill."""
    if not dte or dte <= 0:
        return 0.0
    return pct_return * 365.0 / dte


def _round_to_tick(price: float) -> float:
    """US equity options trade in $0.01 below $3.00 and $0.05 at or above it (penny pilot).
    A limit priced off-tick is rejected by the exchange, so this is correctness, not cosmetics."""
    if price is None:
        return 0.0
    if price < 3.0:
        return round(round(price / 0.01) * 0.01, 2)
    return round(round(price / 0.05) * 0.05, 2)


def _limit_price(bid: float, ask: float, *, selling: bool) -> float:
    """Where to actually place the order.

    Mid is where the trade *should* happen and frequently does not. Harvest asks for slightly
    worse than mid in the direction of getting filled — a third of the way from mid toward the
    bid when selling — because an unfilled ticket earns nothing and a chased fill earns less than
    the screen said. Never crosses the spread.
    """
    bid, ask = bid or 0.0, ask or 0.0
    if bid <= 0 or ask <= 0:
        return 0.0
    mid = (bid + ask) / 2.0
    price = mid - (mid - bid) / 3.0 if selling else mid + (ask - mid) / 3.0
    price = max(bid, min(ask, price))
    return _round_to_tick(price)


def _grow_for(ticker: str, grow_map: dict) -> dict:
    """GROW verdict for a name, with staleness marked (R1)."""
    g = (grow_map or {}).get((ticker or "").upper()) or {}
    if not g:
        return {"has_verdict": False, "stale": False}
    stale = False
    try:
        d = datetime.strptime(str(g.get("analysis_date"))[:10], "%Y-%m-%d").date()
        stale = (date.today() - d).days > GROW_STALE_DAYS
    except (ValueError, TypeError):
        stale = True
    return {
        "has_verdict": True,
        "stale": stale,
        "verdict": (g.get("entry_verdict") or g.get("rating") or "").upper(),
        "durability": _f(g.get("durability")) or _f(g.get("score")),
        "buy_below": _f(g.get("buy_below")),
        "fair_high": _f(g.get("fair_high")) or _f(g.get("reduce_above")),
        "reduce_above": _f(g.get("reduce_above")),
        "analysis_date": str(g.get("analysis_date"))[:10],
    }


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2 — candidate generation (pure Python, no model)
# ─────────────────────────────────────────────────────────────────────────────

def _passes_liquidity(c: dict, *, stale_quotes: bool) -> Tuple[bool, str]:
    if (c.get("open_interest") or 0) < MIN_OPEN_INTEREST:
        return False, f"open interest {c.get('open_interest')} below {MIN_OPEN_INTEREST}"
    if (c.get("bid") or 0) < MIN_BID:
        return False, "bid below $0.05"
    sp = c.get("spread_pct")
    if sp is None:
        return False, "no two-sided market"
    # When the snapshot is stale (weekend / pre-open), bid-ask is unreliable — a Sunday scan
    # produced a 115% "spread" on XLF. Gate loosely then, and mark the ticket for re-check.
    limit = MAX_SPREAD_PCT * 2.0 if stale_quotes else MAX_SPREAD_PCT
    if sp > limit:
        return False, f"spread {sp:.1f}% wider than {limit:.0f}%"
    return True, ""


def _covered_call_candidates(ctx: dict) -> List[dict]:
    """Short calls against lots of 100+ shares already owned (R1, R2, R5, R6)."""
    out = []
    note = ctx["reject"]
    shares = _f(ctx["position"].get("shares")) or 0
    max_contracts = int(shares // CONTRACT_MULTIPLIER)
    if max_contracts < 1:
        if shares > 0:
            note("covered_call", f"{shares:g} shares is under the 100-share contract size")
        return out

    g = ctx["grow"]
    spot, metrics = ctx["spot"], ctx["metrics"]

    # R5 feasibility, checked here rather than in the resolver. Writing 50% of a one-contract lot
    # is zero contracts, so the idea is not merely capped — it does not exist. Surfacing it to the
    # model wastes a shortlist slot and invites reasoning that assumes a trade which cannot happen.
    _high_conviction = g["has_verdict"] and g["verdict"] in ("BUY", "STRONG BUY")
    _frac = CALL_WRITE_CAP_HIGH_CONVICTION if _high_conviction else CALL_WRITE_CAP
    if int(max_contracts * _frac) < 1:
        note("covered_call",
             f"{max_contracts} contract lot — writing the {int(_frac * 100)}% allowed by R5 "
             f"rounds to zero contracts, so there is no covered call to place here")
        return out

    # R2 — never sell cheap volatility.
    if metrics.get("vrp_verdict") != "sell":
        note("covered_call",
             f"IV30 {metrics.get('iv30') or 0:.0f} against realized {metrics.get('hv20') or 0:.0f} "
             f"is a ratio of {metrics.get('vrp') or 0:.2f} — below the {SELL_VRP_FLOOR:.2f} floor "
             f"for selling premium (R2)")
        return out

    # R1 — do not cap the upside on a high-conviction name.
    floor_strike = 0.0
    if g["has_verdict"]:
        if g["verdict"] in ("BUY", "STRONG BUY"):
            fair = g.get("fair_high") or g.get("reduce_above")
            if fair:
                floor_strike = fair       # only write at or above full value
            else:
                note("covered_call",
                     f"GROW rates it {g['verdict']} but carries no fair-high rung, so R1 cannot "
                     f"be satisfied — standing aside rather than capping the upside")
                return out
        elif g["verdict"] in ("SELL", "STRONG SELL"):
            floor_strike = 0.0            # happy to be taken out at any sensible strike
        else:
            floor_strike = (g.get("fair_high") or g.get("reduce_above") or 0.0)

    for c in ctx["contracts"]:
        if c["right"] != "C":
            continue
        if not (DTE_MIN <= c["dte"] <= DTE_MAX):
            continue
        d = _f(c.get("delta")) or 0
        if not (SHORT_DELTA_MIN <= d <= SHORT_DELTA_MAX):
            continue
        if c["strike"] <= spot:
            continue                                   # covered calls are written out of the money
        ok, why = _passes_liquidity(c, stale_quotes=ctx["stale_quotes"])
        if not ok:
            continue
        if floor_strike and c["strike"] < floor_strike:
            continue                                   # R1
        if od.earnings_before(c["expiry"], ctx["earnings"]):
            continue                                   # R6

        credit_per = c["mid"] * CONTRACT_MULTIPLIER
        if credit_per < MIN_NET_CREDIT:
            continue
        static_pct = c["mid"] / spot * 100.0
        out.append({
            "strategy": "covered_call",
            "ticker": ctx["ticker"],
            "contract": c,
            "static_return_pct": round(static_pct, 3),
            "annualised_pct": round(_annualise(static_pct, c["dte"]), 1),
            "capital_at_risk": spot * CONTRACT_MULTIPLIER,   # the shares already held
            "max_contracts": max_contracts,
        })

    if not out and floor_strike:
        # The common and previously invisible case: R1's floor sits so far above spot that every
        # strike satisfying it has a delta under 0.15. That is the doctrine working — it is
        # refusing to cap upside cheaply — but the user must be told, not left with a blank page.
        note("covered_call",
             f"R1 requires a strike at or above ${floor_strike:,.2f} (GROW's fair-high) but spot "
             f"is ${spot:,.2f}; every strike that far out prices below the {SHORT_DELTA_MIN:.2f} "
             f"delta floor. No call here is worth writing at a price you'd be happy to sell at.")
    elif not out:
        note("covered_call", "no strike cleared the delta, liquidity and minimum-credit gates")
    return out


def _cash_secured_put_candidates(ctx: dict) -> List[dict]:
    """Short puts secured against the Treasury/cash ledger (R3, R4).

    Only on the assignment-grade universe, or on a held name GROW rates BUY or better — the test
    is always "would being assigned here be an acceptable outcome", never "is the premium fat".
    """
    out = []
    note = ctx["reject"]
    g, spot, metrics = ctx["grow"], ctx["spot"], ctx["metrics"]

    in_agu = agu.in_universe(ctx["ticker"]) and agu.put_writable(ctx["ticker"], spot)
    grow_wants_it = g["has_verdict"] and g["verdict"] in ("BUY", "STRONG BUY")
    if not (in_agu or grow_wants_it):
        if agu.in_universe(ctx["ticker"]):
            note("cash_secured_put",
                 f"Tier C name at ${spot:,.2f} — ${spot * CONTRACT_MULTIPLIER:,.0f} of collateral "
                 f"per contract is too large to secure; spreads or covered calls only (R4)")
        else:
            note("cash_secured_put",
                 "not in the assignment-grade universe and GROW does not rate it BUY — assignment "
                 "would not be an acceptable outcome (R4)")
        return out
    if metrics.get("vrp_verdict") != "sell":            # R2
        note("cash_secured_put",
             f"IV30 {metrics.get('iv30') or 0:.0f} vs realized {metrics.get('hv20') or 0:.0f} "
             f"= {metrics.get('vrp') or 0:.2f}, below the {SELL_VRP_FLOOR:.2f} floor (R2)")
        return out

    # R1 applied to the put side: only agree to buy at or below GROW's buy_below rung. This binds
    # whenever GROW has a view at all — membership of the assignment-grade universe says the name
    # is sound, not that any price for it is acceptable.
    ceiling_strike = g.get("buy_below") if g["has_verdict"] else None

    for c in ctx["contracts"]:
        if c["right"] != "P":
            continue
        if not (DTE_MIN <= c["dte"] <= DTE_MAX):
            continue
        d = abs(_f(c.get("delta")) or 0)
        if not (SHORT_DELTA_MIN <= d <= SHORT_DELTA_MAX):
            continue
        if c["strike"] >= spot:
            continue
        ok, _why = _passes_liquidity(c, stale_quotes=ctx["stale_quotes"])
        if not ok:
            continue
        if ceiling_strike and c["strike"] > ceiling_strike:
            continue
        if od.earnings_before(c["expiry"], ctx["earnings"]):
            continue                                   # R6

        collateral = c["strike"] * CONTRACT_MULTIPLIER
        credit_per = c["mid"] * CONTRACT_MULTIPLIER
        if credit_per < MIN_NET_CREDIT:
            continue
        yield_on_collateral = credit_per / collateral * 100.0
        ann = _annualise(yield_on_collateral, c["dte"])
        if ann < (TBILL_YIELD_PCT + TBILL_SPREAD_HURDLE_PCT):     # R3
            continue

        out.append({
            "strategy": "cash_secured_put",
            "ticker": ctx["ticker"],
            "contract": c,
            "static_return_pct": round(yield_on_collateral, 3),
            "annualised_pct": round(ann, 1),
            "capital_at_risk": collateral,
            "max_contracts": None,                     # bounded by the collateral ledger, not a lot
        })

    if not out and ceiling_strike:
        note("cash_secured_put",
             f"R1 caps the strike at GROW's buy-below of ${ceiling_strike:,.2f}; spot is "
             f"${spot:,.2f}, so every put that far down prices below the "
             f"{SHORT_DELTA_MIN:.2f} delta floor or under the minimum credit")
    elif not out:
        note("cash_secured_put", "no strike cleared the delta, liquidity, credit and R3 "
                                 "T-bill-hurdle gates")
    return out


def _protective_put_candidates(ctx: dict) -> List[dict]:
    """Buy protection when the market is selling it cheap (R2 inverted).

    Only on names actually held, and only where IV is below realized — the same signal that
    forbids selling premium is what makes buying it sensible.
    """
    out = []
    shares = _f(ctx["position"].get("shares")) or 0
    if shares < CONTRACT_MULTIPLIER:
        return out
    if ctx["metrics"].get("vrp_verdict") != "buy":
        return out

    spot = ctx["spot"]
    for c in ctx["contracts"]:
        if c["right"] != "P":
            continue
        if not (DTE_MIN <= c["dte"] <= DTE_MAX):
            continue
        d = abs(_f(c.get("delta")) or 0)
        if not (LONG_PUT_DELTA_MIN <= d <= LONG_PUT_DELTA_MAX):
            continue
        if c["strike"] >= spot:
            continue
        if (c.get("open_interest") or 0) < MIN_OPEN_INTEREST:
            continue
        if (c.get("ask") or 0) <= 0:
            continue
        sp = c.get("spread_pct")
        if sp is None or sp > (MAX_SPREAD_PCT * 2 if ctx["stale_quotes"] else MAX_SPREAD_PCT):
            continue

        cost_per = c["mid"] * CONTRACT_MULTIPLIER
        protected = min(int(shares // CONTRACT_MULTIPLIER), 10)
        cost_pct = c["mid"] / spot * 100.0

        # A relative signal is not an absolute one. ENVX at $3.42 offered a $3.00 put for $0.21 —
        # "cheap" by IV-vs-realized, and 6.1% of the position for 39 days. Protection that costs
        # more than ~2.5% of notional a month is not insurance, it is a short position with extra
        # steps, and it must never reach a ticket.
        monthly_cost_pct = cost_pct * 30.0 / max(c["dte"], 1)
        if monthly_cost_pct > MAX_PROTECTION_COST_PCT_PER_MONTH:
            continue

        out.append({
            "strategy": "protective_put",
            "ticker": ctx["ticker"],
            "contract": c,
            "static_return_pct": round(-cost_pct, 3),
            "annualised_pct": round(-_annualise(cost_pct, c["dte"]), 1),
            "capital_at_risk": cost_per,               # a long option can only lose its premium
            "max_contracts": protected,
        })
    return out


def _put_credit_spread_candidates(ctx: dict) -> List[dict]:
    """Defined-risk alternative where a naked put is too big — Tier C names, or a tight ledger.

    Sells the same delta band as a cash-secured put and buys a wing ~10% lower, cutting the
    collateral from strike x 100 to the width of the spread.
    """
    out = []
    spot, metrics = ctx["spot"], ctx["metrics"]
    if not agu.in_universe(ctx["ticker"]):
        return out
    # Only where a naked put is not the better trade: Tier C names, whose collateral per contract
    # is too large to secure. On Tier A/B a spread is strictly inferior — a cash-secured put ends
    # with you owning a name you already said you would be happy to own; a spread just loses.
    if agu.put_writable(ctx["ticker"], spot):
        return out
    if metrics.get("vrp_verdict") != "sell":
        return out

    puts = [c for c in ctx["contracts"] if c["right"] == "P" and DTE_MIN <= c["dte"] <= DTE_MAX]
    by_expiry: Dict[str, List[dict]] = {}
    for c in puts:
        by_expiry.setdefault(c["expiry"], []).append(c)

    for expiry, legs in by_expiry.items():
        if od.earnings_before(expiry, ctx["earnings"]):
            continue
        legs.sort(key=lambda c: -c["strike"])
        shorts = [c for c in legs
                  if SHORT_DELTA_MIN <= abs(_f(c.get("delta")) or 0) <= SHORT_DELTA_MAX
                  and c["strike"] < spot]
        for s in shorts:
            ok, _w = _passes_liquidity(s, stale_quotes=ctx["stale_quotes"])
            if not ok:
                continue
            target = s["strike"] * 0.90
            wings = [c for c in legs
                     if c["strike"] < s["strike"] and (c.get("open_interest") or 0) >= MIN_OPEN_INTEREST
                     and (c.get("bid") or 0) > 0]
            if not wings:
                continue
            long_leg = min(wings, key=lambda c: abs(c["strike"] - target))
            width = (s["strike"] - long_leg["strike"]) * CONTRACT_MULTIPLIER
            if width <= 0:
                continue
            net_credit = (s["mid"] - long_leg["mid"]) * CONTRACT_MULTIPLIER
            if net_credit < MIN_NET_CREDIT:
                continue
            max_loss = width - net_credit
            if max_loss <= 0:
                continue
            ret_pct = net_credit / max_loss * 100.0
            ann = _annualise(ret_pct, s["dte"])
            if ann < (TBILL_YIELD_PCT + TBILL_SPREAD_HURDLE_PCT):
                continue
            out.append({
                "strategy": "put_credit_spread",
                "ticker": ctx["ticker"],
                "contract": s,
                "long_leg": long_leg,
                "static_return_pct": round(ret_pct, 3),
                "annualised_pct": round(ann, 1),
                "capital_at_risk": max_loss,
                "max_contracts": None,
            })
            break        # one spread per expiry is plenty
    return out


def _score(cand: dict, ctx: dict) -> float:
    """Composite desirability, 0-100. Deterministic and explainable.

    Yield alone is a trap — it ranks CRDO (IV 72 against realized 111) top of the book. Volatility
    edge and liquidity are weighted heavily enough to override it.
    """
    m, g = ctx["metrics"], ctx["grow"]
    c = cand["contract"]

    ann = cand["annualised_pct"]
    if cand["strategy"] == "protective_put":
        # Protection is scored on cheapness, not yield: the further IV sits below realized, the
        # better the purchase.
        vrp = m.get("vrp") or 1.0
        yield_score = max(0.0, min(35.0, (1.0 - vrp) * 120.0))
    elif cand["strategy"] == "put_credit_spread":
        # A spread's return is measured on max-loss, not on collateral, so it annualises to
        # 300-400% and would otherwise outrank every covered call on the board by construction.
        # Normalised against a scale a defined-risk trade is actually judged on.
        yield_score = max(0.0, min(35.0, ann / 200.0 * 35.0))
    else:
        yield_score = max(0.0, min(35.0, ann / 60.0 * 35.0))

    vrp = m.get("vrp")
    if cand["strategy"] == "protective_put":
        vol_score = 25.0 if (vrp or 1) <= 0.80 else 15.0
    elif vrp is None:
        vol_score = 0.0
    else:
        vol_score = max(0.0, min(25.0, (vrp - 1.0) * 50.0))

    oi = c.get("open_interest") or 0
    spread = c.get("spread_pct") or 99
    liq_score = min(12.0, math.log10(max(oi, 1)) * 4.0) + max(0.0, 8.0 - spread / 2.0)
    liq_score = min(20.0, liq_score)

    if not g["has_verdict"]:
        grow_score = 4.0                      # provisional — ranked below anything that passes cleanly
    elif g["stale"]:
        grow_score = 8.0
    else:
        grow_score = 14.0
        if cand["strategy"] == "covered_call" and g["verdict"] in ("HOLD", "SELL", "STRONG SELL"):
            grow_score = 20.0                 # writing calls on what you'd happily sell is ideal
        if cand["strategy"] == "cash_secured_put" and g["verdict"] in ("BUY", "STRONG BUY"):
            grow_score = 20.0                 # getting paid to buy what you want is ideal

    ts = m.get("term_structure")
    penalty = 0.0
    if ts is not None and ts < -8 and cand["strategy"] != "protective_put":
        penalty += 8.0        # sharp backwardation: the market expects an event you may not see
    if ctx["stale_quotes"]:
        penalty += 3.0

    return round(max(0.0, yield_score + vol_score + liq_score + grow_score - penalty), 1)


def generate_candidates(
    snapshots: Dict[str, dict],
    metrics: Dict[str, dict],
    positions: Dict[str, dict],
    grow_map: Dict[str, dict],
    earnings: Dict[str, dict],
    *,
    per_underlying: int = 2,
    max_total: int = 20,
    rejections: List[dict] = None,
) -> List[dict]:
    """Layer 2. ~180,000 contracts -> ~20 scored finalists. No model involved.

    Pass a list as `rejections` to receive, for every underlying that produced nothing, the reason
    it produced nothing. The Options Desk renders these: an engine that shows only what it likes
    is indistinguishable from one that is broken, and the rejections are the trust surface.
    """
    all_cands: List[dict] = []
    rejections = rejections if rejections is not None else []

    for ticker, snap in (snapshots or {}).items():
        spot = _f(snap.get("spot"))
        if not spot or spot <= 0:
            continue
        rejected_here: List[dict] = []
        ctx = {
            "ticker": ticker,
            "spot": spot,
            "contracts": snap.get("contracts") or [],
            "metrics": (metrics or {}).get(ticker) or {},
            "position": (positions or {}).get(ticker) or {},
            "grow": _grow_for(ticker, grow_map),
            "earnings": (earnings or {}).get(ticker),
            "stale_quotes": od.quote_is_stale(snap.get("quote_timestamp")),
            "reject": lambda strat, why, _t=ticker, _acc=rejected_here: _acc.append(
                {"ticker": _t, "strategy": strat, "reason": why}),
        }
        found: List[dict] = []
        found += _covered_call_candidates(ctx)
        found += _cash_secured_put_candidates(ctx)
        found += _protective_put_candidates(ctx)
        found += _put_credit_spread_candidates(ctx)
        if not found:
            rejections.extend(rejected_here)

        for c in found:
            c["score"] = _score(c, ctx)
            c["vrp"] = ctx["metrics"].get("vrp")
            c["iv30"] = ctx["metrics"].get("iv30")
            c["hv20"] = ctx["metrics"].get("hv20")
            c["term_structure"] = ctx["metrics"].get("term_structure")
            c["grow"] = ctx["grow"]
            c["spot"] = spot
            c["stale_quotes"] = ctx["stale_quotes"]
            c["earnings"] = ctx["earnings"]
            c["sector"] = agu.sector_of(ticker)

        # Best N per underlying — R7 forbids stacking, and 12 near-identical ORCL strikes
        # crowd out every other name from the shortlist the model sees.
        # Best contract per (underlying, strategy), then at most `per_underlying` strategies.
        # Two near-identical CIFR protective puts differing only by strike are not two ideas, and
        # letting both through costs a distinct name its place in the 20 rows the model sees.
        found.sort(key=lambda c: -c["score"])
        keep, seen_strategies = [], set()
        for c in found:
            if c["strategy"] in seen_strategies:
                continue
            keep.append(c)
            seen_strategies.add(c["strategy"])
            if len(keep) >= per_underlying:
                break
        all_cands += keep

    all_cands.sort(key=lambda c: -c["score"])
    for i, c in enumerate(all_cands[:max_total], 1):
        c["candidate_id"] = f"{c['ticker']}-{c['strategy'][:2].upper()}-{i:02d}"
    return all_cands[:max_total]


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 4 — deterministic order resolution
# ─────────────────────────────────────────────────────────────────────────────

def resolve_order(cand: dict, *, collateral_available: float, collateral_committed: float = 0.0,
                  open_underlyings: set = None) -> dict:
    """Turn a candidate into a ticket with every number computed here, not by the model.

    Applies the position caps (R4, R5, R7) and returns a `blocked` reason rather than silently
    shrinking to zero contracts, so the UI can explain why an otherwise good idea is not offered.
    """
    open_underlyings = open_underlyings or set()
    c = cand["contract"]
    strategy = cand["strategy"]
    ticker = cand["ticker"]
    spot = cand["spot"]
    g = cand.get("grow") or {}

    selling = strategy in ("covered_call", "cash_secured_put", "put_credit_spread")
    ticket = {
        "candidate_id": cand.get("candidate_id"),
        "ticker": ticker,
        "strategy": strategy,
        "expiry": c["expiry"],
        "dte": c["dte"],
        "right": c["right"],
        "strike": c["strike"],
        "contract_symbol": c["symbol"],
        "spot": spot,
        "delta": c.get("delta"),
        "iv_contract": round((c.get("iv") or 0) * 100, 1) or None,
        "open_interest": c.get("open_interest"),
        "spread_pct": c.get("spread_pct"),
        "bid": c.get("bid"),
        "ask": c.get("ask"),
        "mid": c.get("mid"),
        "score": cand.get("score"),
        "vrp": cand.get("vrp"),
        "iv30": cand.get("iv30"),
        "hv20": cand.get("hv20"),
        "sector": cand.get("sector"),
        "quotes_stale": bool(cand.get("stale_quotes")),
        "blocked": None,
        "warnings": [],
    }

    # R7 — one position per underlying.
    if ticker in open_underlyings:
        ticket["blocked"] = f"already carrying an open Harvest position in {ticker} (R7)"
        return ticket

    limit = _limit_price(c.get("bid"), c.get("ask"), selling=selling)
    if limit <= 0:
        ticket["blocked"] = "no two-sided market to price against"
        return ticket
    ticket["limit_price"] = limit
    ticket["action"] = "SELL" if selling else "BUY"

    # ── contract count ──
    if strategy == "covered_call":
        shares_cap = cand.get("max_contracts") or 0
        high_conviction = g.get("has_verdict") and g.get("verdict") in ("BUY", "STRONG BUY")
        frac = CALL_WRITE_CAP_HIGH_CONVICTION if high_conviction else CALL_WRITE_CAP
        n = int(shares_cap * frac)
        if n < 1:
            ticket["blocked"] = (f"lot of {shares_cap} contract(s) is too small to write "
                                 f"{int(frac*100)}% against without exceeding the cap (R5)")
            return ticket
        ticket["contracts"] = n
        ticket["coverage_note"] = (f"writing {n} of {shares_cap} possible — "
                                   f"{int(frac*100)}% cap, R5" + (" (high-conviction name)" if high_conviction else ""))
        ticket["collateral"] = 0.0
        ticket["collateral_note"] = "none — the shares are the cover"

    elif strategy in ("cash_secured_put", "put_credit_spread"):
        per_contract = (c["strike"] * CONTRACT_MULTIPLIER) if strategy == "cash_secured_put" \
            else cand["capital_at_risk"]
        room = max(0.0, collateral_available * COLLATERAL_CAP - collateral_committed)
        n = int(room // per_contract) if per_contract > 0 else 0
        n = max(0, min(n, 5))
        if n < 1:
            ticket["blocked"] = (f"needs ${per_contract:,.0f} of collateral; only ${room:,.0f} "
                                 f"remains inside the {int(COLLATERAL_CAP*100)}% ledger cap (R4)")
            return ticket
        ticket["contracts"] = n
        ticket["collateral"] = per_contract * n
        ticket["collateral_note"] = (f"${per_contract:,.0f} per contract · "
                                     f"${room:,.0f} of ledger room before this trade")

    else:   # protective_put
        n = max(1, min(int(cand.get("max_contracts") or 1), 5))
        ticket["contracts"] = n
        ticket["collateral"] = 0.0
        ticket["collateral_note"] = "none — a long option risks only its premium"

    n = ticket["contracts"]
    gross = limit * CONTRACT_MULTIPLIER * n
    commission = COMMISSION_PER_CONTRACT * n * (2 if strategy == "put_credit_spread" else 1)

    if strategy == "put_credit_spread":
        long_leg = cand["long_leg"]
        long_limit = _limit_price(long_leg.get("bid"), long_leg.get("ask"), selling=False)
        net_per = _round_to_tick(limit - long_limit)
        gross = net_per * CONTRACT_MULTIPLIER * n
        ticket["long_strike"] = long_leg["strike"]
        ticket["long_contract_symbol"] = long_leg["symbol"]
        ticket["limit_price"] = net_per
        ticket["order_description"] = (
            f"SELL {n} × {ticker} {_fmt_expiry(c['expiry'])} {c['strike']:g} PUT / "
            f"BUY {n} × {ticker} {_fmt_expiry(c['expiry'])} {long_leg['strike']:g} PUT "
            f"— net credit ${net_per:.2f}")
        ticket["max_loss"] = round((c["strike"] - long_leg["strike"]) * CONTRACT_MULTIPLIER * n - gross, 2)
        ticket["breakeven"] = round(c["strike"] - net_per, 2)
    else:
        ticket["order_description"] = (
            f"{ticket['action']} {n} × {ticker} {_fmt_expiry(c['expiry'])} "
            f"{c['strike']:g} {'CALL' if c['right'] == 'C' else 'PUT'}"
            + (" — covered" if strategy == "covered_call" else ""))

    ticket["gross_premium"] = round(gross if selling else -gross, 2)
    ticket["commission"] = round(commission, 2)
    ticket["net_premium"] = round((gross - commission) if selling else -(gross + commission), 2)

    # ── strategy-specific economics ──
    if strategy == "covered_call":
        ticket["breakeven"] = round(spot - limit, 2)
        ticket["effective_sale_price"] = round(c["strike"] + limit, 2)
        ticket["upside_to_strike_pct"] = round((c["strike"] / spot - 1) * 100, 1)
        ticket["static_return_pct"] = round(limit / spot * 100, 2)
        ticket["annualised_pct"] = round(_annualise(limit / spot * 100, c["dte"]), 1)
        ticket["carry_spread_pct"] = round(ticket["annualised_pct"] - FUNDING_COST_PCT, 1)
        ticket["assignment_outcome"] = (
            f"you sell {n * CONTRACT_MULTIPLIER:,} shares at ${c['strike']:g} plus ${limit:.2f} "
            f"premium = ${ticket['effective_sale_price']:.2f} effective, "
            f"{ticket['upside_to_strike_pct']:+.1f}% from ${spot:,.2f}")
        ticket["max_loss"] = None

    elif strategy == "cash_secured_put":
        ticket["breakeven"] = round(c["strike"] - limit, 2)
        ticket["static_return_pct"] = round(limit * CONTRACT_MULTIPLIER / (c["strike"] * CONTRACT_MULTIPLIER) * 100, 2)
        ticket["annualised_pct"] = round(_annualise(ticket["static_return_pct"], c["dte"]), 1)
        ticket["tbill_spread_pct"] = round(ticket["annualised_pct"] - TBILL_YIELD_PCT, 1)
        ticket["assignment_cost"] = round(c["strike"] * CONTRACT_MULTIPLIER * n, 2)
        ticket["assignment_outcome"] = (
            f"you buy {n * CONTRACT_MULTIPLIER:,} shares at ${c['strike']:g} "
            f"(${ticket['assignment_cost']:,.0f}), effective cost ${ticket['breakeven']:.2f} "
            f"after premium — {(ticket['breakeven']/spot - 1)*100:+.1f}% vs today's ${spot:,.2f}")
        ticket["max_loss"] = round(ticket["breakeven"] * CONTRACT_MULTIPLIER * n, 2)

    elif strategy == "protective_put":
        ticket["breakeven"] = round(c["strike"] - limit, 2)
        ticket["cost_pct_of_position"] = round(limit / spot * 100, 2)
        ticket["annualised_pct"] = round(-_annualise(limit / spot * 100, c["dte"]), 1)
        ticket["protects"] = round(c["strike"] * CONTRACT_MULTIPLIER * n, 2)
        ticket["assignment_outcome"] = (
            f"floors {n * CONTRACT_MULTIPLIER:,} shares at ${c['strike']:g} until "
            f"{_fmt_expiry(c['expiry'])}; costs {ticket['cost_pct_of_position']:.2f}% of the position")
        ticket["max_loss"] = round(abs(ticket["net_premium"]), 2)

    else:  # put_credit_spread
        ticket["static_return_pct"] = cand["static_return_pct"]
        ticket["annualised_pct"] = cand["annualised_pct"]
        ticket["assignment_outcome"] = (
            f"max loss ${ticket['max_loss']:,.0f} if {ticker} closes below "
            f"${ticket.get('long_strike'):g} at expiry")

    # ── R8 — exits, computed, not optional ──
    if selling:
        target = _round_to_tick(limit * (1 - PROFIT_TARGET_FRAC))
        ticket["exit_profit_target"] = target
        ticket["exit_note"] = (f"buy to close at ${target:.2f} — {int(PROFIT_TARGET_FRAC*100)}% of "
                               f"maximum profit, banked early rather than held to expiry")
        roll_level = c["strike"] * (0.98 if c["right"] == "C" else 1.02)
        ticket["roll_trigger"] = (
            f"if {ticker} {'rises above' if c['right'] == 'C' else 'falls below'} "
            f"${roll_level:,.2f} with more than {ROLL_DTE_TRIGGER} days left, roll "
            f"{'up and out' if c['right'] == 'C' else 'down and out'}")
    else:
        ticket["exit_profit_target"] = None
        ticket["exit_note"] = ("sell to close if the position it protects is exited, or roll down "
                               "if the put goes deep in the money with time left")
        ticket["roll_trigger"] = f"review at {ROLL_DTE_TRIGGER} days to expiry"

    # ── checks the reader must see ──
    ticket["earnings_note"] = (
        f"reports {cand['earnings']['date']}"
        + (f" ({cand['earnings']['hour']})" if cand["earnings"].get("hour") else "")
        if cand.get("earnings") else "no scheduled report before expiry on the Finnhub calendar")

    # No "GROW" prefix here — the UI already labels this row "GROW", and the two together
    # rendered as "GROW GROW BUY · Durability 78".
    if g.get("has_verdict"):
        ticket["grow_note"] = (
            f"{g.get('verdict')} · Durability {g.get('durability'):.0f}"
            if g.get("durability") else str(g.get("verdict")))
        if g.get("fair_high"):
            ticket["grow_note"] += f" · fair-high ${g['fair_high']:,.2f}"
        if g.get("stale"):
            ticket["grow_note"] += f" · as of {g.get('analysis_date')}"
            ticket["warnings"].append(f"GROW verdict is from {g.get('analysis_date')} — over "
                                      f"{GROW_STALE_DAYS} days old (R1)")
    else:
        ticket["grow_note"] = "no verdict on file — R1 cannot be evaluated"
        ticket["warnings"].append("PROVISIONAL: run GROW on this name before trading it (R1)")

    if ticket["quotes_stale"]:
        ticket["warnings"].append(
            "quotes are from a previous session — re-check the bid/ask at the open before placing")
    if cand.get("term_structure") is not None and cand["term_structure"] < -8:
        ticket["warnings"].append(
            f"term structure is {cand['term_structure']:.1f} points backwardated — the market "
            f"expects something before the back month that the earnings calendar may not show")
    if ticket.get("annualised_pct") and selling and ticket["annualised_pct"] < TBILL_YIELD_PCT:
        ticket["warnings"].append(
            f"annualised {ticket['annualised_pct']:.1f}% is below the {TBILL_YIELD_PCT:.1f}% "
            f"T-bill alternative (R3)")

    return ticket


def _fmt_expiry(iso: str) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b %y").upper()
    except (ValueError, TypeError):
        return iso


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3 — the one Claude call a day
# ─────────────────────────────────────────────────────────────────────────────

import os

DOCTRINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "harvest")
DOCTRINE_FILE = "HARVEST_v1_DOCTRINE.md"

_PRICES = {   # USD per 1M tokens
    "claude-sonnet-5": {"in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "claude-opus-5":   {"in": 5.00, "out": 25.00, "cache_read": 0.50, "cache_write": 6.25},
}


def doctrine_available() -> bool:
    return os.path.exists(os.path.join(DOCTRINE_DIR, DOCTRINE_FILE))


def load_doctrine() -> str:
    with open(os.path.join(DOCTRINE_DIR, DOCTRINE_FILE), "r", encoding="utf-8") as f:
        return f.read()


def candidates_table(cands: List[dict]) -> str:
    """The ~20-row table the model sees instead of 180,000 contracts.

    Deliberately terse and fixed-width: this is the single biggest lever on cost, and every column
    here is one the doctrine actually reasons about. Roughly 1,200-1,600 tokens for a full slate.
    """
    if not cands:
        return "(no candidates cleared the gates today)"
    head = (f"{'ID':<16}{'TICKER':<8}{'STRATEGY':<18}{'EXP':<11}{'STRIKE':>8}{'DTE':>4}"
            f"{'DELTA':>7}{'MID':>8}{'ANN%':>7}{'IV30':>7}{'HV20':>7}{'VRP':>6}"
            f"{'OI':>8}{'SPRD%':>7}{'SCORE':>7}  GROW")
    lines = [head, "-" * len(head)]
    for c in cands:
        ct = c["contract"]
        g = c.get("grow") or {}
        grow_txt = "none" if not g.get("has_verdict") else (
            f"{g.get('verdict','?')}"
            + (f"/D{g['durability']:.0f}" if g.get("durability") else "")
            + (f"/fair{g['fair_high']:.0f}" if g.get("fair_high") else "")
            + (" STALE" if g.get("stale") else ""))
        lines.append(
            f"{c['candidate_id']:<16}{c['ticker']:<8}{c['strategy']:<18}{ct['expiry']:<11}"
            f"{ct['strike']:>8.2f}{ct['dte']:>4}{(ct.get('delta') or 0):>7.2f}{ct['mid']:>8.2f}"
            f"{c['annualised_pct']:>7.1f}{(c.get('iv30') or 0):>7.1f}{(c.get('hv20') or 0):>7.1f}"
            f"{(c.get('vrp') or 0):>6.2f}{(ct.get('open_interest') or 0):>8}"
            f"{(ct.get('spread_pct') or 0):>7.1f}{c['score']:>7.1f}  {grow_txt}")
    return "\n".join(lines)


def _portfolio_context(ctx: dict) -> str:
    lines = [
        f"DATE: {ctx.get('as_of')}",
        f"Liquid collateral ledger: ${ctx.get('collateral_available', 0):,.0f} "
        f"(Treasury ETFs + cash). Already committed to open short puts: "
        f"${ctx.get('collateral_committed', 0):,.0f}. "
        f"R4 cap is {int(COLLATERAL_CAP*100)}% of the ledger.",
        f"Open Harvest positions: {ctx.get('open_positions_desc') or 'none'}",
        f"Funding: borrowings in CHF/JPY/SGD at ~{FUNDING_COST_PCT:.1f}%. "
        f"T-bill alternative on collateral: {TBILL_YIELD_PCT:.1f}%.",
    ]
    if ctx.get("quotes_stale_any"):
        lines.append("WARNING: some quotes in this scan predate the last session — "
                     "bid/ask is unreliable and every ticket is marked for re-check.")
    if ctx.get("prior_slate_desc"):
        lines.append(f"Yesterday's slate: {ctx['prior_slate_desc']}")
    return "\n".join(lines)


def select_slate(cands: List[dict], ctx: dict, *, model: str = None,
                 client=None) -> Tuple[Optional[dict], str, dict]:
    """ONE Claude call. Returns (selection_dict, error, usage).

    The model is handed a table and a portfolio context and asked to pick at most five and say
    why. It cannot price anything — every number it might write is discarded by resolve_order().
    """
    from core.settings import (CLAUDE_DEFAULT_MODEL, CLAUDE_FAST_MODEL, extract_text,
                               get_api_key, call_claude)

    model = model or CLAUDE_DEFAULT_MODEL
    if not doctrine_available():
        return None, "Harvest doctrine file not found in harvest/.", {}
    if not cands:
        return ({"as_of": ctx.get("as_of"), "selected": [], "rejected_notable": [],
                 "market_note": "",
                 "slate_size_reason": "No candidate cleared the doctrine's gates today."},
                "", {})

    if client is None:
        api_key = get_api_key("ANTHROPIC_API_KEY")
        if not api_key or api_key.startswith("your_"):
            return None, "Anthropic API key not configured.", {}
        try:
            import anthropic
        except ImportError:
            return None, "anthropic package not installed.", {}
        client = anthropic.Anthropic(api_key=api_key, timeout=180.0, max_retries=1)

    system = [
        {"type": "text", "text": load_doctrine(), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text":
            "You are the HARVEST engine inside the Prosper app. Apply the doctrine above to "
            "today's candidates. Reply with the JSON object described in the output contract and "
            "nothing else — no memo, no preamble, no explanation outside the JSON."},
    ]
    user = (
        "PORTFOLIO CONTEXT\n" + _portfolio_context(ctx) +
        "\n\nCANDIDATES (already filtered and priced by the engine — pick from these only)\n" +
        candidates_table(cands) +
        "\n\nSelect at most 5, best first. Fewer is expected and correct when the day is thin."
    )

    try:
        resp = call_claude(
            client,
            messages=[{"role": "user", "content": user}],
            max_tokens=3000,
            preferred_model=model,
            system=system,
            thinking={"type": "disabled"},   # a selection task, not a reasoning marathon
            timeout=180,
        )
    except Exception as e:
        return None, f"Harvest selection call failed: {str(e)[:250]}", {}

    text = extract_text(resp)
    data = _extract_json(text)
    if not data:
        _log.warning("Harvest: unparseable selection, tail=%r", text[-300:])
        return None, "Harvest ran but the selection could not be parsed.", {}

    usage = _usage(resp, getattr(resp, "model", model))
    return data, "", usage


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    fences = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidates = list(reversed(fences)) or []
    start = text.find("{")
    if start != -1:
        candidates.append(text[start:])
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            try:
                return json.loads(re.sub(r",\s*([}\]])", r"\1", c))
            except json.JSONDecodeError:
                continue
    return None


def _usage(resp, model: str) -> dict:
    u = getattr(resp, "usage", None)
    p = _PRICES.get(model, _PRICES["claude-sonnet-5"])
    inp = getattr(u, "input_tokens", 0) or 0
    out = getattr(u, "output_tokens", 0) or 0
    cr = getattr(u, "cache_read_input_tokens", 0) or 0
    cw = getattr(u, "cache_creation_input_tokens", 0) or 0
    cost = (inp * p["in"] + out * p["out"] + cr * p["cache_read"] + cw * p["cache_write"]) / 1e6
    return {"input_tokens": inp, "output_tokens": out, "cache_read": cr, "cache_write": cw,
            "cost": round(cost, 5), "model_id": model}


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration — Layer 2 -> 3 -> 4 in one call
# ─────────────────────────────────────────────────────────────────────────────

def build_slate(snapshots: Dict[str, dict], metrics: Dict[str, dict],
                positions: Dict[str, dict], grow_map: Dict[str, dict],
                earnings: Dict[str, dict], *, collateral_available: float,
                collateral_committed: float = 0.0, open_underlyings: set = None,
                as_of: str = None, model: str = None, client=None,
                prior_slate_desc: str = "") -> dict:
    """The whole engine. Returns a payload ready to store and render.

    Order matters: candidates are generated and scored first, the model chooses from them, and
    only then does resolve_order() compute the numbers — so a model that hallucinates a strike
    simply has its pick dropped, and a model that picks something the caps forbid produces a
    ticket that says so rather than a wrong trade.
    """
    as_of = as_of or date.today().isoformat()
    open_underlyings = open_underlyings or set()

    rejections: List[dict] = []
    cands = generate_candidates(snapshots, metrics, positions, grow_map, earnings,
                                rejections=rejections)
    by_id = {c["candidate_id"]: c for c in cands}

    ctx = {
        "as_of": as_of,
        "collateral_available": collateral_available,
        "collateral_committed": collateral_committed,
        "open_positions_desc": ", ".join(sorted(open_underlyings)) if open_underlyings else "none",
        "quotes_stale_any": any(c.get("stale_quotes") for c in cands),
        "prior_slate_desc": prior_slate_desc,
    }

    selection, err, usage = select_slate(cands, ctx, model=model, client=client)
    if selection is None:
        return {"as_of": as_of, "error": err, "tickets": [], "candidates_considered": len(cands),
                "rejected": [], "engine_rejections": rejections, "market_note": "", "usage": {}}

    tickets: List[dict] = []
    blocked: List[dict] = []
    committed = collateral_committed
    used_underlyings = set(open_underlyings)

    # A candidate the model listed in BOTH selected and rejected_notable is a contradiction. It
    # happened on the first live run: ORCL appeared as pick #3 carrying rationale that began
    # "included here only to be explicit that it's rejected, not chosen". Trust the rejection.
    _rejected_ids = {(r or {}).get("candidate_id") for r in (selection.get("rejected_notable") or [])}

    for pick in (selection.get("selected") or [])[:5]:
        cid = (pick or {}).get("candidate_id")
        cand = by_id.get(cid)
        if not cand:
            _log.info("Harvest: model returned unknown candidate_id %r — dropped", cid)
            continue
        if cid in _rejected_ids:
            _log.info("Harvest: %s appeared in both selected and rejected — treating as rejected", cid)
            continue
        ticket = resolve_order(cand, collateral_available=collateral_available,
                               collateral_committed=committed,
                               open_underlyings=used_underlyings)
        ticket["conviction"] = (pick.get("conviction") or "medium").lower()
        ticket["why"] = pick.get("why") or ""
        ticket["risk"] = pick.get("risk") or ""
        ticket["rules_cited"] = pick.get("rules_cited") or []
        if ticket.get("blocked"):
            # Kept for the record and shown under "not offered today", but a blocked idea must
            # not occupy one of the five slots — that would silently shrink the slate.
            blocked.append(ticket)
            continue
        ticket["rank"] = len(tickets) + 1
        tickets.append(ticket)
        committed += ticket.get("collateral") or 0.0
        used_underlyings.add(ticket["ticker"])

    return {
        "as_of": as_of,
        "framework": HARVEST_VERSION,
        "market_note": selection.get("market_note") or "",
        "slate_size_reason": selection.get("slate_size_reason") or "",
        "tickets": tickets,
        "rejected": selection.get("rejected_notable") or [],
        "blocked": blocked,
        "engine_rejections": rejections,
        "candidates_considered": len(cands),
        "candidates": [
            {"candidate_id": c["candidate_id"], "ticker": c["ticker"], "strategy": c["strategy"],
             "score": c["score"], "annualised_pct": c["annualised_pct"], "vrp": c.get("vrp"),
             "strike": c["contract"]["strike"], "expiry": c["contract"]["expiry"]}
            for c in cands],
        "collateral_available": collateral_available,
        "collateral_committed_after": committed,
        "usage": usage,
        "error": "",
    }
