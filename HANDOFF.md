# Prosper — Handoff (5 Sep 2026)

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

## Open items / next steps
1. User to re-test Google sign-in after v7.1 deploy (redirect URI `https://prosper-gzlf.onrender.com/OAuth_Callback`
   must be in Google Cloud Console).
2. Holdings on production: `PROSPER_CLAIM_LEGACY` moved only 13 rows — production Turso never held the 116
   April holdings (they are only in the stale local DB). Plan: re-import from `Portfolio Info/` via Upload Portal
   (IBKR PS + AS, Coinbase, Trendlyne; Fidelity PDFs via AI). Settings → Diagnostics shows who owns what.
3. Fund "FTIFWAU LX" (Franklin Templeton, Lux) has no Yahoo ticker — map manually or price via Twelve Data.
4. Full GROW tier not yet live-tested. Batch cost guide: screen ≈ $0.10/name, standard ≈ $1.20/name.
5. Optimisation ideas: Render paid instance ($7) to kill cold starts; multi-portfolio per IBKR account
   (AS vs PS); Fidelity 401k as a separate "retirement" portfolio; net-worth summary CSV → cash/other assets;
   Full-tier verification; verifier (`grow/grow_verify.py`) in CI.
6. Never map old PROSPER verdicts onto GROW (rule 22); every verdict shown must carry Durability + Entry arithmetic
   (rule 20); positions are never sent to the engine (rule 13).
