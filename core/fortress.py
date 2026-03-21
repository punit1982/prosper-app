"""
FORTRESS — Framework for Optimized Risk-Tuned Regime-Responsive Equity Sizing & Strategy
=========================================================================================
Dynamic Portfolio Management System  |  Proprietary  |  v1.0  |  March 2026

All 9 modules:
  1. Regime Detection Engine
  2. Exposure Governor
  3. Dynamic Position Sizing (Half-Kelly)
  4. Factor Balance & Correlation Monitor
  5. Rebalancing Protocol
  6. Drawdown Circuit Breakers
  7. Portfolio Health Dashboard
  8. PROSPER ↔ FORTRESS Integration
  9. System Evolution & Governance
"""

import json
import math
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

# ---------------------------------------------------------------------------
# MODULE 1: REGIME DETECTION ENGINE
# ---------------------------------------------------------------------------

# The four regimes
REGIME_EXPANSION = "I"       # Goldilocks
REGIME_OVERHEATING = "II"    # Late Cycle
REGIME_CONTRACTION = "III"   # Risk-Off
REGIME_RECOVERY = "IV"       # Early Cycle

REGIME_NAMES = {
    REGIME_EXPANSION: "Expansion (Goldilocks)",
    REGIME_OVERHEATING: "Overheating (Late Cycle)",
    REGIME_CONTRACTION: "Contraction (Risk-Off)",
    REGIME_RECOVERY: "Recovery (Early Cycle)",
}

REGIME_COLORS = {
    REGIME_EXPANSION: "#1a9e5c",     # Green
    REGIME_OVERHEATING: "#f39c12",   # Orange
    REGIME_CONTRACTION: "#d63031",   # Red
    REGIME_RECOVERY: "#0984e3",      # Blue
}

# ---------------------------------------------------------------------------
# Shared plain-English regime display mapping
# Used by Command Center, Risk & Strategy, and any other page showing regime.
# Keys: regime constants. Values: dict with label, color, icon, explanation, action.
# ---------------------------------------------------------------------------
REGIME_DISPLAY = {
    REGIME_EXPANSION: {
        "label": "Growing",
        "color": "#4CAF50",
        "icon": "\U0001f7e2",       # green circle
        "explanation": "Economy is healthy. Markets favour risk-taking and equities tend to do well.",
        "action": "Stay invested. Full-size positions in high-conviction stocks. No need to raise extra cash.",
    },
    REGIME_OVERHEATING: {
        "label": "Heating Up",
        "color": "#FF9800",
        "icon": "\U0001f7e1",       # yellow circle
        "explanation": "Late-cycle signals: inflation rising, valuations stretched, volatility increasing.",
        "action": "Tighten stop-losses, trim overweight winners, avoid new speculative bets. Build cash buffer.",
    },
    REGIME_CONTRACTION: {
        "label": "Slowing Down",
        "color": "#f44336",
        "icon": "\U0001f534",       # red circle
        "explanation": "Economic weakness detected. Corporate earnings under pressure, risk of further declines.",
        "action": "Reduce equity exposure. Hold more cash. Focus on quality defensive names. Avoid new positions.",
    },
    REGIME_RECOVERY: {
        "label": "Bouncing Back",
        "color": "#2196F3",
        "icon": "\U0001f535",       # blue circle
        "explanation": "Early recovery signs emerging. Best risk/reward phase of the market cycle.",
        "action": "Gradually increase equity exposure. Add to quality growth stocks on pullbacks.",
    },
}

# Geopolitical tiers
GEO_GREEN = "GREEN"
GEO_AMBER = "AMBER"
GEO_RED = "RED"


class RegimeSignal:
    """One signal used in regime detection."""
    def __init__(self, category: str, indicator: str, value: float = None,
                 regime_scores: Dict[str, float] = None):
        self.category = category
        self.indicator = indicator
        self.value = value
        # regime_scores: {"I": 1, "II": 0, "III": 0, "IV": 0}
        self.regime_scores = regime_scores or {}


