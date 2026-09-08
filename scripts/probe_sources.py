#!/usr/bin/env python3
"""
probe_sources.py — ask every data source, from THIS network, whether it works.

The recurring lesson on this project is that "verified live" from a laptop is
not the same as verified on Render. Mubasher works perfectly from a residential
IP and 403s Render's datacenter IPs; Yahoo's chart endpoint now rate-limits
both. A source's reachability is a property of the network, not of the code, so
it has to be measured where the code actually runs.

Run it anywhere:

    venv/bin/python3 scripts/probe_sources.py           # human-readable
    venv/bin/python3 scripts/probe_sources.py --json    # for CI / logging

In production, use the "Data Source Health" panel on the Settings page, which
runs these same probes server-side. TradingView is the result that matters most:
it is the primary for every market and the only source that prices ADX/DFM.
Confirmed answering from Render on 8 Sep 2026 (200, 191ms); Mubasher confirmed
403 on the same run and was removed from the price path as a result.

No API keys are required for the keyless probes; keyed ones are skipped with a
clear note when the key is absent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UA = "Mozilla/5.0 (compatible; Prosper-probe/1.0)"
TIMEOUT = 12


def _call(url, *, payload=None, headers=None):
    hdr = {"User-Agent": UA, "Accept": "application/json,text/plain,*/*"}
    if payload is not None:
        hdr["Content-Type"] = "application/json"
    hdr.update(headers or {})
    data = json.dumps(payload).encode() if payload is not None else None
    started = time.time()
    try:
        req = urllib.request.Request(url, data=data, headers=hdr,
                                     method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            return resp.status, int((time.time() - started) * 1000), body
    except urllib.error.HTTPError as exc:
        return exc.code, int((time.time() - started) * 1000), (exc.read()[:200] if exc.fp else b"")
    except Exception as exc:                       # noqa: BLE001
        return "ERR", int((time.time() - started) * 1000), str(exc)[:160].encode()


def probe_tradingview():
    """THE probe. Prices real UAE holdings — the market with no other source."""
    body = {
        "symbols": {"tickers": ["ADX:ALDAR", "DFM:EMAAR", "ADX:ADCB"], "query": {"types": []}},
        "columns": ["close", "currency", "update_mode"],
    }
    status, ms, raw = _call("https://scanner.tradingview.com/uae/scan", payload=body)
    detail = ""
    ok = False
    if status == 200:
        try:
            rows = json.loads(raw).get("data") or []
            ok = len(rows) >= 3
            detail = ", ".join(f"{r['s'].split(':')[-1]} {r['d'][0]} {r['d'][1]}" for r in rows[:3])
        except Exception:
            detail = raw[:120].decode("utf-8", "replace")
    else:
        detail = raw[:120].decode("utf-8", "replace")
    return "tradingview (UAE)", ok, status, ms, detail


def probe_yahoo_chart():
    status, ms, raw = _call(
        "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    ok = status == 200
    detail = "ok" if ok else raw[:100].decode("utf-8", "replace")
    return "yahoo chart", ok, status, ms, detail


def probe_mubasher():
    """Informational only — Mubasher is no longer in the price path.

    Removed on 8 Sep 2026 after this probe returned 403 from Render. Still
    checked because scripts/prewarm.py calls it from a GitHub Actions runner,
    where it does work, and because a green here would mean Cloudflare had
    stopped blocking us.
    """
    status, ms, raw = _call("https://english.mubasher.info/markets/ADX/stocks")
    ok = status == 200
    return ("mubasher (prewarm only)", ok, status, ms,
            "reachable — datacenter block lifted?" if ok
            else "403 as expected; not used for pricing")


def probe_amfi():
    status, ms, raw = _call("https://www.amfiindia.com/spages/NAVAll.txt")
    ok = status == 200 and len(raw) > 100_000
    return "amfi (India funds)", ok, status, ms, f"{len(raw):,} bytes"


def probe_justetf():
    isin = "IE00BGSF1X88"
    status, ms, raw = _call(
        f"https://www.justetf.com/api/etfs/{isin}/quote?locale=en&currency=USD&isin={isin}")
    ok = False
    detail = raw[:100].decode("utf-8", "replace")
    if status == 200:
        try:
            q = (json.loads(raw).get("latestQuote") or {}).get("raw")
            ok, detail = q is not None, f"IB01 = {q}"
        except Exception:
            pass
    return "justetf (LSE ETFs)", ok, status, ms, detail


def probe_boerse_frankfurt():
    status, ms, raw = _call(
        "https://api.boerse-frankfurt.de/v1/data/quote_box/single"
        "?isin=CH0038863350&mic=XFRA")
    ok = False
    detail = raw[:100].decode("utf-8", "replace")
    if status == 200:
        try:
            px = json.loads(raw).get("lastPrice")
            ok, detail = px is not None, f"NESN(XFRA) = EUR {px}"
        except Exception:
            pass
    return "boerse frankfurt", ok, status, ms, detail


def probe_finnhub():
    key = os.getenv("FINNHUB_API_KEY", "")
    if not key:
        return "finnhub (US)", None, "SKIP", 0, "FINNHUB_API_KEY not set"
    status, ms, raw = _call(f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={key}")
    ok = False
    detail = raw[:100].decode("utf-8", "replace")
    if status == 200:
        try:
            c = json.loads(raw).get("c")
            ok, detail = bool(c), f"AAPL = {c}"
        except Exception:
            pass
    return "finnhub (US)", ok, status, ms, detail


def probe_edgar():
    status, ms, raw = _call(
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000796343.json",
        headers={"User-Agent": "Prosper punit1982@gmail.com"})
    return "sec edgar", status == 200, status, ms, f"{len(raw):,} bytes"


def probe_fx():
    status, ms, raw = _call("https://api.frankfurter.app/latest?from=USD&to=INR,JPY,CHF,SGD")
    ok = status == 200
    detail = raw[:110].decode("utf-8", "replace") if ok else "unreachable"
    return "frankfurter (FX)", ok, status, ms, detail


def probe_cboe():
    status, ms, raw = _call(
        "https://cdn.cboe.com/api/global/delayed_quotes/options/ADBE.json")
    return "cboe (US options)", status == 200, status, ms, f"{len(raw):,} bytes"


def probe_crypto():
    status, ms, raw = _call("https://api.coinbase.com/v2/prices/BTC-USD/spot")
    ok = False
    detail = raw[:90].decode("utf-8", "replace")
    if status == 200:
        try:
            amt = (json.loads(raw).get("data") or {}).get("amount")
            ok, detail = bool(amt), f"BTC = ${amt}"
        except Exception:
            pass
    return "coinbase (crypto)", ok, status, ms, detail


PROBES = [
    probe_tradingview, probe_yahoo_chart, probe_mubasher, probe_amfi,
    probe_justetf, probe_boerse_frankfurt, probe_finnhub, probe_edgar,
    probe_fx, probe_cboe, probe_crypto,
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    results = []
    for probe in PROBES:
        try:
            name, ok, status, ms, detail = probe()
        except Exception as exc:                   # noqa: BLE001
            name, ok, status, ms, detail = probe.__name__, False, "ERR", 0, repr(exc)[:120]
        results.append({"source": name, "ok": ok, "status": status,
                        "ms": ms, "detail": detail})

    if args.json:
        print(json.dumps({"probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                          "results": results}, indent=2))
        return 0

    print(f"\nProsper data-source probe — {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("Run this on the network the app actually uses. A pass here from a")
    print("laptop says nothing about Render.\n")
    print(f"  {'SOURCE':<24} {'':<5} {'HTTP':<6} {'TIME':>8}  DETAIL")
    print("  " + "-" * 92)
    for r in results:
        mark = "SKIP" if r["ok"] is None else ("PASS" if r["ok"] else "FAIL")
        print(f"  {r['source']:<24} {mark:<5} {str(r['status']):<6} {str(r['ms'])+'ms':>8}  {r['detail'][:60]}")

    failed = [r["source"] for r in results if r["ok"] is False]
    print()
    if failed:
        print(f"  {len(failed)} unreachable from this network: {', '.join(failed)}")
    else:
        print("  every source reachable from this network")

    tv = next((r for r in results if r["source"].startswith("tradingview")), None)
    if tv and not tv["ok"]:
        print("\n  TradingView did NOT answer from this network. It is the primary for")
        print("  every market and the ONLY source that prices ADX/DFM, so expect UAE")
        print("  lines to fall back to the committed IBKR marks until it recovers.")
        print("  Kill switch, if it starts returning nonsense: PROSPER_DISABLE_TRADINGVIEW=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
