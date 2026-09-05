"""
Portfolio file parsers
======================
Turns broker exports into Prosper holdings without any AI call.

Supported (auto-detected):
  • IBKR Activity Statement CSV  — multi-section file ("Statement,Header,…"): reads the
    Open Positions section (+ names/exchanges from Financial Instrument Information, cash from
    Forex Balances, account id/alias from Account Information)
  • Coinbase transaction history CSV — nets Buy / Convert / Sell / staking & reward income
    into positions per asset; USDC is treated as USD cash
  • Trendlyne portfolio Excel (India) — NSEcode/BSEcode, Quantity, Avg. Buy Price → .NS/.BO
  • Generic table (CSV/XLSX) with ticker / quantity / avg cost columns (any aliases)

Every parser returns plain dicts shaped for save_holdings():
  {"ticker", "name", "quantity", "avg_cost", "currency", "broker_source"}
plus cash rows with ticker "CASH" (positive) or "MARGIN" (negative), avg_cost 1.
"""

import csv
import io
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

# IBKR "Listing Exch" → Yahoo Finance suffix
IBKR_EXCHANGE_SUFFIX = {
    "NASDAQ": "", "NYSE": "", "ARCA": "", "AMEX": "", "BATS": "", "PINK": "", "VALUE": "", "NYSENAT": "",
    "EBS": ".SW", "SGX": ".SI", "ADX": ".AE", "DFM": ".AE", "LSE": ".L", "LSEETF": ".L",
    "TSEJ": ".T", "KRX": ".KS", "TSE": ".TO", "IBIS": ".DE", "SBF": ".PA", "BVME": ".MI",
    "AEB": ".AS", "BM": ".MC", "ASX": ".AX", "SEHK": ".HK", "MEXI": ".MX", "NSE": ".NS", "BSE": ".BO",
    "OSE": ".OL", "SFB": ".ST", "CPH": ".CO", "HEX": ".HE", "VSE": ".VI", "WSE": ".WA",
}
# Fallback when the exchange is unknown: currency → suffix
CURRENCY_SUFFIX = {
    "CHF": ".SW", "SGD": ".SI", "AED": ".AE", "GBP": ".L", "JPY": ".T", "KRW": ".KS", "CAD": ".TO",
    "EUR": ".DE", "HKD": ".HK", "INR": ".NS", "AUD": ".AX", "SEK": ".ST", "NOK": ".OL", "DKK": ".CO",
}


def _num(s) -> float:
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        f = float(s)
        return 0.0 if (f != f or f in (float("inf"), float("-inf"))) else f
    t = str(s).strip().replace(",", "").replace("$", "").replace("₹", "").replace("%", "")
    if t in ("", "-", "--", "nan", "None"):
        return 0.0
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    try:
        return float(t)
    except ValueError:
        return 0.0


def _decode(data) -> str:
    if isinstance(data, str):
        return data
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")


# ─────────────────────────────────────────
# IBKR ACTIVITY STATEMENT
# ─────────────────────────────────────────

def is_ibkr_statement(text: str) -> bool:
    head = text[:4000]
    return ("Statement,Header,Field Name" in head or "Open Positions,Header" in text
            or "Financial Instrument Information,Header" in text)


