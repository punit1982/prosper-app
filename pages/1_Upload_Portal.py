import streamlit as st
import pandas as pd
from PIL import Image
from core.screenshot_parser import parse_brokerage_image
from core.database import save_holdings

st.header("Prosper Portal")
st.caption("Upload brokerage screenshots to extract your holdings.")

# ------------------------------------------------------------------
# SESSION STATE SETUP
# Streamlit reruns the whole page on every button click.
# We use st.session_state to remember parsed holdings across reruns.
# ------------------------------------------------------------------
if "parsed_holdings" not in st.session_state:
    st.session_state.parsed_holdings = []
if "last_uploaded_names" not in st.session_state:
    st.session_state.last_uploaded_names = []
if "save_done" not in st.session_state:
    st.session_state.save_done = False

# --- Sidebar: Upload Controls ---
with st.sidebar:
    st.subheader("Step 1 — Upload")
    uploaded_files = st.file_uploader(
        "Drop brokerage screenshots here",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
        help="You can upload multiple screenshots at once. Max 50MB each.",
    )

    broker_source = st.selectbox(
        "Broker (optional)",
        ["Auto-detect", "IBKR", "Zerodha", "HSBC", "Tiger Brokers", "Other"],
    )

    st.divider()
    st.subheader("Step 2 — Parse")
    parse_button = st.button(
        "Parse with AI",
        type="primary",
        disabled=not uploaded_files,
        use_container_width=True,
    )

    # If new files are uploaded, clear previous results
    if uploaded_files:
        current_names = sorted([f.name for f in uploaded_files])
        if current_names != st.session_state.last_uploaded_names:
            st.session_state.parsed_holdings = []
            st.session_state.last_uploaded_names = current_names
            st.session_state.save_done = False

# --- No files yet ---
if not uploaded_files:
    st.info(
        "**How it works:**\n\n"
        "1. Upload one or more brokerage screenshots using the sidebar\n"
        "2. Click **Parse with AI** — Claude reads your screenshot and extracts holdings\n"
        "3. Review the table, fix anything if needed\n"
        "4. Click **Save to Portfolio**\n\n"
        "You can upload multiple screenshots at once (e.g. from different brokers)."
    )
    st.stop()

# --- Files uploaded but not yet parsed ---
if not parse_button and not st.session_state.parsed_holdings:
    st.subheader("Ready to Parse")
    cols = st.columns(min(len(uploaded_files), 3))
    for i, file in enumerate(uploaded_files):
        with cols[i % 3]:
            image = Image.open(file)
            st.image(image, caption=file.name, width="stretch")
    st.info("Click **Parse with AI** in the sidebar to extract your holdings.")
    st.stop()

# --- Run parsing when button clicked ---
if parse_button and uploaded_files:
    st.session_state.parsed_holdings = []
    st.session_state.save_done = False
    all_holdings = []

    for file in uploaded_files:
        with st.spinner(f"Reading {file.name}..."):
            file.seek(0)
            result = parse_brokerage_image(file.getvalue(), file.type)

        if isinstance(result, str):
            st.error(f"**{file.name}** — {result}")
        elif isinstance(result, list) and len(result) > 0:
            st.success(f"✓ Extracted {len(result)} holdings from **{file.name}**")
            all_holdings.extend(result)
        else:
            st.warning(f"No holdings found in **{file.name}**.")

    st.session_state.parsed_holdings = all_holdings

# --- Show results table (persists across button clicks) ---
if not st.session_state.parsed_holdings:
    st.warning("No holdings were extracted. Try uploading a clearer screenshot.")
    st.stop()

# Save success banner
if st.session_state.save_done:
    st.success(
        "✅ Portfolio saved! Go to **Portfolio Dashboard** in the sidebar to view it."
    )
    if st.button("Upload More Screenshots", use_container_width=True):
        st.session_state.parsed_holdings = []
        st.session_state.last_uploaded_names = []
        st.session_state.save_done = False
        st.rerun()
    st.stop()

# --- Editable table ---
st.subheader("Step 3 — Review & Save")
st.caption(
    "Check the data below. Click any cell to edit. "
    "When everything looks right, click **Save to Portfolio**."
)

df = pd.DataFrame(st.session_state.parsed_holdings)
for col in ["ticker", "name", "quantity", "avg_cost", "currency"]:
    if col not in df.columns:
        df[col] = ""

edited_df = st.data_editor(
    df[["ticker", "name", "quantity", "avg_cost", "currency"]],
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "ticker": st.column_config.TextColumn("Ticker", help="e.g. AAPL, RELIANCE.NS"),
        "name": st.column_config.TextColumn("Company Name"),
        "quantity": st.column_config.NumberColumn("Qty", min_value=0, format="%.4f"),
        "avg_cost": st.column_config.NumberColumn("Avg Cost", min_value=0, format="%.4f"),
        "currency": st.column_config.SelectboxColumn(
            "Currency",
            options=["USD", "INR", "AED", "EUR", "GBP", "SGD", "HKD", "JPY", "CNY", "AUD"],
            default="USD",
        ),
    },
)

st.divider()
broker = broker_source if broker_source != "Auto-detect" else None

if st.button("💾 Save to Portfolio", type="primary", use_container_width=True):
    if edited_df.empty:
        st.warning("Nothing to save — the table is empty.")
    else:
        save_holdings(edited_df, broker_source=broker)
        st.session_state.save_done = True
        st.rerun()
