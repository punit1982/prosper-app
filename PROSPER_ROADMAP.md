# PROSPER: Strategic Product Roadmap
## AI-Native Investment Operating System
### Last Updated: 2026-03-15

---

## 1. Product Vision

Prosper is a global, unified investment dashboard for high-net-worth individuals and institutional client management. It solves the "fragmented data" problem by ingesting holdings from any global broker and transforming that data into a CIO-level analytical suite powered by AI.

**North Star:** A platform where a CIO opens Prosper in the morning, sees their entire global portfolio health in 2 seconds, reads an AI-generated briefing with action items, and makes better investment decisions in 10 minutes than they could in 2 hours with Bloomberg.

---

## 2. Current State (v5.0 — March 2026)

### Tech Stack
- **Frontend:** Python + Streamlit v1.39+ (dark theme, custom CSS)
- **Database:** SQLite (local, ~/prosper_data/prosper.db) with 10 tables
- **AI Engine:** Anthropic Claude API (Vision for parsing, Chat for analysis/summaries)
- **Model Strategy:** Universal `call_claude()` with automatic fallback across 5 models (claude-opus-4-5, claude-sonnet-4-5, claude-3-5-sonnet-20241022, claude-3-5-haiku-20241022, claude-3-haiku-20240307)
- **API Key Resolution:** `get_api_key()` checks os.getenv first, then st.secrets with 3 fallback patterns (direct, .get(), nested [secrets] table)
- **Data Sources:** yfinance (primary), Finnhub, Twelve Data, ADX/Mubasher, Serper (web search), StockTwits API, Reddit API, Google News RSS, FMP (optional)
- **Auth:** streamlit-authenticator v0.4.2 with bcrypt password hashing, YAML config, optional (PROSPER_AUTH_ENABLED env var)
- **Deployment:** Streamlit Cloud (prosper.streamlit.app) + local dev support
- **Caching:** Multi-layer — SQLite (prices 5min, news 1hr, parse 90d, tickers 24hr) + Streamlit session_state

### Complete Feature Inventory

#### Page 1: Upload Portal (pages/1_Upload_Portal.py)
- **File Types:** PNG, JPG (screenshots), PDF (statements), CSV, XLSX (spreadsheets)
- **AI Parsing:** Claude Vision extracts {Ticker, Name, Quantity, Average Cost, Currency} from brokerage screenshots
- **Broker Hints:** Auto-detect or manual selection (IBKR, Zerodha, HSBC, Tiger, Saxo, Groww, Kotak, etc.)
- **Column Mapping:** 40+ column alias mappings for CSV/Excel auto-detection (e.g., "Avg Price", "Average Cost", "Cost Basis" all map to avg_cost)
- **Exchange Suffixes:** Automatic mapping — .NS (NSE India), .BO (BSE India), .AE (Dubai DFM), .SW (Swiss), .SI (Singapore), .HK (Hong Kong), .L (London)
- **Parse Cache:** SHA256 hash of image → cached result (90-day TTL), same screenshot = instant + zero API cost
- **Editable Results Table:** Inline editing of ticker, name, qty, avg_cost, currency before saving
- **Validation:** Flags missing currency, zero quantity, missing cost basis with color-coded warnings
- **21 Currencies Supported:** USD, EUR, GBP, INR, AED, SGD, HKD, CHF, JPY, AUD, CAD, CNY, KRW, TWD, SAR, QAR, BHD, KWD, OMR, ZAR, SEK
- **Backup & Restore:** CSV download of entire portfolio + CSV upload restore (workaround for Streamlit Cloud data loss)
- **Demo Mode:** If no API key, returns mock holdings (AAPL, MSFT, RELIANCE.NS) so UI can be explored

