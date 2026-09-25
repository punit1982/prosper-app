#!/usr/bin/env python3
"""
PROSPER v5.13.1 — import a chat-window card into Prosper
=======================================================
Takes the reply a Claude (or any capable LLM) conversation produced for a PROSPER brief,
validates it, runs the deterministic resolver over it, and stores it in prosper_analysis — the
same table, the same shape and the same arithmetic as an API run.

    python3 scripts/prosper_import.py --file ~/prosper_out/ADBE.md --ticker ADBE
    python3 scripts/prosper_import.py --dir  ~/prosper_out            # whole folder, ticker from filename
    python3 scripts/prosper_import.py --file ADBE.md --ticker ADBE --dry-run

WHY THE RESOLVER MATTERS HERE
-----------------------------
`resolve_card()` recomputes the score, the call, the printed reward:risk ratio, the hard caps and
the buy-below line in Python from the card's own inputs, and OVERRIDES whatever the model wrote.
That is what makes a chat-window card trustworthy here: the model supplies the judgement (scores,
cases, integrity type), Python supplies every number the Options Desk's Rule 1 then reads.
Both paths call core.prosper_engine.assemble_result(), so they cannot drift apart.

WHAT IS CHECKED BEFORE ANYTHING IS SAVED
----------------------------------------
  * a fenced ```json block exists and parses
  * the ticker in the JSON matches the ticker you are importing as
  * a price exists to rate against (step 1)
  * bear, base and bull prices exist (step 9) — unless a microcap kill-switch fired
  * `no_rating_reason` is empty (step 4: no reconciliation = no rating)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stub"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from core import prosper_engine as pe          # noqa: E402


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

    data = pe._extract_json_block(text)
    if not data:
        print(f"  {ticker}: no parseable ```json block — was the WHOLE reply saved, "
              f"including the fenced block at the end?")
        return False

    json_ticker = str(data.get("ticker") or "").strip().upper()
    if json_ticker and json_ticker != ticker:
        print(f"  {ticker}: the JSON says ticker={json_ticker!r}. Refusing to file one "
              f"company's card under another's name — pass --ticker {json_ticker} if that "
              f"is what you meant.")
        return False

    # The price the card was written at, if it states one, is the one to rate against: the
    # ratio is a function of spot, and re-pricing it here would silently change the call.
    price_obj = data.get("price") if isinstance(data.get("price"), dict) else {"value": data.get("price")}
    quote = None
    if pe._f(price_obj.get("value")) is None:
        quote = _price_for(ticker)
        if not quote:
            print(f"  {ticker}: no price in the JSON and none fetchable — nothing to rate "
                  f"against. Add price.value to the JSON and retry.")
            return False

    info, prior = {}, None
    try:
        from core.data_engine import get_ticker_info
        info = get_ticker_info(ticker) or {}
    except Exception:
        pass
    try:
        from core.database import get_prosper_analysis
        prior = get_prosper_analysis(ticker)
    except Exception:
        pass

    memo = pe._strip_json_block(text)
    result, err = pe.assemble_result(
        ticker, data, memo, tier="cowork", info=info, price_quote=quote,
        model_id="chat window (subscription)", cost=0.0, elapsed=0.0,
        data_fields=12, usage={}, prior=prior,
    )
    if not result:
        print(f"  {ticker}: {err}")
        return False

    note = ("Produced in a chat window on a subscription, not through the API. Every number on "
            "this card was recomputed in Python from the card's own inputs.")
    result["uncertainties"] = [note] + list(result.get("uncertainties") or [])
    result["full_response"]["uncertainties"] = result["uncertainties"]

    r = result["resolved"]
    print(f"  {ticker}: score {result['q_score']:.1f} · {result['entry_verdict']} · "
          f"reward:risk {r['ratio_text']} · buy below {result.get('buy_below')} · "
          f"take-profit {result.get('fair_high')} · card {len(memo):,} chars")
    if result.get("model_call") and result["model_call"] != result["entry_verdict"]:
        print(f"      override: the card wrote {result['model_call']}, "
              f"the arithmetic says {result['entry_verdict']}")
    for g in r.get("gates") or []:
        print(f"      gate {g['rule']}: {g['from']} → {g['to']}")

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
    ap = argparse.ArgumentParser(description="Import a chat-window PROSPER card into Prosper")
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
