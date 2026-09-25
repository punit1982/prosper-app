#!/usr/bin/env python3
"""
PROSPER v5.13.1 — build a brief to run in a chat window (no API cost)
=====================================================================
Writes a self-contained brief per ticker to paste into a Claude Project / Cowork conversation (or
any capable LLM — the framework is the model-agnostic edition). A subscription conversation
costs nothing per token; the API path (scripts/prosper_batch.py) costs ~$0.50-$1.00 a name.

WHAT THIS DOES AND DOESN'T CHANGE
---------------------------------
The framework, the output contract and the arithmetic are identical either way. The resolver
still runs on import (core.prosper_engine.assemble_result), so a chat-window card produces the
same score, call, ratio and buy-below as an API run — the model is not trusted with that
arithmetic on either path.

HOW TO USE IT
-------------
  1. Generate the briefs:

       python3 scripts/prosper_prompt.py --universe --out ~/prosper_briefs
       python3 scripts/prosper_prompt.py --tickers ADBE,CRM --out ~/prosper_briefs

  2. Open a conversation with `prosper_framework/PROSPER v5.13.1 MODEL-AGNOSTIC.md` attached as
     project knowledge / custom instructions — that is the framework, and it must be in context.

  3. Paste one brief. The model does the searches and returns the card plus a fenced ```json block.

  4. Save the WHOLE reply to a file and import it:

       python3 scripts/prosper_import.py --file ~/prosper_out/ADBE.md --ticker ADBE

One ticker per conversation keeps the card and the JSON inside the reply budget.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stub"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from core import prosper_engine as pe          # noqa: E402

_HEADER = """# {version} — {ticker}

`Prosper {ticker}` — run {version} (attached) for **{ticker}**, THE RUN steps 1-13, and follow it
exactly. Today is {today}.

## Platform notes for this run (PART 0)

1. The DATA SNAPSHOT below has two parts that do **not** carry equal weight. Anything under
   "SEC EDGAR XBRL — PRIMARY FILING DATA" is as-filed and carries the accession number of the
   filing it came from — cite it and do not re-retrieve those figures. Everything below the
   divider is aggregator data: confirmation only.
2. The price in the snapshot comes from the Prosper app's quote pipeline, not a broker feed; tag
   it [EXCHANGE] with its basis and time and cross-check it once.
3. Portfolio-blind (P1): you are given no holding, cost basis or weight. Do not ask for one.
4. Do NOT output the cards file — the app stores the card on import (P7).
5. {prior_note}

## Output — two parts, in this order

**PART 1** — the PROSPER CARD exactly as §B13 lays it out: 9 sections, plain English.

**PART 2** — a single fenced ```json block, the LAST thing in your reply, matching the shape
below exactly (all keys present):

{contract}

{notes}

**Note on the arithmetic:** on import the app recomputes the score, the call, the reward:risk
ratio, the hard caps and the buy-below line in Python from your inputs and overrides your
figures. Get the *inputs* right — the scores, the three case prices and weights, the integrity
type, the AI class and the catalysts.

---

## DATA SNAPSHOT

```
{snapshot}
```
{prior_block}"""


def _inputs(ticker: str):
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
            c = fetch_closes(ticker, twelve_data_key=os.getenv("TWELVE_DATA_API_KEY", ""))
            if c:
                quote = {"price": c[-1], "source": "Yahoo chart / Twelve Data close"}
        except Exception:
            pass
    edgar = None
    try:
        from core import edgar_client
        edgar = edgar_client.filing_snapshot(ticker)
    except Exception:
        pass
    return info, quote, edgar


def build_brief(ticker: str) -> str:
    info, quote, edgar = _inputs(ticker)
    snapshot, _ = pe.build_data_snapshot(ticker, info, quote, edgar=edgar)
    prior = None
    try:
        from core.database import get_prosper_analysis
        prior = pe._prior_slim(get_prosper_analysis(ticker))
    except Exception:
        pass
    import json
    from datetime import datetime
    prior_note = ("A PRIOR RUN is attached at the end — carry every anchor no named company fact "
                  "has moved, and print the change table (P9)." if prior else
                  "No prior card exists: this is a first run — say so in the change table (P9).")
    prior_block = ("\n## PRIOR RUN (P9)\n\n```json\n" + json.dumps(prior, default=str)[:12000] + "\n```\n"
                   if prior else "")
    return _HEADER.format(version=pe.PROSPER_VERSION, ticker=ticker.upper(),
                          today=datetime.now().strftime("%d-%b-%Y"), prior_note=prior_note,
                          contract=pe._JSON_CONTRACT.strip(), notes=pe._CONTRACT_NOTES,
                          snapshot=snapshot, prior_block=prior_block)


def main():
    ap = argparse.ArgumentParser(description="Generate PROSPER briefs for a chat-window run")
    ap.add_argument("--tickers", help="comma-separated")
    ap.add_argument("--universe", action="store_true",
                    help="the 50-name assignment-grade universe")
    ap.add_argument("--holdings", action="store_true", help="US holdings by position value")
    ap.add_argument("--top", type=int, help="cap at N")
    ap.add_argument("--out", default="prosper_briefs", help="output directory")
    args = ap.parse_args()

    names = []
    if args.tickers:
        names += [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.universe:
        from harvest import universe as agu
        names += agu.universe_tickers(include_hedge=False)
    if args.holdings:
        import importlib.util as _u
        spec = _u.spec_from_file_location(
            "gb", os.path.join(os.path.dirname(os.path.abspath(__file__)), "prosper_batch.py"))
        gb = _u.module_from_spec(spec)
        sys.argv = ["prosper_batch"]
        spec.loader.exec_module(gb)
        from core.database import get_all_holdings
        import pandas as pd
        df = get_all_holdings()
        if df is not None and not df.empty:
            df = df.copy()
            qty = pd.to_numeric(df["quantity"], errors="coerce").fillna(0)
            px = pd.to_numeric(df.get("last_known_price"), errors="coerce")
            px = px.fillna(pd.to_numeric(df.get("avg_cost"), errors="coerce")).fillna(0)
            df["v"] = qty.abs() * px
            df = df[[not gb._looks_like_fund(r.ticker, getattr(r, "name", ""))
                     for r in df.itertuples()]]
            names += df.sort_values("v", ascending=False)["ticker"].astype(str).str.upper().tolist()

    seen, targets = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n); targets.append(n)
    if args.top:
        targets = targets[:args.top]
    if not targets:
        ap.error("pick --tickers / --universe / --holdings")

    os.makedirs(args.out, exist_ok=True)
    for i, t in enumerate(targets, 1):
        try:
            brief = build_brief(t)
        except Exception as e:
            print(f"  [{i}/{len(targets)}] {t}: FAILED — {e}")
            continue
        path = os.path.join(args.out, f"{t.replace('.', '_')}.md")
        with open(path, "w") as f:
            f.write(brief)
        print(f"  [{i}/{len(targets)}] {t}: {path} ({len(brief) // 3700}k tokens approx)")

    print(f"\n{len(targets)} brief(s) in {args.out}/")
    print("Open a conversation with prosper_framework/PROSPER v5.13.1 MODEL-AGNOSTIC.md attached,")
    print("paste one brief, save the whole reply, then:")
    print("  python3 scripts/prosper_import.py --file <reply> --ticker <T>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
