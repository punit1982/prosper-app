"""
GROW Engine — batch analysis for the whole portfolio
=====================================================
Two verdicts per name (Durability 0–100 · Entry word + buy-below price).
Individual deep runs live in Equity Deep Dive.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from core.database import (
    get_all_holdings, save_prosper_analysis, get_all_prosper_analyses,
    delete_prosper_analysis, get_grow_verdict_log, get_price_cache,
)
from core.grow_engine import GROW_TIERS, GROW_VERSION, run_grow, framework_available
from core.grow_render import ENTRY_COLORS, durability_color
from core.data_engine import get_ticker_info_batch

from core.ui_components import page_header
page_header('GROW Engine', 'Two verdicts per name: durability and entry')
st.caption(
    f"**{GROW_VERSION}** — two questions, answered separately: *is this worth owning* (Durability, no price in it) "
    f"and *is it worth buying today* (Entry, from expected return vs the return the risk demands). "
    f"For one stock in depth, use **Equity Deep Dive**."
)

if not framework_available():
    st.error("GROW framework files are missing from the app's `grow/` folder.")
    st.stop()

holdings = get_all_holdings()
portfolio_tickers = sorted(holdings["ticker"].dropna().unique().tolist()) if not holdings.empty else []
if not portfolio_tickers:
    st.info("Upload holdings via **Upload Portal** to run GROW on your portfolio.")
    st.stop()

# ─────────────────────────────────────────
# CONTROLS
# ─────────────────────────────────────────
c1, c2, c3 = st.columns([2, 2, 1])
with c1:
    tier = st.selectbox(
        "Run type",
        list(GROW_TIERS.keys()),
        format_func=lambda t: f"{GROW_TIERS[t]['label']} — {GROW_TIERS[t]['description']}",
        index=0,
        key="grow_batch_tier",
    )
with c2:
    skip_recent = st.checkbox("Skip names with a GROW run in the last 7 days", value=True, key="grow_skip_recent")
    est = len(portfolio_tickers) * GROW_TIERS[tier]["est_cost"]
    st.caption(f"**{len(portfolio_tickers)} names** · estimated cost ≈ **${est:,.2f}** at this run type")
with c3:
    st.markdown("<br>", unsafe_allow_html=True)
    run_btn = st.button(f"Run GROW on all ({len(portfolio_tickers)})", type="primary", use_container_width=True, key="grow_batch_btn")

if tier != "screen":
    st.warning("Standard/Full runs retrieve filings via web search for every name — slow (2–5 min each) and they cost real API credits. "
               "For a whole portfolio, run **Screen** first and go deep only on the names that matter.")

# ─────────────────────────────────────────
# RUN
# ─────────────────────────────────────────
if run_btn:
    existing = get_all_prosper_analyses()
    skip = set()
    if skip_recent and not existing.empty and "framework" in existing.columns:
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        rank = {"full": 3, "standard": 2, "screen": 1}
        for _, r in existing.iterrows():
            if str(r.get("framework") or "").startswith("GROW") and str(r.get("analysis_date", "")) >= cutoff:
                if rank.get(str(r.get("model_used")), 0) >= rank.get(tier, 1):
                    skip.add(r["ticker"])
    todo = [t for t in portfolio_tickers if t not in skip]
    if skip:
        st.info(f"Skipping {len(skip)} names with a recent GROW run of this depth or deeper.")
    if not todo:
        st.success("Every name already has a recent GROW run. Nothing to do.")
    else:
        progress = st.progress(0, text="Fetching market data…")
        info_map = get_ticker_info_batch(todo)
        price_map = get_price_cache(todo)
        done, errors = {}, []
        for i, t in enumerate(todo):
            progress.progress((i + 1) / len(todo), text=f"GROW {t} ({i+1}/{len(todo)})…")
            res, err = run_grow(t, tier=tier, info=info_map.get(t, {}), price_quote=price_map.get(t))
            if res:
                save_prosper_analysis(t, res)
                done[t] = res
            else:
                errors.append(f"{t}: {err}")
        progress.empty()
        total_cost = sum(r.get("cost_estimate", 0) or 0 for r in done.values())
        st.success(f"GROW complete: {len(done)}/{len(todo)} rated · {len(skip)} skipped · cost USD {total_cost:.2f}")
        if errors:
            with st.expander(f"Not rated ({len(errors)}) — rule 21: listed, with the reason"):
                for e in errors:
                    st.caption(e)
        st.rerun()

# ─────────────────────────────────────────
# RATING LIST — rule 21: one row per rated name, Durability + Entry + price + date
# ─────────────────────────────────────────
st.divider()
all_df = get_all_prosper_analyses()
if not all_df.empty and "framework" in all_df.columns:
    grow_df = all_df[all_df["framework"].fillna("").str.startswith("GROW")]
    legacy_df = all_df[~all_df["framework"].fillna("").str.startswith("GROW")]
else:
    grow_df, legacy_df = pd.DataFrame(), all_df
_pf = set(portfolio_tickers)
rated_in_pf = len(set(grow_df["ticker"]) & _pf) if not grow_df.empty else 0
legacy_in_pf = len((set(legacy_df["ticker"]) & _pf) - (set(grow_df["ticker"]) if not grow_df.empty else set())) if not legacy_df.empty else 0

st.subheader("Rated names")
st.caption(f"{rated_in_pf} of {len(portfolio_tickers)} portfolio names rated under GROW · "
           f"{len(portfolio_tickers) - rated_in_pf} not yet rated"
           + (f" · {legacy_in_pf} carry only a superseded PROSPER verdict (rule 22 — unrated until re-run)" if legacy_in_pf else ""))

if grow_df.empty:
    st.info("No GROW runs yet. Choose **Screen** above and click Run to rate the whole portfolio cheaply.")
else:
    show = pd.DataFrame({
        "Ticker": grow_df["ticker"],
        "Durability": pd.to_numeric(grow_df["durability"], errors="coerce"),
        "Entry": grow_df["entry_verdict"].fillna(grow_df["rating"]),
        "Buy below": pd.to_numeric(grow_df["buy_below"], errors="coerce"),
        "Price at run": pd.to_numeric(grow_df["price_at_run"], errors="coerce"),
        "Exp. return / yr": pd.to_numeric(grow_df["cagr_spot"], errors="coerce") * 100,
        "Bar": pd.to_numeric(grow_df["required_return"], errors="coerce") * 100,
        "Confidence": grow_df["confidence"].fillna(""),
        "Run": grow_df["model_used"].fillna(""),
        "Date": grow_df["analysis_date"],
    }).sort_values("Durability", ascending=False).reset_index(drop=True)

    def _c_entry(v):
        c = ENTRY_COLORS.get(str(v).strip(), "")
        return f"color:{c};font-weight:600" if c else ""

    def _c_dur(v):
        return f"color:{durability_color(v)};font-weight:600"

    styled = (show.style
              .map(_c_entry, subset=["Entry"])
              .map(_c_dur, subset=["Durability"])
              .format({"Durability": "{:.0f}", "Buy below": "{:,.2f}", "Price at run": "{:,.2f}",
                       "Exp. return / yr": "{:+.1f}%", "Bar": "{:.1f}%"}, na_rep="—"))
    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.caption("Screen runs are provisional (no filings retrieved). Durability answers *own or not*; Entry answers *buy at this price or not* — "
               "a name that got expensive is one you stop buying, never a reason to sell (rule 18).")

    with st.expander("Verdict log (calibration record, append-only)", expanded=False):
        log = get_grow_verdict_log(limit=300)
        if log.empty:
            st.caption("No entries yet.")
        else:
            cols = [c for c in ("run_date", "ticker", "tier", "durability", "entry_verdict", "price_at_run", "buy_below", "cagr_spot", "required_return", "confidence") if c in log.columns]
            st.dataframe(log[cols], use_container_width=True, hide_index=True)

    if st.button("Clear all GROW results", type="secondary", key="grow_clear_all"):
        for t in grow_df["ticker"].tolist():
            delete_prosper_analysis(t)
        st.rerun()
