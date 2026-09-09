"""
HARVEST — the Options Desk
==========================
Today's slate: at most five specific, tradeable orders, each with the reasoning, the exit, and
the reason it survived the doctrine.

This page does NO network work. Everything it shows was computed overnight by
scripts/options_scan.py and stored — a scan moves ~150MB against a rate-limited CDN and takes
6-12 minutes, which would be a catastrophic page load. Rendering is a handful of indexed SELECTs,
so the page is fast even on a cold Render instance.

Design rules followed here (from the mobile system, each learned the hard way):
  * stat_grid() not st.columns() — columns stack below ~640px and turn a 3-KPI row into three
    70px rows.
  * no st.dataframe for anything the user must read on a phone — it is a fixed-height widget with
    its own scrollbars, a scroll trap inside a scrolling page.
  * the dollar figure leads. This is read at 6am on a phone; the credit is what decides whether
    the reader cares, not the annualised percentage.
"""

import json
import os
from datetime import datetime, date

import pandas as pd
import streamlit as st

from core.settings import SETTINGS
from core.ui_components import page_header, stat_grid, status_chip, hero_metric, fmt_compact
from core.ui_errors import empty_state, unexpected
from core.database import (
    get_harvest_slate, get_open_harvest_positions, get_harvest_recommendations,
    get_chain_snapshots,
)

# ─────────────────────────────────────────────────────────────────────────────
# Styling — scoped to this page's own classes so nothing leaks into other pages
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.hv-card{border:1px solid rgba(128,128,128,0.22);border-left:3px solid #0f7a52;
         padding:11px 12px;margin-bottom:9px;border-radius:3px;}
