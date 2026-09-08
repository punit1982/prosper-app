"""
symbology.py — one place that knows what a ticker IS.

Prosper's price problems have almost always been identity problems, not fetch
problems: PRYm vs PRY.MI, 17041163.NS vs 543895.BO, Morningstar fund IDs turned
into fake ".NS" tickers, EMAAR rewritten to "EMAAR:DFM" and then cached that way
for 24 hours. Every one of those was the app *guessing* an identity the broker
statement had already stated.

So this module does two things and nothing else:

  1. Classify a ticker into a MARKET (a venue we know how to price), from the
     Yahoo-style suffix, the broker's own listing-exchange code, or the ISIN
     country prefix — in that order of trust.
  2. Translate that market + symbol into whatever form a given provider wants.

It performs no network calls and holds no state, so it is cheap to call in a
loop and safe to import from anywhere.

Suffix table follows the market-data source review (8 Sep 2026). Note the UAE
entry: that review says ADX is ".AD" and DFM is ".AE", while Prosper has always
written ".AE" for both. Yahoo was rate-limiting every request on the day this
was written, so the claim could not be settled either way — both forms are
therefore accepted as UAE and the ambiguity is recorded rather than guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ── Markets ──────────────────────────────────────────────────────────────────
# A "market" is a venue Prosper knows how to route. It is deliberately coarser
# than an exchange: SIX and Euronext behave the same for our purposes.

US = "us"
UAE = "uae"                 # ADX + DFM
INDIA_EQ = "india_eq"       # NSE + BSE
INDIA_FUND = "india_fund"   # AMFI-registered mutual funds (no exchange listing)
JAPAN = "japan"
SWISS = "swiss"
LSE = "lse"                 # London, incl. Irish-domiciled ETFs listed there
SGX = "sgx"
HK = "hk"
KOREA = "korea"
CANADA = "canada"
EUROPE = "europe"           # Xetra, Euronext, Milan, Madrid, Nordics, Vienna…
FUND_OFFSHORE = "fund_offshore"   # FUNDSERV / ALLFUNDS / SICAV lines with no venue
UNKNOWN = "unknown"

# ── Yahoo-style suffix → market ──────────────────────────────────────────────
SUFFIX_MARKET = {
    "AE": UAE, "AD": UAE, "DU": UAE,
    "NS": INDIA_EQ, "BO": INDIA_EQ,
    "T": JAPAN,
    "SW": SWISS, "VX": SWISS,
    "L": LSE, "IL": LSE,
    "SI": SGX,
    "HK": HK,
    "KS": KOREA, "KQ": KOREA,
    "TO": CANADA, "V": CANADA, "CN": CANADA, "NE": CANADA,
    "DE": EUROPE, "F": EUROPE, "PA": EUROPE, "AS": EUROPE, "MI": EUROPE,
    "MC": EUROPE, "ST": EUROPE, "OL": EUROPE, "HE": EUROPE, "BR": EUROPE,
    "IR": EUROPE, "VI": EUROPE, "LS": EUROPE, "WA": EUROPE, "CO": EUROPE,
}

# ── Broker listing-exchange code → market ────────────────────────────────────
# These come straight out of the IBKR statement's "Listing Exch" column and are
# the most trustworthy signal available: the broker is telling us where it holds
# the position. Cheaper and safer than any suffix heuristic.
IBKR_EXCH_MARKET = {
    "NASDAQ": US, "NYSE": US, "ARCA": US, "AMEX": US, "BATS": US,
    "PINK": US, "VALUE": US, "NASDAQ.NMS": US,
    "ADX": UAE, "DFM": UAE, "NASDAQDUBAI": UAE,
    "TSEJ": JAPAN, "JPX": JAPAN,
    "EBS": SWISS, "SWX": SWISS, "VIRTX": SWISS,
    "LSE": LSE, "LSEETF": LSE, "LSEIOB1": LSE,
    "SGX": SGX,
    "SEHK": HK, "HKEX": HK,
    "KSE": KOREA,
    "TSE": CANADA, "VENTURE": CANADA,          # IBKR calls Toronto "TSE"
    "IBIS": EUROPE, "IBIS2": EUROPE, "FWB": EUROPE, "SBF": EUROPE,
    "AEB": EUROPE, "BVME": EUROPE, "BM": EUROPE, "SFB": EUROPE,
    "OSE": EUROPE, "HEX": EUROPE, "ENEXT.BE": EUROPE, "VSE": EUROPE,
    "BVL": EUROPE, "WSE": EUROPE, "CPH": EUROPE,
    "NSE": INDIA_EQ, "BSE": INDIA_EQ,
    "FUNDSERV": FUND_OFFSHORE, "ALLFUNDS": FUND_OFFSHORE,
}

# ── ISIN country prefix → market (weakest signal, used only as a backstop) ───
# Deliberately partial. An ISIN says where the security is *registered*, not
# where it trades — IE/LU funds list all over Europe — so only unambiguous
# cases are listed here.
ISIN_PREFIX_MARKET = {
    "AE": UAE, "JP": JAPAN, "CH": SWISS, "SG": SGX,
    "IN": INDIA_EQ, "KR": KOREA, "HK": HK, "CA": CANADA,
}

# ── TradingView exchange prefixes, by market ────────────────────────────────
# TradingView needs "EXCHANGE:SYMBOL". Where a market has more than one venue we
# try each in turn: sending a wrong prefix simply omits the row, it never errors.
TRADINGVIEW_PREFIXES = {
    US: ["NASDAQ", "NYSE", "AMEX"],
    UAE: ["ADX", "DFM"],
    INDIA_EQ: ["NSE", "BSE"],
    JAPAN: ["TSE"],
    SWISS: ["SIX"],
    LSE: ["LSE"],
    SGX: ["SGX"],
    HK: ["HKEX"],
    KOREA: ["KRX"],
    CANADA: ["TSX", "TSXV"],
    EUROPE: ["XETR", "EURONEXT", "MIL", "BME", "OMXSTO", "SIX"],
}

# TradingView groups its screener by COUNTRY slug, not by exchange or by our
# coarse market. That distinction matters for EUROPE, which spans six countries:
# routing all of them to "germany" silently loses Milan, Paris and Amsterdam.
TRADINGVIEW_SCAN_GROUP = {
    US: "america", UAE: "uae", INDIA_EQ: "india", JAPAN: "japan",
    SWISS: "switzerland", LSE: "uk", SGX: "singapore", HK: "hongkong",
    KOREA: "korea", CANADA: "canada", EUROPE: "germany",
}

# Exchange-level override, consulted first. Keyed by both the IBKR listing code
# and the Yahoo suffix so it works whether or not the broker told us the venue.
EXCHANGE_SCAN_GROUP = {
    "BVME": "italy",   "MI": "italy",
    "IBIS": "germany", "IBIS2": "germany", "FWB": "germany", "DE": "germany", "F": "germany",
    "SBF": "france",   "PA": "france",
    "AEB": "netherlands", "AS": "netherlands",
    "BM": "spain",     "MC": "spain",
    "SFB": "sweden",   "ST": "sweden",
    "OSE": "norway",   "OL": "norway",
    "HEX": "finland",  "HE": "finland",
    "VSE": "austria",  "VI": "austria",
    "ENEXT.BE": "belgium", "BR": "belgium",
    "BVL": "portugal", "LS": "portugal",
    "WSE": "poland",   "WA": "poland",
    "CPH": "denmark",  "CO": "denmark",
}

# IBKR truncates long symbols in its statements and its position feed
# (PUREHEALT for PUREHEALTH, ADNOCDRIL for ADNOCDRILL, EMIRATESN for
# EMIRATESNBD). The truncated form is what lands in holdings.ticker, and no
# quote provider recognises it. Each entry here is a symbol confirmed against
# the exchange, not a guess; add to it when a UAE or long-symbol line comes back
# unpriced.
SYMBOL_ALIASES = {
    "PUREHEALT": ["PUREHEALTH"],
    "ADNOCDRIL": ["ADNOCDRILL"],
    "EMIRATESN": ["EMIRATESNBD"],
    "EMAARDEV":  ["EMAARDEV"],
    "ADNOCLS":   ["ADNOCLS"],
}

# Markets whose home currency is not obvious from the ticker.
MARKET_CURRENCY = {
    UAE: "AED", JAPAN: "JPY", SWISS: "CHF", SGX: "SGD",
    INDIA_EQ: "INR", INDIA_FUND: "INR", KOREA: "KRW", HK: "HKD",
    CANADA: "CAD", US: "USD",
}

# London quotes many lines in pence. Anything priced in GBX must be divided by
# 100 before it meets a GBP cost basis — a 100x error that looks plausible on a
# small position and catastrophic on a large one.
GBX_MARKETS = {LSE}


@dataclass
class Instrument:
    """Everything Prosper knows about one holding's identity.

    `market` is the only field the pricing pipeline routes on. The rest exist so
    a provider can build whatever symbol form it needs without re-deriving it.
    """
    ticker: str                      # Prosper's canonical form, e.g. "ALDAR.AE"
    base: str = ""                   # symbol without suffix, e.g. "ALDAR"
    suffix: str = ""                 # "AE", "T", "" for US
    market: str = UNKNOWN
    isin: Optional[str] = None
    conid: Optional[str] = None      # IBKR contract id — globally unique, never reused
    listing_exchange: Optional[str] = None
    currency: Optional[str] = None
    asset_category: Optional[str] = None
    name: str = ""
    aliases: list = field(default_factory=list)

    @property
    def is_fund(self) -> bool:
        cat = (self.asset_category or "").lower()
        return "fund" in cat or self.market in (INDIA_FUND, FUND_OFFSHORE)

    @property
    def quotes_in_pence(self) -> bool:
        return self.market in GBX_MARKETS


def split_ticker(ticker: str) -> tuple:
    """'ALDAR.AE' → ('ALDAR', 'AE'). Handles bare US symbols and colon forms."""
    t = (ticker or "").strip().upper()
    if not t:
        return "", ""
    # Twelve Data's "EMAAR:DFM" form, which older cached rows still carry.
    if ":" in t:
        base, _, venue = t.partition(":")
        return base, venue
    if "." in t:
        base, _, suffix = t.rpartition(".")
        return base, suffix
    return t, ""


def classify(
    ticker: str,
    *,
    listing_exchange: str = "",
    isin: str = "",
    asset_category: str = "",
) -> str:
    """Return the market code for a ticker.

    Trust order — broker statement, then suffix, then ISIN. The broker is the
    only source that actually knows; the others are inference.
    """
    exch = (listing_exchange or "").strip().upper()
    if exch in IBKR_EXCH_MARKET:
        return IBKR_EXCH_MARKET[exch]

    base, suffix = split_ticker(ticker)

    # Colon forms carry the venue directly.
    if suffix in ("DFM", "ADX"):
        return UAE

    cat = (asset_category or "").strip().lower()
    if "fund" in cat:
        # A fund with an Indian ISIN is an AMFI scheme; anything else offshore.
        if (isin or "").upper().startswith("INF"):
            return INDIA_FUND
        if suffix in ("NS", "BO"):
            # Legacy rows where a Morningstar fund id was given a fake .NS suffix.
            return INDIA_FUND if base.startswith("F0") else INDIA_EQ
        return FUND_OFFSHORE

    if suffix in SUFFIX_MARKET:
        return SUFFIX_MARKET[suffix]
    if not suffix:
        return US

    iso = (isin or "").strip().upper()
    if len(iso) >= 2 and iso[:2] in ISIN_PREFIX_MARKET:
        return ISIN_PREFIX_MARKET[iso[:2]]

    return UNKNOWN


def build(
    ticker: str,
    *,
    listing_exchange: str = "",
    isin: str = "",
    conid: str = "",
    currency: str = "",
    asset_category: str = "",
    name: str = "",
) -> Instrument:
    """Assemble an Instrument from whatever identity fields are available."""
    base, suffix = split_ticker(ticker)
    market = classify(
        ticker,
        listing_exchange=listing_exchange,
        isin=isin,
        asset_category=asset_category,
    )
    return Instrument(
        ticker=(ticker or "").strip().upper(),
        base=base,
        suffix=suffix,
        market=market,
        isin=(isin or "").strip().upper() or None,
        conid=(conid or "").strip() or None,
        listing_exchange=(listing_exchange or "").strip().upper() or None,
        currency=(currency or "").strip().upper() or MARKET_CURRENCY.get(market),
        asset_category=asset_category or None,
        name=name or "",
    )


def tradingview_symbols(inst: Instrument) -> list:
    """Candidate 'EXCHANGE:SYMBOL' forms for one instrument.

    When the broker told us the listing exchange we emit exactly one candidate.
    Otherwise we emit every venue in the market and let the scanner drop the
    misses — a wrong prefix costs nothing because unmatched tickers are simply
    absent from the response.
    """
    exch_direct = {
        "ADX": "ADX", "DFM": "DFM", "TSEJ": "TSE", "EBS": "SIX", "SGX": "SGX",
        "LSE": "LSE", "LSEETF": "LSE", "BVME": "MIL", "IBIS": "XETR",
        "SBF": "EURONEXT", "AEB": "EURONEXT", "TSE": "TSX", "SEHK": "HKEX",
        "NASDAQ": "NASDAQ", "NYSE": "NYSE", "ARCA": "AMEX", "AMEX": "AMEX",
        "NSE": "NSE", "BSE": "BSE", "KSE": "KRX",
    }
    bases = [inst.base] + [a for a in SYMBOL_ALIASES.get(inst.base, []) if a != inst.base]
    if inst.listing_exchange and inst.listing_exchange in exch_direct:
        venues = [exch_direct[inst.listing_exchange]]
    else:
        venues = TRADINGVIEW_PREFIXES.get(inst.market, [])
    return [f"{v}:{b}" for b in bases for v in venues]


def scan_group(market: str, exchange: str = "", suffix: str = "") -> Optional[str]:
    """TradingView screener slug. Exchange wins over market when we know it."""
    for key in ((exchange or "").upper(), (suffix or "").upper()):
        if key and key in EXCHANGE_SCAN_GROUP:
            return EXCHANGE_SCAN_GROUP[key]
    return TRADINGVIEW_SCAN_GROUP.get(market)
