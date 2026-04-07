"""
Interactive Brokers Sync
========================
Sync your IBKR portfolio automatically via:
1. CSV Activity Statement (simplest - download from IBKR, upload here)
2. Flex Query API (automatic - set token once, sync on demand)
3. Pre-built Flex Query template (fastest - import template into IBKR in one click)
"""

import streamlit as st
import pandas as pd
import io
from datetime import datetime
from core.settings import get_api_key, load_user_settings, save_user_settings
from core.database import get_all_portfolios, get_active_portfolio_id, save_holdings

# Graceful imports for modules that may not be deployed yet
try:
    from core.ibkr_sync import sync_ibkr_portfolio, get_last_sync_info, save_sync_info
    _IBKR_SYNC_AVAILABLE = True
except ImportError:
    _IBKR_SYNC_AVAILABLE = False

try:
    from core.ibkr_client import IBKRFlexClient  # noqa: F401
    _IBKR_CLIENT_AVAILABLE = True
except ImportError:
    _IBKR_CLIENT_AVAILABLE = False


# ── Page Header ──────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='margin-bottom:0'>🔗 Interactive Brokers Sync</h1>"
    "<p style='color:#888;font-size:1.05rem;margin-top:0'>"
    "Import your IBKR portfolio — Choose the easiest method for you</p>",
    unsafe_allow_html=True,
)

# ── Helper Functions ─────────────────────────────────────────────────────────
def parse_ibkr_csv(csv_file) -> pd.DataFrame:
    """Parse IBKR Activity Statement CSV and extract open positions.

    Handles IBKR's multi-section CSV format by:
    1. Reading entire file as text
    2. Finding "Open Positions" section
    3. Extracting header row and data rows from that section
    4. Parsing positions with flexible column matching
    """
    try:
        # Read as text first to handle IBKR's complex format
        content = csv_file.read().decode('utf-8') if isinstance(csv_file.read(), bytes) else csv_file.read()
        if isinstance(content, bytes):
            content = content.decode('utf-8')

        # Reset file pointer if needed
        csv_file.seek(0)

        lines = content.split('\n')

        # Find "Open Positions" section
        open_pos_idx = None
        for i, line in enumerate(lines):
            if 'Open Positions' in line:
                open_pos_idx = i
                break

        if open_pos_idx is None:
            st.error("Could not find 'Open Positions' section in CSV")
            return pd.DataFrame()

        # Find header row (should be right after "Open Positions" or shortly after)
        header_idx = None
        for i in range(open_pos_idx, min(open_pos_idx + 10, len(lines))):
            if 'Symbol' in lines[i] or 'Ticker' in lines[i]:
                header_idx = i
                break

        if header_idx is None:
            # Try alternative: look for first non-empty line after section
            for i in range(open_pos_idx + 1, min(open_pos_idx + 10, len(lines))):
                if lines[i].strip() and ',' in lines[i]:
                    header_idx = i
                    break

        if header_idx is None:
            st.error("Could not find header row in 'Open Positions' section")
            return pd.DataFrame()

        # Extract header and data rows
        header_line = lines[header_idx]
        headers = [h.strip() for h in header_line.split(',')]

        # Normalize header names (IBKR sometimes uses different cases)
        header_map = {}
        for h in headers:
            h_lower = h.lower().strip()
            if 'symbol' in h_lower or 'ticker' in h_lower:
                header_map['symbol'] = h
            elif 'description' in h_lower or 'name' in h_lower:
                header_map['description'] = h
            elif 'position' in h_lower and 'quantity' not in h_lower:
                header_map['quantity'] = h
            elif 'quantity' in h_lower:
                header_map['quantity'] = h
            elif 'price' in h_lower and 'cost' in h_lower:
                header_map['avg_cost'] = h
            elif 'price' in h_lower and ('mark' in h_lower or 'close' in h_lower):
                header_map['market_price'] = h
            elif 'currency' in h_lower or 'curr' in h_lower:
                header_map['currency'] = h
            elif 'value' in h_lower and ('position' in h_lower or 'market' in h_lower or h_lower == 'value'):
                header_map['position_value'] = h

        if 'symbol' not in header_map:
            st.error("Could not find 'Symbol' column in header")
            return pd.DataFrame()

        # Parse data rows
        positions = []
        for i in range(header_idx + 1, len(lines)):
            line = lines[i].strip()

            # Stop at totals or empty lines
            if not line or 'Total' in line or ',' not in line:
                continue

            try:
                parts = [p.strip() for p in line.split(',')]

                # Map parts to columns based on header
                row_dict = {}
                for col_idx, col_name in enumerate(headers):
                    if col_idx < len(parts):
                        row_dict[col_name] = parts[col_idx]

                symbol = row_dict.get(header_map.get('symbol', ''), '').strip()
                quantity_str = row_dict.get(header_map.get('quantity', ''), '0')
                market_price_str = row_dict.get(header_map.get('market_price', ''), '0')
                currency = row_dict.get(header_map.get('currency', ''), 'USD').strip() or 'USD'
                description = row_dict.get(header_map.get('description', ''), symbol).strip()
                position_value_str = row_dict.get(header_map.get('position_value', ''), '0')
                avg_cost_str = row_dict.get(header_map.get('avg_cost', ''), '0')

                # Clean up strings (remove currency symbols, commas)
                quantity = float(quantity_str.replace(',', '').replace('$', '').strip() or 0)
                market_price = float(market_price_str.replace(',', '').replace('$', '').strip() or 0)
                position_value = float(position_value_str.replace(',', '').replace('$', '').strip() or 0)
                avg_cost = float(avg_cost_str.replace(',', '').replace('$', '').strip() or 0)

                if symbol and symbol != 'Totals' and quantity != 0:
                    # Use avg_cost from Cost Price if available, otherwise calculate from position_value / quantity
                    if avg_cost <= 0:
                        avg_cost = position_value / quantity if quantity != 0 else market_price

                    positions.append({
                        "ticker": symbol,
                        "name": description or symbol,
                        "quantity": quantity,
                        "avg_cost": avg_cost,
                        "currency": currency,
                        "market_price": market_price,
                    })
            except (ValueError, IndexError) as e:
                continue

        if not positions:
            st.warning("No positions found. Make sure the CSV contains 'Open Positions' section with holdings.")
            return pd.DataFrame()

        return pd.DataFrame(positions)
    except Exception as e:
        st.error(f"CSV parsing error: {str(e)}")
        import traceback
        st.error(f"Debug: {traceback.format_exc()}")
        return pd.DataFrame()