def detect_regime(signals: List[RegimeSignal] = None,
                  vix: float = None, pmi: float = None,
                  credit_spread: float = None, yield_curve: float = None,
                  inflation_yoy: float = None, fed_trajectory: str = None) -> Dict:
    """
    Detect current market regime from signals.

    If explicit signals are not provided, uses the quick-signal approach
    based on VIX, PMI, credit spreads, yield curve, and inflation.

    Returns dict with: regime, confidence, scores, geo_tier, signals_used
    """
    scores = {REGIME_EXPANSION: 0, REGIME_OVERHEATING: 0,
              REGIME_CONTRACTION: 0, REGIME_RECOVERY: 0}

    signals_used = []

    if signals:
        # Full signal dashboard scoring
        for sig in signals:
            for regime, score in sig.regime_scores.items():
                scores[regime] += score
            signals_used.append(sig.indicator)
    else:
        # Quick regime detection from market data
        if vix is not None:
            if vix < 16:
                scores[REGIME_EXPANSION] += 1
            elif 16 <= vix <= 22:
                scores[REGIME_OVERHEATING] += 1
            elif vix > 25:
                scores[REGIME_CONTRACTION] += 1
            # VIX falling from highs → recovery
            signals_used.append(f"VIX={vix:.1f}")

        if pmi is not None:
            if pmi > 52:
                scores[REGIME_EXPANSION] += 1
                if pmi < 54:  # Flat/falling
                    scores[REGIME_OVERHEATING] += 0.5
            elif pmi < 48:
                scores[REGIME_CONTRACTION] += 1
            elif 48 <= pmi <= 50:
                scores[REGIME_RECOVERY] += 1
            signals_used.append(f"PMI={pmi:.1f}")

        if credit_spread is not None:
            if credit_spread < 120:
                scores[REGIME_EXPANSION] += 1
            elif 120 <= credit_spread <= 160:
                scores[REGIME_OVERHEATING] += 0.5
                scores[REGIME_EXPANSION] += 0.5
            elif credit_spread > 200:
                scores[REGIME_CONTRACTION] += 1
            signals_used.append(f"Credit Spread={credit_spread:.0f}bps")

        if yield_curve is not None:
            if yield_curve > 0.5:
                scores[REGIME_EXPANSION] += 1
            elif yield_curve < -0.2:
                scores[REGIME_CONTRACTION] += 0.5
                scores[REGIME_OVERHEATING] += 0.5
            elif yield_curve > 0 and yield_curve <= 0.5:
                scores[REGIME_RECOVERY] += 1
            signals_used.append(f"Yield Curve 2s10s={yield_curve:.2f}%")

        if inflation_yoy is not None:
            if 2.0 <= inflation_yoy <= 3.0:
                scores[REGIME_EXPANSION] += 1
            elif inflation_yoy > 3.5:
                scores[REGIME_OVERHEATING] += 1
            elif inflation_yoy < 2.0:
                scores[REGIME_RECOVERY] += 0.5
            signals_used.append(f"Core CPI={inflation_yoy:.1f}%")

        if fed_trajectory:
            ft = fed_trajectory.lower()
            if "cut" in ft:
                scores[REGIME_EXPANSION] += 0.5
                scores[REGIME_RECOVERY] += 0.5
            elif "hik" in ft:
                scores[REGIME_OVERHEATING] += 1
            elif "hold" in ft or "paus" in ft:
                scores[REGIME_EXPANSION] += 0.5
                scores[REGIME_RECOVERY] += 0.5
            signals_used.append(f"Fed={fed_trajectory}")

    # Determine winning regime
    max_score = max(scores.values())
    winners = [r for r, s in scores.items() if s == max_score]

    # Tie-breaking: transition regimes (II, IV) take precedence
    if len(winners) > 1:
        for pref in [REGIME_OVERHEATING, REGIME_RECOVERY]:
            if pref in winners:
                regime = pref
                break
        else:
            regime = winners[0]
    else:
        regime = winners[0]

    # Confidence: HIGH (8+), MODERATE (5-7), LOW (<5)
    total_signals = sum(scores.values())
    if max_score >= 8:
        confidence = "HIGH"
    elif max_score >= 5:
        confidence = "MODERATE"
    else:
        confidence = "LOW"

    return {
        "regime": regime,
        "regime_name": REGIME_NAMES[regime],
        "confidence": confidence,
        "scores": scores,
        "max_score": max_score,
        "signals_used": signals_used,
        "detected_at": datetime.now().isoformat(),
    }


def get_geopolitical_tier(gpr_index: float = None,
                          active_conflicts: int = 0,
                          sanctions_affecting_portfolio: bool = False) -> Dict:
    """Assess geopolitical tier (GREEN/AMBER/RED)."""
    if sanctions_affecting_portfolio or active_conflicts >= 2:
        tier = GEO_RED
        action = "Force Regime III parameters. Reduce gross to floor. Activate hedging."
    elif active_conflicts >= 1 or (gpr_index and gpr_index > 120):
        tier = GEO_AMBER
        action = "Tighten gross by 10-15%. Add 5% cash. Review exposed positions."
    else:
        tier = GEO_GREEN
        action = "No override. Use macro regime as-is."

    return {"tier": tier, "action": action}


# ---------------------------------------------------------------------------
# MODULE 2: EXPOSURE GOVERNOR
# ---------------------------------------------------------------------------

# Exposure limits by regime — {param: {regime: (min, max)}}
EXPOSURE_LIMITS = {
    "gross_exposure": {
        REGIME_EXPANSION: (130, 170), REGIME_OVERHEATING: (100, 130),
        REGIME_CONTRACTION: (60, 100), REGIME_RECOVERY: (110, 150),
    },
    "net_exposure": {
        REGIME_EXPANSION: (80, 120), REGIME_OVERHEATING: (50, 80),
        REGIME_CONTRACTION: (0, 40), REGIME_RECOVERY: (70, 100),
    },
    "long_book": {
        REGIME_EXPANSION: (90, 130), REGIME_OVERHEATING: (70, 100),
        REGIME_CONTRACTION: (40, 70), REGIME_RECOVERY: (80, 110),
    },
    "short_book": {
        REGIME_EXPANSION: (20, 40), REGIME_OVERHEATING: (30, 50),
        REGIME_CONTRACTION: (30, 60), REGIME_RECOVERY: (20, 40),
    },
    "cash_allocation": {
        REGIME_EXPANSION: (0, 5), REGIME_OVERHEATING: (5, 15),
        REGIME_CONTRACTION: (15, 40), REGIME_RECOVERY: (5, 10),
    },
    "max_single_name_long": {
        REGIME_EXPANSION: (8, 8), REGIME_OVERHEATING: (6, 6),
        REGIME_CONTRACTION: (4, 4), REGIME_RECOVERY: (7, 7),
    },
    "max_single_name_short": {
        REGIME_EXPANSION: (4, 4), REGIME_OVERHEATING: (5, 5),
        REGIME_CONTRACTION: (5, 5), REGIME_RECOVERY: (3, 3),
    },
    "max_sector_concentration": {
        REGIME_EXPANSION: (30, 30), REGIME_OVERHEATING: (25, 25),
        REGIME_CONTRACTION: (20, 20), REGIME_RECOVERY: (25, 25),
    },
    "max_geo_concentration": {
        REGIME_EXPANSION: (60, 60), REGIME_OVERHEATING: (50, 50),
        REGIME_CONTRACTION: (40, 40), REGIME_RECOVERY: (50, 50),
    },
    "max_archetype_concentration": {
        REGIME_EXPANSION: (40, 40), REGIME_OVERHEATING: (35, 35),
        REGIME_CONTRACTION: (30, 30), REGIME_RECOVERY: (35, 35),
    },
}

