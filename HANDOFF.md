# Prosper — Handoff (5 Sep 2026, updated post-v7.2)

Paste this into a new chat to continue. Everything below is verified unless marked otherwise.

## What Prosper is
Streamlit + Python investment operating system for one family's multi-broker portfolio (IBKR ×2 accounts,
Coinbase, India via Trendlyne, Fidelity 401k/DCP/RSUs). Owner: Punit Singh (non-programmer, product lead).
Repo: https://github.com/punit1982/prosper-app (branch `main`, this folder). Production: Render free tier
(Docker, Python 3.12, Turso cloud SQLite), auto-deploys on every push to `main`, URL
https://prosper-gzlf.onrender.com, service id `srv-d70gqpuuk2gs739abg7g`, workspace `tea-d70gmplm5p6s73asj1hg`
(user has granted full Render access via the Render MCP connector). Free tier spins down when idle → 30–60 s
cold starts and a "stale sidebar flash" on the first request.

## Local machine
- Folder: `…/AA-Investments /GROW Operating System/prosper/` (iCloud). Sibling folders: `New GROW Prompts/`
  (source of the GROW framework files), `Portfolio Info/` (latest broker exports, Sep 2026).
- `venv/` = Python 3.14 with the **exact production pins** (streamlit 1.41.1, streamlit-authenticator 0.3.3,
  yfinance 1.7, anthropic 0.125). Run the app: `./run.sh`. `.env` holds real API keys (git-ignored):
  ANTHROPIC, FMP, FINNHUB, TWELVE_DATA, SERPER. Google OAuth + Turso creds exist only on Render.
- Old folder `~/Documents/Prosper with Claude March 2026/` (py3.9 venv) is legacy — don't use.
- Local data `~/prosper_data/prosper.db` (stale, April 2026). Test against a COPY with `HOME=<scratch dir>`.
- Test scripts used today live in the session scratchpad (not in repo): verify_fixes.py (32 checks),
  test_auth.py (14), test_grow.py (23 + optional `--live TICKER --tier screen|standard`).

## Architecture (key files)
- `app.py` — page config, sidebar-hide CSS, auth gate, `ensure_settings_loaded()`, `st.navigation` (page URLs
  come from FILE NAMES, e.g. `/Portfolio_Dashboard`), NAV snapshot, floating chat.
- `core/auth.py` — email/password (streamlit-authenticator) + Google OAuth popup → `pages/99_OAuth_Callback.py`.
  Usernames are derived from the email local part (`punit1982@gmail.com` → `punit1982`); since v7.0.1 the form
  also accepts the email (alias entries carry `_canonical`). Credentials need `name`+`roles` (lib 0.3.3).
  Recovery env vars: `PROSPER_RESET_PASSWORD="email:pw"`, `PROSPER_CLAIM_LEGACY="email"` (one-shot; delete after).
- `core/settings.py` — per-session `SETTINGS` proxy (per-user prefs in DB), Claude model IDs
  (`claude-sonnet-5` default, `claude-opus-5` best, `claude-haiku-4-5` fast), `call_claude`, `extract_text`.
- `core/database.py` — SQLite/Turso via `core/db_connector.py`; multi-tenant `user_id` scoping; migrations in
  `init_db` (indexes AFTER migrations; nav_snapshots UNIQUE now per user); `grow_verdict_log`; admin helpers
  `get_data_ownership_summary`, `move_data_between_users`, `claim_legacy_shard_for`.
- `core/cio_engine.py` + `core/data_engine.py` + `core/currency_normalizer.py` — prices (ADX/Mubasher →
  Twelve Data → yfinance → Finnhub), FX, news, fundamentals; all parallel fetches go through
  `core/parallel.py` (hard deadlines; `pool.shutdown(wait=False)`).
- `core/grow_engine.py` — **GROW v5.1 is the analysis engine** (PROSPER v3.0 retired). Tiers: screen
  (Sonnet 5, thinking off, ~$0.10/1 min), standard (Sonnet 5 + web_search/web_fetch, ~$1.20/9 min),
  full (Opus 5, ~$4). Framework text from `grow/` sent as a cached system block; deterministic §8 resolver
  `resolve_entry()` recomputes Entry verdict + price ladder + ±25% stability from the model's inputs.
  `core/grow_render.py` renders; `pages/15_GROW_Analysis.py` = batch page; Deep Dive shows the memo.
