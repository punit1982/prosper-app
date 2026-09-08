#!/usr/bin/env python3
"""
Offline tests for the quote pipeline — no network, no database, no model.

The pipeline's job is routing and failover, and both are pure logic, so both
can be tested exactly. Providers are replaced with fakes that return canned
rows, which is the only way to assert "tier 2 was asked for precisely the
tickers tier 1 could not price" without depending on whether a vendor is up.

    venv/bin/python3 tests/test_market_data.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import market_data as md              # noqa: E402
from core import symbology as sym               # noqa: E402
from core.market_data import Quote              # noqa: E402

_passed = 0
_failed: list = []


def check(label, got, want):
    global _passed
    if got == want:
        _passed += 1
    else:
        _failed.append(f"{label}\n      got:  {got!r}\n      want: {want!r}")


def check_true(label, cond):
    check(label, bool(cond), True)


# ─────────────────────────────────────────────────────────────────────────────
# symbology — identity and routing
# ─────────────────────────────────────────────────────────────────────────────

def test_split():
    check("split US", sym.split_ticker("ADBE"), ("ADBE", ""))
    check("split suffix", sym.split_ticker("ALDAR.AE"), ("ALDAR", "AE"))
    check("split Tokyo numeric", sym.split_ticker("7974.T"), ("7974", "T"))
    # Twelve Data's colon form still sits in old ticker_cache rows.
    check("split colon form", sym.split_ticker("EMAAR:DFM"), ("EMAAR", "DFM"))
    check("split BSE numeric", sym.split_ticker("543895.BO"), ("543895", "BO"))


def test_classify_by_suffix():
    check("US default", sym.classify("ADBE"), sym.US)
    check("UAE .AE", sym.classify("ALDAR.AE"), sym.UAE)
    # The source review says ADX is .AD; Prosper writes .AE. Both must route to
    # UAE or half the book silently falls off the map.
    check("UAE .AD", sym.classify("FAB.AD"), sym.UAE)
    check("Japan", sym.classify("7974.T"), sym.JAPAN)
    check("Swiss", sym.classify("NESN.SW"), sym.SWISS)
    check("LSE", sym.classify("IB01.L"), sym.LSE)
    check("SGX", sym.classify("5E2.SI"), sym.SGX)
    check("India NSE", sym.classify("RELIANCE.NS"), sym.INDIA_EQ)
    check("Milan is Europe", sym.classify("PRY.MI"), sym.EUROPE)
    check("Toronto", sym.classify("VNP.TO"), sym.CANADA)
    check("Korea", sym.classify("000660.KS"), sym.KOREA)


def test_broker_exchange_beats_suffix():
    """The statement's listing exchange is the only field that actually knows.

    IBKR writes Toronto as "TSE", which as a Yahoo suffix would mean Tokyo. A
    suffix-first router gets this exactly backwards.
    """
    check("IBKR TSE = Toronto, not Tokyo",
          sym.classify("VNP", listing_exchange="TSE"), sym.CANADA)
    check("IBKR TSEJ = Tokyo",
          sym.classify("7974", listing_exchange="TSEJ"), sym.JAPAN)
    check("IBKR EBS = Swiss",
          sym.classify("NESN", listing_exchange="EBS"), sym.SWISS)
    check("IBKR ADX = UAE with no suffix at all",
          sym.classify("ALDAR", listing_exchange="ADX"), sym.UAE)
    check("IBKR LSEETF = LSE",
          sym.classify("IB01", listing_exchange="LSEETF"), sym.LSE)
    check("FUNDSERV = offshore fund",
          sym.classify("IBCID288654906", listing_exchange="FUNDSERV"), sym.FUND_OFFSHORE)


def test_classify_funds():
    check("Indian ISIN fund -> AMFI",
          sym.classify("SOMEFUND", isin="INF846K01WO1", asset_category="Fund"),
          sym.INDIA_FUND)
    # The legacy bug: a Morningstar fund id given a fake ".NS" suffix. It is a
    # fund, not an equity, and must never be sent to an equity quote provider.
    check("legacy F0*.NS is a fund, not NSE equity",
          sym.classify("F00000ABCD.NS", asset_category="Fund"), sym.INDIA_FUND)
    check("offshore SICAV",
          sym.classify("FTIFWAU", asset_category="Fund"), sym.FUND_OFFSHORE)


def test_build_and_tv_symbols():
    inst = sym.build("ALDAR.AE", listing_exchange="ADX", isin="AEA002001013",
                     conid="789881669", currency="AED")
    check("build market", inst.market, sym.UAE)
    check("build base", inst.base, "ALDAR")
    check("build isin", inst.isin, "AEA002001013")
    # Broker told us the venue, so exactly one candidate — no shotgunning.
    check("tv symbol from broker exchange",
          sym.tradingview_symbols(inst), ["ADX:ALDAR"])

    # No listing exchange: try every venue in the market, misses cost nothing.
    bare = sym.build("EMAAR.AE")
    check("tv candidates without broker hint",
          sorted(sym.tradingview_symbols(bare)), ["ADX:EMAAR", "DFM:EMAAR"])

    check("scan group for UAE", sym.scan_group(sym.UAE), "uae")
    check("scan group for unknown market", sym.scan_group(sym.UNKNOWN), None)


def test_pence_flag():
    check_true("LSE flagged as pence-quoting", sym.build("IB01.L").quotes_in_pence)
    check("US not pence-quoting", sym.build("ADBE").quotes_in_pence, False)


# ─────────────────────────────────────────────────────────────────────────────
# pipeline — tiering, failover, provenance
# ─────────────────────────────────────────────────────────────────────────────

class FakeProvider:
    """Prices only the tickers it was told to, and records what it was asked."""

    def __init__(self, name, prices, latency=md.DELAYED, raises=False):
        self.name = name
        self._prices = prices
        self.latency = latency
        self._raises = raises
        self.asked: list = []

    def fetch(self, insts):
        self.asked.append([i.ticker for i in insts])
        if self._raises:
            raise RuntimeError("provider is down")
        return {
            i.ticker: Quote(symbol=i.ticker, price=self._prices[i.ticker],
                            currency="USD", source=self.name,
                            latency=self.latency, asof=1234.0)
            for i in insts if i.ticker in self._prices
        }


def _with_tiers(market, providers, fn):
    original = md.TIERS.get(market)
    md.TIERS[market] = providers
    try:
        return fn()
    finally:
        if original is None:
            md.TIERS.pop(market, None)
        else:
            md.TIERS[market] = original


def test_first_tier_wins():
    t1 = FakeProvider("t1", {"AAA": 10.0, "BBB": 20.0})
    t2 = FakeProvider("t2", {"AAA": 99.0, "BBB": 99.0})
    insts = [sym.build("AAA"), sym.build("BBB")]
    quotes, report = _with_tiers(sym.US, [t1, t2], lambda: md.fetch_quotes(insts))
    check("tier 1 prices both", quotes["AAA"].price, 10.0)
    check("tier 1 source recorded", quotes["BBB"].source, "t1")
    # The point of tiering: tier 2 is never even called when tier 1 is complete.
    check("tier 2 never called", t2.asked, [])
    check("report counts", (report.requested, report.priced), (2, 2))


def test_failover_asks_only_for_the_gap():
    t1 = FakeProvider("t1", {"AAA": 10.0})
    t2 = FakeProvider("t2", {"BBB": 20.0, "CCC": 30.0})
    insts = [sym.build(t) for t in ("AAA", "BBB", "CCC")]
    quotes, report = _with_tiers(sym.US, [t1, t2], lambda: md.fetch_quotes(insts))
    check("tier 1 result kept", quotes["AAA"].source, "t1")
    check("tier 2 filled the gap", quotes["BBB"].source, "t2")
    # This is the efficiency claim: tier 2 is handed the two it needs, not all three.
    check("tier 2 asked only for unpriced", sorted(t2.asked[0]), ["BBB", "CCC"])
    check("everything priced", report.priced, 3)


def test_a_raising_provider_does_not_stop_the_walk():
    broken = FakeProvider("broken", {}, raises=True)
    good = FakeProvider("good", {"AAA": 42.0})
    quotes, report = _with_tiers(sym.US, [broken, good],
                                 lambda: md.fetch_quotes([sym.build("AAA")]))
    check("walk continued past the exception", quotes["AAA"].price, 42.0)
    check("priced despite failure", report.priced, 1)


def test_unpriced_is_reported_not_hidden():
    t1 = FakeProvider("t1", {"AAA": 10.0})
    insts = [sym.build("AAA"), sym.build("ZZZ")]
    quotes, report = _with_tiers(sym.US, [t1], lambda: md.fetch_quotes(insts))
    check("only the priced one returned", sorted(quotes), ["AAA"])
    check("the gap is named", report.unpriced, ["ZZZ"])
    check("counts are honest", (report.requested, report.priced), (2, 1))


def test_markets_are_routed_independently():
    us = FakeProvider("us-only", {"ADBE": 266.0})
    uae = FakeProvider("uae-only", {"ALDAR.AE": 7.81})
    insts = [sym.build("ADBE"), sym.build("ALDAR.AE")]

    def run():
        return _with_tiers(sym.UAE, [uae], lambda: md.fetch_quotes(insts))

    quotes, _ = _with_tiers(sym.US, [us], run)
    check("US routed to US provider", quotes["ADBE"].source, "us-only")
    check("UAE routed to UAE provider", quotes["ALDAR.AE"].source, "uae-only")
    # A US provider must never be handed a UAE ticker — that is the 403-per-name
    # waste the old global cascade produced.
    check("US provider saw only US", us.asked, [["ADBE"]])
    check("UAE provider saw only UAE", uae.asked, [["ALDAR.AE"]])


def test_provenance_survives_to_the_cache_row():
    q = Quote(symbol="ALDAR.AE", price=7.81, currency="AED", source="tradingview",
              latency=md.DELAYED, asof=1000.0, change=-0.04, change_pct=-0.51)
    row = q.to_cache_row()
    check("cache row price", row["price"], 7.81)
    check("cache row keeps currency", row["currency"], "AED")
    check("cache row keeps latency", row["latency"], md.DELAYED)
    check("cache row keeps source", row["source"], "tradingview")
    check("legacy key name preserved", row["changesPercentage"], -0.51)


def test_actionability():
    """A broker mark is a valuation, not a price. The Options Desk must be able
    to tell the difference before it writes a strike against it."""
    delayed = Quote("X", 1.0, "USD", "tv", md.DELAYED, 0.0)
    mark = Quote("X", 1.0, "USD", "ibkr-mark", md.BROKER_MARK, 0.0)
    stale = Quote("X", 1.0, "USD", "cache", md.STALE_CACHE, 0.0)
    check_true("delayed is actionable", delayed.is_actionable)
    check("broker mark is not actionable", mark.is_actionable, False)
    check("stale cache is not actionable", stale.is_actionable, False)


def test_tradingview_is_off_unless_enabled():
    """Shipping an undocumented endpoint enabled-by-default would make the
    decision for the owner. It has to be switched on deliberately."""
    original = md.TRADINGVIEW_ENABLED
    try:
        md.TRADINGVIEW_ENABLED = False
        check("disabled returns nothing",
              md.TradingViewProvider().fetch([sym.build("ALDAR.AE")]), {})
    finally:
        md.TRADINGVIEW_ENABLED = original


def test_every_market_has_a_tier_list():
    """A market with no tier list silently prices nothing."""
    for market in (sym.US, sym.UAE, sym.INDIA_EQ, sym.INDIA_FUND, sym.JAPAN,
                   sym.SWISS, sym.LSE, sym.SGX, sym.HK, sym.KOREA, sym.CANADA,
                   sym.EUROPE, sym.FUND_OFFSHORE, sym.UNKNOWN):
        check_true(f"tier list exists for {market}", md.TIERS.get(market))
    # And every tier ends somewhere that always has an answer for a held position.
    for market in (sym.UAE, sym.JAPAN, sym.SWISS, sym.US):
        last = md.TIERS[market][-1]
        check(f"{market} falls back to the broker mark", last.name, "ibkr-mark")


def test_empty_input():
    quotes, report = md.fetch_quotes([])
    check("no quotes", quotes, {})
    check("report is zeroed", (report.requested, report.priced), (0, 0))


def main():
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("test_"):
            fn()
    print(f"\n  {_passed} assertions passed, {len(_failed)} failed")
    for f in _failed:
        print(f"\n  FAIL: {f}")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