#### Page 2: Portfolio Dashboard (pages/2_Portfolio_Dashboard.py) — DEFAULT PAGE
- **Live Prices:** 5-source cascade: ADX/Mubasher → Twelve Data → yfinance → Finnhub → fallback
- **Parallel Fetching:** ThreadPoolExecutor (15 workers), 20 stocks in ~5 seconds
- **Failed Ticker Cooldown:** 10-minute cooldown prevents hammering dead symbols
- **Currency Normalization:** Real-time FX conversion to base currency via yfinance FX pairs (5-min cache)
- **Key Metrics Row:** Portfolio Value, Today's Gain/Loss, Unrealized P&L, Realized P&L, Holdings Count
- **Per-Currency Tabs:** Separate tables per currency + "All" aggregate view
- **Dual Tables:** Stocks vs Funds/ETFs shown separately
- **Extended Metrics (on-demand):** 52W High/Low, Forward P/E, Beta, Dividend Yield, Revenue Growth, Earnings Growth, Profit Margin, EPS, ROE, Debt-to-Equity
- **Analyst Data (when extended loaded):** Rating (Strong Buy → Strong Sell), Price Target, Upside %
- **Prosper AI Ratings Integration:** Shows AI score, rating, and upside potential from cached analyses
- **Inline Editing:** Adjust quantity, avg cost, currency directly in the table
- **Color Coding:** Green = positive P&L / buy consensus, Red = negative / sell, Orange = hold / neutral
- **Auto-Refresh:** Prices refresh every 5 min via st.fragment (configurable TTL)
- **NAV Auto-Snapshot:** Saves daily portfolio value to nav_snapshots table
- **Persistent Preferences:** Base currency, column visibility, auto-load settings saved to user_settings.json

#### Page 3: Portfolio News (pages/3_Portfolio_News.py)
- **Smart Tiering:** Top 15 holdings by value loaded first (covers ~80% of typical portfolio), remaining available on-demand
- **ETF/Fund Filtering:** Excludes ETFs and mutual funds from stock news using keyword detection (iShares, Vanguard, SPDR, Invesco, ProShares, WisdomTree, Schwab, First Trust, Global X, PIMCO, JPMorgan Equity, plus "ETF", "FUND", "INDEX", "TRUST" in name)
- **Data Sources:** yfinance news API with 1-hour SQLite cache + warm-start detection
- **AI Summaries:** Per-article Claude-powered summaries (toggle auto-show or on-demand button)
- **Consistent Styling:** All AI output uses "AI Summary" label in st.info() blue boxes
- **Card Layout:** Title, publisher, date, "Read" link button per article
- **Sidebar Controls:** Max articles slider (10-100), auto-show AI summaries toggle (persisted)

#### Page 4: Portfolio Summary (pages/4_Portfolio_Summary.py)
- **5 Pie Charts with Drill-Down:** By Sector, Industry, Currency, Country, Market Cap Size — click any segment to see individual holdings
- **Market Cap Buckets:** Mega (>200B), Large (10-200B), Mid (2-10B), Small (300M-2B), Micro (<300M)
- **Portfolio Returns Table:** 9 time periods (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 3y, 5y, YTD) with CAGR calculation
- **Risk Metrics Panel:** Portfolio Beta, Max Drawdown, Annualized Volatility, Sharpe Ratio, Sortino Ratio — selectable over 1y/2y/3y/5y
- **Parallel History Fetching:** ThreadPoolExecutor (15 workers, 60s timeout) for OHLCV data
- **Weighted Returns:** Market-value-weighted portfolio return calculation

#### Page 5: Performance (pages/5_Performance.py)
- **Benchmark Comparison:** Portfolio returns vs major indices on indexed (base=100) chart
- **Default Benchmarks:** S&P 500 (^GSPC), Nasdaq 100 (^NDX), Nifty 50 (^NSEI), Sensex (^BSESN) — user-selectable, persisted
- **Time Periods:** 5d, 1mo, 3mo, 6mo, 1y, 2y, 3y, 5y, YTD
- **Return Summary Table:** Return %, CAGR for each benchmark vs portfolio
- **NAV History Chart:** Portfolio value over time with cost basis overlay line
- **NAV Metrics:** All-Time High, Drawdown from ATH, Total Return, CAGR
- **Optimization:** Only fetches history for tickers with valid live prices

#### Page 6: Market News (pages/6_Market_News.py)
- **7 Focus Areas:** Global, US Market, India Market, Technology, Energy, Healthcare, Finance
- **Dynamic "My Funds & ETFs":** Automatically builds from portfolio fund holdings
- **Data Sources:** yfinance news API for major indices and sector tickers
- **15-min Cache:** SQLite session-state cache per focus area
- **AI Summaries:** Toggle auto-show or on-demand per article
- **Deduplication:** Removes duplicate headlines by title match