def generate_flex_query_template() -> str:
    """Generate a pre-configured Flex Query XML template for IBKR import."""
    template = """<?xml version="1.0" encoding="UTF-8"?>
<!--
    IBKR Flex Query Template for Prosper
    Import this into your IBKR account at: Account Management → Flex Queries → Import

    This template is pre-configured to extract the exact fields Prosper needs:
    - Symbol, Description (company name), Position (quantity)
    - CostBasisPrice (average cost), MarkPrice (market price)
    - Currency, ListingExchange (for international stocks)

    After import:
    1. Generate a Flex Query Token (Account Management → Flex Query Token)
    2. Enter the Token and Query ID in Prosper's IBKR Sync page
    3. Click "Sync Now" to import automatically
-->
<FlexQueryRequest>
    <FlexQuery>
        <QueryName>Prosper Positions</QueryName>
        <FlexTemplate>Activity</FlexTemplate>
        <Sections>
            <Section name="OpenPositions" />
        </Sections>
        <Columns>
            <Column name="assetCategory" />
            <Column name="symbol" />
            <Column name="description" />
            <Column name="position" />
            <Column name="costBasisPrice" />
            <Column name="markPrice" />
            <Column name="markValue" />
            <Column name="currency" />
            <Column name="listingExchange" />
        </Columns>
    </FlexQuery>
</FlexQueryRequest>"""
    return template


st.subheader("📥 Choose Your Sync Method")
sync_method = st.radio(
    "Select how you want to import from IBKR:",
    ["📋 CSV Upload (Easiest)", "🔗 Flex Query API (Automatic)", "⚡ Flex Query Template (Quick Setup)"],
    index=0,
    help="CSV: Download a file, upload it here. Flex API: Set once, sync anytime. Template: Fast setup in IBKR.",
    horizontal=False,
)

st.divider()

