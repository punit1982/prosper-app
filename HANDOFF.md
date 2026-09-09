# Prosper — Handoff (9 Sep 2026, current at v7.38)

Paste this whole file into a new chat to continue. Everything below is verified unless marked
otherwise. Version-by-version history lives in `docs/HANDOFF_ARCHIVE.md` — read that only when you
need to know *why* something looks the way it does.

**Where the work stands.** Phases 1, 2 and six pushes of Phase 3 are shipped and live.
**Phase 3 (mobile) is IN PROGRESS** — **PHASE 3 IS COMPLETE** — 18 pushes live (`695f4f6` … `b40eaf0`). §13 carries
what shipped, what is left, and in what order, through to done.

Phase 3 is being built against a second design review (9 Sep) that audited the 8 Sep proposal
itself and scored it 9/20 technical, 23/40 Nielsen. That review, the token system and eight
screens rendered by the shipped code:
`https://claude.ai/code/artifact/aa161c0b-b317-4b9f-9954-3172536b0dc2`
The original 8 Sep review, kept for the IA argument (24 → 11 destinations, which still stands):
`https://claude.ai/code/artifact/342f6ad4-b305-4fcd-bf10-1d20025220c6`

**The design system is `core/ledger_ui.py`.** Read its module docstring before touching any UI —
it carries the tokens, the contrast table, and the reason the app is still dark.

**THE APP IS LIGHT.** `core/ledger_ui.ACTIVE_THEME` is the single declaration of the ground. It
drives the CSS token pin, the Plotly literals (`c()`, `CHART_SEQUENCE`, `VERDICT_RAMP`,
`DIVERGING`) and — by hand, so keep them in step — `.streamlit/config.toml`. **Change one without
the others and half the app paints on the wrong surface.** The dark palette is still defined and
contrast-verified; switching back is `ACTIVE_THEME = "dark"` plus the four config.toml values.

**Never hard-code a colour in a page again.** Use `ledger_ui.c("up")` for a Plotly literal, a
`--p-*` var in CSS, `verdict()` for a rating word, `CHART_SEQUENCE` for a multi-series chart. The
sweep removed 174 literals; the point was not tidiness, it was that 11 greens and 16 reds made
"up" mean four different things.

**The §11/§12 audits are measured leads, not gospel.** Four of the eleven Phase 2 findings were
wrong on inspection (a "dead" function that was actually called, a "crash" that can't happen, a bad
grep, a non-issue Streamlit already handles) — see the ledger at the top of §11. Verify each Phase
3 finding against the current code before acting on it.

**tests/test_harvest.py is 56/60 on main** — four pre-existing failures
(`test_real_businesses_are_kept`, `test_wrappers_are_skipped` + 2) that predate Phase 3 and are
unrelated to it. `test_market_data.py` is 91/91. Do not treat the harvest suite as a clean
baseline until those four are diagnosed.

**Before you touch anything: `git pull`, then check `list_deploys` via the Render MCP.** Two separate
Claude sessions have worked this repo on the same day and one shipped v7.15 while the other was
mid-flight. Assume you are not alone.

---

## 1. What Prosper is

Streamlit + Python investment operating system for one family's multi-broker portfolio (IBKR ×2,
Coinbase, India via Trendlyne, Fidelity 401k/DCP/RSUs/NIQ stock). ~182 live holdings across 10
currencies.

Owner: **Punit Singh** — product lead, **not a programmer**. Explain in plain English before writing
code. He reads on a phone a lot; mobile is a first-class surface, not an afterthought.

- Repo: `https://github.com/punit1982/prosper-app`, branch `main`, this folder.
- Production: Render, Docker, Python 3.12, Turso cloud SQLite. Auto-deploys on every push to `main`.
  - URL `https://prosper-gzlf.onrender.com`
  - service `srv-d70gqpuuk2gs739abg7g`, workspace `tea-d70gmplm5p6s73asj1hg`
  - Render MCP access granted. `list_logs` needs the `workspaceId` passed explicitly.
- **Free tier**: spins down when idle → 30–60s cold starts. This is infrastructure, not a bug, and it
  is the residual cause of most "slow page" complaints. $7/mo fixes it; no code change will.

## 2. Working on it locally

- `venv/` = Python 3.14 with production pins (streamlit **1.41.1**, streamlit-authenticator 0.3.3,
  yfinance 1.7.0, anthropic 0.125.0). Run with `./run.sh`.
- `.env` holds ANTHROPIC / FMP / FINNHUB / TWELVE_DATA / SERPER keys. **Google OAuth and Turso creds
  exist only on Render** — you cannot read or write the production database from a local session.
- **`yfinance` segfaults locally for ANY ticker** in this venv (Python 3.14). Pre-existing, unrelated
  to app code, production 3.12 is fine. Stub it (see below) rather than fighting it.
- Old folder `~/Documents/Prosper with Claude March 2026/` is legacy — don't use.
- Sibling folders: `New GROW Prompts/` (source of GROW framework revisions), `Portfolio Info/`
  (real broker exports, Sep 2026).

### The preview harness — how to actually SEE the signed-in app

Every session before 6 Sep said "I couldn't click through the signed-in pages." You can. No
credentials, no repo changes:

1. `rsync` the repo to a scratch dir, excluding `venv/.git/__pycache__`.
2. In the **copy's** `app.py`: force `st.session_state["authentication_status"]=True` plus
   `username`/`user_id`, replace `run_auth` with a no-op, and short-circuit the onboarding gate.
   Bypass auth — never create an account or type a password to do this.
3. Seed the scratch SQLite by running `parse_ibkr_statement` / `parse_trendlyne` over the real files
   in `Portfolio Info/` and calling `save_holdings()`. `HOME=<scratch>` puts the DB at
   `<scratch>/prosper_data/prosper.db`.
4. **Pre-warm `save_price_cache()` and `save_ticker_info_cache({t: {} …})` offline first**, or the
   first page load runs past two minutes and you never see the UI.
5. Run with `PYTHONPATH=<scratch>/stub` holding a stub `yfinance.py`. The Yahoo `chart` fallback
   covers everything, so the app still runs live.
6. **Streamlit's file watcher does not work here** (no watchdog) — restart on a new port and clear
   `__pycache__` after every edit.
7. Drive it with the browser at `resize_window` preset `mobile`. **Measure against
   `[data-testid="stMain"]`, NOT `document.documentElement`** — Streamlit scrolls an inner container,
   so the document's own `scrollHeight` is always just the viewport height.

## 3. Architecture (key files)

- `app.py` — page config, sidebar-hide CSS, auth gate, `ensure_settings_loaded()`, `st.navigation`,
  NAV snapshot, global `mobile_shell()`, `bottom_nav()`, the daily IBKR price backfill, and the
  floating "Ask Prosper" popover.
- `core/auth.py` + `pages/99_OAuth_Callback.py` — Google OAuth popup. Checks `verified_email`
  (Google's REST userinfo field), **not** `email_verified` (that only exists on the OIDC path). The
  popup-close fallback button must render in an iframe with a real height (`height=180`, not 0).
  **Persistence:** both the Google and the email path now write streamlit-authenticator's 30-day
  re-auth cookie (`_persist_cookie_pending` flag → `authenticator.cookie_controller.set_cookie()` in
  the authed branch of `run_auth`), and `run_auth` does an `unrendered` cookie precheck before
  drawing the login page, so a refresh / free-tier cold start restores the session instead of
  logging you out. Before this the Google path never touched the cookie — that was the whole "refresh
  logs me out" bug. `login()` is called with `sleep_time=0` (its default is a 1s sleep on every
  unauthenticated rerun). The credential rebuild (`_db_get_all_users` → Turso) is session-cached for
  45s except mid-transition. Login screen is a 430px centred card (`_LOGIN_CSS`), not
  `st.columns([1,2,1])` which crushed it on a phone.
- `core/settings.py` — `SETTINGS` proxy, Claude model IDs (`claude-sonnet-5` default,
  `claude-opus-5` best, `claude-haiku-4-5` fast). `call_claude`/`call_claude_stream` default
  `thinking={"type":"disabled"}` unless the caller opts in. **Critical: `claude-opus-5` has extended
  thinking ON by default and it eats `max_tokens`** — an unprotected Opus fallback returns empty text
  with `stop_reason="max_tokens"`. Opus is deliberately OUT of `CLAUDE_AUTO_FALLBACK`
  (`[sonnet, haiku]`); it is used only when a caller asks for it.
- `core/database.py` — SQLite/Turso via `core/db_connector.py` (pooled Session + retry); multi-tenant
  `user_id` scoping; additive migrations in `init_db()`. `save_holdings()` DELETE-before-insert is
  scoped by `(ticker, broker_source)` so re-uploading one account never wipes another's same-ticker
  position; a second, broader delete scoped by `(broker_source, asset_category IN ('Restricted
  Stock','Retirement Account'))` runs first, because those tickers are AI-generated fresh each parse.
- `core/symbology.py` — **identity and routing (new in v7.21).** Classifies a ticker into a
  *market* from the broker's listing exchange, then the suffix, then the ISIN country prefix, in
  that order of trust. Holds the Yahoo suffix table, the per-country TradingView slugs, the IBKR
  symbol truncations, the crypto symbol set and the GBX→GBP flag. No network, no state.
