"""
Upload Portal — Modern File Upload Experience
===============================================
Upload brokerage screenshots, CSVs, Excel files, or PDFs to extract portfolio holdings.
Supports: PNG/JPG (AI vision), CSV, XLSX, PDF (AI vision).
"""

import streamlit as st
import pandas as pd
from PIL import Image
from core.screenshot_parser import parse_brokerage_image
from core.database import save_holdings, get_all_holdings, save_cash_position

# ── Page Header ──────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='margin-bottom:0'>Upload Portal</h1>"
    "<p style='color:#888;font-size:1.05rem;margin-top:0'>"
    "Import holdings from any broker — screenshots, CSVs, Excel, or PDFs</p>",
    unsafe_allow_html=True,
)

SUPPORTED_CURRENCIES = [
    "USD", "AED", "INR", "EUR", "GBP", "CHF", "SGD", "HKD",
    "JPY", "CNY", "AUD", "CAD", "SAR", "KWD", "QAR",
    "BHD", "OMR", "ZAR", "MYR", "KRW", "BRL",
]

# ------------------------------------------------------------------
# SESSION STATE SETUP
# ------------------------------------------------------------------
if "parsed_holdings" not in st.session_state:
    st.session_state.parsed_holdings = []
if "last_uploaded_names" not in st.session_state:
    st.session_state.last_uploaded_names = []
if "save_done" not in st.session_state:
    st.session_state.save_done = False
if "saving_in_progress" not in st.session_state:
    st.session_state.saving_in_progress = False


# ─────────────────────────────────────────
# TABULAR FILE PARSERS (CSV / Excel)
# ─────────────────────────────────────────
_COL_ALIASES = {
    "ticker":   ["ticker", "symbol", "stock", "instrument", "code", "stock code",
                 "security", "scrip", "isin", "stock symbol", "asset"],
    "name":     ["name", "company", "company name", "description", "stock name",
                 "security name", "instrument name", "holding"],
    "quantity": ["quantity", "qty", "units", "shares", "position", "no. of shares",
                 "holdings", "volume", "lot", "nos"],
    "avg_cost": ["avg_cost", "avg cost", "avg. cost", "average cost", "avg price",
                 "average price", "buy avg", "buy price", "purchase price", "wac",
                 "avg unit cost", "cost price", "cost/share", "cost per share",
                 "average buy price"],
    "currency": ["currency", "ccy", "cur", "curr"],
}

# Cash/margin detection keywords in ticker or account name fields
_CASH_KEYWORDS = {
    "cash", "cash balance", "settled cash", "available cash", "net cash",
    "margin", "margin balance", "margin debit", "debit balance", "borrowing",
    "money market", "sweep", "core position", "free balance", "buying power",
    "ledger balance", "credit balance", "net liquidation",
}

def _is_cash_line(ticker: str, name: str) -> bool:
    """Detect if a parsed line represents a cash/margin balance, not a stock."""
    combined = f"{ticker} {name}".lower()
    for kw in _CASH_KEYWORDS:
        if kw in combined:
            return True
    # Specific patterns
    if ticker.upper() in ("CASH", "USD", "EUR", "GBP", "INR", "AED", "SGD", "HKD"):
        return True
    return False


def _auto_map_columns(df: pd.DataFrame) -> dict:
    mapping = {}
    cols_lower = {c: c.strip().lower() for c in df.columns}
    for field, aliases in _COL_ALIASES.items():
        for orig_col, low_col in cols_lower.items():
            if low_col in aliases:
                mapping[field] = orig_col
                break
    return mapping


def _parse_tabular(df: pd.DataFrame, default_currency: str = "USD") -> list:
    if df.empty:
        return []
    df.columns = df.columns.str.strip()
    col_map = _auto_map_columns(df)
    holdings = []
    for _, row in df.iterrows():
        ticker = str(row.get(col_map.get("ticker", ""), "") or "").strip()
        if not ticker:
            continue
        name = str(row.get(col_map.get("name", ""), "") or "").strip()
        currency = str(row.get(col_map.get("currency", ""), default_currency) or default_currency).strip()
        try:
            qty = float(str(row.get(col_map.get("quantity", ""), 0) or 0).replace(",", ""))
        except (ValueError, TypeError):
            qty = 0
        try:
            avg_cost = float(str(row.get(col_map.get("avg_cost", ""), 0) or 0).replace(",", ""))
        except (ValueError, TypeError):
            avg_cost = 0
        if qty > 0:
            holdings.append({
                "ticker": ticker,
                "name": name,
                "quantity": qty,
                "avg_cost": avg_cost,
                "currency": currency.upper() if currency else default_currency,
            })
    return holdings


