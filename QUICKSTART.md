# Prosper — Quick Start Guide

## Run Locally

```bash
cd "/Users/singpu03/Documents/Prosper with Claude March 2026"
streamlit run app.py
```

Then open your browser to: **http://localhost:8501**

---

## Keyboard Shortcuts (Streamlit)
- `R` — Refresh/rerun the app
- `C` — Clear cache
- `S` — Open settings

---

## First Time Setup

1. **Add Your Holdings:**
   - Click "📤 Upload Portal" in sidebar
   - Upload screenshots from your brokers (IBKR, Zerodha, DFM, etc.)
   - App extracts ticker, qty, price automatically

2. **Set Your Base Currency:**
   - Go to Settings page (⚙️ in sidebar)
   - Select your preferred base currency (USD, AED, EUR, etc.)
   - All prices will convert to this currency

3. **Load Extended Data (Optional):**
   - Go to Portfolio Dashboard
   - Check "Auto-load Extended Metrics" to fetch analyst consensus automatically
   - OR click "📊 Load Extended Metrics" button once to get it

4. **Explore Pages:**
   - **Portfolio Dashboard** — See your holdings, P&L, consensus ratings
   - **Performance** — Compare your returns vs benchmarks
   - **Portfolio Summary** — Diversification by sector, country, currency
   - **Transaction Log** — Record trades and calculate realized gains
   - **Watchlist** — Track stocks you want to buy

---

## Environment Setup

### Required Files
- `.env` — API keys (Finnhub, FMP, Anthropic — optional for AI summaries)

### Example `.env`:
```
FINNHUB_API_KEY=your_key_here
FMP_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
BASE_CURRENCY=USD
```

### Data Location
All your data stored in: `~/prosper_data/`
- `prosper.db` — All holdings, prices, news, transactions
- `user_settings.json` — Your preferences (persisted)

---

## Support / Troubleshooting

### App loads but no data appears
1. Go to Portfolio Dashboard
2. Click 🔄 (refresh button) to load prices
3. Wait 10-15 seconds for yfinance to fetch data

### "No live price for ticker XYZ"
- Ticker might need exchange suffix (e.g., `EMAAR.AE` for UAE, `RELIANCE.NS` for India)
- Or ticker doesn't exist on yfinance
- Try uploading again with correct ticker from your broker

### Settings not saving
1. Check that `~/prosper_data/` directory exists and is writable
2. Click Settings → scroll down → click "💾 Save Settings"
3. Check `~/prosper_data/user_settings.json` to see if it was written

### News not loading
- Some tickers may not have news available
- Try clicking "🔄 Refresh News" button
- Check internet connection

---

## Architecture

```
Prosper/
├── app.py                          # Entry point + navigation
├── core/
│   ├── settings.py                 # User preferences (persisted JSON)
│   ├── database.py                 # SQLite operations
│   ├── data_engine.py              # yfinance, ticker resolution, cache
│   ├── cio_engine.py               # Portfolio enrichment + FX conversion
│   └── ... (other clients)
├── pages/
│   ├── home.py                     # Landing page
│   ├── 1_Upload_Portal.py          # Screenshot parser
│   ├── 2_Portfolio_Dashboard.py    # Main holdings view (v4)
│   ├── 3_Portfolio_News.py         # Stock news only
│   ├── 4_Portfolio_Summary.py      # Diversification + risk
│   ├── 5_Performance.py            # vs benchmarks + NAV history
│   ├── 6_Market_News.py            # Sector/fund news
│   ├── 7_Analyst_Consensus.py      # Buy/sell ratings
│   ├── 8_Sentiment.py              # Social sentiment
│   ├── 9_Insider_Activity.py       # Insider trades
│   ├── 10_Institutional.py         # Ownership %
│   ├── 12_Transaction_Log.py       # Trade history + P&L
│   ├── 13_Export.py                # CSV/Excel export
│   ├── 14_Watchlist.py             # Watchlist
│   └── 0_Settings.py               # Preferences UI
├── requirements.txt                # Python dependencies
└── RELEASE_NOTES.md               # What's new in each phase
```

---

## Tips & Tricks

### Speed Up Performance Page
- Use shorter time periods (1y vs 5y) for faster loads
- Select fewer benchmarks
- Benchmark loading is cached for 30 minutes

### Reduce API Calls
- Enable "Parse Cache" in Settings (caches screenshots for 90 days)
- Enable "Auto-load Extended Metrics" to batch fetch analyst data
- Use "Load Extended Metrics" once instead of clicking multiple times

### Track Taxes
- Record all sells in Transaction Log with fees
- Export realized P&L report for tax filing
- Supports FIFO method (most sold = longest held)

### Monitor Your Funds
1. Upload fund holdings as screenshots
2. See them listed separate from stocks on Dashboard
3. Check "Market News" → "My Funds & ETFs" for fund-specific news
4. Not available for insider activity (funds don't have insider data)

---

## Version History

| Phase | Date | Focus |
|-------|------|-------|
| **Phase 1** | Mar 11 | Bug fixes (Insider, Institutional, Consensus) |
| **Phase 2** | Mar 12 | Trading (Transactions, Watchlist, Export, NAV) |
| **Phase 3** | Mar 12 | UX (Preferences, Fund separation, Consensus, Tabs) |
| **Phase 4+** | TBD | Real-time alerts, tax tools, direct broker API |

---

## Questions?

Check the RELEASE_NOTES.md for what changed in each phase.
Check individual page docstrings (top of each `.py` file) for implementation details.

**Happy investing! 🚀**