- `core/market_data.py` — **the quote pipeline (new in v7.21).** Per-market ordered tier lists of
  batch-shaped providers; a `Quote` carrying `source` / `latency` / `asof` / `currency`; a
  `FetchReport` naming what could not be priced. This is the ONLY price path — see §6.
- `core/cio_engine.py` + `core/data_engine.py` + `core/currency_normalizer.py` — the price /
  fundamentals waterfall, FX, news, ticker resolution. All parallel fetches go through
  `core/parallel.py`: `gather()`'s outer deadline only bounds how long the CALLER waits, **not** how
  long one call holds its worker slot — that distinction caused a real 5-minute production hang.
  `run_with_timeout()` is the real per-call cap (6s around yfinance).
- `core/adx_client.py` — Mubasher scrape for UAE (ADX + DFM) prices and fundamentals. Discovers chart
  IDs at runtime across both market paths; the static `ADX_CHART_IDS` map is an optimisation, not the
  supported-ticker list. Day change uses the previous **session** close from the daily history CSV.
- `core/ibkr_client.py` / `core/ibkr_sync.py` / `core/ibkr_prices.py` — Flex Query web service.
- `core/grow_engine.py` — **GROW v5.1** (PROSPER v3.0 retired). Framework text in `grow/` sent as a
  cached system block. Tiers: screen (Sonnet 5), standard (Sonnet 5 + web search), full (Opus 5).
  The deterministic §8 resolver `resolve_entry()` recomputes Entry verdict + 5-rung ladder from the
  model's own JSON and **overrides the model's arithmetic** — by design, but it must be kept in exact
  sync with CORE.md or it silently replaces correct numbers with stale ones. After ANY change to
  `grow/*.md` run `venv/bin/python3 grow/grow_verify.py "grow/GROW v5 1 CORE 04Sep2026.md"` and
  expect `RESULT: ALL CHECKS PASS`.
- `core/edgar_client.py` — SEC EDGAR XBRL: primary filing data for US names, free, with
  accession numbers. See §8.
- `core/options_data.py` + `core/vol_metrics.py` + `core/options_engine.py` + `harvest/` —
  **HARVEST v1.0, the Options Desk** (new in v7.19). Daily options recommendation engine. See §8.
- `core/file_parsers.py`, `core/screenshot_parser.py` — broker imports. Restricted-stock and
  retirement rows get an AI-built deterministic `broker_source`, but **only if the Upload Portal's
  Broker dropdown stays on "Auto-detect"**; a manual selection collapses NIQ/401(k)/DCP into one tag.
- `core/ui_components.py` — the design system (see §5).
- `core/ui_errors.py` — four canonical templates (`empty_state` / `fetch_failed` / `fetch_pending` /
  `unsupported`). Real exceptions are logged, never shown. Note `empty_state(what, *, action=…)` —
  the second argument is keyword-only.

## 4. Rules learned the hard way

Read this section before writing Streamlit code. Each line cost a real debugging session.

1. **`st.markdown("<div class=…>")` never wraps the widgets that follow.** Streamlit closes every
   element it opens. Scope CSS off a marker element's following siblings:
   `[data-testid="stElementContainer"]:has(.marker) ~ [data-testid="stElementContainer"] …`.
   `position_rows`, `mobile_only_start/end`, `bottom_nav` and `responsive_holdings` all rely on this.
   *(Cost: two separate sessions.)*
2. **Never depend on a Streamlit CSS custom property.** `var(--secondary-background-color,#f6f6f6)`
   is undefined in 1.41, so the light fallback won and mobile cards rendered light-on-light —
   invisible. Use `rgba(128,128,128,α)` and `color:inherit`, which read correctly on either ground.
3. **Anything rendered after `pg.run()` in `app.py` is skipped on 21 of the 24 pages**, because they
   call `st.stop()` on empty states and `st.stop()` halts the whole script. Render persistent chrome
   *before* `pg.run()`. (The floating chat widget still has this bug; it branches on `pg.title`, so
   moving it needs care.)
4. **`st.columns()` stacks below ~640px with no per-row opt-out.** Every "row of 3 KPIs" becomes three
   ~70px rows. Use `stat_grid()` (a CSS grid) for anything that must stay side by side.
5. **`st.dataframe` is a fixed-height widget with its own horizontal AND vertical scrollbars** — a
   scroll trap inside a scrolling page. On a 375px screen the holdings table showed 3 of 12 columns.
6. **Streamlit runs a button *label* through its full markdown pipeline.** `\n\n` → two `<p>`,
   `:green[…]` → `<span>`. Writing each line as exactly two markdown nodes lets
   `justify-content:space-between` produce an IBKR-style left/right split — which is how tappable
   position rows work.
7. **Plain `<a href>` inside the app is a real navigation**: full reload, brand-new Streamlit session,
   price cache and active portfolio destroyed. Use `st.page_link` / `st.switch_page` for anything
   internal.
8. **Widget keys must be unique per render.** `_render_currency_section` runs once per country tab, so
   any fixed key raises `StreamlitDuplicateElementKey` on every load.
9. **Streamlit cannot read the viewport.** There is no server-side "is this a phone". Every responsive
   decision has to be CSS, and every fix must work at 375px *and* 1280px from one definition.
10. **Bound long lists.** The first card-list cut rendered all 182 positions and made the Dashboard
    12.8 screens tall — worse than the scroll-box it replaced. Sort by value, cap at 25, offer
    "show all".
11. **A source's reachability is a property of the NETWORK, not the code.** Mubasher works from a
    laptop and 403s Render. Yahoo rate-limits both, intermittently. Never write "verified live"
    without saying which network the check ran from. `scripts/probe_sources.py` and
    Settings → 📡 Data Source Health exist to settle this in one click.
12. **An additive migration creates a window where the columns do not exist yet.** It runs in
    `init_db()`, so any path that reads or writes before that — a script, a direct page render, the
    deploy window itself — sees the old schema. On a READ path that silently made every ticker look
    stale and re-fetched the whole book on every page load. Try the new columns, catch, fall back.
13. **Silence a third-party library's own chatter when a miss is normal.** yfinance prints
    "symbol may be delisted" for every failure; in a tiered pipeline a failure just means "next
    tier", so those lines are pure noise — and noise is how real errors get missed.
14. **Route by market, not by a global source order.** Finnhub 403s outside the US, FMP 402s, Twelve
    Data 404s. A single global cascade walks all three certain failures for every non-US name before
    reaching a source that can answer.

## 5. The mobile design system (`core/ui_components.py`)

Density target is the IBKR mobile app. `mobile_shell()` is injected **once globally in `app.py`**, so
every page — including ones never individually converted — gets 44px tap targets (Apple HIG / WCAG
2.5.5), reclaimed block padding, hidden Plotly modebars and faded tab strips.

| Component | Replaces | Notes |
|---|---|---|
| `page_header(title, meta)` | `st.header` / hand-rolled `<h2>+<p>` | ~211px → ~55px |
| `hero_metric(...)` | the one figure a page exists for | display size |
| `stat_grid(stats, columns)` | `st.columns(3-6)` + `st.metric` | **the core fix** — stays a grid at 375px |
| `position_rows(...)` | `st.dataframe` for holdings | tappable, IBKR two-line layout |
| `responsive_holdings` / `row_list` | read-only card list | CSS-swapped with the desktop table |
| `holdings_rows(df, ccy)` | — | enriched slice → rows, sorted by value |
| `render_responsive_table(df)` | `st.dataframe` for small tables | card-per-row under 768px; **takes display-ready strings, does no formatting** |
| `show_chart(fig)` / `mobile_chart(fig)` | all 39 `st.plotly_chart` calls | automargin, `uniformtext` minsize 9, horizontal legends + pie labels, modebar off |
| `bottom_nav()` | the 24-item sidebar on phones | 5 `st.page_link`s, fixed bar |
| `fmt_compact(v, ccy)` | raw currency figures | `2,417,140` → `2.4M`, exact value in `title=` |
| `status_chip(label, level)` | ad hoc 🔴/🟡/🟢 | critical / warn / good / neutral |

`st.metric` was mostly replaced by `stat_grid` / `hero_metric` (was 78) — but **23 `.metric()`
calls remain**, all written as `colN.metric(...)` on `st.columns` objects, in `8_Sentiment.py`,
`7_Analyst_Consensus.py`, `5_Performance.py` and `core/grow_render.py`. They still depend on the
`[data-testid="stMetric*"]` CSS in `app.py`. Finishing the conversion is P3-11 (§12).

Measured on a real 375×812 viewport against the real portfolio: Command Center went from 4.5 screens
with the first number 526px down, to 3.9 screens with it at 118px. The Dashboard went from ~4 to ~15
positions per screen.

Design review + page-by-page plan (published artifact):
`https://claude.ai/code/artifact/fe1423f6-44eb-4103-909f-4c4e495fafc7`

## 6. Data sources — the pipeline (v7.22, 8 Sep 2026)

Prices no longer walk a fixed global cascade per ticker. `core/market_data.py`
groups holdings by **market** and asks that market's best provider for all of them
at once, then falls down a per-market tier list for whatever is still missing.
`core/symbology.py` decides which market a ticker belongs to. There is **one** price
path — the old `cio_engine._fetch_one_quote` cascade is deleted, not bypassed.

