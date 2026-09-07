#!/usr/bin/env python3
"""
GROW — batch runner
===================
Runs the GROW engine over many tickers in one process and writes each result to
prosper_analysis, so the Options Desk's Rule 1 has verdicts to work with and the
Dashboard shows a Durability score per holding.

WHY THIS EXISTS — the cost is not what it looks like
----------------------------------------------------
The fear is "hundreds of dollars of Claude tokens". Measured, that is only true of the
`full` tier used indiscriminately:

    tier       model      searches  content   per name   50 names   182 holdings
    screen     Sonnet 5      0          -      $0.073*      $4          $13
    standard   Sonnet 5     12        40k      ~$1.20      $60         $219
    full_lean  Sonnet 5     25        18k      ~$1.36      $68         $248
    full       Opus 5       25        40k      ~$5.78     $289       $1,052

    * measured on a real NKE run, not estimated.

The framework is 36,053 tokens and, cached, costs $0.018 a call — it is NOT the cost
driver. web_fetch is: 25 fetches x 40,000 tokens of page content is ~1M input tokens per
name. full_lean keeps all 25 sources (breadth of evidence is the point of the full tier)
and trims the boilerplate pulled from each, which is where the 76% saving comes from.

Batching matters because prompt caching only pays off while the cache is warm, which
needs the calls close together in one process rather than clicked one at a time in the UI.

RECOMMENDED USE
---------------
    # every name the Options Desk needs a Rule 1 verdict for — a couple of dollars
    python3 scripts/grow_batch.py --universe --tier screen

    # depth where it changes a decision — full retrieval breadth, a quarter of the price
    python3 scripts/grow_batch.py --holdings --top 20 --tier full_lean

Screen tier produces the Durability score and the full price ladder (buy_below,
fair_high) — everything Rule 1 needs. It does no filings retrieval, so it is marked
provisional by the engine itself and should not be mistaken for a researched memo.
"""

import argparse
import re
import logging
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_log = logging.getLogger("grow.batch")


def _resolve_targets(args) -> list:
    names = []
    if args.tickers:
        names += [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.universe:
        from harvest import universe as agu
        names += agu.universe_tickers(include_hedge=False)
    if args.holdings:
        try:
            from core.database import get_all_holdings
            import pandas as _pd
            df = get_all_holdings()
            if df is not None and not df.empty:
                df = df.copy()
                # Rank by POSITION VALUE, not share count.
                #
                # The first version sorted on `quantity`, so "--top 20" returned the twenty
                # largest *share counts* — which on this book means the cheapest stocks:
                # TALABAT.AE, AKT, DHLU.SI, CAN, SPACE42.AE, penny lines and UAE listings.
                # Precisely the opposite of "the positions worth spending $1.40 a name on".
                qty = _pd.to_numeric(df.get("quantity"), errors="coerce").fillna(0)
                px = _pd.to_numeric(df.get("last_known_price"), errors="coerce")
                px = px.fillna(_pd.to_numeric(df.get("avg_cost"), errors="coerce")).fillna(0)
                df["value_usd"] = qty.abs() * px
                # FX: values are in the listing currency, so a JPY line would otherwise dwarf a
                # USD one by ~150x. Normalise the majors well enough to rank on.
                _fx = {"USD": 1.0, "AED": 0.2723, "SAR": 0.2666, "EUR": 1.09, "GBP": 1.27,
                       "GBp": 0.0127, "CHF": 1.12, "SGD": 0.775, "JPY": 0.0067,
                       "INR": 0.0119, "HKD": 0.1282, "CAD": 0.73}
                cur = df.get("currency").astype(str) if "currency" in df.columns else "USD"
                df["value_usd"] = df["value_usd"] * cur.map(lambda c: _fx.get(c, 1.0))
                df = df.sort_values("value_usd", ascending=False)
                if not args.include_funds:
                    _before = len(df)
                    _mask = [not _looks_like_fund(r.ticker, getattr(r, "name", ""))
                             for r in df.itertuples()]
                    _dropped = df[[not m for m in _mask]]["ticker"].tolist()
                    df = df[_mask]
                    if _dropped:
                        _log.info("skipping %d fund/ETF/bond line(s) — GROW scores businesses, "
                                  "not wrappers (--include-funds to override): %s",
                                  len(_dropped), ", ".join(_dropped[:12]))
                if args.top:
                    _log.info("largest positions by value: %s",
                              ", ".join(f"{r.ticker} (${r.value_usd:,.0f})"
                                        for r in df.head(min(args.top, 8)).itertuples()))
                names += [str(t).upper() for t in df["ticker"].tolist()]
        except Exception as e:
            _log.warning("could not read holdings: %s", e)
    seen, out = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n); out.append(n)
    return out[:args.top] if args.top else out


