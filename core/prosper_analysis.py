"""
Prosper AI Analysis Engine
==========================
CIO-grade equity analysis using the PROSPER v3.0 framework.
Supports 3 tiers: Quick (Haiku), Standard (Sonnet), Full CIO (Sonnet + Web Search).

Multi-source data enrichment (US & India focus):
  1. yfinance — primary fundamentals, price, ratios
  2. Finnhub — analyst consensus, upgrade/downgrade, recommendation trends
  3. Serper (Google Search) — recent news, sentiment, web context
  4. Google News RSS — headline diversity
  5. Enriched portfolio data — fallback for non-US stocks
"""

import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─────────────────────────────────────────
# MODEL CONFIGURATION
# ─────────────────────────────────────────

MODEL_TIERS = {
    "quick": {
        "label": "Quick Score",
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 1200,
        "description": "Fast archetype + score using pre-fetched data only (~$0.008/stock)",
        "cost_per_1k_input": 0.001,
        "cost_per_1k_output": 0.005,
    },
    "standard": {
        "label": "Standard",
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 2000,
        "description": "Full scoring + fair value with multi-source data (~$0.04/stock)",
        "cost_per_1k_input": 0.003,
        "cost_per_1k_output": 0.015,
    },
    "full": {
        "label": "Full CIO",
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 2500,
        "description": "Deep analysis with web search + all sources (~$0.04/stock + search)",
        "cost_per_1k_input": 0.003,
        "cost_per_1k_output": 0.015,
    },
}


# ─────────────────────────────────────────
# ARCHETYPE SCORING WEIGHTS
# ─────────────────────────────────────────

ARCHETYPE_WEIGHTS = {
    "A": {"name": "FCF Compounder",     "weights": {"revenue_growth": 10, "margins": 20, "moat_ip": 20, "balance_sheet": 15, "valuation": 15, "execution": 10, "risk_adj_upside": 10}},
    "B": {"name": "Scaling Platform",    "weights": {"revenue_growth": 25, "margins": 15, "moat_ip": 15, "balance_sheet": 10, "valuation": 10, "execution": 15, "risk_adj_upside": 10}},
    "C": {"name": "Pre-Revenue Innovator","weights": {"revenue_growth": 10, "margins": 5,  "moat_ip": 25, "balance_sheet": 15, "valuation": 5,  "execution": 20, "risk_adj_upside": 20}},
    "D": {"name": "Biotech / Clinical",  "weights": {"revenue_growth": 5,  "margins": 5,  "moat_ip": 30, "balance_sheet": 20, "valuation": 5,  "execution": 15, "risk_adj_upside": 20}},
    "E": {"name": "Cyclical / Commodity", "weights": {"revenue_growth": 10, "margins": 15, "moat_ip": 10, "balance_sheet": 20, "valuation": 20, "execution": 10, "risk_adj_upside": 15}},
    "F": {"name": "Turnaround",          "weights": {"revenue_growth": 10, "margins": 10, "moat_ip": 10, "balance_sheet": 20, "valuation": 15, "execution": 20, "risk_adj_upside": 15}},
    "G": {"name": "High-Beta Growth",    "weights": {"revenue_growth": 20, "margins": 10, "moat_ip": 15, "balance_sheet": 10, "valuation": 10, "execution": 15, "risk_adj_upside": 20}},
    "H": {"name": "Deep-Tech / Frontier","weights": {"revenue_growth": 5,  "margins": 5,  "moat_ip": 30, "balance_sheet": 15, "valuation": 5,  "execution": 20, "risk_adj_upside": 20}},
}


# ─────────────────────────────────────────
# MULTI-SOURCE DATA FETCHERS
# ─────────────────────────────────────────