**Measured on the real book (185 instruments incl. crypto):**

    179/185 priced in 17.1s
    tradingview 172 · coinbase 3 · yahoo-chart 2 · boerse-frankfurt 1 · peg 1
    58 live · 121 delayed
    all 11 UAE names priced

For comparison the pre-pipeline cascade managed 175/181 and took 67.7s. The six
still unpriced have no free source anywhere: OZON and Balasore Alloys (both
suspended listings) plus four offshore / Morningstar fund lines.

### The production probe that decided all of this

Run from Render on 8 Sep 2026 (Settings → 📡 Data Source Health):

| Source | Result | HTTP | Time |
|---|---|---|---|
| tradingview (UAE) | **PASS** | 200 | 191 ms — ALDAR 7.81 AED, EMAAR 11.1, ADCB 15.38 |
| yahoo chart | PASS | 200 | 66 ms |
| **mubasher (UAE)** | **FAIL** | **403** | 37 ms — Cloudflare blocks datacenter IPs |
| amfi · justetf · boerse frankfurt · finnhub · sec edgar · frankfurter · cboe | PASS | 200 | 433–1471 ms |

### Sources REMOVED from the price path (not disabled — removed)

| Source | Why |
|---|---|
| **Mubasher** | 403 from Render, as the v7.15 investigation predicted. Every "verified live" claim about it came from a laptop or a GitHub runner. In the tier list it cost one guaranteed-failing call per UAE holding per refresh. `core/adx_client.py` **stays** — `scripts/prewarm.py` calls it from a GitHub Actions runner, where it does work. |
| **Twelve Data** | `404 available starting with the Pro or Venture plan` for UAE, India and OTC funds; US is covered twice over. **This is a paid subscription now contributing nothing to pricing — worth cancelling.** |
| **Twelve Data's UAE symbol rewrite** | Turned `EMAAR` into `EMAAR:DFM`, a form nothing could quote, and `resolve_tickers_batch` cached it in Turso for 24h — one bad resolution poisoned every later load. |
| **`_fetch_one_quote`** | ~240 lines, three of six sources known-dead and called anyway. Everything it reached is now a provider, including yfinance `fast_info`. No second price path left to drift. |
| UAE circuit breaker, `_price_sanity_check`, `_is_twelve_data_symbol` | Existed only to serve that cascade. |

### The pipeline as it stands

| Market | Tier 1 | Tier 2 | Tier 3 | Last resort |
|---|---|---|---|---|
| US (84) | tradingview | finnhub | yahoo-chart → yfinance | ibkr-mark |
| **UAE (11)** | **tradingview** | — | — | ibkr-mark |
| India equity (50) | tradingview | yahoo-chart → yfinance | — | ibkr-mark |
| India funds | **amfi** (official NAV) | — | — | ibkr-mark |
| Japan · Swiss · SGX · HK · Korea · Europe | tradingview | yahoo-chart → yfinance | boerse-frankfurt (by ISIN) | ibkr-mark |
| LSE / Irish ETFs (6) | tradingview | **justetf** (by ISIN) | yahoo-chart → yfinance | ibkr-mark |
| Offshore funds | justetf | — | — | ibkr-mark |
| **Crypto** | **coinbase** → coingecko | — | — | — |

Everything above is **keyless and needs no configuration** except Finnhub, which
uses the existing `FINNHUB_API_KEY`. TradingView is **on by default**;
`PROSPER_DISABLE_TRADINGVIEW=true` is the kill switch if it ever starts returning
nonsense. Its screener is undocumented and its terms do not license
redistribution — a considered trade-off, since it is the only free ADX/DFM source
and it cross-checks against IBKR's own marks to within 0.80% across ten holdings
in five markets.

**FX** now goes: hard pegs → in-memory → Turso (1h) → yfinance → **ECB reference
rates via Frankfurter** → open.er-api → stale cache of any age → static table. It
never silently returns 1.0. Frankfurter publishes 30 currencies and **AED is not
one of them**, so the 3.6725 peg stays load-bearing.

**Crypto** is new. The Coinbase export emits bare symbols (`BTC`, `ETH`) that
every equity provider would fail to price, so routing is by broker tag, not by
symbol shape; stablecoins short-circuit to 1.00 without a round trip.

### Provenance — the rule that makes failures diagnosable

Every quote carries `source`, `latency`, `asof` and `currency`, and `price_cache`
stores `latency` + `quote_currency`. Classes are `live` / `delayed` / `eod` /
`broker_mark` / `stale_cache`; `Quote.is_actionable` is true only for the first
two, so the Options Desk can refuse to write a strike against a broker valuation.

**Both `price_cache` paths fall back to the legacy column set** when the additive
migration has not yet run. Found by running it: without the fallback the SELECT
raises, every ticker looks stale, and every page load re-fetches the whole book.

### Identity — stop resolving, start recording

The IBKR statement's *Financial Instrument Information* section states the
**ISIN**, the **Conid** and the **listing exchange** for every position; the parser
now keeps all three (`holdings.isin` / `.conid` / `.listing_exchange`). That is
what the ISIN-keyed providers need, and it is why `symbology.classify()` trusts the
broker's exchange code over any suffix guess — IBKR writes Toronto as `TSE`, which
as a Yahoo suffix means Tokyo.

`core/symbology.py` also encodes per-**country** TradingView slugs (routing all of
"europe" to Germany silently loses Milan), the IBKR symbol truncations
(`PUREHEALT` → `PUREHEALTH`), a GBX→GBP guard for London pence quotes, and the
crypto symbol set.

### Checking a source from the network that matters

    venv/bin/python3 scripts/probe_sources.py         # add --json for CI

…or **Settings → 📡 Data Source Health**, which runs the same eleven probes
server-side. A pass on a laptop says nothing about Render — that lesson cost two
rounds on the UAE bug and one paid subscription.

## 7. Where the work stands — the phase board

Three fronts were measured on 8 Sep 2026. Two are shipped; the third is audited and waiting.

| Phase | Scope | State | Detail |
|---|---|---|---|
| **1 — Data sources** | Every price, FX, fundamental and options feed | ✅ **shipped, live** (`63118b2`, `dep-dag0f8eq1p3s73efb5kg`) | §6 |
| **2 — Simplicity & speed** | Caching, duplication, dead weight, per-page cost | ✅ **shipped, live** (`7d7108d` → `e575e69`, 8 Sep) | §11 |
| **3 — Mobile rehaul** | Design system, IA, all screens at 375 px | 🔄 **in progress** — 9 pushes live (`695f4f6` … `818e498`) | **§13** (§12 is the superseded 8 Sep audit) |

**Phase 2 shipped as four pushes on 8 Sep, each verified and deployed live.** What went in and —
just as important — what was dropped after inspection is the header of §11. The one-line version:
Market News durable-cached, `prosper_analysis.py` (713 lines) deleted, Sentiment made on-demand,
Deep Dive's insider/holder tables cut, the Dashboard's 12 eager country tabs collapsed to one
region picker, and the Performance "freeze" fixed by drawing the portfolio curve from
`nav_snapshots` instead of a 180-ticker history fan-out. **Four of the eleven §11 findings did not
survive inspection** (P2-1's target function was dead, P2-3's crash bug isn't real, P2-9's premise
was a bad grep, P2-10 was already solved by Streamlit) — the standing lesson is that §11 and §12
are *measured leads, not facts*; re-verify each against the current code before acting.

### What Phase 1 actually changed

- One price path, not two. `cio_engine._fetch_one_quote` (~240 lines) deleted; everything routes
  through `core/market_data.py`.
- **179/185 instruments priced in 17.1 s**, against 175/181 in 67.7 s before. All 11 UAE names
  priced for the first time from Render.
- Mubasher and Twelve Data removed from the price path on probe evidence, not opinion.
- New: crypto (Coinbase → CoinGecko), India fund NAV (AMFI), LSE ETFs (justETF), ECB FX
  (Frankfurter), ISIN/Conid/listing-exchange capture from the broker statement.
- Provenance (`source` / `latency` / `asof` / `currency`) on every quote and every cache row.

### Standing items that belong to no phase

1. **Run GROW across the book and the universe — through Cowork, not the API.** Still the critical
   path. Rule 1 of the options doctrine cannot be evaluated without a Durability score and a price
   ladder, so **every assignment-grade name currently produces a PROVISIONAL ticket**. See §9; it
   costs nothing per token. Two names are done: NKE (screen) and ADBE (full_lean).
2. **Paper-trade HARVEST before placing a real order.** Log the slate daily without acting, then
   measure what fraction would have expired worthless and whether the doctrine's rejections were
   right. An options engine that has never been measured is a confident-sounding random number
   generator, and this one makes specific probability claims every morning.
3. **Install the two GitHub Actions.** `docs/harvest-scan-github-action.yml` and
   `docs/prewarm-github-action.yml` need copying into `.github/workflows/` plus repo secrets. Every
   session's push token has lacked `workflow` scope. Until then the nightly options scan is manual.
   Note the prewarm job is now the *only* remaining consumer of `core/adx_client.py`.
4. **Cancel the Twelve Data subscription.** It is paid, and after Phase 1 it contributes nothing:
   `404 available starting with the Pro or Venture plan` for UAE, India and OTC funds, and US is
   covered twice over by TradingView and Finnhub. Confirm nothing else regressed first —
   `core/yf_utils.py` still borrows its rate-limiter helper.
