"""
HARVEST — Assignment-Grade Universe (AGU)
=========================================
Fifty names outside (or overlapping) the book that are liquid enough to trade options in and
sound enough that assignment is an acceptable outcome rather than a disaster.

Why this list exists
--------------------
The owner's own book cannot honestly feed five ideas a day. A live gate across all 69 of his
US-listed 100-share lots (25-50 DTE, delta 0.15-0.35, OI >= 100, spread <= 15%) passed only 11.
The biggest lots by share count are the smallest by dollar value and the worst by liquidity —
25,000 shares of a $0.47 stock whose options nobody trades. So short-put and spread ideas need a
second universe.

How it was built (06-07 Sep 2026)
---------------------------------
84 candidates were screened against live CBOE chains and Finnhub fundamentals. Gates:

  * open interest >= 150,000 across the chain
  * >= 13 listed expiries (weeklies exist, so rolling is possible)
  * IV30 high enough that the premium is worth collecting
  * an ETF, or a profitable company above $45bn market cap

Liquidity was scored on **open interest and expiry count, not bid/ask spread**. The scan ran on a
weekend and produced a 115% "median spread" on XLF — one of the most liquid ETFs in existence —
because Friday's closing quotes sit stale on untraded strikes. OI and expiry count are stable when
the market is shut; spread is not. Spread is therefore re-checked live at execution time and is
never trusted from a cached scan (see core/options_engine.py).

Tiering
-------
Tiers are set by **collateral per contract** (price x 100), because that is what actually
constrains this book. One LLY put at $1,140 is a $114,000 obligation.

  TIER_A  < $15k   — normal short-put sizing
  TIER_B  $15-40k  — short puts one position at a time
  TIER_C  > $40k   — covered calls and defined-risk spreads ONLY, never a naked short put

`HEDGE_ANNEX` is separate: SPY and TLT fail the IV floor (11.6 and 10.0 — too little premium to be
worth selling) but are the deepest, cheapest instruments in the world for *buying* protection,
which is the opposite trade and wants exactly that low IV.

Maintenance
-----------
Prices and vols here are a snapshot for tiering and documentation only — nothing at runtime reads
them for pricing. `scripts/options_scan.py` re-tiers from live spot on every run, so a name that
doubles moves to the next tier by itself. Re-run the full screen quarterly.
"""

from typing import Dict, List, Optional

TIER_A = "A"
TIER_B = "B"
TIER_C = "C"

# Collateral thresholds (USD per 100-share contract) used to (re-)tier from live spot.
TIER_A_MAX = 15_000
TIER_B_MAX = 40_000


