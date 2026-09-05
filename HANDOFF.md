# Prosper — Handoff (5 Sep 2026, updated post-v7.10 + reliability audit)

Paste this into a new chat to continue. Everything below is verified unless marked otherwise.

## What Prosper is
Streamlit + Python investment operating system for one family's multi-broker portfolio (IBKR ×2 accounts,
Coinbase, India via Trendlyne, Fidelity 401k/DCP/RSUs/NIQ stock). Owner: Punit Singh (non-programmer, product
lead, email punit_singh@outlook.com). Repo: https://github.com/punit1982/prosper-app (branch `main`, this
folder). Production: Render free tier (Docker, Python 3.12, Turso cloud SQLite), auto-deploys on every push to
`main`, URL https://prosper-gzlf.onrender.com, service id `srv-d70gqpuuk2gs739abg7g`, workspace
`tea-d70gmplm5p6s73asj1hg` (user has granted full Render access via the Render MCP connector). Free tier spins
down when idle → 30–60s cold starts and a "stale sidebar flash" on the first request — this is an infra
limitation, not a code bug, and shows up repeatedly in user reports as "slow reload."

## Local machine
- Folder: `…/AA-Investments /GROW Operating System/prosper/` (iCloud). Sibling folders: `New GROW Prompts/`
  (source of the GROW framework files — check here for any future GROW methodology revisions), `Portfolio Info/`
  (latest broker exports, Sep 2026).
- `venv/` = Python 3.14 with the **exact production pins** (streamlit 1.41.1, streamlit-authenticator 0.3.3,
  yfinance 1.7.0 — confirmed latest published release, anthropic SDK for claude-sonnet-5/claude-opus-5/
  claude-haiku-4-5). Run the app: `./run.sh`. `.env` holds real API keys (git-ignored): ANTHROPIC, FMP,
  FINNHUB, TWELVE_DATA, SERPER. Google OAuth + Turso creds exist only on Render.
- Old folder `~/Documents/Prosper with Claude March 2026/` (py3.9 venv) is legacy — don't use.
- `yfinance` segfaults locally for ANY ticker in this machine's venv (Python 3.14), independent of app code —
  production runs Python 3.12 in Docker and does not have this problem. Test data-fetch logic against
  production logs / live curl instead of relying on local yfinance calls.

## Architecture (key files)
- `app.py` — page config, sidebar-hide CSS, auth gate, `ensure_settings_loaded()`, `st.navigation`, NAV
  snapshot, floating "Ask Prosper" chat popover (hidden on the full Ask Prosper page itself; uses the app's own
  accent color `#0984e3`/`#0a6bb3`, not a generic purple gradient).
- `core/auth.py` + `pages/99_OAuth_Callback.py` — Google OAuth popup flow. Checks `verified_email` (Google's
  REST userinfo field), not `email_verified` (only exists on the OIDC/ID-token path). Popup close fallback
  button renders in a properly-sized `st.components.v1.html(..., height=180)` iframe (NOT height=0 — that was
  a real bug, invisible-but-present button, fixed in v7.5).
- `core/settings.py` — per-session `SETTINGS` proxy, Claude model IDs (`claude-sonnet-5` default,
  `claude-opus-5` best, `claude-haiku-4-5` fast), `call_claude`/`call_claude_stream` — both default
  `thinking={"type":"disabled"}` via `.setdefault()` unless the caller explicitly opts in (GROW engine does,
  per-tier) — **critical**: `claude-opus-5` has extended thinking ON by default and it consumes real
  `max_tokens` budget, so an unprotected Opus fallback (e.g. from a transient Sonnet error) can return empty
  text with `stop_reason="max_tokens"`.