5. **`PROSPER_COOKIE_SECRET` is only 18 bytes** on production — JWT logs an
   `InsecureKeyLengthWarning` (non-fatal, HS256 works). Regenerate as 32 bytes
   (`python -c "import secrets;print(secrets.token_hex(32))"`); existing sessions need one re-login.
6. **GROW Annex E calibration** — the archetype premium/required-return table
   (`grow/GROW v5 1 ANNEX E ARCHETYPE LOOKUPS.md`) is a **mechanical linear rescale of
   pre-compression values, explicitly labelled a placeholder**, chosen by Punit as a stopgap.
   Replace with real per-archetype judgment when he is ready. Do not treat the numbers as final.
7. **Exhicon (`543895.BO`)** — Yahoo shows ₹258.55 against Trendlyne's ₹469.85 and a 52-week range
   of 220–440. That looks like a corporate action; **the share count needs confirming before the
   position value is trusted.**
8. **`PRYM.MI` should be `PRY.MI`.** IBKR writes Prysmian with a trailing lowercase share-class
   marker, and the parser keeps it. The pipeline prices it anyway via Boerse Frankfurt by ISIN — a
   fair demonstration of why capturing the ISIN mattered — but the ticker is still wrong.
9. **A/B `full_lean` against `full` on two or three names.** `full_lean` (Sonnet, 25 searches, 18k
   fetch content) is measured at $1.27 and produces a complete result. Whether the memo is as *good*
   as Opus at 40k content is unmeasured. Cost can be modelled; quality has to be compared.
10. **Never map old PROSPER-era verdicts onto GROW.** Every GROW verdict shown must carry Durability
    + Entry arithmetic. Positions are never sent to the engine.

**Closed since the last handoff:** the whole of Phase 2 (§11 ledger — 7 findings shipped across
`7d7108d`…`e575e69`, 2 dropped as non-bugs, 1 reverted); the whole of Phase 1 (§6);
`last_known_price` back-fill; the full tier live-tested end to end; the "mobile Connecting… hang"
watchdog shipped (efficacy still unconfirmed — see §12 P3-9).

## 8. HARVEST v1.0 — the Options Desk (new in v7.19)

Daily options engine: at most five specific, tradeable orders a morning, from live chains, for
about **$0.0155 a day** in model cost (measured, cache warm).

**Architecture — the GROW split, applied to options.** Claude never sees an option chain and never
does arithmetic.

| Layer | Where | What |
|---|---|---|
| 2 | `options_engine.generate_candidates()` | Pure Python. Walks the chains, applies every doctrine gate, scores survivors. ~180,000 contracts → ~20 finalists. |
| 3 | `options_engine.select_slate()` | ONE Claude call (Sonnet 5). Sees a 20-row table, picks ≤5, writes the reasoning. |
| 4 | `options_engine.resolve_order()` | Pure Python. Recomputes limit price, size, collateral, breakeven, max loss and exits — **overrides the model**, exactly as `resolve_entry()` does for GROW. |

**Doctrine** — `harvest/HARVEST_v1_DOCTRINE.md`, sent as a cached system block (~3.1k tokens).
Eleven rules. R1 is the keystone and is where GROW earns its keep: **a covered call's strike must
sit at or above GROW's `fair_high` rung, and a short put's strike at or below `buy_below`** — you
only ever agree to a price GROW already called fair. R2 forbids selling cheap volatility
(IV30/HV20 ≥ 1.10 required). R4 caps short-put collateral at 60% of the ledger. R9 makes "fewer
than five" and "zero" valid answers.

**SEC EDGAR XBRL (`core/edgar_client.py`, v7.20)** — primary filing data for US names without
an LLM. Revenue, income, cash flow, debt, equity and the cover-page share count arrive as
numbers, each tagged with the form, fiscal period, filing date and **accession number**. Free,
no key, ~850 tokens a name. Verified on 12 filers, 12/12.

  * Concept names are NOT consistent between filers. HIMS tags revenue only as
    `RevenueFromContractWithCustomerExcludingAssessedTax` and has no `Revenues` concept at all;
    ADBE has both. Every metric is an ordered fallback chain — a single-concept lookup silently
    returns nothing for a third of the book.
  * It is injected ABOVE a divider in the snapshot and §6.2's instruction was rewritten to say
    which half is Class A. Without that the model re-fetches what it was handed and the whole
    exercise is pointless.
  * **Honest result:** the measured ADBE run cost **$1.27 against a modelled $1.36 without it —
    a ~7% saving, not the ~55% first projected.** The freed search budget gets spent on
    qualitative retrieval by design, so the gain is better evidence per dollar, not a smaller
    bill. Cutting the bill further means cutting searches, which is a separate decision.
  * US filers only. SREN.SW, EMAAR.AE, the India lines and the LSE/Lux funds return None and
    fall back to ordinary retrieval.

**Data — all free, all verified live 06-07 Sep 2026.**

| Source | Status |
|---|---|
| **CBOE delayed quotes** (`cdn.cboe.com/api/global/delayed_quotes/options/<SYM>.json`) | Works, keyless. The only free source with **greeks + IV per contract**. Verified on US equities, ADRs, ETFs and index options (`_SPX` takes the underscore). |
| **Finnhub `/calendar/earnings`** | Works on the existing key. One call covers the whole R6 blackout gate. |
| **Yahoo `chart` → Twelve Data** | Realized-vol closes, two sources. Yahoo 429s under a 110-name sweep, hence the fallback. |
| **Yahoo v7 options** | **Dead** — `401 Invalid Crumb`, same as `quoteSummary`. Do not build on it. |

**Two operational constraints that shaped everything:**

1. **CBOE rate-limits hard.** Eight parallel workers → HTTP 429 within seconds, and it silently
   reported that NVDA/ORCL/PLTR have no listed options. Sequential at ~3s ran 84/84 clean.
   `options_data._Pacer` does adaptive backoff. **Never add concurrency there.**
2. **Weekend quotes lie about spreads.** A Sunday scan gave a 115% median spread on XLF. Open
   interest survives the weekend; bid/ask does not. Hence `quote_is_stale()`, the loosened gate
   when stale, and the "re-check before placing" warning on every affected ticket.

**Running it.** `scripts/options_scan.py`, on a **GitHub Actions runner** (`docs/harvest-scan-github-action.yml`,
21:30 UTC weekdays — after the US close). Not Render: a scan moves ~150MB over 6-12 minutes, and
Render's datacenter IPs are already known to be Cloudflare-blocked for the UAE fetches. **CBOE has
only been verified from a residential IP — the first runner execution is the real test.**

    python scripts/options_scan.py --vol-only    # phase 0: start the IV-history clock TODAY

`--vol-only` matters more than it looks: IV percentile needs ~120 observations
(`vol_metrics.MIN_HISTORY_FOR_PERCENTILE`) and **cannot be backfilled from any free source**. Every
day it does not run pushes usable IV-rank six months further out.

**Tables** (additive, in `init_db()`): `option_chain_cache` (the reduced slice, not raw chains),
`vol_history` (the permanent series), `harvest_recommendations` (append-only, like
`grow_verdict_log`), `harvest_positions`, `harvest_slate`.

**Settings**: `harvest_collateral_usd` is the liquid collateral ledger (Treasury ETFs + cash, NOT
the margin loan). **Left at 0, every short put is blocked by R4** — the safe default. Set it on the
Settings page.

**Owner context that shaped the doctrine** (corrected 7 Sep after a first pass got it wrong):
~$208k of short-duration Treasury ETFs (IB01, U03A) + ~$67k AED cash = real collateral. The
CHF/JPY/SGD debit is a deliberate 1-1.5% funding carry, not distress. UAE-resident Indian national:
no capital gains tax, and option premium suffers no US withholding while US dividends lose 30% —
so premium is the best-taxed income stream (R10, and it is *configuration*, not tax advice).

**Universe**: `harvest/universe.py` — 50 assignment-grade names, tiered by collateral per contract
(A <$15k, B $15-40k, C >$40k = never a naked short put), plus a SPY/TLT hedge annex. Built because
only **11 of the owner's 69 eligible US lots** pass a real liquidity gate — his own book cannot
honestly feed five ideas a day.

**Tests**: `tests/test_harvest.py`, **60 assertions**, offline, no network/model/DB. Run them after any
change to the gates or the arithmetic — this is where a wrong number becomes a real order.

    venv/bin/python3 tests/test_harvest.py

The suite inserts `scripts/_stub` on its own path. It has to: yfinance segfaults
(SIGSEGV, exit 139) for every ticker in the local venv on Python 3.14, and a segfault
produces NO output and exit 139 — indistinguishable from a clean pass at a glance. This
suite reported nothing for one run before that was noticed.

**Verified in the preview harness** at 375×812 against the real slate: `stat_grid` holds a
3-column grid (112.6px each), hero at 30.4px, no horizontal overflow, page 4.2 screens.

**Not yet done**: the workflow file needs copying to `.github/workflows/` plus secrets (same
`workflow`-scope problem as prewarm); no live GROW verdicts existed locally so R1 was exercised
against seeded verdicts, not production ones; and the engine has never been paper-traded — see
open item 10.

## 9. Running GROW on the Pro subscription instead of the API (v7.20)