# name: (tier_at_screen, sector, is_etf, spot_at_screen, iv30_at_screen, hv20_at_screen, open_interest)
_AGU: Dict[str, tuple] = {
    # ── TIER A — under $15k collateral per contract ───────────────────────────
    "NKE":   (TIER_A, "Consumer Discretionary", False,   38.42, 45.6, 31.7,  2_187_421),
    "BAC":   (TIER_A, "Financials",             False,   62.68, 20.7, 16.9,  2_306_040),
    "XLF":   (TIER_A, "Financials",             True,    58.10, 14.0, 11.8,  6_327_203),
    "PEP":   (TIER_A, "Consumer Staples",       False,  137.78, 20.4, 17.2,    392_132),
    "SBUX":  (TIER_A, "Consumer Discretionary", False,  104.84, 25.5, 21.7,    488_530),
    "XLE":   (TIER_A, "Energy",                 True,    64.06, 23.7, 20.8,  4_488_541),
    "SCHW":  (TIER_A, "Financials",             False,  109.28, 22.9, 20.5,    484_711),
    "COP":   (TIER_A, "Energy",                 False,  134.72, 28.4, 27.1,    310_553),
    "UBER":  (TIER_A, "Industrials",            False,   75.70, 33.9, 34.2,  1_353_923),
    "DIS":   (TIER_A, "Communication Services", False,  105.37, 22.3, 25.9,    684_763),
    "NFLX":  (TIER_A, "Communication Services", False,   78.32, 31.8, 38.4,  5_087_611),
    "WMT":   (TIER_A, "Consumer Staples",       False,  107.10, 21.6, 39.2,  1_159_714),

    # ── TIER B — $15k-40k collateral per contract ─────────────────────────────
    "QCOM":  (TIER_B, "Information Technology", False,  168.64, 39.9, 26.0,    883_878),
    "JPM":   (TIER_B, "Financials",             False,  358.28, 20.6, 13.8,    681_404),
    "UNH":   (TIER_B, "Health Care",            False,  396.85, 27.6, 18.8,    943_325),
    "ORCL":  (TIER_B, "Information Technology", False,  159.70, 68.3, 49.0,  3_203_989),
    "IWM":   (TIER_B, "Broad Market",           True,   296.01, 16.1, 11.9, 10_391_695),
    "MS":    (TIER_B, "Financials",             False,  217.75, 28.0, 21.4,    376_060),
    "TXN":   (TIER_B, "Information Technology", False,  259.71, 35.0, 27.1,    253_614),
    "GOOGL": (TIER_B, "Communication Services", False,  338.72, 27.3, 21.2,  3_262_028),
    "AXP":   (TIER_B, "Financials",             False,  327.15, 21.9, 17.0,    267_123),
    "AAPL":  (TIER_B, "Information Technology", False,  320.01, 24.4, 20.9,  4_612_375),
    "LRCX":  (TIER_B, "Information Technology", False,  307.48, 57.5, 49.8,    551_433),
    "ABBV":  (TIER_B, "Health Care",            False,  256.53, 24.0, 21.0,    268_966),
    "AMZN":  (TIER_B, "Consumer Discretionary", False,  258.30, 29.3, 25.8,  4_668_963),
    "CVX":   (TIER_B, "Energy",                 False,  208.47, 24.0, 21.3,    570_428),
    "BKNG":  (TIER_B, "Consumer Discretionary", False,  193.34, 31.4, 27.9,    647_178),
    "KLAC":  (TIER_B, "Information Technology", False,  186.47, 52.3, 46.6,    454_598),
    "MCD":   (TIER_B, "Consumer Discretionary", False,  256.00, 20.0, 17.9,    326_044),
    "ADBE":  (TIER_B, "Information Technology", False,  266.49, 50.9, 48.4,    703_795),
    "JNJ":   (TIER_B, "Health Care",            False,  275.23, 21.5, 20.7,    383_885),
    "XOM":   (TIER_B, "Energy",                 False,  159.18, 26.7, 25.7,  1_071_637),
    "AVGO":  (TIER_B, "Information Technology", False,  357.07, 36.0, 34.7,  2_549_519),
    "INTU":  (TIER_B, "Information Technology", False,  332.55, 43.8, 46.1,    196_137),
    "GE":    (TIER_B, "Industrials",            False,  337.73, 28.4, 30.7,    216_834),
    "NVDA":  (TIER_B, "Information Technology", False,  229.49, 33.3, 43.7, 14_723_234),
    "CRM":   (TIER_B, "Information Technology", False,  259.40, 37.7, 76.5,    910_735),

    # ── TIER C — over $40k per contract; covered calls / spreads only ─────────
    "QQQ":   (TIER_C, "Broad Market",           True,   717.50, 17.0, 12.5, 11_763_455),
    "MU":    (TIER_C, "Information Technology", False, 1014.91, 65.5, 52.9,  3_364_458),
    "GS":    (TIER_C, "Financials",             False, 1039.40, 30.6, 24.7,    479_943),
    "COST":  (TIER_C, "Consumer Staples",       False,  916.00, 23.6, 19.3,    345_335),
    "TSM":   (TIER_C, "Information Technology", False,  427.98, 31.1, 25.4,  1_941_187),
    "CAT":   (TIER_C, "Industrials",            False,  812.00, 35.3, 29.1,    305_088),
    "AMAT":  (TIER_C, "Information Technology", False,  454.94, 50.3, 45.2,    527_642),
    "META":  (TIER_C, "Communication Services", False,  615.20, 35.2, 32.2,  3_222_876),
    "AMD":   (TIER_C, "Information Technology", False,  476.24, 48.4, 44.8,  3_222_724),
    "SMH":   (TIER_C, "Information Technology", True,   565.59, 32.9, 30.6,  1_916_292),
    "MSFT":  (TIER_C, "Information Technology", False,  499.41, 23.7, 22.9,  3_790_673),
    "LLY":   (TIER_C, "Health Care",            False, 1140.22, 30.8, 32.3,    384_675),
    "GLD":   (TIER_C, "Commodities",            True,   406.77, 24.0, 26.4,  6_249_085),
}