- `core/database.py` — SQLite/Turso via `core/db_connector.py`; multi-tenant `user_id` scoping; migrations in
  `init_db()` (additive `ALTER TABLE` in try/except, following the `_GROW_ANALYSIS_COLUMNS` pattern);
  `ticker_info_cache` table (persists yfinance `.info` results — including failures — across Render
  restarts, critical for cold-start speed); `save_holdings()` DELETE-before-insert is scoped by
  `(ticker, broker_source)` so re-uploading one account never wipes another account's same-ticker position;
  a SECOND, broader delete scoped by `(broker_source, asset_category IN ('Restricted Stock',
  'Retirement Account'))` runs first for those two categories specifically, because their tickers are
  AI-generated fresh each parse and can drift between uploads.
- `core/cio_engine.py` + `core/data_engine.py` + `core/currency_normalizer.py` — prices/fundamentals waterfall
  (UAE `.AE`/`.AD` tickers → `core/adx_client.py get_fundamentals()` [Mubasher scrape] first → Twelve Data →
  yfinance → Finnhub), FX, news (region-appropriate Google News edition + company name in the query, not just
  the bare ticker), fundamentals. All parallel fetches go through `core/parallel.py`: `gather()` (bounded
  parallel with an OUTER deadline that only bounds how long the CALLER waits for already-completed futures —
  does NOT cap how long one call occupies its worker slot) and `run_with_timeout()` (a real per-call hard
  timeout via nested ThreadPoolExecutor — used to wrap the actual yfinance calls in `_yf_fetch_info` and
  `_fetch_one_quote`, 6s each, after a real production incident where slow-failing yfinance calls serialized
  into a 5+ minute hang with only 4 workers).
- `core/adx_client.py` — `get_fundamentals(ticker)`: scrapes english.mubasher.info stock pages (static HTML,
  no auth) for Market Cap/P/E/P/B/EPS/Book Value, tries both ADX and DFM market paths, 6h cache. Does not cover
  every yfinance `.info` field (no sector/beta/dividend yield/52-week range) — only what Mubasher itself
  reports.
- `core/grow_engine.py` — **GROW v5.1 is the analysis engine** (PROSPER v3.0 retired). Framework text lives in
  `grow/` (CORE.md + Annexes A/B/C/E, D is review-only) sent as a cached system block. Tiers: screen (Sonnet 5,
  thinking off), standard (Sonnet 5 + web_search/web_fetch), full (Opus 5). Deterministic §8 resolver
  `resolve_entry()` recomputes the Entry verdict + 5-rung price ladder + ±25% stability stress from the
  model's own JSON inputs, OVERRIDING the model's own arithmetic if it disagrees — this is by design (§8 is
  arithmetic, not judgment) but means `resolve_entry()` must be kept in exact sync with whatever CORE.md's
  formula currently says, or it will silently replace correct new-methodology numbers with stale ones (this
  happened and was caught proactively — see v7.7 below). `core/grow_render.py` renders (falls back to the old
  4-rung ladder text for analyses saved before the 5-rung update); `pages/15_GROW_Analysis.py` = batch page.
  `grow/grow_verify.py` is a standalone self-consistency verifier (not imported by the live app) — run it after
  ANY change to `grow/*.md`: `venv/bin/python3 grow/grow_verify.py "grow/GROW v5 1 CORE 04Sep2026.md"`, expect
  `RESULT: ALL CHECKS PASS`.
- `core/file_parsers.py` — IBKR Activity Statement, Coinbase, Trendlyne, generic table → holdings + cash.
- `core/screenshot_parser.py` — Claude vision for images/PDFs; restricted stock/retirement rows get an AI-built
  deterministic `broker_source` (e.g. "Fidelity Stock Plan — NIQ") for consistent re-upload tagging — **only
  if the Upload Portal's Broker dropdown is left on "Auto-detect"** for these files; a manual dropdown
  selection overrides every row's broker_source uniformly and would collapse NIQ/401(k)/DCP into one tag.
