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
            df = get_all_holdings()
            if df is not None and not df.empty:
                if args.top and "quantity" in df.columns:
                    df = df.copy()
                    df["_q"] = df["quantity"].astype(float)
                    df = df.sort_values("_q", ascending=False)
                names += [str(t).upper() for t in df["ticker"].tolist()]
        except Exception as e:
            _log.warning("could not read holdings: %s", e)
    seen, out = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n); out.append(n)
    return out[:args.top] if args.top else out


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
    src.add_argument("--top", type=int, help="cap the list at N names")

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
            _log.warning("   %s failed: %s", t, str(err)[:160])
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
