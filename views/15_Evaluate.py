"""
Evaluate — PROSPER v5.13.1 across the portfolio
===============================================
One card per name: a 0–100 score, the call, the printed reward:risk ratio and the buy-below
line. Individual deep runs live on Security (Equity Deep Dive).

Batch runs follow the framework's own budget (§A): one regime scan for the batch, then ≤6
searches a name. Position-blind (P1): holdings pick WHICH names to run, and nothing about a
holding is passed to the engine.
"""

import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

from core.database import (
    get_all_holdings, save_prosper_analysis, get_all_prosper_analyses, get_current_analyses,
    get_prosper_analysis, delete_prosper_analysis, get_verdict_log, get_price_cache,
)
from core.framework_version import FRAMEWORK_VERSION, is_current
from core.prosper_engine import (
    PROSPER_TIERS, BATCH_MAX_SEARCHES, run_prosper, framework_available, cards_file,
)
from core.prosper_render import call_color, score_color
from core.data_engine import get_ticker_info_batch

from core.ui_components import page_header
page_header('Evaluate', 'One card per name: score, call, and the price that makes it a buy')
with st.popover(f"How {FRAMEWORK_VERSION} scores a name ⓘ", use_container_width=False):
    st.markdown(
        f"**{FRAMEWORK_VERSION}** scores five things — megatrend fit, moat, forward "
        f"opportunity, management & capital, and asymmetry — into one score out of 100.\n\n"
        f"**The call** comes from the score, then the hard rules: a buy needs at least **$2 of "
        f"upside for every $1 of downside**, printed as a formula; accounting problems force a "
        f"sell; conduct problems are priced in and block adding.\n\n"
        f"**Buy below** is the price where that 2-to-1 is reached: (bull + 2 × bear) ÷ 3.\n\n"
        f"The rating never looks at what you own. For one name in depth, use **Security**."
    )

if not framework_available():
    st.error("The PROSPER framework file is missing from the app's `prosper_framework/` folder.")
    st.stop()

holdings = get_all_holdings()
portfolio_tickers = sorted(holdings["ticker"].dropna().unique().tolist()) if not holdings.empty else []
if not portfolio_tickers:
    st.info("Upload holdings via **Add holdings** to run PROSPER on your portfolio.")
    st.stop()

# ─────────────────────────────────────────
# CONTROLS
# ─────────────────────────────────────────
_batch_tiers = ["screen", "delta", "standard"]      # "full" (Opus + memo) is a single-name run
c1, c2, c3 = st.columns([2, 2, 1])
with c1:
    tier = st.selectbox(
        "Run type",
        _batch_tiers,
        format_func=lambda t: f"{PROSPER_TIERS[t]['label']} — {PROSPER_TIERS[t]['description']}",
        index=0,
        key="prosper_batch_tier",
    )
with c2:
    skip_recent = st.checkbox("Skip names with a PROSPER card in the last 7 days", value=True, key="prosper_skip_recent")
    est = len(portfolio_tickers) * PROSPER_TIERS[tier]["est_cost"]
    st.caption(f"**{len(portfolio_tickers)} names** · estimated cost ≈ **${est:,.2f}** at this run type")
with c3:
    st.markdown("<br>", unsafe_allow_html=True)
    run_btn = st.button(f"Run PROSPER on all ({len(portfolio_tickers)})", type="primary",
                        use_container_width=True, key="prosper_batch_btn")

if tier != "screen":
    st.warning(f"Web-search runs cost real API credits and take minutes a name. In a batch each name gets "
               f"≤{BATCH_MAX_SEARCHES} searches and the market-mood scan is done once (§A). "
               "Delta re-runs a name against its last card; names without one get a first run.")

# ─────────────────────────────────────────
# RUN
# ─────────────────────────────────────────
if run_btn:
    existing = get_current_analyses()
    skip = set()
    if skip_recent and not existing.empty:
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        rank = {"full": 4, "standard": 3, "cowork": 3, "delta": 2, "screen": 1}
        for _, r in existing.iterrows():
            if str(r.get("analysis_date", "")) >= cutoff and rank.get(str(r.get("model_used")), 0) >= rank.get(tier, 1):
                skip.add(r["ticker"])
    todo = [t for t in portfolio_tickers if t not in skip]
    if skip:
        st.info(f"Skipping {len(skip)} names with a recent PROSPER card of this depth or deeper.")
    if not todo:
        st.success("Every name already has a recent PROSPER card. Nothing to do.")
    else:
        progress = st.progress(0, text="Fetching market data…")
        info_map = get_ticker_info_batch(todo)
        price_map = get_price_cache(todo)
        done, errors, regime = {}, [], None
        for i, t in enumerate(todo):
            progress.progress((i + 1) / len(todo), text=f"PROSPER {t} ({i+1}/{len(todo)})…")
            prior = get_prosper_analysis(t)
            res, err = run_prosper(t, tier=tier, info=info_map.get(t, {}), price_quote=price_map.get(t),
                                   prior=prior, max_searches=BATCH_MAX_SEARCHES, regime_hint=regime)
            if res:
                save_prosper_analysis(t, res)
                done[t] = res
                if regime is None and tier != "screen" and res.get("regime_state"):
                    regime = (res.get("full_response") or {}).get("prosper_json", {}).get("regime")
            else:
                errors.append(f"{t}: {err}")
        progress.empty()
        total_cost = sum(r.get("cost_estimate", 0) or 0 for r in done.values())
        st.success(f"PROSPER complete: {len(done)}/{len(todo)} rated · {len(skip)} skipped · cost USD {total_cost:.2f}")
        if errors:
            with st.expander(f"Not rated ({len(errors)}) — each with the reason"):
                for e in errors:
                    st.caption(e)
        st.rerun()