- `core/ui_components.py` — shared `status_chip(label, level)` (critical/warn/good/neutral — one consistent
  color+shape for "fine/watch/act now" across the whole app, replacing a different ad hoc emoji vocabulary per
  page) and `fmt_age(secs)` (human "X ago" string, shared so every freshness caption reads the same way).
  Currently used in: Dividend Dashboard, Portfolio Dashboard (cash positions + alerts), Command Center
  (alerts), Risk Strategy (cash & margin). NOT yet applied to: Technical Analysis, Sentiment, Analyst
  Consensus, Earnings Calendar, Upload Portal (all still have their own 🔴/🟡/🟢 patterns — lower priority,
  those are directional buy/sell signals more than the "same three severity states" problem the audit flagged,
  but worth sweeping eventually for full consistency).

## Session history (chronological, all pushed + confirmed live via Render MCP unless noted)
- **v6.x → v7.0**: GROW v5.1 engine replaces PROSPER v3.0; OAuth/parser/PDF fixes.
- **v7.2**: 8 user-reported bugs (Google sign-in field-name bug, cash/FX mismatch, Twelve Data India/fund
  plan-gating discovered, Trendlyne fund-ID parsing, Rebalance page missing cache, dividend FX, Peer Comparison
  crash, Ask Prosper streaming).
- **v7.3**: second cash-FX occurrence (Grand Total hero card), multi-account upload data-loss (DELETE not
  scoped by broker_source), sentiment "news" hardcoded has_data=True skewing composite scores neutral,
  restricted/unvested holdings introduced as a category, missing company names for numeric scrip codes
  (Japan/Singapore), Google OAuth popup close behavior, Ask Prosper nav-stuck (two independent chat widgets on
  one page), CIO Briefing hallucinated tickers.
- **v7.4**: root-caused yfinance `.info` failing for ~every ticker (Yahoo API-side, not a coverage gap);
  `ticker_info_cache` DB table added so the failing sweep persists across Render cold-start restarts instead
  of re-running from scratch on every login.
- **v7.5**: the actual 5+ minute Portfolio Dashboard hang (see `core/parallel.py` note above — `gather()`'s
  outer timeout doesn't bound a single call's worker-slot time); Claude Opus thinking-token empty-response bug
  (see `core/settings.py` note above); invisible OAuth popup fallback button (`height=0` → `height=180`);
  sentiment `company_name` parameter was dead code, now actually threaded through + regional Google News
  editions; UX batch one (chat button recolor, Dividend Dashboard `status_chip`).
- **v7.6**: UAE fundamentals via Mubasher scraping (`core/adx_client.py get_fundamentals()`), verified live
  against real holdings (ADCB, EMAAR, ALDAR, PUREHEALT, SPACE42); restricted-holdings re-upload duplication
  fixed (category-scoped delete, see `core/database.py` note above) + AI-generated deterministic
  `broker_source` tags.
- **v7.7**: GROW framework synced to CORE.md Revision 2 (05-Sep-2026, sourced from `New GROW Prompts/`) —
  new CAGR formula (`destination = central + cash_returned`), 5th price-ladder rung ("Acceptable below",
  gated on a supplied `base_cost_of_equity`). `resolve_entry()`/`run_grow()`/`database.py`/`grow_render.py`
  updated to match. **Important, still true today**: Annex E's archetype premium/required-return table
  (`grow/GROW v5 1 ANNEX E ARCHETYPE LOOKUPS.md`) is a **mechanical linear rescale of the old pre-compression
  values**, NOT a real calibration — explicitly labeled as a placeholder in the file itself, per the user's
  own choice (they were asked, via AskUserQuestion, whether to invent calibrated numbers, wait, or apply a
  mechanical rescale as a stopgap; they chose the rescale). `grow_verify.py` passes cleanly against this
  placeholder table, but if the user ever provides real per-archetype calibration, it should replace these
  numbers — do not treat them as final. Also: CORE's own rule says v5.0-and-earlier Entry verdicts are not
  convertible to this scale; the same likely applies across this Revision-2 change too, so any GROW analysis
  saved before 2026-09-05 should be treated as run under a different methodology, not directly comparable to
  new runs.