The API is the expensive path: **$1.27 a name measured** at `full_lean`, ~$25 for twenty
holdings. Punit's decision is to run GROW in **Claude Cowork** on his existing Pro limits
instead, and pay nothing per token. Two scripts make that a supported path rather than
copy-paste:

    python3 scripts/grow_prompt.py --universe --out ~/grow_briefs   # 1. generate briefs
    # 2. open Cowork with the grow/ folder attached; paste ONE brief per conversation
    # 3. save the WHOLE reply (the fenced ```json block at the end is what gets read)
    python3 scripts/grow_import.py --dir ~/grow_out                 # 4. import

**The guarantee that makes this safe.** §8 is arithmetic, not judgement. `resolve_entry()`
recomputes the Entry verdict, the five-rung ladder and the ±25% stability band in Python from
the memo's own inputs and **overrides whatever the memo wrote** — on both paths. To keep them
from drifting, the whole assembly step was extracted into
`core.grow_engine.assemble_result()`, which the API path and the import path both call. There
is no second implementation.

Demonstrated, not asserted: a test feeds a memo whose ladder reads
`strong_buy_below: 1.0, buy_below: 2.0, fair_high: 4.0` and asserts the stored result is
`174.12 / 230.07 / 348.00`. Another feeds a memo claiming STRONG BUY on numbers that support
HOLD and asserts the verdict is corrected and the disagreement recorded in `uncertainties`.

`grow_import.py` refuses, before saving anything: no parseable JSON block; a missing or
out-of-range `durability.score` (rule 20); an `entry.verdict` outside the five permitted words
(rule 22); no price to solve the ladder against; and a JSON `ticker` that disagrees with the
one being imported as — filing one company's analysis under another's name is the one mistake
that would quietly poison Rule 1.

Rows imported this way are tagged `model_used="cowork"` and carry a note in `uncertainties`
saying so. They are otherwise indistinguishable from API rows, which is the point.

**One brief per conversation.** The framework is ~36,000 tokens and each memo is long; a
conversation carrying three or four names starts truncating the earlier ones.

## 10. What verification is and isn't possible here

Achievable and expected: `py_compile` on every touched file; the preview harness at 375×812 and
1280px against the real portfolio; live production Render logs and deploy status via the Render MCP;
live `curl` probes of any data source before believing a claim about it.

**Not achievable from a session:** anything requiring Turso credentials (so no reads or writes against
the production database), and anything requiring Punit's real login. Production checks are limited to
the sign-in page rendering, deploy status, and error-level logs.

**A standing lesson:** "verified live" from a laptop is not the same as verified on Render. The UAE
price bug survived two rounds of fixes because every verification ran from a residential IP. When a
data source is involved, say which network the check ran from.

## 11. PHASE 2 — Simplicity, speed and reliability (SHIPPED 8 Sep 2026)

Shipped in four pushes on 8 Sep. Everything below the "shipped / dropped" ledger is the original
audit, kept for context — but **it is a set of measured leads, and four of the eleven were wrong.**
Re-verify before reusing any number here.

### What shipped, and what was dropped

| # | Finding | Outcome |
|---|---|---|
| **P2-1** | Market News uncached (measured 11.7 s / visit) | ✅ **Shipped**, but the audit misattributed it: `get_market_news()` had **zero callers**. Real cost is `6_Market_News.py` looping session-only-cached `get_ticker_news` over 6 index tickers on every cold start. Fix: durable `news_cache` tier on that page, keyed by focus area, Refresh busts it. Dead `get_market_news` + `MARKET_RSS_FEEDS` deleted (`_fetch_rss_feed` kept — `get_ticker_news` uses it). |
| **P2-5** | 713-line retired `prosper_analysis.py` | ✅ **Shipped.** One live consumer (`grow_engine` → `_fetch_finnhub_analyst`); moved that helper verbatim into `finnhub_client.py`, deleted the file. The `prosper_analysis` **table** and its `database.py` accessors are the GROW verdict store — untouched. |
| **P2-9** | "Dead `st.metric` CSS in `app.py`" | ❌ **Shipped then reverted.** Premise was a bad grep — `grep "st\.metric("` misses `col1.metric(...)` on column objects. There are **23 live `.metric()` calls** (Sentiment, Analyst Consensus, Performance, `grow_render`). The `[data-testid="stMetric*"]` block stays until those pages move to `stat_grid`/`hero_metric`. §5's "st.metric gone from every page" and this finding's "down to two" are both **false**. |
| **P2-11** | Top Movers shows `+0.0%` filler | ✅ **Shipped.** One line: also drop exactly-zero rows (a missing day-change is filled as `0`, not null, so `dropna` misses it). The existing "No price data available yet." caption now shows when there is genuinely nothing to rank. |
| **P2-7** | Sentiment sweeps the whole book (>200 s) | ✅ **Shipped.** The whole-book sweep is behind an "Analyse all N holdings" button; picking one holding fetches just that name on demand (cached 30 min). Overview chart + status bar render only once a whole-book run exists. |
| **P2-8** | Deep Dive Ownership tab: 4 uncached yfinance calls | ✅ **Shipped.** Removed `get_major_holders` / `get_institutional_holders` / `get_insider_purchases` / `get_insider_transactions` and the tables they fed. Kept the ownership-split pie + insights (run off the ticker `info` the page already fetches). `data_engine` functions left in place — no other caller, harmless. |
| **P2-4** | Dashboard builds 12 tables to show 1 | ✅ **Shipped.** `st.tabs(["All", country, …])` (eager: ~12 tabs × 2 tables = ~24 `stDataFrame`s/render) → `st.segmented_control` "Region" picker, key `dash_region`, default "All". `_render_currency_section` untouched. **This is also most of P3-6** — see §12. |
| **P2-2** | Performance never finishes loading | ✅ **Shipped.** The "vs Benchmarks" chart rebuilt the portfolio curve from a full history fetch for every one of ~180 holdings. Now the portfolio line is `nav_snapshots.total_value` (written every Dashboard visit), clipped to the selected period, indexed to 100; only the ~4 selected benchmarks still fetch. **Trade-off:** the portfolio line only covers the window since NAV snapshots began, so short periods show an info message until they accumulate. `get_history`'s durable-cache tier (`history_cache` table, audit's "part a") was **not** built — once the fan-out is gone nothing here is on a freeze path. It is still worth doing for Deep Dive / Technical / Risk / `portfolio_optimizer`; carry it into §12. |
| **P2-3 / P2-6** | 12 ways to sum the portfolio; "8 sites crash where 4 degrade" | ❌ **Dropped — the bug is not real.** `enrich_portfolio()` builds `pd.DataFrame(list-of-dicts)` where `market_value` is `float | None` → the column is **float64**, and bare `.sum()` equals `to_numeric().sum()` equals `.dropna().sum()`. The only thing that puts `""` in a numeric column is `clean_nan()` (`fillna("")`) — and its output is **display-only, never summed** (every call site checked). A 12-site refactor that fixes nothing and can only regress. If revisited, it is purely a consolidation-for-tidiness call, not a correctness one. |
| **P2-10** | Renumber page 18 / de-auto-discover `pages/` | ❌ **Dropped — already solved.** Under Streamlit 1.41 + `st.navigation`, `set_pages()` swaps `PagesStrategyV1` → `V2`, which fully replaces `pages/` auto-discovery; unregistered pages 404 (the `99_OAuth_Callback` comment already says so). The duplicate `18_` prefix has no functional effect. Residue is **one cosmetic boot-warning line**. The "fix" (rename `pages/` → `views/`, 54 refs) was the riskiest change in the batch for no reward. Only revisit if the "Connecting…" hang is reproduced on a real phone *and* traced to `pages/`. |

**Net:** ~1,600 lines removed across the four pushes, the two slowest surfaces (Market News, Performance) fixed, no feature the book uses removed. Deploys: `7d7108d` (dep-dag10i9…), `decf584` (dep-dag2s6…), `a134ae7` (dep-dag4gt…), `e575e69` (dep-dag53f…) — all live, sign-in 200, no error logs.

---

*Original audit follows (8 Sep 2026, preview harness §2, real 182-holding book):*

### The one rule that explains nearly every slow page

Prosper has two cache tiers: **durable** (Turso) and **session** (`st.session_state`, dead on every
refresh and every free-tier spin-down). I walked all twenty cached functions in `data_engine`:

| Tier | Count | Functions |
|---|---|---|
| Durable | **2** | `get_ticker_info_batch`, `get_portfolio_news` |
| Session only | **17** | `get_history`, `get_financials`, `get_ticker_info`, `get_ticker_news`, `get_analyst_recommendations`, `get_analyst_price_targets`, `get_recommendations_summary`, `get_upgrade_downgrade`, `get_finnhub_analyst_data`, `get_insider_transactions`, `get_insider_purchases`, `get_institutional_holders`, `get_major_holders`, `get_mutualfund_holders`, `resolve_ticker`, `resolve_tickers_batch`, `calc_portfolio_beta` |
| **No cache at all** | **1** | `get_market_news` |

Two of twenty. The fast pages are the two that hit Turso; everything else re-fetches from scratch on
every page load, every refresh and every cold start. `get_history()` — the heaviest payload in the
app and its biggest single memory allocation — is in the session tier on a 1-hour TTL.

**Measured page cost** (headless `AppTest`, one page per subprocess, caches warm):