.hv-card.debit{border-left-color:#b3261e;}
.hv-card.hedge{border-left-color:#1e3a8a;}
.hv-card.blocked{border-left-color:#9a5b06;opacity:0.72;}
.hv-r1{display:flex;justify-content:space-between;align-items:baseline;gap:10px;}
.hv-sym{font-weight:700;font-size:1.02rem;letter-spacing:-0.01em;}
.hv-amt{font-weight:700;font-size:1.02rem;font-variant-numeric:tabular-nums;white-space:nowrap;}
.hv-amt.pos{color:#0f7a52;} .hv-amt.neg{color:#b3261e;}
.hv-r2{display:flex;justify-content:space-between;gap:10px;font-size:0.72rem;
       opacity:0.62;margin-top:2px;font-variant-numeric:tabular-nums;}
.hv-why{font-size:0.8rem;line-height:1.45;margin-top:7px;color:inherit;opacity:0.92;}
.hv-warn{font-size:0.72rem;color:#9a5b06;margin-top:5px;line-height:1.4;}
.hv-order{font-family:ui-monospace,'IBM Plex Mono',Menlo,monospace;font-size:0.76rem;
          background:rgba(128,128,128,0.10);padding:7px 9px;border-radius:3px;margin-top:7px;
          overflow-x:auto;white-space:nowrap;}
.hv-kv{font-size:0.76rem;line-height:1.75;}
.hv-kv b{display:inline-block;min-width:11.5ch;opacity:0.6;font-weight:500;}
.hv-rej{font-size:0.76rem;line-height:1.5;padding:5px 0;
        border-bottom:1px solid rgba(128,128,128,0.14);}
.hv-rej .t{font-weight:650;font-family:ui-monospace,monospace;}
.hv-note{font-size:0.82rem;opacity:0.75;line-height:1.5;}
</style>
""", unsafe_allow_html=True)


def _money(v, dp=0):
    try:
        return f"${float(v):,.{dp}f}"
    except (TypeError, ValueError):
        return "—"


# ─────────────────────────────────────────────────────────────────────────────
# Load — DB only
# ─────────────────────────────────────────────────────────────────────────────
try:
    slate = get_harvest_slate()
except Exception as e:
    unexpected("the options desk", e)
    st.stop()

if not slate:
    page_header("Options", "HARVEST v1.0 — the doctrine this desk enforces")
    empty_state(
        "options scan",
        action=("The nightly scan hasn't run yet. It fetches the chains, measures implied "
                "against realised volatility, and builds the day's slate. Run "
                "`python scripts/options_scan.py` or wait for tonight's scheduled run."),
    )
    st.caption("The scan is deliberately a nightly job, not a page load — it moves ~150MB against "
               "a rate-limited data source and takes several minutes.")
    st.stop()

def _rebuild_slate():
    """Re-run layers 2-4 against the chains already stored — no network, one Claude call.

    Deliberately NOT a full scan. A scan fetches ~115 chains at 2-20s each against a
    rate-limited CDN; the last full run took 164 minutes. That can never be a button.

    This is the thing that actually needs re-running by hand: the slate is built with the
    collateral ledger as it stood at scan time, so changing harvest_collateral_usd in
    Settings leaves yesterday's slate with every short put still blocked by R4 until the
    next overnight run. ~30 seconds and about $0.015.
    """
    from datetime import date as _date
    from core import options_engine as _oe
    from core import options_data as _od
    from core.database import (
        get_chain_snapshots as _gcs, get_all_holdings as _gah,
        get_all_prosper_analyses as _gapa, get_open_harvest_positions as _gohp,
        save_harvest_slate as _shs, log_harvest_recommendations as _lhr,
    )

    snaps = _gcs()
    if not snaps:
        st.error("No stored option chains to rebuild from. The overnight scan has to run first.")
        return
    scan_date = next(iter(snaps.values())).get("scan_date") or _date.today().isoformat()

    metrics, clean = {}, {}
    for t, sn in snaps.items():
        metrics[t] = sn.get("_metrics") or {}
        clean[t] = {"ticker": t, "spot": sn.get("spot"), "iv30": sn.get("iv30"),
                    "quote_timestamp": sn.get("quote_timestamp"),
                    "contracts": sn.get("contracts") or []}

    positions = {}
    try:
        h = _gah()
        if h is not None and not h.empty:
            for _, r in h.iterrows():
                tk = str(r.get("ticker") or "").strip().upper()
                if not tk or "." in tk or not tk.isalpha() or len(tk) > 5:
                    continue
                if str(r.get("currency") or "USD").upper() != "USD":
                    continue
                try:
                    q = float(r.get("quantity") or 0)
                except (TypeError, ValueError):
                    continue
                if q > 0:
                    positions[tk] = {"shares": positions.get(tk, {}).get("shares", 0) + q}
    except Exception:
        pass

    grow_map = {}
    try:
        g = _gapa()
        if g is not None and not g.empty:
            grow_map = {str(r["ticker"]).upper(): dict(r) for _, r in g.iterrows()}
    except Exception:
        pass

    open_u, committed = set(), 0.0
    try:
        op = _gohp()
        if op is not None and not op.empty:
            open_u = {str(t).upper() for t in op["ticker"].tolist()}
            committed = float(op["collateral"].fillna(0).sum())
    except Exception:
        pass

    _oe.configure()
    collateral = float(SETTINGS.get("harvest_collateral_usd", 0) or 0)
    earnings = _od.fetch_earnings_calendar(os.getenv("FINNHUB_API_KEY", ""))

    payload = _oe.build_slate(
        clean, metrics, positions, grow_map, earnings,
        collateral_available=collateral, collateral_committed=committed,
        open_underlyings=open_u, as_of=scan_date,
    )
    if payload.get("error"):
        st.error(f"Rebuild failed: {payload['error']}")
        return
    u = payload.get("usage") or {}
    _shs(scan_date, payload, market_note=payload.get("market_note") or "",
         n_selected=len(payload.get("tickets") or []),
         n_candidates=payload.get("candidates_considered") or 0,
         model_id=u.get("model_id") or "", cost_estimate=u.get("cost") or 0.0)
    _lhr(scan_date, payload.get("tickets") or [])
    st.success(f"Rebuilt: {len(payload.get('tickets') or [])} idea(s) from "
               f"{payload.get('candidates_considered') or 0} candidates "
               f"(${u.get('cost') or 0:.4f}).")
    st.rerun()


meta = slate.get("_meta") or {}
tickets = slate.get("tickets") or []
blocked = slate.get("blocked") or []
engine_rejections = slate.get("engine_rejections") or []
model_rejections = slate.get("rejected") or []
slate_date = meta.get("slate_date") or slate.get("as_of") or ""

try:
    _age_days = (date.today() - datetime.strptime(slate_date, "%Y-%m-%d").date()).days
except (ValueError, TypeError):
    _age_days = None

page_header(
    "Options Desk",
    f"{slate_date} · {len(tickets)} idea{'s' if len(tickets) != 1 else ''} · "
    f"{meta.get('n_candidates') or 0} candidates screened",
)

if _age_days is not None and _age_days >= 1:
    st.warning(
        f"This slate is {_age_days} day{'s' if _age_days > 1 else ''} old. Prices move; "
        f"re-run the scan before acting on any of it."
    )

# ─────────────────────────────────────────────────────────────────────────────
# Headline
# ─────────────────────────────────────────────────────────────────────────────
net_credit = sum((t.get("net_premium") or 0) for t in tickets if (t.get("net_premium") or 0) > 0)
net_debit = sum(abs(t.get("net_premium") or 0) for t in tickets if (t.get("net_premium") or 0) < 0)
collateral_used = sum((t.get("collateral") or 0) for t in tickets)
collateral_avail = slate.get("collateral_available") or 0

hero_metric(
    "Premium available today",
    _money(net_credit),
    delta=(f"less {_money(net_debit)} spent on protection" if net_debit else ""),
    delta_value=(-1 if net_debit else 0),
    sub=f"across {len(tickets)} order{'s' if len(tickets) != 1 else ''}, "
        f"{_money(collateral_used)} of collateral committed",
)

stat_grid([
    ("Collateral free", _money(max(0, collateral_avail - collateral_used))),
    ("Ledger", _money(collateral_avail)),
    ("Screened", str(meta.get("n_candidates") or 0)),
], columns=3)

if slate.get("market_note"):
    st.markdown(f"<div class='hv-note'>{slate['market_note']}</div>", unsafe_allow_html=True)

if slate.get("error"):
    st.error(f"The engine reported: {slate['error']}")

_cfg_collateral = float(SETTINGS.get("harvest_collateral_usd", 0) or 0)
if abs(_cfg_collateral - (slate.get("collateral_available") or 0)) > 1:
    st.warning(
        f"This slate was built against a collateral ledger of "
        f"{_money(slate.get('collateral_available') or 0)}, but Settings now says "
        f"{_money(_cfg_collateral)}. Short puts were sized — or blocked — against the old "
        f"figure. Rebuild to apply the new one."
    )

if st.button("Rebuild today's slate", use_container_width=True,
             help="Re-scores the chains already stored and re-picks the slate. No new market "
                  "data is fetched — that is the overnight job — so this takes ~30 seconds "
                  "and about $0.015."):
    with st.spinner("Re-scoring stored chains and re-picking…"):
        _rebuild_slate()

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# The slate
# ─────────────────────────────────────────────────────────────────────────────
if not tickets:
    st.info(slate.get("slate_size_reason")
            or "Nothing cleared the doctrine today. That is a valid answer — see below for why.")
else:
    for t in tickets:
        prem = t.get("net_premium") or 0
        css = "hv-card" + (" debit" if prem < 0 else "")
        if t.get("strategy") == "protective_put":
            css = "hv-card hedge"
        amt_cls = "pos" if prem >= 0 else "neg"
        strat_label = (t.get("strategy") or "").replace("_", " ")

        st.markdown(
            f"<div class='{css}'>"
            f"<div class='hv-r1'><span class='hv-sym'>{t.get('ticker')}</span>"
            f"<span class='hv-amt {amt_cls}'>{'+' if prem >= 0 else '−'}{_money(abs(prem))}</span></div>"
            f"<div class='hv-r2'><span>{strat_label} · {t.get('contracts')}× {t.get('strike'):g}"
            f"{t.get('right')}</span><span>Δ{abs(t.get('delta') or 0):.2f} · {t.get('dte')}d · "
            f"{(t.get('annualised_pct') or 0):.0f}% ann</span></div>"
            f"<div class='hv-why'>{t.get('why') or ''}</div>"
            + "".join(f"<div class='hv-warn'>⚠ {w}</div>" for w in (t.get("warnings") or []))
            + "</div>",
            unsafe_allow_html=True,
        )

        with st.expander(f"Ticket — {t.get('ticker')} {strat_label}", expanded=False):
            st.markdown(f"<div class='hv-order'>{t.get('order_description')}</div>",
                        unsafe_allow_html=True)
            rows = [
                ("Limit", f"{_money(t.get('limit_price'), 2)} · "
                          f"{'GTC' if (t.get('dte') or 0) > 7 else 'day'}"),
                ("Market", f"bid {_money(t.get('bid'), 2)} / ask {_money(t.get('ask'), 2)} · "
                           f"spread {(t.get('spread_pct') or 0):.1f}% · OI {t.get('open_interest'):,}"),
                ("Net", f"{_money(t.get('net_premium'), 2)} after {_money(t.get('commission'), 2)} commission"),
                ("Breakeven", _money(t.get("breakeven"), 2)),
                ("Collateral", t.get("collateral_note") or "—"),
                ("If assigned", t.get("assignment_outcome") or "—"),
                ("Exit", t.get("exit_note") or "—"),
                ("Roll", t.get("roll_trigger") or "—"),
                ("Volatility", f"IV30 {(t.get('iv30') or 0):.1f} vs realised {(t.get('hv20') or 0):.1f} "
                               f"= {(t.get('vrp') or 0):.2f}×"),
                ("GROW", t.get("grow_note") or "—"),
                ("Earnings", t.get("earnings_note") or "—"),
            ]
            if t.get("max_loss") is not None:
                rows.insert(4, ("Max loss", _money(t.get("max_loss"))))
            if t.get("coverage_note"):
                rows.insert(4, ("Coverage", t["coverage_note"]))
            st.markdown(
                "<div class='hv-kv'>"
                + "".join(f"<div><b>{k}</b> {v}</div>" for k, v in rows)
                + "</div>", unsafe_allow_html=True)
            if t.get("risk"):
                st.caption(f"What would make this wrong: {t['risk']}")
            if t.get("rules_cited"):
                st.markdown(" ".join(status_chip(r, "neutral") for r in t["rules_cited"]),
                            unsafe_allow_html=True)
            st.caption("Prosper writes tickets. It never places orders — type this into IBKR "
                       "yourself, and re-check the bid/ask first.")

# ─────────────────────────────────────────────────────────────────────────────
# Why things did not make it — the trust surface
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("What was rejected, and why")
st.caption("An engine that shows only what it likes is indistinguishable from one that is broken. "
           "These are the names that produced nothing today.")

if blocked:
    st.markdown("**Passed the doctrine but blocked by a position cap**")
    for b in blocked:
        st.markdown(f"<div class='hv-rej'><span class='t'>{b.get('ticker')}</span> "
                    f"{b.get('strategy','').replace('_',' ')} — {b.get('blocked')}</div>",
                    unsafe_allow_html=True)

if model_rejections:
    st.markdown("**Considered and set aside**")
    for r in model_rejections:
        st.markdown(f"<div class='hv-rej'><span class='t'>{r.get('candidate_id','')}</span> "
                    f"{r.get('reason','')}</div>", unsafe_allow_html=True)

if engine_rejections:
    st.markdown("**Filtered before scoring**")
    _shown = 0
    for r in engine_rejections:
        if _shown >= 25:
            st.caption(f"…and {len(engine_rejections) - _shown} more.")
            break
        st.markdown(f"<div class='hv-rej'><span class='t'>{r.get('ticker')}</span> "
                    f"<em>{r.get('strategy','').replace('_',' ')}</em> — {r.get('reason')}</div>",
                    unsafe_allow_html=True)
        _shown += 1

if not (blocked or model_rejections or engine_rejections):
    st.caption("Nothing was rejected for a recordable reason today.")

# ─────────────────────────────────────────────────────────────────────────────
# Open positions
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Open positions")
try:
    open_pos = get_open_harvest_positions()
except Exception:
    open_pos = pd.DataFrame()

if open_pos is None or open_pos.empty:
    st.caption("No open Harvest positions recorded. Add one after you place a trade so the engine "
               "can honour the one-position-per-underlying rule and manage rolls.")
else:
    today = date.today()
    for _, p in open_pos.iterrows():
        try:
            dte = (datetime.strptime(str(p["expiry"]), "%Y-%m-%d").date() - today).days
        except (ValueError, TypeError):
            dte = None
        level = "critical" if (dte is not None and dte <= 7) else (
            "warn" if (dte is not None and dte <= 14) else "good")
        st.markdown(
            f"<div class='hv-card'><div class='hv-r1'>"
            f"<span class='hv-sym'>{p['ticker']}</span>"
            f"<span class='hv-amt pos'>{_money(p.get('credit_received'))}</span></div>"
            f"<div class='hv-r2'><span>{str(p['strategy']).replace('_',' ')} · "
            f"{int(p['contracts'])}× {float(p['strike']):g}{p['right']} · {p['expiry']}</span>"
            f"<span>{status_chip(f'{dte}d left' if dte is not None else 'expiry ?', level)}</span>"
            f"</div></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Premium ledger — R3's scoreboard
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Premium ledger")
try:
    recs = get_harvest_recommendations(days=365)
except Exception:
    recs = pd.DataFrame()

if recs is None or recs.empty:
    st.caption("No recommendation history yet. Every idea is logged the day it is made, with the "
               "price it was made at — that record is the only way to find out whether the engine "
               "is any good.")
else:
    taken = recs[recs["status"] == "taken"] if "status" in recs.columns else recs.iloc[0:0]
    proposed_credit = pd.to_numeric(recs.get("net_premium"), errors="coerce").fillna(0)
    taken_credit = pd.to_numeric(taken.get("net_premium"), errors="coerce").fillna(0) \
        if not taken.empty else pd.Series(dtype=float)
    stat_grid([
        ("Ideas logged", str(len(recs))),
        ("Taken", str(len(taken))),
        ("Premium if all taken", fmt_compact(proposed_credit.sum(), "USD")),
    ], columns=3)
    if not taken.empty:
        collected = taken_credit.sum()
        stat_grid([
            ("Premium collected", _money(collected)),
            ("vs T-bill on collateral", f"{(collected / collateral_avail * 100):.2f}%"
                if collateral_avail else "—"),
            ("Positions", str(len(taken))),
        ], columns=3)

# ─────────────────────────────────────────────────────────────────────────────
# Volatility map — one chart that makes the whole engine legible
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Volatility map")
st.caption("Implied against realised. Above the line, the market is paying more than the stock is "
           "moving — premium worth selling. Below it, options are cheap and worth buying.")

try:
    snaps = get_chain_snapshots(slate_date)
except Exception:
    snaps = {}

points = []
for tkr, s in (snaps or {}).items():
    m = s.get("_metrics") or {}
    if m.get("iv30") and m.get("hv20"):
        points.append({"ticker": tkr, "iv30": m["iv30"], "hv20": m["hv20"],
                       "vrp": m.get("vrp") or 0})

if not points:
    st.caption("No volatility observations stored for this scan date yet.")
else:
    import plotly.graph_objects as go
    from core.ui_components import show_chart

    df = pd.DataFrame(points)
    lim = float(max(df["iv30"].max(), df["hv20"].max())) * 1.08
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[0, lim], y=[0, lim], mode="lines", name="fair",
        line=dict(dash="dash", width=1, color="rgba(128,128,128,0.55)"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=df["hv20"], y=df["iv30"], mode="markers+text", text=df["ticker"],
        textposition="top center", textfont=dict(size=9), name="names",
        marker=dict(size=9,
                    color=df["vrp"], colorscale=[[0, "#b3261e"], [0.5, "#9a5b06"], [1, "#0f7a52"]],
                    cmin=0.6, cmax=1.6, showscale=False,
                    line=dict(width=0.5, color="rgba(128,128,128,0.5)")),
        customdata=df[["vrp"]].values,
        hovertemplate="<b>%{text}</b><br>realised %{x:.1f}<br>implied %{y:.1f}"
                      "<br>ratio %{customdata[0]:.2f}<extra></extra>"))
    fig.update_layout(
        xaxis_title="Realised volatility (HV20, %)", yaxis_title="Implied volatility (IV30, %)",
        showlegend=False, margin=dict(l=10, r=10, t=10, b=10), height=420)
    show_chart(fig, key="hv_volmap")

# ─────────────────────────────────────────────────────────────────────────────
st.divider()
_u = slate.get("usage") or {}
st.caption(
    f"HARVEST v1.0 · slate {slate_date} · model {meta.get('model_id') or _u.get('model_id') or '—'} "
    f"· ${(meta.get('cost_estimate') or _u.get('cost') or 0):.4f} for today's run · "
    f"chains from CBOE delayed quotes, earnings from Finnhub, realised volatility from Yahoo/Twelve Data. "
    f"Prosper writes tickets and never places orders."
)