def _fetch_finnhub_analyst(ticker: str) -> str:
    """
    Fetch analyst consensus + recent upgrades/downgrades from Finnhub.
    Returns formatted context string for the analysis prompt.
    """
    try:
        from core.data_engine import get_finnhub_analyst_data
        data = get_finnhub_analyst_data(ticker)
        if not data:
            return ""

        lines = []
        # Recommendation trends (latest month)
        recs = data.get("recommendations", [])
        if recs:
            latest = recs[0]  # Most recent month
            buy = latest.get("buy", 0) + latest.get("strongBuy", 0)
            hold = latest.get("hold", 0)
            sell = latest.get("sell", 0) + latest.get("strongSell", 0)
            total = buy + hold + sell
            period = latest.get("period", "")
            if total > 0:
                lines.append(f"Finnhub Analyst Consensus ({period}): {buy} Buy, {hold} Hold, {sell} Sell (n={total})")
                # Show trend if we have 3+ months
                if len(recs) >= 3:
                    prev = recs[2]
                    prev_buy = prev.get("buy", 0) + prev.get("strongBuy", 0)
                    if prev_buy > 0:
                        trend = "improving" if buy > prev_buy else "declining" if buy < prev_buy else "stable"
                        lines.append(f"Buy Rating Trend (3mo): {trend} ({prev_buy} → {buy})")

        # Upgrade/downgrade history
        upgrades = data.get("upgrades", [])
        if upgrades:
            recent = upgrades[:5]
            ud_lines = []
            for ud in recent:
                action = ud.get("action", "")
                firm = ud.get("company", "Unknown")
                from_grade = ud.get("fromGrade", "")
                to_grade = ud.get("toGrade", "")
                date = ud.get("gradeTime", "")
                if isinstance(date, (int, float)) and date > 0:
                    date = datetime.fromtimestamp(date).strftime("%Y-%m-%d")
                if action and to_grade:
                    ud_lines.append(f"  {date}: {firm} {action} → {to_grade}" +
                                    (f" (from {from_grade})" if from_grade else ""))
            if ud_lines:
                lines.append("Recent Analyst Actions:\n" + "\n".join(ud_lines))

        return "\n".join(lines)
    except Exception:
        return ""


def _fetch_serper_context(ticker: str, company_name: str) -> str:
    """
    Fetch recent web analysis/news via Serper (Google Search API).
    Returns compact context string, or empty string if unavailable.
    """
    try:
        from core.data_engine import get_serper_web_context
        query = f"{company_name} {ticker} stock analysis outlook 2025 2026"
        results = get_serper_web_context(query, count=5)
        if not results:
            return ""

        snippets = []
        for r in results:
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            date = r.get("date", "")
            if title and snippet:
                prefix = f"[{date}] " if date else ""
                snippets.append(f"- {prefix}{title}: {snippet[:200]}")

        if snippets:
            return "RECENT WEB CONTEXT:\n" + "\n".join(snippets)
        return ""
    except Exception:
        return ""


def _fetch_google_news_headlines(ticker: str) -> str:
    """
    Fetch latest headlines from Google News RSS for real-time sentiment.
    Returns compact headline summary.
    """
    try:
        import requests
        import xml.etree.ElementTree as ET
        from urllib.parse import quote

        clean = ticker.split(".")[0] if "." in ticker else ticker
        url = f"https://news.google.com/rss/search?q={quote(clean)}+stock&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return ""

        root = ET.fromstring(resp.content)
        titles = []
        for item in root.findall(".//item")[:5]:
            title = item.findtext("title", "").strip()
            if title:
                # Remove " - Source" suffix for cleaner context
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0]
                titles.append(f"- {title}")

        if titles:
            return "RECENT HEADLINES:\n" + "\n".join(titles)
        return ""
    except Exception:
        return ""


def _detect_market_region(ticker: str, info: dict = None) -> str:
    """Detect if ticker is US, India, or other based on suffix/country."""
    upper = ticker.upper()
    if upper.endswith(".NS") or upper.endswith(".BO"):
        return "india"
    country = (info or {}).get("country", "").lower()
    if country == "india":
        return "india"
    exchange = (info or {}).get("exchange", "").upper()
    if exchange in ("NMS", "NYQ", "NGM", "NCM", "PCX", "ASE", "BTS"):
        return "us"
    if country in ("united states", "us", "usa"):
        return "us"
    if any(upper.endswith(s) for s in (".NS", ".BO")):
        return "india"
    return "other"


