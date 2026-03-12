# Project Prosper — Product Blueprint
*Last updated: March 2026*

---

## What's Built (Phase 1 MVP)
- Screenshot upload → Claude Vision AI reads it → editable table → save to local SQLite DB
- Parse caching (same image = no re-API call)
- Live prices from FMP (1 batch API call for all stocks)
- Currency auto-detection from ticker suffix (.NS=INR, .AE=AED, etc.)
- Portfolio Dashboard with P&L, Day Gain, color coding
- Configurable settings via `core/settings.py`

---

## a) CIO Engine — Live Prices & Health Metrics
**STATUS: Built in this session**

- **Live Price**: Batch fetches all tickers in ONE FMP API call (efficient)
- **Day Gain/Loss**: Change in price × quantity, converted to base currency
- **Unrealized P&L**: (Current Price − Avg Cost) × Qty in base currency
- **Health Metrics** (on-demand, separate button to save API quota):
  - P/E Ratio (Price-to-Earnings)
  - ROIC (Return on Invested Capital)
  - Debt-to-Equity
- **FMP Free Tier Note**: 250 calls/day. Batch quotes = 1 call. Metrics = 1 per stock.
  Toggle `fetch_key_metrics` in settings.py to False to preserve quota.

---

## b) Parse Caching — Don't Re-Parse the Same Image Twice
**STATUS: Built in this session**

- Every image is SHA-256 hashed before calling Claude
- Hash + result stored in local SQLite (`parse_cache` table)
- If same screenshot uploaded again → returns cached result instantly, zero API cost
- Cache TTL configurable in `core/settings.py` (`parse_cache_ttl_days`, default 90)
- Saves: ~$0.01–0.03 per image, and ~3–8 seconds of wait time

---

## c) Efficiency Mechanisms (All Configurable)
**STATUS: Built in this session — edit `core/settings.py`**

| Setting | Default | What it controls |
|---|---|---|
| `parse_cache_enabled` | True | Skip re-parsing same screenshot |
| `parse_cache_ttl_days` | 90 | How long to keep cached parses |
| `price_cache_ttl_seconds` | 300 | Refresh prices max once per 5 min |
| `fetch_key_metrics` | True | P/E, ROIC, D/E (uses extra API calls) |
| `fmp_batch_size` | 50 | Tickers per quote call |
| `fmp_timeout` | 10 | Seconds before giving up on API |

---

## d) Hosting on the Web — Options & Recommendation

### Option 1: Streamlit Community Cloud ⭐ EASIEST (Free)
**Best for**: Personal use, demo, sharing with a few people
**Cost**: Free
**Steps**:
1. Create a GitHub account and push your project to a GitHub repo
2. Go to https://share.streamlit.io
3. Sign in with GitHub → select your repo → click Deploy
4. Add your API keys in the Streamlit "Secrets" section (replaces .env)
5. Done — you get a public URL like `yourname-prosper.streamlit.app`

**Limitation**: Single-user, public URL (unless you pay for private apps), cold starts

---

### Option 2: Railway.app ⭐ BEST FOR PRIVATE USE ($5/month)
**Best for**: Private personal dashboard, always-on server
**Steps**:
1. Push code to GitHub
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Add environment variables (API keys) in Railway dashboard
4. Railway auto-detects Python, runs `streamlit run app.py`
5. You get a private URL with SSL

---

### Option 3: Render.com (Free tier available)
Similar to Railway. Free tier sleeps after 15 min of inactivity (slow cold start).

---

### ⚠️ Streamlit for Multi-User — Important Note
Streamlit is designed as a **single-user** tool. For multiple users with their own portfolios, you need a proper web architecture (see item e below). Streamlit Community Cloud does support multiple visitors but they all share the same session — **not suitable for private financial data**.

---

## e) Multi-User Profiles + Login (Google, Apple, Email)
**STATUS: Roadmap — requires architectural upgrade**

### What needs to change:
1. **Database**: SQLite → Supabase (cloud PostgreSQL with built-in auth)
2. **Auth**: Add Google OAuth, Apple Sign-In, email/password via Supabase Auth
3. **Data isolation**: Add `user_id` to all tables so each user sees only their data
4. **Multiple portfolios**: Add `portfolio_id` column — each user can have "Personal", "Corporate", "Family", etc.

### Recommended Stack for Multi-User:
```
User Browser → Streamlit App (hosted on Railway/Render)
                    ↓
              Supabase (Auth + PostgreSQL DB)
                    ↓
              Claude API + FMP API
```

### Step-by-Step to Implement (future session):
1. Create free Supabase account at https://supabase.com
2. Set up Google OAuth in Supabase dashboard (15 min)
3. Replace SQLite calls in `core/database.py` with Supabase client
4. Add `user_id` and `portfolio_id` columns to holdings table
5. Add login page using `streamlit-supabase-auth` library
6. Add portfolio selector dropdown in sidebar

**Estimated effort**: 1 full development session

---

## f) Currency Detection & Conversion Fix
**STATUS: Built in this session**

### The Problem (now fixed):
Stocks traded on UAE exchanges (DFM, ADX) have prices in AED.
Previously the app was treating AED prices as USD, inflating portfolio value by ~3.67x.

