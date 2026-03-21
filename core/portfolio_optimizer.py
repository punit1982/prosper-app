"""
Portfolio Optimizer Engine for Prosper
======================================
Two modes:
  1. Rule-Based Allocation – compare current portfolio against model portfolios
     and suggest rebalancing trades.
  2. Modern Portfolio Theory (MPT) – compute the efficient frontier and find the
     maximum-Sharpe-ratio portfolio using historical returns.
"""

import pandas as pd
import numpy as np
from core.data_engine import get_history, get_ticker_info_batch

# ---------------------------------------------------------------------------
# Try importing scipy (optional – only needed for MPT mode)
# ---------------------------------------------------------------------------
try:
    from scipy.optimize import minimize

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# ---------------------------------------------------------------------------
# Model Portfolios (target allocations by asset class)
# ---------------------------------------------------------------------------
MODEL_PORTFOLIOS = {
    "Ray Dalio All-Weather": {
        "Equity": 0.30,
        "Fixed Income": 0.55,
        "Gold/Commodities": 0.15,
    },
    "60/40 Classic": {
        "Equity": 0.60,
        "Fixed Income": 0.40,
    },
    "Endowment (Yale Model)": {
        "Equity": 0.35,
        "Fixed Income": 0.15,
        "Real Estate": 0.20,
        "Gold/Commodities": 0.15,
        "Cash": 0.15,
    },
    "Balanced Growth": {
        "Equity": 0.55,
        "Fixed Income": 0.25,
        "Real Estate": 0.10,
        "Gold/Commodities": 0.05,
        "Cash": 0.05,
    },
    "Growth": {
        "Equity": 0.75,
        "Fixed Income": 0.15,
        "Real Estate": 0.05,
        "Cash": 0.05,
    },
    "Aggressive Growth": {
        "Equity": 0.90,
        "Fixed Income": 0.05,
        "Cash": 0.05,
    },
    "Conservative Income": {
        "Equity": 0.25,
        "Fixed Income": 0.45,
        "Gold/Commodities": 0.15,
        "Real Estate": 0.05,
        "Cash": 0.10,
    },
}

MODEL_DESCRIPTIONS = {
    "Ray Dalio All-Weather": "Designed to perform in any economic environment — inflation, deflation, growth, or recession. Heavy on bonds with gold as a hedge. Best for: capital preservation with steady returns.",
    "60/40 Classic": "The traditional institutional benchmark. 60% stocks for growth, 40% bonds for stability. Best for: moderate risk tolerance, retirement portfolios.",
    "Endowment (Yale Model)": "Inspired by David Swensen's Yale endowment strategy. Diversified across asset classes including alternatives. Best for: long-term investors who can tolerate illiquidity.",
    "Balanced Growth": "A middle ground — tilted toward equities but with meaningful diversification across bonds, real estate, and commodities. Best for: 5-10 year time horizons.",
    "Growth": "Equity-focused with minimal fixed income. Accepts higher volatility for higher expected returns. Best for: investors with 10+ year horizons.",
    "Aggressive Growth": "Near-maximum equity exposure. High volatility but highest expected long-term returns. Best for: young investors, long time horizons, high risk tolerance.",
    "Conservative Income": "Prioritizes income and capital preservation. Heavy on bonds and gold, light on equities. Best for: retirees, near-term spending needs, low risk tolerance.",
}

# ---------------------------------------------------------------------------
# Helpers – classifying holdings
# ---------------------------------------------------------------------------

# Cash Proxy Detection — money market funds, T-bill ETFs, ultra-short bond ETFs
_CASH_PROXIES = {
    # US Money Market Funds
    "VMFXX", "SPAXX", "FDRXX", "SPRXX", "SNAXX", "SWVXX", "TTTXX",
    # Ultra-Short Duration / T-Bill ETFs
    "BIL", "SHV", "SGOV", "USFR", "JPST", "MINT", "NEAR", "ICSH",
    "FLOT", "CSHI", "TBIL", "CLIP", "BOXX",
    # Ultra-Short Bond ETFs (near-cash)
    "VUSB", "GSY", "PULS",
}