#### Page 7: Analyst Consensus (pages/7_Analyst_Consensus.py)
- **Single-Stock Deep Dive:** Ticker picker from portfolio holdings
- **AI Summary:** Claude summarizes recent analyst activity in 2-3 sentences (top of page)
- **Key Metrics:** Current Price, Target Low/Mean/High, # Analysts, Consensus Upside %
- **Visual Gauge:** Current price positioned within analyst target range (color-coded zones)
- **Rating Summary:** Strong Buy / Buy / Hold / Sell / Strong Sell counts with emoji + conviction score (1-5 scale)
- **Recommendation Breakdown Chart:** Stacked bar by period showing rating distribution
- **Recent Actions Table:** Date, Analyst Firm, Action (Upgrade/Downgrade/Initiated), From Grade, To Grade, Price Target, Prior Target
- **Data Sources:** yfinance (consensus) + Finnhub (upgrade/downgrade history)

#### Page 8: Sentiment Analysis (pages/8_Sentiment.py)
- **5-Source Composite Score:**
  1. News Headlines (30% weight) — yfinance headline sentiment via Claude
  2. StockTwits (15% weight) — bull/bear message ratio with bounds clamping [-1, +1] and thin-data dampening
  3. Reddit (10% weight) — weekly mention counts + top posts
  4. Analyst Consensus (20% weight) — weighted recommendation breakdown (Strong Buy=+1.5, Buy=+1, Hold=0, Sell=-1, Strong Sell=-1.5)
  5. Google News RSS (25% weight) — headline sentiment analysis
- **Dynamic Weight Redistribution:** If a source returns no data, its weight is split proportionally among active sources
- **Portfolio Overview Chart:** Horizontal bar chart (-100 to +100) sorted by sentiment score
- **Summary Metrics:** Average sentiment, most bullish ticker, most bearish ticker
- **Per-Ticker Detail (st.fragment):** Breakdown by source, sample StockTwits messages, Reddit posts, analyst consensus, positive/negative headline lists
- **Color Scale:** Deep red (-100) → orange (-60) → yellow (0) → light green (+60) → deep green (+100), grey for neutral zone (-10 to +10)
- **30-Minute Cache:** Prevents re-fetching on every page interaction

#### Page 12: Transaction Log (pages/12_Transaction_Log.py)
- **Add Transaction Form:** Type (BUY/SELL), Ticker, Date, Quantity, Price, Fees, Currency, Broker, Notes
- **FIFO Accounting:** First-In-First-Out realized P&L calculation
- **Realized P&L Summary:** Net P&L, Total Gains, Total Losses, Total Fees — per-ticker breakdown
- **Transaction History Table:** Filterable by Ticker, Type (All/BUY/SELL), Date Range (All/7d/30d/90d/This Year)
- **CSV Export:** Download transaction history
- **Delete Transactions:** Individual row deletion

#### Page 15: Prosper AI Analysis (pages/15_Prosper_AI_Analysis.py)
- **3 Analysis Tiers:**
  - Quick ($0.008/stock) — Haiku model, pre-fetched data only
  - Standard ($0.04/stock) — Sonnet model, multi-source data, fair value + thesis
  - Full CIO ($0.04+search) — Sonnet + Serper web search, deep thesis
- **Batch Processing:** Analyze entire portfolio in one click with progress bar
- **Smart Skip Logic:** Auto-skips tickers with existing analysis of equal/higher grade within 7-day window
- **Analysis Outputs:** Rating (Strong Buy → Strong Sell), Score (0-100), Archetype, Fair Value, Upside %, Conviction (High/Medium/Low), Thesis, Market Environment (Bull/Neutral/Bear)
- **8 Archetype Taxonomy:** FCF Compounder, Scaling Platform, Pre-Revenue Innovator, Biotech, Cyclical, Turnaround, High-Beta Growth, Deep-Tech
- **7 Scoring Dimensions:** Revenue Growth, Margins, Moat/IP, Balance Sheet, Valuation, Execution, Risk-Adjusted Upside (weights vary by archetype)
- **Color-Coded Results Table:** Green for Strong Buy/Buy, Red for Sell/Strong Sell, styled score bars