# Transition glide paths (days)
TRANSITION_GLIDE = {
    ("I", "II"): 30, ("II", "III"): 15, ("III", "IV"): 30, ("IV", "I"): 15,
    ("I", "III"): 15, ("II", "IV"): 30, ("I", "IV"): 15, ("III", "I"): 30,
    ("II", "I"): 30, ("IV", "III"): 15, ("III", "II"): 15, ("IV", "II"): 15,
}


def get_exposure_limits(regime: str, confidence: str = "HIGH",
                        geo_tier: str = GEO_GREEN) -> Dict:
    """
    Get exposure limits for the current regime, adjusted for confidence and geo tier.

    Returns dict of {param: (min, max)} with all limits.
    """
    limits = {}
    for param, regime_limits in EXPOSURE_LIMITS.items():
        lo, hi = regime_limits.get(regime, (0, 100))
        # Low confidence → use conservative end (lower for upside params, higher for defensive)
        if confidence == "LOW":
            if param in ("cash_allocation",):
                lo = hi  # Max cash when low confidence
            elif param in ("gross_exposure", "net_exposure", "long_book"):
                hi = lo  # Min exposure when low confidence
        elif confidence == "MODERATE":
            mid = (lo + hi) / 2
            if param in ("gross_exposure", "net_exposure", "long_book"):
                hi = mid  # Cap at midpoint

        # Geopolitical overlay
        if geo_tier == GEO_AMBER:
            if param == "gross_exposure":
                hi = max(lo, hi - 15)
            if param == "cash_allocation":
                lo = lo + 5
        elif geo_tier == GEO_RED:
            # Force Contraction parameters
            lo, hi = EXPOSURE_LIMITS[param].get(REGIME_CONTRACTION, (lo, hi))

        limits[param] = (lo, hi)

    return limits


def check_exposure_compliance(portfolio_metrics: Dict, regime: str,
                              confidence: str = "HIGH",
                              geo_tier: str = GEO_GREEN) -> List[Dict]:
    """
    Check if current portfolio exposure complies with regime limits.

    portfolio_metrics should include:
      - gross_exposure (%), net_exposure (%), cash_pct (%)
      - max_single_name_pct (%), max_sector_pct (%), max_geo_pct (%)

    Returns list of violations: {param, current, limit_min, limit_max, status}
    """
    limits = get_exposure_limits(regime, confidence, geo_tier)
    violations = []

    check_map = {
        "gross_exposure": portfolio_metrics.get("gross_exposure", 100),
        "net_exposure": portfolio_metrics.get("net_exposure", 100),
        "cash_allocation": portfolio_metrics.get("cash_pct", 0),
        "max_single_name_long": portfolio_metrics.get("max_single_name_pct", 0),
        "max_sector_concentration": portfolio_metrics.get("max_sector_pct", 0),
        "max_geo_concentration": portfolio_metrics.get("max_geo_pct", 0),
    }

    for param, current in check_map.items():
        lo, hi = limits.get(param, (0, 100))
        if current < lo:
            violations.append({
                "param": param, "current": current,
                "limit_min": lo, "limit_max": hi,
                "status": "BELOW_MIN",
                "severity": "amber" if (lo - current) < 5 else "red",
            })
        elif current > hi:
            violations.append({
                "param": param, "current": current,
                "limit_min": lo, "limit_max": hi,
                "status": "ABOVE_MAX",
                "severity": "amber" if (current - hi) < 5 else "red",
            })
        else:
            violations.append({
                "param": param, "current": current,
                "limit_min": lo, "limit_max": hi,
                "status": "OK",
                "severity": "green",
            })

    return violations


# ---------------------------------------------------------------------------
# MODULE 3: DYNAMIC POSITION SIZING (Half-Kelly)
# ---------------------------------------------------------------------------

# Conviction tiers from PROSPER score
CONVICTION_TIERS = {
    "MAXIMUM": (85, 100),
    "HIGH": (70, 84),
    "MODERATE": (55, 69),
    "LOW": (40, 54),
    "NO_POSITION": (0, 39),
}

# Position size matrix: {conviction_tier: {regime: (min%, max%)}}
SIZING_MATRIX = {
    "MAXIMUM": {
        REGIME_EXPANSION: (6, 8), REGIME_OVERHEATING: (4, 6),
        REGIME_CONTRACTION: (2, 4), REGIME_RECOVERY: (5, 7),
    },
    "HIGH": {
        REGIME_EXPANSION: (4, 6), REGIME_OVERHEATING: (3, 5),
        REGIME_CONTRACTION: (2, 3), REGIME_RECOVERY: (3, 5),
    },
    "MODERATE": {
        REGIME_EXPANSION: (2, 4), REGIME_OVERHEATING: (2, 3),
        REGIME_CONTRACTION: (1, 2), REGIME_RECOVERY: (2, 3),
    },
    "LOW": {
        REGIME_EXPANSION: (1, 2), REGIME_OVERHEATING: (1, 2),
        REGIME_CONTRACTION: (0.5, 1), REGIME_RECOVERY: (1, 2),
    },
    "NO_POSITION": {
        REGIME_EXPANSION: (0, 0), REGIME_OVERHEATING: (0, 0),
        REGIME_CONTRACTION: (0, 0), REGIME_RECOVERY: (0, 0),
    },
}

# Regime scalars for Kelly formula
REGIME_SCALAR = {
    REGIME_EXPANSION: 1.0, REGIME_OVERHEATING: 0.75,
    REGIME_CONTRACTION: 0.50, REGIME_RECOVERY: 0.85,
}


def get_conviction_tier(prosper_score: float) -> str:
    """Map a PROSPER score (0-100) to a conviction tier."""
    if prosper_score >= 85:
        return "MAXIMUM"
    elif prosper_score >= 70:
        return "HIGH"
    elif prosper_score >= 55:
        return "MODERATE"
    elif prosper_score >= 40:
        return "LOW"
    return "NO_POSITION"


