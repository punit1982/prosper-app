#!/usr/bin/env python3
"""
HARVEST — nightly options scan
==============================
Sweeps the option chains for the book plus the assignment-grade universe, computes the volatility
metrics, writes them to the database, and (optionally) builds the day's slate with one Claude call.

Run it AFTER a weekday US close. Two reasons:

  * CBOE's bid/ask goes stale over a weekend or a long gap. A Sunday scan reported a 115% median
    spread on XLF, one of the most liquid ETFs alive, purely because Friday's quotes sit unmoved
    on strikes that never traded. Open interest survives; bid/ask does not.
  * The whole point is that the Streamlit page never touches the network. A scan moves ~150MB and
    takes 6-12 minutes against a rate-limited CDN. That cannot live in a page request.

Where it runs
-------------
A GitHub Actions runner, alongside scripts/prewarm.py. Not Render: Render's datacenter IPs are
already known to be blocked by Cloudflare for the Mubasher/UAE fetches, and the same risk applies
here. The runner's IPs are not.

    python scripts/options_scan.py                 # full scan + slate
    python scripts/options_scan.py --no-slate      # data only, no Claude call (free)
    python scripts/options_scan.py --vol-only      # phase 0: just start the IV history clock
    python scripts/options_scan.py --tickers A,B   # a subset, for debugging

`--vol-only` is the mode to run from day one even before the rest is wired up. IV percentile needs
~120 observations and cannot be backfilled from any free source, so every day it does not run is a
day pushed onto the far end of the calendar.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_log = logging.getLogger("harvest.scan")

from core import options_data as od          # noqa: E402
from core import vol_metrics as vm           # noqa: E402
from harvest import universe as agu          # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────

def ensure_schema() -> bool:
    """Create the tables this script writes to.

    app.py calls init_db() after login; a headless runner never reaches that, so without this
    every save_chain_snapshot / save_vol_observation raised "no such table", was swallowed as a
    per-name warning, and the run still reported success. The IV-history clock would have looked
    like it was ticking while writing nothing — the exact failure that makes a --vol-only run
    worthless.
    """
    try:
        from core.database import init_db
        init_db()
        return True
    except Exception as e:
        _log.error("could not create/verify the database schema: %s", e)
        return False


def _positions_from_db() -> dict:
    """{TICKER: {'shares': n}} for US-listed lots, from holdings.

    Needs a Streamlit session for the multi-tenant scoping, so it degrades to an empty dict when
    run headless without one. The scan is still fully useful in that mode — the assignment-grade
    universe does not depend on holdings, only covered calls do.
    """
    try:
        from core.database import get_all_holdings
        df = get_all_holdings()
        if df is None or df.empty:
            return {}
        out = {}
        for _, r in df.iterrows():
            t = str(r.get("ticker") or "").strip().upper()
            cur = str(r.get("currency") or "").strip().upper()
            if not t or "." in t or not t.isalpha() or len(t) > 5:
                continue                      # US-listed only; options are a US-market feature here
            if cur and cur != "USD":
                continue
            try:
                q = float(r.get("quantity") or 0)
            except (TypeError, ValueError):
                continue
            if q > 0:
                out[t] = {"shares": out.get(t, {}).get("shares", 0) + q}
        return out
    except Exception as e:
        _log.info("holdings unavailable (%s) — scanning the universe only", e)
        return {}


def _grow_map_from_db() -> dict:
    try:
        from core.database import get_all_prosper_analyses
        df = get_all_prosper_analyses()
        if df is None or df.empty:
            return {}
        return {str(r["ticker"]).upper(): dict(r) for _, r in df.iterrows()}
    except Exception:
        return {}


def build_scan_list(extra: list = None) -> list:
    """Book lots (100+ shares, US-listed) + the assignment-grade universe + the hedge annex."""
    positions = _positions_from_db()
    book = [t for t, p in positions.items() if (p.get("shares") or 0) >= 100]
    names = sorted(set(book) | set(agu.universe_tickers()) | set(extra or []))
    return names, positions


# ─────────────────────────────────────────────────────────────────────────────

def already_scanned(scan_date: str) -> set:
    """Tickers already stored for this scan date."""
    try:
        from core.database import get_chain_snapshots
        return set((get_chain_snapshots(scan_date) or {}).keys())
    except Exception:
        return set()


def scan(tickers: list, *, scan_date: str, td_key: str, persist: bool = True) -> tuple:
    """Fetch, reduce and measure every ticker. Returns (snapshots, metrics, failures).

    Deliberately fault-tolerant per name: one dead underlying must never abort a 110-name sweep
    that has already spent eight minutes. Failures are collected and reported, not raised.
    """
    snapshots, metrics, failures = {}, {}, []
    stored, persist_errors = [], []
    pacer = od._Pacer()

    iv_history = {}
    if persist:
        try:
            from core.database import get_iv_history_map
            iv_history = get_iv_history_map(tickers)
        except Exception:
            iv_history = {}

    t0 = time.time()
    for i, t in enumerate(tickers, 1):
        try:
            snap = od.chain_snapshot(t, pacer=pacer)
        except od.ChainUnavailable as e:
            failures.append({"ticker": t, "stage": "chain", "error": str(e)})
            _log.info("[%3d/%d] %-6s no chain", i, len(tickers), t)
            continue
        except Exception as e:
            failures.append({"ticker": t, "stage": "chain", "error": f"{type(e).__name__}: {e}"})
            _log.warning("[%3d/%d] %-6s chain error: %s", i, len(tickers), t, e)
            continue

        closes = od.fetch_closes(t, twelve_data_key=td_key)
        m = vm.build_metrics(snap, closes, iv_history.get(t, []))
        snapshots[t], metrics[t] = snap, m

        if persist:
            try:
                from core.database import save_chain_snapshot, save_vol_observation
                save_chain_snapshot(t, scan_date, snap, m)
                save_vol_observation(t, scan_date, m)
                stored.append(t)
            except Exception as e:
                _log.warning("%-6s persist failed: %s", t, e)
                persist_errors.append(f"{t}: {e}")

        _log.info("[%3d/%d] %-6s spot=%-9s iv30=%-6s hv20=%-6s vrp=%-6s %-8s oi=%s",
                  i, len(tickers), t,
                  f"{m.get('spot') or 0:.2f}", f"{m.get('iv30') or 0:.1f}",
                  f"{m.get('hv20') or 0:.1f}", f"{m.get('vrp') or 0:.2f}",
                  m.get("vrp_verdict"), m.get("total_oi"))

    _log.info("scan complete: %d fetched, %d stored, %d failed, %.1f min",
              len(snapshots), len(stored), len(failures), (time.time() - t0) / 60)
    if persist and persist_errors:
        # Loud, not a shrug: a scan that fetched everything and stored nothing looks identical to
        # a successful one in the logs unless this is said plainly.
        _log.error("NOTHING WAS SAVED for %d name(s). First error: %s",
                   len(persist_errors), persist_errors[0])
    return snapshots, metrics, failures, stored


def build_and_store_slate(snapshots: dict, metrics: dict, positions: dict, *, scan_date: str):
    """Layers 2-4 plus persistence. One Claude call."""
    from core import options_engine as oe
    from core.settings import SETTINGS

    cfg = oe.configure()
    _log.info("doctrine numbers: T-bill %.2f%%, funding %.2f%%",
              cfg["tbill_yield_pct"], cfg["funding_cost_pct"])

    grow_map = _grow_map_from_db()

    earnings = od.fetch_earnings_calendar(os.getenv("FINNHUB_API_KEY", ""))
    _log.info("earnings calendar: %d symbols with a scheduled date", len(earnings))

    collateral = float(SETTINGS.get("harvest_collateral_usd", 0) or 0)
    if collateral <= 0:
        collateral = float(os.getenv("HARVEST_COLLATERAL_USD", "0") or 0)
    if collateral <= 0:
        _log.warning("no collateral configured — short puts will all be blocked by R4. "
                     "Set harvest_collateral_usd in Settings or HARVEST_COLLATERAL_USD in env.")

    open_underlyings, committed = set(), 0.0
    try:
        from core.database import get_open_harvest_positions
        pos = get_open_harvest_positions()
        if pos is not None and not pos.empty:
            open_underlyings = {str(t).upper() for t in pos["ticker"].tolist()}
            committed = float(pos["collateral"].fillna(0).sum())
    except Exception:
        pass

    payload = oe.build_slate(
        snapshots, metrics, positions, grow_map, earnings,
        collateral_available=collateral, collateral_committed=committed,
        open_underlyings=open_underlyings, as_of=scan_date,
    )

    if payload.get("error"):
        _log.error("slate build failed: %s", payload["error"])
        return payload

    _log.info("slate: %d ticket(s) from %d candidates, cost $%.4f",
              len(payload.get("tickets") or []), payload.get("candidates_considered") or 0,
              (payload.get("usage") or {}).get("cost") or 0)

    try:
        from core.database import save_harvest_slate, log_harvest_recommendations, prune_chain_cache
        u = payload.get("usage") or {}
        save_harvest_slate(scan_date, payload,
                           market_note=payload.get("market_note") or "",
                           n_selected=len(payload.get("tickets") or []),
                           n_candidates=payload.get("candidates_considered") or 0,
                           model_id=u.get("model_id") or "",
                           cost_estimate=u.get("cost") or 0.0)
        log_harvest_recommendations(scan_date, payload.get("tickets") or [])
        prune_chain_cache()
    except Exception as e:
        _log.warning("slate persist failed: %s", e)
    return payload


# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="HARVEST nightly options scan")
    ap.add_argument("--tickers", help="comma-separated subset, for debugging")
    ap.add_argument("--no-slate", action="store_true", help="scan and store data; skip the Claude call")
    ap.add_argument("--vol-only", action="store_true",
                    help="phase 0: IV/HV history only — no candidates, no slate, no model")
    ap.add_argument("--no-persist", action="store_true", help="do not write to the database")
    ap.add_argument("--resume", action="store_true",
                    help="skip tickers already stored for today — a rate-limited sweep can run "
                         "for hours, and this makes it safe to stop and restart")
    ap.add_argument("--out", help="also write the slate payload to this JSON path")
    args = ap.parse_args()

    scan_date = date.today().isoformat()
    td_key = os.getenv("TWELVE_DATA_API_KEY", "")

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        positions = _positions_from_db()
    else:
        tickers, positions = build_scan_list()

    if not args.no_persist and not ensure_schema():
        _log.error("aborting: the database is not writable, so nothing would be recorded.")
        return 1

    if args.resume and not args.no_persist:
        done = already_scanned(scan_date)
        before = len(tickers)
        tickers = [t for t in tickers if t not in done]
        _log.info("--resume: %d of %d already stored for %s, %d to go",
                  before - len(tickers), before, scan_date, len(tickers))
        if not tickers:
            _log.info("nothing left to scan today.")
            return 0

    _log.info("HARVEST scan %s — %d ticker(s)", scan_date, len(tickers))
    snapshots, metrics, failures, stored = scan(tickers, scan_date=scan_date, td_key=td_key,
                                                persist=not args.no_persist)

    if failures:
        _log.info("names with no usable chain: %s",
                  ", ".join(f["ticker"] for f in failures))

    if args.vol_only:
        if args.no_persist:
            _log.info("--vol-only with --no-persist: %d measured, nothing written.", len(metrics))
            return 0
        if not stored:
            _log.error("--vol-only: NOTHING was written. The IV-history clock has not started.")
            return 1
        _log.info("--vol-only: %d observation(s) written. IV percentile unlocks at %d "
                  "observations per name.", len(stored), vm.MIN_HISTORY_FOR_PERCENTILE)
        return 0

    if args.no_slate:
        _log.info("--no-slate: data stored, no model call made.")
        return 0

    payload = build_and_store_slate(snapshots, metrics, positions, scan_date=scan_date)

    if args.out:
        with open(args.out, "w") as f:
            json.dump(payload, f, indent=1, default=str)
        _log.info("payload written to %s", args.out)

    for t in payload.get("tickets") or []:
        _log.info("  #%s %-6s %-18s %s", t.get("rank"), t.get("ticker"), t.get("strategy"),
                  t.get("order_description"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