def _build_india_context(ticker: str, info: dict) -> str:
    """Add India-specific context for .NS/.BO tickers."""
    lines = []
    # Promoter holding (available in some yfinance data)
    holders = info.get("majorHoldersBreakdown")
    if holders:
        insiders = holders.get("insidersPercentHeld")
        insts = holders.get("institutionsPercentHeld")
        if insiders is not None:
            lines.append(f"Promoter/Insider Holding: {insiders*100:.1f}%")
        if insts is not None:
            lines.append(f"Institutional Holding: {insts*100:.1f}%")

    # India-specific: check for NIFTY50/SENSEX membership
    clean = ticker.replace(".NS", "").replace(".BO", "")
    nifty50_members = [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
        "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK",
        "ASIANPAINT", "HCLTECH", "BAJFINANCE", "MARUTI", "TITAN",
        "SUNPHARMA", "NESTLEIND", "ULTRACEMCO", "WIPRO", "NTPC",
        "POWERGRID", "M&M", "TATAMOTORS", "TATASTEEL", "ONGC",
        "JSWSTEEL", "ADANIENT", "ADANIPORTS", "TECHM", "INDUSINDBK",
        "BAJAJFINSV", "HINDALCO", "CIPLA", "DRREDDY", "EICHERMOT",
        "DIVISLAB", "APOLLOHOSP", "COALINDIA", "BPCL", "HEROMOTOCO",
        "GRASIM", "BRITANNIA", "SBILIFE", "BAJAJ-AUTO", "HDFCLIFE",
        "TATACONSUM", "LTIM", "SHRIRAMFIN",
    ]
    if clean in nifty50_members:
        lines.append(f"Index: NIFTY 50 constituent")

    return "\n".join(lines)


# ─────────────────────────────────────────
# CONTEXT BUILDER — Multi-source enrichment
# ─────────────────────────────────────────