# ────────────────────────────────────────────────────────────────────────────
# METHOD 1: CSV UPLOAD
# ────────────────────────────────────────────────────────────────────────────
if sync_method == "📋 CSV Upload (Easiest)":
    st.subheader("📋 CSV Upload Method")

    with st.expander("📖 How to download from IBKR (3 steps)", expanded=True):
        st.markdown("""
        1. **Log into** [IBKR Account Management](https://www.interactivebrokers.com/sso/Login)
        2. **Go to** Reports → Activity → Activity Statement
        3. **Download** the CSV file and upload it below

        That's it! No API keys or Flex Query setup needed.
        """)

    uploaded_file = st.file_uploader("Choose IBKR CSV file", type="csv")

    if uploaded_file:
        positions_df = parse_ibkr_csv(uploaded_file)

        if not positions_df.empty:
            st.success(f"✅ Parsed {len(positions_df)} positions from CSV")

            # Portfolio selector
            portfolios_df = get_all_portfolios()
            if not portfolios_df.empty:
                pf_names = portfolios_df["name"].tolist()
                pf_ids = portfolios_df["id"].tolist()
                current_pid = get_active_portfolio_id()
                current_idx = pf_ids.index(current_pid) if current_pid in pf_ids else 0
                selected_pf = st.selectbox(
                    "Target Portfolio",
                    pf_names,
                    index=current_idx,
                )
                target_portfolio_id = pf_ids[pf_names.index(selected_pf)]
            else:
                target_portfolio_id = 1

            # Show preview
            with st.expander("Preview positions from CSV"):
                st.dataframe(positions_df, use_container_width=True)

            # Import button
            if st.button("📥 Import Positions", type="primary", use_container_width=True):
                try:
                    # Add broker_source and portfolio_id to each position
                    positions_df["broker_source"] = "IBKR"

                    # Save to database
                    save_holdings(positions_df, broker_source="IBKR", portfolio_id=target_portfolio_id)

                    st.success(f"✅ Imported {len(positions_df)} holdings from IBKR CSV!")

                    # Invalidate cache
                    for key in list(st.session_state.keys()):
                        if key.startswith("enriched_") or key in ("last_refresh_time", "extended_df"):
                            del st.session_state[key]

                    st.rerun()
                except Exception as e:
                    st.error(f"Import failed: {str(e)}")
        else:
            st.warning("Could not parse positions from CSV. Make sure it's an IBKR Activity Statement.")

# ────────────────────────────────────────────────────────────────────────────
# METHOD 2: FLEX QUERY TEMPLATE
# ────────────────────────────────────────────────────────────────────────────
elif sync_method == "⚡ Flex Query Template (Quick Setup)":
    st.subheader("⚡ Flex Query Template")

    st.markdown("""
    This is the **fastest way to set up** automatic syncing:

    1. **Download** the template below
    2. **Import** it into your IBKR account (takes 1 click)
    3. **Generate** a Flex Query Token
    4. **Paste** token & Query ID into Prosper
    5. **Click Sync Now** anytime to update
    """)

    template = generate_flex_query_template()

    col_dl, col_help = st.columns([2, 3])
    with col_dl:
        st.download_button(
            "⬇️ Download Template",
            data=template,
            file_name="prosper_flex_query_template.xml",
            mime="application/xml",
        )
    with col_help:
        st.caption("Import this into: Account Management → Flex Queries → Import")

    st.info("""
    **Next steps:**
    1. Go to Account Management → Flex Queries → Import
    2. Upload the template file above
    3. Generate a Flex Query Token (Account Management → Flex Query Token)
    4. Switch to the "Flex Query API" method below and enter your Token & Query ID
    """)