| Page | Time |
|---|---|
| Market News | **11,710 ms** — *every visit* |
| Command Center | 750 ms |
| Portfolio Dashboard | 630 ms |
| Performance | **never completed** — still on "Loading 1y data for 181 tickers + 4 benchmarks…" after 10 s in the browser |

### The findings, with the fix for each

**P2-1 · `get_market_news` has no cache, and the cache it should use already exists.**
`CRITICAL / 15 min.` The function body contains zero references to `_cache_get`, `_cache_set` or
`news_cache` — I checked the whole thing. It fans out to nine RSS feeds plus Finnhub on every
single visit. Forty lines above it, `get_portfolio_news()` reads and writes `news_cache` correctly.
→ **Fix:** three lines, copied from the function above it. 11.7 s → ~50 ms warm. Best
benefit-to-risk ratio in the codebase; do this first.

**P2-2 · Performance loads a year of history for every holding, uncached.** `CRITICAL / 1 day.`
185 × 1y daily bars held in memory simultaneously, session-cached only, on a 512 MiB / 0.15 vCPU
instance. This is the "freeze".
→ **Fix:** (a) give `get_history` a durable tier — a `history_cache` table keyed
`(ticker, period, date)`; (b) then bound the page — portfolio NAV comes from `nav_snapshots`, which
is already written daily and needs **no** per-ticker history at all. Per-ticker history belongs on
Deep Dive, one name at a time.

**P2-3 · The same total is computed twelve different ways.** `CORRECTNESS / half a day.`
`market_value.sum()` appears in four distinct coercion styles across eight files — bare `.sum()`,
`to_numeric(errors="coerce").sum()`, `…dropna().sum()`, `to_numeric(df[…]).sum()`. On a clean float
column all four agree. On an **object** column containing an empty string — exactly what an unpriced
line produces — the bare variant raises
`TypeError: unsupported operand type(s) for +: 'float' and 'str'` while the others return the right
number. **Eight sites crash where four degrade.** Demonstrated, not asserted.
→ **Fix:** one `portfolio_totals(df) -> dict` in `cio_engine`, called by Command Center, Dashboard,
Summary, Performance, Risk, Dividends, Earnings, AI Chat and the NAV snapshot in `app.py`. Nine call
sites collapse to one definition of "what the portfolio is worth".

**P2-4 · The Dashboard builds twelve holdings tables to show one.** `HIGH / low risk.`
Measured in the DOM at 375 px: **12 `stDataFrame` widgets and 11 tab buttons** on a single render.
Streamlit tabs are not lazy — every country tab's table is serialised and shipped whether or not it
is opened.
→ **Fix:** replace the tab strip with `st.segmented_control` (or a selectbox) that renders one
table. Eleven twelfths of that work disappears. Pairs naturally with **P3-4**.

**P2-5 · 713 lines of a retired engine survive for one helper.** `TIDY / zero risk.`
`core/prosper_analysis.py` is PROSPER v3.0, retired in favour of GROW v5.1. It is imported exactly
once in the whole codebase: `grow_engine.py:457 → _fetch_finnhub_analyst`. The `prosper_analysis`
*table* is very much alive — it is the GROW verdict store — which is what has been protecting the
module from deletion.
→ **Fix:** move `_fetch_finnhub_analyst` into `finnhub_client.py` where it belongs, delete the file.
−713 lines, zero behaviour change.

**P2-6 · Eight pages independently re-enrich the same portfolio.** `STRUCTURAL / half a day.`
`enrich_portfolio()` is called from nine sites across eight pages, and seven pages each build their
own full holdings table. The enrichment itself is cheap (~0.08 s) — the cost is that each page then
derives its own KPIs from it, which is where the twelve summation variants came from.
→ **Fix:** one `get_portfolio_view()` returning the enriched frame **and** the totals, memoised per
`(portfolio_id, base_currency)`. Do this *with* P2-3, not after it.

**P2-7 · Sentiment is a page nobody waits for.** `HIGH / low risk.` Five sources × 186 holdings,
measured at **>200 s**.
→ **Fix:** restrict to on-demand, single ticker. Nothing that takes three minutes is a signal.

**P2-8 · Insider transactions and institutional holders.** `TIDY / low risk.` Four yfinance calls
per render, on one tab of one page, for data that is quarterly-stale by nature.
→ **Fix:** cut, or move to Finnhub. ~120 lines.

**P2-9 · Sixty lines of CSS styling a widget that no longer exists.** `TIDY / zero risk.`
`app.py` carries twelve `[data-testid="stMetric*"]` rules from before the v7.16 migration.
`st.metric` is down to two uses app-wide.
→ **Fix:** delete the block. It is also the last thing in `app.py` fighting `mobile_shell()` for the
same selectors.

**P2-10 · Two pages share the number 18.** `TIDY, but see the note / 1 hour.`
`18_Equity_Deep_Dive.py` and `18_Risk_Strategy.py`. Harmless under `st.navigation` — but the
`pages/` directory is **also** being auto-discovered. Streamlit logs that warning on every boot, and
a direct page URL bypasses `app.py` entirely, which means the whole design system fails to load
(confirmed in the harness).
→ **Fix:** renumber, and take `pages/` out of auto-discovery. **This is a live suspect for the
"Connecting…" hang** — worth doing before blaming the WebSocket again.

**P2-11 · Top Movers shows zeros instead of an empty state.** `HONESTY / 1 hour.` When day-change
data is missing, the Command Center's Top Movers list fills with `+0.0%` rows in ticker order rather
than saying it has nothing to show.
→ **Fix:** filter rows where change is null or exactly zero; fall back to
`ui_errors.empty_state`. The component already exists.

### What Phase 2 adds up to

| Change | Lines | Effect | Risk |
|---|---|---|---|
| P2-1 cache Market News | +3 | 11.7 s → ~50 ms | none |
| P2-5 delete `prosper_analysis.py` | −713 | no behaviour change | none |
| P2-9 delete dead `stMetric` CSS | −60 | fewer selector collisions | none |
| P2-3 one `portfolio_totals()` | −~90 | one definition of net worth | low |
| P2-2 durable `history_cache` | +~40 | unblocks Performance, Risk, Technical | medium |
| P2-4 one Dashboard table, not twelve | −~50 | ~11/12 of render work | low |
| P2-7 Sentiment on-demand | −~40 | removes a >200 s page | low |
| P2-8 cut insider + institutional | −~120 | 4 yfinance calls/render gone | low |

Roughly **−1,000 lines net**, the two slowest surfaces fixed, and no feature the book actually uses
removed.

### Suggested order

`P2-1` → `P2-11` → `P2-9` → `P2-5` → `P2-10` → `P2-3` + `P2-6` together → `P2-2` → `P2-4` → `P2-7`
→ `P2-8`. The first five are an afternoon and carry almost no risk; they also make the rest easier
to reason about.

---

## 12. PHASE 3 — Mobile rehaul (audited; for a future session)

**Read §11's "shipped / dropped" ledger first.** Four of eleven Phase 2 findings did not survive
inspection. Phase 3 was written by the same 8 Sep review in the same voice — treat every number
below as a *lead to re-measure*, not a fact. Phase 2 has also already moved three of these screens
(Dashboard, Performance, Sentiment), so the original measurement table is partly obsolete.

### STEP 0 for the next session — re-measure, then plan

The 8 Sep screen-count table (below, struck through) predates the Phase 2 pushes. Before touching
anything: bring up the preview harness (§2 — rsync a scratch copy, force
`authentication_status=True`, no-op `run_auth`, seed from `Portfolio Info/`, pre-warm the price and
ticker-info caches, stub `yfinance`), drive it with the browser at `resize_window` preset `mobile`,
and **measure against `[data-testid="stMain"]`, never `document.documentElement`** — Streamlit
scrolls an inner container, so the document's own `scrollHeight` is always just the viewport height.
Scope tap-target counts to `stMain` too (the whole document counts the 32 collapsed-sidebar links).
Screen counts are "screens of scrolling"; under 2.5 is good. Then rebuild the table and the
priority order from what you actually see.

~~8 Sep 2026 — now stale:~~

| Screen | ~~Screens tall~~ | ~~First # at~~ | ~~Sub-44px~~ | ~~Charts~~ | ~~Tables~~ | Note (updated) |
|---|---|---|---|---|---|---|
| Portfolio Summary | ~~1.67~~ | ~~160 px~~ | ~~1/13~~ | ~~5~~ | 0 | unchanged by Phase 2 — 5 donuts still there (P3-4) |
| Command Center | ~~3.62~~ | ~~112 px~~ | ~~15/25~~ | ~~3~~ | 0 | P2-11 fixed the zero-filler movers; layout untouched |
| Portfolio Dashboard | ~~3.49~~ | ~~136 px~~ | — | 0 | ~~12~~ **1** | **P2-4 done**: 12 eager tabs → one `segmented_control`. P3-6's table-count problem is solved; the row-content and hero-dup parts are not. |
| Equity Deep Dive | ~~1.00~~ | — | — | 0 | 0 | P2-8 lightened the Ownership tab; still 7 tabs, still the alpha-sort default ticker (P3-8) |
| Performance | ~~1.00~~ | — | — | — | — | **P2-2 done**: no longer fans out ~180 histories; portfolio line now from `nav_snapshots`. The "never loads" freeze is gone. |
| Risk & Strategy | ~~11.93~~ | ~~168 px~~ | — | 3 | 1 | still long. **4 top-level tabs, not 8** (the audit was wrong) + one nested `st.tabs` in the allocation tab. Re-measure the screen count. |