# ─────────────────────────────────────────
# RATED NAMES — one row per name: score · call · ratio · buy-below · price · date
# ─────────────────────────────────────────
st.divider()
all_df = get_all_prosper_analyses()
cur_df = get_current_analyses()
_pf = set(portfolio_tickers)
rated = set(cur_df["ticker"]) if not cur_df.empty else set()
retired = set()
if not all_df.empty and "framework" in all_df.columns:
    retired = set(all_df[~all_df["framework"].apply(is_current)]["ticker"]) - rated
rated_in_pf = len(rated & _pf)
retired_in_pf = len(retired & _pf)

st.subheader("Rated names")
st.caption(f"{rated_in_pf} of {len(portfolio_tickers)} portfolio names carry a {FRAMEWORK_VERSION} card · "
           f"{len(portfolio_tickers) - rated_in_pf} not yet rated"
           + (f" · {retired_in_pf} carry only a superseded GROW/PROSPER-v3 verdict (context only — unrated until re-run)"
              if retired_in_pf else ""))

if cur_df.empty:
    st.info("No PROSPER cards yet. Choose **Screen** above and click Run to rate the whole portfolio cheaply.")
else:
    def _num(col):
        return pd.to_numeric(cur_df[col], errors="coerce") if col in cur_df.columns else pd.Series([None] * len(cur_df))

    show = pd.DataFrame({
        "Ticker": cur_df["ticker"].values,
        "Score": _num("q_score").fillna(_num("score")).values,
        "Call": cur_df["entry_verdict"].fillna(cur_df["rating"]).values,
        "Reward:risk": _num("reward_risk").values,
        "Buy below": _num("buy_below").values,
        "Price at run": _num("price_at_run").values,
        "3-yr return (prob.-wtd)": (_num("prob_weighted_return") * 100).values,
        "Mood": cur_df["regime_state"].fillna("").values if "regime_state" in cur_df.columns else "",
        "Confidence": cur_df["confidence"].fillna("").values,
        "Run": cur_df["model_used"].fillna("").values,
        "Date": cur_df["analysis_date"].values,
        "Valid until": cur_df["valid_until"].fillna("").values if "valid_until" in cur_df.columns else "",
    }).sort_values("Score", ascending=False).reset_index(drop=True)
    show.loc[show["Reward:risk"] >= 999, "Reward:risk"] = float("inf")

    styled = (show.style
              .map(lambda v: f"color:{call_color(v)};font-weight:600" if str(v).strip() else "", subset=["Call"])
              .map(lambda v: f"color:{score_color(v)};font-weight:600", subset=["Score"])
              .format({"Score": "{:.1f}", "Reward:risk": "{:.2f}×", "Buy below": "{:,.2f}",
                       "Price at run": "{:,.2f}", "3-yr return (prob.-wtd)": "{:+.0f}%"}, na_rep="—"))
    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.caption("Screen runs are provisional (no live searches). A buy needs reward:risk of 2× or better; "
               "Buy below is where that happens. The call is recomputed in Python from the card's own "
               "inputs — the model's words never override the arithmetic.")

    # P7 — the saved cards file: master table, regime, anchor log and every card
    try:
        rows = []
        for t in show["Ticker"].tolist():
            a = get_prosper_analysis(t)
            if a and is_current(a.get("framework")):
                full = a.get("full_response") or {}
                rows.append({**full, "card_md": a.get("card_md"), "ticker": t,
                             "full_response": full})
        if rows:
            fname, md = cards_file(rows, label="BOOK")
            st.download_button(f"Download cards file ({len(rows)} cards)", data=md, file_name=fname,
                               mime="text/markdown", key="prosper_cards_file")
    except Exception:
        pass

    with st.expander("Verdict log (calibration record, append-only)", expanded=False):
        log = get_verdict_log(limit=300)
        if log.empty:
            st.caption("No entries yet.")
        else:
            cols = [c for c in ("run_date", "ticker", "framework", "tier", "q_score", "entry_verdict",
                                "price_at_run", "reward_risk", "reentry_price", "buy_below",
                                "regime_state", "confidence") if c in log.columns]
            st.dataframe(log[cols], use_container_width=True, hide_index=True)

    if st.button("Clear all PROSPER cards", type="secondary", key="prosper_clear_all"):
        for t in cur_df["ticker"].tolist():
            delete_prosper_analysis(t)
        st.rerun()
