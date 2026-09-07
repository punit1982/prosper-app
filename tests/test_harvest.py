"""
HARVEST — tests for the deterministic layers
============================================
Layers 2 and 4 decide what you are told to trade and at what price. A wrong number here is not a
rendering glitch, it is a real order for the wrong size at the wrong price. Everything below runs
offline against hand-built chains — no network, no model, no database.

    venv/bin/python3 -m pytest tests/test_harvest.py -q
    venv/bin/python3 tests/test_harvest.py          # also works without pytest
"""

import json
import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
# yfinance segfaults (SIGSEGV, exit 139) for every ticker in the local venv on Python 3.14, and
# importing core.grow_engine pulls it in transitively. A segfault produces NO output and exit
# 139, which looks exactly like a silent pass — this suite reported "nothing" for one run before
# that was spotted. Load the inert stand-in first so the tests are self-contained.
sys.path.insert(0, os.path.join(_ROOT, "scripts", "_stub"))

from core import options_data as od          # noqa: E402
from core import vol_metrics as vm           # noqa: E402
from core import options_engine as oe        # noqa: E402
from harvest import universe as agu          # noqa: E402

TODAY = date(2026, 9, 7)


def _c(symbol, right, strike, dte, *, bid, ask, delta, oi=1000, iv=0.45, vol=100):
    return {
        "symbol": symbol, "expiry": (TODAY + timedelta(days=dte)).isoformat(), "dte": dte,
        "right": right, "strike": strike, "bid": bid, "ask": ask,
        "mid": round((bid + ask) / 2, 4),
        "spread_pct": round((ask - bid) / ((bid + ask) / 2) * 100, 2) if (bid + ask) else None,
        "iv": iv, "delta": delta, "gamma": 0.01, "theta": -0.02, "vega": 0.1,
        "open_interest": oi, "volume": vol, "theo": (bid + ask) / 2, "last_trade_time": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# OSI symbol parsing — an adjusted contract mispriced as a standard one is a real trade error
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_osi_standard():
    p = od.parse_osi("AAPL261016C00205000")
    assert p["root"] == "AAPL" and p["right"] == "C"
    assert p["strike"] == 205.0
    assert p["expiry"] == date(2026, 10, 16)


def test_parse_osi_fractional_strike():
    assert od.parse_osi("F261016P00012500")["strike"] == 12.5


def test_parse_osi_rejects_garbage():
    assert od.parse_osi("NOTACONTRACT") is None
    assert od.parse_osi("") is None
    assert od.parse_osi(None) is None


def test_adjusted_root_detected():
    # Post-split deliverables carry a suffixed root. Writing a call against one believing it is
    # standard means promising 100 shares you do not have.
    assert od.is_adjusted_root("AAPL1261016C00205000", "AAPL") is True
    assert od.is_adjusted_root("AAPL261016C00205000", "AAPL") is False


def test_index_symbols_get_underscore():
    assert od.cboe_symbol("SPX") == "_SPX"
    assert od.cboe_symbol("AAPL") == "AAPL"


# ─────────────────────────────────────────────────────────────────────────────
# Volatility maths
# ─────────────────────────────────────────────────────────────────────────────

def test_realized_vol_of_flat_series_is_zero():
    assert vm.realized_vol([100.0] * 40, 20) == 0.0


def test_realized_vol_is_annualised():
    # A series alternating +1%/-1% daily has a known daily sigma of ~0.00995 in log terms.
    closes = [100.0]
    for i in range(60):
        closes.append(closes[-1] * (1.01 if i % 2 == 0 else 1 / 1.01))
    hv = vm.realized_vol(closes, 20)
    assert 14.0 < hv < 17.0, hv          # ~0.00995 * sqrt(252) * 100


def test_realized_vol_needs_enough_data():
    assert vm.realized_vol([100, 101], 20) is None


def test_vrp_verdicts_match_doctrine_r2():
    assert vm.vrp_verdict(vm.vrp_ratio(60, 40)) == "sell"      # 1.50
    assert vm.vrp_verdict(vm.vrp_ratio(45, 40)) == "sell"      # 1.125 — at or above the floor
    assert vm.vrp_verdict(vm.vrp_ratio(41, 40)) == "neutral"   # 1.025 — inside the dead band
    assert vm.vrp_verdict(vm.vrp_ratio(38, 40)) == "neutral"   # 0.95  — inside the dead band
    assert vm.vrp_verdict(vm.vrp_ratio(30, 40)) == "buy"       # 0.75
    assert vm.vrp_verdict(None) == "unknown"


def test_vrp_boundary_is_inclusive():
    assert vm.vrp_verdict(vm.SELL_VRP_FLOOR) == "sell"
    assert vm.vrp_verdict(vm.BUY_VRP_CEILING) == "buy"


def test_iv_percentile_refuses_short_history():
    # Better no number than a percentile computed from three weeks of data.
    assert vm.iv_percentile(50, [40] * 50) is None
    assert vm.iv_percentile(50, [40] * 200) == 100.0
    assert vm.iv_percentile(30, [40] * 200) == 0.0


def test_the_crdo_case():
    """The trade the engine exists to refuse.

    CRDO showed IV30 71.9 against realized 111.0 on 06-Sep-2026 — a 72% headline IV that a
    yield-ranked screen would have put near the top of the book, and the worst name in it to sell
    calls on.
    """
    assert vm.vrp_verdict(vm.vrp_ratio(71.9, 111.0)) == "buy"


# ─────────────────────────────────────────────────────────────────────────────
# Price and tick handling
# ─────────────────────────────────────────────────────────────────────────────

def test_tick_rounding_penny_pilot():
    assert oe._round_to_tick(2.437) == 2.44        # below $3 -> penny
    assert oe._round_to_tick(6.42) == 6.40         # at/above $3 -> nickel
    assert oe._round_to_tick(6.48) == 6.50


def test_limit_price_never_crosses_the_spread():
    p = oe._limit_price(1.00, 1.30, selling=True)
    assert 1.00 <= p <= 1.30
    p2 = oe._limit_price(1.00, 1.30, selling=False)
    assert 1.00 <= p2 <= 1.30
    # Selling asks below mid; buying offers above it.
    assert p < 1.15 and p2 > 1.15


def test_limit_price_handles_missing_market():
    assert oe._limit_price(0, 0, selling=True) == 0.0
    assert oe._limit_price(None, 1.2, selling=True) == 0.0


def test_annualise_is_simple_not_compounded():
    assert round(oe._annualise(4.0, 365), 4) == 4.0
    assert round(oe._annualise(1.0, 30), 2) == 12.17
    assert oe._annualise(5.0, 0) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Doctrine R1 — the keystone
# ─────────────────────────────────────────────────────────────────────────────

def _ctx(ticker, spot, contracts, *, shares=0, grow=None, vrp=1.4, iv=60.0, hv=42.0):
    rejects = []
    return {
        "ticker": ticker, "spot": spot, "contracts": contracts,
        "metrics": {"vrp": vrp, "vrp_verdict": vm.vrp_verdict(vrp), "iv30": iv, "hv20": hv,
                    "term_structure": 2.0},
        "position": {"shares": shares},
        "grow": oe._grow_for(ticker, {ticker: grow} if grow else {}),
        "earnings": None, "stale_quotes": False,
        "reject": lambda s, w: rejects.append({"strategy": s, "reason": w}),
    }, rejects


def test_r1_blocks_calls_below_grow_fair_high():
    """A BUY-rated name may only be written at or above its fair-high rung."""
    contracts = [
        _c("X261016C00110000", "C", 110.0, 39, bid=3.0, ask=3.2, delta=0.30),   # below fair_high
        _c("X261016C00130000", "C", 130.0, 39, bid=1.2, ask=1.3, delta=0.18),   # above fair_high
    ]
    ctx, _ = _ctx("X", 100.0, contracts, shares=400,
                  grow={"entry_verdict": "BUY", "durability": 70, "fair_high": 125.0,
                        "analysis_date": date.today().isoformat()})
    out = oe._covered_call_candidates(ctx)
    strikes = {c["contract"]["strike"] for c in out}
    assert strikes == {130.0}, strikes


def test_r1_buy_rated_without_a_ladder_stands_aside():
    contracts = [_c("X261016C00110000", "C", 110.0, 39, bid=3.0, ask=3.2, delta=0.30)]
    ctx, rejects = _ctx("X", 100.0, contracts, shares=400,
                        grow={"entry_verdict": "STRONG BUY", "durability": 80,
                              "analysis_date": date.today().isoformat()})
    assert oe._covered_call_candidates(ctx) == []
    assert any("fair-high" in r["reason"] for r in rejects)


def test_r1_put_ceiling_binds_even_for_universe_names():
    """Membership of the assignment-grade universe says the name is sound, not that any price
    for it is acceptable. This regressed once: an ORCL 148 put was proposed against a $135
    buy-below rung."""
    contracts = [
        _c("ORCL261016P00148000", "P", 148.0, 39, bid=7.0, ask=7.1, delta=-0.32),
        _c("ORCL261016P00135000", "P", 135.0, 39, bid=3.0, ask=3.1, delta=-0.20),
    ]
    ctx, _ = _ctx("ORCL", 159.7, contracts,
                  grow={"entry_verdict": "HOLD", "durability": 72, "buy_below": 135.0,
                        "fair_high": 178.0, "analysis_date": date.today().isoformat()})
    out = oe._cash_secured_put_candidates(ctx)
    assert all(c["contract"]["strike"] <= 135.0 for c in out), \
        [c["contract"]["strike"] for c in out]


# ─────────────────────────────────────────────────────────────────────────────
# Doctrine R2 — never sell cheap volatility
# ─────────────────────────────────────────────────────────────────────────────

def test_r2_blocks_selling_when_options_are_cheap():
    contracts = [_c("X261016C00110000", "C", 110.0, 39, bid=3.0, ask=3.2, delta=0.30)]
    ctx, rejects = _ctx("X", 100.0, contracts, shares=400, vrp=0.65, iv=71.9, hv=111.0)
    assert oe._covered_call_candidates(ctx) == []
    assert any("R2" in r["reason"] for r in rejects)


# ─────────────────────────────────────────────────────────────────────────────
# Doctrine R5 / R4 / R7 — the caps
# ─────────────────────────────────────────────────────────────────────────────

def test_r5_one_contract_lot_yields_no_covered_call():
    """int(1 * 0.50) is zero contracts — the idea does not exist and must not reach the model."""
    contracts = [_c("X261016C00110000", "C", 110.0, 39, bid=3.0, ask=3.2, delta=0.30)]
    ctx, rejects = _ctx("X", 100.0, contracts, shares=100)
    assert oe._covered_call_candidates(ctx) == []
    assert any("rounds to zero" in r["reason"] for r in rejects)


def test_r5_caps_coverage_at_half_the_lot():
    contracts = [_c("X261016C00110000", "C", 110.0, 39, bid=3.0, ask=3.2, delta=0.30)]
    ctx, _ = _ctx("X", 100.0, contracts, shares=1000)          # 10 contracts possible
    cand = oe._covered_call_candidates(ctx)[0]
    cand.update({"candidate_id": "T-1", "spot": 100.0, "grow": ctx["grow"], "score": 50,
                 "stale_quotes": False, "earnings": None})
    t = oe.resolve_order(cand, collateral_available=100000)
    assert t["contracts"] == 5


def test_r5_tightens_to_a_third_on_high_conviction():
    contracts = [_c("X261016C00130000", "C", 130.0, 39, bid=1.2, ask=1.3, delta=0.20)]
    ctx, _ = _ctx("X", 100.0, contracts, shares=900,
                  grow={"entry_verdict": "BUY", "durability": 75, "fair_high": 125.0,
                        "analysis_date": date.today().isoformat()})
    cand = oe._covered_call_candidates(ctx)[0]
    cand.update({"candidate_id": "T-1", "spot": 100.0, "grow": ctx["grow"], "score": 50,
                 "stale_quotes": False, "earnings": None})
    t = oe.resolve_order(cand, collateral_available=100000)
    # 33% of a 9-contract lot is 2.97 — and 3 of 9 would be 33.3%, over the cap. Round down.
    assert t["contracts"] == 2


def test_r4_collateral_cap_blocks_when_the_ledger_is_full():
    contracts = [_c("NKE261016P00035000", "P", 35.0, 39, bid=0.80, ask=0.84, delta=-0.23)]
    ctx, _ = _ctx("NKE", 38.42, contracts)
    cand = oe._cash_secured_put_candidates(ctx)[0]
    cand.update({"candidate_id": "T-1", "spot": 38.42, "grow": ctx["grow"], "score": 50,
                 "stale_quotes": False, "earnings": None})
    t = oe.resolve_order(cand, collateral_available=10000, collateral_committed=9999)
    assert t["blocked"] and "R4" in t["blocked"]


def test_r4_never_commits_more_than_sixty_percent_of_the_ledger():
    contracts = [_c("NKE261016P00035000", "P", 35.0, 39, bid=0.80, ask=0.84, delta=-0.23)]
    ctx, _ = _ctx("NKE", 38.42, contracts)
    cand = oe._cash_secured_put_candidates(ctx)[0]
    cand.update({"candidate_id": "T-1", "spot": 38.42, "grow": ctx["grow"], "score": 50,
                 "stale_quotes": False, "earnings": None})
    t = oe.resolve_order(cand, collateral_available=100000)
    assert t["collateral"] <= 100000 * oe.COLLATERAL_CAP


def test_r7_blocks_a_second_position_in_the_same_underlying():
    contracts = [_c("NKE261016P00035000", "P", 35.0, 39, bid=0.80, ask=0.84, delta=-0.23)]
    ctx, _ = _ctx("NKE", 38.42, contracts)
    cand = oe._cash_secured_put_candidates(ctx)[0]
    cand.update({"candidate_id": "T-1", "spot": 38.42, "grow": ctx["grow"], "score": 50,
                 "stale_quotes": False, "earnings": None})
    t = oe.resolve_order(cand, collateral_available=500000, open_underlyings={"NKE"})
    assert t["blocked"] and "R7" in t["blocked"]


# ─────────────────────────────────────────────────────────────────────────────
# Doctrine R6 — earnings blackout
# ─────────────────────────────────────────────────────────────────────────────

def test_r6_earnings_inside_the_window_blocks_the_trade():
    expiry = (TODAY + timedelta(days=39)).isoformat()
    inside = {"date": (TODAY + timedelta(days=20)).isoformat(), "hour": "amc"}
    outside = {"date": (TODAY + timedelta(days=60)).isoformat(), "hour": "bmo"}
    assert od.earnings_before(expiry, inside, TODAY) is True
    assert od.earnings_before(expiry, outside, TODAY) is False
    assert od.earnings_before(expiry, None, TODAY) is False      # unknown reads as clear


# ─────────────────────────────────────────────────────────────────────────────
# Protection cost ceiling
# ─────────────────────────────────────────────────────────────────────────────

def test_protection_that_costs_too_much_is_refused():
    """ENVX at $3.42 offered a $3.00 put at $0.21 — 6.1% of the position for 39 days. Cheap by
    IV-vs-realized and ruinous in absolute terms."""
    contracts = [_c("ENVX261016P00003000", "P", 3.0, 39, bid=0.20, ask=0.22, delta=-0.29,
                    iv=0.79)]
    ctx, _ = _ctx("ENVX", 3.42, contracts, shares=3000, vrp=0.80, iv=79.2, hv=99.5)
    assert oe._protective_put_candidates(ctx) == []


def test_affordable_protection_is_allowed():
    contracts = [_c("X261016P00090000", "P", 90.0, 39, bid=1.00, ask=1.06, delta=-0.25)]
    ctx, _ = _ctx("X", 100.0, contracts, shares=500, vrp=0.75, iv=30.0, hv=40.0)
    out = oe._protective_put_candidates(ctx)
    assert len(out) == 1 and out[0]["strategy"] == "protective_put"


# ─────────────────────────────────────────────────────────────────────────────
# Ticket arithmetic
# ─────────────────────────────────────────────────────────────────────────────

def test_covered_call_ticket_numbers():
    contracts = [_c("X261016C00110000", "C", 110.0, 39, bid=3.00, ask=3.20, delta=0.30)]
    ctx, _ = _ctx("X", 100.0, contracts, shares=400)
    cand = oe._covered_call_candidates(ctx)[0]
    cand.update({"candidate_id": "T-1", "spot": 100.0, "grow": ctx["grow"], "score": 60,
                 "stale_quotes": False, "earnings": None})
    t = oe.resolve_order(cand, collateral_available=100000)

    assert t["contracts"] == 2                                   # 50% of a 4-contract lot
    assert t["action"] == "SELL"
    assert t["limit_price"] == 3.05                              # mid 3.10, a third toward the bid
    assert t["gross_premium"] == 610.0                           # 3.05 * 100 * 2
    assert t["net_premium"] == 610.0 - 2 * oe.COMMISSION_PER_CONTRACT
    assert t["breakeven"] == 96.95                               # spot - premium
    assert t["effective_sale_price"] == 113.05                   # strike + premium
    assert t["exit_profit_target"] == oe._round_to_tick(3.05 * 0.35)
    assert t["max_loss"] is None                                 # covered: the shares are the risk
    assert "R1 cannot be evaluated" in t["grow_note"]            # no verdict supplied
    assert not t["grow_note"].startswith("GROW")                  # the UI supplies that label


def test_cash_secured_put_states_the_cost_of_assignment():
    contracts = [_c("NKE261016P00035000", "P", 35.0, 39, bid=0.80, ask=0.84, delta=-0.23)]
    ctx, _ = _ctx("NKE", 38.42, contracts)
    cand = oe._cash_secured_put_candidates(ctx)[0]
    cand.update({"candidate_id": "T-1", "spot": 38.42, "grow": ctx["grow"], "score": 55,
                 "stale_quotes": False, "earnings": None})
    t = oe.resolve_order(cand, collateral_available=100000)
    assert t["assignment_cost"] == 35.0 * 100 * t["contracts"]
    assert t["collateral"] == t["assignment_cost"]
    assert t["breakeven"] == round(35.0 - t["limit_price"], 2)
    assert "you buy" in t["assignment_outcome"]


def test_every_sold_ticket_carries_an_exit():
    """Doctrine R8 — a trade without a written exit is not a recommendation."""
    contracts = [_c("NKE261016P00035000", "P", 35.0, 39, bid=0.80, ask=0.84, delta=-0.23)]
    ctx, _ = _ctx("NKE", 38.42, contracts)
    cand = oe._cash_secured_put_candidates(ctx)[0]
    cand.update({"candidate_id": "T-1", "spot": 38.42, "grow": ctx["grow"], "score": 55,
                 "stale_quotes": False, "earnings": None})
    t = oe.resolve_order(cand, collateral_available=100000)
    assert t["exit_profit_target"] and t["exit_note"] and t["roll_trigger"]
    assert t["assignment_outcome"]


def test_missing_grow_verdict_is_flagged_provisional():
    contracts = [_c("NKE261016P00035000", "P", 35.0, 39, bid=0.80, ask=0.84, delta=-0.23)]
    ctx, _ = _ctx("NKE", 38.42, contracts)
    cand = oe._cash_secured_put_candidates(ctx)[0]
    cand.update({"candidate_id": "T-1", "spot": 38.42, "grow": ctx["grow"], "score": 55,
                 "stale_quotes": False, "earnings": None})
    t = oe.resolve_order(cand, collateral_available=100000)
    assert any("PROVISIONAL" in w for w in t["warnings"])


# ─────────────────────────────────────────────────────────────────────────────
# Quote staleness — the weekend problem
# ─────────────────────────────────────────────────────────────────────────────

def test_stale_quotes_are_detected_and_warned():
    assert od.quote_is_stale("2020-01-01 12:00:00") is True
    assert od.quote_is_stale(None) is True
    assert od.quote_is_stale("not a timestamp") is True
    from datetime import datetime as _dt
    fresh = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    assert od.quote_is_stale(fresh) is False


# ─────────────────────────────────────────────────────────────────────────────
# Universe
# ─────────────────────────────────────────────────────────────────────────────

def test_universe_is_fifty_names():
    assert len(agu.universe_tickers(include_hedge=False)) == 50


def test_tier_c_names_are_never_put_writable():
    assert agu.put_writable("LLY") is False        # $1,140 -> $114k per contract
    assert agu.put_writable("NKE") is True         # $38 -> $3.8k


def test_tiering_follows_live_price_not_the_snapshot():
    assert agu.tier_for_price(50) == agu.TIER_A
    assert agu.tier_for_price(200) == agu.TIER_B
    assert agu.tier_for_price(600) == agu.TIER_C


def test_hedge_annex_is_not_for_selling():
    assert agu.put_writable("SPY") is False
    assert agu.meta("SPY")["role"] == "hedge"


def test_sector_margin_floors_are_relative():
    """A single absolute net-margin gate wrongly flagged WMT, COST and UNH as weak."""
    assert agu.margin_floor("Consumer Staples") < agu.margin_floor("Information Technology")


# ─────────────────────────────────────────────────────────────────────────────
# Chain slicing
# ─────────────────────────────────────────────────────────────────────────────

def test_slice_chain_drops_adjusted_and_far_strikes():
    data = {
        "current_price": 100.0, "_underlying": "X",
        "options": [
            {"option": "X261016C00110000", "bid": 1, "ask": 1.1, "delta": 0.3, "open_interest": 10},
            {"option": "X1261016C00110000", "bid": 1, "ask": 1.1, "delta": 0.3, "open_interest": 10},
            {"option": "X261016C00500000", "bid": 0.01, "ask": 0.05, "delta": 0.01, "open_interest": 1},
        ],
    }
    out = od.slice_chain(data, today=TODAY)
    assert [c["symbol"] for c in out] == ["X261016C00110000"]


def test_slice_chain_survives_a_missing_spot():
    assert od.slice_chain({"current_price": None, "options": []}, today=TODAY) == []


# ─────────────────────────────────────────────────────────────────────────────
# GROW batch targeting — both bugs here shipped and cost real money
# ─────────────────────────────────────────────────────────────────────────────

def _grow_batch():
    import importlib.util as _u
    spec = _u.spec_from_file_location(
        "grow_batch", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "scripts", "grow_batch.py"))
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_netflix_is_not_a_fund():
    """A substring match on "etf" classified NETFLIX as a fund — n-ETF-lix. It ran in
    production and silently dropped a real holding from the analysis list."""
    assert _grow_batch()._looks_like_fund("NFLX", "Netflix Inc") is False