### Four cross-cutting problems

**P3-1 · The floating "Ask Prosper" button.** `HIGH / 30 min. VERIFIED.` `app.py` renders
`st.popover("💬 Ask Prosper")` styled `position:fixed; bottom:24px; right:24px; z-index:9999`
**after `pg.run()`** (line ~354), and the bottom-nav bar's 5th item is already "Ask" →
`pages/24_AI_Chat.py` (`_NAV_ITEMS` in `ui_components.py`). It overlaps the nav bar, duplicates a
tab, and — because it is after `pg.run()` — it silently vanishes on the 21 pages that call
`st.stop()`. → **Delete the popover block** (`app.py` ~347–430) and the `pg.title != "Ask Prosper"`
guard with it. (P2-10, which this was to be paired with, was dropped — do P3-1 on its own.)

**P3-2 · Em-dash cells take a full grid slot.** `HIGH / half a day. NEEDS RE-MEASURE.` The audit
said Command Center spends two `stat_grid` rows on six figures with three em-dashes (Realized,
Cash, Div/Yr), and the Dashboard does the same (Cash, Cash %, Margin). `stat_grid` is in
`ui_components.py`. → **Make `stat_grid` drop cells whose value is `"—"`/`None`/`""` before it lays
out the grid** — a 2-cell grid beats a 3-cell grid with a hole. One change to the component fixes
every caller. Confirm the current em-dash count in the harness first.

**P3-3 · The Dashboard hero prints twice.** `HIGH / 30 min. PARTLY MITIGATED.` `hero_metric("Total
Portfolio Value", …)` renders once (~line 796 of `2_Portfolio_Dashboard.py`), then
`_render_currency_section` opens with a `stat_grid` whose first cell is `f"{currency_label} value"`
— for the "All" region that is the same number again. P2-4 stopped this rendering 12 times, but the
"All" echo remains. → **In `_render_currency_section`, skip the first `stat_grid` cell when
`currency_label == "All"`** (the page hero already covers it); keep it for a specific region.

**P3-4 · Donuts.** `MEDIUM / 1 day. NEEDS COUNT CHECK.` Portfolio Summary was measured with 5
Plotly donuts, ~330 px each. → A ranked horizontal-bar list carries the same "X% in Y" in a third
of the height, sorts correctly, and skips Plotly's bundle. Under 768 px show bars; above it the
donut is fine. `show_chart`/`mobile_chart` in `ui_components.py` is where a `ranked_bars()` helper
would live. Grep `4_Portfolio_Summary.py` for `go.Pie` / `px.pie` and confirm the count.

### Per-screen actions

**P3-5 · Command Center → the "am I fine?" screen.** `1 day.` Hero once, at the top. Two-cell grid
where every cell carries a number. **Stale-data as first-class content** — "4 holdings unpriced,
ADX feed stale" on the face of the page, not a silent fallback; Phase 1's `Quote.latency` /
provenance classes (`live`/`delayed`/`eod`/`broker_mark`/`stale_cache`, see §6) make this
computable now. Movers show the **money** as well as the percent (`−$4,120`, not just `−1.51%`) —
the enriched frame already has `day_gain`. Optional "Needs a decision" block: GROW ladder breaches
(from `prosper_analysis` rows) + HARVEST earnings blackouts.

**P3-6 · Portfolio Dashboard — finish what P2-4 started.** `half a day now.` The 12-tables-to-1
part is **done** (`segmented_control`, key `dash_region`). Remaining: (a) P3-3's hero de-dup above;
(b) **rows carry quantity and average cost** — `_build_stock_table` / `_build_fund_table` in
`2_Portfolio_Dashboard.py` omit both, and they were specifically asked for; (c) optionally, a
ranked allocation bar list above the picker so the currency split is visible without changing the
selection.

**P3-7 · Risk & Strategy is still too long.** `1 day. RE-MEASURE FIRST.` The audit's "11.93 screens,
8 tabs" is wrong on the tab count — it is 4 (`tab_health`, `tab_sizing`, `tab_alloc`,
`tab_advanced`) plus a nested `st.tabs` inside the allocation tab. The *direction* may still hold:
the regime chip + portfolio-health score are "am I fine?" answers that belong on the Command
Center; position-sizing and allocation-drift are "about to trade" tools. But measure the real
screen count post-Phase-2 before committing to a split — it may just need `stat_grid` fixes (P3-2)
and the nested tabs flattened. Its "Growing" explainer card reportedly duplicates the Command
Center expander verbatim — worth a `grep`.

**P3-8 · Equity Deep Dive default ticker.** `1 hour. VERIFIED (mechanism).` `18_Equity_Deep_Dive.py`
line ~36: `portfolio_tickers = sorted(holdings["ticker"].unique())`, and the picker defaults to
`[0]` — the **alphabetically first** holding, which for this book is a numeric-prefix Asian ticker
(`000660.KS` / `4519.T` / `543895.BO`). If that line can't be priced the page opens on a fetch
error. → **Default to the largest holding by market value** (join `holdings` to the enriched frame
in session, or fall back to the first with a `last_known_price`). Also trim the ~4 lines of prose
above the first control to one line.

