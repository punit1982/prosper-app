# Prosper — Handoff (6 Sep 2026, current at v7.17)

Paste this whole file into a new chat to continue. Everything below is verified unless marked
otherwise. Version-by-version history lives in `docs/HANDOFF_ARCHIVE.md` — read that only when you
need to know *why* something looks the way it does.

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

`st.metric` is now **gone from every page** (was 78).

Measured on a real 375×812 viewport against the real portfolio: Command Center went from 4.5 screens
with the first number 526px down, to 3.9 screens with it at 118px. The Dashboard went from ~4 to ~15
positions per screen.

Design review + page-by-page plan (published artifact):
`https://claude.ai/code/artifact/fe1423f6-44eb-4103-909f-4c4e495fafc7`

## 6. Data sources — what actually works today

| Source | Status |
|---|---|
| **yfinance** | `chart` works unauthenticated. `quoteSummary` + v7 `quote` return "Invalid Crumb" on a raw call — yfinance 1.7's internal workaround is the only thing keeping `.info` alive, and it has broken once already. |
| **Yahoo `chart` (direct, keyless)** | Added as a fallback between yfinance and Finnhub. Verified pricing PRY.MI / 543895.BO / AAPL / D05.SI / NESN.SW with yfinance fully stubbed. **Use `range=1d`** — over a longer range `chartPreviousClose` is the close before the window, which produced a bogus −47% day move. |
| **Mubasher (UAE ADX/DFM)** | Works from a residential IP. **Behind Cloudflare — 403s datacenter IPs, so it fails on Render.** Every earlier "verified live" was run from a laptop. |
| **Twelve Data** | **Paid "Basic" plan**, ~800/day. Does *not* cover India NSE/BSE, OTC funds, or ADX/DFM ("available starting with Pro or Venture"). Fallback-only. |
| **Finnhub** | Works. US-centric; `/stock/metric` is the US fundamentals fallback. |
| **FMP** | Legacy `/api/v3/*` is dead. `/stable/*` works but is US-only on this key. |
| **IBKR Flex Query** | Works, app-usable (token + query id). This is the only IBKR path the deployed app can use. |
| **IBKR MCP connector** | Has live prices for every UAE/Japan/SGX/CH name — but it authenticates as *the user's own Claude connector*. **The Render app can never call it.** Good for in-session verification only. |
| **FX** | AED/SAR/HKD hard pegs (AED 3.6725) resolve with no network call. Chain: yfinance → `open.er-api.com` → stale DB cache of any age → static table. It never silently returns 1.0 any more. |

**Consequence:** UAE, European/offshore funds and suspended lines have no free live source reachable
from Render. They are valued from IBKR's own `markPrice` via two paths:

  1. `core/ibkr_prices.maybe_daily_refresh()` — Flex Query web service, once per calendar day. Only
     runs if `IBKR_FLEX_TOKEN` + a query id are set. **They are not**, so this is currently a no-op.
  2. `core/ibkr_prices.apply_static_marks_to_holdings()` — reads `data/ibkr_marks.json`, a committed
     snapshot of IBKR's mark for every position, and writes it into `holdings.last_known_price` (the
     durable fallback the price cascade already uses — never wiped by a failed live fetch, unlike a
     `price_cache` row). This is the path that actually runs today. **Refresh the file at the start
     of a working session:** call the IBKR connector's `get_account_positions`, save its JSON, run
     `venv/bin/python3 scripts/refresh_ibkr_marks.py <that file>`, commit, push.

`scripts/prewarm.py` also fetches UAE quotes and runs on a **GitHub Actions runner**, whose IPs
Cloudflare does not block like Render's.

Instruments with genuinely no quote anywhere are listed in `cio_engine.NO_LIVE_SOURCE` (OZON —
suspended ADR; Balasore Alloys; legacy `F0…​.NS` Morningstar fund rows) and are reported as "no market
quote exists" rather than as fetch failures.

## 7. Open items, highest value first

1. **IBKR Flex web service still not configured** (`IBKR_FLEX_TOKEN` + query id). Until it is, the
   committed `data/ibkr_marks.json` snapshot is the price source for UAE/fund/suspended lines —
   see §6. Configuring Flex would make it self-updating; the static file is the stopgap.
2. ~~Nothing back-fills `last_known_price`~~ — `apply_static_marks_to_holdings()` now does, on every
   app start, from `data/ibkr_marks.json`. Keep that file fresh (§6).
3. **Install the pre-warm GitHub Action.** `docs/prewarm-github-action.yml` needs copying to
   `.github/workflows/` plus repo secrets — the push token used in these sessions lacks `workflow`
   scope. This is what kills the slow first load of the morning.
4. **Cold load.** A first load of 182 holdings ran past two minutes locally with no Render cold start
   involved. Pre-warm + a paid instance is the answer.
5. **GROW Annex E calibration** — the archetype premium/required-return table
   (`grow/GROW v5 1 ANNEX E ARCHETYPE LOOKUPS.md`) is a **mechanical linear rescale of pre-compression
   values, explicitly labelled a placeholder**, chosen by Punit as a stopgap. Replace with real
   per-archetype judgment when he is ready. Do not treat the numbers as final.
6. **Full GROW tier (Opus 5, ~$4/name) still not live-tested end to end.** Open question Punit is
   weighing: run full tier on Sonnet 5 instead (~50% cheaper; the deterministic §8 resolver already
   overrides model arithmetic, so only narrative depth changes). A/B it first.
7. **Exhicon (`543895.BO`)** — Yahoo shows ₹258.55 against Trendlyne's ₹469.85 and a 52-week range of
   220–440. That looks like a corporate action; **the share count needs confirming before the position
   value is trusted.**
8. Sweep the remaining ad hoc 🔴/🟡/🟢 into `status_chip()` (Technical Analysis, Sentiment, Analyst
   Consensus, Earnings Calendar, Upload Portal). Low value — these are directional signals, not
   severity states.
9. Never map old PROSPER-era verdicts onto GROW. Every GROW verdict shown must carry Durability +
   Entry arithmetic. Positions are never sent to the engine.

## 8. What verification is and isn't possible here

Achievable and expected: `py_compile` on every touched file; the preview harness at 375×812 and
1280px against the real portfolio; live production Render logs and deploy status via the Render MCP;
live `curl` probes of any data source before believing a claim about it.

**Not achievable from a session:** anything requiring Turso credentials (so no reads or writes against
the production database), and anything requiring Punit's real login. Production checks are limited to
the sign-in page rendering, deploy status, and error-level logs.

**A standing lesson:** "verified live" from a laptop is not the same as verified on Render. The UAE
price bug survived two rounds of fixes because every verification ran from a residential IP. When a
data source is involved, say which network the check ran from.