_BOND_ETFS = {
    "BND", "AGG", "TLT", "IEF", "SHY", "LQD", "HYG", "BNDX", "VCIT",
    "VCSH", "VGSH", "VGIT", "VGLT", "TIP", "GOVT", "MUB", "SUB",
}
_GOLD_COMMODITY = {
    "GLD", "IAU", "SLV", "PDBC", "DJP", "GSG", "GLDM", "SGOL", "DBC",
    "COMT", "FTGC",
}
_REIT_ETFS = {
    "VNQ", "VNQI", "IYR", "SCHH", "RWR", "XLRE", "REET", "USRT", "SRVR",
}

_SECTOR_MAP = {
    "Technology": "Technology",
    "Healthcare": "Healthcare",
    "Financial Services": "Financials",
    "Financials": "Financials",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Communication Services": "Communication",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Basic Materials": "Materials",
}


def is_cash_proxy(ticker: str, info: dict = None) -> bool:
    """Check if a ticker is a cash or money-market proxy."""
    t = ticker.upper()
    if t in _CASH_PROXIES:
        return True
    # Heuristic: check fund name for money-market / treasury-bill keywords
    if info:
        name = (info.get("shortName") or info.get("longName") or "").lower()
        mm_keywords = ("money market", "treasury bill", "t-bill", "government mmf",
                       "cash reserve", "liquid reserve", "overnight")
        if any(kw in name for kw in mm_keywords):
            return True
    return False


def _classify_asset_class(ticker: str, info: dict) -> str:
    """Return one of: Equity, Fixed Income, Gold/Commodities, Real Estate, Cash."""
    t = ticker.upper()
    # Cash proxies first
    if is_cash_proxy(t, info):
        return "Cash"
    if t in _BOND_ETFS:
        return "Fixed Income"
    if t in _GOLD_COMMODITY:
        return "Gold/Commodities"
    if t in _REIT_ETFS:
        return "Real Estate"
    qt = (info.get("quoteType") or "").upper()
    if qt == "MUTUALFUND":
        name = (info.get("shortName") or "").lower()
        if "bond" in name or "fixed" in name or "income" in name:
            return "Fixed Income"
        if "gold" in name or "commodity" in name:
            return "Gold/Commodities"
        if "real estate" in name or "reit" in name:
            return "Real Estate"
        # Money market mutual funds
        if "money market" in name or "liquid" in name:
            return "Cash"
    sector = info.get("sector") or ""
    if sector == "Real Estate":
        return "Real Estate"
    return "Equity"


def _normalise_sector(info: dict) -> str:
    raw = info.get("sector") or ""
    if raw and raw != "None":
        return _SECTOR_MAP.get(raw, raw)
    # Fallback: try to classify from company/fund name
    name = (info.get("shortName") or info.get("longName") or "").lower()
    qt = (info.get("quoteType") or "").upper()
    if qt in ("ETF", "MUTUALFUND"):
        cat = (info.get("category") or "").lower()
        for label, keywords in [
            ("Technology", ("tech", "semiconductor", "software")),
            ("Healthcare", ("health", "biotech", "pharma")),
            ("Financials", ("financ", "bank")),
            ("Energy", ("energy", "oil")),
            ("Real Estate", ("real estate", "reit")),
            ("Fixed Income", ("bond", "income", "fixed", "treasury", "credit")),
        ]:
            if any(k in cat or k in name for k in keywords):
                return label
        return "Funds & ETFs"
    if name:
        for label, keywords in [
            ("Financials", ("bank", "finance", "insurance", "capital")),
            ("Technology", ("tech", "software", "digital", "semiconductor")),
            ("Energy", ("energy", "oil", "gas", "petrol", "drilling")),
            ("Healthcare", ("health", "pharma", "biotech", "hospital")),
            ("Communication", ("telecom", "communication", "media")),
            ("Real Estate", ("real estate", "reit", "property")),
            ("Industrials", ("industrial", "aerospace", "defense", "construction")),
            ("Materials", ("mining", "chemical", "steel", "cement")),
        ]:
            if any(k in name for k in keywords):
                return label
    return "Unknown"