def test_real_businesses_are_kept():
    m = _grow_batch()
    for t, n in [("ADBE", "ADOBE INC"), ("HIMS", "HIMS & HERS HEALTH"),
                 ("EMAAR.AE", "EMAAR PROPERTIES"), ("SREN.SW", "SWISS RE AG"),
                 ("CRM", "SALESFORCE INC"), ("IREN", "IREN LTD")]:
        assert m._looks_like_fund(t, n) is False, t


def test_wrappers_are_skipped():
    """GROW scores businesses. A durability memo on a Treasury ETF is $1.40 for nothing."""
    m = _grow_batch()
    for t, n in [("U03A.L", "iShares Treasury Bond ETF"), ("JEPG", "JPM GB EQ PR IN ACT"),
                 ("PDI", "Pimco Dynamic Inco"), ("QYLD", "GX NASDAQ 100 COV C"),
                 ("IAU", "ISHARES GOLD TRUST"), ("NDIA", "iShares MSCI India UCITS ETF")]:
        assert m._looks_like_fund(t, n) is True, t


def test_isin_shaped_tickers_are_skipped():
    m = _grow_batch()
    assert m._looks_like_fund("LU1255915586", "Allianz Income And") is True
    assert m._looks_like_fund("I288654906", "FRANKLIN INCOME FU") is True
    assert m._looks_like_fund("MF:12345", "Some Mutual Fund") is True
    assert m._looks_like_fund("RESTRICTED:NIQ", "Unvested award") is True


