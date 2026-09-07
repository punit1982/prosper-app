"""
SEC EDGAR XBRL client — primary filing data without an LLM
==========================================================
Pulls the load-bearing financial figures for US filers straight from the SEC's structured XBRL
API, as numbers with the accession number of the filing they came from.

Why this exists
---------------
GROW's expensive tier spends ~25 web_fetch calls pulling up to 40,000 tokens of page content
each — roughly 1M input tokens a name — and a large share of that is a language model reading
figures back out of HTML it was just handed. That is the single dominant cost in the engine, and
it is also the weakest link in the evidence chain: a number re-read from a rendered page has no
provenance.

This replaces that for US filers. Every figure below arrives as a number, tagged with the form
(10-K / 10-Q), the fiscal period, the filing date and the accession number — which is exactly the
Class A, primary-source evidence GROW §6 asks for and an HTML fetch can never provide. Searches
are then free to be spent on what XBRL genuinely cannot give: guidance, competitive position,
management credibility.

Coverage and limits
-------------------
* **US filers only.** SREN.SW, EMAAR.AE, the India lines and the LSE/Lux funds are not in EDGAR
  and still need retrieval. `filing_snapshot()` returns None for them and the caller falls back.
* Foreign private issuers file 20-F rather than 10-K; those are included where tagged.
* Concept names are NOT consistent between filers — HIMS tags revenue only as
  `RevenueFromContractWithCustomerExcludingAssessedTax` and has no `Revenues` at all, while ADBE
  has both. Every metric below is therefore an ordered fallback chain, and the concept actually
  used is reported so a reader can see which line was read.

SEC rules
---------
The SEC requires a User-Agent that identifies the requester with a contact address, and asks for
no more than 10 requests/second. Both are honoured below. A generic User-Agent gets blocked.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

_log = logging.getLogger("prosper.edgar")

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# The SEC asks for a real contact address. Overridable so a fork does not impersonate this one.
_CONTACT = os.getenv("SEC_EDGAR_CONTACT", "Prosper Research punit1982@gmail.com")
_UA = {"User-Agent": _CONTACT, "Accept-Encoding": "gzip, deflate"}

_CACHE_DIR = os.path.expanduser("~/prosper_data/edgar")
_CACHE_TTL = 7 * 24 * 3600          # filings do not change; a week is conservative

_MIN_INTERVAL = 0.12                # SEC asks for <= 10 req/s; this is ~8
_last_request = [0.0]


def _pace():
    gap = time.time() - _last_request[0]
    if gap < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - gap)
    _last_request[0] = time.time()


def _get_json(url: str, timeout: int = 40) -> Optional[dict]:
    _pace()
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None                       # not an EDGAR filer — a real answer
        _log.info("EDGAR %s: HTTP %s", url.rsplit("/", 1)[-1], e.code)
        return None
    except Exception as e:
        _log.info("EDGAR %s: %s", url.rsplit("/", 1)[-1], e)
        return None


def _cache_path(key: str) -> str:
    return os.path.join(_CACHE_DIR, f"{key}.json")


def _cache_read(key: str) -> Optional[dict]:
    p = _cache_path(key)
    try:
        if os.path.exists(p) and (time.time() - os.path.getmtime(p)) < _CACHE_TTL:
            with open(p, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _cache_write(key: str, data: dict):
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w") as f:
            json.dump(data, f)
    except OSError:
        pass                                   # ephemeral filesystem — in-process cache still helps


# ─────────────────────────────────────────────────────────────────────────────
# Ticker → CIK
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _ticker_map() -> Dict[str, int]:
    cached = _cache_read("company_tickers")
    data = cached or _get_json(TICKER_MAP_URL)
    if not data:
        return {}
    if not cached:
        _cache_write("company_tickers", data)
    out = {}
    for row in data.values():
        t = str(row.get("ticker", "")).strip().upper()
        if t:
            out[t] = int(row.get("cik_str", 0))
    return out


def ticker_to_cik(ticker: str) -> Optional[int]:
    """CIK for a US-listed ticker, or None.

    A suffixed ticker (SREN.SW, EMAAR.AE, 543895.BO) is not a US filer by construction, so it is
    rejected before the lookup rather than accidentally matching a same-named US company.
    """
    t = (ticker or "").strip().upper()
    if not t or "." in t or ":" in t or not t.replace("-", "").isalnum():
        return None
    return _ticker_map().get(t)


# ─────────────────────────────────────────────────────────────────────────────
# Company facts
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=64)
def company_facts(cik: int) -> Optional[dict]:
    key = f"facts_{cik:010d}"
    cached = _cache_read(key)
    if cached:
        return cached
    data = _get_json(FACTS_URL.format(cik=cik))
    if data:
        _cache_write(key, data)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Metric extraction
# ─────────────────────────────────────────────────────────────────────────────
# Ordered fallback chains. First concept present in the filer's taxonomy wins. Verified live
# against ADBE, HIMS, CRM, UPST and IREN — HIMS in particular carries only the
# RevenueFromContractWithCustomer* tag, so a single-concept lookup would have returned nothing.

_METRICS: Dict[str, Tuple[str, List[str]]] = {
    "revenue": ("us-gaap", [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues", "SalesRevenueNet", "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense"]),
    "gross_profit": ("us-gaap", ["GrossProfit"]),
    "operating_income": ("us-gaap", [
        "OperatingIncomeLoss", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"]),
    "net_income": ("us-gaap", [
        "NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]),
    "operating_cash_flow": ("us-gaap", [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]),
    "capex": ("us-gaap", [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets"]),
    "buybacks": ("us-gaap", [
        "PaymentsForRepurchaseOfCommonStock"]),
    "dividends_paid": ("us-gaap", [
        "PaymentsOfDividendsCommonStock", "PaymentsOfDividends"]),
    "cash": ("us-gaap", [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
    "total_assets": ("us-gaap", ["Assets"]),
    "total_liabilities": ("us-gaap", ["Liabilities"]),
    "equity": ("us-gaap", [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
    "long_term_debt": ("us-gaap", [
        "LongTermDebtNoncurrent", "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations"]),
    "short_term_debt": ("us-gaap", [
        "LongTermDebtCurrent", "ShortTermBorrowings", "DebtCurrent"]),
    # The cover-page share count GROW asks for by name. dei is authoritative; some filers
    # (HIMS) omit it, so fall through to the balance-sheet count.
    "shares_outstanding": ("dei", ["EntityCommonStockSharesOutstanding"]),
    "shares_outstanding_alt": ("us-gaap", [
        "CommonStockSharesOutstanding", "CommonStockSharesIssued"]),
    "diluted_shares": ("us-gaap", [
        "WeightedAverageNumberOfDilutedSharesOutstanding"]),
}

_ANNUAL_FORMS = ("10-K", "20-F", "40-F")
_ALL_FORMS = _ANNUAL_FORMS + ("10-Q", "6-K")


def _series(facts: dict, taxonomy: str, concepts: List[str], *, annual_only: bool,
            limit: int = 5) -> Tuple[List[dict], Optional[str]]:
    """Most recent observations for the first concept that exists, newest first.

    Returns (rows, concept_used). Each row carries its own provenance: the form it came from,
    the fiscal year and period, the filing date and the accession number.
    """
    tax = (facts.get("facts") or {}).get(taxonomy) or {}
    for concept in concepts:
        node = tax.get(concept)
        if not node:
            continue
        best: List[dict] = []
        for unit, entries in (node.get("units") or {}).items():
            for e in entries:
                form = e.get("form") or ""
                if annual_only and form not in _ANNUAL_FORMS:
                    continue
                if form not in _ALL_FORMS:
                    continue
                # Duration facts carry start+end; instant facts only end. For annual figures we
                # want the ~365-day duration, not a quarter that happens to sit in a 10-K.
                if annual_only and e.get("start") and e.get("end"):
                    try:
                        from datetime import date as _d
                        s = _d.fromisoformat(e["start"]); en = _d.fromisoformat(e["end"])
                        if (en - s).days < 300:
                            continue
                    except (ValueError, TypeError):
                        pass
                best.append({
                    "value": e.get("val"), "unit": unit, "end": e.get("end"),
                    "start": e.get("start"), "form": form, "fy": e.get("fy"),
                    "fp": e.get("fp"), "filed": e.get("filed"), "accn": e.get("accn"),
                })
        if not best:
            continue
        # Newest first; where a period is restated in a later filing, keep the later filing.
        best.sort(key=lambda r: (str(r.get("end") or ""), str(r.get("filed") or "")), reverse=True)
        seen, deduped = set(), []
        for r in best:
            if r["end"] in seen:
                continue
            seen.add(r["end"])
            deduped.append(r)
            if len(deduped) >= limit:
                break
        return deduped, concept
    return [], None


def extract_financials(facts: dict, *, years: int = 4) -> dict:
    """Every GROW Class A metric this filer reports, with provenance."""
    out: Dict[str, dict] = {}
    for name, (tax, concepts) in _METRICS.items():
        rows, used = _series(facts, tax, concepts,
                             annual_only=(name not in ("shares_outstanding",)), limit=years)
        if rows:
            out[name] = {"concept": used, "taxonomy": tax, "observations": rows}
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Prompt block
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(v, unit: str) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "n/a"
    if unit == "shares" or abs(v) >= 1e6 and unit != "USD":
        pass
    if abs(v) >= 1e9:
        return f"{v/1e9:,.2f}bn"
    if abs(v) >= 1e6:
        return f"{v/1e6:,.1f}m"
    return f"{v:,.0f}"


_LABELS = [
    ("revenue", "Revenue"), ("gross_profit", "Gross profit"),
    ("operating_income", "Operating income"), ("net_income", "Net income"),
    ("operating_cash_flow", "Operating cash flow"), ("capex", "Capex"),
    ("buybacks", "Buybacks"), ("dividends_paid", "Dividends paid"),
    ("cash", "Cash and equivalents"), ("total_assets", "Total assets"),
    ("total_liabilities", "Total liabilities"), ("equity", "Shareholders' equity"),
    ("long_term_debt", "Long-term debt"), ("short_term_debt", "Short-term debt"),
    ("diluted_shares", "Diluted weighted-average shares"),
]


def filing_snapshot(ticker: str, *, years: int = 4) -> Optional[dict]:
    """Structured filing data for one US ticker, ready to drop into a prompt.

    Returns None when the ticker is not a US EDGAR filer — the caller then falls back to
    ordinary retrieval. Never raises.
    """
    try:
        cik = ticker_to_cik(ticker)
        if not cik:
            return None
        facts = company_facts(cik)
        if not facts:
            return None
        fin = extract_financials(facts, years=years)
        if not fin:
            return None

        lines = [
            f"SEC EDGAR XBRL — PRIMARY FILING DATA (Class A evidence, §6 source ladder)",
            f"Entity: {facts.get('entityName') or ticker} · CIK {cik:010d}",
            "Every figure below is as-filed and carries the accession number of the filing it",
            "came from. These are NOT aggregator estimates — do not re-derive them from the web.",
            "",
        ]

        # Cover-page share count first: GROW asks for it by name.
        sh = fin.get("shares_outstanding") or fin.get("shares_outstanding_alt")
        if sh and sh["observations"]:
            o = sh["observations"][0]
            lines.append(
                f"Shares outstanding (cover page, {sh['concept']}): {_fmt(o['value'], o['unit'])} "
                f"as of {o.get('end')} · {o.get('form')} filed {o.get('filed')} · {o.get('accn')}")
            lines.append("")

        for key, label in _LABELS:
            node = fin.get(key)
            if not node or not node["observations"]:
                continue
            obs = node["observations"]
            cells = " | ".join(
                f"{str(o.get('end'))[:10]}: {_fmt(o['value'], o['unit'])}" for o in obs)
            lines.append(f"{label} ({node['concept']}): {cells}")
            src = obs[0]
            lines.append(f"    latest from {src.get('form')} FY{src.get('fy')} "
                         f"filed {src.get('filed')} · accession {src.get('accn')}")

        missing = [lab for k, lab in _LABELS if k not in fin]
        if missing:
            lines.append("")
            lines.append("NOT TAGGED by this filer (absent from XBRL, not necessarily absent "
                         "from the business — check the filing if load-bearing): "
                         + ", ".join(missing))

        return {
            "ticker": ticker.upper(),
            "cik": cik,
            "entity": facts.get("entityName"),
            "financials": fin,
            "text": "\n".join(lines),
            "concepts_found": len(fin),
        }
    except Exception as e:
        _log.info("EDGAR snapshot failed for %s: %s", ticker, e)
        return None


def is_us_filer(ticker: str) -> bool:
    return ticker_to_cik(ticker) is not None