# ────────────────────────────────────────────────────────────────────────────
# METHOD 3: FLEX QUERY API (AUTOMATIC)
# ────────────────────────────────────────────────────────────────────────────
else:  # "🔗 Flex Query API (Automatic)"
    st.subheader("🔗 Flex Query API Setup")

    # Check IBKR Flex Token status
    ibkr_token = get_api_key("IBKR_FLEX_TOKEN")
    _token_placeholder = "your_" in ibkr_token.lower() if ibkr_token else True
    token_configured = bool(ibkr_token) and not _token_placeholder

    if token_configured:
        st.markdown("✅ **IBKR Flex Token** — Configured")
    else:
        st.markdown("❌ **IBKR Flex Token** — Not configured")
        st.caption("Add `IBKR_FLEX_TOKEN` to your `.env` file or Render Environment Variables.")

    # Flex Query ID (stored in user settings, not secrets)
    user_settings = load_user_settings()
    saved_query_id = user_settings.get("ibkr_flex_query_id", "")

    col_qid, col_save = st.columns([3, 1])
    with col_qid:
        flex_query_id = st.text_input(
            "Flex Query ID",
            value=saved_query_id,
            placeholder="e.g. 123456",
            help="The numeric ID of your IBKR Activity Flex Query for open positions.",
        )
    with col_save:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Save Query ID", use_container_width=True):
            save_user_settings({"ibkr_flex_query_id": flex_query_id.strip()})
            st.success("Query ID saved!")
            st.rerun()

    query_id_configured = bool(flex_query_id.strip())

    # Setup instructions for Flex Query API
    with st.expander("📖 How to Set Up FLEX QUERY API (5 minutes)"):
        st.markdown("""
    **Option A: Use the Pre-built Template (Recommended)**
    1. Switch to "⚡ Flex Query Template" method above
    2. Download the template and import it into your IBKR account (1 click)
    3. Follow the remaining steps below

    **Option B: Manual Setup**
    1. Log into [IBKR Account Management](https://www.interactivebrokers.com/sso/Login)
    2. Go to Performance & Reports → Flex Queries → "+" (create new)
    3. Select "Activity" template → Check "Open Positions"
    4. Select fields: Symbol, Description, Position, CostBasisPrice, MarkPrice, Currency, ListingExchange
    5. Save and note the **Query ID**

    **In Prosper:**
    1. Go to Account Management → Flex Query Token → Generate new token
    2. Add token as `IBKR_FLEX_TOKEN` in your `.env` or Render environment variables
    3. Enter **Query ID** above and click Save
    4. Click **Sync Now** to import
    """)

    st.divider()

    # ── Sync Section (only if both token + query ID are configured) ──────────────
    if not token_configured or not query_id_configured:
        st.info(
            "Configure both the **IBKR Flex Token** and **Flex Query ID** above to enable syncing."
        )
        st.stop()

    if not _IBKR_SYNC_AVAILABLE:
        st.warning(
            "The IBKR sync module (`core/ibkr_sync.py`) is not yet available. "
            "Once deployed, syncing will be enabled automatically."
        )
        st.stop()

    st.subheader("🔄 Sync Portfolio Now")

    # Sync mode
    col_mode, col_portfolio = st.columns(2)

    with col_mode:
        sync_mode = st.selectbox(
            "Sync Mode",
            ["Full Replace", "Smart Merge"],
            index=0,
            help=(
                "**Full Replace:** Overwrites all IBKR holdings with the latest data.\n\n"
                "**Smart Merge:** Adds new positions and updates existing ones without removing manually-added holdings."
            ),
        )

    with col_portfolio:
        portfolios_df = get_all_portfolios()
        if not portfolios_df.empty:
            pf_names = portfolios_df["name"].tolist()
            pf_ids = portfolios_df["id"].tolist()
            current_pid = get_active_portfolio_id()
            current_idx = pf_ids.index(current_pid) if current_pid in pf_ids else 0
            selected_pf = st.selectbox(
                "Target Portfolio",
                pf_names,
                index=current_idx,
                help="Which portfolio to sync IBKR holdings into.",
            )
            target_portfolio_id = pf_ids[pf_names.index(selected_pf)]
        else:
            st.caption("No portfolios found.")
            target_portfolio_id = 1

    # Last sync info
    try:
        last_sync = get_last_sync_info()
        if last_sync:
            col_ls1, col_ls2, col_ls3 = st.columns(3)
            with col_ls1:
                st.metric("Last Sync", last_sync.get("timestamp", "Never"))
            with col_ls2:
                st.metric("Holdings Synced", last_sync.get("count", 0))
            with col_ls3:
                status = last_sync.get("status", "Unknown")
                icon = "✅" if status == "Success" else "⚠️"
                st.metric("Status", f"{icon} {status}")
            st.divider()
    except Exception:
        pass  # No last sync info available

    # Sync button
    if st.button("🔄 Sync Now", type="primary", use_container_width=True):
        with st.spinner("Connecting to IBKR and fetching positions..."):
            try:
                result = sync_ibkr_portfolio(
                    flex_token=ibkr_token,
                    query_id=flex_query_id.strip(),
                    portfolio_id=target_portfolio_id,
                    mode="replace" if sync_mode == "Full Replace" else "merge",
                )

                if result.get("success"):
                    count = result.get("count", 0)
                    st.success(f"Synced **{count}** holdings from IBKR successfully!")

                    # Save sync info
                    try:
                        save_sync_info({
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "count": count,
                            "status": "Success",
                            "mode": sync_mode,
                            "portfolio_id": target_portfolio_id,
                        })
                    except Exception:
                        pass

                    # Show synced holdings
                    if result.get("holdings"):
                        with st.expander(f"Synced Holdings ({count})", expanded=True):
                            df = pd.DataFrame(result["holdings"])
                            st.dataframe(df, use_container_width=True)

                    # Invalidate enriched cache so dashboard reloads fresh data
                    for key in list(st.session_state.keys()):
                        if key.startswith("enriched_") or key in ("last_refresh_time", "extended_df"):
                            del st.session_state[key]
                else:
                    error_msg = result.get("error", "Unknown error during sync.")
                    st.error(f"Sync failed: {error_msg}")

                    try:
                        save_sync_info({
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "count": 0,
                            "status": "Failed",
                            "mode": sync_mode,
                            "error": error_msg,
                        })
                    except Exception:
                        pass

                    # Show detailed errors if available
                    if result.get("errors"):
                        with st.expander("Error Details"):
                            for err in result["errors"]:
                                st.markdown(f"- {err}")

            except Exception as e:
                st.error(f"Sync error: {str(e)}")
                try:
                    save_sync_info({
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "count": 0,
                        "status": "Error",
                        "error": str(e),
                    })
                except Exception:
                    pass