def _get_country(info: dict) -> str:
    return info.get("country") or "Unknown"


def _get_market_cap_label(info: dict) -> str:
    mc = info.get("marketCap")
    if mc is None:
        return "Unknown"
    if mc >= 200_000_000_000:
        return "Mega Cap"
    if mc >= 10_000_000_000:
        return "Large Cap"
    if mc >= 2_000_000_000:
        return "Mid Cap"
    if mc >= 300_000_000:
        return "Small Cap"
    return "Micro Cap"


# ===================================================================
# MODE 1 – Rule-Based Allocation
# ===================================================================

def analyze_current_allocation(enriched_df: pd.DataFrame, info_map: dict) -> dict:
    """
    Return current allocation breakdowns.

    Parameters
    ----------
    enriched_df : DataFrame with at least columns ``ticker`` and ``market_value``
        (market_value = quantity * current price in base currency).
    info_map : dict  ticker -> info dict (from get_ticker_info_batch).

    Returns
    -------
    dict with keys: asset_class, sector, geography, cap_size.
    Each value is a dict of {category: fraction}.
    """
    df = enriched_df.copy()
    total_value = df["market_value"].sum()
    if total_value == 0:
        return {
            "asset_class": {},
            "sector": {},
            "geography": {},
            "cap_size": {},
        }

    df["asset_class"] = df["ticker"].apply(
        lambda t: _classify_asset_class(t, info_map.get(t, {}))
    )
    df["sector"] = df["ticker"].apply(
        lambda t: _normalise_sector(info_map.get(t, {}))
    )
    df["geography"] = df["ticker"].apply(
        lambda t: _get_country(info_map.get(t, {}))
    )
    df["cap_size"] = df["ticker"].apply(
        lambda t: _get_market_cap_label(info_map.get(t, {}))
    )

    result = {}
    for dim in ("asset_class", "sector", "geography", "cap_size"):
        grouped = df.groupby(dim)["market_value"].sum()
        result[dim] = (grouped / total_value).to_dict()

    return result


def concentration_risk_check(enriched_df: pd.DataFrame) -> list[dict]:
    """
    Check for concentration risks.

    Parameters
    ----------
    enriched_df : DataFrame with ``ticker``, ``market_value``, ``sector``, ``country``.

    Returns
    -------
    List of warning dicts: {type, detail, value, threshold}.
    """
    warnings = []
    df = enriched_df.copy()
    total = df["market_value"].sum()
    if total == 0:
        return warnings

    # --- Single stock > 10% ---
    df["weight"] = df["market_value"] / total
    for _, row in df.iterrows():
        if row["weight"] > 0.10:
            warnings.append({
                "type": "Single Stock",
                "detail": f"{row['ticker']} is {row['weight']:.1%} of portfolio",
                "value": round(row["weight"] * 100, 1),
                "threshold": 10,
            })

    # --- Single sector > 30% ---
    if "sector" in df.columns:
        sector_weights = df.groupby("sector")["market_value"].sum() / total
        for sec, w in sector_weights.items():
            if w > 0.30:
                warnings.append({
                    "type": "Sector Concentration",
                    "detail": f"{sec} is {w:.1%} of portfolio",
                    "value": round(w * 100, 1),
                    "threshold": 30,
                })

    # --- Single country > 50% ---
    if "country" in df.columns:
        geo_weights = df.groupby("country")["market_value"].sum() / total
        for geo, w in geo_weights.items():
            if w > 0.50:
                warnings.append({
                    "type": "Country Concentration",
                    "detail": f"{geo} is {w:.1%} of portfolio",
                    "value": round(w * 100, 1),
                    "threshold": 50,
                })

    # --- Top 5 holdings > 50% ---
    top5 = df.nlargest(5, "market_value")["market_value"].sum()
    top5_pct = top5 / total
    if top5_pct > 0.50:
        warnings.append({
            "type": "Top-5 Concentration",
            "detail": f"Top 5 holdings are {top5_pct:.1%} of portfolio",
            "value": round(top5_pct * 100, 1),
            "threshold": 50,
        })

    return warnings


