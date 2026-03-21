# Prosper — Product Documentation

**Version:** 5.3
**Last Updated:** March 2026
**Classification:** Product Owner Reference

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Architecture](#2-architecture)
3. [Feature Catalog](#3-feature-catalog)
4. [PROSPER Analysis Framework](#4-prosper-analysis-framework)
5. [FORTRESS Risk Framework](#5-fortress-risk-framework)
6. [Data Architecture](#6-data-architecture)
7. [Security and Privacy](#7-security-and-privacy)
8. [Configuration](#8-configuration)
9. [Deployment](#9-deployment)
10. [Code Structure](#10-code-structure)

---

## 1. Product Overview

### What Is Prosper?

Prosper is an AI-native investment operating system designed for high-net-worth individuals and institutional client managers. It consolidates fragmented brokerage data into a single, CIO-grade analytical dashboard.

### Who Is It For?

- **High-net-worth individuals** managing multi-broker, multi-currency portfolios across global markets (US, India, UAE, Europe, Asia).
- **Family office managers** who need consolidated views of holdings spread across IBKR, Zerodha, HSBC, Tiger, and other brokers.
- **DIY investors** who want institutional-quality analysis (risk frameworks, AI scoring, fair value estimates) without paying for Bloomberg Terminal.

### What Problems Does It Solve?

1. **Fragmented Data** — Holdings scattered across 3-5 brokers with no unified view. Prosper ingests screenshots, CSVs, Excel files, and PDFs from any broker worldwide and merges them into one portfolio.
2. **No Risk Framework** — Retail investors lack systematic risk management. Prosper provides the FORTRESS framework with regime detection, circuit breakers, position sizing, and health scoring.
3. **Shallow Analysis** — Free tools give P/E and a chart. Prosper provides AI-powered equity scoring (PROSPER framework) with 8 archetypes, 7 dimensions, fair value estimates, and conviction ratings.
4. **Manual Currency Conversion** — Global portfolios require constant FX math. Prosper auto-detects trading currencies from ticker suffixes and converts everything to a chosen base currency in real-time.
5. **No Actionable Guidance** — Most dashboards show data but do not tell you what to do. Prosper's Command Center provides AI briefings, regime-aware position guidance, rebalancing triggers, and circuit breaker alerts.

---

## 2. Architecture

### Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Frontend/UI** | Streamlit (Python) | Multi-page web app with sidebar navigation, interactive charts, data tables |
| **AI Engine** | Anthropic Claude API (Sonnet, Haiku, Opus) | Screenshot parsing (Vision), equity analysis (PROSPER), AI chat, news summaries, briefings |
| **Database** | SQLite (local) / Turso (cloud) | Holdings, transactions, analyses, price cache, NAV snapshots, settings |
| **Data Sources** | yfinance, Finnhub, Serper (Google Search), Google News RSS | Live prices, fundamentals, analyst consensus, news, web context |
| **Price Feeds** | yfinance (primary), Finnhub (fallback), Twelve Data (UAE/DFM), Mubasher/ADX (Abu Dhabi) | Multi-source price cascade with automatic failover |
| **FX Rates** | yfinance | Live currency conversion via Yahoo Finance FX pairs |
| **Charting** | Plotly | Interactive financial charts, heatmaps, efficient frontier, technical indicators |
| **Authentication** | Streamlit Cloud SSO, streamlit-authenticator (local) | 3-tier auth system |
| **Optimization** | SciPy | Modern Portfolio Theory, efficient frontier, max-Sharpe optimization |

### Deployment Targets

- **Local Development** — `streamlit run app.py` with SQLite database at `~/prosper_data/prosper.db`
- **Streamlit Cloud** — Deployed with Turso cloud database, secrets managed via Streamlit Cloud dashboard

### Key Design Principles

- **Local-First** — All financial data stays on the user's machine (SQLite). Cloud deployment uses Turso with encrypted HTTP API.
- **Progressive Enhancement** — Core features (dashboard, holdings) work without any API keys. AI features activate when API keys are provided.
- **Parallel Data Fetching** — All price fetches, FX lookups, and data enrichment use ThreadPoolExecutor for sub-5-second load times on 20+ stock portfolios.
- **Session Caching** — Enriched portfolio data, ticker info, and news are cached in `st.session_state` with per-type TTLs to eliminate redundant HTTP calls when switching pages.
- **Graceful Degradation** — If yfinance fails for a ticker, Finnhub is tried. If Finnhub fails, the ticker is marked as failed with a 10-minute cooldown. The app never crashes on missing data.

---

## 3. Feature Catalog

### 3.1 Command Center (Home Page)

**File:** `pages/00_Command_Center.py`

The Bloomberg-style executive dashboard. This is the landing page after login.

**Sections:**
- **Market Context Bar** — Shows current FORTRESS regime (Growing / Heating Up / Slowing Down / Bouncing Back), holdings count, currency count, cash position.
- **Portfolio Pulse** — Total value, unrealized P&L, day gain/loss, realized P&L, cash positions, net portfolio value. All displayed as metric cards with delta indicators.
- **Performance Heatmap** — TreeMap visualization showing each holding sized by market value and colored by day change percentage. Sector grouping when available.
- **Top Movers** — Biggest winners and losers of the day with percentage change bars.
- **Sector Allocation** — Donut chart showing portfolio distribution across sectors.
- **AI Briefing** — AI-generated daily briefing covering market regime, portfolio health, top opportunities, and risks. Persisted to database (survives page refresh). Generated via Claude Sonnet with full portfolio context.
- **Regime Explanation** — Plain-English description of what the current market regime means and what actions to take.

### 3.2 Portfolio Dashboard

**File:** `pages/2_Portfolio_Dashboard.py`

The core holdings table with live prices, P&L, and configurable columns.

**Features:**
- **Live Price Enrichment** — Fetches prices for all holdings in parallel using SQLite-backed price cache. Second load is instant (only re-fetches stale tickers >5 minutes old).
- **Currency Tabs** — One tab per portfolio currency (USD, INR, AED, etc.) with currency-specific totals.
- **Configurable Columns** — Sidebar checkboxes to show/hide: Day Gain, Unrealized P&L, Extended Metrics (52W H/L, Forward PE, Analyst Target), Growth & Financials, Prosper AI Ratings, Broker source. Preferences persist across sessions via `user_settings.json`.
- **Extended Metrics** — On-demand fetch of 52-week range, forward P/E, analyst consensus, revenue growth, profit margins, ROE, dividend yield, market cap, beta. Works for both individual stocks and ETFs/funds (with fund-specific metrics).
- **Cash & Margin Management** — Sidebar section to add/remove cash and margin positions. Auto-detects margin rates from known broker rate tables (IBKR, Schwab, TD Ameritrade, Fidelity). Calculates annual margin cost.
- **Force Retry** — Button to clear failed-ticker cache and price cache, forcing a full re-fetch of all prices.
- **Summary Metrics** — Total portfolio value, total cost, unrealized P&L (amount and %), day gain, realized P&L, net cash, all in chosen base currency.

### 3.3 Upload Portal

**File:** `pages/1_Upload_Portal.py`

Multi-format portfolio ingestion supporting any global broker.

**Supported Formats:**
- **Screenshots (PNG/JPG)** — Parsed using Claude Vision AI. Extracts ticker, name, quantity, average cost, and currency from brokerage screenshots of any layout.
- **CSV files** — Auto-maps columns using alias detection (e.g., "qty", "shares", "units" all map to quantity). Supports 6+ aliases per field.
- **Excel files (XLSX)** — Same auto-mapping as CSV.
- **PDF files** — Parsed using Claude Vision AI (converted to image first).

**Key Features:**
- **Parse Cache** — SHA-256 hash of each image is stored. Uploading the same screenshot again returns instant results with zero API cost. Cache TTL: 90 days (configurable).
- **Cash/Margin Detection** — Lines containing "cash", "margin", "sweep", etc. are auto-detected and routed to cash positions rather than stock holdings.
- **Multi-Currency Support** — 21 currencies supported (USD, AED, INR, EUR, GBP, CHF, SGD, HKD, JPY, CNY, AUD, CAD, SAR, KWD, QAR, BHD, OMR, ZAR, MYR, KRW, BRL).
- **Broker Source Tagging** — Each upload is tagged with the broker source for tracking provenance.
- **Review Before Save** — Parsed data is displayed in an editable table. Users can modify, delete rows, or change currencies before saving to the database.

### 3.4 Risk & Strategy

**File:** `pages/18_Risk_Strategy.py`

Unified portfolio governance page combining FORTRESS risk management with Portfolio Optimizer.

**Sections:**
- **Market Regime Panel** — Sidebar with editable market signals (VIX, PMI, Credit Spread, Yield Curve, Core CPI, Fed Direction). Regime detection runs in real-time as signals are adjusted. Signals persist to database.
- **Regime Dashboard** — Shows detected regime with plain-English name, confidence level, color-coded status, explanation, and recommended actions.
- **Portfolio Health Score** — 10-dimension scorecard (regime alignment, exposure compliance, concentration, factor balance, correlation, liquidity, drawdown, PROSPER average, kill risks). Each dimension is green/amber/red with an overall score out of 10.
- **Exposure Compliance** — Checks portfolio metrics against regime-appropriate limits for gross exposure, net exposure, cash allocation, single-name concentration, sector concentration, and geo concentration.
- **Position Sizing Guidance** — For each holding, calculates FORTRESS-recommended position size using Half-Kelly formula adjusted for regime, conviction tier, and PROSPER score. Shows current weight vs. recommended weight with trim/add guidance.
- **Circuit Breaker Status** — Portfolio-level breakers (Yellow at -5%, Orange at -10%, Red at -15%, Critical at -20%) and single-name breakers (-15%, -25%, -35%). Shows current drawdown level and active alerts.
- **Allocation Comparison** — Compare current portfolio against 7 model portfolios (Ray Dalio All-Weather, 60/40 Classic, Yale Endowment, Balanced Growth, Growth, Aggressive Growth, Conservative Income). Shows overweight/underweight by asset class.
- **Concentration Warnings** — Flags single stocks >10%, sectors >30%, countries >50%, and top-5 >50%.
- **Efficient Frontier** — Modern Portfolio Theory visualization showing current portfolio position relative to the efficient frontier. Requires scipy. Shows risk (volatility) vs. return with the optimal (max-Sharpe) portfolio highlighted.
- **Optimal Portfolio** — Calculates the maximum-Sharpe-ratio allocation using scipy.optimize and shows the recommended weight for each holding.

### 3.5 Portfolio Summary

**File:** `pages/4_Portfolio_Summary.py`

Diversification analysis with interactive breakdown charts.

**Breakdowns:**
- **By Sector** — Donut chart with sector classification. ETFs/funds are classified by category (e.g., "Fixed Income Fund", "Technology ETF") rather than defaulting to "Other".
- **By Industry** — More granular than sector. Uses yfinance industry field with fallback heuristics.
- **By Currency** — Shows allocation across trading currencies before base-currency conversion.
- **By Country** — Geographic allocation using yfinance country data with fallback based on ticker suffix.
- **By Market Cap** — Mega Cap (>$200B), Large Cap (>$10B), Mid Cap (>$2B), Small Cap (>$300M), Micro Cap.

**Additional Metrics:**
- CAGR, Max Drawdown, Sharpe Ratio, Sortino Ratio, Portfolio Beta, Portfolio Volatility (when NAV history is available).

### 3.6 Equity Deep Dive

**File:** `pages/18_Equity_Deep_Dive.py`

Single-stock 360-degree research view. The most comprehensive per-stock page.

**Sections:**
1. **Identity Header** — Company name, ticker, sector, industry, country (with flag), market cap badge, exchange.
2. **Price & Valuation** — Current price, day change, 52-week range with position indicator, market cap, P/E, P/B, P/S, PEG, EV/EBITDA.
3. **Interactive Price Chart** — Candlestick chart with volume bars, configurable time periods (3mo to 5y).
4. **Fundamentals Panel** — Revenue, EBITDA, Free Cash Flow, profit margins, operating margins, ROE, ROA, debt-to-equity, current ratio. Displayed with "money" formatting (e.g., "$2.4B").
5. **Analyst Consensus** — yfinance analyst target (mean, low, high), number of analysts, recommendation key. Finnhub upgrade/downgrade history.
6. **Sentiment** — News sentiment indicators.
7. **Ownership** — Insider transactions (recent buys/sells), institutional holders, major holders breakdown.
8. **Portfolio Position** — If the stock is in the user's portfolio: quantity, average cost, market value, unrealized P&L.
9. **PROSPER AI Analysis (On-Demand)** — Runs the full PROSPER analysis for the selected stock. Tier selector (Quick/Standard/Full CIO). Displays archetype, score, fair value targets, thesis, risks, catalysts.

### 3.7 Prosper AI Analysis (Batch)

**File:** `pages/15_Prosper_AI_Analysis.py`

Batch PROSPER analysis for the entire portfolio.

**Features:**
- **Tier Selector** — Quick ($0.008/stock, Haiku), Standard ($0.04/stock, Sonnet), Full CIO ($0.04+search, Sonnet).
- **Cost Estimator** — Shows estimated API cost before running.
- **Skip Logic** — Automatically skips tickers with recent analysis of equal or higher tier (within 7 days).
- **Progress Bar** — Real-time progress with ticker name and count.
- **Results Dashboard** — Sortable table with rating badges, score bars, archetype, conviction, fair value, upside, thesis, risks, catalysts. Color-coded ratings (Strong Buy green through Strong Sell red).
- **Persistence** — All analyses are saved to the `prosper_analysis` database table and available across sessions.

### 3.8 Technical Analysis

**File:** `pages/21_Technical_Analysis.py`

Single-stock technical chart with overlay indicators.

**Indicators Calculated:**
- **Moving Averages** — SMA 20, SMA 50, SMA 200, EMA 12, EMA 26
- **RSI** — 14-period Relative Strength Index with overbought (70) and oversold (30) lines
- **MACD** — MACD line, signal line, histogram
- **Bollinger Bands** — 20-period, 2 standard deviations
- **ATR** — 14-period Average True Range
- **Volume** — Volume bars with color coding

**Chart Layout:**
- Multi-panel Plotly chart with candlestick + overlays in main panel, RSI in sub-panel, MACD in sub-panel, volume at bottom.

### 3.9 Analyst Consensus

**File:** `pages/7_Analyst_Consensus.py`

Per-stock analyst ratings, price targets, and recommendation history.

**Features:**
- Ticker selector with search filter across portfolio holdings.
- AI-generated summary of recent analyst actions (upgrades/downgrades) using Claude.
- Analyst price target distribution (low, mean, high) with current price overlay.
- Recommendation trend over time.
- Recent upgrade/downgrade history table with firm names, dates, and grade changes.

### 3.10 Peer Comparison

**File:** `pages/23_Peer_Comparison.py`

Side-by-side fundamental comparison against sector peers.

**Features:**
- Auto-detects sector peers from a curated list of well-known companies per sector (Technology, Financial Services, Healthcare, Energy, etc.).
- Compares P/E, P/B, P/S, EV/EBITDA, revenue growth, profit margins, ROE, debt-to-equity, dividend yield, market cap, beta.
- Radar chart and bar chart visualizations for easy comparison.
- Supports manual ticker entry for comparing against any stock.

### 3.11 Dividend Dashboard

**File:** `pages/22_Dividend_Dashboard.py`

Income tracking, yield analysis, and dividend projections.

**Features:**
- **Dividend Summary** — Total annual dividend income, portfolio-weighted yield, number of dividend-paying holdings.
- **Per-Stock Detail** — Dividend rate, yield, ex-dividend date, payout ratio, 5-year average yield.
- **Upcoming Ex-Dates** — Calendar view of upcoming ex-dividend dates.
- **Income Projection** — Estimated annual income based on current holdings and declared dividend rates.
- **Yield Analysis** — Sector-level yield breakdown.

### 3.12 Earnings Calendar

**File:** `pages/20_Earnings_Calendar.py`

Upcoming earnings dates for portfolio holdings.

**Features:**
- Fetches earnings dates from yfinance for all holdings.
- Shows days until next earnings report.
- Displays trailing EPS, forward EPS, and analyst recommendation.
- Sorted by nearest earnings date.
- Sector and market cap context for each holding.

### 3.13 Portfolio News

**File:** `pages/3_Portfolio_News.py`

Aggregated news for portfolio holdings.

**Features:**
- Fetches recent news articles for each ticker in the portfolio.
- AI-powered news summarization (optional, using Claude).
- Grouped by ticker with sentiment indicators.

### 3.14 Market News

**File:** `pages/6_Market_News.py`

Broader market and sector news.

**Features:**
- Market-wide news from major indices and sectors.
- AI summary option for quick digest.

### 3.15 Ask Prosper (AI Chat)

**File:** `pages/24_AI_Chat.py`

Natural-language portfolio assistant powered by Claude.

**Features:**
- Full chat interface with message history.
- System prompt includes: portfolio summary (holdings count, total value, P&L), top 10 holdings with weights, sector allocation, and recent PROSPER analyses.
- Can answer questions about specific holdings, portfolio allocation, market conditions, and general investment topics.
- Never gives explicit buy/sell advice — frames responses as analysis.
- Uses the same `call_claude` function with model fallback chain.

**Floating Widget:**
- A mini chat popover appears on every page (bottom-right corner) when an Anthropic API key is configured. Provides quick 2-3 sentence answers. Links to full chat page.

### 3.16 Transaction Log

**File:** `pages/12_Transaction_Log.py`

Record and view buy/sell transactions.

**Features:**
- Manual transaction entry with ticker, type (buy/sell), quantity, price, date, fees, broker source, notes.
- Transaction history table with filtering.
- Realized P&L calculation from closed positions.

### 3.17 Performance Tracking

**File:** `pages/5_Performance.py`

Historical portfolio performance with benchmark comparison.

**Features:**
- NAV history chart from daily snapshots (auto-captured by `app.py` on each visit).
- Benchmark comparison against configurable indices (S&P 500, Nasdaq 100, Nifty 50, Sensex, FTSE 100, DAX, Hang Seng, Nikkei 225).
- Performance metrics: CAGR, max drawdown, Sharpe ratio, Sortino ratio.
- Period selector (3mo, 6mo, 1y, 2y, 5y).

### 3.18 Sentiment

**File:** `pages/8_Sentiment.py`

Social and news sentiment analysis for portfolio holdings.

### 3.19 Settings

**File:** `pages/0_Settings.py`

Application configuration page.

**Configurable Items:**
- Base currency selection.
- API key management (display status, link to where to get keys).
- Column visibility defaults for Dashboard.
- Cache TTL settings.
- Performance page preferences (default period, benchmark selection).
- News preferences (auto-summary, max articles).

### 3.20 User Management

**File:** `pages/17_User_Management.py`

User account management for authenticated deployments.

### 3.21 Multi-Portfolio Management

**Location:** `app.py` sidebar

**Features:**
- Create multiple named portfolios (e.g., "Main Portfolio", "Retirement Fund", "Crypto").
- Switch between portfolios via sidebar dropdown.
- Each portfolio has its own holdings, independent of others.
- Portfolio switching clears enriched data cache to force a fresh load.
- Default portfolio (ID 1, "Main Portfolio") is protected from deletion.

---

## 4. PROSPER Analysis Framework

**File:** `core/prosper_analysis.py`

### Overview

PROSPER v3.0 is a CIO-level equity analysis engine that classifies stocks into archetypes, scores them on 7 dimensions, estimates fair value, and produces investment ratings. It is powered by Claude AI with multi-source data enrichment.

### The 8 Archetypes

Each stock is classified into one archetype, which determines how the 7 scoring dimensions are weighted:

| Code | Archetype | Key Weight Emphasis |
|------|-----------|-------------------|
| **A** | FCF Compounder | Margins (20%), Moat/IP (20%), Balance Sheet (15%), Valuation (15%) |
| **B** | Scaling Platform | Revenue Growth (25%), Moat/IP (15%), Execution (15%) |
| **C** | Pre-Revenue Innovator | Moat/IP (25%), Execution (20%), Risk-Adj Upside (20%) |
| **D** | Biotech / Clinical | Moat/IP (30%), Balance Sheet (20%), Risk-Adj Upside (20%) |
| **E** | Cyclical / Commodity | Balance Sheet (20%), Valuation (20%), Risk-Adj Upside (15%) |
| **F** | Turnaround | Balance Sheet (20%), Execution (20%), Valuation (15%), Risk-Adj Upside (15%) |
| **G** | High-Beta Growth | Revenue Growth (20%), Risk-Adj Upside (20%), Moat/IP (15%) |
| **H** | Deep-Tech / Frontier | Moat/IP (30%), Execution (20%), Risk-Adj Upside (20%) |

### The 7 Scoring Dimensions

Each dimension is scored 1-10 by Claude AI:

1. **Revenue Growth** — Top-line growth trajectory and sustainability
2. **Margins** — Profit margins, operating margins, margin expansion trend
3. **Moat / IP** — Competitive advantages, intellectual property, network effects
4. **Balance Sheet** — Debt levels, cash position, financial health
5. **Valuation** — Current valuation relative to intrinsic value and peers
6. **Execution** — Management quality, capital allocation, strategic decisions
7. **Risk-Adjusted Upside** — Potential reward relative to downside risk

The weighted score (0-100) determines the rating:
- **STRONG BUY:** Score > 80
- **BUY:** Score 65-79
- **HOLD:** Score 50-64
- **SELL:** Score 35-49
- **STRONG SELL:** Score < 35

### 3 Model Tiers

| Tier | Model | Max Tokens | Data Sources | Cost/Stock |
|------|-------|-----------|--------------|-----------|
| **Quick** | Claude 3.5 Haiku | 1,200 | yfinance + Finnhub (pre-fetched) | ~$0.008 |
| **Standard** | Claude 3.5 Sonnet | 2,000 | + Serper web search + Google News | ~$0.04 |
| **Full CIO** | Claude 3.5 Sonnet | 2,500 | All sources + deep web search | ~$0.04 + search |

### Fair Value Methodology

Claude generates three price targets with probability weights:
- **Bear Case** — Worst-case scenario price with probability (e.g., 20%)
- **Base Case** — Most likely outcome with probability (e.g., 55%)
- **Bull Case** — Best-case scenario price with probability (e.g., 25%)

Probabilities must sum to 100%. The probability-weighted fair value = (bear x prob_bear) + (base x prob_base) + (bull x prob_bull). Upside/downside is calculated from current price to probability-weighted fair value.

### Multi-Source Data Enrichment

The context builder (`build_analysis_context`) aggregates data from:

1. **yfinance** — Price, market cap, ratios (P/E, P/B, P/S, PEG, EV/EBITDA), growth (revenue, earnings), margins, balance sheet, EPS, 52W range, beta, analyst targets, business summary.
2. **Finnhub** — Analyst consensus (buy/hold/sell counts), recommendation trends (3-month comparison), recent upgrade/downgrade history (firm, action, grade, date).
3. **Serper (Google Search)** — Recent web articles and analysis about the stock (Standard and Full tiers only).
4. **Google News RSS** — Latest 5 headlines for real-time sentiment context (Standard and Full tiers only).
5. **Portfolio Data** — User's holdings (quantity, avg cost, market value, unrealized P&L) for position context.
6. **India Market Context** — For .NS/.BO tickers: promoter holding, institutional holding, NIFTY 50 membership.

Data confidence is rated HIGH (15+ data points), MEDIUM (8-14), or LOW (<8). Low confidence triggers a note in the analysis and reduces conviction.

### Conviction Levels

- **HIGH** — >80% data coverage and analyst consensus aligns with scoring
- **MEDIUM** — 50-80% data coverage or mixed signals across sources
- **LOW** — <50% data coverage; analysis should be treated as directional only

---

## 5. FORTRESS Risk Framework

**File:** `core/fortress.py`

### Full Name

**F**ramework for **O**ptimized **R**isk-**T**uned **R**egime-**R**esponsive **E**quity **S**izing & **S**trategy

### The 9 Modules

#### Module 1: Regime Detection Engine

Detects the current market regime from macroeconomic signals. Four regimes form a cycle:

| Regime | Code | Plain-English Label | Color | Description |
|--------|------|-------------------|-------|-------------|
| Expansion | I | Growing | Green | Economy healthy, markets favor risk-taking |
| Overheating | II | Heating Up | Orange | Late cycle: inflation rising, valuations stretched |
| Contraction | III | Slowing Down | Red | Economic weakness, earnings pressure, risk of declines |
| Recovery | IV | Bouncing Back | Blue | Early recovery, best risk/reward phase |

**Input Signals:**
- VIX (volatility index)
- Global PMI (purchasing managers index)
- Credit Spreads (investment grade, basis points)
- Yield Curve (2s10s spread)
- Core CPI (year-over-year inflation)
- Fed Funds Trajectory (cutting/hiking/holding)

**Geopolitical Overlay:**
- GREEN — No override, use macro regime
- AMBER — Tighten gross by 10-15%, add 5% cash
- RED — Force Contraction parameters regardless of macro regime

#### Module 2: Exposure Governor

Defines hard limits for portfolio exposure based on the current regime:

| Parameter | Expansion | Overheating | Contraction | Recovery |
|-----------|-----------|-------------|-------------|----------|
| Gross Exposure | 130-170% | 100-130% | 60-100% | 110-150% |
| Net Exposure | 80-120% | 50-80% | 0-40% | 70-100% |
| Cash Allocation | 0-5% | 5-15% | 15-40% | 5-10% |
| Max Single Name (Long) | 8% | 6% | 4% | 7% |
| Max Sector Concentration | 30% | 25% | 20% | 25% |
| Max Geo Concentration | 60% | 50% | 40% | 50% |

Limits are further adjusted by:
- **Confidence** — LOW confidence tightens limits (caps at conservative end)
- **Geopolitical Tier** — AMBER reduces gross by 15%, RED forces Contraction limits

**Transition Glide Paths:** When regime changes, exposure adjustments happen over a defined number of days (15-30) to prevent whipsawing.

#### Module 3: Dynamic Position Sizing (Half-Kelly)

Calculates recommended position size for each holding using:

1. **PROSPER Score** maps to a **Conviction Tier**: MAXIMUM (85-100), HIGH (70-84), MODERATE (55-69), LOW (40-54), NO_POSITION (0-39).
2. **Kelly Criterion** — Uses probability of bull scenario and reward/risk ratio to calculate raw Kelly fraction.
3. **Half-Kelly** — Takes 50% of raw Kelly for safety.
4. **Regime Scalar** — Multiplies Half-Kelly by regime factor: Expansion (1.0x), Recovery (0.85x), Overheating (0.75x), Contraction (0.50x).
5. **Matrix Bounds** — Clamps result within a position-size matrix defined by conviction tier and regime.
6. **Druckenmiller Override** — For MAXIMUM conviction in Expansion with PROSPER score >80, allows 10-12% positions.

#### Module 4: Factor Balance & Correlation Monitor

Tracks portfolio exposure to style factors with limits:
- Value: max 40%
- Growth: max 40%
- Quality: unlimited
- Momentum: max 50%
- Small Cap: max 30%
- Leverage: max 25%
- Illiquid: max 15%

Correlation monitoring with traffic-light zones:
- Average pairwise correlation: Green (<0.30), Amber (0.30-0.50), Red (>0.50)
- Max pairwise correlation: Green (<0.60), Amber (0.60-0.75), Red (>0.75)

#### Module 5: Rebalancing Protocol

Automated detection of rebalancing triggers:
1. **Regime Change** — Initiates glide path to new exposure limits
2. **Thesis Break** — PROSPER re-evaluation needed
3. **Sizing Breach** — Position exceeds 1.5x target weight
4. **Factor Breach** — Style factor exceeds defined limit
5. **Correlation Spike** — Average pairwise enters RED zone
6. **Drawdown Trigger** — Portfolio drawdown hits circuit breaker level
7. **Catalyst Realized** — Bull/bear catalyst has played out
8. **Valuation Mean Reversion** — Stock reached fair value target
9. **Liquidity Event** — Reduced market liquidity
10. **Quarterly Review** — Scheduled portfolio review

Each trigger includes urgency level (IMMEDIATE/HIGH/MODERATE) and specific recommended action.

#### Module 6: Drawdown Circuit Breakers

**Portfolio-Level Breakers:**

| Level | Drawdown | Action |
|-------|----------|--------|
| YELLOW | -5% | Alert, review all positions, re-run regime check, no new longs |
| ORANGE | -10% | Reduce gross 20%, cut LOW conviction, add index hedge, CIO review |
| RED | -15% | Reduce to Contraction floor, exit LOW and <1% positions, hedge 50% of net |
| CRITICAL | -20% | Move to 50% cash, hold only MAXIMUM conviction at half size, 30-day freeze |

**Single-Name Breakers:**

| Drawdown | Action |
|----------|--------|
| -15% | Mandatory re-evaluation, re-run PROSPER, cut 50% if thesis weakened |
| -25% | Cut to half-size regardless of thesis |
| -35% | EXIT: Full liquidation within 5 days, no exceptions |

#### Module 7: Portfolio Health Dashboard

10-dimension scorecard, each rated green/amber/red:

1. Regime Alignment
2. Exposure Compliance
3. Single-Name Concentration
4. Sector/Geo Concentration
5. Factor Balance
6. Correlation
7. Liquidity Coverage
8. Drawdown Status
9. PROSPER Score Average
10. Open Kill Risks

Overall assessment ranges from "Optimally positioned" (10/10 green) to "CRISIS MODE — Activate circuit breakers" (<4/10 green).

#### Module 8: PROSPER-FORTRESS Integration

The `fortress_size_ticker` function provides the full sizing workflow: Regime detection --> Factor limit check --> Correlation check --> Circuit breaker check --> Half-Kelly position size.

#### Module 9: System Evolution & Governance

Defines the governance process for updating FORTRESS parameters and thresholds.

### Margin Rate Intelligence

FORTRESS includes a built-in broker margin rate database for:
- Interactive Brokers (IBKR) — Tiered by balance (1.5% for >$1M down to 6.83% for <$100K)
- Charles Schwab — Tiered (11.075% to 13.575%)
- TD Ameritrade — Tiered (10.75% to 13.75%)
- Fidelity — Tiered (8.00% to 13.325%)

Used in the Dashboard's Cash & Margin section to auto-calculate annual margin costs.

---

## 6. Data Architecture

### Database Tables

All tables are created at startup via `init_db()`. On Turso, creation is batched into a single HTTP pipeline call.

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `holdings` | Stock positions | ticker, name, quantity, avg_cost, currency, broker_source, portfolio_id |
| `portfolios` | Named portfolios | id, name, description |
| `transactions` | Buy/sell records | ticker, type, quantity, price, date, fees, broker_source, notes |
| `prosper_analysis` | AI analysis results | ticker (PK), rating, score, archetype, fair_value_base/bear/bull, thesis, score_breakdown |
| `nav_snapshots` | Daily portfolio value | date, total_value, total_cost, unrealized_pnl, realized_pnl, holdings_count, base_currency |
| `price_cache` | Live price cache | ticker (PK), price, change_val, change_pct, source, fetched_at |
| `ticker_cache` | Resolved ticker mappings | ticker (PK), resolved, fetched_at |
| `parse_cache` | Screenshot parse results | image_hash (PK), result_json |
| `news_cache` | Cached news articles | cache_key (PK), news_json, fetched_at |
| `cash_positions` | Cash and margin | account_name, currency, amount, is_margin, margin_rate, broker_source |
| `fortress_state` | Risk framework state | key (PK, e.g., "vix", "pmi"), value |
| `watchlist` | Stock watchlist | ticker, name, target_price, notes |
| `briefing_cache` | AI briefing storage | briefing_date, currency, content |

### Caching Strategy

**Session-State Cache (st.session_state):**
- Enriched portfolio data: keyed by `enriched_{base_currency}`, cleared on portfolio switch or price refresh.
- Ticker info: cached with 24-hour TTL (`INFO_TTL`).
- News: 15-minute TTL (`NEWS_TTL`).
- Analyst data: 12-hour TTL (`ANALYST_TTL`).
- History (OHLCV): 1-hour TTL (`HISTORY_TTL`).
- Holdings: cached per portfolio ID, invalidated on save/update/delete.

**SQLite Price Cache:**
- All live prices are persisted to `price_cache` table.
- On second load, prices are served from SQLite instantly.
- Only stale tickers (>5 minutes old) are re-fetched from APIs.
- Failed tickers have a 10-minute cooldown (skip re-fetching).

### Price Fetching Pipeline

Multi-source cascade per ticker:

1. **ADX/Mubasher** — For Abu Dhabi stocks (.AE suffix with known chart IDs). Uses CSV intraday data from Mubasher.
2. **Twelve Data** — For UAE symbols in `TICKER:DFM` or `TICKER:XADS` format.
3. **yfinance** — Primary source for all other global stocks. Returns price, previous close, day change, and trading currency.
4. **Finnhub** — Fallback for everything else when yfinance fails.

All tickers are fetched in parallel (ThreadPoolExecutor, max 15 workers). Batch timeout scales with portfolio size (30s base + 2s per ticker beyond 20).

**Price Sanity Check:** Rejects negative prices and flags ETF/fund prices >10,000 as likely errors.

### Ticker Resolution

For tickers without exchange suffixes, the resolution cascade:

1. **Override Map** — Hardcoded corrections (e.g., `EMIRATESN.AE` -> `EMIRATESNBD.AE`, `I288654906` -> `FKINX`).
2. **Crypto Map** — Maps bare symbols to yfinance format (e.g., `BTC` -> `BTC-USD`).
3. **yfinance Probe** — Try the bare ticker on Yahoo Finance.
4. **Suffix Map** — Try common suffixes based on stored currency (e.g., AED -> `.AE`, `.AD`; INR -> `.NS`, `.BO`).
5. **Twelve Data** — For AED currency, try DFM/XADS exchanges.
6. **Finnhub** — Last resort probe.
7. **SQLite Cache** — Resolved mappings are cached for 24 hours in `ticker_cache`.

### API Integrations

| API | Purpose | Key Required | Free Tier |
|-----|---------|-------------|-----------|
| **yfinance** | Prices, fundamentals, history, analyst data | No | Unlimited |
| **Anthropic Claude** | Screenshot parsing, PROSPER analysis, AI chat, briefings, news summaries | Yes (`ANTHROPIC_API_KEY`) | Pay-per-use |
| **Finnhub** | Analyst consensus, upgrade/downgrade history, price fallback | Yes (`FINNHUB_API_KEY`) | 60 calls/min |
| **Serper** | Google Search results for web context in PROSPER analysis | Yes (`SERPER_API_KEY`) | 2,500 free/month |
| **Twelve Data** | UAE stock prices (DFM, ADX) | Yes (`TWELVE_DATA_API_KEY`) | 800 calls/day |
| **Financial Modeling Prep** | Historical FMP data (legacy, partially replaced by yfinance) | Yes (`FMP_API_KEY`) | 250 calls/day |

---

## 7. Security and Privacy

### Local-First Design

- **No cloud telemetry.** Prosper does not send portfolio data to any analytics service.
- **SQLite by default.** All data is stored in `~/prosper_data/prosper.db` on the user's machine.
- **Cloud option is opt-in.** Turso (cloud SQLite) is only activated when `TURSO_DATABASE_URL` is configured.
- **API keys are never hardcoded.** All keys are read from `.env` file (local) or Streamlit secrets (cloud).

### API Key Management

Keys are resolved via a priority cascade in `get_api_key()`:
1. `os.environ` / `.env` file (local development)
2. `st.secrets` direct access (Streamlit Cloud)
3. `st.secrets.get()` fallback
4. Nested `st.secrets["secrets"]` table
5. Returns empty string if not found anywhere

### Authentication System

Three-tier authentication:

1. **Streamlit Cloud Native Auth** — When deployed on Streamlit Cloud, uses the platform's built-in Google/GitHub SSO. Detects cloud environment automatically.
2. **streamlit-authenticator (Local)** — For local deployments, uses `auth_config.yaml` with bcrypt-hashed passwords. Includes a registration form for creating new accounts.
3. **Disabled** — Auth is disabled by default on Streamlit Cloud (uses Cloud's own auth) and enabled by default locally. Controlled by `PROSPER_AUTH_ENABLED` environment variable.

The login page includes:
- Google and GitHub social login buttons (when OAuth client IDs are configured)
- Username/password sign-in
- Account registration with validation (email, name, password length, confirmation)

### Data Privacy

- Financial data never leaves the user's network unless Turso cloud DB is explicitly configured.
- Claude API calls send only the specific data needed for analysis (fundamentals, not personal information).
- Parse cache stores image hashes, not the original images.
- No user tracking, no cookies beyond Streamlit's session management.

---

## 8. Configuration

### Environment Variables (.env File)

Create a `.env` file in the project root directory:

```
# Required for AI features
ANTHROPIC_API_KEY=sk-ant-...

# Optional — enhances data coverage
FINNHUB_API_KEY=...
SERPER_API_KEY=...
TWELVE_DATA_API_KEY=...
FMP_API_KEY=...

# Optional — Cloud database
TURSO_DATABASE_URL=libsql://your-db.turso.io
TURSO_AUTH_TOKEN=...

# Optional — Authentication
PROSPER_AUTH_ENABLED=true
GOOGLE_CLIENT_ID=...
GITHUB_CLIENT_ID=...

# Optional — Base currency override
BASE_CURRENCY=USD
```

### User Settings File

Stored at `~/prosper_data/user_settings.json`. Managed via the Settings page. Only user-modified values are saved (defaults are not persisted).

**Key Settings:**

| Setting | Default | Description |
|---------|---------|-------------|
| `base_currency` | USD | Base currency for all value conversions |
| `parse_cache_enabled` | true | Cache screenshot parse results |
| `parse_cache_ttl_days` | 90 | Days before parse cache expires |
| `price_cache_ttl_seconds` | 300 | Seconds before re-fetching a price (5 min) |
| `fetch_key_metrics` | true | Auto-fetch health metrics on dashboard |
| `pref_dash_show_day_gain` | true | Show day gain column on dashboard |
| `pref_dash_show_extended` | false | Show extended metrics by default |
| `pref_dash_auto_extended` | false | Auto-load extended metrics on page load |
| `pref_perf_period` | 1y | Default period for performance charts |
| `pref_perf_benchmarks` | [S&P 500, Nasdaq 100, Nifty 50, Sensex] | Benchmark indices for performance comparison |
| `pref_news_auto_summary` | false | Auto-generate AI news summaries |

### API Keys Needed (By Feature)

| Feature | Required API Key |
|---------|-----------------|
| Screenshot Parsing | ANTHROPIC_API_KEY |
| PROSPER AI Analysis | ANTHROPIC_API_KEY |
| Ask Prosper (AI Chat) | ANTHROPIC_API_KEY |
| AI Briefing (Command Center) | ANTHROPIC_API_KEY |
| News Summaries | ANTHROPIC_API_KEY |
| Analyst Consensus (Finnhub data) | FINNHUB_API_KEY |
| Web Context for Analysis | SERPER_API_KEY |
| UAE Stock Prices | TWELVE_DATA_API_KEY |
| Cloud Database | TURSO_DATABASE_URL + TURSO_AUTH_TOKEN |

**No API key needed for:** Live prices (yfinance), fundamentals, history, technical analysis, portfolio management, risk framework calculations.

---

## 9. Deployment

### Local Development

```bash
# 1. Clone the repository
# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create .env file with API keys (see Configuration section)

# 5. Run the app
streamlit run app.py
```

The database is created automatically at `~/prosper_data/prosper.db` on first run.

### Streamlit Cloud Deployment

1. **Push code to GitHub** — Streamlit Cloud deploys from a Git repository.
2. **Connect on Streamlit Cloud** — Go to share.streamlit.io, connect your GitHub repo, set `app.py` as the main file.
3. **Configure Secrets** — In the Streamlit Cloud dashboard, add secrets:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   FINNHUB_API_KEY = "..."
   TURSO_DATABASE_URL = "libsql://your-db.turso.io"
   TURSO_AUTH_TOKEN = "..."
   ```
4. **Turso Setup** — Create a Turso database at turso.tech. Get the database URL and auth token. The app auto-detects Turso when `TURSO_DATABASE_URL` is set and uses HTTP pipeline API for all queries.
5. **Authentication** — On Streamlit Cloud, authentication is disabled by default (Cloud's built-in auth is used). Set `PROSPER_AUTH_ENABLED=true` in secrets to force streamlit-authenticator.

### Turso Cloud Database

The `db_connector.py` module provides a Turso HTTP Pipeline API wrapper that mimics the sqlite3 interface. Key behaviors:
- Tables are created via `execute_batch()` in a single HTTP call (instead of 10+ individual calls).
- Queries use Turso's HTTP pipeline endpoint.
- `PRAGMA` statements are not supported by Turso and are handled gracefully.
- Portfolio-ID queries include fallback for missing columns (migration resilience).

### Requirements

From `requirements.txt`:
- streamlit >= 1.39.0
- anthropic >= 0.40.0
- python-dotenv >= 1.0.0
- pandas >= 2.1.0
- Pillow >= 10.0.0
- requests >= 2.31.0
- yfinance >= 0.2.54
- plotly >= 5.18.0
- finnhub-python >= 2.4.0
- openpyxl >= 3.1.0
- streamlit-authenticator >= 0.3.2
- scipy >= 1.11.0
- numpy >= 1.24.0
- PyYAML >= 6.0.0
- bcrypt

---

## 10. Code Structure

```
prosper/
|-- app.py                          # Main entrypoint: page config, auth, navigation, global CSS, floating chat widget
|-- requirements.txt                # Python dependencies
|-- .env                            # API keys (not committed to git)
|-- auth_config.yaml                # Local authentication credentials (bcrypt hashed)
|
|-- core/                           # Business logic and data layer
|   |-- __init__.py
|   |-- settings.py                 # App configuration, user settings, API key resolution, call_claude() with model fallback
|   |-- database.py                 # SQLite/Turso data access layer: all CRUD operations, caching, migrations
|   |-- db_connector.py             # Database connection abstraction: Turso HTTP API or local SQLite
|   |-- cio_engine.py               # Portfolio enrichment: parallel price fetching, FX conversion, P&L calculation
|   |-- data_engine.py              # Central data hub: ticker resolution, info/news/analyst/history fetching, caching
|   |-- prosper_analysis.py         # PROSPER AI analysis framework: archetypes, scoring, multi-source context, Claude integration
|   |-- fortress.py                 # FORTRESS risk framework: 9 modules (regime, exposure, sizing, factors, rebalancing, breakers, health)
|   |-- portfolio_optimizer.py      # Portfolio optimization: model portfolios, allocation analysis, MPT efficient frontier
|   |-- screenshot_parser.py        # Claude Vision screenshot/PDF parsing with parse cache
|   |-- currency_normalizer.py      # Ticker-suffix currency detection, FX rate fetching, currency code corrections
|   |-- finnhub_client.py           # Finnhub API client for analyst data and price fallback
|   |-- twelve_data_client.py       # Twelve Data API client for UAE/DFM stock prices
|   |-- adx_client.py               # Abu Dhabi Securities Exchange (ADX) price client via Mubasher
|   |-- social_sentiment.py         # Social media sentiment analysis
|
|-- pages/                          # Streamlit pages (each is a separate view)
|   |-- 00_Command_Center.py        # Home: executive dashboard, regime, portfolio pulse, AI briefing
|   |-- 0_Settings.py               # App settings and configuration
|   |-- 1_Upload_Portal.py          # File upload: screenshots, CSV, Excel, PDF ingestion
|   |-- 2_Portfolio_Dashboard.py    # Holdings table, live prices, P&L, cash/margin management
|   |-- 3_Portfolio_News.py         # Aggregated news for portfolio holdings
|   |-- 4_Portfolio_Summary.py      # Diversification analysis: sector, currency, country, market cap
|   |-- 5_Performance.py            # NAV history, benchmark comparison, performance metrics
|   |-- 6_Market_News.py            # Broad market and sector news
|   |-- 7_Analyst_Consensus.py      # Per-stock analyst ratings, targets, upgrade/downgrade history
|   |-- 8_Sentiment.py              # Social and news sentiment
|   |-- 12_Transaction_Log.py       # Buy/sell transaction recording and realized P&L
|   |-- 15_Prosper_AI_Analysis.py   # Batch PROSPER analysis for all holdings
|   |-- 17_User_Management.py       # User account management
|   |-- 18_Equity_Deep_Dive.py      # Single-stock 360-degree research view
|   |-- 18_FORTRESS_Dashboard.py    # Standalone FORTRESS dashboard (legacy, superseded by Risk & Strategy)
|   |-- 18_Risk_Strategy.py         # Unified risk governance: FORTRESS + Portfolio Optimizer
|   |-- 19_Portfolio_Optimizer.py   # Standalone optimizer (legacy, superseded by Risk & Strategy)
|   |-- 20_Earnings_Calendar.py     # Upcoming earnings dates for portfolio holdings
|   |-- 21_Technical_Analysis.py    # Technical indicators: SMA, EMA, RSI, MACD, Bollinger, ATR
|   |-- 22_Dividend_Dashboard.py    # Dividend income, yield, ex-dates, projections
|   |-- 23_Peer_Comparison.py       # Side-by-side fundamental comparison with sector peers
|   |-- 24_AI_Chat.py               # Ask Prosper: natural-language portfolio assistant
|
|-- ~/prosper_data/                 # User data directory (created automatically)
|   |-- prosper.db                  # SQLite database
|   |-- user_settings.json          # Persistent user preferences
```

### Navigation Structure (Sidebar)

The sidebar organizes pages into 7 sections:

1. **Prosper** — Command Center (home)
2. **Portfolio** — Dashboard, Risk & Strategy, Summary, Performance
3. **Research** — Equity Deep Dive, Analyst Consensus, Sentiment, Prosper AI, Peer Comparison, Technical Analysis
4. **Income & Calendar** — Dividends, Earnings Calendar
5. **News & Activity** — Portfolio News, Market News, Transactions
6. **AI** — Ask Prosper
7. **Settings** — Settings, Upload Portal, Users

---

*This document was generated from the Prosper codebase at version 5.3 (March 2026).*