#### Page 18: Equity Deep Dive (pages/18_Equity_Deep_Dive.py)
- **360-Degree Single-Stock Research** with sections:
  1. Identity Header — Company name, sector, industry, country, market cap badge
  2. Price & Metrics — Current price, 52W H/L, P/E, Beta, dividend yield
  3. Price Chart — 1-year historical OHLCV with volume bars (Plotly interactive)
  4. Fundamentals — Revenue, EPS, ROE, D/E, FCF, margins
  5. Analyst Consensus — Ratings, price targets, recent upgrades/downgrades
  6. Sentiment — Multi-source score + positive/negative headline breakdown with AI summaries
  7. Ownership — Top insider transactions (buys/sells), institutional holders
  8. Portfolio Position — If in portfolio: quantity, cost basis, current value, unrealized P&L
  9. Prosper AI (on-demand) — Run full analysis for this single stock
- **Data Sources:** yfinance (50+ fields), Finnhub, Serper, Google News RSS

#### Page 0: Settings (pages/0_Settings.py)
- **Display Settings:** Base currency, number format (compact vs full)
- **Data Refresh:** Price cache TTL (1-15 min), parse cache duration (7-365 days)
- **Dashboard Preferences:** Column visibility toggles, auto-load extended metrics, AI summaries
- **API Status Dashboard:** Shows configuration status for each API key (Anthropic required, Finnhub/TwelveData/Serper/FMP optional)
- **Streamlit Cloud Secrets Guidance:** TOML format instructions in expander
- **Data Management:** Clear Price Cache, Clear Parse Cache, Clear News Cache buttons
- **About Section:** Version, stack, data sources, storage path

#### Page 17: User Management (pages/17_User_Management.py)
- **My Profile:** Edit name, email
- **Change Password:** Current → new password flow with bcrypt validation
- **Admin Features:** User directory, create new user, edit user details, reset password, delete user, role assignment (admin/user)
- **Auth Storage:** YAML config file (auth_config.yaml) with bcrypt-hashed passwords

### Core Modules Inventory

#### database.py (871 lines) — 10 SQLite Tables
- `holdings` — Portfolio positions (ticker, name, qty, avg_cost, currency, broker_source)
- `transactions` — Buy/sell trades (FIFO P&L)
- `nav_snapshots` — Daily portfolio value history
- `prosper_analyses` — Cached AI analysis results
- `price_cache` — Live prices (5-min TTL)
- `news_cache` — Aggregated news (1-hour TTL)
- `parse_cache` — Screenshot parse results (90-day TTL)
- `ticker_cache` — Resolved tickers (24-hour TTL)
- `watchlist` — Non-portfolio tracked tickers
- `user_settings` — JSON blob of preferences

#### cio_engine.py (424 lines) — Portfolio Enrichment
- 5-source price cascade: ADX/Mubasher → Twelve Data → yfinance → Finnhub → fallback
- ThreadPoolExecutor (15 workers) parallel price fetching
- Currency normalization to base currency
- Key metrics enrichment (P/E, ROE, D/E, growth, margins)
- Failed-ticker cooldown (10-min) to prevent API hammering

#### data_engine.py (1617 lines) — Central Data Hub
- Ticker info fetching (sector, industry, 52W, forward PE, market cap, growth)
- News aggregation with deduplication
- Analyst recommendations + price targets
- Insider transactions + institutional holders
- Historical OHLCV data for charts and risk calculations
- AI-powered news summarization via Claude
- Ticker suffix resolution (probes .NS/.BO/.AE/.SW/.SI/.HK/.L)
- Crypto mapping (BTC → BTC-USD, ETH → ETH-USD, etc.)
- Hard-coded ticker corrections (e.g., EMIRATESN.AE → EMIRATESNBD.AE)

#### prosper_analysis.py (716 lines) — PROSPER v3.0 Analysis Framework
- 3-tier analysis system (Quick/Standard/Full CIO)
- 8-archetype classification
- 7-dimension scoring with archetype-weighted importance
- Multi-source data aggregation (yfinance + Finnhub + Serper + Google News)
- Structured JSON output parsing from Claude responses

#### social_sentiment.py (316 lines) — 5-Source Sentiment Engine
- News headline sentiment (Claude-powered)
- StockTwits bull/bear ratio (with bounds clamping and thin-data dampening)
- Reddit mention count + top posts
- Analyst consensus (industry-standard weighting: Hold=neutral)
- Google News RSS headline analysis
- Dynamic weight redistribution for missing sources

#### portfolio_optimizer.py (481 lines) — NOT YET IN UI
- Efficient frontier calculation
- Optimal allocation suggestions
- Risk parity allocation
- Constraint support (min/max per stock)
- Uses scipy optimization