def build_analysis_context(ticker: str, info: dict = None, enriched_row: dict = None) -> Tuple[str, int]:
    """
    Build a comprehensive context string from ALL available data sources.
    Pulls from: yfinance, Finnhub, enriched portfolio data.

    Returns:
        (context_string, data_fields_count) — context for the prompt and count of data points found.
    """
    if info is None:
        info = {}

    lines = [f"TICKER: {ticker}"]
    lines.append(f"Company: {info.get('longName') or info.get('shortName', 'N/A')}")
    lines.append(f"Sector: {info.get('sector', 'N/A')} | Industry: {info.get('industry', 'N/A')}")
    lines.append(f"Country: {info.get('country', 'N/A')} | Exchange: {info.get('exchange', 'N/A')}")
    lines.append(f"Quote Type: {info.get('quoteType', 'EQUITY')}")

    # Price & valuation
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if price:
        lines.append(f"Current Price: {price}")
    mkt_cap = info.get("marketCap")
    if mkt_cap:
        lines.append(f"Market Cap: {mkt_cap:,.0f}")

    # Key ratios
    ratios = []
    for key, label in [
        ("trailingPE", "P/E"), ("forwardPE", "Fwd P/E"), ("priceToBook", "P/B"),
        ("priceToSalesTrailing12Months", "P/S"), ("pegRatio", "PEG"),
        ("enterpriseToEbitda", "EV/EBITDA"), ("dividendYield", "Div Yield"),
    ]:
        v = info.get(key)
        if v is not None:
            if key == "dividendYield":
                ratios.append(f"{label}: {v*100:.1f}%")
            else:
                ratios.append(f"{label}: {v:.2f}")
    if ratios:
        lines.append(f"Valuation: {' | '.join(ratios)}")

    # Growth & profitability
    growth = []
    for key, label in [
        ("revenueGrowth", "Rev Growth"), ("earningsGrowth", "Earn Growth"),
        ("profitMargins", "Profit Margin"), ("operatingMargins", "Op Margin"),
        ("returnOnEquity", "ROE"), ("returnOnAssets", "ROA"),
    ]:
        v = info.get(key)
        if v is not None:
            growth.append(f"{label}: {v*100:.1f}%")
    if growth:
        lines.append(f"Growth/Margins: {' | '.join(growth)}")

    # Balance sheet
    bs = []
    for key, label in [
        ("debtToEquity", "D/E"), ("currentRatio", "Current Ratio"),
        ("totalCash", "Cash"), ("totalDebt", "Debt"),
    ]:
        v = info.get(key)
        if v is not None:
            if key in ("totalCash", "totalDebt"):
                bs.append(f"{label}: {v:,.0f}")
            else:
                bs.append(f"{label}: {v:.2f}")
    if bs:
        lines.append(f"Balance Sheet: {' | '.join(bs)}")

    # Revenue & earnings
    rev = info.get("totalRevenue")
    ebitda = info.get("ebitda")
    fcf = info.get("freeCashflow")
    if rev:
        lines.append(f"Revenue: {rev:,.0f}")
    if ebitda:
        lines.append(f"EBITDA: {ebitda:,.0f}")
    if fcf:
        lines.append(f"Free Cash Flow: {fcf:,.0f}")

    # EPS
    trail_eps = info.get("trailingEps")
    fwd_eps = info.get("forwardEps")
    if trail_eps:
        lines.append(f"EPS (TTM): {trail_eps:.2f} | EPS (Fwd): {fwd_eps:.2f}" if fwd_eps else f"EPS (TTM): {trail_eps:.2f}")

    # 52W range
    hi = info.get("fiftyTwoWeekHigh")
    lo = info.get("fiftyTwoWeekLow")
    if hi and lo:
        lines.append(f"52W Range: {lo:.2f} - {hi:.2f}")

    # Analyst consensus (yfinance)
    target = info.get("targetMeanPrice")
    rec = info.get("recommendationKey")
    n_analysts = info.get("numberOfAnalystOpinions")
    if target:
        lines.append(f"yfinance Analyst Target: {target:.2f} ({n_analysts or '?'} analysts) | Consensus: {rec or 'N/A'}")

    # Beta
    beta = info.get("beta")
    if beta:
        lines.append(f"Beta: {beta:.2f}")

    # Portfolio context (if user holds this stock)
    if enriched_row:
        qty = enriched_row.get("quantity")
        avg = enriched_row.get("avg_cost")
        mv = enriched_row.get("market_value")
        pnl = enriched_row.get("unrealized_pnl")
        if qty:
            lines.append(f"Portfolio: {qty} shares @ avg {avg} | Value: {mv} | Unrealized P&L: {pnl}")

        # Supplement sparse info with enriched data (esp. for non-US stocks)
        if not price and enriched_row.get("current_price"):
            lines.append(f"Current Price: {enriched_row['current_price']}")
        for ext_key, ext_label in [
            ("sector", "Sector"), ("industry", "Industry"), ("country", "Country"),
            ("forward_pe", "Fwd P/E"), ("trailing_pe", "P/E"), ("beta", "Beta"),
            ("revenue_growth", "Rev Growth"), ("earnings_growth", "Earn Growth"),
            ("profit_margin", "Profit Margin"), ("roe", "ROE"), ("debt_to_equity", "D/E"),
            ("ev_ebitda", "EV/EBITDA"), ("dividend_yield", "Div Yield"),
        ]:
            if enriched_row.get(ext_key) and not info.get(ext_key):
                v = enriched_row[ext_key]
                try:
                    import math
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        continue
                except (TypeError, ValueError):
                    pass
                if v and str(v) not in ("", "None", "nan"):
                    lines.append(f"{ext_label}: {v}")

    # Business summary (truncated to save tokens)
    summary = info.get("longBusinessSummary", "")
    if summary:
        truncated = summary[:300] + "..." if len(summary) > 300 else summary
        lines.append(f"Business: {truncated}")

    # ── Finnhub analyst data (always attempt — adds upgrade/downgrade context) ──
    finnhub_ctx = _fetch_finnhub_analyst(ticker)
    if finnhub_ctx:
        lines.append("")
        lines.append("ANALYST INTELLIGENCE (Finnhub):")
        lines.append(finnhub_ctx)

    # ── India-specific context ──
    region = _detect_market_region(ticker, info)
    if region == "india":
        india_ctx = _build_india_context(ticker, info)
        if india_ctx:
            lines.append("")
            lines.append("INDIA MARKET CONTEXT:")
            lines.append(india_ctx)

    # ── Data confidence indicator ──
    data_fields = len([l for l in lines if ":" in l and l.split(":")[0].strip() not in ("TICKER", "Company")])

    # Track which specific sources succeeded vs missing
    sources_found = []
    sources_missing = []

    # yfinance: check if we got meaningful data beyond just the ticker/name
    yf_has_data = bool(price or mkt_cap or ratios or growth or bs or rev)
    if yf_has_data:
        sources_found.append("yfinance (fundamentals)")
    else:
        sources_missing.append("yfinance (fundamentals)")

    if finnhub_ctx:
        sources_found.append("Finnhub (analyst consensus)")
    else:
        sources_missing.append("Finnhub (analyst consensus)")

    if enriched_row:
        sources_found.append("Portfolio (holdings data)")
    else:
        sources_missing.append("Portfolio (holdings data)")

    if region == "india":
        india_ctx_check = _build_india_context(ticker, info)
        if india_ctx_check:
            sources_found.append("India market context")
        else:
            sources_missing.append("India market context")

    # Add Data Sources Status section
    lines.append("")
    lines.append("DATA SOURCES STATUS:")
    if sources_found:
        lines.append(f"  Found: {', '.join(sources_found)}")
    if sources_missing:
        lines.append(f"  Missing: {', '.join(sources_missing)}")

    if data_fields >= 15:
        confidence = "HIGH"
    elif data_fields >= 8:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
        lines.append("\nNOTE: Limited data available for this stock. Use your knowledge of this company, sector, and market to provide a complete analysis. Set conviction to LOW.")

    lines.append(f"\nDATA CONFIDENCE: {confidence} ({data_fields} data points from {', '.join(sources_found) if sources_found else 'none'})")

    return "\n".join(lines), data_fields