def parse_ibkr_statement(text: str) -> Tuple[List[Dict], List[Dict], Dict]:
    """Parse an IBKR Activity Statement CSV → (holdings, cash_rows, meta)."""
    rows = list(csv.reader(io.StringIO(text)))
    sections: Dict[str, List[List[str]]] = {}
    for r in rows:
        if not r:
            continue
        key = (r[0] or "").strip().lstrip("﻿")
        sections.setdefault(key, []).append(r)

    meta = {"format": "IBKR Activity Statement", "account": "", "alias": "", "name": "", "period": ""}
    for r in sections.get("Account Information", []):
        if len(r) >= 4 and r[1] == "Data":
            if r[2] == "Account":
                meta["account"] = r[3].strip()
            elif r[2] == "Account Alias":
                meta["alias"] = r[3].strip()
            elif r[2] == "Name":
                meta["name"] = r[3].strip()
    for r in sections.get("Statement", []):
        if len(r) >= 4 and r[1] == "Data" and r[2] == "Period":
            meta["period"] = r[3].strip()
    label = meta["alias"] or meta["account"] or "IBKR"
    broker = f"IBKR {label}".strip()
    meta["broker_source"] = broker

    # Symbol → (description, listing exchange, asset category)
    instruments: Dict[str, Tuple[str, str, str]] = {}
    fii = sections.get("Financial Instrument Information", [])
    fii_header = next((r for r in fii if len(r) > 1 and r[1] == "Header"), None)
    if fii_header:
        idx = {c.strip(): i for i, c in enumerate(fii_header)}
        for r in fii:
            if len(r) > 1 and r[1] == "Data":
                def g(col):
                    i = idx.get(col)
                    return r[i].strip() if i is not None and i < len(r) else ""
                instruments[g("Symbol")] = (g("Description"), g("Listing Exch"), g("Asset Category"))

    holdings: List[Dict] = []
    op = sections.get("Open Positions", [])
    op_header = next((r for r in op if len(r) > 1 and r[1] == "Header"), None)
    if op_header:
        idx = {c.strip(): i for i, c in enumerate(op_header)}
        for r in op:
            if len(r) < 3 or r[1] != "Data" or r[2].strip() != "Summary":
                continue

            def g(col):
                i = idx.get(col)
                return r[i].strip() if i is not None and i < len(r) else ""

            symbol = g("Symbol")
            qty = _num(g("Quantity"))
            if not symbol or qty == 0:
                continue
            currency = (g("Currency") or "USD").upper()
            asset_cat = g("Asset Category")
            cost_price = _num(g("Cost Price"))
            if cost_price <= 0 and qty:
                cost_price = _num(g("Cost Basis")) / qty
            desc, exch, _ = instruments.get(symbol, ("", "", asset_cat))
            holdings.append({
                "ticker": ibkr_symbol_to_ticker(symbol, exch, currency, asset_cat),
                "name": desc or symbol,
                "quantity": qty,
                "avg_cost": round(cost_price, 6),
                "currency": currency,
                "broker_source": broker,
                "asset_category": asset_cat,
                "ibkr_symbol": symbol,
            })

    cash_rows: List[Dict] = []
    fx = sections.get("Forex Balances", [])
    fx_header = next((r for r in fx if len(r) > 1 and r[1] == "Header"), None)
    if fx_header:
        idx = {c.strip(): i for i, c in enumerate(fx_header)}
        for r in fx:
            if len(r) < 3 or r[1] != "Data" or r[2].strip() != "Forex":
                continue
            ccy = r[idx["Description"]].strip().upper() if "Description" in idx and idx["Description"] < len(r) else ""
            amt = _num(r[idx["Quantity"]]) if "Quantity" in idx and idx["Quantity"] < len(r) else 0.0
            if not ccy or abs(amt) < 0.5:
                continue
            cash_rows.append({
                "ticker": "CASH" if amt >= 0 else "MARGIN",
                "name": f"{broker} cash {ccy}",
                "quantity": round(amt, 2),
                "avg_cost": 1,
                "currency": ccy,
                "broker_source": broker,
            })
    return holdings, cash_rows, meta


def ibkr_symbol_to_ticker(symbol: str, listing_exch: str = "", currency: str = "USD", asset_cat: str = "") -> str:
    """Map an IBKR symbol to the Yahoo Finance ticker Prosper prices with."""
    s = (symbol or "").strip()
    if not s:
        return s
    if " " in s and asset_cat.lower().startswith("mutual"):
        return s  # fund codes like "FTIFWAU LX" — left for manual mapping
    s = s.replace(" ", "-")
    if "." in s[1:]:  # already suffixed (4519.T, 000660.KS)
        return s
    suffix = IBKR_EXCHANGE_SUFFIX.get((listing_exch or "").upper())
    if suffix is None:
        suffix = "" if currency.upper() == "USD" else CURRENCY_SUFFIX.get(currency.upper(), "")
    # LSE symbols with lowercase class letters (PRYm) → uppercase
    s = s.upper()
    return f"{s}{suffix}"


# ─────────────────────────────────────────
# COINBASE TRANSACTION HISTORY
# ─────────────────────────────────────────

def is_coinbase_transactions(text: str) -> bool:
    head = text[:3000]
    return "Transaction Type" in head and "Quantity Transacted" in head