- **v7.8 / v7.9 (UX audit batches two and three)**: extended `status_chip()` to Command Center's alerts and
  Portfolio Dashboard's/Risk Strategy's cash-position rows; added a "📡 Data as of {age}" freshness caption to
  Command Center (it silently reuses whatever enriched snapshot is cached rather than refetching — no visible
  sign of that before, likely a real contributor to "I thought numbers would be cached" confusion); regrouped
  Portfolio Dashboard's Grand Total metrics into "Net Worth" / "Performance" clusters instead of one flat row
  mixing a point-in-time balance with today-only and since-purchase deltas. Full roadmap and rationale in the
  published audit artifact: https://claude.ai/code/artifact/e520e963-2086-443a-bda5-f29102aa6aa4 (read-only
  design review, no code — the actual fixes are what shipped in v7.5/v7.8/v7.9).

- **v7.10 (UX audit batches 4–6)**: `core/ui_errors.py` — four canonical templates
  (`empty_state` / `fetch_failed` / `fetch_pending` / `unsupported`) plus `unexpected` and
  `safe_message`; real exceptions logged (`prosper.ui` / `prosper.auth`), never shown. Swept every
  raw-`{e}` render: Equity Deep Dive ×6, Command Center briefing, IBKR Sync ×2, Upload Portal,
  User Management ×2, Onboarding, AI Chat, Risk Strategy, OAuth callback, app.py ×2, data_engine
  summaries ×2. `core/ui_components.render_responsive_table()` — CSS-only card-per-row fallback
  below 768px, applied to Peer Comparison + Dividend Dashboard (income + yield). New
  `pages/13_Research_Hub.py` ("Research Hub", first in "Research & AI") — orientation + `page_link`
  nav, "open Equity Deep Dive first"; picks a `st.session_state["research_ticker"]` that seeds
  Technical Analysis + Peer Comparison defaults. Still open from Step 6: the full tab-merge and
  ticker-sync for Analyst Consensus / Sentiment / Equity Deep Dive. Chip sweep of the remaining ad
  hoc 🔴/🟡/🟢 pages (TA, Sentiment, Analyst Consensus, Earnings Calendar, Upload Portal) still not
  done — lowest priority. Deployed live and clean (dep-dae61dh5efls739mqvtg, status live).

## Reliability & Connections audit (5 Sep 2026, report only — no code changed)
Full report: https://claude.ai/code/artifact/f3d24762-2d6f-48d0-8edd-6223b0be5a5d
Live-probed every key/source. **Working:** Anthropic, Finnhub, Serper, Mubasher (ADX/DFM healthy
with the Referer header). **Twelve Data:** works but it's a *paid "basic" plan* (not free as this
doc previously said), and daily usage was 568/800 mid-session — treat as fallback-only behind
Mubasher. **FMP:** legacy `/api/v3/*` endpoints are dead ("no longer supported"); `/stable/*` work
with the same key — but nothing in the code calls FMP any more (yfinance + Finnhub replaced it), so
it's just dead config in Settings + render.yaml. **yfinance/Yahoo:** `chart` works unauthenticated;
`quoteSummary` + v7 `quote` return "Unauthorized / Invalid Crumb" on a raw call (yfinance 1.7's
internal workaround is the only thing keeping fundamentals alive — the v7.4 fragility persists).
Top findings, in fix order: (1) **FX fallback returns `1.0`** on any yfinance FX failure
[`core/currency_normalizer.py:151`] → silently misvalues INR/AED holdings; hard-code the AED peg
3.6725, fall back to stale cache then a static table, never 1.0. (2) **Yahoo is a single point of
failure** for prices+FX+fundamentals+analyst data with no non-Yahoo fundamentals fallback for
US/India → add Finnhub `/stock/metric`. (3) Twelve Data quota. (4) **Turso connector has no
retry + new connection per query** [`core/db_connector.py:214`] — `tenacity` already a dep, unused.
(5) **Memory peaks 423 MB / 512 MB cap** on Render free tier → lower enrich concurrency.
(6) `call_claude` only retries 404, not 429/529; auto Sonnet→Opus fallback = silent cost spike; no
request timeout. (7) `render.yaml` stale (region oregon vs live singapore) + missing
`TWELVE_DATA_API_KEY` / `SERPER_API_KEY`. (8) no dependency lock; anthropic/yfinance float.
(9) cookie-secret fallback `"dev-placeholder"` [`pages/99_OAuth_Callback.py:69`]. (10) static
lookup maps degrade silently. (11) numeric `.NS` scrip codes reach yfinance. (12) prompt caching
only in GROW — add to chat/briefing. (13) GROW framework 5-min cache TTL net-negative for one-off
runs. Plus: **no scheduled jobs** — a nightly cron to pre-warm `ticker_info_cache` + enriched
snapshot + `fx_rate_cache` would kill the slow-morning load.