# GROW scores the durability of a BUSINESS — market pull, moat, margin room, operator
# credibility. None of that is meaningful for a Treasury ETF, a covered-call income fund or a
# closed-end bond fund, and at full_lean prices each one is $1.40 spent to produce a memo about
# a wrapper rather than a company. holdings.asset_category is NULL for all 116 rows here, so the
# instrument name is the only signal available.
# Whole words only. A naive substring match dropped NETFLIX, because "n-ETF-lix" contains "etf".
_FUND_WORDS = (
    "etf", "etfs", "fund", "funds", "fd", "index", "ishares", "vanguard", "spdr", "invesco",
    "ucits", "trust", "pimco", "franklin", "wisdomtree", "amundi", "lyxor", "schwab",
    "buywrite", "dividend", "aggregate", "treasury", "govt", "allianz",
)
# Multi-word markers that are unambiguous even inside a longer name.
_FUND_PHRASES = (
    "global x", "gx nasdaq", "covered c", "cov c", "income fu", "dynamic inco",
    "eq pr in", "jpm usd", "glb hy", "msci", "treasury bond", "bond etf",
)
# ISIN-shaped identifiers used as tickers: two country letters then 9-10 alphanumerics
# (LU1255915586), or a leading letter followed by all digits (I288654906).
_ISIN_LIKE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9,10}$|^[A-Z]\d{6,}$")


def _looks_like_fund(ticker: str, name: str) -> bool:
    t = (ticker or "").strip().upper()
    if t.startswith(("MF:", "RESTRICTED:")):
        return True
    if _ISIN_LIKE.match(t):
        return True
    n = (name or "").lower()
    if any(ph in n for ph in _FUND_PHRASES):
        return True
    words = set(re.findall(r"[a-z]+", n))
    return bool(words & set(_FUND_WORDS))


def _snapshot_inputs(ticker: str):
    """(info, price_quote) for the Tier-5 snapshot.

    Price comes through cio_engine's cascade, which reaches the keyless Yahoo `chart`
    endpoint and the price cache — both of which work here, unlike yfinance (segfaults
    locally) and Yahoo's quoteSummary (dead). Fundamentals come from whatever
    get_ticker_info can assemble, which in practice is Finnhub.
    """
    info, quote = {}, None
    try:
        from core.data_engine import get_ticker_info
        info = get_ticker_info(ticker) or {}
    except Exception:
        pass
    try:
        from core.cio_engine import fetch_batch_quotes_with_cache
        quote = (fetch_batch_quotes_with_cache([ticker]) or {}).get(ticker)
    except Exception:
        pass
    if not quote or not quote.get("price"):
        try:
            from core.options_data import fetch_closes
            closes = fetch_closes(ticker, twelve_data_key=os.getenv("TWELVE_DATA_API_KEY", ""))
            if closes:
                quote = {"price": closes[-1], "source": "Yahoo chart / Twelve Data close"}
        except Exception:
            pass
    return info, quote