#### Other Modules
- `screenshot_parser.py` (238 lines) — Claude Vision AI image/PDF parsing with SHA256 caching
- `currency_normalizer.py` (158 lines) — FX detection + yfinance rate fetching + portfolio conversion
- `settings.py` (198 lines) — Configuration management, `get_api_key()`, `call_claude()` universal caller
- `finnhub_client.py` (144 lines) — Finnhub API wrapper (analyst, recommendations, earnings)
- `twelve_data_client.py` (164 lines) — Twelve Data API for UAE/DFM symbols
- `adx_client.py` (193 lines) — Mubasher intraday CSV for ADX Dubai stocks

### Known Limitations
1. **Data dies on Streamlit Cloud reboot** (ephemeral filesystem wipes SQLite)
2. **13 pages is too many** — fragmented navigation, unclear information architecture
3. **No executive landing page** — user lands on Upload Portal, not a dashboard
4. **No proactive alerts or AI briefings** — user must manually explore each page
5. **Portfolio Optimizer code exists but not wired to UI**
6. **No peer comparison** in equity research
7. **Fair value is single-point estimate** (not 3-scenario range)
8. **No multi-portfolio support** (single portfolio per instance)
9. **No broker direct connect** (screenshot-only ingestion)
10. **Mobile UX is poor** (Streamlit column layouts collapse badly)
11. **No dividend tracking** (ex-dates, yield on cost, income projections)
12. **No earnings calendar** (no alerts for upcoming reporting dates)
13. **No technical analysis** (no moving averages, RSI, MACD, Bollinger Bands)
14. **No tax reporting** (no 1099 export, no wash-sale detection, FIFO only)
15. **No corporate actions** (no split/spinoff/merger tracking)
16. **No audit trail** (no logging of who viewed/modified what)
17. **No role-based data isolation** (all users see all holdings)

---

## 3. Immediate Sprint (v5.1 — Top 5 Priorities)

### Priority 1: Persistent Database (Supabase/Turso Migration)
**Problem:** SQLite on Streamlit Cloud is wiped on every reboot/redeploy. Users lose their entire portfolio.
**Solution:** Migrate to Turso (SQLite-over-HTTP, edge-distributed) or Supabase (PostgreSQL).
**Approach:**
- Create a `core/cloud_db.py` abstraction layer
- Detect environment: local → SQLite, cloud → Turso/Supabase
- Migrate all database.py functions to use the abstraction
- Schema maps directly (holdings, transactions, nav_snapshots, caches, settings)
- Add connection string to Streamlit secrets
**Impact:** Eliminates the #1 user complaint. Data survives reboots, deployments, and scaling.

### Priority 2: Command Center (New Landing Page)
**Problem:** No executive summary. User must click through 5+ pages to understand portfolio health.
**Solution:** Build a "Command Center" as the default landing page.
**Components:**
- **Portfolio Value Card:** Total value, today's P&L ($ and %), base currency
- **Top Movers Strip:** Top 3 gainers and top 3 losers (with sparklines)
- **Alert Strip:** Stocks down >5%, analyst downgrades this week, concentration warnings, earnings in next 7 days
- **Portfolio Heat Map:** Treemap visualization (box size = position weight, color = daily P&L)
- **Quick Stats Row:** Holdings count, currencies, sectors, portfolio beta
- **Daily AI Briefing:** (see Priority 3)
- **Navigation Cards:** Quick links to Research, News, Analysis with "last updated" timestamps
**Design:** Single-scroll page, no sidebar clutter, mobile-friendly card layout.

### Priority 3: Daily AI Briefing
**Problem:** User gets raw data but no synthesized "what should I do?" guidance.
**Solution:** AI-generated morning brief that synthesizes all data sources.
**Briefing Structure:**
1. **Portfolio Pulse** — 1-line health check ("Portfolio up 0.8% today, outperforming S&P by 0.3%")
2. **Top Movers** — Why your biggest gainers/losers moved (news-linked)
3. **Attention Required** — Stocks with material events (earnings, downgrades, sentiment shifts, concentration risk)
4. **Market Context** — 2-line macro summary (Fed, earnings season, sector rotation)
5. **Action Items** — Specific, actionable suggestions:
   - "Consider trimming NVDA (18% of portfolio, above 10% target)"
   - "AAPL reports earnings Thursday — current position is 8% of portfolio"
   - "Analyst downgrade on TSLA from Goldman — review thesis"