# ─────────────────────────────────────────
# PROMPT TEMPLATE — Optimized for cost + accuracy
# ─────────────────────────────────────────

ANALYSIS_PROMPT = """You are PROSPER v3.0, a CIO-level equity analysis engine. Analyze the stock below using these steps:

1. ENVIRONMENTAL SCAN: Assess macro, geopolitical, regulatory, tech disruption, industry cycle, and thematic tailwinds/headwinds. Summarize as NET POSITIVE, NET NEGATIVE, or NEUTRAL.

2. CLASSIFY ARCHETYPE: Choose one: A(FCF Compounder), B(Scaling Platform), C(Pre-Revenue), D(Biotech), E(Cyclical), F(Turnaround), G(High-Beta Growth), H(Deep-Tech).

3. SCORE (1-10 each): revenue_growth, margins, moat_ip, balance_sheet, valuation, execution, risk_adj_upside. Apply archetype weights to get weighted score (0-100).

4. FAIR VALUE: Estimate bear/base/bull price targets with probability weights (must sum to 100%). Calculate probability-weighted fair value and upside from current price.

5. RATING: STRONG BUY (>80), BUY (65-79), HOLD (50-64), SELL (35-49), STRONG SELL (<35).

ACCURACY RULES:
- Use ALL data provided including analyst intelligence, web context, and headlines.
- Cross-reference multiple data sources for higher confidence ratings.
- For US stocks: leverage deep yfinance fundamentals + Finnhub analyst consensus + recent headlines for maximum accuracy.
- For India stocks (.NS, .BO): use available fundamentals + India market context. Factor in promoter holding patterns and index membership.
- If data confidence is LOW, note this prominently in the thesis and reduce conviction accordingly.
- If data is limited, use industry knowledge and sector context. Lower conviction but still score.
- Mark conviction: HIGH (>80% data + analyst consensus aligns), MEDIUM (50-80% data or mixed signals), LOW (<50% data).

{web_context}

STOCK DATA:
{context}

Respond ONLY with valid JSON (no markdown, no explanation):
{{
  "rating": "BUY",
  "score": 72,
  "archetype": "A",
  "archetype_name": "FCF Compounder",
  "conviction": "HIGH",
  "thesis": "1-2 sentence investment thesis",
  "env_net": "NET POSITIVE",
  "fair_value": {{"bear": 120.0, "base": 155.0, "bull": 190.0, "prob_bear": 20, "prob_base": 55, "prob_bull": 25}},
  "scores": {{"revenue_growth": 7, "margins": 8, "moat_ip": 9, "balance_sheet": 7, "valuation": 6, "execution": 8, "risk_adj_upside": 7}},
  "risks": ["Top risk 1", "Top risk 2", "Top risk 3"],
  "catalysts": ["Catalyst 1", "Catalyst 2", "Catalyst 3"]
}}"""