# Deep, cheap protection. Excluded from premium selling by the IV floor — which is precisely why
# they are good to BUY. Scanned every night alongside the AGU.
HEDGE_ANNEX: Dict[str, tuple] = {
    "SPY": ("Broad Market", True, 770.19, 11.6,  7.9, 18_650_372),
    "TLT": ("Rates",        True,  82.24, 10.0, 10.4, 12_360_004),
}

# Screened and deliberately excluded. Kept so a future maintainer does not "helpfully" re-add them.
EXCLUDED: Dict[str, str] = {
    "CRWD": "1.1% net margin — assignment is not an acceptable outcome at this valuation",
    "PANW": "2.7% net margin on a high multiple — same reason",
    "NOW":  "priced for perfection; a bag-holder scenario here is a long way down",
    "ARM":  "13% ROE against an extreme multiple; too fragile to be assigned into",
    "CMG":  "chain depth failed the 150k open-interest gate",
    "SPY":  "IV 11.6 is below the premium-selling floor — see HEDGE_ANNEX, it is a buy-protection name",
    "TLT":  "IV 10.0 — same; buy-protection only",
}

# Sector-relative net-margin floors. A single absolute threshold wrongly flagged WMT (3.0%),
# COST (3.0%) and UNH (3.1%) as weak — those are structurally low-margin businesses, not troubled
# ones. Used by scripts/options_scan.py when it re-validates quality.
SECTOR_MARGIN_FLOOR: Dict[str, float] = {
    "Consumer Staples":       1.5,
    "Consumer Discretionary": 3.0,
    "Health Care":            2.0,
    "Financials":             8.0,
    "Energy":                 4.0,
    "Industrials":            5.0,
    "Information Technology": 8.0,
    "Communication Services": 6.0,
    "Broad Market":           0.0,
    "Commodities":            0.0,
    "Rates":                  0.0,
}
_DEFAULT_MARGIN_FLOOR = 5.0


def tier_for_price(spot: float) -> str:
    """Re-tier from live spot. A name that doubles moves tier by itself."""
    collateral = (spot or 0) * 100
    if collateral < TIER_A_MAX:
        return TIER_A
    if collateral < TIER_B_MAX:
        return TIER_B
    return TIER_C


def universe_tickers(include_hedge: bool = True) -> List[str]:
    out = list(_AGU.keys())
    if include_hedge:
        out += [t for t in HEDGE_ANNEX if t not in _AGU]
    return out


def meta(ticker: str) -> Optional[dict]:
    """Static metadata for a universe name, or None if it isn't in the universe."""
    t = (ticker or "").strip().upper()
    if t in _AGU:
        tier, sector, is_etf, spot, iv, hv, oi = _AGU[t]
        return {"ticker": t, "tier": tier, "sector": sector, "is_etf": is_etf,
                "spot_at_screen": spot, "iv30_at_screen": iv, "hv20_at_screen": hv,
                "open_interest_at_screen": oi, "role": "agu"}
    if t in HEDGE_ANNEX:
        sector, is_etf, spot, iv, hv, oi = HEDGE_ANNEX[t]
        return {"ticker": t, "tier": tier_for_price(spot), "sector": sector, "is_etf": is_etf,
                "spot_at_screen": spot, "iv30_at_screen": iv, "hv20_at_screen": hv,
                "open_interest_at_screen": oi, "role": "hedge"}
    return None


def in_universe(ticker: str) -> bool:
    return meta(ticker) is not None


def sector_of(ticker: str) -> str:
    m = meta(ticker)
    return m["sector"] if m else "Unknown"


def margin_floor(sector: str) -> float:
    return SECTOR_MARGIN_FLOOR.get(sector, _DEFAULT_MARGIN_FLOOR)


def put_writable(ticker: str, spot: float = None) -> bool:
    """Tier C names never take a naked short put (doctrine R4)."""
    m = meta(ticker)
    if not m:
        return False
    if m["role"] == "hedge":
        return False
    tier = tier_for_price(spot) if spot else m["tier"]
    return tier in (TIER_A, TIER_B)
