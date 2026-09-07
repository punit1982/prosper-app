"""
HARVEST — options data layer
============================
Everything that reaches the network for the Options Desk. Deliberately free of Streamlit imports
at module level so `scripts/options_scan.py` can run it on a bare GitHub Actions runner.

What works, verified live 06-07 Sep 2026
----------------------------------------
* **CBOE delayed quotes** — `cdn.cboe.com/api/global/delayed_quotes/options/<SYM>.json`. Free, no
  key, and the only free source that carries **greeks and IV per contract** plus a top-level IV30
  and spot. Verified across US equities, ADRs (TSM, ASML), ETFs and index options (_SPX, _VIX).
  Index symbols take a leading underscore.
* **Finnhub `/calendar/earnings`** — 511 upcoming US earnings dates with bmo/amc timing on the
  existing free key. One call covers the whole blackout gate for a month.
* **Yahoo `chart`** — daily closes for realized volatility. Keyless, and already this app's price
  fallback.

What does NOT work — do not "fix" these by trying again
-------------------------------------------------------
* Yahoo's v7 options endpoint returns `401 Invalid Crumb`, exactly like `quoteSummary`. Dead.
* Twelve Data and FMP put options behind higher plan tiers than this account holds.
* The IBKR MCP connector has live greeks but authenticates as the user's personal Claude
  connector — Render can never call it.

Two hard-won operational constraints
------------------------------------
1. **CBOE rate-limits aggressively.** Eight parallel workers produced HTTP 429 within seconds and
   silently reported that NVDA, ORCL and PLTR have no listed options — nonsense that would have
   poisoned a whole scan. Sequential fetching at ~3s pacing ran 84/84 clean. `_Pacer` below
   implements adaptive throttling with exponential backoff. **Never add concurrency here.**
2. **Payloads are large** (AAPL 1.4MB, SPY 5.3MB, _SPX 12.4MB). A 110-name sweep moves ~150MB and
   takes 6-9 minutes. This can never run inside a Streamlit page request — it is a nightly job.
   `slice_chain()` reduces each chain to the few dozen contracts that matter before anything is
   stored, so the database holds kilobytes rather than gigabytes.
"""

from __future__ import annotations

import json
import math
import re
import time
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

_log = logging.getLogger("prosper.harvest.data")

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
FINNHUB_EARNINGS = "https://finnhub.io/api/v1/calendar/earnings?from={frm}&to={to}&token={key}"

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"}

# OSI contract symbol: ROOT + YYMMDD + C|P + strike x 1000, zero-padded to 8.
_OSI = re.compile(r"^([A-Z0-9]{1,6})(\d{6})([CP])(\d{8})$")

# Symbols CBOE serves under an underscore prefix (cash-settled index options).
_INDEX_SYMBOLS = {"SPX", "VIX", "NDX", "RUT", "XSP", "DJX"}


# ─────────────────────────────────────────────────────────────────────────────
# Pacing
# ─────────────────────────────────────────────────────────────────────────────

class _Pacer:
    """Adaptive sequential throttle for CBOE.

    Starts polite, backs off hard on 429, and creeps back toward the floor after sustained
    success. The floor is 2.0s because 3.0s ran 84/84 clean and 0.0s (8 workers) failed within
    seconds — there is no measured benefit to going faster and a large measured cost to trying.
    """

    FLOOR = 2.0
    START = 3.0
    CEILING = 30.0

    def __init__(self, start: float = None):
        self.delay = float(start or self.START)
        self._last = 0.0
        self._streak = 0

    def wait(self):
        gap = time.time() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.time()

    def ok(self):
        self._streak += 1
        if self._streak >= 8 and self.delay > self.FLOOR:
            self.delay = max(self.FLOOR, self.delay * 0.85)
            self._streak = 0

    def throttled(self):
        self._streak = 0
        self.delay = min(self.CEILING, max(self.delay * 2.0, 8.0))
        _log.warning("CBOE 429 — backing off to %.1fs between requests", self.delay)


_PACER = _Pacer()


