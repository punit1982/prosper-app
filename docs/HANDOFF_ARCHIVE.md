# Prosper — handoff archive (session history, v7.2 → v7.17)

This is the accreted, version-by-version history that used to live at the top of HANDOFF.md.
It is kept for archaeology — *why* a given line of code looks the way it does. The current
state of the project, and everything a new session actually needs, is in `HANDOFF.md`.

---

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

- **v7.11 / v7.12 (reliability audit fixes — all implemented)**:
  - **FX** (`core/currency_normalizer.py`): AED/SAR/HKD hard pegs (AED 3.6725) resolve with zero network
    calls. New fallback chain when yfinance FX fails: `open.er-api.com` (free, keyless) → stale DB cache
    of ANY age (`get_fx_rate_cache(..., max_age=float('inf'))`) → `_STATIC_USD_RATES` hand table →
    (impossible last resort) 1.0 logged as ERROR. The silent-1.0 misvaluation bug is closed.
  - **Fundamentals fallback**: `_yf_fetch_info` treats yfinance `.info` as usable only if ≥2 real
    fields present; else (US only — `.`/`:`-free symbol) tries `core/fmp_client.py` (`/stable`
    key-metrics-ttm + ratios, US-only on this key) then `core/finnhub_client.basic_financials`
    (`/stock/metric`, normalised to yfinance's fraction / ×100 unit conventions). Non-US suffixed
    tickers skip both (no coverage) — India (`.NS`/`.BO`) still has no fundamentals fallback beyond
    yfinance; accepted.
  - **UAE routing FIXED** (this was the "UAE scrips have no financials" complaint — the *source* was
    always fine, the *routing* keyed on a literal `.AE`/`.AD` suffix): `core/adx_client.is_uae_symbol()`
    + `_normalise_uae_symbol()` + `_MUBASHER_SLUG_OVERRIDES` now recognise every stored form
    (`ADCB` / `ADCB.AE` / `ADCB.AD` / `ADCB:DFM` / a known ADX slug) and map slugs
    (`EMIRATESN`→`EMIRATESNBD`, `PUREHEALT`→`PUREHEALTH`, …). Verified live: Mubasher returns
    marketCap/PE/PB/EPS/BVPS for ADCB, ALDAR, ADNOCLS, PUREHEALT, SPACE42, BURJEEL, EMAAR, EMAARDEV,
    TECOM, EMIRATESNBD.
  - **Turso** (`core/db_connector.py`): module-level pooled `requests.Session` + `urllib3 Retry`
    (keep-alive, backoff on connection errors / 5xx) replaces per-query `requests.post`;
    `_send_pipeline` adds a 3× retry loop.
  - **Claude** (`core/settings.py`): `call_claude` / `call_claude_stream` retry 429/500/502/503/529
    (1.5s→3s backoff) + explicit `timeout`; new `CLAUDE_AUTO_FALLBACK = [sonnet, haiku]` — **Opus is
    OUT of the automatic 404 ladder** (still first when a caller passes `preferred_model="claude-opus-5"`,
    e.g. GROW full). `screenshot_parser` uses the same sonnet→haiku ladder. GROW engine unaffected
    (calls the client directly with its own `timeout=900`).
  - **Config/security**: `render.yaml` region → singapore, added `TWELVE_DATA_API_KEY` +
    `SERPER_API_KEY`; OAuth callback no longer falls back to a public `"dev-placeholder"` cookie key
    in prod (`st.stop()` instead); `requirements.txt` pins `anthropic==0.125.0`, `yfinance==1.7.0`.
  - **Perf/cost**: 7+ digit numeric scrip codes (`17041163.NS`) skip yfinance entirely; Ask Prosper
    chat system prompt is a `cache_control` block (`core.settings.cached_system`); `get_ticker_info_batch`
    10→6 workers.
  - **Automation**: `scripts/prewarm.py` warms Turso fundamentals/price/FX caches; schedule via the
    workflow in `docs/prewarm-github-action.yml` (add to `.github/workflows/` manually + set repo
    secrets — the push token used in these sessions lacks `workflow` scope).
  - **NOT done, deliberately**: GROW framework 1-hour cache TTL (audit #13 — marginal, needs a beta
    header, risk not worth it); folding the remaining research pages into the hub (UX Step 6 tail).

- **v7.13 (6 Sep 2026) — UAE prices fixed + three mis-mapped tickers**: the Mubasher price path was
  gated on `is_adx_ticker()` (exact match against a 7-entry static chart-ID map) in BOTH
  `cio_engine._fetch_one_quote` and `data_engine.resolve_ticker` — v7.11 introduced the broader
  `is_uae_symbol()` but wired it only into fundamentals. ALDAR/BURJEEL/PUREHEALTH therefore never
  reached Mubasher, and `resolve_ticker` then rewrote them via Twelve Data into `X:DFM`/`X:ADX`, a
  form Mubasher cannot match and Twelve Data's plan will not quote. **That bad resolution was cached
  24h in `ticker_cache`, and `resolve_tickers_batch` reads the cache BEFORE calling `resolve_ticker`**
  — so the fast-path was never reached and the failure re-armed on every refresh, which is why the
  four tickers that ARE in the static map also failed in production while working in isolation.
  Fixes: `is_uae_symbol()` on the price/resolve/history paths; a UAE pin in `resolve_tickers_batch`
  ahead of the cache read (self-heals poisoned rows); chart-ID discovery across BOTH ADX and DFM
  market paths with `_MUBASHER_SLUG_OVERRIDES`; day change now measured against the previous
  **session** close from the daily history CSV (it used the previous intraday **bar**, so every UAE
  holding read 0.00% every day). New **keyless Yahoo `chart` fallback** in `_fetch_one_quote` between
  yfinance and Finnhub — the reliability audit confirmed `chart` works unauthenticated while
  `quoteSummary`/v7 `quote` return "Invalid Crumb"; verified it prices PRY.MI / 543895.BO / AAPL /
  D05.SI / NESN.SW with yfinance fully stubbed, which closes the Yahoo-single-point-of-failure
  finding for prices. Ticker corrections, each verified live: `PRYM.MI` → `PRY.MI` (IBKR writes
  Prysmian as "PRYm" — the trailing lowercase letter is a share-class marker, **the real symbol and
  exchange are in the statement's own "Financial Instrument Information" section: PRY / BVME /
  IT0004176001**; PRY.MI quoted EUR 122.25 against a 119.80 prior close, both matching the
  statement's marks); `17041163.NS` → `543895.BO` (Exhicon Events Media, a BSE-only SME —
  `parse_trendlyne` already prefers BSEcode for numeric NSEcodes, so this only rescues pre-fix rows;
  **note Yahoo's live 258.55 vs Trendlyne's 469.85 — a corporate action, confirm the share count
  before trusting the value**). New `cio_engine.NO_LIVE_SOURCE` registry routes OZON (Nasdaq listing
  suspended, IBKR carries it on its internal "VALUE" exchange), ISPATALLOY.NS (Balasore Alloys —
  no data on Yahoo for NSE or BSE, and Trendlyne's own export reports a blank Day Change %) and
  legacy `F0…​.NS` Morningstar fund rows straight to `last_known_price`. Portfolio Dashboard now
  separates "couldn't fetch a price" (actionable) from "no market quote exists and none is expected".

- **v7.14 (6 Sep 2026) — mobile design system**: measured first on a real 375×812 viewport against the
  owner's 182-holding portfolio (see the preview-harness note below). Before: Command Center 3,677px =
  4.5 screens with the first portfolio number **526px** down; Portfolio Dashboard's holdings table
  showed **3 of its 12 columns**; **54 tap targets under 44px**. Root cause is layout arithmetic, not
  styling — `st.columns()` stacks below ~640px with no per-row opt-out, and `st.dataframe` is a
  fixed-height widget with its own horizontal AND vertical scrollbars. New in `core/ui_components.py`:
  `mobile_shell()` (stylesheet: block padding, 44px tap targets, hides Plotly's modebar, fades
  scrollable tab strips), `page_header()`, `hero_metric()`, `stat_grid()` (**the core fix** — a CSS
  grid that stays a row at 375px), `row_list()` / `responsive_holdings()` (card rows on phones, the
  full sortable dataframe on desktop, swapped by CSS `:has()` alone since Streamlit cannot read the
  viewport), `holdings_rows()`, `fmt_compact()`. Applied to Command Center + Portfolio Dashboard:
  first number 526px → 118px, 4.5 → 3.9 screens, ~4 → ~15 positions per screen. **Bound the card list
  (25 largest by value + an explicit "show all")** — the first cut rendered all 182 and made the
  Dashboard 12.8 screens, worse than the scroll-box it replaced. Two bugs found only by running it:
  Command Center alerts rendered literal `**ADBE**` (Markdown authored text injected into
  `unsafe_allow_html`, which Streamlit does not parse — regressed in v7.8), and the new per-tab
  "show all" checkbox raised `StreamlitDuplicateElementKey` because `_render_currency_section` runs
  once per country tab. Desktop verified unchanged at 1280px. Design review + page-by-page plan:
  https://claude.ai/code/artifact/fe1423f6-44eb-4103-909f-4c4e495fafc7
  **Not done**: Plotly charts are still unusable at 375px (clipped axis labels, 4–6px treemap text,
  allocation bars spending 40% of width on labels); the 24-page sidebar wants a 4-item bottom bar;
  Equity Deep Dive, Risk & Strategy and Portfolio Summary are the P1 pages still unconverted.

## Seeing the signed-in app at phone width (the missing test class)
Earlier sessions could not click through the signed-in pages and said so. This is how it was done on
6 Sep 2026, with **no credentials and no repo changes**: `rsync` the repo to a scratch dir (excluding
`venv/.git/__pycache__`); in the COPY's `app.py` force `st.session_state["authentication_status"]=True`
+ `user_id`, no-op `run_auth`, and short-circuit the onboarding gate (bypass auth — never create an
account or type a password to do this); seed the scratch SQLite by running `parse_ibkr_statement` /
`parse_trendlyne` over the real files in `Portfolio Info/` and `save_holdings()`; **pre-warm
`save_price_cache()` and `save_ticker_info_cache({t: {} …})` offline first**, or the first load runs
past two minutes and you never see the UI; run with `PYTHONPATH=<scratch>/stub` holding a stub
`yfinance.py` (this machine's Python 3.14 segfaults on any real yfinance call — the new Yahoo `chart`
fallback covers everything, so the app still runs live). Streamlit's watcher does **not** pick up edits
here (no watchdog) — restart on a new port and clear `__pycache__` after every change. Measure with JS
against `[data-testid="stMain"]`, **not** `document.documentElement`: Streamlit scrolls an inner
container, so the document's own `scrollHeight` is always just the viewport height.

- **v7.15 (6 Sep 2026) — UAE prices: the real root cause + workarounds**: `adx_client.get_quote()`
  is correct and prices every UAE name in local testing — but **Mubasher is behind Cloudflare and
  returns 403 to datacenter IPs**, so the scrape fails on Render. Every prior "verified live against
  Mubasher" was run from a residential IP. Twelve Data's "Basic" plan does NOT cover ADX/DFM either
  ("available starting with Pro or Venture"). So there is **no free UAE price source reachable from
  Render.** Workarounds shipped: (1) `ibkr_client.parse_positions` now persists IBKR Flex `markPrice`
  → `last_known_price` (was parsed and dropped); `ibkr_sync` merge path + `database.update_holding`
  pass it through. (2) `screenshot_parser` prompt now captures the per-share current-price column →
  `last_known_price`. (3) `cio_engine._fetch_one_quote` serves the newest `price_cache` row for a UAE
  symbol whose live scrape failed, without the 30-min cooldown. (4) `scripts/prewarm.py` fetches all
  UAE quotes via `adx_client` and writes `price_cache` — it runs on a **GitHub Actions runner**, whose
  Azure IPs Cloudflare does not block like Render's. (5) Portfolio Dashboard shows UAE-specific
  unpriced copy ("ticker is fine; Mubasher blocks cloud servers; run IBKR Sync") instead of the
  misleading "wrong suffix" message. **What the user must do for existing holdings:** run IBKR Sync
  or re-upload the account so `last_known_price` is populated (nothing back-fills it). **Proper
  long-term fix:** IBKR Client Portal / OAuth1.0a integration — IBKR covers ADX/DFM natively and is
  datacenter-friendly; the app already has Flex-Query plumbing in `core/ibkr_client.py`.
  Also: `ISPATALLOY.NS/.BO` → `BALASORE.NS/.BO` (correct NSE symbol for Balasore Alloys) in
  `TICKER_OVERRIDES`; `NO_LIVE_SOURCE` message softened.

- **v7.16 (6 Sep 2026) — mobile redesign across every page**: executes the page-by-page plan from the
  v7.14 design review. All 24 pages loaded at 375×812 against the real 182-holding portfolio; none
  raises a traceback. Two changes carry most of the benefit:
  (1) **`mobile_shell()` is now called once globally in `app.py`**, before the nav — so pages never
  individually converted (Settings, Upload Portal, IBKR Sync, Users, News) still get 44px tap targets,
  reclaimed padding, hidden Plotly modebars and faded tab strips. (2) **`show_chart()` / `mobile_chart()`
  replaces all 39 `st.plotly_chart` calls.** Streamlit cannot read the viewport, so every fix is
  width-independent rather than a phone branch: `automargin` (axis labels were clipped to `00 (-4.7%)`),
  `uniformtext` minsize 9 (the treemap was drawing 4–6px text — now hidden rather than illegible),
  horizontal legends, horizontal pie slice labels (thin slices printed sideways off the edge), modebar off.
  **`st.metric` is now gone from every page** (was 78) — replaced by `hero_metric` + `stat_grid`.
  Biggest conversions: Equity Deep Dive (19 metrics / 6 clusters; the 4-up price header is now a hero +
  3-grid + full-width 52-week bar, signal cards are one CSS grid), Risk & Strategy (5-up regime chips →
  wrapping chip row, 4-up action cards → grid, **4 allocation pies in `st.columns(4)` → tabs** so each
  gets full width), Portfolio Summary (11 metrics; the `st.columns(5)` risk block → two grids),
  Peer Comparison / Technical Analysis / Dividend Dashboard / Transaction Log / Earnings Calendar
  (`st.columns(4-6)` → hero + grid). Wide tables → `render_responsive_table` on Summary, Deep Dive (5),
  Risk (2), Rebalance (2), Transaction Log (2). **New `bottom_nav()`**: fixed 5-item bar (Home /
  Portfolio / Research / Risk / Ask), phones only, plain anchors because a fixed bar must be ONE element
  and Streamlit wraps every widget in its own container. Page headers unified on `page_header()` across
  all 24 pages. Desktop verified unchanged at 1280px.
  **Three bugs found by running it, not reading it:**
  · `render_responsive_table`'s mobile card used `var(--secondary-background-color,#f6f6f6)`; **Streamlit
  1.41 does not define that property**, so the light fallback won and every card rendered a light panel
  under light-on-dark text — invisible. Shipped broken in v7.10 (Peer Comparison, Dividend Dashboard).
  Now theme-neutral translucent greys. **Rule: never rely on a Streamlit CSS custom property; use
  `rgba(128,128,128,α)` and `color:inherit`, which read correctly on either ground.**
  · `bottom_nav()` was first rendered after `pg.run()`. **21 of the 24 pages call `st.stop()`**, which
  halts the whole script — so the bar vanished on exactly the empty-state pages where a way out matters
  most. Moved before `pg.run()` (it is `position:fixed`, so DOM order is free). **The floating chat
  widget has the same pre-existing defect and was left alone — it branches on `pg.title`.**
  · Rebalance's suggestion table was being handed the Styler's raw numeric frame (unformatted floats);
  `render_responsive_table` does no formatting by design, so the display frame is now built explicitly.

- **v7.17 (6 Sep 2026) — four reported issues**:
  1. **Local currency.** Per-share figures hard-coded `USD`/`$`, so a Tokyo listing read "USD 6731.0"
     — a ~150x misstatement, not a formatting nit. New
     `core/currency_normalizer.instrument_currency(ticker, info)`: quote source's own `currency`
     field first (**the only thing that gets `U03A.L` right — an `.L` suffix that trades in USD**),
     then exchange suffix, then stored value. Applied to Equity Deep Dive (price, div/share, mean
     target + range, SMA levels, avg cost), Peer Comparison (hero + the per-row Price column, which
     can span exchanges) and Earnings Calendar EPS. **Portfolio-level totals deliberately keep the
     base currency** — market_value is already FX-converted by `enrich_portfolio`; only per-share
     numbers take the instrument's currency. Transaction Log now names the base currency instead of "$".
  2. **IBKR-style tappable rows.** `ui_components.position_rows()` — two lines per holding, identity
     left / figures hard-right (ticker · last price + day %, then name · market value + unrealised
     P&L %), colour-coded, ~10 per screen. Each row is a real `st.button`, and tapping it opens
     Equity Deep Dive on that holding via `open_deep_dive()`, which seeds the picker's session key
     `dd_ticker_select`. **The trick that makes it look like a table: Streamlit runs a button label
     through its full markdown pipeline** — `\n\n` gives two `<p>`, `:green[…]` gives `<span>`, so
     writing each line as exactly two markdown nodes lets `justify-content:space-between` produce the
     left/right split. Deep Dive gained a **Peers** tab (peers drawn from the user's own holdings in
     the same sector), so Analyst / Sentiment / Technical / Peers are one screen per name.
  3. **Daily IBKR price backfill** (`core/ibkr_prices.py`). Pulls IBKR's own `markPrice` for every
     position on the first run of each calendar day into `price_cache`, covering UAE (ADX/DFM),
     European/offshore funds and suspended lines. **Uses the Flex Query WEB SERVICE (token + query
     id) — the IBKR MCP connector authenticates as the user's own Claude connector and can never be
     called by the deployed app.** Widened past `parse_positions`' STK-only filter to
     FUND/ETF/BOND — that filter is what was dropping the European funds. Never overwrites a live
     quote (an IBKR mark is a previous close); **stamps the date BEFORE the fetch** so a Flex timeout
     cannot re-trigger on every rerun for the rest of the day (IBKR rate-limits report generation
     hard). Dashboard states whether it is configured.
  4. **Bottom tabs did nothing.** They were plain `<a href>` anchors — a real navigation that reloads
     the app, builds a NEW Streamlit session and destroys the price cache and active portfolio.
     Replaced with `st.page_link` (client-side, session preserved; verified by clicking through with
     prices still cached). A fixed bar cannot be one element when Streamlit wraps every widget, so a
     marker is emitted and CSS pins the FOLLOWING horizontal block and forces it back to 5-across.
  **Gotcha repeated from v7.16, worth internalising:** `st.markdown("<div class=…>")` never wraps the
  widgets that follow it — Streamlit closes every element it opens. Scope CSS off a marker element's
  following siblings (`:has(.marker) ~ …`), which is what `position_rows`, `mobile_only_start/end`
  and `bottom_nav` all now do.

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