# ─────────────────────────────────────────
# MAIN ANALYSIS FUNCTION — Multi-source enrichment
# ─────────────────────────────────────────

def run_analysis(
    ticker: str,
    tier: str = "standard",
    info: dict = None,
    enriched_row: dict = None,
) -> Tuple[Optional[Dict], str]:
    """
    Run Prosper AI analysis on a single ticker.
    Before calling Claude, fetches data from ALL available sources in parallel.

    Data sources fetched (in parallel where possible):
      1. yfinance fundamentals (passed in via info)
      2. Finnhub analyst consensus + upgrade/downgrade (built into context)
      3. Serper web search (standard + full tiers)
      4. Google News headlines (standard + full tiers)

    Args:
        ticker: Stock ticker symbol
        tier: "quick", "standard", or "full"
        info: Pre-fetched yfinance info dict
        enriched_row: Row from enriched portfolio DataFrame (optional)

    Returns:
        (result_dict, error_message) — result is None on failure
    """
    from core.settings import get_api_key
    api_key = get_api_key("ANTHROPIC_API_KEY")
    if not api_key or api_key.startswith("your_"):
        return None, "Anthropic API key not configured. Add ANTHROPIC_API_KEY to your .env or Streamlit secrets."

    tier_config = MODEL_TIERS.get(tier, MODEL_TIERS["standard"])

    # Build base context (includes yfinance + Finnhub analyst + enriched data)
    context, data_fields = build_analysis_context(ticker, info, enriched_row)

    # ── Data quality gate — reject if too few data points ──
    if data_fields < 4:
        return {
            "rating": "N/A",
            "score": 0,
            "data_quality_warning": "INSUFFICIENT",
            "thesis": "Not enough data points available to generate a reliable analysis.",
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "model_used": tier,
            "cost_estimate": 0,
        }, ""

    # ── Fetch additional sources in parallel (for standard + full tiers) ──
    web_context = ""
    company_name = (info or {}).get("longName") or (info or {}).get("shortName", ticker)

    if tier in ("standard", "full"):
        # Parallel fetch: Serper web search + Google News headlines
        sources_ctx = []
        pool = ThreadPoolExecutor(max_workers=2)
        futures = {}

        # Serper web search (for standard: headlines only, for full: deep search)
        futures[pool.submit(_fetch_serper_context, ticker, company_name)] = "serper"
        # Google News headlines
        futures[pool.submit(_fetch_google_news_headlines, ticker)] = "google_news"

        try:
            for f in as_completed(futures, timeout=12):
                source = futures[f]
                try:
                    result_text = f.result(timeout=8)
                    if result_text:
                        sources_ctx.append(result_text)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            pool.shutdown(wait=False)

        if sources_ctx:
            web_context = "\n" + "\n\n".join(sources_ctx) + "\n"
        else:
            web_context = "\n(Web search unavailable — analyze using provided data + fundamentals only)\n"

    elif tier == "quick":
        # Quick tier: no web search, just fundamentals + Finnhub (already in context)
        web_context = ""

    prompt = ANALYSIS_PROMPT.format(context=context, web_context=web_context)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        t0 = time.time()
        response = client.messages.create(
            model=tier_config["model"],
            max_tokens=tier_config["max_tokens"],
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.time() - t0

        # Estimate cost
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = (
            input_tokens / 1000 * tier_config["cost_per_1k_input"]
            + output_tokens / 1000 * tier_config["cost_per_1k_output"]
        )

        raw_text = response.content[0].text.strip()

        # Parse JSON — handle potential markdown wrapping
        json_text = raw_text
        if json_text.startswith("```"):
            json_lines = json_text.split("\n")
            json_lines = [l for l in json_lines if not l.strip().startswith("```")]
            json_text = "\n".join(json_lines)

        result = json.loads(json_text)

        # Enrich with metadata
        result["model_used"] = tier
        result["cost_estimate"] = round(cost, 4)

        # Data quality warning based on data_fields count
        if data_fields < 8:
            result["data_quality_warning"] = "LOW"
        elif data_fields >= 15:
            result["data_quality_warning"] = None
        else:
            result["data_quality_warning"] = None
        result["analysis_date"] = datetime.now().strftime("%Y-%m-%d")
        result["elapsed_seconds"] = round(elapsed, 1)
        result["input_tokens"] = input_tokens
        result["output_tokens"] = output_tokens

        # Track data sources used
        result["data_sources"] = ["yfinance"]
        if _fetch_finnhub_analyst(ticker):
            result["data_sources"].append("Finnhub")
        if web_context and "unavailable" not in web_context:
            result["data_sources"].append("Serper")
            result["data_sources"].append("Google News")

        # Extract fair value fields to top level for DB storage
        fv = result.get("fair_value", {})
        result["fair_value_base"] = fv.get("base")
        result["fair_value_bear"] = fv.get("bear")
        result["fair_value_bull"] = fv.get("bull")

        # Calculate upside from current price
        current_price = (info or {}).get("currentPrice") or (info or {}).get("regularMarketPrice")
        if current_price and fv.get("base"):
            result["upside_pct"] = round((fv["base"] - current_price) / current_price * 100, 1)

        # Map scores to score_breakdown for DB
        result["score_breakdown"] = result.get("scores")
        result["key_risks"] = result.get("risks")
        result["key_catalysts"] = result.get("catalysts")
        result["full_response"] = result.copy()

        return result, ""

    except json.JSONDecodeError as e:
        return None, f"Failed to parse AI response as JSON: {e}"
    except ImportError:
        return None, "anthropic package not installed. Run: pip install anthropic"
    except Exception as e:
        return None, f"Analysis failed: {str(e)}"


# ─────────────────────────────────────────
# BATCH ANALYSIS
# ─────────────────────────────────────────

def run_batch_analysis(
    tickers: list,
    tier: str = "quick",
    info_map: dict = None,
    progress_callback=None,
) -> Dict[str, dict]:
    """
    Run analysis on multiple tickers sequentially.
    Uses 'quick' tier by default for batch to minimize cost.

    Args:
        tickers: List of ticker symbols
        tier: Model tier to use
        info_map: {ticker: yfinance_info_dict}
        progress_callback: Optional callable(ticker, i, total) for progress updates

    Returns:
        {ticker: result_dict} for successful analyses
    """
    if info_map is None:
        info_map = {}

    results = {}
    total = len(tickers)
    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(ticker, i, total)

        info = info_map.get(ticker, {})
        result, error = run_analysis(ticker, tier=tier, info=info)
        if result:
            results[ticker] = result

        # Small delay between API calls to avoid rate limiting
        if i < total - 1:
            time.sleep(0.5)

    return results