def _already_done(ticker: str, max_age_days: int) -> bool:
    if max_age_days <= 0:
        return False
    try:
        from core.database import get_prosper_analysis
        row = get_prosper_analysis(ticker) or {}
        d = str(row.get("analysis_date") or "")[:10]
        if not d:
            return False
        age = (datetime.now() - datetime.strptime(d, "%Y-%m-%d")).days
        return age <= max_age_days and bool(row.get("framework"))
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description="Run GROW over many tickers and store the results")
    src = ap.add_argument_group("what to run")
    src.add_argument("--tickers", help="comma-separated list")
    src.add_argument("--universe", action="store_true",
                     help="the 50-name assignment-grade universe (harvest/universe.py)")
    src.add_argument("--holdings", action="store_true", help="every US holding")
    src.add_argument("--top", type=int,
                     help="cap the list at N names, ranked by position VALUE (not share count)")
    src.add_argument("--include-funds", action="store_true",
                     help="don't skip ETFs / bond funds / income wrappers")

    ap.add_argument("--tier", default="screen",
                    choices=["screen", "standard", "full", "full_lean"],
                    help="screen is enough for the Options Desk's Rule 1 (default). full_lean is "
                         "full-tier retrieval breadth at ~a quarter of full's price")
    ap.add_argument("--skip-fresh", type=int, default=30, metavar="DAYS",
                    help="skip names already analysed within N days (0 = re-run everything)")
    ap.add_argument("--budget", type=float, default=0.0, metavar="USD",
                    help="stop once estimated spend exceeds this (0 = no cap)")
    ap.add_argument("--dry-run", action="store_true", help="list what would run, and the estimate")
    ap.add_argument("--stub-yfinance", action="store_true",
                    help="required to run locally: yfinance segfaults (exit 139) for every "
                         "ticker in the local venv on Python 3.14, which kills the batch on the "
                         "first name. Substitutes an inert stand-in. Production (3.12) is fine "
                         "and does not need this.")
    args = ap.parse_args()

    if args.stub_yfinance:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stub"))
        _log.info("--stub-yfinance: aggregator financial statements omitted from the Tier-5 "
                  "snapshot (GROW treats them as confirmation-only under 6.2)")

    if not (args.tickers or args.universe or args.holdings):
        ap.error("pick at least one of --tickers / --universe / --holdings")

    from core import grow_engine as ge

    targets = _resolve_targets(args)
    if args.skip_fresh:
        before = len(targets)
        targets = [t for t in targets if not _already_done(t, args.skip_fresh)]
        _log.info("skipping %d name(s) analysed within %d days", before - len(targets), args.skip_fresh)

    est = ge.GROW_TIERS[args.tier]["est_cost"]
    _log.info("%d name(s), tier=%s, rough estimate $%.2f total ($%.2f each)",
              len(targets), args.tier, est * len(targets), est)

    if args.dry_run:
        print("\n".join(targets))
        return 0
    if not targets:
        _log.info("nothing to run.")
        return 0

    from core.database import save_prosper_analysis, init_db
    try:
        init_db()
    except Exception as e:
        _log.error("database not ready: %s", e)
        return 1

    spent, ok, failed = 0.0, 0, []
    t0 = time.time()
    for i, t in enumerate(targets, 1):
        if args.budget and spent >= args.budget:
            _log.warning("budget of $%.2f reached after %d name(s) — stopping.", args.budget, i - 1)
            break
        _log.info("[%d/%d] GROW %s (%s)…", i, len(targets), t, args.tier)
        # GROW needs a price. run_grow() will not fetch one for itself, and without it the
        # Entry verdict has nothing to solve against — the first version of this script omitted
        # it and every run came back "no Durability score (rule 20) — run rejected".
        info, quote = _snapshot_inputs(t)
        try:
            res, err = ge.run_grow(t, tier=args.tier, info=info, price_quote=quote)
        except Exception as e:
            res, err = None, f"{type(e).__name__}: {e}"
        if not res:
            failed.append((t, err))
            # A failure is not free: a run that dies on max_tokens has already paid for every
            # output token it spent getting there. Charge the estimate against the budget so a
            # string of failures cannot silently blow through it.
            spent += est
            _log.warning("   %s failed (≈$%.2f still spent): %s", t, est, str(err)[:160])
            continue
        spent += res.get("cost_estimate") or 0.0
        try:
            save_prosper_analysis(t, res)
        except Exception as e:
            _log.warning("   %s computed but not saved: %s", t, e)
        ok += 1
        _log.info("   %s Durability %.0f (%s) · Entry %s · buy below %s · $%.4f",
                  t, res.get("durability") or 0, res.get("durability_band") or "?",
                  res.get("entry_verdict"), res.get("buy_below"), res.get("cost_estimate") or 0)

    _log.info("done: %d ok, %d failed, $%.2f spent, %.1f min",
              ok, len(failed), spent, (time.time() - t0) / 60)
    for t, e in failed:
        _log.info("  FAILED %-8s %s", t, str(e)[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())