### The Fix:
Auto-detect currency from ticker suffix:

| Ticker Suffix | Exchange | Currency |
|---|---|---|
| (none) | US Markets | USD |
| `.NS` | NSE India | INR |
| `.BO` | BSE India | INR |
| `.AE` | Dubai (DFM) | AED |
| `.AD` | Abu Dhabi (ADX) | AED |
| `.HK` | Hong Kong | HKD |
| `.SI` | Singapore | SGD |
| `.L` | London | GBP |
| `.PA` | Paris | EUR |
| `.AX` | Australia | AUD |
| `.TO` | Toronto | CAD |
| `.T` | Tokyo | JPY |

Live FX rates fetched from FMP and cached per session.
All values normalized to your chosen base currency (USD, AED, etc.).

---

## g) Portfolio Dashboard — Current Design + UX Recommendations

### What's built now:
- **Summary Cards**: Total Value | Today's Gain | Unrealized P&L | # Holdings (all in base currency, color coded)
- **Holdings Table**: Ticker, Name, Qty, Avg Cost, Current Price, Day Gain, Market Value, Unrealized P&L, P&L %, P/E Ratio
- **Color coding**: Green cells for gains, red cells for losses
- **Refresh button**: Prices cached 5 min by default, manual refresh anytime

### What's NOT yet built (Realized P&L):
Realized P&L requires tracking sell transactions, which the app doesn't do yet.
To add this: create a `transactions` table (buy/sell entries) and compute realized gains.
This is Phase 2 work.

### UX Recommendations for Future Polish:
1. **Treemap / Bubble Chart**: Show portfolio allocation visually (size = market value, color = P&L)
2. **Sortable columns**: Click to sort by P&L, value, etc.
3. **Search/filter bar**: Find a specific stock quickly in a large portfolio
4. **Expand row**: Click a ticker to see its chart, news, analyst ratings
5. **Time period selector**: Today / 1W / 1M / YTD / All-time for P&L view
6. **Benchmark toggle**: Compare your performance vs S&P 500 or Gold
7. **Mobile layout**: Pinned summary cards at top, swipeable columns below

---

## h) Settings — What to Build for Target Users

### Priority 1 (Most requested by HNW investors):
- Base currency selector (USD / AED / EUR / GBP / INR / SGD)
- Column visibility toggles (show/hide P/E, ROIC, D/E, Broker, etc.)
- Light / Dark theme toggle
- Default broker source for uploads

### Priority 2 (Power user features):
- Number format: 1,234.56 vs 1.234,56 (EU style)
- Date format: MM/DD/YYYY vs DD/MM/YYYY
- Price refresh interval: 1 min / 5 min / 15 min / Manual only
- Metrics on/off toggle per column (to manage FMP API quota)

### Priority 3 (Advanced):
- Alert thresholds: Notify when stock > X% down in a day
- Auto-archive: Move holdings with 0 quantity to archive
- Export format: PDF report / CSV / Excel
- Custom benchmarks: Compare vs custom index or ETF

### How to implement Settings UI:
Create `pages/3_Settings.py` with st.form() containing all toggles.
Save preferences to `~/prosper_data/user_settings.json`.
Load on startup and merge with defaults from `core/settings.py`.

---

## i) Recommendations to Make This Great

### Short term (next 2 sessions):
1. **Export Report**: One-click PDF/CSV of your portfolio — great for meetings with advisors
2. **Watchlist**: Track stocks you're considering buying, without adding to portfolio
3. **Transaction Log**: Track buys/sells over time → enables realized P&L
4. **News Feed**: Per-stock news pulled from FMP or NewsAPI (free tier available)

### Medium term (1–2 months):
5. **Multi-broker reconciliation**: Auto-detect duplicate tickers across uploads from different brokers and merge them
6. **Historical NAV chart**: Track your total portfolio value over time (daily snapshots saved to DB)
7. **Allocation pie chart**: By sector, geography, currency, broker
8. **Target allocation**: Set % targets (e.g., 60% equity, 30% bond, 10% cash) and see drift

### Architecture upgrades:
9. **Move to Supabase**: Enables multi-user, cloud sync, mobile access (see item e)
10. **Add Plotly charts**: Interactive price charts per stock, portfolio performance curves
11. **FMP Premium**: Upgrading FMP key ($29/mo) unlocks: real-time prices, earnings calendar, analyst ratings, DCF valuations — significant upgrade to CIO Engine quality

### The North Star Vision:
A private, AI-powered Bloomberg Terminal for HNW individuals.
User uploads a screenshot → AI extracts holdings → live prices + health metrics →
portfolio analytics + alerts → exportable CIO-level report → shareable with advisors.
All data stays private and local (or cloud with Supabase, user's choice).

---

## API Cost Estimates (at current usage)

| Action | API | Cost |
|---|---|---|
| Parse 1 screenshot (first time) | Claude Sonnet | ~$0.02 |
| Parse same screenshot again | Cache | $0.00 |
| Refresh prices (50 stocks) | FMP (1 call) | Free tier |
| Fetch metrics (50 stocks) | FMP (50 calls) | Free tier |
| FX rate per currency pair | FMP (1 call each) | Free tier |
| **Monthly estimate (active user)** | | **~$1–5/month** |