**Implementation:**
- Gather: portfolio data, today's P&L, recent news, analyst changes, sentiment shifts, concentration metrics
- Feed to Claude (Opus for quality) with structured prompt
- Cache for 4 hours (or until next manual refresh)
- Display on Command Center as expandable card
**Cost:** ~$0.05-0.10 per briefing (2-3K tokens input, 500-800 output)

### Priority 4: Portfolio Optimizer (Wire Up Existing Code)
**Problem:** `portfolio_optimizer.py` (481 lines) exists with efficient frontier, risk parity, and optimal allocation — but has no UI.
**Solution:** Create a new page/tab that surfaces the optimizer.
**UI Components:**
- **Current Allocation vs Optimal:** Side-by-side bar chart
- **Efficient Frontier Chart:** Scatter plot (risk vs return) with current portfolio plotted
- **Suggested Rebalance Table:** Ticker | Current Weight | Optimal Weight | Action (Buy/Sell) | Amount
- **Risk Parity View:** Equal-risk-contribution allocation
- **Constraints Panel:** Min/max per stock, sector limits, excluded tickers
**Data Flow:** Uses cached enriched portfolio + 1y historical returns (already fetched for Performance page).

### Priority 5: Consolidate Navigation (13 Pages to 5 Sections)
**Problem:** 13 sidebar items overwhelm users. Related features are scattered across different pages.
**Solution:** Restructure into 5 clear sections with internal tabs.

**New Structure:**
```
PROSPER
  Command Center          (new — landing page)
  Portfolio
    Dashboard             (was: 2_Portfolio_Dashboard)
    Summary               (was: 4_Portfolio_Summary)
    Performance           (was: 5_Performance)
    Optimizer             (new — from Priority 4)
  Research
    Equity Deep Dive      (was: 18_Equity_Deep_Dive — anchor page)
    Analyst Consensus     (merge into Deep Dive as tab)
    Sentiment             (merge into Deep Dive as tab)
    Prosper AI            (was: 15_Prosper_AI_Analysis)
  News & Activity
    Portfolio News        (was: 3_Portfolio_News)
    Market News           (was: 6_Market_News)
    Transactions          (was: 12_Transaction_Log)
  Settings
    Configuration         (was: 0_Settings)
    User Management       (was: 17_User_Management)
    Upload Portal         (was: 1_Upload_Portal — moved to Settings since it's infrequent after initial setup)
```