_STABLECOINS = {"USDC", "USDT", "DAI", "USD"}
_INCOME_TYPES = {"staking income", "reward income", "incentives rewards payout", "rewards income",
                 "learning reward", "receive", "inflation reward", "airdrop"}


def parse_coinbase_transactions(text: str) -> Tuple[List[Dict], List[Dict], Dict]:
    """Net Coinbase transactions into positions. Returns (holdings, cash_rows, meta)."""
    lines = text.splitlines()
    hdr_i = next((i for i, l in enumerate(lines) if "Transaction Type" in l and "Quantity Transacted" in l), None)
    meta = {"format": "Coinbase transactions", "broker_source": "Coinbase"}
    if hdr_i is None:
        return [], [], meta
    reader = csv.DictReader(io.StringIO("\n".join(lines[hdr_i:])))
    qty: Dict[str, float] = {}
    cost: Dict[str, float] = {}
    convert_re = re.compile(r"Converted\s+([\d.,]+)\s+([A-Z0-9]+)\s+to\s+([\d.,]+)\s+([A-Z0-9]+)", re.I)

    def add(asset, q, c=0.0):
        qty[asset] = qty.get(asset, 0.0) + q
        cost[asset] = cost.get(asset, 0.0) + c

    for row in reader:
        ttype = (row.get("Transaction Type") or "").strip().lower()
        asset = (row.get("Asset") or "").strip().upper()
        q = _num(row.get("Quantity Transacted"))
        total = abs(_num(row.get("Total (inclusive of fees and/or spread)") or row.get("Subtotal")))
        notes = row.get("Notes") or ""
        if not asset or not ttype:
            continue
        if ttype == "buy":
            add(asset, abs(q), total)
        elif ttype == "sell":
            avg = cost.get(asset, 0) / qty[asset] if qty.get(asset) else 0
            add(asset, -abs(q), -avg * abs(q))
        elif ttype == "convert":
            m = convert_re.search(notes)
            if m:
                from_q, from_a, to_q, to_a = _num(m.group(1)), m.group(2).upper(), _num(m.group(3)), m.group(4).upper()
                basis = total if total else (cost.get(from_a, 0) / qty[from_a] * from_q if qty.get(from_a) else 0)
                avg_from = cost.get(from_a, 0) / qty[from_a] if qty.get(from_a) else 0
                add(from_a, -from_q, -avg_from * from_q)
                add(to_a, to_q, basis)
            else:
                add(asset, q, total if q > 0 else -total)
        elif ttype in _INCOME_TYPES:
            add(asset, abs(q), total)   # income received at fair value
        elif ttype in ("send", "withdrawal"):
            avg = cost.get(asset, 0) / qty[asset] if qty.get(asset) else 0
            add(asset, -abs(q), -avg * abs(q))
        elif "staking transfer" in ttype or ttype in ("deposit", "unstake", "stake"):
            continue  # internal movement between wallet and staking — no change in ownership
        else:
            continue

    holdings, cash_rows = [], []
    for asset, q in qty.items():
        if abs(q) < 1e-9:
            continue
        if asset in _STABLECOINS:
            if q > 0.5:
                cash_rows.append({"ticker": "CASH", "name": f"Coinbase {asset}", "quantity": round(q, 2),
                                  "avg_cost": 1, "currency": "USD", "broker_source": "Coinbase"})
            continue
        if q <= 0:
            continue
        avg = (cost.get(asset, 0.0) / q) if q else 0.0
        holdings.append({"ticker": asset, "name": f"{asset} (Coinbase)", "quantity": round(q, 8),
                         "avg_cost": round(max(avg, 0.0), 4), "currency": "USD", "broker_source": "Coinbase"})
    return holdings, cash_rows, meta


# ─────────────────────────────────────────
# TRENDLYNE (INDIA)
# ─────────────────────────────────────────

def is_trendlyne(df: pd.DataFrame) -> bool:
    cols = {str(c).strip().lower() for c in df.columns}
    return "nsecode" in cols or "bsecode" in cols


