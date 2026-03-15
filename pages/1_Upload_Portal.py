"""
Upload Portal
=============
Upload brokerage screenshots, CSVs, Excel files, or PDFs to extract portfolio holdings.
Supports: PNG/JPG (AI vision), CSV, XLSX, PDF (AI vision).
"""

import streamlit as st
import pandas as pd
from PIL import Image
from core.screenshot_parser import parse_brokerage_image
from core.database import save_holdings

st.header("Prosper Portal")
st.caption("Upload brokerage screenshots, CSVs, Excel files, or PDFs to extract your holdings.")

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


# ─────────────────────────────────────────
# TABULAR FILE PARSERS (CSV / Excel)
# ─────────────────────────────────────────

# Common column name mappings brokers use
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


def _auto_map_columns(df: pd.DataFrame) -> dict:
    """Try to auto-detect which CSV/Excel columns map to our fields."""
    mapping = {}
    cols_lower = {c: c.strip().lower() for c in df.columns}

    for field, aliases in _COL_ALIASES.items():
        for orig_col, low_col in cols_lower.items():
            if low_col in aliases:
                mapping[field] = orig_col
                break

    return mapping


def _parse_tabular(df: pd.DataFrame, default_currency: str = "USD") -> list:
    """Parse a DataFrame from CSV/Excel into holdings list."""
    if df.empty:
        return []

    # Clean column names
    df.columns = df.columns.str.strip()

    # Auto-map columns
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
# MAIN PAGE LOGIC — Upload in center
# ─────────────────────────────────────────

# --- Save success banner ---
if st.session_state.save_done:
    st.success(
        "Portfolio saved! Go to **Portfolio Dashboard** in the sidebar to view it."
    )
    if st.button("Upload More Files", use_container_width=True):
        st.session_state.parsed_holdings = []
        st.session_state.last_uploaded_names = []
        st.session_state.save_done = False
        st.rerun()
    st.stop()

# --- Step 1: Upload zone (centered) ---
broker_source = "Auto-detect"  # default; overridden below if files uploaded

