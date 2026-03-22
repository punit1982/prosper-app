"""
IBKR Sync Orchestrator
======================
Coordinates fetching positions from IBKR Flex Query and syncing
them into Prosper's holdings database.

Supports two modes:
  - "replace": Clears existing holdings, then inserts fresh IBKR data.
  - "merge":   Upserts by ticker -- updates existing, adds new.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict

import pandas as pd

from core.ibkr_client import get_ibkr_positions, IBKRError
from core.database import (
    save_holdings,
    clear_all_holdings,
    get_all_holdings,
    update_holding,
)
from core.settings import load_user_settings, save_user_settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# Settings keys for sync metadata
# ─────────────────────────────────────────
_SYNC_INFO_KEY = "ibkr_last_sync"


def sync_ibkr_portfolio(
    token: str,
    query_id: str,
    portfolio_id: Optional[int] = None,
    mode: str = "replace",
) -> Dict:
    """
    Fetch IBKR positions and sync them into the Prosper database.

    Args:
        token:        IBKR Flex Query token.
        query_id:     IBKR Flex Query ID.
        portfolio_id: Target portfolio (None = active portfolio).
        mode:         "replace" clears holdings first; "merge" upserts by ticker.

    Returns:
        Result dict with keys: synced, added, updated, skipped, errors, timestamp.
    """
    result = {
        "synced": 0,
        "added": 0,
        "updated": 0,
        "skipped": [],
        "errors": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # --- Fetch positions from IBKR ---
    try:
        positions = get_ibkr_positions(token, query_id)
    except IBKRError as e:
        result["errors"].append(str(e))
        save_sync_info(result)
        return result
    except Exception as e:
        result["errors"].append(f"Unexpected error fetching IBKR data: {e}")
        save_sync_info(result)
        return result

    if not positions:
        result["errors"].append("No stock positions returned from IBKR Flex Query.")
        save_sync_info(result)
        return result

    # --- Build DataFrame for save_holdings ---
    df = pd.DataFrame(positions)

    if mode == "replace":
        result = _sync_replace(df, portfolio_id, result)
    elif mode == "merge":
        result = _sync_merge(df, portfolio_id, result)
    else:
        result["errors"].append(f"Unknown sync mode: '{mode}'. Use 'replace' or 'merge'.")

    result["synced"] = result["added"] + result["updated"]
    save_sync_info(result)
    logger.info("IBKR sync complete: %s", result)
    return result


def _sync_replace(df: pd.DataFrame, portfolio_id: Optional[int], result: Dict) -> Dict:
    """Replace all holdings with fresh IBKR data."""
    try:
        clear_all_holdings(portfolio_id)
        save_holdings(df, broker_source="IBKR", portfolio_id=portfolio_id)
        result["added"] = len(df)
    except Exception as e:
        result["errors"].append(f"Database error during replace sync: {e}")
    return result


def _sync_merge(df: pd.DataFrame, portfolio_id: Optional[int], result: Dict) -> Dict:
    """Upsert positions by ticker -- update existing, add new."""
    try:
        existing = get_all_holdings(portfolio_id)
    except Exception:
        existing = pd.DataFrame()

    # Build lookup of existing holdings by ticker
    existing_map: Dict[str, dict] = {}
    if not existing.empty and "ticker" in existing.columns:
        for _, row in existing.iterrows():
            ticker = str(row.get("ticker", "")).strip().upper()
            if ticker:
                existing_map[ticker] = {
                    "id": row.get("id"),
                    "quantity": row.get("quantity"),
                    "avg_cost": row.get("avg_cost"),
                    "currency": row.get("currency"),
                }

    new_rows = []
    for _, pos in df.iterrows():
        ticker = str(pos.get("ticker", "")).strip().upper()
        if not ticker:
            result["skipped"].append("(empty ticker)")
            continue

        if ticker in existing_map:
            # Update existing holding
            try:
                holding_id = existing_map[ticker]["id"]
                update_holding(
                    holding_id,
                    quantity=float(pos.get("quantity", 0)),
                    avg_cost=float(pos.get("avg_cost", 0)),
                    currency=str(pos.get("currency", "USD")),
                    broker_source="IBKR",
                )
                result["updated"] += 1
            except Exception as e:
                result["errors"].append(f"Failed to update {ticker}: {e}")
        else:
            new_rows.append(pos)

    # Insert new positions in bulk
    if new_rows:
        try:
            new_df = pd.DataFrame(new_rows)
            save_holdings(new_df, broker_source="IBKR", portfolio_id=portfolio_id)
            result["added"] = len(new_rows)
        except Exception as e:
            result["errors"].append(f"Database error inserting new holdings: {e}")

    return result


# ─────────────────────────────────────────
# Sync metadata persistence
# ─────────────────────────────────────────

def get_last_sync_info() -> Dict:
    """
    Read the last IBKR sync result from user settings.

    Returns:
        Dict with sync metadata, or empty dict if never synced.
    """
    settings = load_user_settings()
    return settings.get(_SYNC_INFO_KEY, {})


def save_sync_info(result: Dict):
    """
    Persist the sync result into user settings for display in the UI.
    """
    save_user_settings({_SYNC_INFO_KEY: result})