def suggest_rebalance(current_alloc: dict, target_model: str) -> list[dict]:
    """
    Compare current asset-class allocation against a model portfolio and
    return suggested adjustments.

    Parameters
    ----------
    current_alloc : dict  – the ``asset_class`` sub-dict from
        ``analyze_current_allocation``.
    target_model : str – key into ``MODEL_PORTFOLIOS``.

    Returns
    -------
    List of dicts: {category, current_pct, target_pct, diff_pct, action}.
    """
    targets = MODEL_PORTFOLIOS.get(target_model, {})
    all_cats = sorted(set(list(current_alloc.keys()) + list(targets.keys())))

    rows = []
    for cat in all_cats:
        cur = current_alloc.get(cat, 0.0)
        tgt = targets.get(cat, 0.0)
        diff = cur - tgt
        if abs(diff) < 0.005:
            action = "At Target"
        elif diff > 0:
            action = "Overweight"
        else:
            action = "Underweight"
        rows.append({
            "category": cat,
            "current_pct": round(cur * 100, 1),
            "target_pct": round(tgt * 100, 1),
            "diff_pct": round(diff * 100, 1),
            "action": action,
        })

    return rows


# ===================================================================
# MODE 2 – Modern Portfolio Theory
# ===================================================================

_RISK_FREE_RATE = 0.05  # 5% annualised (US T-bills)


def _fetch_returns(tickers: list[str], period: str = "1y") -> tuple[pd.DataFrame, list[str]]:
    """Fetch daily close prices via get_history and compute daily returns.

    Returns
    -------
    (returns_df, failed_tickers) – the daily returns DataFrame and a list
    of tickers for which history could not be fetched.
    """
    frames = {}
    failed = []
    for t in tickers:
        if t in frames:
            continue  # skip duplicates already fetched
        hist = get_history(t, period=period)
        if hist is not None and not hist.empty:
            close = hist["Close"] if "Close" in hist.columns else hist.iloc[:, 0]
            frames[t] = close
        else:
            failed.append(t)
    if not frames:
        return pd.DataFrame(), failed
    prices = pd.DataFrame(frames).dropna()
    if prices.empty:
        return pd.DataFrame(), failed
    return prices.pct_change().dropna(), failed


def _portfolio_stats(weights: np.ndarray, mean_ret: np.ndarray, cov: np.ndarray):
    """Return (annual_return, annual_vol, sharpe)."""
    port_ret = np.dot(weights, mean_ret) * 252
    port_vol = np.sqrt(np.dot(weights, np.dot(cov * 252, weights)))
    sharpe = (port_ret - _RISK_FREE_RATE) / port_vol if port_vol > 0 else 0
    return port_ret, port_vol, sharpe


def _deduplicate_tickers_weights(
    tickers: list[str], weights: list[float]
) -> tuple[list[str], list[float]]:
    """Merge duplicate tickers by summing their weights."""
    combined: dict[str, float] = {}
    for t, w in zip(tickers, weights):
        combined[t] = combined.get(t, 0.0) + w
    dedup_tickers = list(combined.keys())
    dedup_weights = [combined[t] for t in dedup_tickers]
    return dedup_tickers, dedup_weights


