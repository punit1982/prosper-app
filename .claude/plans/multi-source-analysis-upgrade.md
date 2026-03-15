# Plan: Multi-Source Analysis Upgrade + UI Fixes

## Overview
Upgrade Prosper AI Analysis to pull from ALL available data sources before running analysis, switch web search from Brave to Serper, fix upload UI placement, fix cache timestamp, and improve news page loading UX.

---

## Changes

### 1. Prosper AI Analysis — Multi-Source Data Enrichment (US & India focus)

**File: `core/prosper_analysis.py`**

- **New function `_fetch_finnhub_context(ticker)`** — Pulls analyst recommendations, upgrade/downgrade history, and recommendation trends from Finnhub. Returns formatted context string.
- **New function `_fetch_analyst_consensus(ticker)`** — Pulls analyst price targets and consensus from yfinance (already in `get_ticker_info`) + Finnhub `recommendation_trends`.
- **New function `_fetch_recent_news_summary(ticker, company_name)`** — Uses Serper (replacing Brave) to get 5-8 recent headlines + Google News RSS. Returns bullet-point summary for the prompt.
- **New function `_fetch_india_context(ticker)`** — For `.NS`/`.BO` tickers: fetch additional India-specific data from yfinance (promoter holding, FII/DII data via info dict).
- **Update `build_analysis_context()`** — After building yfinance context, call Finnhub for analyst trends, upgrade/downgrades. Merge all data into the context string (not just for "full" tier — always enrich).
- **Update `run_analysis()`** — Before calling Claude:
  1. Always fetch Finnhub analyst consensus (if configured)
  2. Always fetch recent news via Serper (if configured) or Google News RSS fallback
  3. For India tickers: add India-specific context
  4. Build a "DATA CONFIDENCE" indicator: count non-null fields, report HIGH/MEDIUM/LOW to Claude
  5. Add all sources to context: `[Sources: yfinance ✓, Finnhub ✓, Serper ✓, Google News ✓]`
- **Update `_web_search_context()`** — Replace Brave API with Serper API (`https://google.serper.dev/search`)

**File: `core/data_engine.py`**

- **Replace `_fetch_news_brave()`** with `_fetch_news_serper()` — Same interface, uses Serper API instead of Brave.
- **Update `_fetch_news_rss()`** — Change Brave fallback to Serper fallback.
- **New function `get_finnhub_analyst_data(ticker)`** — Wrapper that fetches recommendation_trends + upgrade_downgrade from Finnhub, cached 1 hour.

### 2. Switch Web Search from Brave to Serper

**File: `core/data_engine.py`**
- Replace `_fetch_news_brave()` with `_fetch_news_serper()` using Serper API
- Serper endpoint: `https://google.serper.dev/search` (POST with JSON body)
- Header: `X-API-KEY: {SERPER_API_KEY}`
- Keep same interface: `_fetch_news_serper(query, count=10) -> List[Dict]`

**File: `core/prosper_analysis.py`**
- Replace Brave Search in `_web_search_context()` with Serper
- Same approach: search `"{company} {ticker} stock analysis outlook 2025 2026"`

**File: `pages/0_Settings.py`**
- Replace "Brave Search" entry with "Serper (Google Search)" in optional APIs
- Update the help text / instructions expander

**File: `.env`**
- The user will need to add `SERPER_API_KEY=xxx` (replacing `BRAVE_SEARCH_API_KEY`)

### 3. Move Upload from Sidebar to Center Screen

**File: `pages/1_Upload_Portal.py`**
- Move the file uploader from `st.sidebar` to the main content area (center)
- Use a clean centered layout: large drag-and-drop zone at center
- Keep broker selector and parse button in the main area too
- Remove sidebar upload controls entirely
- Layout: Hero upload zone → broker selector (inline) → parse button

### 4. Fix Cache Timestamp Display

**File: `pages/2_Portfolio_Dashboard.py`**
- Replace raw `cache_age` with human-readable relative time
- If `cache_age < 60`: show "just now" or "Xs ago"
- If `cache_age < 300` (5 min): show "Xm Xs ago"
- If `cache_age < 3600`: show "Xm ago"
- If `cache_age >= 3600`: show "Xh Xm ago"
- Remove "(from cache)" label — all prices come from cache, it's redundant
- Add "Live" badge if cache_age < 60s, "Recent" if < 5min, "Stale" if > TTL

### 5. Keep Cached News Visible While Loading Fresh

**File: `pages/3_Portfolio_News.py`**
- Show cached news immediately (from SQLite or session state)
- Use `st.spinner` in a separate container below/above to indicate refresh
- After fresh data arrives, replace the displayed news
- Pattern: display old → fetch new in background → swap

**File: `pages/6_Market_News.py`**
- Same pattern: show stale cached data immediately
- Display refresh indicator while fetching
- Replace with fresh data once ready

---

## Implementation Order
1. `core/data_engine.py` — Serper replacement + Finnhub analyst wrapper
2. `core/prosper_analysis.py` — Multi-source enrichment + Serper switch
3. `pages/0_Settings.py` — API key display update
4. `pages/1_Upload_Portal.py` — Center upload UI
5. `pages/2_Portfolio_Dashboard.py` — Fix timestamp
6. `pages/3_Portfolio_News.py` — Cached-while-loading
7. `pages/6_Market_News.py` — Cached-while-loading