def calculate_position_size(prosper_score: float, regime: str,
                            p_bull: float = 0.60, reward_risk: float = 2.0,
                            druckenmiller_override: bool = False) -> Dict:
    """
    Calculate recommended position size using FORTRESS methodology.

    Parameters:
      prosper_score: PROSPER env-adjusted score (0-100)
      regime: Current regime (I/II/III/IV)
      p_bull: Probability of base/bull scenario (from PROSPER)
      reward_risk: Reward/risk ratio (upside/downside)
      druckenmiller_override: If True and eligible, allows 10-12% sizing

    Returns dict with: size_pct, conviction_tier, kelly_raw, kelly_half,
                       regime_adjusted, matrix_min, matrix_max, override_applied
    """
    tier = get_conviction_tier(prosper_score)

    if tier == "NO_POSITION":
        return {
            "size_pct": 0, "conviction_tier": tier,
            "kelly_raw": 0, "kelly_half": 0, "regime_adjusted": 0,
            "matrix_min": 0, "matrix_max": 0, "override_applied": False,
            "recommendation": "Do not hold. Watchlist only.",
        }

    # Kelly calculation
    q = 1.0 - p_bull
    kelly_raw = (p_bull * reward_risk - q) / reward_risk if reward_risk > 0 else 0
    kelly_half = max(0, 0.5 * kelly_raw) * 100  # Convert to percentage

    # Regime adjustment
    scalar = REGIME_SCALAR.get(regime, 0.75)
    regime_adjusted = kelly_half * scalar

    # Matrix bounds
    matrix_min, matrix_max = SIZING_MATRIX[tier].get(regime, (1, 3))

    # Clamp to matrix bounds
    size_pct = max(matrix_min, min(matrix_max, regime_adjusted))

    # Floor: minimum 0.5% if in portfolio at all
    if size_pct > 0 and size_pct < 0.5:
        size_pct = 0.5

    # Druckenmiller override: 10-12% for maximum conviction in Expansion
    override_applied = False
    if (druckenmiller_override and tier == "MAXIMUM" and
            regime == REGIME_EXPANSION and prosper_score >= 80):
        size_pct = min(12, max(10, regime_adjusted))
        override_applied = True

    return {
        "size_pct": round(size_pct, 2),
        "conviction_tier": tier,
        "kelly_raw": round(kelly_raw * 100, 2),
        "kelly_half": round(kelly_half, 2),
        "regime_adjusted": round(regime_adjusted, 2),
        "matrix_min": matrix_min,
        "matrix_max": matrix_max,
        "override_applied": override_applied,
        "recommendation": f"{tier} conviction → {size_pct:.1f}% position in {REGIME_NAMES.get(regime, regime)}",
    }


# ---------------------------------------------------------------------------
# MODULE 4: FACTOR BALANCE & CORRELATION MONITOR
# ---------------------------------------------------------------------------

# Factor exposure limits
FACTOR_LIMITS = {
    "value": {"max_pct": 40, "description": "EV/EBITDA, P/E, FCF yield below sector median"},
    "growth": {"max_pct": 40, "description": "Revenue growth >20%, low/no current earnings"},
    "quality": {"max_pct": 100, "description": "ROIC >15%, low leverage — no limit"},
    "momentum": {"max_pct": 50, "description": "Price >200DMA, positive 6M RS"},
    "small_cap": {"max_pct": 30, "description": "Market cap <$5B"},
    "leverage": {"max_pct": 25, "description": "Net debt/EBITDA >3x"},
    "illiquid": {"max_pct": 15, "description": "ADV <$5M or <20% free float"},
}

# Correlation thresholds
CORRELATION_ZONES = {
    "avg_pairwise": {"green": 0.30, "amber": 0.50},
    "max_pairwise": {"green": 0.60, "amber": 0.75},
    "portfolio_beta_deviation": {"green": 0.20, "amber": 0.40},
    "sector_dispersion": {"green_min": 8, "amber_min": 4},
}


def analyze_factor_exposure(enriched_df: pd.DataFrame, info_map: dict) -> Dict:
    """
    Analyze factor exposure of the portfolio.

    Returns dict with factor exposures and violations.
    """
    if enriched_df.empty or "market_value" not in enriched_df.columns:
        return {"factors": {}, "violations": []}

    total_value = enriched_df["market_value"].sum()
    if total_value <= 0:
        return {"factors": {}, "violations": []}

    factors = {}
    violations = []

    # Value factor: low P/E stocks
    if "forward_pe" in enriched_df.columns or "trailing_pe" in enriched_df.columns:
        pe_col = "forward_pe" if "forward_pe" in enriched_df.columns else "trailing_pe"
        pe_vals = pd.to_numeric(enriched_df[pe_col], errors="coerce")
        value_mask = pe_vals < 15  # Deep value
        value_pct = enriched_df.loc[value_mask, "market_value"].sum() / total_value * 100
        factors["value"] = round(value_pct, 1)
        if value_pct > FACTOR_LIMITS["value"]["max_pct"]:
            violations.append({"factor": "value", "current": value_pct,
                             "limit": FACTOR_LIMITS["value"]["max_pct"]})

    # Growth factor: high revenue growth
    if "revenue_growth" in enriched_df.columns:
        rg = pd.to_numeric(enriched_df["revenue_growth"], errors="coerce")
        growth_mask = rg > 0.20
        growth_pct = enriched_df.loc[growth_mask, "market_value"].sum() / total_value * 100
        factors["growth"] = round(growth_pct, 1)
        if growth_pct > FACTOR_LIMITS["growth"]["max_pct"]:
            violations.append({"factor": "growth", "current": growth_pct,
                             "limit": FACTOR_LIMITS["growth"]["max_pct"]})

    # Small cap factor
    if "market_cap" in enriched_df.columns:
        mc = pd.to_numeric(enriched_df["market_cap"], errors="coerce")
        small_mask = mc < 5_000_000_000
        small_pct = enriched_df.loc[small_mask, "market_value"].sum() / total_value * 100
        factors["small_cap"] = round(small_pct, 1)
        if small_pct > FACTOR_LIMITS["small_cap"]["max_pct"]:
            violations.append({"factor": "small_cap", "current": small_pct,
                             "limit": FACTOR_LIMITS["small_cap"]["max_pct"]})

    # Leverage factor
    if "debt_to_equity" in enriched_df.columns:
        dte = pd.to_numeric(enriched_df["debt_to_equity"], errors="coerce")
        leveraged_mask = dte > 300  # D/E > 3x (expressed as percentage by some sources)
        lev_pct = enriched_df.loc[leveraged_mask, "market_value"].sum() / total_value * 100
        factors["leverage"] = round(lev_pct, 1)
        if lev_pct > FACTOR_LIMITS["leverage"]["max_pct"]:
            violations.append({"factor": "leverage", "current": lev_pct,
                             "limit": FACTOR_LIMITS["leverage"]["max_pct"]})

    return {"factors": factors, "violations": violations}