## Verification note (important limitation)
This session verified all v7.x changes via: `py_compile` on every touched file, live production Render logs
(`list_logs`/`list_deploys`/`get_deploy` via the Render MCP connector — confirmed each deploy reaches `status:
"live"`), and targeted live tests (forcing the Opus fallback path, scratch-DB round-trips, live curl/browser
checks against Mubasher). **This session did NOT have Punit's login credentials** and could not click through
the actual signed-in Command Center / Portfolio Dashboard / Risk Strategy pages in a browser — the sign-in
page itself was confirmed to render without error, and Render's error-level logs show only expected external
API 404s (yfinance quoteSummary failures for tickers now handled by fallback sources), no Python tracebacks.
**Punit should do a real click-through of Command Center, Portfolio Dashboard, and Risk Strategy** after this
session to visually confirm the new status chips and the "Net Worth"/"Performance" grouping look right and
nothing regressed — this is the one category of testing a non-interactive session structurally cannot do.

## Open items / next steps
1. **GROW Annex E calibration** — replace the mechanical-rescale placeholder premiums with real per-archetype
   judgment whenever the user is ready to do that work (see v7.7 above for the exact formula used as a
   stopgap, and why).
2. **Remaining UI/UX audit roadmap items** (see the artifact link above for full detail/mockups):
   - Steps 4 & 5: **DONE in v7.10** (see session history above).
   - Step 6: **partially done in v7.10** — the Research Hub landing page shipped; still open is the full
     tab-merge (fold Analyst Consensus / Sentiment / Technical Analysis into Equity Deep Dive as sections)
     and wiring `research_ticker` into the 3 pages not yet done (Analyst Consensus, Sentiment, Equity Deep
     Dive itself).
   - Lower-priority: sweep the remaining ad hoc 🔴/🟡/🟢 patterns in Technical Analysis, Sentiment, Analyst
     Consensus, Earnings Calendar, Upload Portal into `status_chip()` for full consistency (these are more
     "directional signal" than "severity state" semantically, so lower value than the ones already fixed).
   - **NEW — reliability audit fixes**: see the "Reliability & Connections audit" section above and the
     linked artifact for the full ranked list. Fix order: FX-fallback / Yahoo-SPOF first.
3. Twelve Data free tier does not cover India (NSE/BSE) or OTC fund quotes — confirmed live in v7.2, needs a
   paid Twelve Data plan (Grow/Venture) to actually fix; code is ready and will work immediately on upgrade.
4. Full GROW tier (Opus 5, ~$4/name) not yet live-tested end-to-end this session.
5. Render free-tier cold starts (30-60s) remain the most likely residual cause of any "slow page load"
   complaints not otherwise explained — a $7/mo paid instance would eliminate this; a code fix can't.
6. Never map old PROSPER-era verdicts onto GROW; every GROW verdict shown must carry Durability + Entry
   arithmetic; positions are never sent to the engine (existing GROW rules, unchanged).