- `core/file_parsers.py` — IBKR Activity Statement, Coinbase, Trendlyne, generic table → holdings + cash.
- `core/screenshot_parser.py` — Claude vision for images; PDFs sent as `document` blocks.

## Today's history (all pushed)
v6.7 audit (login KeyError, fresh-DB crash, retired model IDs, stale-holdings cache, per-user settings,
briefings & NAV, real timeouts, dev-mode blank page) → v7.0 GROW engine → v7.0.1/7.0.2 sign-in fixes
(Google button, email login, `name` field, redirect URI) → v7.1 OAuth callback route, broker-file parsers,
PDF fix, data diagnostics. Live-verified: Screen + Standard GROW runs on MSFT.

## v7.2 (5 Sep 2026, same-day follow-up) — user reported 8 bugs after testing v7.1, all addressed, pushed, live
Root-caused via Render production logs + live API testing (Twelve Data, Google userinfo) rather than guessing:
1. **Google sign-in "No access token returned"** — real cause (confirmed in Render logs: "Rejected Google
   login for unverified email"): code checked `email_verified`, but Google's `oauth2/v2/userinfo` REST endpoint
   returns `verified_email` (`email_verified` only exists on the OIDC endpoint / ID token). Every real login was
   being rejected. Fixed in `core/auth.py` + `pages/99_OAuth_Callback.py`; callback error message is now specific
   (token/userinfo/email/verification) instead of always the same generic string.
2. **Cash & margin currency mismatch** — `cash_positions.amount` was being summed across currencies as raw
   numbers with no FX conversion (IBKR alone can report AED/CHF/EUR/JPY/SGD/USD balances on one account — see
   `core/file_parsers.py parse_ibkr_statement` Forex Balances parsing, which is itself correct). Added
   `core/currency_normalizer.py: cash_positions_to_base_currency() / total_cash_in_base_currency()`; used in
   `00_Command_Center.py`, `2_Portfolio_Dashboard.py`, `18_Risk_Strategy.py`. Margin rates: replaced the stale
   March-2026 flat-per-currency IBKR table with the live per-currency tier ladders (effective 2026-08-26, pulled
   from interactivebrokers.com) in `core/fortress.py`, and fixed `get_margin_rate()` silently overwriting every
   non-USD rate with the USD tier ladder.
3. **Missing prices / "some Indian tickers and funds un-fetched"** — Twelve Data's FREE tier does NOT cover
   India (NSE/BSE) or OTC fund quotes at all — confirmed live: `quote?symbol=RELIANCE:NSE` → 404 "available
   starting with the Grow or Venture plan". This is a plan limitation, not fixable in code without an upgrade.
   Added a general (previously UAE-only) Twelve Data fallback in `core/cio_engine.py _fetch_one_quote` with
   plan-restriction caching in `core/twelve_data_client.py` (`_plan_restricted_exchanges`) so this 404 is learned
   once per exchange and every other ticker on it fails instantly instead of repeating the rate-limited call —
   this was actively making page loads slower before the fix. If the Twelve Data plan is ever upgraded, India
   pricing starts working with zero further code changes.
4. **Funds not identified / value not accurate** — root cause had two parts: (a) Trendlyne exports put a
   Morningstar fund ID (e.g. "F0GBR06R8K") in the NSEcode column for actual mutual funds, and a numeric-only
   BSE code in the NSEcode column for BSE-only stocks (e.g. Exhicon Events) — both were turned into bogus
   ".NS" tickers no source can ever price. Fixed in `core/file_parsers.py parse_trendlyne`. (b) `holdings` had
   no DB columns for `asset_category` / `last_known_price` at all — the IBKR parser already captured
   `asset_category="Mutual Funds"` for things like the Franklin Templeton offshore fund "FTIFWAU LX", but
   `save_holdings()` silently dropped it before it ever reached the database. Added both columns (migration in
   `core/database.py init_db()`, additive/safe, already applied to production Turso — confirmed live in Render
   logs, no startup errors). `core/cio_engine.py enrich_portfolio()` now falls back to `last_known_price`
   (IBKR's own "Close Price" / Trendlyne's own "Current Price") when every live source fails, and skips live
   fetch entirely for synthetic `"MF:..."` tickers. `resolve_sector()` (`core/data_engine.py`) and
   `pages/4_Portfolio_Summary.py`'s local `_resolve_sector`/`_resolve_industry` now check `asset_category`
   (ground truth from the broker file) before falling back to a live `quoteType` lookup that only works when a
   ticker actually resolves. FTIFWAU LX ≠ FKINX — different Franklin Income Fund share classes, different NAV,
   do not conflate (TICKER_OVERRIDES entry for FTIFWAU LX points at Twelve Data's own "0P0001ADNT", confirmed
   via ISIN LU1586275312 symbol_search — also plan-gated today, same as #3).
5. **Page loading "takes ages"** — `pages/16_Portfolio_Rebalance.py` was calling `enrich_portfolio(holdings)` on
   every visit with NO session-cache check (unlike every other page) AND no `base_currency` argument at all,
   meaning it always silently priced in USD regardless of the user's actual setting. Fixed to reuse the shared
   `enriched_cache_key` pattern. Remaining likely cause: Render free-tier cold starts (30-60s) — already flagged
   below, needs the paid tier to actually fix, not something a code change can address.
6. **Dividend amount absurdly high** — `dividendRate` from yfinance is per-share in the STOCK'S OWN currency
   (INR for .NS, AED for .AE, etc.), not `base_currency` — was multiplied by share count and summed/labeled as
   base_currency with zero FX conversion (same root pattern as #2). Fixed in `pages/22_Dividend_Dashboard.py`
   using the `fx_rate` column `enrich_portfolio()` already computes per holding.
7. **Peer Comparison crash** (`ValueError: Unknown format code 'f' for object of type 'str'`) — yfinance
   occasionally returns a non-numeric placeholder string for a metric field on thinly-covered tickers; `_safe_get`
   in `pages/23_Peer_Comparison.py` now coerces to float and drops it to `None` on failure (defense added at the
   formatter functions too).
8. **Ask Prosper chat "took ages"** — the full chat page (`pages/24_AI_Chat.py`) blocked with zero visual
   feedback until the ENTIRE reply was generated; now streams via a new `core/settings.py call_claude_stream()` +
   `st.write_stream()`, so the first words appear in ~1s. The floating mini-chat popover in `app.py` had no
   spinner at all during its blocking call — added one. Actual latency may still be dominated by Render free-tier
   cold starts (see below) — streaming/spinners fix the *perceived* freeze, not a literal cold start.

All 19 changed files pass `python -m py_compile`; migration + parser logic smoke-tested against the real Sep-2026
`Portfolio Info/` exports and a local SQLite copy (see session transcript). Could NOT locally exercise the live
`enrich_portfolio()` price-fetch path end-to-end — `yfinance` segfaults for ANY ticker (even bare "AAPL") in this
machine's `venv` (Python 3.14) independent of any of these changes; isolated the new MF-skip/last_known_price
logic by mocking the quote-fetch layer instead. Production runs Python 3.12 in Docker, a different environment —
worth a real click-through on the deployed app to confirm, especially Google sign-in (needs a real Google account)
and a Portfolio Dashboard/Command Center load to see actual cash/dividend/margin numbers with the new FX math.

## Open items / next steps
1. ~~User to re-test Google sign-in after v7.1 deploy~~ — root cause found and fixed in v7.2 (see above);
   user should re-test.
2. Holdings on production: `PROSPER_CLAIM_LEGACY` moved only 13 rows — production Turso never held the 116
   April holdings (they are only in the stale local DB). Plan: re-import from `Portfolio Info/` via Upload Portal
   (IBKR PS + AS, Coinbase, Trendlyne; Fidelity PDFs via AI). Settings → Diagnostics shows who owns what.
3. Twelve Data free tier does not cover India (NSE/BSE) or OTC fund quotes — confirmed live, needs a paid
   Twelve Data plan (Grow/Venture) to actually fix; the code is ready and will work immediately on upgrade
   (see v7.2 §3/§4 above). Until then, Indian mutual funds and the offshore Franklin fund price from their
   broker-statement-reported last known price, not a live quote.
4. Full GROW tier not yet live-tested. Batch cost guide: screen ≈ $0.10/name, standard ≈ $1.20/name.
5. Optimisation ideas: Render paid instance ($7) to kill cold starts (still the most likely cause of any
   remaining "slow page load" complaints); multi-portfolio per IBKR account (AS vs PS); Fidelity 401k as a
   separate "retirement" portfolio; net-worth summary CSV → cash/other assets; Full-tier verification;
   verifier (`grow/grow_verify.py`) in CI.
6. Never map old PROSPER verdicts onto GROW (rule 22); every verdict shown must carry Durability + Entry arithmetic
   (rule 20); positions are never sent to the engine (rule 13).