def parse_trendlyne(df: pd.DataFrame) -> Tuple[List[Dict], List[Dict], Dict]:
    cols = {str(c).strip().lower(): c for c in df.columns}
    meta = {"format": "Trendlyne portfolio (India)", "broker_source": "India (Trendlyne)"}
    holdings = []
    for _, r in df.iterrows():
        nse = str(r.get(cols.get("nsecode", ""), "") or "").strip()
        bse = str(r.get(cols.get("bsecode", ""), "") or "").strip()
        qty = _num(r.get(cols.get("quantity", ""), 0))
        avg = _num(r.get(cols.get("avg. buy price", cols.get("avg buy price", "")), 0))
        name = str(r.get(cols.get("stock name", ""), "") or "").strip()
        if qty <= 0:
            continue
        if nse and nse.lower() not in ("nan", "none", ""):
            ticker = f"{nse.upper()}.NS"
        elif bse and bse.lower() not in ("nan", "none", ""):
            ticker = f"{bse.split('.')[0]}.BO"
        else:
            continue
        holdings.append({"ticker": ticker, "name": name, "quantity": qty, "avg_cost": avg,
                         "currency": "INR", "broker_source": meta["broker_source"]})
    return holdings, [], meta


# ─────────────────────────────────────────
# GENERIC TABLE
# ─────────────────────────────────────────

_COL_ALIASES = {
    "ticker":   ["ticker", "symbol", "stock", "instrument", "code", "stock code", "security",
                 "scrip", "isin", "stock symbol", "asset"],
    "name":     ["name", "company", "company name", "description", "stock name", "security name",
                 "instrument name", "holding"],
    "quantity": ["quantity", "qty", "units", "shares", "position", "no. of shares", "holdings",
                 "volume", "lot", "nos"],
    "avg_cost": ["avg_cost", "avg cost", "avg. cost", "average cost", "avg price", "average price",
                 "buy avg", "buy price", "purchase price", "wac", "avg unit cost", "cost price",
                 "cost/share", "cost per share", "average buy price", "avg. buy price"],
    "currency": ["currency", "ccy", "cur", "curr"],
}


def _auto_map_columns(df: pd.DataFrame) -> dict:
    mapping = {}
    cols_lower = {c: str(c).strip().lower() for c in df.columns}
    for field, aliases in _COL_ALIASES.items():
        for orig_col, low_col in cols_lower.items():
            if low_col in aliases:
                mapping[field] = orig_col
                break
    return mapping


def parse_generic_table(df: pd.DataFrame, default_currency: str = "USD") -> Tuple[List[Dict], List[Dict], Dict]:
    meta = {"format": "Table", "broker_source": ""}
    if df is None or df.empty:
        return [], [], meta
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    col_map = _auto_map_columns(df)
    holdings = []
    for _, row in df.iterrows():
        ticker = str(row.get(col_map.get("ticker", ""), "") or "").strip()
        if not ticker or ticker.lower() == "nan":
            continue
        name = str(row.get(col_map.get("name", ""), "") or "").strip()
        currency = str(row.get(col_map.get("currency", ""), default_currency) or default_currency).strip()
        qty = _num(row.get(col_map.get("quantity", ""), 0))
        avg_cost = _num(row.get(col_map.get("avg_cost", ""), 0))
        if qty > 0:
            holdings.append({"ticker": ticker, "name": name if name != "nan" else "", "quantity": qty,
                             "avg_cost": avg_cost, "currency": currency.upper() if currency else default_currency,
                             "broker_source": ""})
    return holdings, [], meta


# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────

def parse_portfolio_file(file_name: str, data: bytes, default_currency: str = "USD") -> Tuple[List[Dict], List[Dict], Dict]:
    """Detect the file type and parse it. Returns (holdings, cash_rows, meta). Never raises."""
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    try:
        if ext in ("xlsx", "xls"):
            df = pd.read_excel(io.BytesIO(data))
            if is_trendlyne(df):
                return parse_trendlyne(df)
            return parse_generic_table(df, default_currency)

        text = _decode(data)
        if is_ibkr_statement(text):
            return parse_ibkr_statement(text)
        if is_coinbase_transactions(text):
            return parse_coinbase_transactions(text)
        # Generic CSV — tolerate ragged rows
        try:
            df = pd.read_csv(io.StringIO(text))
        except Exception:
            df = pd.read_csv(io.StringIO(text), engine="python", on_bad_lines="skip")
        if is_trendlyne(df):
            return parse_trendlyne(df)
        return parse_generic_table(df, default_currency)
    except Exception as exc:  # noqa: BLE001
        return [], [], {"format": "unknown", "error": str(exc)[:200], "broker_source": ""}
