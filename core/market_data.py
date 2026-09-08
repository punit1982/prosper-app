"""
market_data.py — the quote pipeline.

Replaces "try six sources in a fixed order for every ticker, one ticker at a
time" with "ask each market's best provider for all of that market's tickers at
once, then fall down a tier list for whatever is still missing".

Three ideas carry the design:

  1. **Batch first.** The old cascade made up to six sequential HTTP calls per
     ticker, 186 times. Providers here take a LIST. A whole market is usually
     one request.

  2. **Tiers are per market, not global.** Finnhub is excellent for US and
     returns 403 for Zurich; Twelve Data's plan excludes India and the UAE
     entirely. A single global ordering has to walk those certain failures for
     every non-US name. Routing by market skips them.

  3. **Every quote carries its provenance.** Source, as-of time, latency class
     and quote currency travel with the price. This is rule 1 of the failover
     discipline in the market-data source review, and it is what makes a wrong
     number diagnosable instead of mysterious: a stale AED mark and a live AED
     print are no longer indistinguishable once they reach the UI.

Nothing here raises. A provider that fails returns fewer rows; the pipeline
moves down a tier. The caller gets whatever could be priced plus a per-ticker
record of what was tried.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from core import symbology as sym
from core.symbology import Instrument

log = logging.getLogger(__name__)

# Latency classes, in the order a caller should prefer them. These describe how
# far behind the market a number is — never how fresh our cache is.
LIVE = "live"              # real-time print
DELAYED = "delayed"        # exchange-delayed, typically 10-20 min
EOD = "eod"                # yesterday's close / daily NAV
BROKER_MARK = "broker_mark"  # the broker's own valuation, no market print
STALE_CACHE = "stale_cache"  # a previously good number, past its TTL

_LATENCY_RANK = {LIVE: 0, DELAYED: 1, EOD: 2, BROKER_MARK: 3, STALE_CACHE: 4}

# TradingView's screener is undocumented and its terms do not license
# redistribution. It is also the only free source that prices ADX/DFM at all,
# and the production probe on 8 Sep 2026 confirmed it answers from Render's
# network in 191ms with correct AED prices. On the owner's instruction it is now
# ON by default and needs no configuration; PROSPER_DISABLE_TRADINGVIEW is the
# kill switch if it ever starts returning nonsense or blocking us.
TRADINGVIEW_ENABLED = os.getenv("PROSPER_DISABLE_TRADINGVIEW", "").strip().lower() not in ("1", "true", "yes", "on")

_HTTP_TIMEOUT = 8


@dataclass
class Quote:
    """One price, with everything needed to judge whether to trust it."""
    symbol: str
    price: float
    currency: str
    source: str
    latency: str
    asof: float                       # epoch seconds when the data was fetched
    change: Optional[float] = None
    change_pct: Optional[float] = None
    exchange_delay_s: Optional[int] = None   # provider's own declared delay
    note: Optional[str] = None

    def to_cache_row(self) -> dict:
        """The shape core.database.save_price_cache and the enrichment expect."""
        return {
            "symbol": self.symbol,
            "price": self.price,
            "change": self.change,
            "changesPercentage": self.change_pct,
            "source": self.source,
            "currency": self.currency,
            "latency": self.latency,
            "asof": self.asof,
        }

    @property
    def is_actionable(self) -> bool:
        """True if this number is fresh enough to size a trade against."""
        return self.latency in (LIVE, DELAYED)


# ─────────────────────────────────────────────────────────────────────────────
# Providers
#
# A provider implements:
#     name      : str
#     latency   : str
#     markets   : set[str]   — which markets it can serve at all
#     fetch(insts) -> dict[ticker, Quote]
#
# fetch() must never raise and must never return a partial/None price. Anything
# it cannot price it simply omits.
# ─────────────────────────────────────────────────────────────────────────────


def _http_json(url, *, payload=None, headers=None, timeout=_HTTP_TIMEOUT):
    """POST-or-GET JSON with no exceptions escaping. Returns None on any failure."""
    import urllib.error
    import urllib.request

    hdr = {"User-Agent": "Mozilla/5.0 (compatible; Prosper/1.0)", "Accept": "application/json"}
    if payload is not None:
        hdr["Content-Type"] = "application/json"
    hdr.update(headers or {})
    data = json.dumps(payload).encode() if payload is not None else None
    try:
        req = urllib.request.Request(url, data=data, headers=hdr,
                                     method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read())
    except Exception as exc:                      # noqa: BLE001 — providers never raise
        log.debug("%s failed: %r", url.split("?")[0], exc)
        return None


def _parallel_fetch(insts, fetch_one, *, workers=8, timeout=25):
    """Run a per-ticker fetch across a small thread pool.

    Some providers have no batch endpoint — Finnhub, Yahoo's chart, justETF and
    Boerse Frankfurt are all one-call-per-symbol. Run sequentially, 82 US names
    at Finnhub's rate-limited ~900ms each is 74 seconds, which is most of a page
    load. `core.parallel.gather` already handles the hard part: its per-call
    timeout bounds how long one slow call can hold a worker slot, which a bare
    ThreadPoolExecutor does not.
    """
    if not insts:
        return {}
    out: Dict[str, Quote] = {}
    try:
        from core.parallel import gather
        done, _ = gather(
            fetch_one,
            [(i.ticker, (i,)) for i in insts],
            max_workers=workers,
            timeout=timeout,
        )
        for _key, quote in done.items():
            if quote is not None:
                out[quote.symbol] = quote
    except Exception:
        # gather unavailable (or misbehaving) — correctness beats speed.
        for inst in insts:
            try:
                quote = fetch_one(inst)
            except Exception:
                continue
            if quote is not None:
                out[quote.symbol] = quote
    return out


class TradingViewProvider:
    """One POST per market returns every ticker in that market.

    The only free source verified to price ADX and DFM, and it returns
    home-market prices in home currency rather than a cross-listing proxy.
    Cross-checked against IBKR's own marks on 8 Sep 2026 across ten holdings in
    five markets: worst divergence 0.80%, which is the declared delay rather
    than an error.

    `update_mode` is the provider telling us its own latency
    ("delayed_streaming_900" = 15 min). We record that rather than assuming.
    """

    name = "tradingview"
    latency = DELAYED
    markets = set(sym.TRADINGVIEW_SCAN_GROUP)

    _COLUMNS = ["close", "change", "change_abs", "currency", "update_mode"]

    def fetch(self, insts: List[Instrument]) -> Dict[str, Quote]:
        if not TRADINGVIEW_ENABLED or not insts:
            return {}

        out: Dict[str, Quote] = {}
        # Group by SCAN SLUG, not by market: "europe" spans Milan, Xetra, Paris
        # and Amsterdam, and TradingView wants one country per request.
        by_slug: Dict[str, List[Instrument]] = {}
        for inst in insts:
            slug = sym.scan_group(inst.market, inst.listing_exchange or "", inst.suffix)
            if slug:
                by_slug.setdefault(slug, []).append(inst)

        for slug, group in by_slug.items():
            # Map every candidate symbol form back to the instrument that asked
            # for it, so an unexpected venue prefix still resolves.
            wanted: Dict[str, Instrument] = {}
            for inst in group:
                for cand in sym.tradingview_symbols(inst):
                    wanted.setdefault(cand.upper(), inst)
            if not wanted:
                continue

            body = {
                "symbols": {"tickers": list(wanted), "query": {"types": []}},
                "columns": self._COLUMNS,
            }
            payload = _http_json(f"https://scanner.tradingview.com/{slug}/scan", payload=body)
            if not payload:
                continue

            now = time.time()
            for row in payload.get("data") or []:
                inst = wanted.get(str(row.get("s", "")).upper())
                if inst is None or inst.ticker in out:
                    continue
                vals = row.get("d") or []
                if len(vals) < 4:
                    continue
                price, chg_pct, chg_abs, ccy = vals[0], vals[1], vals[2], vals[3]
                mode = vals[4] if len(vals) > 4 else ""
                if not price or float(price) <= 0:
                    continue
                delay = None
                if isinstance(mode, str) and "_" in mode:
                    tail = mode.rsplit("_", 1)[-1]
                    if tail.isdigit():
                        delay = int(tail)
                out[inst.ticker] = Quote(
                    symbol=inst.ticker,
                    price=float(price),
                    currency=(ccy or inst.currency or "USD").upper(),
                    source=self.name,
                    latency=LIVE if mode == "streaming" else DELAYED,
                    asof=now,
                    change=float(chg_abs) if chg_abs is not None else None,
                    change_pct=round(float(chg_pct), 4) if chg_pct is not None else None,
                    exchange_delay_s=delay,
                )
        return out


class FinnhubProvider:
    """US only — verified. Returns 403 for .SW/.T/.NS and c:0 for .AE, so it is
    routed to US alone rather than tried everywhere and failing slowly."""

    name = "finnhub"
    latency = DELAYED
    markets = {sym.US}

    def fetch(self, insts: List[Instrument]) -> Dict[str, Quote]:
        try:
            from core.finnhub_client import quote as fh_quote, is_configured
            if not is_configured():
                return {}
        except Exception:
            return {}

        def one(inst):
            try:
                q = fh_quote(inst.base)
            except Exception:
                return None
            if not q or not q.get("c"):
                return None
            price = float(q["c"])
            if price <= 0:
                return None
            prev = float(q.get("pc") or 0) or None
            return Quote(
                symbol=inst.ticker, price=price, currency="USD",
                source=self.name, latency=DELAYED, asof=time.time(),
                change=round(price - prev, 6) if prev else None,
                change_pct=round((price - prev) / prev * 100, 4) if prev else None,
            )

        # Finnhub's own client rate-limits internally, so keep the pool modest.
        return _parallel_fetch(insts, one, workers=6, timeout=40)


class YahooChartProvider:
    """Yahoo's `chart` endpoint — kept, demoted.

    It covered most non-US markets until it began returning 429 to both this
    application's production instance (on every boot, 5-8 Sep 2026) and to
    ordinary residential IPs. It still works intermittently, so it stays in the
    tier list below the batch providers rather than being deleted.

    `range=1d` matters: over a longer window `chartPreviousClose` is the close
    before the window starts, which once produced a -47% day move.
    """

    name = "yahoo-chart"
    latency = DELAYED
    markets = set(sym.TRADINGVIEW_SCAN_GROUP) | {sym.UNKNOWN}

    def fetch(self, insts: List[Instrument]) -> Dict[str, Quote]:
        def one(inst):
            payload = _http_json(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{inst.ticker}"
                "?range=1d&interval=1d",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if not payload:
                return None
            meta = (((payload.get("chart") or {}).get("result") or [{}])[0] or {}).get("meta") or {}
            price = meta.get("regularMarketPrice")
            if not price or float(price) <= 0:
                return None
            price = float(price)
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            prev = float(prev) if prev and float(prev) > 0 else None
            ccy = (meta.get("currency") or inst.currency or "USD").upper()
            note = None
            # London quotes many lines in pence. Left unconverted this is a 100x
            # overstatement against a GBP cost basis.
            if ccy == "GBP" and inst.quotes_in_pence and price > 1000:
                price, ccy, note = price / 100.0, "GBP", "converted from GBX"
            return Quote(
                symbol=inst.ticker, price=price, currency=ccy,
                source=self.name, latency=DELAYED, asof=time.time(),
                change=round(price - prev, 6) if prev else None,
                change_pct=round((price - prev) / prev * 100, 4) if prev else None,
                note=note,
            )

        # Yahoo rate-limits aggressively — a wide pool makes 429s more likely,
        # not fewer results.
        return _parallel_fetch(insts, one, workers=4, timeout=30)


class YFinanceProvider:
    """yfinance `fast_info` — a different Yahoo endpoint from `chart`.

    Worth keeping as a separate provider rather than folding into
    YahooChartProvider: they hit different hosts and fail independently, and
    `fast_info` has survived several breakages of the `.info`/`quoteSummary`
    path. This is the only thing the retired per-ticker cascade still
    contributed, so it moves here rather than being lost.

    Note it segfaults for every ticker in the LOCAL Python 3.14 venv — a
    pre-existing environment problem, unrelated to this code, and harmless
    because the provider simply returns nothing there. Production is 3.12.
    """

    name = "yfinance"
    latency = DELAYED
    markets = set(sym.TRADINGVIEW_SCAN_GROUP) | {sym.UNKNOWN}

    def fetch(self, insts: List[Instrument]) -> Dict[str, Quote]:
        try:
            import yfinance as yf
        except Exception:
            return {}

        # yfinance prints its own "No data found, symbol may be delisted" lines
        # for every miss. Here a miss is normal — the ticker falls to the next
        # tier — so those lines are pure noise in the production log, and noise
        # is how real errors get missed. Silence its logger, not ours: the
        # pipeline's own FetchReport already says what could not be priced.
        try:
            logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        except Exception:
            pass

        def one(inst):
            try:
                fi = yf.Ticker(inst.ticker).fast_info
                price, prev = fi.last_price, fi.previous_close
                ccy = (getattr(fi, "currency", None) or inst.currency or "USD").upper()
            except Exception:
                return None
            if not price or float(price) <= 0:
                return None
            price = float(price)
            prev = float(prev) if prev and float(prev) > 0 else None
            note = None
            if ccy == "GBP" and inst.quotes_in_pence and price > 1000:
                price, note = price / 100.0, "converted from GBX"
            return Quote(
                symbol=inst.ticker, price=price, currency=ccy,
                source=self.name, latency=DELAYED, asof=time.time(),
                change=round(price - prev, 6) if prev else None,
                change_pct=round((price - prev) / prev * 100, 4) if prev else None,
                note=note,
            )

        return _parallel_fetch(insts, one, workers=6, timeout=30)


class CryptoProvider:
    """Coinbase spot, then CoinGecko. Both keyless, both verified.

    The Coinbase transaction export gives bare asset symbols (BTC, ETH), which
    every equity provider in this file will fail to price. Coinbase is asked
    first because it is the venue the holdings actually came from, so its mark
    reconciles with the statement; CoinGecko covers anything Coinbase has
    delisted or never listed.
    """

    name = "coinbase"
    latency = LIVE
    markets = {sym.CRYPTO}

    # CoinGecko wants slugs, not tickers, and only for the assets Coinbase misses.
    _GECKO_IDS = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "ADA": "cardano",
        "DOT": "polkadot", "AVAX": "avalanche-2", "MATIC": "matic-network",
        "LINK": "chainlink", "XLM": "stellar", "XRP": "ripple",
        "DOGE": "dogecoin", "LTC": "litecoin", "BCH": "bitcoin-cash",
        "ATOM": "cosmos", "ALGO": "algorand", "FIL": "filecoin",
        "USDC": "usd-coin", "USDT": "tether", "DAI": "dai",
    }

    def fetch(self, insts: List[Instrument]) -> Dict[str, Quote]:
        def one(inst):
            asset = inst.base.upper()
            # Stablecoins are 1:1 by construction; skip the round trip.
            if asset in ("USDC", "USDT", "DAI", "USD"):
                return Quote(symbol=inst.ticker, price=1.0, currency="USD",
                             source="peg", latency=LIVE, asof=time.time(),
                             note="stablecoin, pegged 1:1")
            spot = _http_json(f"https://api.coinbase.com/v2/prices/{asset}-USD/spot")
            amount = ((spot or {}).get("data") or {}).get("amount")
            if amount:
                try:
                    price = float(amount)
                except (TypeError, ValueError):
                    price = 0.0
                if price > 0:
                    return Quote(symbol=inst.ticker, price=price, currency="USD",
                                 source="coinbase", latency=LIVE, asof=time.time())
            gecko_id = self._GECKO_IDS.get(asset)
            if not gecko_id:
                return None
            payload = _http_json(
                f"https://api.coingecko.com/api/v3/simple/price"
                f"?ids={gecko_id}&vs_currencies=usd&include_24hr_change=true")
            row = (payload or {}).get(gecko_id) or {}
            price = row.get("usd")
            if not price or float(price) <= 0:
                return None
            return Quote(symbol=inst.ticker, price=float(price), currency="USD",
                         source="coingecko", latency=LIVE, asof=time.time(),
                         change_pct=row.get("usd_24h_change"))

        return _parallel_fetch(insts, one, workers=6, timeout=25)


class JustEtfProvider:
    """LSE- and Irish-domiciled ETFs, by ISIN, keyless.

    Purpose-built for exactly the six ETF lines Yahoo currently cannot price
    (IB01, U03A, IGLN, ISLN, NDIA, URNU). Requires an ISIN, which is why
    capturing it from the broker statement matters.
    """

    name = "justetf"
    latency = EOD
    markets = {sym.LSE, sym.EUROPE, sym.FUND_OFFSHORE}

    def fetch(self, insts: List[Instrument]) -> Dict[str, Quote]:
        def one(inst):
            if not inst.isin:
                return None
            payload = _http_json(
                f"https://www.justetf.com/api/etfs/{inst.isin}/quote"
                f"?locale=en&currency={(inst.currency or 'USD')}&isin={inst.isin}"
            )
            if not payload:
                return None
            latest = (payload.get("latestQuote") or {}).get("raw")
            prev = (payload.get("previousQuote") or {}).get("raw")
            if not latest or float(latest) <= 0:
                return None
            latest = float(latest)
            prev = float(prev) if prev else None
            return Quote(
                symbol=inst.ticker, price=latest,
                currency=(inst.currency or "USD").upper(),
                source=self.name, latency=EOD, asof=time.time(),
                change=round(latest - prev, 6) if prev else None,
                change_pct=round((latest - prev) / prev * 100, 4) if prev else None,
                note=payload.get("latestQuoteDate"),
            )

        return _parallel_fetch([i for i in insts if i.isin], one, workers=6, timeout=25)


class AmfiProvider:
    """Indian mutual-fund NAV from AMFI's official daily file.

    One 1.5 MB download covers all ~18,000 schemes, so this is fetched once and
    held for the day. These lines previously had no source anywhere: legacy
    Morningstar fund ids were being given fake ".NS" tickers and then reported
    as "no market quote exists".

    Matched on ISIN, which AMFI publishes in the file — never on name.
    """

    name = "amfi"
    latency = EOD
    markets = {sym.INDIA_FUND}

    _cache: Dict[str, tuple] = {}
    _fetched_at: float = 0.0
    _TTL = 6 * 3600

    @classmethod
    def _load(cls) -> Dict[str, tuple]:
        if cls._cache and (time.time() - cls._fetched_at) < cls._TTL:
            return cls._cache
        import urllib.request
        try:
            req = urllib.request.Request(
                "https://www.amfiindia.com/spages/NAVAll.txt",
                headers={"User-Agent": "Mozilla/5.0 (compatible; Prosper/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                text = resp.read().decode("utf-8", "replace")
        except Exception as exc:                   # noqa: BLE001
            log.debug("AMFI fetch failed: %r", exc)
            return cls._cache
        table: Dict[str, tuple] = {}
        for line in text.split("\n"):
            parts = line.split(";")
            if len(parts) < 8:
                continue
            nav = parts[6].strip()
            try:
                nav_f = float(nav)
            except ValueError:
                continue                            # header and section rows
            if nav_f <= 0:
                continue
            for isin in (parts[1].strip(), parts[2].strip()):
                if isin and isin != "-":
                    table[isin.upper()] = (nav_f, parts[7].strip(), parts[3].strip())
        if table:
            cls._cache, cls._fetched_at = table, time.time()
        return cls._cache

    def fetch(self, insts: List[Instrument]) -> Dict[str, Quote]:
        wanted = [i for i in insts if i.isin]
        if not wanted:
            return {}
        table = self._load()
        if not table:
            return {}
        out: Dict[str, Quote] = {}
        for inst in wanted:
            row = table.get(inst.isin)
            if not row:
                continue
            nav, nav_date, scheme = row
            out[inst.ticker] = Quote(
                symbol=inst.ticker, price=nav, currency="INR",
                source=self.name, latency=EOD, asof=time.time(),
                note=f"NAV {nav_date} · {scheme[:60]}",
            )
        return out


class BoerseFrankfurtProvider:
    """Frankfurt cross-listing, by ISIN, keyless.

    Priced 15 of 15 non-UAE international names in testing, but in EUR at a
    different venue — so the day change is Frankfurt's, not Tokyo's, and the
    price needs an FX hop. That makes it a genuine last-resort quote rather
    than a peer of the home-market sources, and it is tiered accordingly.
    It has no UAE coverage at all (0 of 7 ISINs).
    """

    name = "boerse-frankfurt"
    latency = DELAYED
    markets = {sym.JAPAN, sym.SWISS, sym.SGX, sym.EUROPE, sym.LSE, sym.KOREA, sym.HK}

    def fetch(self, insts: List[Instrument]) -> Dict[str, Quote]:
        def one(inst):
            if not inst.isin:
                return None
            payload = _http_json(
                "https://api.boerse-frankfurt.de/v1/data/quote_box/single"
                f"?isin={inst.isin}&mic=XFRA"
            )
            if not payload:
                return None
            price = payload.get("lastPrice") or payload.get("bidLimit")
            if not price or float(price) <= 0:
                return None
            return Quote(
                symbol=inst.ticker, price=float(price), currency="EUR",
                source=self.name, latency=DELAYED, asof=time.time(),
                change_pct=payload.get("changeToPrevDayInPercent"),
                change=payload.get("changeToPrevDayAbsolute"),
                note="Frankfurt cross-listing, EUR — not the home market print",
            )

        return _parallel_fetch([i for i in insts if i.isin], one, workers=6, timeout=25)


# MubasherProvider was here until 8 Sep 2026. Removed, not disabled: the
# production probe returned HTTP 403 from Render's network, which is Cloudflare
# blocking datacenter IPs exactly as the v7.15 investigation predicted. It works
# from a laptop and from the GitHub Actions pre-warm runner, and every "verified
# live" claim about it came from one of those. Keeping it in the Render tier list
# cost one guaranteed-failing HTTP call per UAE holding on every refresh to learn
# something already known. core/adx_client.py stays — scripts/prewarm.py still
# calls it from a GitHub runner, where it does work.


class IbkrMarkProvider:
    """The broker's own valuation, from the committed data/ibkr_marks.json
    snapshot. Not a market price and never presented as one — it is what lets a
    UAE, offshore-fund or suspended line show a number at all."""

    name = "ibkr-mark"
    latency = BROKER_MARK
    markets = set(sym.TRADINGVIEW_SCAN_GROUP) | {sym.FUND_OFFSHORE, sym.INDIA_FUND, sym.UNKNOWN}

    def fetch(self, insts: List[Instrument]) -> Dict[str, Quote]:
        try:
            from core.ibkr_prices import load_static_marks
            payload = load_static_marks() or {}
        except Exception:
            return {}
        marks = payload.get("marks") or {}
        if not marks:
            return {}
        # `as_of` is an ISO stamp in the file; keep it for display but fall back
        # to now for arithmetic so a bad stamp can never produce a negative age.
        asof = time.time()
        stamp = payload.get("as_of")
        out: Dict[str, Quote] = {}
        for inst in insts:
            row = marks.get(inst.ticker)
            if row is None:
                # IBKR truncates some symbols (PUREHEALT vs PUREHEALTH).
                row = next(
                    (v for k, v in marks.items()
                     if k.split(".")[0] == inst.base or inst.base.startswith(k.split(".")[0])),
                    None,
                )
            price = (row or {}).get("price") if isinstance(row, dict) else None
            if not price or float(price) <= 0:
                continue
            out[inst.ticker] = Quote(
                symbol=inst.ticker, price=float(price),
                currency=((row.get("currency") if isinstance(row, dict) else None)
                          or inst.currency or "USD").upper(),
                source=self.name, latency=BROKER_MARK, asof=asof,
                note=f"broker mark as of {stamp}" if stamp else "broker mark, not a market print",
            )
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Tiers
#
# Ordered per market, best first. The pipeline stops asking for a ticker as soon
# as one provider prices it, so a tier list is a statement of preference, not a
# sequence that always runs.
# ─────────────────────────────────────────────────────────────────────────────

_TV = TradingViewProvider()
_FH = FinnhubProvider()
_YC = YahooChartProvider()
_YF = YFinanceProvider()
_JE = JustEtfProvider()
_AM = AmfiProvider()
_BF = BoerseFrankfurtProvider()
_CX = CryptoProvider()
_IB = IbkrMarkProvider()

TIERS: Dict[str, List] = {
    # TradingView leads everywhere it has coverage: one call per country beats
    # one call per ticker, and it is the only source that prices ADX/DFM at all.
    # Each list then falls through independent Yahoo endpoints and ends at the
    # broker's own mark, so every held position resolves to *something*.
    sym.US:            [_TV, _FH, _YC, _YF, _IB],
    # UAE is two entries now. Mubasher was the third and is gone: HTTP 403 from
    # Render, confirmed by the production probe.
    sym.UAE:           [_TV, _IB],
    sym.INDIA_EQ:      [_TV, _YC, _YF, _IB],
    # AMFI is the official all-schemes NAV file; nothing else covers these.
    sym.INDIA_FUND:    [_AM, _IB],
    sym.JAPAN:         [_TV, _YC, _YF, _BF, _IB],
    sym.SWISS:         [_TV, _YC, _YF, _BF, _IB],
    sym.LSE:           [_TV, _JE, _YC, _YF, _IB],
    sym.SGX:           [_TV, _YC, _YF, _BF, _IB],
    sym.HK:            [_TV, _YC, _YF, _BF, _IB],
    sym.KOREA:         [_TV, _YC, _YF, _BF, _IB],
    sym.CANADA:        [_TV, _YC, _YF, _IB],
    sym.EUROPE:        [_TV, _YC, _YF, _BF, _IB],
    sym.FUND_OFFSHORE: [_JE, _IB],
    sym.CRYPTO:        [_CX],
    sym.UNKNOWN:       [_YC, _YF, _IB],
}


@dataclass
class FetchReport:
    """What the pipeline did, for logging and the diagnostics panel."""
    requested: int = 0
    priced: int = 0
    by_source: Dict[str, int] = None
    by_latency: Dict[str, int] = None
    unpriced: List[str] = None
    elapsed_ms: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def fetch_quotes(instruments: List[Instrument]) -> tuple:
    """Price a list of instruments. Returns (quotes_by_ticker, FetchReport).

    Walks each market's tier list, handing every provider the full set of
    tickers still unpriced for that market. Providers are batch-shaped, so a
    tier is usually one HTTP call regardless of how many tickers it covers.
    """
    started = time.time()
    quotes: Dict[str, Quote] = {}
    if not instruments:
        return quotes, FetchReport(0, 0, {}, {}, [], 0)

    by_market: Dict[str, List[Instrument]] = {}
    for inst in instruments:
        by_market.setdefault(inst.market or sym.UNKNOWN, []).append(inst)

    for market, group in by_market.items():
        pending = {i.ticker: i for i in group}
        for provider in TIERS.get(market, TIERS[sym.UNKNOWN]):
            if not pending:
                break
            try:
                got = provider.fetch(list(pending.values()))
            except Exception as exc:               # noqa: BLE001 — a bad provider must not stop the tier walk
                log.warning("provider %s raised for %s: %r", provider.name, market, exc)
                continue
            for ticker, quote in (got or {}).items():
                if ticker in pending:
                    quotes[ticker] = quote
                    pending.pop(ticker, None)

    by_source: Dict[str, int] = {}
    by_latency: Dict[str, int] = {}
    for q in quotes.values():
        by_source[q.source] = by_source.get(q.source, 0) + 1
        by_latency[q.latency] = by_latency.get(q.latency, 0) + 1

    report = FetchReport(
        requested=len(instruments),
        priced=len(quotes),
        by_source=by_source,
        by_latency=by_latency,
        unpriced=sorted({i.ticker for i in instruments} - set(quotes)),
        elapsed_ms=int((time.time() - started) * 1000),
    )
    log.info(
        "market_data: %d/%d priced in %dms — %s",
        report.priced, report.requested, report.elapsed_ms, by_source,
    )
    return quotes, report


def fetch_for_tickers(tickers: List[str], meta: Optional[Dict[str, dict]] = None) -> tuple:
    """Convenience wrapper for callers that hold plain ticker strings.

    `meta` supplies identity fields per ticker (isin / listing_exchange /
    currency / asset_category) when the caller has them — which, once the IBKR
    parser stores them, it does.
    """
    meta = meta or {}
    instruments = [
        sym.build(
            t,
            listing_exchange=(meta.get(t) or {}).get("listing_exchange", ""),
            isin=(meta.get(t) or {}).get("isin", ""),
            conid=(meta.get(t) or {}).get("conid", ""),
            currency=(meta.get(t) or {}).get("currency", ""),
            asset_category=(meta.get(t) or {}).get("asset_category", ""),
            broker_source=(meta.get(t) or {}).get("broker_source", ""),
        )
        for t in tickers
    ]
    return fetch_quotes(instruments)
