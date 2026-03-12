"""
Export Reports
==============
Download portfolio data as CSV or Excel files.
"""

import io
import streamlit as st
import pandas as pd
from datetime import datetime

from core.database import get_all_holdings, get_transactions, get_realized_pnl_summary
from core.settings import SETTINGS

st.header("📥 Export Reports")

holdings = get_all_holdings()
if holdings.empty:
    st.info("Add holdings via **Upload Portal** to export portfolio data.")
    st.stop()

base_currency = SETTINGS.get("base_currency", "USD")
cache_key = f"enriched_{base_currency}"

st.divider()

# ─────────────────────────────────────────
# PORTFOLIO EXPORT
# ─────────────────────────────────────────
st.subheader("📊 Portfolio Holdings")

enriched = st.session_state.get(cache_key)

if enriched is not None and not enriched.empty:
    # Build clean export DataFrame
    export_df = enriched.copy()

    # Select key columns for export
    export_cols = {
        "ticker": "Ticker",
        "name": "Name",
        "quantity": "Quantity",
        "avg_cost": "Avg Cost",
        "currency": "Currency",
        "current_price": "Current Price",
        "market_value": f"Market Value ({base_currency})",
        "cost_basis": f"Cost Basis ({base_currency})",
        "unrealized_pnl": f"Unrealized P&L ({base_currency})",
        "unrealized_pnl_pct": "Unrealized P&L %",
        "day_gain": f"Day Gain ({base_currency})",
        "change_pct": "Day Change %",
        "broker_source": "Broker",
    }

    available_cols = {k: v for k, v in export_cols.items() if k in export_df.columns}
    clean_export = export_df[list(available_cols.keys())].rename(columns=available_cols)

    st.caption(f"{len(clean_export)} holdings · Base currency: {base_currency}")
    st.dataframe(clean_export.head(5), use_container_width=True, hide_index=True)
    st.caption("Preview of first 5 rows. Full data included in download.")

    col1, col2 = st.columns(2)

    with col1:
        csv_data = clean_export.to_csv(index=False)
        st.download_button(
            "📥 Download as CSV",
            data=csv_data,
            file_name=f"prosper_portfolio_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
            type="primary",
        )

    with col2:
        try:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                clean_export.to_excel(writer, sheet_name="Portfolio", index=False)
            st.download_button(
                "📥 Download as Excel",
                data=buffer.getvalue(),
                file_name=f"prosper_portfolio_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except ImportError:
            st.warning("Install `openpyxl` for Excel export: `pip install openpyxl`")

else:
    st.warning("Portfolio prices not loaded yet. Go to **Portfolio Dashboard** first to load live prices, then come back here to export.")

st.divider()

# ─────────────────────────────────────────
# TRANSACTION EXPORT
# ─────────────────────────────────────────
st.subheader("📝 Transaction History")

txns = get_transactions()

if not txns.empty:
    st.caption(f"{len(txns)} transaction(s) recorded")

    txn_export = txns.rename(columns={
        "ticker": "Ticker", "name": "Name", "type": "Type",
        "quantity": "Quantity", "price": "Price", "currency": "Currency",
        "fees": "Fees", "date": "Date", "broker_source": "Broker", "notes": "Notes",
    })
    show_cols = ["Date", "Ticker", "Name", "Type", "Quantity", "Price", "Currency", "Fees", "Broker", "Notes"]
    show_cols = [c for c in show_cols if c in txn_export.columns]
    txn_export = txn_export[show_cols]

    csv_txn = txn_export.to_csv(index=False)
    st.download_button(
        "📥 Download Transactions (CSV)",
        data=csv_txn,
        file_name=f"prosper_transactions_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True,
    )
else:
    st.info("No transactions recorded yet. Go to **Transaction Log** to add buy/sell trades.")

st.divider()

# ─────────────────────────────────────────
# REALIZED P&L EXPORT
# ─────────────────────────────────────────
st.subheader("💰 Realized P&L Summary")

pnl = get_realized_pnl_summary()

if not pnl.empty:
    total_realized = pnl["realized_pnl"].sum()
    st.caption(f"Net Realized P&L: **${total_realized:+,.2f}**")

    pnl_export = pnl.rename(columns={
        "ticker": "Ticker",
        "total_bought_qty": "Total Bought",
        "total_sold_qty": "Total Sold",
        "avg_buy_price": "Avg Buy Price",
        "avg_sell_price": "Avg Sell Price",
        "realized_pnl": "Realized P&L",
        "total_fees": "Total Fees",
    })
    show_cols = ["Ticker", "Total Bought", "Total Sold", "Avg Buy Price", "Avg Sell Price", "Realized P&L", "Total Fees"]
    show_cols = [c for c in show_cols if c in pnl_export.columns]

    csv_pnl = pnl_export[show_cols].to_csv(index=False)
    st.download_button(
        "📥 Download Realized P&L (CSV)",
        data=csv_pnl,
        file_name=f"prosper_realized_pnl_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True,
    )
else:
    st.info("No realized P&L data. Add sell transactions to see gains/losses.")

st.divider()

# ─────────────────────────────────────────
# COMBINED REPORT
# ─────────────────────────────────────────
st.subheader("📋 Combined Report (Excel)")
st.caption("Download a single Excel file with all data in separate sheets.")

if enriched is not None and not enriched.empty:
    try:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            # Sheet 1: Portfolio
            available_cols = {k: v for k, v in export_cols.items() if k in enriched.columns}
            enriched[list(available_cols.keys())].rename(columns=available_cols).to_excel(
                writer, sheet_name="Portfolio", index=False
            )
            # Sheet 2: Transactions
            if not txns.empty:
                txns.to_excel(writer, sheet_name="Transactions", index=False)
            # Sheet 3: Realized P&L
            if not pnl.empty:
                pnl.to_excel(writer, sheet_name="Realized P&L", index=False)
            # Sheet 4: Summary
            summary_data = {
                "Metric": [
                    "Total Holdings",
                    "Base Currency",
                    "Report Date",
                    "Total Portfolio Value",
                    "Total Cost Basis",
                    "Unrealized P&L",
                    "Realized P&L",
                    "Total Transactions",
                ],
                "Value": [
                    len(enriched),
                    base_currency,
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                    f"{enriched['market_value'].sum():,.2f}" if "market_value" in enriched.columns else "N/A",
                    f"{enriched['cost_basis'].sum():,.2f}" if "cost_basis" in enriched.columns else "N/A",
                    f"{enriched['unrealized_pnl'].sum():,.2f}" if "unrealized_pnl" in enriched.columns else "N/A",
                    f"{pnl['realized_pnl'].sum():,.2f}" if not pnl.empty else "0.00",
                    len(txns),
                ],
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)

        st.download_button(
            "📥 Download Combined Report (Excel)",
            data=buffer.getvalue(),
            file_name=f"prosper_report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary",
        )
    except ImportError:
        st.warning("Install `openpyxl` for Excel export: `pip install openpyxl`")
else:
    st.warning("Load portfolio prices on the Dashboard first to generate a combined report.")

st.divider()
st.caption("ℹ️ All exports use your current base currency and latest prices.")
