#!/usr/bin/env python3
"""
Cache pre-warm
==============
Runs OUTSIDE the Streamlit app (cron / GitHub Action) to fill the shared
Turso-backed caches before the user's morning, so the first page load of the
day isn't the one that pays for 100+ slow yfinance calls on top of Render's
cold start (reliability audit, §5 "Automation worth adding").

What it refreshes, for every distinct ticker across all portfolios:
  • ticker_info_cache   — fundamentals (yfinance → FMP → Finnhub → Mubasher)
  • price_cache         — latest prices
  • fx_rate_cache       — one rate per non-base currency held

Needs the same environment as production:
  TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, ANTHROPIC_API_KEY (unused here but
  imported), FINNHUB_API_KEY, TWELVE_DATA_API_KEY, FMP_API_KEY.

Safe to run anytime; it only writes cache rows. Exits 0 even on partial
failure so a scheduler doesn't alarm on a single flaky source.
"""
import os
import sys
import time

# repo root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _log(msg):
    print(f"[prewarm {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    if not os.getenv("TURSO_DATABASE_URL"):
        _log("TURSO_DATABASE_URL not set — nothing to warm (would only hit a local file). Exiting.")
        return 0

    try:
        from core.database import get_all_holdings
        from core.data_engine import get_ticker_info_batch, resolve_tickers_batch
        from core.currency_normalizer import detect_currency_from_ticker, get_exchange_rate
    except Exception as e:
        _log(f"import failed: {e}")
        return 0

    try:
        holdings = get_all_holdings()
    except Exception as e:
        _log(f"could not read holdings: {e}")
        return 0

    if holdings is None or holdings.empty:
        _log("no holdings found — nothing to warm.")
        return 0

    _rows = holdings[["ticker", "currency"]].dropna(subset=["ticker"]) if "currency" in holdings.columns else None
    tickers = sorted({str(t).strip() for t in holdings["ticker"].dropna() if str(t).strip()})
    _log(f"{len(tickers)} distinct tickers")

    # 1. Resolve suffixes (cached 24h) so the info/price fetches use good symbols
    try:
        pairs = []
        seen = set()
        for _, row in (holdings.iterrows() if _rows is not None else []):
            t = str(row.get("ticker", "")).strip()
            if t and t not in seen:
                seen.add(t)
                pairs.append((t, str(row.get("currency") or "USD")))
        if not pairs:
            pairs = [(t, "USD") for t in tickers]
        resolved = resolve_tickers_batch(pairs)
        tickers = sorted({resolved.get(t, t) for t in tickers})
    except Exception as e:
        _log(f"resolve step skipped: {e}")

    # 2. Fundamentals — this is the big one; get_ticker_info_batch writes
    #    ticker_info_cache in Turso.
    try:
        info = get_ticker_info_batch(tickers)
        got = sum(1 for v in info.values() if v)
        _log(f"fundamentals: {got}/{len(tickers)} populated")
    except Exception as e:
        _log(f"fundamentals step failed: {e}")

    # 3. UAE (ADX/DFM) prices — Mubasher is Cloudflare-gated from Render's
    #    datacenter IPs but usually reachable from a GitHub Actions runner, so
    #    fetch here and write price_cache for the app to read.
    try:
        from core.adx_client import is_uae_symbol, get_quote as adx_quote
        from core.database import save_price_cache
        uae = [t for t in tickers if is_uae_symbol(t)]
        warmed = {}
        for t in uae:
            try:
                q = adx_quote(t)
                if q and q.get("price", 0) > 0:
                    warmed[t] = q
                    _log(f"uae {t}: {q['price']} ({q.get('changesPercentage')}%)")
            except Exception as e:
                _log(f"uae {t} failed: {e}")
        if warmed:
            save_price_cache(warmed)
            _log(f"cached {len(warmed)}/{len(uae)} UAE prices")
    except Exception as e:
        _log(f"UAE price step failed: {e}")

    # 4. FX — one warm rate per currency actually held
    base = os.getenv("BASE_CURRENCY", "USD")
    currencies = {detect_currency_from_ticker(t) for t in tickers} - {base}
    for ccy in sorted(c for c in currencies if c):
        try:
            r = get_exchange_rate(ccy, base)
            _log(f"fx {ccy}->{base}: {r:.4f}")
        except Exception as e:
            _log(f"fx {ccy}->{base} failed: {e}")

    _log("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