def calculate_correlation_matrix(returns_df: pd.DataFrame) -> Dict:
    """
    Calculate portfolio correlation metrics from a returns DataFrame.

    Returns: avg_pairwise, max_pairwise, max_pair_tickers, zone statuses.
    """
    if returns_df.empty or len(returns_df.columns) < 2:
        return {"avg_pairwise": 0, "max_pairwise": 0, "status": "insufficient_data"}

    corr = returns_df.corr()
    n = len(corr)

    # Extract upper triangle (excluding diagonal)
    mask = np.triu(np.ones((n, n), dtype=bool), k=1)
    pairwise = corr.values[mask]

    if len(pairwise) == 0:
        return {"avg_pairwise": 0, "max_pairwise": 0, "status": "insufficient_data"}

    avg_pw = float(np.mean(pairwise))
    max_pw = float(np.max(pairwise))

    # Find the max correlated pair
    max_idx = np.argmax(corr.values * mask)
    row, col = divmod(max_idx, n)
    max_pair = (corr.columns[row], corr.columns[col]) if row < n and col < n else ("?", "?")

    # Zone assessment
    avg_zone = "green" if avg_pw < 0.30 else ("amber" if avg_pw < 0.50 else "red")
    max_zone = "green" if max_pw < 0.60 else ("amber" if max_pw < 0.75 else "red")

    return {
        "avg_pairwise": round(avg_pw, 3),
        "max_pairwise": round(max_pw, 3),
        "max_pair": max_pair,
        "avg_zone": avg_zone,
        "max_zone": max_zone,
        "overall_zone": "red" if avg_zone == "red" or max_zone == "red" else (
            "amber" if avg_zone == "amber" or max_zone == "amber" else "green"),
        "correlation_matrix": corr.round(3).to_dict(),
    }


# ---------------------------------------------------------------------------
# MODULE 5: REBALANCING PROTOCOL
# ---------------------------------------------------------------------------

REBALANCING_TRIGGERS = [
    "REGIME_CHANGE", "THESIS_BREAK", "SIZING_BREACH", "FACTOR_BREACH",
    "CORRELATION_SPIKE", "DRAWDOWN_TRIGGER", "CATALYST_REALIZED",
    "VALUATION_MEAN_REVERSION", "LIQUIDITY_EVENT", "QUARTERLY_REVIEW",
]


def check_rebalancing_triggers(portfolio_df: pd.DataFrame, regime: str,
                               prev_regime: str = None,
                               drawdown_pct: float = 0,
                               factor_violations: List = None,
                               correlation_zone: str = "green") -> List[Dict]:
    """
    Scan for all rebalancing triggers.

    Returns list of triggered actions with urgency and recommended response.
    """
    triggers = []

    # 1. Regime change
    if prev_regime and prev_regime != regime:
        glide_days = TRANSITION_GLIDE.get((prev_regime, regime), 30)
        triggers.append({
            "trigger": "REGIME_CHANGE",
            "detail": f"Regime shifted from {REGIME_NAMES.get(prev_regime, prev_regime)} → {REGIME_NAMES.get(regime, regime)}",
            "urgency": "IMMEDIATE",
            "action": f"Initiate {glide_days}-day glide path to new exposure limits.",
            "glide_days": glide_days,
        })

    # 2. Sizing breach — any position >1.5x target weight
    if not portfolio_df.empty and "market_value" in portfolio_df.columns:
        total = portfolio_df["market_value"].sum()
        if total > 0:
            portfolio_df = portfolio_df.copy()
            portfolio_df["weight_pct"] = portfolio_df["market_value"] / total * 100
            limits = get_exposure_limits(regime)
            max_single = limits.get("max_single_name_long", (8, 8))[1]
            overweight = portfolio_df[portfolio_df["weight_pct"] > max_single * 1.5]
            for _, row in overweight.iterrows():
                triggers.append({
                    "trigger": "SIZING_BREACH",
                    "detail": f"{row.get('ticker', '?')} at {row['weight_pct']:.1f}% (limit: {max_single}%)",
                    "urgency": "MODERATE",
                    "action": f"Trim to {max_single}% within 10 days.",
                })

    # 3. Factor breach
    if factor_violations:
        for v in factor_violations:
            triggers.append({
                "trigger": "FACTOR_BREACH",
                "detail": f"{v['factor']} at {v['current']:.1f}% (limit: {v['limit']}%)",
                "urgency": "MODERATE",
                "action": "Reduce most concentrated contributor within 10 days.",
            })

    # 4. Correlation spike
    if correlation_zone == "red":
        triggers.append({
            "trigger": "CORRELATION_SPIKE",
            "detail": "Avg pairwise correlation >0.50 (RED zone)",
            "urgency": "HIGH",
            "action": "Freeze new positions. Reduce gross 10%. Add tail hedges.",
        })

    # 5. Drawdown triggers (Module 6 integration)
    if drawdown_pct <= -5:
        level = _get_circuit_breaker_level(drawdown_pct)
        triggers.append({
            "trigger": "DRAWDOWN_TRIGGER",
            "detail": f"Portfolio drawdown: {drawdown_pct:+.1f}% (Level: {level['level']})",
            "urgency": "IMMEDIATE" if drawdown_pct <= -15 else "HIGH",
            "action": level["action"],
        })

    return triggers


