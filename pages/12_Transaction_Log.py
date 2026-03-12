"""
Transaction Log
================
Record buy/sell trades and track realized P&L using FIFO accounting.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date

from core.database import (
    get_all_holdings, save_transaction, get_transactions,
    delete_transaction, get_realized_pnl_summary, get_total_realized_pnl,
)

st.header("📝 Transaction Log")

# ─────────────────────────────────────────
# ADD TRANSACTION FORM
# ─────────────────────────────────────────
st.subheader("➕ Add Transaction")

holdings = get_all_holdings()
ticker_list = sorted(holdings["ticker"].dropna().unique().tolist(), key=str.upper) if not holdings.empty else []

with st.form("add_transaction", clear_on_submit=True):
    col1, col2, col3 = st.columns(3)

    with col1:
        txn_type = st.selectbox("Type", ["BUY", "SELL"])
        txn_ticker = st.text_input(
            "Ticker",
            placeholder="e.g. AAPL, EMAAR.AE",
            help="Enter a stock ticker. Must match the ticker in your portfolio.",
        )

    with col2:
        txn_date = st.date_input("Date", value=date.today(), max_value=date.today())
        txn_qty = st.number_input("Quantity", min_value=0.0001, value=1.0, step=1.0, format="%.4f")

    with col3:
        txn_price = st.number_input("Price per Share", min_value=0.0001, value=100.0, step=0.01, format="%.4f")
        txn_fees = st.number_input("Fees / Commission", min_value=0.0, value=0.0, step=0.01, format="%.2f")

    col_a, col_b = st.columns(2)
    with col_a:
        txn_currency = st.selectbox("Currency", ["USD", "AED", "EUR", "GBP", "INR", "SGD", "HKD", "CHF", "AUD", "CAD", "JPY"])
    with col_b:
        txn_broker = st.text_input("Broker (optional)", placeholder="e.g. IBKR, Zerodha")

    txn_notes = st.text_input("Notes (optional)", placeholder="e.g. Earnings play, rebalance")

    submitted = st.form_submit_button("💾 Save Transaction", type="primary", use_container_width=True)

    if submitted:
        if not txn_ticker.strip():
            st.error("Please enter a ticker symbol.")
        elif txn_qty <= 0:
            st.error("Quantity must be greater than zero.")
        elif txn_price <= 0:
            st.error("Price must be greater than zero.")
        else:
            # Look up name from holdings
            name_match = holdings[holdings["ticker"].str.upper() == txn_ticker.strip().upper()]
            txn_name = name_match.iloc[0]["name"] if not name_match.empty else None

            save_transaction(
                ticker=txn_ticker.strip().upper(),
                txn_type=txn_type,
                quantity=txn_qty,
                price=txn_price,
                currency=txn_currency,
                fees=txn_fees,
                date=txn_date.isoformat(),
                broker_source=txn_broker or None,
                notes=txn_notes or None,
                name=txn_name,
            )
            st.success(f"✅ {txn_type} {txn_qty:,.4f} × {txn_ticker.upper()} @ {txn_price:,.4f} saved!")
            st.rerun()

st.divider()

# ─────────────────────────────────────────
# REALIZED P&L SUMMARY
# ─────────────────────────────────────────
st.subheader("📊 Realized P&L Summary")

pnl_summary = get_realized_pnl_summary()

if not pnl_summary.empty:
    total_realized = pnl_summary["realized_pnl"].sum()
    total_gains = pnl_summary[pnl_summary["realized_pnl"] > 0]["realized_pnl"].sum()
    total_losses = pnl_summary[pnl_summary["realized_pnl"] < 0]["realized_pnl"].sum()
    total_fees = pnl_summary["total_fees"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Net Realized P&L",
              f"${total_realized:+,.2f}",
              delta=f"{'Profit' if total_realized >= 0 else 'Loss'}")
    c2.metric("Total Gains", f"${total_gains:,.2f}")
    c3.metric("Total Losses", f"${abs(total_losses):,.2f}")
    c4.metric("Total Fees Paid", f"${total_fees:,.2f}")

    # Per-ticker breakdown
    st.markdown("**Per-Ticker Breakdown**")
    display_pnl = pnl_summary.copy()
    display_pnl = display_pnl.rename(columns={
        "ticker": "Ticker",
        "total_bought_qty": "Total Bought",
        "total_sold_qty": "Total Sold",
        "avg_buy_price": "Avg Buy Price",
        "avg_sell_price": "Avg Sell Price",
        "realized_pnl": "Realized P&L",
        "total_fees": "Fees",
    })

    # Format numbers
    for col in ["Total Bought", "Total Sold"]:
        if col in display_pnl.columns:
            display_pnl[col] = display_pnl[col].apply(lambda x: f"{x:,.2f}")
    for col in ["Avg Buy Price", "Avg Sell Price"]:
        if col in display_pnl.columns:
            display_pnl[col] = display_pnl[col].apply(lambda x: f"${x:,.4f}" if x > 0 else "—")
    if "Realized P&L" in display_pnl.columns:
        display_pnl["Realized P&L"] = display_pnl["Realized P&L"].apply(lambda x: f"${x:+,.2f}")
    if "Fees" in display_pnl.columns:
        display_pnl["Fees"] = display_pnl["Fees"].apply(lambda x: f"${x:,.2f}")

    show_cols = ["Ticker", "Total Bought", "Total Sold", "Avg Buy Price", "Avg Sell Price", "Realized P&L", "Fees"]
    show_cols = [c for c in show_cols if c in display_pnl.columns]

    from core.data_engine import clean_nan
    st.dataframe(clean_nan(display_pnl[show_cols]), use_container_width=True, hide_index=True)
else:
    st.info("No transactions recorded yet. Add buy/sell trades above to see realized P&L.")

st.divider()

# ─────────────────────────────────────────
# TRANSACTION HISTORY
# ─────────────────────────────────────────
st.subheader("📜 Transaction History")

# Filters
filter_col1, filter_col2, filter_col3 = st.columns(3)

with filter_col1:
    filter_ticker = st.text_input("Filter by Ticker", placeholder="Leave empty for all")
with filter_col2:
    filter_type = st.selectbox("Filter by Type", ["All", "BUY", "SELL"])
with filter_col3:
    filter_range = st.selectbox("Date Range", ["All Time", "Last 7 Days", "Last 30 Days", "Last 90 Days", "This Year"])

# Calculate date range
date_from = None
if filter_range == "Last 7 Days":
    date_from = (datetime.now() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
elif filter_range == "Last 30 Days":
    date_from = (datetime.now() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
elif filter_range == "Last 90 Days":
    date_from = (datetime.now() - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
elif filter_range == "This Year":
    date_from = f"{datetime.now().year}-01-01"

txns = get_transactions(
    ticker=filter_ticker.strip().upper() if filter_ticker.strip() else None,
    txn_type=filter_type if filter_type != "All" else None,
    date_from=date_from,
)

if not txns.empty:
    st.caption(f"Showing {len(txns)} transaction(s)")

    display_txns = txns.copy()
    display_txns = display_txns.rename(columns={
        "ticker": "Ticker",
        "name": "Name",
        "type": "Type",
        "quantity": "Quantity",
        "price": "Price",
        "currency": "Currency",
        "fees": "Fees",
        "date": "Date",
        "broker_source": "Broker",
        "notes": "Notes",
    })

    # Format numbers
    if "Quantity" in display_txns.columns:
        display_txns["Quantity"] = display_txns["Quantity"].apply(lambda x: f"{x:,.4f}")
    if "Price" in display_txns.columns:
        display_txns["Price"] = display_txns["Price"].apply(lambda x: f"{x:,.4f}")
    if "Fees" in display_txns.columns:
        display_txns["Fees"] = display_txns["Fees"].apply(lambda x: f"${x:,.2f}" if x > 0 else "—")

    show_cols = ["Date", "Ticker", "Name", "Type", "Quantity", "Price", "Currency", "Fees", "Broker", "Notes"]
    show_cols = [c for c in show_cols if c in display_txns.columns]

    from core.data_engine import clean_nan
    st.dataframe(clean_nan(display_txns[show_cols]), use_container_width=True, hide_index=True)

    # Export transactions
    csv_data = txns.to_csv(index=False)
    st.download_button(
        "📥 Export Transactions (CSV)",
        data=csv_data,
        file_name=f"prosper_transactions_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    # Delete transaction
    st.divider()
    with st.expander("🗑️ Delete a Transaction"):
        txn_ids = txns["id"].tolist()
        txn_labels = [
            f"#{row['id']} — {row['date']} — {row['type']} {row['quantity']:.2f} × {row['ticker']} @ {row['price']:.2f}"
            for _, row in txns.iterrows()
        ]
        selected_txn = st.selectbox("Select transaction to delete", txn_labels)
        if st.button("🗑️ Delete Selected Transaction", type="secondary"):
            idx = txn_labels.index(selected_txn)
            delete_transaction(txn_ids[idx])
            st.success("Transaction deleted!")
            st.rerun()
else:
    st.info("No transactions found matching your filters.")

st.divider()
st.caption("ℹ️ Realized P&L is calculated using FIFO (First In, First Out) accounting method.")