def _http_json(url: str, timeout: int = 45, headers: dict = None) -> Optional[dict]:
    req = urllib.request.Request(url, headers=headers or _UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ─────────────────────────────────────────────────────────────────────────────
# Contract symbols
# ─────────────────────────────────────────────────────────────────────────────

def parse_osi(symbol: str) -> Optional[dict]:
    """Decode an OSI contract symbol into root / expiry / right / strike.

    'AAPL261016C00205000' -> {root: AAPL, expiry: date(2026,10,16), right: 'C', strike: 205.0}
    Returns None on anything that isn't a well-formed OSI symbol — non-standard roots and
    adjusted contracts (post split/merger, root suffixed with a digit) are rejected rather than
    guessed at, because pricing an adjusted contract as if it were standard is how you write a
    call against a deliverable you do not own.
    """
    m = _OSI.match((symbol or "").strip().upper())
    if not m:
        return None
    root, ymd, right, strike = m.groups()
    try:
        expiry = datetime.strptime(ymd, "%y%m%d").date()
    except ValueError:
        return None
    return {"root": root, "expiry": expiry, "right": right, "strike": int(strike) / 1000.0}


def cboe_symbol(ticker: str) -> str:
    """CBOE serves cash-settled index options under a leading underscore."""
    t = (ticker or "").strip().upper()
    return f"_{t}" if t in _INDEX_SYMBOLS else t


def is_adjusted_root(contract_symbol: str, underlying: str) -> bool:
    """True when the contract's root differs from the underlying — an adjusted/non-standard
    deliverable (AAPL1, MSFT2 …). These never enter a ticket."""
    p = parse_osi(contract_symbol)
    if not p:
        return True
    return p["root"] != (underlying or "").strip().upper()


# ─────────────────────────────────────────────────────────────────────────────
# CBOE chains
# ─────────────────────────────────────────────────────────────────────────────

class ChainUnavailable(Exception):
    """No listed options for this underlying (CBOE 403/404), or the fetch failed."""


def fetch_chain(ticker: str, *, retries: int = 3, pacer: _Pacer = None) -> dict:
    """Return CBOE's `data` block for one underlying. Raises ChainUnavailable.

    A 403 or 404 is a real answer — the name has no listed options (QTEX returns 403). It is not
    retried, because retrying turns a 2-second "no" into a 45-second one across a whole scan.
    """
    pacer = pacer or _PACER
    sym = cboe_symbol(ticker)
    url = CBOE_URL.format(sym=sym)
    last = None
    for attempt in range(retries):
        pacer.wait()
        try:
            payload = _http_json(url)
            pacer.ok()
            data = (payload or {}).get("data") or {}
            if not data.get("options"):
                raise ChainUnavailable(f"{ticker}: empty chain")
            data["_timestamp"] = (payload or {}).get("timestamp")
            data["_underlying"] = (ticker or "").strip().upper()
            return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 404):
                raise ChainUnavailable(f"{ticker}: no listed options (HTTP {e.code})")
            if e.code == 429:
                pacer.throttled()
                continue
            if attempt == retries - 1:
                break
        except ChainUnavailable:
            raise
        except Exception as e:                      # timeout, JSON error, connection reset
            last = e
            time.sleep(2.0 * (attempt + 1))
    raise ChainUnavailable(f"{ticker}: chain fetch failed ({last})")


