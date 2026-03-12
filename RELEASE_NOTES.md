# Prosper Release Notes

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
