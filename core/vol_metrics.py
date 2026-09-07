"""
HARVEST — volatility metrics
============================
The signal layer. Pure arithmetic over a chain snapshot and a price history; no network, no model,
no Streamlit. Every function here is unit-testable, which matters because these numbers decide
whether a trade is proposed.

The central signal is the **variance risk premium** — implied volatility against what the stock is
actually realizing. It is what separates a good premium sale from a bad one, and it is computable
on day one with no history at all.

Why that matters more than IV rank
----------------------------------
Measured across this book on 06-Sep-2026:

    CRDO   IV30 71.9   HV20 111.0   ratio 0.65   <- 72% IV looks rich; the stock realizes 111%.
    U      IV30 51.8   HV20  29.8   ratio 1.74      Selling CRDO calls is a losing trade.
    ORCL   IV30 68.3   HV20  49.0   ratio 1.39
    HIMS   IV30 65.2   HV20  81.1   ratio 0.80   <- largest raw premium in the book, and a sale.

A screen ranked on premium yield puts CRDO and HIMS near the top. The ratio rejects both. IV
percentile rank would not have caught either, because both are high against their own history.

IV percentile is still worth having as a second opinion — it needs ~120 daily observations, so
`vol_history` has to start accumulating from day one. Until it has, `iv_percentile()` returns None
and nothing downstream pretends otherwise.
"""

from __future__ import annotations

import math
import statistics
from typing import Dict, List, Optional, Sequence

TRADING_DAYS = 252

# Doctrine R2 thresholds.
SELL_VRP_FLOOR = 1.10     # below this, do not sell premium
BUY_VRP_CEILING = 0.90    # at or below this, options are cheap — buy protection


# ─────────────────────────────────────────────────────────────────────────────
# Realized volatility
# ─────────────────────────────────────────────────────────────────────────────

def log_returns(closes: Sequence[float]) -> List[float]:
    out = []
    for i in range(1, len(closes)):
        a, b = closes[i - 1], closes[i]
        if a and b and a > 0 and b > 0:
            out.append(math.log(b / a))
    return out