def slice_chain(data: dict, *, today: date = None, dte_min: int = 7, dte_max: int = 130,
                moneyness: float = 0.45) -> List[dict]:
    """Reduce a raw CBOE chain to the contracts a strategy could plausibly use.

    A raw chain is 100kB-12MB and up to 28,000 contracts. Everything outside a sane expiry window
    and a band around spot is noise that would otherwise be stored, re-read and re-parsed every
    day. Typically returns 150-600 contracts.

    `dte_max` reaches 130 days deliberately. No strategy trades that far out, but
    `vol_metrics.term_structure()` needs a back-month ATM strike to measure the front against,
    and a 70-day window silently returned None for every name.

    `moneyness` keeps strikes within +/-45% of spot, which comfortably covers the 0.10-0.40 delta
    band used by every Harvest strategy while discarding the deep-ITM and lottery wings.
    """
    today = today or date.today()
    spot = _f(data.get("current_price"))
    if not spot or spot <= 0:
        return []
    underlying = data.get("_underlying") or ""
    lo, hi = spot * (1 - moneyness), spot * (1 + moneyness)

    out: List[dict] = []
    for o in data.get("options") or []:
        sym = o.get("option") or ""
        p = parse_osi(sym)
        if not p or p["root"] != underlying:
            continue                                # adjusted / non-standard deliverable
        dte = (p["expiry"] - today).days
        if dte < dte_min or dte > dte_max:
            continue
        k = p["strike"]
        if k < lo or k > hi:
            continue
        bid, ask = _f(o.get("bid")) or 0.0, _f(o.get("ask")) or 0.0
        mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else 0.0
        out.append({
            "symbol": sym,
            "expiry": p["expiry"].isoformat(),
            "dte": dte,
            "right": p["right"],
            "strike": k,
            "bid": bid,
            "ask": ask,
            "mid": round(mid, 4),
            "spread_pct": round((ask - bid) / mid * 100, 2) if mid > 0 else None,
            "iv": _f(o.get("iv")),
            "delta": _f(o.get("delta")),
            "gamma": _f(o.get("gamma")),
            "theta": _f(o.get("theta")),
            "vega": _f(o.get("vega")),
            "open_interest": int(_f(o.get("open_interest")) or 0),
            "volume": int(_f(o.get("volume")) or 0),
            "theo": _f(o.get("theo")),
            "last_trade_time": o.get("last_trade_time"),
        })
    return out