# ─────────────────────────────────────────────────────────────────────────────
# SEC EDGAR — primary filing data. Offline: no network, synthetic facts.
# ─────────────────────────────────────────────────────────────────────────────

from core import edgar_client as ec          # noqa: E402


def _facts(**concepts):
    """Build a companyfacts-shaped payload from {concept: [observations]}."""
    us, dei = {}, {}
    for name, obs in concepts.items():
        target = dei if name.startswith("Entity") else us
        target[name] = {"units": {"shares" if "Shares" in name else "USD": obs}}
    return {"entityName": "Test Co", "facts": {"us-gaap": us, "dei": dei}}


def _obs(end, val, *, form="10-K", start=None, fy=2025, accn="0001-25-000001"):
    o = {"end": end, "val": val, "form": form, "fy": fy, "fp": "FY",
         "filed": "2026-01-15", "accn": accn}
    if start:
        o["start"] = start
    return o


def test_ticker_to_cik_rejects_non_us_listings():
    """A suffixed ticker is not a US filer by construction. Without this guard SREN.SW could
    match a same-named US company and the memo would cite the wrong entity's filings."""
    for t in ("SREN.SW", "EMAAR.AE", "543895.BO", "4519.T", "U03A.L", "D05.SI"):
        assert ec.ticker_to_cik(t) is None, t