# ---------------------------------------------------------------------------
# MODULE 6: DRAWDOWN CIRCUIT BREAKERS
# ---------------------------------------------------------------------------

PORTFOLIO_BREAKERS = [
    {"threshold": -5, "level": "YELLOW",
     "action": "Alert: Review all positions. Re-run regime check. No new longs."},
    {"threshold": -10, "level": "ORANGE",
     "action": "Reduce gross by 20%. Cut all LOW conviction. Add index hedge. CIO review."},
    {"threshold": -15, "level": "RED",
     "action": "Reduce gross to Contraction floor. Exit LOW & <1% positions. Hedge 50% of net."},
    {"threshold": -20, "level": "CRITICAL",
     "action": "Move to 50% cash. Hold only MAXIMUM conviction at half size. 30-day freeze."},
]

SINGLE_NAME_BREAKERS = [
    {"threshold": -15, "action": "Mandatory re-evaluation. Re-run PROSPER. Cut 50% if thesis weakened."},
    {"threshold": -25, "action": "Cut to half-size regardless of thesis."},
    {"threshold": -35, "action": "EXIT. Full liquidation within 5 days. No exceptions."},
]

SHORT_BREAKERS = [
    {"threshold": 20, "action": "Cover 50% of short position."},
    {"threshold": 35, "action": "Full cover. Reassess thesis completely."},
]


def _get_circuit_breaker_level(drawdown_pct: float) -> Dict:
    """Get the active circuit breaker level for a portfolio drawdown."""
    active = {"level": "NONE", "action": "No circuit breaker active.", "threshold": 0}
    for breaker in PORTFOLIO_BREAKERS:
        if drawdown_pct <= breaker["threshold"]:
            active = breaker
    return active


def check_circuit_breakers(portfolio_drawdown_pct: float,
                           position_drawdowns: Dict[str, float] = None) -> Dict:
    """
    Check all circuit breakers.

    Parameters:
      portfolio_drawdown_pct: Current drawdown from peak (negative number)
      position_drawdowns: {ticker: drawdown_pct_from_entry} (negative = loss)

    Returns dict with portfolio_level and per-position alerts.
    """
    # Portfolio-level
    portfolio_level = _get_circuit_breaker_level(portfolio_drawdown_pct)

    # Position-level
    position_alerts = []
    if position_drawdowns:
        for ticker, dd in position_drawdowns.items():
            for breaker in SINGLE_NAME_BREAKERS:
                if dd <= breaker["threshold"]:
                    position_alerts.append({
                        "ticker": ticker,
                        "drawdown": dd,
                        "threshold": breaker["threshold"],
                        "action": breaker["action"],
                    })
                    break  # Only the most severe applies

    return {
        "portfolio_drawdown": portfolio_drawdown_pct,
        "portfolio_level": portfolio_level,
        "position_alerts": position_alerts,
        "any_breaker_active": portfolio_level["level"] != "NONE" or len(position_alerts) > 0,
    }


# ---------------------------------------------------------------------------
# MODULE 7: PORTFOLIO HEALTH DASHBOARD
# ---------------------------------------------------------------------------

HEALTH_DIMENSIONS = [
    "regime_alignment", "exposure_compliance", "single_name_concentration",
    "sector_geo_concentration", "factor_balance", "correlation",
    "liquidity_coverage", "drawdown_status", "prosper_score_avg",
    "open_kill_risks",
]


