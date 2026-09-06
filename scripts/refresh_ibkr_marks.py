"""
Refresh data/ibkr_marks.json from an IBKR positions snapshot.
=============================================================
Why this exists
---------------
The deployed app has no working live quote for UAE (ADX/DFM) names, several
European / offshore funds, and a handful of thin or suspended lines — Mubasher
is Cloudflare-gated from Render, Twelve Data gates them behind a paid tier, and
yfinance / Finnhub do not carry them (see HANDOFF.md §6).

IBKR knows what every one of them is worth. The Flex Query *web service* would
give the app a token-based path to that, but it has never been configured on
Render. Until it is, the fallback is this file: a snapshot of IBKR's own mark
price for every position, committed to the repo and refreshed by hand at the
start of a working session.

On startup the app calls ``core.ibkr_prices.apply_static_marks_to_holdings()``,
which writes these numbers into ``holdings.last_known_price`` — the same column
the price cascade already falls back to (core/cio_engine.py) and the one that
nothing else back-fills. It never overrides a live quote.

How to refresh (do this once at the start of a session)
-------------------------------------------------------
1. In the Claude session, call the IBKR connector's ``get_account_positions``.
2. Save its JSON output to a file, e.g. ``/tmp/ibkr_raw.json``. The expected
   shape is ``{"positions": [{"contract_description": "EMAAR @DFM",
   "market_price": 11.0, "currency": "AED", ...}, ...]}``.
3. Run:  ``venv/bin/python3 scripts/refresh_ibkr_marks.py /tmp/ibkr_raw.json``
   (or pipe the JSON in on stdin).
4. ``git add data/ibkr_marks.json && git commit && git push`` — the deploy
   picks it up and the daily backfill applies it on the next app start.

The mapping from IBKR's venue codes to the app's ticker suffixes reuses
``core.file_parsers.IBKR_EXCHANGE_SUFFIX`` so it stays in sync with how the
Flex statement parser builds tickers in the first place.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _REPO)

from core.file_parsers import IBKR_EXCHANGE_SUFFIX, CURRENCY_SUFFIX  # noqa: E402

_OUT_PATH = os.path.join(_REPO, "data", "ibkr_marks.json")

# IBKR "position feed" venue codes that are not real listing exchanges — the
# instrument is a fund wrapper or a broker-internal book with no public symbol.
_SYNTHETIC_VENUES = {"FUNDSERV", "ALLFUNDS", "VALUE"}


def _mapped_ticker(contract_description: str, currency: str) -> str | None:
    """'EMAAR @DFM' -> 'EMAAR.AE'.  'ADBE' -> 'ADBE'.  Returns None to skip."""
    desc = (contract_description or "").strip()
    if not desc:
        return None
    if " @" in desc:
        symbol, _, venue = desc.partition(" @")
        symbol = symbol.strip().upper()
        venue = venue.strip().upper()
    else:
        symbol, venue = desc.upper(), ""

    if symbol.startswith("IBCID") or venue in _SYNTHETIC_VENUES:
        return None

    if venue in IBKR_EXCHANGE_SUFFIX:
        suffix = IBKR_EXCHANGE_SUFFIX[venue]
    elif venue:
        # Unknown venue — fall back to the currency-based suffix the Flex
        # parser also uses, so we still produce the app's ticker form.
        suffix = CURRENCY_SUFFIX.get((currency or "").upper(), "")
    else:
        suffix = ""  # US line, no suffix

    if suffix and not symbol.endswith(suffix):
        return symbol + suffix
    return symbol


def build(raw: dict) -> dict:
    positions = raw.get("positions") or raw.get("data") or []
    marks: dict[str, dict] = {}
    skipped: list[str] = []
    for p in positions:
        desc = p.get("contract_description") or p.get("description") or ""
        currency = (p.get("currency") or "USD").strip().upper()
        try:
            price = float(p.get("market_price") or p.get("markPrice") or 0)
        except (TypeError, ValueError):
            price = 0.0
        ticker = _mapped_ticker(desc, currency)
        if not ticker or price <= 0:
            skipped.append(desc or "?")
            continue
        marks[ticker] = {"price": round(price, 6), "currency": currency}

    return {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "IBKR connector snapshot (get_account_positions), refreshed in-session",
        "note": (
            "Broker mark prices, not live quotes — a previous close for most "
            "markets. Written into holdings.last_known_price on app start; "
            "never overrides a live quote. Regenerate with "
            "scripts/refresh_ibkr_marks.py."
        ),
        "count": len(marks),
        "marks": dict(sorted(marks.items())),
        "_skipped": sorted(set(skipped)),
    }


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] not in ("-", "/dev/stdin"):
        with open(argv[1], encoding="utf-8") as fh:
            raw = json.load(fh)
    else:
        raw = json.load(sys.stdin)

    out = build(raw)
    os.makedirs(os.path.dirname(_OUT_PATH), exist_ok=True)
    with open(_OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"Wrote {out['count']} marks to {os.path.relpath(_OUT_PATH, _REPO)} "
          f"(as of {out['as_of']}).")
    if out["_skipped"]:
        print(f"Skipped {len(out['_skipped'])}: {', '.join(out['_skipped'][:12])}"
              + (" ..." if len(out['_skipped']) > 12 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
