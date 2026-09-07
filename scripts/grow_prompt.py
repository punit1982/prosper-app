#!/usr/bin/env python3
"""
GROW — build a brief to run in Claude Cowork (no API cost)
==========================================================
Writes a self-contained brief per ticker that you paste into a Claude Cowork conversation.
Cowork runs on your Pro subscription, so the analysis costs nothing per token; the API path
(scripts/grow_batch.py) costs ~$1.27 a name at full_lean.

WHAT THIS DOES AND DOESN'T CHANGE
---------------------------------
The framework, the output contract and the §8 arithmetic are identical either way. The ONLY
difference is which Claude reads the brief. In particular the deterministic §8 resolver still
runs on import (core.grow_engine.assemble_result), so a Cowork memo produces the same verdict,
the same five-rung ladder and the same stability band as an API run — the model is not trusted
with that arithmetic on either path.

HOW TO USE IT
-------------
  1. Generate the briefs:

       python3 scripts/grow_prompt.py --universe --out ~/grow_briefs
       python3 scripts/grow_prompt.py --tickers ADBE,CRM --out ~/grow_briefs

  2. Open a Claude Cowork conversation with the `grow/` folder attached (it holds CORE plus the
     runtime annexes — that is the framework, and it must be in context).

  3. Paste one brief. Claude does the retrieval and returns a memo plus a fenced ```json block.

  4. Save the WHOLE reply to a file and import it:

       python3 scripts/grow_import.py --file ~/grow_out/ADBE.md --ticker ADBE

Keep one ticker per conversation. The framework is ~36,000 tokens and each memo is long; a
conversation carrying three or four names starts truncating the earlier ones.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stub"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from core import grow_engine as ge          # noqa: E402

_HEADER = """# {version} — {ticker}

You are running the GROW framework. The complete framework (CORE + runtime annexes) is in the
`grow/` folder attached to this conversation — read it first and follow it exactly. Do not
substitute your own valuation method for §8.

## Operating rules for this run

1. Run the nine steps of §3 for **{ticker}**.
2. Retrieval: work the §6 source ladder. Primary filings first (SEC EDGAR / the exchange's
   filing system / the company's investor-relations site), then the company on the record, then
   aggregators for confirmation only. Spend your effort on the load-bearing Class A inputs.
3. The DATA SNAPSHOT below has two parts and they do **not** carry equal weight — read the
   divider carefully. Anything under "SEC EDGAR XBRL — PRIMARY FILING DATA" is as-filed and
   carries the accession number of the filing it came from; treat it as Class A and cite the
   accession number when you use a figure. Everything below the divider is Tier-5 aggregator
   data, confirmation only under §6.2.
4. Position-blind (rule 13): you are given no holding, cost basis or weight. Do not ask for one.
5. Produce **both** verdicts (rule 1). The only permitted Entry words are STRONG BUY, BUY, HOLD,
   SELL, STRONG SELL (rule 22).
6. All prices in the listing currency shown in the snapshot.
7. §8.1/§8.2: `entry.cash_returned` is the cumulative dividends/cash the §8.1 table tells you to
   include over the horizon (0 if the company pays nothing — never omit the field).
   `entry.base_cost_of_equity` is required_return with the archetype premium (§4) subtracted
   back out. Both are mandatory numeric fields even when zero.

## Output — two parts, in this order

**PART 1** — the memo in plain English, in the §10.2 order, as markdown.

**PART 2** — a single fenced ```json block, the LAST thing in your reply, matching the shape
below exactly. All keys present; use null where a value genuinely does not exist; rates as
decimals (0.114 for 11.4%).

{contract}

The JSON is machine-read on import. `durability.score` (0-100), `entry.verdict` (one of the five
words), `entry.ladder` and `entry.price` are mandatory and must agree with the memo.

**Note on the arithmetic:** the app recomputes the Entry verdict, the five-rung ladder and the
±25% stability band in Python from your own inputs (central value, horizon, required return,
cash returned, base cost of equity) and overrides your figures. Get the *inputs* right; do not
worry about the ladder arithmetic.

---

## DATA SNAPSHOT

```
{snapshot}
```
"""


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
    snapshot, _ = ge.build_data_snapshot(ticker, info, quote, edgar=edgar)
    return _HEADER.format(version=ge.GROW_VERSION, ticker=ticker.upper(),
                          contract=ge._JSON_CONTRACT.strip(), snapshot=snapshot)


def main():
    ap = argparse.ArgumentParser(description="Generate GROW briefs for Claude Cowork")
    ap.add_argument("--tickers", help="comma-separated")
    ap.add_argument("--universe", action="store_true",
                    help="the 50-name assignment-grade universe")
    ap.add_argument("--holdings", action="store_true", help="US holdings by position value")
    ap.add_argument("--top", type=int, help="cap at N")
    ap.add_argument("--out", default="grow_briefs", help="output directory")
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
            "gb", os.path.join(os.path.dirname(os.path.abspath(__file__)), "grow_batch.py"))
        gb = _u.module_from_spec(spec)
        sys.argv = ["grow_batch"]
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
    print("Open Cowork with the grow/ folder attached, paste one brief per conversation,")
    print("save the whole reply, then: python3 scripts/grow_import.py --file <reply> --ticker <T>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