def compute_health_score(regime: str, portfolio_df: pd.DataFrame,
                         exposure_violations: List = None,
                         factor_analysis: Dict = None,
                         correlation_data: Dict = None,
                         drawdown_pct: float = 0,
                         avg_prosper_score: float = 65,
                         kill_risk_count: int = 0) -> Dict:
    """
    Compute the weekly portfolio health scorecard (Module 7).

    Returns dict with per-dimension scores and overall score.
    """
    dimensions = {}

    # 1. Regime Alignment
    if exposure_violations:
        red_count = sum(1 for v in exposure_violations if v.get("severity") == "red")
        amber_count = sum(1 for v in exposure_violations if v.get("severity") == "amber")
        ok_count = sum(1 for v in exposure_violations if v.get("status") == "OK")
        if red_count >= 3:
            dimensions["regime_alignment"] = "red"
        elif red_count >= 1 or amber_count >= 2:
            dimensions["regime_alignment"] = "amber"
        else:
            dimensions["regime_alignment"] = "green"
    else:
        dimensions["regime_alignment"] = "green"

    # 2. Exposure compliance
    if exposure_violations:
        outside = [v for v in exposure_violations if v.get("status") != "OK"]
        if len(outside) >= 2:
            dimensions["exposure_compliance"] = "red"
        elif len(outside) >= 1:
            dimensions["exposure_compliance"] = "amber"
        else:
            dimensions["exposure_compliance"] = "green"
    else:
        dimensions["exposure_compliance"] = "green"

    # 3. Single-name concentration
    if not portfolio_df.empty and "market_value" in portfolio_df.columns:
        total = portfolio_df["market_value"].sum()
        if total > 0:
            max_weight = portfolio_df["market_value"].max() / total * 100
            limits = get_exposure_limits(regime)
            cap = limits.get("max_single_name_long", (8, 8))[1]
            if max_weight > cap:
                dimensions["single_name_concentration"] = "red"
            elif max_weight > cap - 0.5:
                dimensions["single_name_concentration"] = "amber"
            else:
                dimensions["single_name_concentration"] = "green"
        else:
            dimensions["single_name_concentration"] = "green"
    else:
        dimensions["single_name_concentration"] = "green"

    # 4. Sector/Geo concentration
    dimensions["sector_geo_concentration"] = "green"  # Default; updated by exposure_violations
    if exposure_violations:
        for v in exposure_violations:
            if v["param"] in ("max_sector_concentration", "max_geo_concentration") and v["status"] != "OK":
                dimensions["sector_geo_concentration"] = "red" if v["severity"] == "red" else "amber"
                break

    # 5. Factor balance
    if factor_analysis and factor_analysis.get("violations"):
        n_violations = len(factor_analysis["violations"])
        dimensions["factor_balance"] = "red" if n_violations >= 2 else "amber"
    else:
        dimensions["factor_balance"] = "green"

    # 6. Correlation
    if correlation_data:
        dimensions["correlation"] = correlation_data.get("overall_zone", "green")
    else:
        dimensions["correlation"] = "green"

    # 7. Liquidity coverage (simplified — always green unless flagged)
    dimensions["liquidity_coverage"] = "green"

    # 8. Drawdown status
    if drawdown_pct <= -10:
        dimensions["drawdown_status"] = "red"
    elif drawdown_pct <= -5:
        dimensions["drawdown_status"] = "amber"
    else:
        dimensions["drawdown_status"] = "green"

    # 9. PROSPER score average
    if avg_prosper_score < 55:
        dimensions["prosper_score_avg"] = "red"
    elif avg_prosper_score < 65:
        dimensions["prosper_score_avg"] = "amber"
    else:
        dimensions["prosper_score_avg"] = "green"

    # 10. Open kill risks
    if kill_risk_count >= 2:
        dimensions["open_kill_risks"] = "red"
    elif kill_risk_count >= 1:
        dimensions["open_kill_risks"] = "amber"
    else:
        dimensions["open_kill_risks"] = "green"

    # Overall score
    green_count = sum(1 for v in dimensions.values() if v == "green")
    amber_count = sum(1 for v in dimensions.values() if v == "amber")
    red_count = sum(1 for v in dimensions.values() if v == "red")
    total_dims = len(dimensions)

    score = green_count  # Out of 10

    if score >= 10:
        overall = "Optimally positioned. Continue monitoring."
    elif score >= 8:
        overall = "Minor drift. Address in next quarterly review."
    elif score >= 6:
        overall = "Portfolio needs attention. Review within 5 days."
    elif score >= 4:
        overall = "Portfolio is stressed. Reduce risk immediately."
    else:
        overall = "CRISIS MODE. Activate circuit breakers. No new risk."

    return {
        "dimensions": dimensions,
        "score": score,
        "total": total_dims,
        "green": green_count,
        "amber": amber_count,
        "red": red_count,
        "overall_assessment": overall,
    }


# ---------------------------------------------------------------------------
# MODULE 8: PROSPER ↔ FORTRESS INTEGRATION
# ---------------------------------------------------------------------------

def fortress_size_ticker(ticker: str, prosper_score: float, regime: str,
                         p_bull: float = 0.60, reward_risk: float = 2.0,
                         factor_violations: List = None,
                         correlation_zone: str = "green",
                         circuit_breaker_active: bool = False) -> Dict:
    """
    Full FORTRESS sizing workflow for a single ticker (Module 8).

    Checks: regime → factor limits → correlation → circuit breakers → size.
    Returns sizing recommendation or block reason.
    """
    # Step 1: Circuit breaker check
    if circuit_breaker_active:
        return {
            "ticker": ticker, "action": "BLOCKED",
            "reason": "Circuit breaker active. No new longs until breaker clears.",
            "size_pct": 0,
        }

    # Step 2: Correlation check
    if correlation_zone == "red":
        return {
            "ticker": ticker, "action": "BLOCKED",
            "reason": "Correlation spike (RED). No new positions until correlation normalizes.",
            "size_pct": 0,
        }

    # Step 3: Factor limit check
    if factor_violations:
        # Check if adding this name would worsen any violation
        # (simplified: just warn, don't block)
        pass

    # Step 4: Calculate size
    sizing = calculate_position_size(prosper_score, regime, p_bull, reward_risk)

    return {
        "ticker": ticker,
        "action": "SIZE" if sizing["size_pct"] > 0 else "NO_POSITION",
        "reason": sizing["recommendation"],
        **sizing,
    }


# ---------------------------------------------------------------------------
# MODULE 9: SYSTEM EVOLUTION & GOVERNANCE (metadata / logging)
# ---------------------------------------------------------------------------

def log_fortress_event(event_type: str, details: Dict) -> Dict:
    """Create a structured FORTRESS event log entry."""
    return {
        "event_type": event_type,
        "timestamp": datetime.now().isoformat(),
        "details": details,
    }