**Implementation Approach:**
- Use Streamlit's `st.tabs()` within pages for sub-navigation
- Reduce sidebar to 5 top-level items
- Upload Portal moves to Settings (it's a setup action, not daily workflow)
- Analyst Consensus and Sentiment become tabs within Equity Deep Dive

---

## 4. Phase 2 Roadmap (v6.0 — April-May 2026)

### Research 2.0
- **Peer Comparison:** Auto-detect sector peers, side-by-side metrics table
- **3-Scenario Fair Value:** Bear/Base/Bull with explicit assumptions and range bar
- **Earnings Calendar:** Upcoming earnings dates for portfolio holdings with IV/expected move
- **Sentiment Momentum:** Trend line (improving/deteriorating vs. last week), not just current score
- **Technical Indicators:** 50/200 DMA, RSI, Bollinger Bands (sidebar overlay on price chart)

### Portfolio Intelligence
- **Dividend Dashboard:** Income tracking (actual + projected), ex-dates, yield on cost, DRIP modeling
- **Correlation Matrix:** Heatmap of cross-holding correlations (true diversification check)
- **Risk Alerts:** Real-time notifications for concentration, drawdown, earnings proximity
- **Multi-Portfolio Support:** Add `portfolio_id` to holdings; personal/spouse/trust/offshore views + aggregate

### Speed & Performance
- **Background Pre-Fetch:** Kick off price fetching on login (before user navigates to Dashboard)
- **Incremental Loading:** Show table immediately, fill extended columns as data arrives
- **Batch yfinance:** Use `yf.download(tickers_list)` instead of individual calls
- **SQLite WAL Mode:** Enable write-ahead logging for concurrent read/write
- **Cache Warming on Deploy:** Health-check endpoint that pre-warms caches after reboot

---

## 5. Phase 3 Roadmap (v7.0-v8.0 — June-August 2026)

### Professional Features
- **Broker Direct Connect:** IBKR Client Portal API, Zerodha Kite Connect, Schwab API
- **PDF Reports:** One-click "Quarterly Review" PDF (Goldman Sachs quality)
- **Excel Export:** Full data dump with formatting and charts
- **Email Digest:** Weekly/monthly portfolio summary email
- **Tax Reporting:** Realized gains/losses, tax-lot accounting, wash-sale detection
- **Corporate Actions:** Split, spinoff, merger tracking with cost basis adjustment

### Platform Scaling
- **Frontend Migration:** Next.js + Tailwind + FastAPI backend (if Streamlit hits UX ceiling)
- **Multi-Tenant / White-Label:** For RIAs and family offices
- **Audit Trail:** Who viewed/modified what, when (compliance requirement)
- **Role-Based Data Isolation:** Per-user portfolio visibility
- **API Layer:** REST/GraphQL API for programmatic access

### AI Evolution
- **ML Sentiment Model:** Train on historical data to predict price movement from multi-source sentiment
- **Macro Scenario Engine:** Portfolio performance under different macro regimes (rates, recession, inflation)
- **Natural Language Queries:** "Show me my most overvalued tech holdings" → instant answer
- **Auto-Rebalance Suggestions:** Weekly AI-generated rebalance recommendations based on drift analysis

---

## 6. Technical Architecture (Target State)

```
                    ┌─────────────────────────┐
                    │     Next.js Frontend     │
                    │  (or Streamlit for MVP)  │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │     FastAPI Backend      │
                    │  (API layer + auth)      │
                    └───────────┬─────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                  │
    ┌─────────▼──────┐  ┌──────▼───────┐  ┌──────▼───────┐
    │   Supabase /   │  │  Redis Cache │  │  Claude API  │
    │   PostgreSQL   │  │  (prices,    │  │  (Vision,    │
    │   (persistent) │  │   news, FX)  │  │   Analysis)  │
    └────────────────┘  └──────────────┘  └──────────────┘
              │
    ┌─────────▼──────────────────────────────────┐
    │           Data Source Layer                  │
    │  yfinance │ Finnhub │ TwelveData │ Serper  │
    │  StockTwits │ Reddit │ Google News │ ADX   │
    └────────────────────────────────────────────┘
```

---

## 7. Competitive Landscape

| Feature | Bloomberg | Sharesight | Wealthica | **Prosper** |
|---------|-----------|------------|-----------|-------------|
| Multi-broker aggregation | Via API | Via API | Via API | **Screenshots + API (planned)** |
| AI-generated analysis | No | No | No | **Yes (3 tiers)** |
| AI daily briefing | No | No | No | **Yes (planned)** |
| Sentiment analysis | Basic | No | No | **5-source composite** |
| Screenshot parsing | No | No | No | **Yes (Claude Vision)** |
| Fair value estimation | No | No | No | **Yes (AI-generated)** |
| Portfolio optimization | Limited | No | No | **Yes (efficient frontier)** |
| Cost | $24K/year | $240/year | $100/year | **TBD** |
| Self-hosted option | No | No | No | **Yes (local SQLite)** |

**Our Moat:** AI-native from day one. Every competitor bolts AI on top. We built the entire analysis pipeline around Claude. The daily briefing + 3-scenario fair value + archetype classification is a combination nobody else offers.

---

## 8. Cost Model (Per User, Monthly)

| Component | Estimated Cost |
|-----------|---------------|
| Claude API (daily briefing, 30 days) | $1.50-3.00 |
| Claude API (batch analysis, 30 stocks/month) | $1.20 |
| Claude API (news summaries, ~200/month) | $2.00 |
| Claude API (screenshot parsing, ~5/month) | $0.50 |
| Supabase (free tier, <500MB) | $0.00 |
| Finnhub (free tier) | $0.00 |
| Serper (2,500 free/month) | $0.00 |
| **Total AI cost per user** | **~$5-7/month** |

At $50/month pricing → **85-90% gross margin.** At scale with caching optimizations, AI cost drops to $2-3/month.

---

## 9. Key Metrics to Track

1. **Time to Insight:** How long from login to first actionable information? (Target: <5 seconds)
2. **Daily Active Usage:** % of users who open Prosper daily (Target: >60%)
3. **AI Briefing Read Rate:** % of users who read the daily briefing (Target: >80%)
4. **Analysis Coverage:** % of portfolio with Prosper AI analysis <7 days old (Target: >90%)
5. **Data Freshness:** Average price cache age at time of user view (Target: <5 min)
6. **Parse Success Rate:** % of screenshots successfully parsed without manual correction (Target: >85%)
7. **User Retention:** 30-day retention rate (Target: >70%)

---

## 10. Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Claude API pricing increases | High | Multi-model fallback, cache aggressively, use Haiku for low-stakes tasks |
| yfinance rate limiting / deprecation | High | Multiple fallback sources already built; add Alpha Vantage as backup |
| Streamlit Cloud instability | Medium | Supabase migration decouples data from hosting; can migrate to Railway/Render |
| Competitor launches similar product | Medium | Speed to market + AI-native architecture is 6-12 month lead |
| Data accuracy issues (wrong prices) | High | Multi-source validation, anomaly detection, user-reported corrections |
| Security breach (user portfolios) | Critical | Move to encrypted DB, add audit logging, implement row-level security |

---

## Appendix A: API Keys Required

| API | Required? | Free Tier | Used For |
|-----|-----------|-----------|----------|
| Anthropic (Claude) | **Required** | No free tier | Vision parsing, analysis, briefings, summaries |
| Finnhub | Optional | 60 calls/min | Analyst data, recommendations, earnings |
| Twelve Data | Optional | 800 calls/day | UAE/DFM stock prices |
| Serper | Optional | 2,500/month | Web search for Full CIO analysis |
| FMP (Financial Modeling Prep) | Optional | 250 calls/day | Fundamental metrics (backup) |

## Appendix B: Database Schema

```sql
-- Core tables
holdings (id, ticker, name, quantity, avg_cost, currency, broker_source, created_at, updated_at)
transactions (id, ticker, type, date, quantity, price, fees, currency, broker, notes, created_at)
nav_snapshots (id, date, total_value, base_currency, holdings_count, created_at)
prosper_analyses (id, ticker, analysis_date, rating, score, archetype, fair_value_base, ...)

-- Cache tables
price_cache (ticker, price, change_val, change_pct, source, fetched_at)
news_cache (cache_key, news_json, fetched_at)
parse_cache (image_hash, result_json, created_at)
ticker_cache (ticker, resolved_ticker, resolved_at)

-- Settings
user_settings (key, value_json, updated_at)
```

## Appendix C: File Structure (Current)

```
prosper/
  app.py                          # Main entrypoint
  requirements.txt                # Dependencies
  PROSPER_ROADMAP.md              # This document
  CLAUDE.md                       # AI coding instructions
  auth_config.yaml                # User credentials
  .env                            # API keys (local)
  .streamlit/config.toml          # Streamlit config
  core/
    database.py                   # SQLite CRUD (871 lines)
    cio_engine.py                 # Portfolio enrichment (424 lines)
    data_engine.py                # Central data hub (1617 lines)
    prosper_analysis.py           # AI analysis framework (716 lines)
    screenshot_parser.py          # Claude Vision parsing (238 lines)
    social_sentiment.py           # 5-source sentiment (316 lines)
    currency_normalizer.py        # FX conversion (158 lines)
    portfolio_optimizer.py        # Efficient frontier (481 lines) — NOT IN UI YET
    settings.py                   # Configuration (198 lines)
    finnhub_client.py             # Finnhub wrapper (144 lines)
    twelve_data_client.py         # Twelve Data wrapper (164 lines)
    adx_client.py                 # Dubai ADX wrapper (193 lines)
  pages/
    0_Settings.py                 # Configuration hub
    1_Upload_Portal.py            # Screenshot/CSV ingest
    2_Portfolio_Dashboard.py      # Live portfolio (DEFAULT)
    3_Portfolio_News.py           # Holdings news
    4_Portfolio_Summary.py        # Diversification analysis
    5_Performance.py              # Benchmark comparison
    6_Market_News.py              # Market-wide news
    7_Analyst_Consensus.py        # Analyst ratings
    8_Sentiment.py                # Composite sentiment
    12_Transaction_Log.py         # Trade history
    15_Prosper_AI_Analysis.py     # Batch AI analysis
    17_User_Management.py         # Admin CRUD
    18_Equity_Deep_Dive.py        # 360-degree research
```

---

*This document should be updated after each major release. It serves as the single source of truth for product direction, technical decisions, and prioritization.*