if not st.session_state.parsed_holdings:
    st.markdown("### Step 1 — Upload Files")

    # Central upload area
    uploaded_files = st.file_uploader(
        "Drop brokerage files here",
        type=["png", "jpg", "jpeg", "csv", "xlsx", "xls", "pdf"],
        accept_multiple_files=True,
        help="Supported: Screenshots (PNG/JPG), CSV, Excel (XLSX), PDF. Max 50MB each.",
        label_visibility="collapsed",
    )

    # Broker + parse controls (inline below uploader)
    if uploaded_files:
        col_broker, col_parse = st.columns([2, 1])
        with col_broker:
            broker_source = st.selectbox(
                "Broker (optional)",
                ["Auto-detect", "IBKR", "Zerodha", "HSBC", "Tiger Brokers", "Saxo", "Swissquote", "Other"],
            )
        with col_parse:
            st.markdown("<br>", unsafe_allow_html=True)
            parse_button = st.button(
                "Parse Files",
                type="primary",
                use_container_width=True,
            )

        # Detect new upload
        current_names = sorted([f.name for f in uploaded_files])
        if current_names != st.session_state.last_uploaded_names:
            st.session_state.parsed_holdings = []
            st.session_state.last_uploaded_names = current_names
            st.session_state.save_done = False
    else:
        broker_source = "Auto-detect"
        parse_button = False

    # --- No files yet → show instructions ---
    if not uploaded_files:
        st.info(
            "**How it works:**\n\n"
            "1. Upload one or more files above\n"
            "   - **Screenshots** (PNG/JPG): AI reads your brokerage screen\n"
            "   - **CSV / Excel**: Auto-maps columns (Ticker, Qty, Avg Cost, Currency)\n"
            "   - **PDF**: AI extracts holdings from statements\n"
            "2. Click **Parse Files** to extract holdings\n"
            "3. Review the table, fix anything if needed\n"
            "4. Click **Save to Portfolio**\n\n"
            "You can upload multiple files at once (e.g. from different brokers)."
        )
        st.stop()

    # --- Files uploaded, show previews ---
    if not parse_button:
        st.subheader("File Preview")
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
                st.caption(f"**{file.name}** (PDF — will be parsed by AI)")

        st.info("Click **Parse Files** above to extract your holdings.")
        st.stop()

    # --- Run parsing ---
    if parse_button and uploaded_files:
        st.session_state.parsed_holdings = []
        st.session_state.save_done = False
        all_holdings = []

        for file in uploaded_files:
            ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""

            if ext == "csv":
                with st.spinner(f"Reading CSV: {file.name}..."):
                    try:
                        file.seek(0)
                        df = pd.read_csv(file)
                        parsed = _parse_tabular(df)
                        if parsed:
                            st.success(f"Extracted {len(parsed)} holdings from **{file.name}**")
                            all_holdings.extend(parsed)
                        else:
                            st.warning(f"No holdings found in **{file.name}**. Check column names.")
                    except Exception as e:
                        st.error(f"**{file.name}** — Error reading CSV: {e}")

            elif ext in ("xlsx", "xls"):
                with st.spinner(f"Reading Excel: {file.name}..."):
                    try:
                        file.seek(0)
                        df = pd.read_excel(file)
                        parsed = _parse_tabular(df)
                        if parsed:
                            st.success(f"Extracted {len(parsed)} holdings from **{file.name}**")
                            all_holdings.extend(parsed)
                        else:
                            st.warning(f"No holdings found in **{file.name}**. Check column names.")
                    except Exception as e:
                        st.error(f"**{file.name}** — Error reading Excel: {e}")

            elif ext == "pdf":
                with st.spinner(f"AI parsing PDF: {file.name}..."):
                    file.seek(0)
                    result = parse_brokerage_image(file.getvalue(), "application/pdf")
                    if isinstance(result, str):
                        st.error(f"**{file.name}** — {result}")
                    elif isinstance(result, list) and len(result) > 0:
                        st.success(f"Extracted {len(result)} holdings from **{file.name}**")
                        all_holdings.extend(result)
                    else:
                        st.warning(f"No holdings found in **{file.name}**.")

            elif ext in ("png", "jpg", "jpeg"):
                with st.spinner(f"AI parsing image: {file.name}..."):
                    file.seek(0)
                    result = parse_brokerage_image(file.getvalue(), file.type)
                    if isinstance(result, str):
                        st.error(f"**{file.name}** — {result}")
                    elif isinstance(result, list) and len(result) > 0:
                        st.success(f"Extracted {len(result)} holdings from **{file.name}**")
                        all_holdings.extend(result)
                    else:
                        st.warning(f"No holdings found in **{file.name}**.")

        st.session_state.parsed_holdings = all_holdings

# --- Show results table (persists across clicks) ---
if not st.session_state.parsed_holdings:
    if not st.session_state.save_done:
        st.warning("No holdings were extracted. Try uploading a different file or clearer screenshot.")
    st.stop()

# --- Editable table ---
st.subheader("Step 2 — Review & Save")
st.caption(
    "Check the data below. Click any cell to edit. "
    "When everything looks right, click **Save to Portfolio**."
)

df = pd.DataFrame(st.session_state.parsed_holdings)
for col in ["ticker", "name", "quantity", "avg_cost", "currency"]:
    if col not in df.columns:
        df[col] = ""

# Highlight missing critical fields
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
    st.warning(
        "**Missing data detected:** " + " · ".join(issues) + "\n\n"
        "Please fill in the missing values below before saving."
    )

edited_df = st.data_editor(
    df[["ticker", "name", "quantity", "avg_cost", "currency"]],
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "ticker": st.column_config.TextColumn("Ticker", help="e.g. AAPL, RELIANCE.NS, SREN.SW"),
        "name": st.column_config.TextColumn("Company Name"),
        "quantity": st.column_config.NumberColumn("Qty", min_value=0, format="%.4f"),
        "avg_cost": st.column_config.NumberColumn("Avg Cost", min_value=0, format="%.4f"),
        "currency": st.column_config.SelectboxColumn(
            "Currency",
            options=SUPPORTED_CURRENCIES,
            default="USD",
        ),
    },
)

st.divider()
broker = broker_source if broker_source != "Auto-detect" else None

if st.button("Save to Portfolio", type="primary", use_container_width=True):
    if edited_df.empty:
        st.warning("Nothing to save — the table is empty.")
    else:
        save_holdings(edited_df, broker_source=broker)
        st.session_state.save_done = True
        st.rerun()