# ─────────────────────────────────────────
# BACKUP & RESTORE (collapsible, bottom priority)
# ─────────────────────────────────────────
_existing = get_all_holdings()

with st.expander("Backup & Restore" + (f" ({len(_existing)} holdings)" if not _existing.empty else ""), expanded=False):
    col_backup, col_restore = st.columns(2)
    with col_backup:
        if not _existing.empty:
            _csv = _existing[["ticker", "name", "quantity", "avg_cost", "currency"]].to_csv(index=False)
            st.download_button(
                "Download Backup CSV",
                data=_csv,
                file_name=f"prosper_backup_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.caption("No holdings to backup.")
    with col_restore:
        restore_file = st.file_uploader("Restore from CSV", type=["csv"], key="restore_csv")
        if restore_file:
            try:
                restore_df = pd.read_csv(restore_file)
                if st.button("Restore Now", type="primary", use_container_width=True):
                    save_holdings(restore_df)
                    st.success(f"Restored {len(restore_df)} holdings!")
                    st.rerun()
            except Exception as e:
                st.error(f"Invalid CSV: {e}")

# ─────────────────────────────────────────
# SAVE SUCCESS STATE
# ─────────────────────────────────────────
if st.session_state.save_done:
    st.success("Portfolio saved successfully!")
    col_a, col_b = st.columns(2)
    with col_a:
        st.page_link("pages/2_Portfolio_Dashboard.py", label="View Portfolio Dashboard", icon="📊")
    with col_b:
        if st.button("Upload More Files", use_container_width=True):
            st.session_state.parsed_holdings = []
            st.session_state.last_uploaded_names = []
            st.session_state.save_done = False
            st.session_state.saving_in_progress = False
            st.rerun()
    st.stop()


# ─────────────────────────────────────────
# STEP 1: UPLOAD ZONE
# ─────────────────────────────────────────
broker_source = "Auto-detect"

if not st.session_state.parsed_holdings:
    # Step indicator
    st.markdown(
        "<div style='display:flex;gap:12px;margin:1rem 0'>"
        "<span style='background:#1E88E5;color:white;border-radius:50%;width:28px;height:28px;"
        "display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px'>1</span>"
        "<span style='font-size:1.1rem;font-weight:600;padding-top:2px'>Upload Files</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    uploaded_files = st.file_uploader(
        "Drop brokerage files here",
        type=["png", "jpg", "jpeg", "csv", "xlsx", "xls", "pdf"],
        accept_multiple_files=True,
        help="Screenshots (PNG/JPG), CSV, Excel (XLSX), PDF. Max 50MB each.",
        label_visibility="collapsed",
    )

    if uploaded_files:
        col_broker, col_parse = st.columns([2, 1])
        with col_broker:
            broker_source = st.selectbox(
                "Broker (optional)",
                ["Auto-detect", "IBKR", "Zerodha", "HSBC", "Tiger Brokers", "Saxo", "Swissquote", "Other"],
            )
        with col_parse:
            st.markdown("<br>", unsafe_allow_html=True)
            parse_button = st.button("Parse Files", type="primary", use_container_width=True)

        # Detect new upload
        current_names = sorted([f.name for f in uploaded_files])
        if current_names != st.session_state.last_uploaded_names:
            st.session_state.parsed_holdings = []
            st.session_state.last_uploaded_names = current_names
            st.session_state.save_done = False
    else:
        broker_source = "Auto-detect"
        parse_button = False

    # No files uploaded — show quick start guide
    if not uploaded_files:
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(
                "<div style='padding:16px;border-radius:12px;border:1px solid #333;text-align:center'>"
                "<div style='font-size:2rem'>📷</div>"
                "<div style='font-weight:600;margin:8px 0'>Screenshots</div>"
                "<div style='color:#888;font-size:0.85rem'>PNG or JPG from any broker app</div>"
                "</div>",
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                "<div style='padding:16px;border-radius:12px;border:1px solid #333;text-align:center'>"
                "<div style='font-size:2rem'>📊</div>"
                "<div style='font-weight:600;margin:8px 0'>CSV / Excel</div>"
                "<div style='color:#888;font-size:0.85rem'>Auto-maps Ticker, Qty, Cost columns</div>"
                "</div>",
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                "<div style='padding:16px;border-radius:12px;border:1px solid #333;text-align:center'>"
                "<div style='font-size:2rem'>📄</div>"
                "<div style='font-weight:600;margin:8px 0'>PDF Statements</div>"
                "<div style='color:#888;font-size:0.85rem'>AI reads brokerage statements</div>"
                "</div>",
                unsafe_allow_html=True,
            )
        st.stop()

    # Files uploaded, show previews before parse
    if not parse_button:
        with st.expander("File Preview", expanded=True):
            for file in uploaded_files:
                ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
                if ext in ("png", "jpg", "jpeg"):
                    try:
                        image = Image.open(file)
                        st.image(image, caption=file.name, width=400)
                        file.seek(0)
                    except Exception:
                        st.caption(f"**{file.name}** (image)")
                elif ext == "csv":
                    st.caption(f"**{file.name}** (CSV)")
                    try:
                        preview = pd.read_csv(file, nrows=5)
                        st.dataframe(preview, use_container_width=True)
                        file.seek(0)
                    except Exception as e:
                        st.warning(f"Could not preview: {e}")
                elif ext in ("xlsx", "xls"):
                    st.caption(f"**{file.name}** (Excel)")
                    try:
                        preview = pd.read_excel(file, nrows=5)
                        st.dataframe(preview, use_container_width=True)
                        file.seek(0)
                    except Exception as e:
                        st.warning(f"Could not preview: {e}")
                elif ext == "pdf":
                    st.caption(f"**{file.name}** (PDF)")
        st.info("Click **Parse Files** above to extract holdings.")
        st.stop()

    # --- Run parsing ---
    if parse_button and uploaded_files:
        st.session_state.parsed_holdings = []
        st.session_state.save_done = False
        all_holdings = []

        progress_bar = st.progress(0, text="Parsing files...")
        total_files = len(uploaded_files)

        for i, file in enumerate(uploaded_files):
            ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
            progress_bar.progress((i + 1) / total_files, text=f"Parsing {file.name}...")

            if ext == "csv":
                try:
                    file.seek(0)
                    df = pd.read_csv(file)
                    parsed = _parse_tabular(df)
                    if parsed:
                        st.success(f"Extracted **{len(parsed)}** holdings from {file.name}")
                        all_holdings.extend(parsed)
                    else:
                        st.warning(f"No holdings found in {file.name}")
                except Exception as e:
                    st.error(f"{file.name} — Error: {e}")

            elif ext in ("xlsx", "xls"):
                try:
                    file.seek(0)
                    df = pd.read_excel(file)
                    parsed = _parse_tabular(df)
                    if parsed:
                        st.success(f"Extracted **{len(parsed)}** holdings from {file.name}")
                        all_holdings.extend(parsed)
                    else:
                        st.warning(f"No holdings found in {file.name}")
                except Exception as e:
                    st.error(f"{file.name} — Error: {e}")

            elif ext == "pdf":
                with st.spinner(f"AI parsing {file.name}..."):
                    file.seek(0)
                    result = parse_brokerage_image(file.getvalue(), "application/pdf")
                    if isinstance(result, str):
                        st.error(f"{file.name} — {result}")
                    elif isinstance(result, list) and len(result) > 0:
                        st.success(f"Extracted **{len(result)}** holdings from {file.name}")
                        all_holdings.extend(result)
                    else:
                        st.warning(f"No holdings found in {file.name}")

            elif ext in ("png", "jpg", "jpeg"):
                with st.spinner(f"AI parsing {file.name}..."):
                    file.seek(0)
                    result = parse_brokerage_image(file.getvalue(), file.type)
                    if isinstance(result, str):
                        st.error(f"{file.name} — {result}")
                    elif isinstance(result, list) and len(result) > 0:
                        st.success(f"Extracted **{len(result)}** holdings from {file.name}")
                        all_holdings.extend(result)
                    else:
                        st.warning(f"No holdings found in {file.name}")

        progress_bar.empty()
        st.session_state.parsed_holdings = all_holdings


# ─────────────────────────────────────────
# STEP 2: REVIEW & EDIT
# ─────────────────────────────────────────
if not st.session_state.parsed_holdings:
    if not st.session_state.save_done:
        st.warning("No holdings extracted. Try a different file or clearer screenshot.")
    st.stop()

# Step indicator
st.markdown(
    "<div style='display:flex;gap:12px;margin:1rem 0'>"
    "<span style='background:#1E88E5;color:white;border-radius:50%;width:28px;height:28px;"
    "display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px'>2</span>"
    "<span style='font-size:1.1rem;font-weight:600;padding-top:2px'>Review & Save</span>"
    "</div>",
    unsafe_allow_html=True,
)

col_title, col_restart = st.columns([3, 1])
with col_restart:
    if st.button("Clear & Start Over"):
        st.session_state.parsed_holdings = []
        st.session_state.last_uploaded_names = []
        st.session_state.save_done = False
        st.session_state.saving_in_progress = False
        st.rerun()

st.caption("Click any cell to edit. When everything looks right, click **Save to Portfolio**.")

df = pd.DataFrame(st.session_state.parsed_holdings)
for col in ["ticker", "name", "quantity", "avg_cost", "currency"]:
    if col not in df.columns:
        df[col] = ""

# Highlight missing fields
missing_currency = df["currency"].isna() | (df["currency"].astype(str).isin(["", "nan"]))
missing_avg_cost = pd.to_numeric(df["avg_cost"], errors="coerce").fillna(0) == 0
missing_qty = pd.to_numeric(df["quantity"], errors="coerce").fillna(0) == 0

if missing_currency.any() or missing_avg_cost.any() or missing_qty.any():
    issues = []
    if missing_currency.any():
        issues.append(f"**Currency** missing for {missing_currency.sum()} row(s)")
    if missing_avg_cost.any():
        issues.append(f"**Avg Cost** missing for {missing_avg_cost.sum()} row(s)")
    if missing_qty.any():
        issues.append(f"**Quantity** missing for {missing_qty.sum()} row(s)")
    st.warning("Missing data: " + " · ".join(issues))

edited_df = st.data_editor(
    df[["ticker", "name", "quantity", "avg_cost", "currency"]],
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "ticker": st.column_config.TextColumn("Ticker", help="e.g. AAPL, RELIANCE.NS, SREN.SW"),
        "name": st.column_config.TextColumn("Company Name"),
        "quantity": st.column_config.NumberColumn("Qty", min_value=0, format="%.4f"),
        "avg_cost": st.column_config.NumberColumn("Avg Cost", min_value=0, format="%.4f"),
        "currency": st.column_config.SelectboxColumn("Currency", options=SUPPORTED_CURRENCIES, default="USD"),
    },
)

