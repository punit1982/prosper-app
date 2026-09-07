#!/usr/bin/env python3
"""
GROW — import a Cowork memo into Prosper
=======================================
Takes the reply Claude Cowork produced for a GROW brief, validates it, runs the deterministic
§8 resolver over it, and stores it in prosper_analysis — the same table, the same shape and the
same arithmetic as an API run.

    python3 scripts/grow_import.py --file ~/grow_out/ADBE.md --ticker ADBE
    python3 scripts/grow_import.py --dir  ~/grow_out            # whole folder, ticker from filename
    python3 scripts/grow_import.py --file ADBE.md --ticker ADBE --dry-run

WHY THE RESOLVER MATTERS HERE
-----------------------------
GROW's §8 is arithmetic, not judgement: `resolve_entry()` recomputes the Entry verdict, the
five-rung price ladder and the ±25% stability band in Python from the model's own inputs and
OVERRIDES whatever the model wrote. That is deliberate on the API path and it is what makes a
chat-window memo trustworthy here — the model supplies the judgement (archetype, central value,
horizon, required return), Python supplies every number the Options Desk's Rule 1 then reads.

Both paths call core.grow_engine.assemble_result(), so they cannot drift apart.

WHAT IS CHECKED BEFORE ANYTHING IS SAVED
----------------------------------------
  * a fenced ```json block exists and parses
  * durability.score is present and 0-100 (rule 20 — a run without it is rejected)
  * entry.verdict is one of the five permitted words (rule 22)
  * a price exists to solve the ladder against
  * the ticker in the JSON matches the ticker you are importing as
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stub"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from core import grow_engine as ge          # noqa: E402


def _price_for(ticker: str):
    try:
        from core.cio_engine import fetch_batch_quotes_with_cache
        q = (fetch_batch_quotes_with_cache([ticker]) or {}).get(ticker)
        if q and q.get("price"):
            return q
    except Exception:
        pass
    try:
        from core.options_data import fetch_closes
        c = fetch_closes(ticker, twelve_data_key=os.getenv("TWELVE_DATA_API_KEY", ""))
        if c:
            return {"price": c[-1], "source": "Yahoo chart / Twelve Data close"}
    except Exception:
        pass
    return None


def import_one(path: str, ticker: str = None, *, dry_run: bool = False) -> bool:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    ticker = (ticker or os.path.splitext(os.path.basename(path))[0].replace("_", ".")).upper()

    data = ge._extract_json_block(text)
    if not data:
        print(f"  {ticker}: no parseable ```json block — was the WHOLE reply saved, "
              f"including the fenced block at the end?")
        return False

    json_ticker = str(data.get("ticker") or "").strip().upper()
    if json_ticker and json_ticker != ticker:
        print(f"  {ticker}: the JSON says ticker={json_ticker!r}. Refusing to file one "
              f"company's analysis under another's name — pass --ticker {json_ticker} if that "
              f"is what you meant.")
        return False

    score = ((data.get("durability") or {}).get("score"))
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = None
    if score is None or not (0 <= score <= 100):
        print(f"  {ticker}: durability.score missing or out of range ({score!r}) — "
              f"rejected under rule 20.")
        return False

    verdict = str(((data.get("entry") or {}).get("verdict")) or "").strip().upper()
    if verdict not in ge.ENTRY_SCALE:
        print(f"  {ticker}: entry.verdict {verdict!r} is not one of {ge.ENTRY_SCALE} (rule 22).")
        return False

    quote = _price_for(ticker)
    if not quote and not ((data.get("entry") or {}).get("price")):
        print(f"  {ticker}: no price in the JSON and none fetchable — the ladder cannot be "
              f"solved. Add entry.price to the JSON and retry.")
        return False

    info = {}
    try:
        from core.data_engine import get_ticker_info
        info = get_ticker_info(ticker) or {}
    except Exception:
        pass

    memo = ge._strip_json_block(text)
    result, err = ge.assemble_result(
        ticker, data, memo, tier="cowork", info=info, price_quote=quote,
        model_id="cowork (Claude Pro)", cost=0.0, elapsed=0.0,
        data_fields=12, usage={},
    )
    if not result:
        print(f"  {ticker}: {err}")
        return False

    note = ("Produced in Claude Cowork on the Pro subscription, not through the API. "
            "The §8 ladder below was recomputed in Python from the memo's own inputs.")
    result["uncertainties"] = [note] + list(result.get("uncertainties") or [])

    print(f"  {ticker}: Durability {result['durability']:.0f} ({result.get('durability_band')}) · "
          f"Entry {result['entry_verdict']} · strong-buy below {result.get('strong_buy_below')} · "
          f"buy below {result.get('buy_below')} · fair-high {result.get('fair_high')} · "
          f"memo {len(memo):,} chars")
    if result.get("model_entry_verdict") and result["model_entry_verdict"] != result["entry_verdict"]:
        print(f"      §8 override: the memo wrote {result['model_entry_verdict']}, "
              f"the arithmetic says {result['entry_verdict']}")

    if dry_run:
        print("      (dry run — nothing saved)")
        return True

    try:
        from core.database import save_prosper_analysis, init_db
        init_db()
        save_prosper_analysis(ticker, result)
        print("      saved to prosper_analysis")
        return True
    except Exception as e:
        print(f"      SAVE FAILED: {e}")
        return False


def main():
    ap = argparse.ArgumentParser(description="Import a Cowork GROW memo into Prosper")
    ap.add_argument("--file", help="one saved reply (markdown or text)")
    ap.add_argument("--dir", help="a folder of them; ticker taken from each filename")
    ap.add_argument("--ticker", help="override the ticker (defaults to the filename)")
    ap.add_argument("--dry-run", action="store_true", help="validate and show, save nothing")
    args = ap.parse_args()

    if not (args.file or args.dir):
        ap.error("pass --file or --dir")

    paths = []
    if args.file:
        paths.append((args.file, args.ticker))
    if args.dir:
        for fn in sorted(os.listdir(args.dir)):
            if fn.lower().endswith((".md", ".txt", ".json")):
                paths.append((os.path.join(args.dir, fn), None))

    ok = 0
    for path, tk in paths:
        try:
            if import_one(path, tk, dry_run=args.dry_run):
                ok += 1
        except Exception as e:
            print(f"  {path}: FAILED — {type(e).__name__}: {e}")
    print(f"\n{ok} of {len(paths)} imported.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