def realized_vol(closes: Sequence[float], window: int = 20) -> Optional[float]:
    """Annualised close-to-close realized volatility, in percent.

    Population standard deviation (not sample): the mean is not estimated from a separate sample
    here, and with a 20-day window the Bessel correction moves the answer by ~2.5% of its own
    value — enough to shift a borderline VRP ratio across the 1.10 threshold if applied
    inconsistently. Fixed choice, applied everywhere.
    """
    r = log_returns(closes)
    if len(r) < max(5, window // 2):
        return None
    r = r[-window:]
    if len(r) < 2:
        return None
    return statistics.pstdev(r) * math.sqrt(TRADING_DAYS) * 100.0


def vol_of_vol(closes: Sequence[float], window: int = 60) -> Optional[float]:
    """Dispersion of 20-day realized vol over the window — how stable the vol regime is.

    A name whose realized vol swings between 40% and 120% is not really described by a single HV20
    number, and a VRP ratio computed from one is fragile. Surfaced so the engine can prefer stable
    regimes when two candidates are otherwise equal.
    """
    r = log_returns(closes)
    if len(r) < window + 20:
        return None
    series = []
    for end in range(20, len(r) + 1):
        w = r[end - 20:end]
        series.append(statistics.pstdev(w) * math.sqrt(TRADING_DAYS) * 100.0)
    series = series[-window:]
    if len(series) < 5:
        return None
    return statistics.pstdev(series)


# ─────────────────────────────────────────────────────────────────────────────
# Variance risk premium
# ─────────────────────────────────────────────────────────────────────────────

def vrp_ratio(iv30: Optional[float], hv20: Optional[float]) -> Optional[float]:
    """IV30 / HV20. Above 1.10 sell, below 0.90 buy, in between no edge."""
    if not iv30 or not hv20 or hv20 <= 0:
        return None
    return round(iv30 / hv20, 4)


def vrp_verdict(ratio: Optional[float]) -> str:
    """'sell' | 'buy' | 'neutral' | 'unknown' — doctrine R2."""
    if ratio is None:
        return "unknown"
    if ratio >= SELL_VRP_FLOOR:
        return "sell"
    if ratio <= BUY_VRP_CEILING:
        return "buy"
    return "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# IV percentile — needs history, degrades honestly without it
# ─────────────────────────────────────────────────────────────────────────────

MIN_HISTORY_FOR_PERCENTILE = 120


def iv_percentile(current_iv: Optional[float], history: Sequence[float]) -> Optional[float]:
    """Share of historical observations below the current IV, 0-100.

    Returns None below MIN_HISTORY_FOR_PERCENTILE observations rather than a misleading number
    computed from three weeks of data. Callers must treat None as "not yet knowable".
    """
    if current_iv is None or not history:
        return None
    clean = [h for h in history if h is not None and h > 0]
    if len(clean) < MIN_HISTORY_FOR_PERCENTILE:
        return None
    below = sum(1 for h in clean if h < current_iv)
    return round(below / len(clean) * 100.0, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Term structure and skew — computable from a single snapshot
# ─────────────────────────────────────────────────────────────────────────────

def _atm_iv(contracts: List[dict], spot: float, right: str, dte_lo: int, dte_hi: int) -> Optional[float]:
    """Mean IV of the two strikes nearest spot in the DTE band, for one right."""
    band = [c for c in contracts
            if c.get("right") == right and dte_lo <= (c.get("dte") or 0) <= dte_hi
            and c.get("iv") and c.get("strike")]
    if not band:
        return None
    band.sort(key=lambda c: abs(c["strike"] - spot))
    near = band[:2]
    return sum(c["iv"] for c in near) / len(near) * 100.0


def term_structure(contracts: List[dict], spot: float) -> Optional[float]:
    """Back-month ATM IV minus front-month ATM IV, in vol points.

    Positive (contango) is the normal state and mildly favours selling the front. Sharply negative
    (backwardation) means the market expects something soon — often an event the earnings calendar
    does not carry, and a reason to stand aside rather than collect the fat front-month premium.
    """
    front = _atm_iv(contracts, spot, "C", 7, 35)
    back = _atm_iv(contracts, spot, "C", 45, 130)
    if front is None or back is None:
        return None
    return round(back - front, 2)


def put_skew(contracts: List[dict], spot: float, *, dte_lo: int = 20, dte_hi: int = 60) -> Optional[float]:
    """25-delta put IV minus 25-delta call IV, in vol points.

    High positive skew means downside protection is expensive relative to upside — which makes
    selling puts *look* attractive and is exactly when it is most dangerous. Reported so the
    engine can size a short put down when the market is paying up for crash protection.
    """
    def _near_delta(right: str, target: float) -> Optional[float]:
        band = [c for c in contracts
                if c.get("right") == right and dte_lo <= (c.get("dte") or 0) <= dte_hi
                and c.get("iv") and c.get("delta") is not None]
        if not band:
            return None
        best = min(band, key=lambda c: abs(abs(c["delta"]) - target))
        return best["iv"] * 100.0 if abs(abs(best["delta"]) - target) < 0.12 else None

    p = _near_delta("P", 0.25)
    c = _near_delta("C", 0.25)
    if p is None or c is None:
        return None
    return round(p - c, 2)


def chain_liquidity(contracts: List[dict]) -> Dict[str, float]:
    """Depth summary used for gating and for the UI's confidence line."""
    if not contracts:
        return {"total_oi": 0, "total_volume": 0, "n_expiries": 0, "median_spread_pct": None}
    spreads = [c["spread_pct"] for c in contracts
               if c.get("spread_pct") is not None and (c.get("open_interest") or 0) >= 50]
    return {
        "total_oi": int(sum(c.get("open_interest") or 0 for c in contracts)),
        "total_volume": int(sum(c.get("volume") or 0 for c in contracts)),
        "n_expiries": len({c.get("expiry") for c in contracts if c.get("expiry")}),
        "median_spread_pct": round(statistics.median(spreads), 2) if spreads else None,
    }


# ─────────────────────────────────────────────────────────────────────────────

def build_metrics(snapshot: dict, closes: Sequence[float], iv_history: Sequence[float] = None) -> dict:
    """Everything the candidate generator needs to know about one underlying's volatility."""
    spot = snapshot.get("spot") or 0.0
    contracts = snapshot.get("contracts") or []
    iv30 = snapshot.get("iv30")

    hv20 = realized_vol(closes, 20)
    hv60 = realized_vol(closes, 60)
    ratio = vrp_ratio(iv30, hv20)

    return {
        "ticker": snapshot.get("ticker"),
        "spot": spot,
        "iv30": iv30,
        "hv20": round(hv20, 2) if hv20 else None,
        "hv60": round(hv60, 2) if hv60 else None,
        "vol_of_vol": round(vol_of_vol(closes) or 0, 2) or None,
        "vrp": ratio,
        "vrp_verdict": vrp_verdict(ratio),
        "iv_percentile": iv_percentile(iv30, iv_history or []),
        "term_structure": term_structure(contracts, spot) if spot else None,
        "put_skew": put_skew(contracts, spot) if spot else None,
        **chain_liquidity(contracts),
    }