def get_efficient_frontier(
    tickers: list[str],
    weights: list[float],
    period: str = "1y",
    n_points: int = 50,
) -> dict:
    """
    Generate efficient frontier data points.

    Parameters
    ----------
    tickers : list of ticker strings present in the portfolio.
    weights : current portfolio weights (same order as tickers).
    period : look-back period for historical returns.
    n_points : number of points on the frontier.

    Returns
    -------
    dict with keys:
      - ``points``: list of dicts with risk, return_, sharpe, weights, is_current.
      - ``failed_tickers``: list of tickers that could not be fetched.
      - ``error``: str or None describing why the frontier is empty.
    """
    result = {"points": [], "failed_tickers": [], "error": None}

    if not HAS_SCIPY:
        result["error"] = (
            "scipy is required for MPT calculations. "
            "Install it with: pip install scipy"
        )
        return result

    # De-duplicate tickers (merge weights for the same ticker)
    tickers, weights = _deduplicate_tickers_weights(tickers, weights)

    if len(tickers) < 2:
        result["error"] = f"Need at least 2 unique tickers, but got {len(tickers)}."
        return result

    returns_df, failed = _fetch_returns(tickers, period)
    result["failed_tickers"] = failed

    if returns_df.empty:
        result["error"] = (
            f"Could not fetch historical prices for any ticker. "
            f"Failed tickers: {', '.join(failed) if failed else 'all'}."
        )
        return result

    # Align tickers to what we actually fetched
    available = [t for t in tickers if t in returns_df.columns]
    if len(available) < 2:
        result["error"] = (
            f"Only {len(available)} ticker(s) returned price data "
            f"(need at least 2). Failed: {', '.join(failed)}."
        )
        return result
    returns_df = returns_df[available]

    mean_ret = returns_df.mean().values
    cov = returns_df.cov().values
    n = len(available)

    # Current portfolio (re-normalise weights for available tickers)
    idx_map = {t: i for i, t in enumerate(tickers)}
    cur_w = np.array([weights[idx_map[t]] for t in available])
    cur_w = cur_w / cur_w.sum() if cur_w.sum() > 0 else np.ones(n) / n
    cur_ret, cur_vol, cur_sharpe = _portfolio_stats(cur_w, mean_ret, cov)

    points = []

    # Add current portfolio marker
    points.append({
        "risk": round(cur_vol, 4),
        "return_": round(cur_ret, 4),
        "sharpe": round(cur_sharpe, 4),
        "weights": {t: round(w, 4) for t, w in zip(available, cur_w)},
        "is_current": True,
    })

    # Random portfolios to sketch the frontier
    np.random.seed(42)
    for _ in range(n_points):
        w = np.random.dirichlet(np.ones(n))
        r, v, s = _portfolio_stats(w, mean_ret, cov)
        points.append({
            "risk": round(v, 4),
            "return_": round(r, 4),
            "sharpe": round(s, 4),
            "weights": {t: round(ww, 4) for t, ww in zip(available, w)},
            "is_current": False,
        })

    result["points"] = points
    return result


def get_optimal_portfolio(
    tickers: list[str],
    weights: list[float],
    period: str = "1y",
) -> dict:
    """
    Find the maximum-Sharpe-ratio portfolio.

    Returns
    -------
    dict with keys: weights (dict ticker->weight), return_, risk, sharpe.
    Empty dict on failure.
    """
    if not HAS_SCIPY:
        return {}

    # De-duplicate tickers
    tickers, weights = _deduplicate_tickers_weights(tickers, weights)

    if len(tickers) < 2:
        return {}

    returns_df, _failed = _fetch_returns(tickers, period)
    if returns_df.empty or len(returns_df.columns) < 2:
        return {}

    available = [t for t in tickers if t in returns_df.columns]
    if len(available) < 2:
        return {}
    returns_df = returns_df[available]

    mean_ret = returns_df.mean().values
    cov = returns_df.cov().values
    n = len(available)

    def neg_sharpe(w):
        r, v, s = _portfolio_stats(w, mean_ret, cov)
        return -s

    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
    bounds = [(0.0, 1.0)] * n
    x0 = np.ones(n) / n

    opt_result = minimize(
        neg_sharpe,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )

    if not opt_result.success:
        return {}

    opt_w = opt_result.x
    opt_ret, opt_vol, opt_sharpe = _portfolio_stats(opt_w, mean_ret, cov)

    return {
        "weights": {t: round(w, 4) for t, w in zip(available, opt_w)},
        "return_": round(opt_ret, 4),
        "risk": round(opt_vol, 4),
        "sharpe": round(opt_sharpe, 4),
    }