def chain_snapshot(ticker: str, *, today: date = None, pacer: _Pacer = None) -> dict:
    """One underlying, fetched and reduced. The unit of work for the nightly scan."""
    data = fetch_chain(ticker, pacer=pacer)
    contracts = slice_chain(data, today=today)
    return {
        "ticker": (ticker or "").strip().upper(),
        "spot": _f(data.get("current_price")),
        "iv30": _f(data.get("iv30")),
        "iv30_change": _f(data.get("iv30_change")),
        "prev_close": _f(data.get("prev_day_close")),
        "quote_timestamp": data.get("_timestamp"),
        "contracts": contracts,
        "n_raw": len(data.get("options") or []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Quote freshness — the weekend problem
# ─────────────────────────────────────────────────────────────────────────────

def quote_is_stale(quote_timestamp: str, *, max_age_hours: float = 20.0) -> bool:
    """True when the CBOE snapshot predates the last session by enough that bid/ask is unreliable.

    This matters more than it sounds. A Sunday scan produced a 115% median spread on XLF — one of
    the most liquid ETFs alive — because Friday's closing quotes sit stale on strikes that did not
    trade. Open interest survives the weekend; bid/ask does not. Any spread figure from a stale
    snapshot must be re-checked before an order is placed, and the UI says so.
    """
    if not quote_timestamp:
        return True
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            ts = datetime.strptime(str(quote_timestamp)[:19], fmt)
            return (datetime.now() - ts) > timedelta(hours=max_age_hours)
        except ValueError:
            continue
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Realized volatility inputs
# ─────────────────────────────────────────────────────────────────────────────

_YAHOO_PACER = _Pacer(start=1.2)


def _closes_from_yahoo(ticker: str, lookback: str, timeout: int) -> List[float]:
    """Yahoo `chart` — keyless, and already this app's price fallback.

    Yahoo rate-limits with HTTP 429 under sustained use, exactly as CBOE does. A 110-name nightly
    sweep is sustained use, so this shares the same paced/backoff treatment rather than firing
    requests back to back and silently returning empty lists — which is what an unpaced version
    did, producing `hv20=None` on every name and disabling the whole variance-risk-premium signal.
    """
    for attempt in range(3):
        _YAHOO_PACER.wait()
        try:
            d = _http_json(YAHOO_CHART.format(sym=ticker, rng=lookback), timeout=timeout)
            _YAHOO_PACER.ok()
            result = ((d or {}).get("chart") or {}).get("result") or []
            if not result:
                return []
            quote = (result[0].get("indicators", {}).get("quote") or [{}])[0]
            return [float(c) for c in (quote.get("close") or []) if c is not None and float(c) > 0]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _YAHOO_PACER.throttled()
                continue
            return []
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return []


def _closes_from_twelve_data(ticker: str, api_key: str, bars: int, timeout: int) -> List[float]:
    """Twelve Data `time_series` — the paid Basic plan covers US equities and ETFs.

    Not a general price source for this app (it does not cover India, UAE or the offshore funds),
    but the Harvest universe is entirely US-listed, so it is a complete fallback *here*. Verified
    live: 130 daily bars for ORCL on the current key.
    """
    if not api_key or api_key.startswith("your_"):
        return []
    url = (f"https://api.twelvedata.com/time_series?symbol={ticker}&interval=1day"
           f"&outputsize={bars}&apikey={api_key}")
    try:
        d = _http_json(url, timeout=timeout)
    except Exception:
        return []
    if (d or {}).get("status") != "ok":
        return []
    # Twelve Data returns newest-first; realized_vol() expects chronological order.
    values = list(reversed((d or {}).get("values") or []))
    out = []
    for row in values:
        try:
            c = float(row.get("close"))
            if c > 0:
                out.append(c)
        except (TypeError, ValueError):
            continue
    return out


def fetch_closes(ticker: str, *, lookback: str = "6mo", timeout: int = 25,
                 twelve_data_key: str = "") -> List[float]:
    """Daily closes for realized-volatility maths, Yahoo first then Twelve Data.

    Deliberately NOT routed through core.data_engine.get_history(): that is decorated with
    st.cache_data and expects a Streamlit runtime, and yfinance segfaults in the local venv.

    Realized vol is not optional garnish — it is the denominator of the variance risk premium,
    which is the single signal that decides whether premium is worth selling. A silent empty list
    here turns every VRP into None and the engine into a yield-ranker, which is precisely the
    failure mode the doctrine exists to prevent. Hence two independent sources.
    """
    closes = _closes_from_yahoo(ticker, lookback, timeout)
    if len(closes) >= 40:
        return closes
    fallback = _closes_from_twelve_data(ticker, twelve_data_key, 130, timeout)
    if len(fallback) > len(closes):
        _log.info("closes for %s served by Twelve Data fallback (%d bars)", ticker, len(fallback))
        return fallback
    if not closes:
        _log.warning("no price history for %s from either source — VRP will be unavailable", ticker)
    return closes


# ─────────────────────────────────────────────────────────────────────────────
# Earnings blackout (doctrine R6)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_earnings_calendar(api_key: str, *, days_ahead: int = 75) -> Dict[str, dict]:
    """{TICKER: {'date': 'YYYY-MM-DD', 'hour': 'bmo'|'amc'|''}} for the window ahead.

    ONE call covers the entire universe — 511 rows for a five-week window on the free key. Only
    the soonest date per ticker is kept, which is the only one a 25-50 DTE trade can span.
    """
    if not api_key or api_key.startswith("your_"):
        return {}
    frm = date.today().isoformat()
    to = (date.today() + timedelta(days=days_ahead)).isoformat()
    try:
        d = _http_json(FINNHUB_EARNINGS.format(frm=frm, to=to, key=api_key), timeout=30)
    except Exception as e:
        _log.warning("earnings calendar unavailable: %s", e)
        return {}
    out: Dict[str, dict] = {}
    for row in (d or {}).get("earningsCalendar") or []:
        sym = (row.get("symbol") or "").strip().upper()
        dt = row.get("date")
        if not sym or not dt:
            continue
        prev = out.get(sym)
        if prev is None or dt < prev["date"]:
            out[sym] = {"date": dt, "hour": (row.get("hour") or "").strip()}
    return out


def earnings_before(expiry_iso: str, earnings: Optional[dict], today: date = None) -> bool:
    """True when a known earnings date falls between today and expiry — doctrine R6 blackout.

    A name with no known date is treated as clear, and the ticket states that explicitly rather
    than implying the check passed on evidence.
    """
    if not earnings or not earnings.get("date"):
        return False
    today = today or date.today()
    try:
        ed = datetime.strptime(earnings["date"], "%Y-%m-%d").date()
        xd = datetime.strptime(expiry_iso, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    return today <= ed <= xd


# ─────────────────────────────────────────────────────────────────────────────

def _f(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None