def test_revenue_falls_back_across_concepts():
    """HIMS tags revenue ONLY as RevenueFromContractWithCustomerExcludingAssessedTax and has no
    `Revenues` concept at all — a single-concept lookup returns nothing for it."""
    f = _facts(RevenueFromContractWithCustomerExcludingAssessedTax=[
        _obs("2025-12-31", 1_500_000_000, start="2025-01-01")])
    out = ec.extract_financials(f)
    assert out["revenue"]["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert out["revenue"]["observations"][0]["value"] == 1_500_000_000


def test_preferred_concept_wins_when_several_exist():
    f = _facts(
        Revenues=[_obs("2025-12-31", 999, start="2025-01-01")],
        RevenueFromContractWithCustomerExcludingAssessedTax=[
            _obs("2025-12-31", 1000, start="2025-01-01")])
    assert ec.extract_financials(f)["revenue"]["observations"][0]["value"] == 1000


def test_quarterly_durations_are_excluded_from_annual_figures():
    """A 10-K carries quarterly duration facts too. Taking one as the annual revenue understates
    the business by ~4x."""
    f = _facts(Revenues=[
        _obs("2025-12-31", 250, start="2025-10-01"),      # a quarter inside the 10-K
        _obs("2025-12-31", 1000, start="2025-01-01"),     # the actual year
    ])
    assert ec.extract_financials(f)["revenue"]["observations"][0]["value"] == 1000


def test_every_observation_carries_provenance():
    """Provenance is the whole reason this beats a web fetch."""
    f = _facts(Revenues=[_obs("2025-12-31", 1000, start="2025-01-01", accn="0000796343-26-000003")])
    o = ec.extract_financials(f)["revenue"]["observations"][0]
    assert o["accn"] == "0000796343-26-000003"
    assert o["form"] == "10-K" and o["filed"] == "2026-01-15"


def test_restated_periods_keep_the_later_filing():
    f = _facts(Revenues=[
        {"end": "2024-12-31", "val": 900, "start": "2024-01-01", "form": "10-K",
         "fy": 2024, "fp": "FY", "filed": "2025-01-10", "accn": "old"},
        {"end": "2024-12-31", "val": 950, "start": "2024-01-01", "form": "10-K",
         "fy": 2025, "fp": "FY", "filed": "2026-01-15", "accn": "new"},
    ])
    obs = ec.extract_financials(f)["revenue"]["observations"]
    assert len([o for o in obs if o["end"] == "2024-12-31"]) == 1
    assert obs[0]["accn"] == "new"


def test_untagged_metrics_are_reported_not_invented():
    f = _facts(Revenues=[_obs("2025-12-31", 1000, start="2025-01-01")])
    out = ec.extract_financials(f)
    assert "revenue" in out
    assert "long_term_debt" not in out          # absent, and must not be fabricated


def test_snapshot_returns_none_for_non_filers():
    assert ec.filing_snapshot("EMAAR.AE") is None
    assert ec.filing_snapshot("") is None


def test_grow_snapshot_separates_primary_from_aggregator():
    """If the model is told as-filed XBRL is Tier-5 aggregator data it will re-fetch it, and the
    entire saving evaporates."""
    from core import grow_engine as ge
    edgar = {"text": "SEC EDGAR XBRL — PRIMARY FILING DATA\nRevenue: 1000"}
    text, _ = ge.build_data_snapshot("TEST", info={"longName": "T"}, edgar=edgar)
    assert text.index("PRIMARY FILING DATA") < text.index("Tier-5 aggregator data")
    assert "confirmation only" in text


# ─────────────────────────────────────────────────────────────────────────────
# Cowork import — the §8 resolver must override a hand-produced memo exactly as
# it overrides an API one, or the two paths drift and Rule 1 reads a wrong ladder.
# ─────────────────────────────────────────────────────────────────────────────

def _cowork_reply(**over):
    entry = {"verdict": "HOLD", "price": 259.40, "required_return": 0.109,
             "base_cost_of_equity": 0.089, "cash_returned": 8.0, "central_value": 340.0,
             # Deliberately absurd — the resolver must replace every one of these.
             "ladder": {"strong_buy_below": 1.0, "buy_below": 2.0, "acceptable_below": 3.0,
                        "fair_high": 4.0, "reduce_above": 4.0},
             "caps": [], "ceilings": []}
    entry.update(over.pop("entry", {}))
    payload = {
        "ticker": "CRM", "company": "Salesforce, Inc.",
        "classification": {"archetype": "T2", "horizon_years": 4.0},
        "durability": {"score": 71, "band": "Strong", "integrity_level": "0", "criteria": []},
        "entry": entry,
        "cases": {"base": {"price": 340.0}, "bull": {"price": 460.0}},
        "confidence": "reasonably confident", "uncertainties": [],
    }
    payload.update(over)
    return "# Memo\n\nSome prose.\n\n```json\n" + json.dumps(payload) + "\n```\n"


def _assemble(text, ticker="CRM", price=259.40):
    from core import grow_engine as ge
    data = ge._extract_json_block(text)
    return ge.assemble_result(ticker, data, ge._strip_json_block(text), tier="cowork",
                              price_quote={"price": price, "source": "test"})


def test_cowork_ladder_is_recomputed_not_trusted():
    """The memo's ladder said 1.0 / 2.0 / 4.0. Python must replace all of it."""
    res, err = _assemble(_cowork_reply())
    assert res, err
    assert res["fair_high"] == 348.0                       # central 340 + cash 8
    assert abs(res["buy_below"] - 230.07) < 0.5            # 348 / 1.109^4
    assert abs(res["strong_buy_below"] - 174.12) < 0.5     # 348 / 1.189^4
    assert res["buy_below"] > 2.0 and res["fair_high"] > 4.0


def test_cowork_verdict_is_recomputed_from_the_arithmetic():
    """§8.1 is a table, not an opinion. A memo claiming STRONG BUY on numbers that do not
    support it gets corrected, and the disagreement is recorded."""
    res, _ = _assemble(_cowork_reply(entry={"verdict": "STRONG BUY"}))
    assert res["entry_verdict"] == "HOLD"
    assert res["model_entry_verdict"] == "STRONG BUY"
    assert any("recomputed by arithmetic" in u for u in res["uncertainties"])


def test_cowork_import_matches_the_api_path_exactly():
    """Both paths go through assemble_result, so identical JSON must give identical numbers."""
    from core import grow_engine as ge
    text = _cowork_reply()
    data = ge._extract_json_block(text)
    a, _ = ge.assemble_result("CRM", data, "", tier="cowork",
                              price_quote={"price": 259.40, "source": "t"})
    b, _ = ge.assemble_result("CRM", data, "", tier="full_lean",
                              price_quote={"price": 259.40, "source": "t"})
    for k in ("entry_verdict", "durability", "buy_below", "strong_buy_below",
              "fair_high", "acceptable_below", "cagr_spot"):
        assert a[k] == b[k], k


def test_cowork_rejects_a_missing_durability_score():
    """Rule 20: a run without a Durability score is rejected, not filed with a blank."""
    res, err = _assemble(_cowork_reply(durability={"band": "Strong"}))
    assert res is None and "Durability" in err


def test_cowork_needs_a_price_to_solve_against():
    from core import grow_engine as ge
    text = _cowork_reply(entry={"price": None})
    data = ge._extract_json_block(text)
    res, _ = ge.assemble_result("CRM", data, "", tier="cowork", price_quote=None)
    # No price means no ladder — the resolver returns nothing rather than inventing one.
    assert res is None or res.get("buy_below") in (None, 2.0)


def test_brief_carries_the_primary_data_divider():
    """The brief must tell Cowork which half of the snapshot is Class A, or it re-fetches it."""
    from core import grow_engine as ge
    text, _ = ge.build_data_snapshot(
        "TEST", info={"longName": "T"},
        edgar={"text": "SEC EDGAR XBRL — PRIMARY FILING DATA\nRevenue: 1000"})
    assert "PRIMARY FILING DATA" in text and "Tier-5 aggregator data" in text


if __name__ == "__main__":
    import traceback
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in fns:
        try:
            fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed, {len(fns)} total")
    sys.exit(1 if failed else 0)