st.divider()
broker = broker_source if broker_source != "Auto-detect" else None

# ── Detect cash/margin lines ──
cash_lines = []
stock_lines = []
for idx, row in edited_df.iterrows():
    ticker = str(row.get("ticker", "")).strip()
    name = str(row.get("name", "")).strip()
    if _is_cash_line(ticker, name):
        # For cash lines, quantity * avg_cost = total amount, or just use quantity as amount
        amt = float(row.get("quantity", 0) or 0)
        # If avg_cost is set and looks like a total, use it
        avg = float(row.get("avg_cost", 0) or 0)
        amount = amt * avg if avg > 0 and amt > 0 else (amt if amt != 0 else avg)
        cash_lines.append({
            "account_name": name or ticker,
            "currency": str(row.get("currency", "USD")).strip(),
            "amount": amount,
            "is_margin": "margin" in f"{ticker} {name}".lower() or amount < 0,
        })
    else:
        stock_lines.append(idx)

if cash_lines:
    st.info(f"💵 **{len(cash_lines)} cash/margin line(s) detected** — these will be saved as cash positions, not stock holdings.")
    for cl in cash_lines:
        sign = "🔴" if cl["amount"] < 0 or cl["is_margin"] else "🟢"
        margin_tag = " *(margin)*" if cl["is_margin"] else ""
        st.markdown(f"{sign} **{cl['account_name']}** — {cl['currency']} {cl['amount']:,.2f}{margin_tag}")
    st.divider()

# ─── SAVE BUTTON — with double-click protection ─────────────────────────────
is_saving = st.session_state.saving_in_progress

if st.button(
    "Saving..." if is_saving else "Save to Portfolio",
    type="primary",
    use_container_width=True,
    disabled=is_saving,
):
    if edited_df.empty and not cash_lines:
        st.warning("Nothing to save — the table is empty.")
    else:
        # Set flag BEFORE save to prevent double-click
        st.session_state.saving_in_progress = True
        try:
            # Save stock holdings (exclude cash lines)
            if stock_lines:
                stock_df = edited_df.loc[stock_lines]
                if not stock_df.empty:
                    save_holdings(stock_df, broker_source=broker)

            # Save cash positions
            for cl in cash_lines:
                save_cash_position(
                    account_name=cl["account_name"],
                    currency=cl["currency"],
                    amount=cl["amount"],
                    is_margin=cl["is_margin"],
                    broker_source=broker,
                )

            st.session_state.save_done = True
            st.session_state.saving_in_progress = False
            st.rerun()
        except Exception:
            st.session_state.saving_in_progress = False
