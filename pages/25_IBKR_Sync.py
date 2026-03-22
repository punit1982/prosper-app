"""
Interactive Brokers Sync
========================
Sync your IBKR portfolio automatically via Flex Query.
Fetches open positions from IBKR and imports them into Prosper.
"""

import streamlit as st
from datetime import datetime
from core.settings import get_api_key, load_user_settings, save_user_settings
from core.database import get_all_portfolios, get_active_portfolio_id

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
    "Sync your IBKR portfolio automatically via Flex Query</p>",
    unsafe_allow_html=True,
)

# ── Configuration Section ────────────────────────────────────────────────────
st.subheader("🔧 Configuration")

# Check IBKR Flex Token status
ibkr_token = get_api_key("IBKR_FLEX_TOKEN")
_token_placeholder = "your_" in ibkr_token.lower() if ibkr_token else True
token_configured = bool(ibkr_token) and not _token_placeholder

if token_configured:
    st.markdown("✅ **IBKR Flex Token** — Configured")
else:
    st.markdown("❌ **IBKR Flex Token** — Not configured")
    st.caption("Add `IBKR_FLEX_TOKEN` to your `.env` file or Streamlit Cloud Secrets.")

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

# ── Setup Instructions ───────────────────────────────────────────────────────
with st.expander("📖 How to Set Up IBKR Flex Query"):
    st.markdown("""
**Step-by-step guide to create your Flex Query and token:**

1. **Log into** [IBKR Account Management](https://www.interactivebrokers.com/sso/Login) (Client Portal)
2. **Navigate to** Performance & Reports → **Flex Queries**
3. **Click "+"** to create a new **Activity Flex Query**
4. Under **Sections**, check **"Open Positions"**
5. **Select these fields:**
   - `Symbol`, `Description`, `Position`, `CostBasisPrice`, `MarkPrice`, `Currency`, `ListingExchange`
6. **Save** the query and note the **Query ID** (numeric, shown in the list)
7. Go to the **Flex Query Token** page → generate a token
8. **Add the token** as `IBKR_FLEX_TOKEN` in your `.env` file or Streamlit Cloud Secrets:

```toml
IBKR_FLEX_TOKEN = "your-flex-token-here"
```

Then enter the **Query ID** in the field above and click **Save Query ID**.
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

st.subheader("🔄 Sync Portfolio")

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
                        import pandas as pd
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