**P3-9 · "Connecting…" watchdog.** `unknown.` `connection_watchdog()` (`ui_components.py`, called
`app.py` ~343, before `pg.run()`) is installed. Efficacy still unconfirmed — needs a real phone
left backgrounded, then foregrounded, on a spun-down free-tier instance. P2-10 (the old "do this
first" suspect) was dropped as a non-issue, so if the hang persists the WebSocket / free-tier
cold-start is the remaining suspect; `$7/mo` paid tier removes the spin-down entirely.

### New for Phase 3 — carried from Phase 2

**P3-10 · Durable `history_cache` table.** `medium.` P2-2 removed the Performance page's
180-ticker `get_history` fan-out, but `get_history` is still session-cache-only and still called
per-ticker by **Portfolio Summary** (risk section), **Technical Analysis**, **Equity Deep Dive**
and **`core/portfolio_optimizer.py`**. A `history_cache` table keyed `(ticker, period, date)` with
the read-through wrapper on `get_history` (try new columns / `except` / fall back to a re-fetch —
the additive-migration rule, §4 #12) makes all of those survive a cold start. Untestable without
Turso creds, so ship it with the user watching and a page that exercises it open.

**P3-11 · `st.metric` → design system.** `small, per page.` §5 claims `st.metric` is gone; it is
not — 23 `.metric()` calls remain in `8_Sentiment.py`, `7_Analyst_Consensus.py`, `5_Performance.py`
and `core/grow_render.py` (all as `colN.metric(...)`, which is why the §11 grep missed them).
Convert each cluster to `stat_grid` / `hero_metric`, then the `[data-testid="stMetric*"]` block in
`app.py` can finally go (P2-9, done right this time).

### The design rules (unchanged — these held up)

| Rule | Why |
|---|---|
| One hero per page, near the top | The number the page exists for, once, above 200 px |
| Never render an em-dash cell above the fold | Collapse the grid; 2 real cells beat 3 with a hole |
| Percentages get their money | `−1.51%` means nothing; `−$4,120` is a decision |
| Ranked bars, not donuts, under 768 px | Same information, a third of the height, no Plotly bundle |
| Streamlit tabs are eager | Every hidden tab is built and shipped — use `segmented_control` to render one slice (P2-4 is the worked example) |
| A page over ~4 screens is two pages | Layout tweaks won't save a scope problem |
| Stale data is content, not an exception | Say "4 unpriced, ADX stale" on the face of the page — §6 provenance makes it computable |
| No floating button over the nav bar | It overlaps, and it duplicates a tab |

### Suggested order for the next session

`STEP 0` (re-measure in the harness) → `P3-1` (delete the FAB) → `P3-8` (Deep Dive default) →
`P3-2` (`stat_grid` drops empty cells) → `P3-3` (Dashboard hero de-dup) → `P3-11` (st.metric
cleanup, then finish P2-9) → `P3-6` (qty/avg-cost rows) → `P3-4` (bars for donuts) → `P3-7`
(decide, from real numbers, whether Risk needs splitting) → `P3-10` (`history_cache`) →
`P3-9` (watchdog, needs a phone). The first five are subtraction and low-risk; do them as one or
two pushes and verify each on a phone before the next.

---

## 13. PHASE 3 — mobile rehaul (IN PROGRESS, 9 Sep 2026)

Built against the 9 Sep design review, which audited the 8 Sep proposal and found it wanting:
9/20 on the Impeccable technical audit, 23/40 on Nielsen, 495 detector findings, and — the
disqualifying one — **six numeric self-contradictions in a review whose central charge was that
two pages give different numbers for the same thing.** The rebuilt system scores 19/20 with 0
detector findings. The IA argument from 8 Sep (24 → 11 destinations) survived unchanged; only the
visual system and the components were replaced.

### Shipped and live

| Push | Commit | What |
|---|---|---|
| **1** | `695f4f6` | The floating FAB deleted (app.py, 98 lines) · Quick Navigation deleted (Command Center) · Portfolio Summary's 1,638-call returns block deleted · `stat_grid` drops empty cells · Deep Dive defaults to the largest holding · `fmt_compact` sub-1000 rounding bug fixed |
| **2** | `6a7da75` | `core/ledger_ui.py` — the design system · `design_shell()` wired into `app.py` · Command Center's alert queue converted to ruled rows, sorted by severity, capped at 4 with an explicit overflow row · `scripts/render_ledger_proof.py` |

**Net so far:** four navigation systems → two (sidebar + bottom bar). The last known freeze path
is gone. Nothing visual changed on 23 of 24 pages — Push 2 adds tokens and component classes but
deliberately does not repaint Streamlit's chrome, so unconverted pages are untouched.

### The design system — `core/ledger_ui.py`

Read the module docstring first; it is the spec. Summary:

- **13 colour tokens**, light and dark, every text/ground pair computed ≥4.5:1 (the table is in
  the docstring). One interactive accent, three semantics (`up`/`down`/`watch`) which are
  deliberately *not* the accent, and `mark` — a colourless token for a broker valuation, because
  a mark is not a price and colouring it would imply otherwise.
- **6-step type scale, 12px floor.** The old app has 41 distinct sizes; the v1 proposal put four
  sizes inside 3.5px and nav labels at 9.5px.
- **44px on everything tappable**, pills and buttons included.
- **16 components**, all pure functions returning HTML — testable without Streamlit, which is how
  `scripts/render_ledger_proof.py` can render eight screens offline.
- **Motion:** press 120ms, hover 150ms (gated `hover:hover` so touch does not stick), focus
  instant, skeleton shimmer 1.4s. Nothing else moves, because Streamlit re-runs the whole script
  on every interaction — any entry animation replays on every tap.

`venv/bin/python3 scripts/render_ledger_proof.py out.html` renders the system to a static page.
Every screen calls the real components and reads one shared `BOOK` dict, so the proof cannot
drift from the code and two screens cannot disagree. That constraint is the fix for the v1
contradictions, and it is worth preserving.

### Shipped in Phase 3 so far

| Push | Commit | What landed |
|---|---|---|
| 1 | `695f4f6` | FAB deleted · Quick Navigation deleted · Summary's 1,638-call returns block deleted · `stat_grid` drops empty cells · Deep Dive defaults to the largest holding · `fmt_compact` sub-1000 rounding fixed |
| 2 | `6a7da75` | `core/ledger_ui.py` shipped · `design_shell()` wired · Command Center alert queue → ruled rows, severity-sorted · `render_ledger_proof.py` |
| 3 | `347d3da` | **Fixed the CSS-never-reinjected bug** (see below) · hero eyebrow deleted · stat grids → one ruled block · Top Movers → ledger rows with money at full weight · header band reclaimed |
| 4 | `12eedb6` | Holdings rows carry **position, average cost, day in money + %, unrealised in money + %, dividend yield, ex-date** — four markdown lines inside one tappable button · `ex_dividend_date` mapped · `stat_row` orphan-cell fix |
| 5 | `4c98e0b` | Holdings **Find + Sort** (Value / Today % / Today worst / Unrealized % / Name) · Dashboard hero de-duped (P3-3) · `holdings_rows(presorted=)` |
| 6 | `d2cedae` | P&L attribution chart → ranked rows (**fixes the label clipping**) · Allocation by Sector → `ranked_bars` |
| 7 | `893ebb5` | HANDOFF roadmap |
| 8 | `4efc234` | **Security** — Deep Dive renamed and made the single research entry point; publishes `research_ticker`; drill-down links; nav group "Security — full analysis"; **Research Hub deleted** |
| 9 | `818e498` | **Activity** — Portfolio News + Market News + Earnings + Transactions merged into one page (`pages/9_Activity.py` + `core/activity_views.py`), sliced by segmented control |
| 10 | `7024e09` | CIO briefing leads with pulse + actions, explanation behind a tap (parses, does not re-prompt) · **all 8 donuts → `ranked_bars`** · Summary's 5 eager pie-tabs → one picker with selectbox drill-down |
| 11 | `6c67c17` | **Risk** 4 tabs + nested set → segmented controls · **Income** (renamed from Dividends) 4 tabs → picker, hero de-eyebrowed |
| 12 | `bc5dabf` | **Security** 7 tabs → segmented control · **Peer Comparison** 5 tabs → segmented control |
| 13 | `d2e5262` | **Token sweep + the light flip** — 174 literals mapped to tokens, `ACTIVE_THEME` drives CSS + Plotly + config.toml, zero text colours below 4.5:1 |
| 14 | `2699fb1` | Fixed white-on-white (a `:root:not()` specificity bug beat the light pin on dark-mode phones) · **dark mode shipped** (Settings → Appearance) |
| 15 | `57da6e8` | Loading skeleton, error state with a working retry, designed empty state |
| 16 | `5b2e1db` | Raw markup printed on screen (`value` is escaped, `value_html` is not) · segmented controls themed · bottom bar aligned · `keep_row()` · sector allocation removed from Today |
| 17 | `3fc76bd` | **Built the preview harness and found four bugs no headless test can see** — chiefly that `st.markdown` was TRUNCATING the stylesheet at the first CSS comment, so Push 16's widget rules never reached the browser |
| 18 | `b40eaf0` | Last 23 `st.metric` calls converted, `stMetric` CSS deleted, font unified on IBM Plex Sans · **naming pass** (Today / Holdings / Allocation / Risk / Evaluate / Options / Ask / Add holdings / Connections / Account & access / Setup) |

**The bug worth remembering.** Push 2 guarded `design_shell()` with a session flag. Streamlit
rebuilds the DOM every rerun, so after the first load the stylesheet was never re-emitted and
every component rendered as unstyled divs. `mobile_shell()`'s own docstring warns about exactly
this. **Never guard a CSS injection by session state.**

### One plan change, recorded

The review said "five research pages become one Security page with five tabs".
On inspection that was wrong and Push 8 did something else. Security's tabs are
**5-10x thinner** than the standalone pages they would have absorbed (Peers 57
lines vs Peer Comparison 549; Technical 89 vs 434; Analyst 162 vs 272) — they
are summaries of the same ground, not duplicates of it, so merging would have
deleted real analysis. And **Streamlit tabs are eager**: four deep analyses
would render on every visit to a page most visits never drill past, on a
512MiB/0.15vCPU box.

So Security is the *entry point*, not the container: it publishes
`research_ticker`, its thin tabs link out to the full versions, and the nav
group is named for the relationship. Activity, whose four pages are shallow and
genuinely duplicative, got the real merge — via `segmented_control`, which
renders one slice, not `st.tabs`, which renders all of them.

**The general rule:** merge when the pages duplicate; subordinate when one
summarises the other. Never fold a heavy page into a Streamlit tab.

### st.tabs is gone from the daily path

Pushes 10-12 removed every eager tab set that costs anything: Summary (5),
Risk (4 + a nested 4), Income (4), Security (7), Peer Comparison (5). Streamlit
builds and ships EVERY tab on EVERY render, so Security alone was running a
price-history fetch, a fundamentals pull, an analyst call and a peer batch for
a visit that reads one section.

The replacement is `st.segmented_control` plus a three-line `_Section` class
that is truthy only when selected and is a no-op context manager. `with tab_x:`
becomes `if tab_x:`, no body is re-indented, and an unselected body does not
run. Copy that pattern rather than inventing another.

Only User Management's three per-user tabs remain — admin-only, inside a
collapsed expander, no fetches. Leave them.

### Phase 3 is complete

Every item on the roadmap is shipped. Final state, measured in a real browser
at 375px in both themes:

| | light | dark |
|---|---|---|
| Contrast failures | 0 | 0 |
| Sub-44px tap targets | 0 | 0 |
| `st.metric` widgets | 0 | 0 |
| Horizontal overflow | none | none |

24 destinations became 20 with one navigation system (was four). Every eager
`st.tabs` in the daily path became a `segmented_control`. All 8 donuts became
ranked bars. The token layer replaced 174 hard-coded literals. Light is the
default with a real dark toggle in Settings → Appearance.

### THE VERIFICATION LESSON — read this before any UI change

Pushes 13-17 shipped four visual bugs to production that headless testing
could not catch, because every one was about what the BROWSER computes, not
what Python returns:

* a `:root:not()` selector outranking the theme pin on a dark-mode phone;
* `st.markdown` silently TRUNCATING a `<style>` block at its first CSS comment,
  so an entire push's worth of rules never reached the page;
* `design_shell()` reading the theme before `ensure_settings_loaded()` ran;
* a tap-target rule matching a class Streamlit no longer guarantees.

**The preview harness (§2) is the only thing that finds these.** Build it, drive
it at 375px, and run the DOM audit in BOTH themes before pushing UI. The audit
composites semi-transparent backgrounds over their parents — treating `rgba()`
as opaque produces false positives.

`.harness/` is gitignored: it is a scratch copy with auth bypassed and must
never deploy.

### Two things that are NOT design problems

- **The free-tier cold start (30–60s)** is infrastructure. No layout work touches it; $7/mo does.
  Until then, the loading state in (4) is the only real mitigation.
- **`tests/test_harvest.py` 56/60** — four failures predate Phase 3 entirely. Verified by running
  the suite on a stashed clean tree. Diagnose separately; do not let them block a UI push.
