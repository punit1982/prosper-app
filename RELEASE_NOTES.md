# Prosper Release Notes

## v7.0.1 — Sign-in fixes (September 5, 2026)

- **"Continue with Google" button had vanished.** Its once-per-run render guard was never
  cleared after v6.6, so from the first rerun of a session onward the button was gone.
  Cleared at the top of every run. (`app.py`)
- **Sign in with your email.** The form asked for a *Username* but accounts are keyed by the
  part before the @ (`punit1982@gmail.com` → `punit1982`). The form now says
  *Email or username* and both work. (`core/auth.py`)
- **Locked out? Admin recovery via Render environment variables** (set, let the service
  restart, sign in, then delete them):
  - `PROSPER_RESET_PASSWORD` = `you@example.com:NewPassword123` — sets that account's
    password (creates the account as admin if it doesn't exist).
  - `PROSPER_CLAIM_LEGACY` = `you@example.com` — moves all pre-multi-user data (holdings,
    transactions, cash, watchlist, NAV history, portfolios) from the legacy `default`
    shard to that account.
- Local setup notes updated for python.org installs (`python3`, new Terminal window).

---

## v7.0 — GROW v5.1 becomes the analysis engine (September 5, 2026)

The PROSPER v3.0 scoring prompt is retired. Every analysis now runs the **GROW v5.1**
framework (`grow/GROW v5 1 CORE 04Sep2026.md` + annexes A/B/C/E, shipped in the repo and
checked by `grow/grow_verify.py`).

### What changes for you
- **Two answers instead of one rating.** *Durability 0–100* — is this worth owning (contains
  no price) — and an *Entry verdict* — STRONG BUY · BUY · HOLD · SELL · STRONG SELL — with the
  four-level price ladder (strong-buy-below / buy-below / fairly-priced / reduce-above).
- **Entry is arithmetic, not opinion.** The app recomputes the verdict, the ladder and the
  ±25% stability test in Python from the model's central case, horizon and required return
  (§8.1–8.4). If the model's own words disagree with its numbers, the arithmetic wins and the
  disagreement is printed under "What I'm not sure about".
- **Three run types.** *Screen* (provider data only, ~$0.10, ~1 min, provisional) ·
  *Standard GROW* (Sonnet 5 retrieves filings via web search, ~$0.60, 2–5 min) ·
  *Full GROW* (Opus 5, deeper retrieval, appendix, ~$2.50).
- **Position-blind** (rule 13): your holdings are never sent to the engine.
- **Continuity** (§11): a re-run is an update — the prior result is passed back and a change
  table is produced.
- **Calibration log** (§12.3): every verdict is appended to `grow_verdict_log` with the price
  it was issued at, so the 12-month read can actually be done.
- **Rule 22:** old PROSPER verdicts are superseded, never mapped — they show as "unrated,
  re-run with GROW".

### Where
- **GROW Engine** page (was "Prosper AI") — batch runs and the rule-21 rating list.
- **Equity Deep Dive** — full memo view for one name, with re-run.
- **Dashboard** — optional columns *Durability · GROW Entry · Buy below*.

### Under the hood
`core/grow_engine.py` (runner + resolver), `core/grow_render.py` (views), new DB columns on
`prosper_analysis`, new table `grow_verdict_log`. Framework text is sent as a cached system
block, so a batch pays for it once. Web tools: `web_search_20260209` / `web_fetch_20260209`.

---

## v6.7 — Stability & Reliability Audit (September 5, 2026)

Full code audit of all 21k lines. Every fix below was reproduced first, then verified
with an automated test suite (32 checks) and a live click-through of the app.

### 🔴 Critical bugs fixed
- **Email/password sign-in was broken** for every user (`KeyError: 'password'`). The v6.6
  hardening removed the password hash from the in-memory credentials that
  streamlit-authenticator needs. Hashes are now kept in memory only and still never
  written to disk. (`core/auth.py`)
- **Brand-new database crashed on first start** (`no such column: portfolio_id`) — indexes
  were created before the migration that adds the column. Indexes now run after
  migrations, each one best-effort. (`core/database.py`)
- **All AI features pointed at retired Claude model IDs** (`claude-3-5-haiku-*`,
  `claude-sonnet-4-2025*`, a non-existent `claude-haiku-4-5-20250514`). Updated to the
  current generation (Sonnet 5 / Opus 5 / Haiku 4.5) in one place, and responses are now
  read with `extract_text()` because current models can return a thinking block before
  the text (`response.content[0].text` would crash). (`core/settings.py` + all call sites)
- **Dashboard showed stale holdings after every upload / edit / delete** until logout —
  the cache-invalidation key prefix never matched the real key. (`core/database.py`)
- **Local/dev mode (`PROSPER_AUTH_ENABLED=false`) rendered a blank page.** (`core/auth.py`)

### 🟠 Data-integrity & multi-user fixes
- **Saved preferences were never loaded at startup** — base currency and column choices
  reverted to defaults after every restart/redeploy. They now load once per session.
- **Preferences were shared between all logged-in users** (one global dict). `SETTINGS` is
  now per-session; saved per user in the database. (`core/settings.py`)
- **AI CIO briefings leaked between users** — briefings are now saved and read per user.
- **Only one user could store a daily NAV snapshot** (legacy `UNIQUE(date, currency)`).
  Table is migrated in place, keeping all history. (`core/database.py`)
- **Turso writes with NaN values were silently rejected** (NaN is not valid JSON) — NaN/inf
  now store as NULL, numpy numbers are typed correctly. (`core/db_connector.py`)
- **UAE tickers resolved as `TICKER:ADX` were never routed to Twelve Data.** (`core/cio_engine.py`)
- Onboarding "Go to Command Center" used an invalid page path. (`pages/26_Onboarding.py`)
- OAuth callback page now uses the same signing key as the main app in local dev.

### ⚡ Speed & latency
- **Timeouts were not real.** Every parallel fetch (prices, FX, ticker resolution,
  fundamentals, news, RSS) waited for *all* threads to finish when the `with` block closed,
  so one hung ticker could freeze a page for minutes. New `core/parallel.py` enforces hard
  deadlines and abandons stragglers. Concurrency raised 5→6 for quotes/news, 3→5 for RSS.
- Removed the dead Reuters RSS feed (DNS no longer resolves).
- "Reset to Defaults" in Settings now also clears the database copy (previously a no-op on Render).

### 🧭 Local setup
- `run.sh`, `.claude/launch.json`, and `QUICKSTART.md` now point at this folder and a local
  `venv/` (they referenced the old `~/Documents/Prosper with Claude March 2026` path).

---

## Phase 3 — User Experience & Preferences (March 12, 2026)

### ✨ New Features

#### a) Persistent User Preferences
- **Dashboard:** Column toggles (Day Gain, Unrealized P&L, Extended Metrics, Growth, Broker) now persist across sessions
- **Performance:** Time period and benchmark selections save automatically
- **News Pages:** Auto-summarize and max-articles settings are remembered
- All preferences stored in `~/prosper_data/user_settings.json` — survives browser restarts and app updates

#### b) Insider Activity Page — Clean Error Handling
- Removed debug traceback expander (non-technical users won't see stack traces)
- **Fund/ETF Detection:** Identifies Funds and ETFs automatically and shows appropriate message instead of empty data
- User-friendly error messages replace silent failures
- Shows basic fund info (Fund Family, Category, Assets Under Management) when available

#### c) Portfolio Dashboard — Consensus Ratings & Upside/Downside
When "Load Extended Metrics" is clicked, each stock displays:
- **Rating Column:** Strong Buy / Buy / Hold / Sell (color-coded for quick scanning)
- **Target Price:** Analyst mean price target
- **Upside %:** Percentage gain/loss to target (green = room to grow, red = already expensive)

#### d) Portfolio Dashboard — Currency Tabs
- **Single view:** Grand total metrics at top (all currencies combined)
- **Multi-currency:** One tab per currency showing per-currency summary + holdings table
- **Tab labels:** Include currency code, portfolio value, and holding count for quick reference
- Eliminates need for global currency filter — now you see all currencies at a glance

#### e) Funds & ETFs Separation
**Detection:** Uses yfinance `quoteType` field (EQUITY / ETF / MUTUALFUND)

**Dashboard:**
- Stocks and Funds/ETFs shown in separate tables within each currency tab
- Stock table: Rating, Target, Upside %, P/E, Beta, Growth metrics
- Fund table: Category, Fund Family, Expense Ratio, AUM, YTD/3Y/5Y returns

**Portfolio News:**
- Funds/ETFs excluded from stock news (reduces clutter)
- Shows "Excluded N Funds/ETFs" note with link to Market News

**Market News:**
- New "📊 My Funds & ETFs" focus option auto-appears when you have funds in portfolio
- Fetches news specifically for your fund holdings
- Shows clear info banner explaining this is fund-specific coverage

---

## Phase 2 — Portfolio Management (March 12, 2026)

### ✨ New Features
- **Settings UI** (`pages/0_Settings.py`) — User preferences, API status, cache management
- **Transaction Log** (`pages/12_Transaction_Log.py`) — Record trades, FIFO realized P&L, transaction history
- **Export Reports** (`pages/13_Export.py`) — CSV/Excel export with combined multi-sheet reports
- **Watchlist** (`pages/14_Watchlist.py`) — Track potential investments with target prices and upside calculations
- **NAV History** — Daily portfolio value snapshots on Performance page with ATH, drawdown, CAGR
- **Risk Metrics** — Portfolio Beta, Max Drawdown, Volatility, Sharpe Ratio, Sortino Ratio on Portfolio Summary
- **Realized P&L Card** — 5th summary card on Dashboard showing net gains/losses from closed positions
- **Auto-Snapshot** — Portfolio NAV saved daily (once per day per currency) when you visit Dashboard

---

## Phase 1 — Bug Fixes (March 11, 2026)

### 🐛 Fixes
- **Insider Activity:** Added try/except error handling, renamed columns, removed debug screens
- **Institutional Ownership:** Rewritten with metric cards (dark theme text visibility fix), white pie chart text
- **Analyst Consensus:** Inverted rating scale so 5=Strong Buy, 1=Strong Sell (higher=better conviction)
- **Ownership Breakdown:** Fixed column width and text visibility issues in dark theme

---

## Technical Details

### Files Modified (Phase 3)
- `core/settings.py` — 11 new preference keys
- `pages/2_Portfolio_Dashboard.py` — Major v4 rewrite (currency tabs, consensus, fund separation, preferences)
- `pages/9_Insider_Activity.py` — Error handling, fund detection
- `pages/3_Portfolio_News.py` — Fund exclusion, preference persistence
- `pages/6_Market_News.py` — Fund section, preference persistence
- `pages/5_Performance.py` — Preference persistence

### Database Schema
- No schema changes in Phase 3 (all Phase 2 tables still used)
- Extends Phase 2's `quote_type` detection for fund classification

### Dependencies
- No new packages required in Phase 3
- Phase 2 added: `openpyxl>=3.1.0` (already included in requirements.txt)

---

## How to Use New Features

### Persistent Preferences
1. Change any sidebar setting (checkboxes, sliders, multiselect)
2. Setting auto-saves — nothing extra needed
3. Close browser, restart app → your choices are remembered

### Consensus Rating on Dashboard
1. Go to Portfolio Dashboard
2. Click "📊 Load Extended Metrics"
3. Wait ~15 seconds for analyst data to load
4. New "Rating", "Target", "Upside %" columns appear
5. (Or check "Auto-load Extended Metrics" to skip step 2)

### Currency Tabs
1. If you have multiple currencies, scroll down past summary cards
2. Each currency gets its own tab
3. Click tab to see that currency's holdings + summary
4. Top 5 summary cards still show portfolio totals (all currencies)

### Market News for Your Funds
1. If you have ETFs/Funds in portfolio, go to Market News
2. "📊 My Funds & ETFs" option appears in the Focus dropdown
3. Select it to see news for your specific funds

### Insider Activity for Stocks Only
1. Select a stock on Insider Activity page
2. See insider transactions + metrics
3. Select a Fund/ETF → gets a clear message + fund info instead

---

## Browser Cache Clearing

If you experience stale data after upgrade:
1. Go to Settings page
2. Click "Clear Price Cache" and "Clear Parse Cache" buttons
3. Or manually: Cmd+Shift+Delete (or Ctrl+Shift+Delete on Windows) → Clear browsing data → All time

---

## Known Limitations

- **Market News Fund Coverage:** Only shows news for funds in your portfolio (doesn't auto-discover new ones)
- **Insider Activity:** Only works for stocks; Funds/ETFs don't have insider transaction data (by design)
- **Consensus Ratings:** Requires "Load Extended Metrics" to be clicked (not automatic due to API rate limits)

---

## Next Steps (Phase 4 - Planned)

- Real-time price notifications
- Advanced portfolio rebalancing tools
- Tax-loss harvesting recommendations
- API integrations for direct broker connections (vs manual screenshots)

---

**Built with:** Python · Streamlit · yfinance · SQLite · Plotly
**Last Updated:** March 12, 2026
**Version:** 3.0 (Phase 3 complete)