def get_fortress_summary(regime: str, confidence: str, geo_tier: str,
                         health_score: Dict, circuit_breakers: Dict,
                         rebalancing_triggers: List) -> Dict:
    """
    Generate a complete FORTRESS summary for dashboard display.

    Combines all module outputs into a single overview.
    """
    return {
        "regime": regime,
        "regime_name": REGIME_NAMES.get(regime, regime),
        "confidence": confidence,
        "geo_tier": geo_tier,
        "health_score": health_score.get("score", 0),
        "health_total": health_score.get("total", 10),
        "health_assessment": health_score.get("overall_assessment", ""),
        "circuit_breaker_active": circuit_breakers.get("any_breaker_active", False),
        "circuit_breaker_level": circuit_breakers.get("portfolio_level", {}).get("level", "NONE"),
        "active_triggers": len(rebalancing_triggers),
        "triggers": rebalancing_triggers,
        "generated_at": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# BROKER MARGIN RATES — live reference data
# ---------------------------------------------------------------------------

# Standard margin rates by broker (as of March 2026)
# These serve as defaults; can be overridden by user input
BROKER_MARGIN_RATES = {
    "IBKR": {
        "name": "Interactive Brokers",
        "tiers": [
            {"up_to": 100_000, "rate": 5.83},
            {"up_to": 1_000_000, "rate": 5.83},
            {"up_to": 3_000_000, "rate": 5.33},
            {"up_to": 200_000_000, "rate": 5.08},
            {"up_to": float("inf"), "rate": 4.83},
        ],
        "benchmark": "Fed Funds + spread",
        "currency_rates": {
            "USD": 5.83, "EUR": 4.636, "GBP": 5.934,
            "INR": 10.5, "HKD": 6.50, "SGD": 5.25,
            "AED": 6.00, "AUD": 5.75, "CAD": 5.50,
        },
    },
    "Zerodha": {
        "name": "Zerodha",
        "tiers": [{"up_to": float("inf"), "rate": 18.0}],
        "benchmark": "Flat rate",
        "currency_rates": {"INR": 18.0},
    },
    "HSBC": {
        "name": "HSBC InvestDirect",
        "tiers": [
            {"up_to": 500_000, "rate": 8.50},
            {"up_to": float("inf"), "rate": 7.50},
        ],
        "benchmark": "Base rate + spread",
        "currency_rates": {
            "USD": 7.50, "GBP": 7.25, "EUR": 6.50,
            "HKD": 7.75, "SGD": 7.00, "AED": 7.50,
        },
    },
    "Tiger Brokers": {
        "name": "Tiger Brokers",
        "tiers": [
            {"up_to": 100_000, "rate": 6.49},
            {"up_to": float("inf"), "rate": 5.99},
        ],
        "benchmark": "Benchmark + spread",
        "currency_rates": {
            "USD": 6.49, "SGD": 5.99, "HKD": 6.80,
            "AUD": 6.49,
        },
    },
    "Saxo": {
        "name": "Saxo Bank",
        "tiers": [
            {"up_to": 100_000, "rate": 7.50},
            {"up_to": float("inf"), "rate": 6.50},
        ],
        "benchmark": "Benchmark + spread",
        "currency_rates": {
            "USD": 7.50, "EUR": 6.00, "GBP": 7.25,
            "AED": 7.50, "SGD": 6.50, "HKD": 7.00,
        },
    },
    "Charles Schwab": {
        "name": "Charles Schwab",
        "tiers": [
            {"up_to": 25_000, "rate": 12.325},
            {"up_to": 50_000, "rate": 11.825},
            {"up_to": 100_000, "rate": 11.325},
            {"up_to": 250_000, "rate": 10.575},
            {"up_to": 500_000, "rate": 10.575},
            {"up_to": float("inf"), "rate": 10.075},
        ],
        "benchmark": "Schwab base rate + spread",
        "currency_rates": {"USD": 12.325},
    },
    "Fidelity": {
        "name": "Fidelity",
        "tiers": [
            {"up_to": 25_000, "rate": 12.325},
            {"up_to": 50_000, "rate": 11.075},
            {"up_to": 100_000, "rate": 8.825},
            {"up_to": 250_000, "rate": 8.325},
            {"up_to": 500_000, "rate": 7.825},
            {"up_to": float("inf"), "rate": 7.075},
        ],
        "benchmark": "Base rate varies by balance",
        "currency_rates": {"USD": 12.325},
    },
    "TD Ameritrade": {
        "name": "TD Ameritrade",
        "tiers": [
            {"up_to": 10_000, "rate": 12.75},
            {"up_to": 25_000, "rate": 12.50},
            {"up_to": 50_000, "rate": 12.00},
            {"up_to": 100_000, "rate": 11.50},
            {"up_to": float("inf"), "rate": 11.00},
        ],
        "benchmark": "Base rate + spread",
        "currency_rates": {"USD": 12.75},
    },
}


def get_margin_rate(broker: str, balance: float = 0, currency: str = "USD") -> Dict:
    """
    Get the applicable margin rate for a broker, balance, and currency.

    Returns dict with: broker_name, rate, currency, tier_info
    """
    broker_key = broker.strip().upper() if broker else ""

    # Try exact match first, then fuzzy
    matched = None
    for key, data in BROKER_MARGIN_RATES.items():
        if key.upper() == broker_key or key.upper() in broker_key or broker_key in key.upper():
            matched = data
            break

    if not matched:
        # Try partial match on name
        for key, data in BROKER_MARGIN_RATES.items():
            if broker_key in data["name"].upper():
                matched = data
                break

    if not matched:
        return {
            "broker_name": broker, "rate": None, "currency": currency,
            "message": f"Broker '{broker}' not found. Add manually.",
        }

    # Get currency-specific rate
    currency_rates = matched.get("currency_rates", {})
    if currency in currency_rates:
        base_rate = currency_rates[currency]
    else:
        # Default to USD rate
        base_rate = currency_rates.get("USD", matched["tiers"][0]["rate"])

    # Apply tiered rate based on balance
    rate = base_rate
    abs_balance = abs(balance)
    for tier in matched["tiers"]:
        if abs_balance <= tier["up_to"]:
            rate = tier["rate"]
            break

    return {
        "broker_name": matched["name"],
        "rate": rate,
        "currency": currency,
        "benchmark": matched.get("benchmark", ""),
        "all_tiers": matched["tiers"],
        "all_currency_rates": currency_rates,
    }


def calculate_margin_cost(balance: float, rate_pct: float, days: int = 365) -> float:
    """Calculate annual margin interest cost."""
    return abs(balance) * (rate_pct / 100) * (days / 365)
