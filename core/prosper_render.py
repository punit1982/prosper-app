"""
PROSPER v5.13.1 — Streamlit rendering of a saved card
=====================================================
§B13: the deliverable is the PROSPER CARD, nine sections in PS's order, plain English, with the
[FACT]/[CALC]/[EST] tags left inline on numbers. Every number drawn here comes from the Python
resolver (core.prosper_engine.resolve_card), never from the model's own arithmetic; the model's
card is kept, verbatim, behind a tap.

Model text goes into raw HTML in a few places, so it is always escaped first.
"""

import html
import json
import math
from typing import Optional

import streamlit as st

import core.ledger_ui as _lu
from core.framework_version import FRAMEWORK_VERSION, is_current, retired_label

TIER_LABEL = {"screen": "Screen — provisional", "delta": "Delta", "standard": "Standard",
              "full": "Full + memo", "cowork": "Imported from a chat window"}

DIM_NAMES = {
    "d1": "Megatrend fit", "d2": "Moat & traction", "d3": "Forward opportunity",
    "d4": "Founder & capital", "d5": "Asymmetric setup",
    "d6": "Dividend durability", "d7": "Local-cycle position",
}


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _f(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        return None if (f != f or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _money(v, ccy: str = "") -> str:
    f = _f(v)
    if f is None:
        return "—"
    s = f"{f:,.2f}" if abs(f) < 1000 else f"{f:,.0f}"
    return f"{ccy} {s}".strip()


def _vs(v, spot) -> str:
    f, s = _f(v), _f(spot)
    if f is None or not s:
        return "—"
    return f"{(f / s - 1) * 100:+.0f}%"


def _load_json(v, default):
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return default


def score_color(q) -> str:
    """Colour for a 0–100 PROSPER score, on the same ramp as the call words."""
    f = _f(q)
    if f is None:
        return _lu.c("ink-3") if hasattr(_lu, "c") else "#888"
    from core.prosper_engine import band_for
    return _lu.verdict(band_for(f))


def call_color(word) -> str:
    return _lu.verdict(str(word or ""))


def is_prosper(analysis: dict) -> bool:
    return bool(analysis) and is_current(analysis.get("framework"))


def _parts(analysis: dict):
    full = _load_json(analysis.get("full_response"), {}) or {}
    data = full.get("prosper_json") or {}
    r = full.get("resolved") or {}
    return full, data, r


def header_html(analysis: dict, ccy: str = "") -> str:
    """Card header + section 2 — the score, the call and the one line to act on."""
    full, data, r = _parts(analysis)
    q = analysis.get("q_score") if analysis.get("q_score") is not None else analysis.get("score")
    call = str(analysis.get("entry_verdict") or analysis.get("rating") or "—")
    qc, cc = score_color(q), call_color(call)
    spot = analysis.get("price_at_run")
    price = data.get("price") if isinstance(data.get("price"), dict) else {}
    basis = price.get("basis") or "price at run"
    when = price.get("time") or analysis.get("analysis_date") or ""
    off = r.get("pct_off_high")
    regime = analysis.get("regime_state") or r.get("regime_state")
    mult = r.get("regime_multiplier")
    mood = (f"Market mood: <b>{_e(regime)}</b>" + (f" (new buys at {mult*100:.0f}% size)" if mult is not None else "")
            if regime else "Market mood: not established")
    conf = analysis.get("confidence") or ""
    raise_ = data.get("confidence_raise") or ""
    q_txt = f"{float(q):.1f}" if _f(q) is not None else "—"
    return (
        f'<div style="border:1px solid rgba(128,128,128,0.18);border-radius:12px;padding:16px 20px;margin:8px 0 12px 0">'
        f'<div style="font-size:0.82rem;color:var(--p-ink-3)">{_money(spot, ccy)} ({_e(basis)} · {_e(when)})'
        + (f' · {off:.0f}% off 52-wk high' if _f(off) is not None else "")
        + f' · {mood}</div>'
        f'<div style="display:flex;gap:24px;flex-wrap:wrap;align-items:center;margin-top:10px">'
        f'<div><div style="font-size:0.72rem;color:var(--p-ink-3);letter-spacing:0.5px">SCORE</div>'
        f'<div style="font-size:2.3rem;font-weight:800;color:{qc};line-height:1">{q_txt}'
        f'<span style="font-size:1rem;color:var(--p-ink-3)"> / 100</span></div></div>'
        f'<div><div style="font-size:0.72rem;color:var(--p-ink-3);letter-spacing:0.5px">THE CALL</div>'
        f'<div style="display:inline-block;background:{cc};color:white;padding:7px 18px;border-radius:8px;'
        f'font-weight:800;font-size:1.25rem;margin-top:4px">{_e(call)}</div></div>'
        f'</div>'
        f'<div style="margin-top:12px;font-size:1rem"><b>Do this:</b> {_e(analysis.get("do_this") or "—")}</div>'
        + (f'<div style="margin-top:4px;font-size:0.9rem;color:var(--p-ink-3)">Confidence: <b>{_e(conf)}</b>'
           + (f' — {_e(raise_)}' if raise_ else "") + '</div>' if conf else "")
        + '</div>'
    )


def render_retired(analysis: dict, ticker: str = "") -> None:
    """A row written by a retired framework: superseded, never mapped (P9)."""
    fw = retired_label(analysis.get("framework"))
    st.warning(
        f"The saved analysis for **{ticker or analysis.get('ticker', '')}** was produced by "
        f"**{fw}** on **{analysis.get('analysis_date', '?')}**. {FRAMEWORK_VERSION} has replaced it, "
        f"and its levels are context only, not a prior run — this name counts as **unrated** "
        f"until it is run under {FRAMEWORK_VERSION}."
    )
    with st.expander(f"The superseded {fw} view (context only)", expanded=False):
        if analysis.get("thesis"):
            st.caption(str(analysis["thesis"]))
        if analysis.get("memo_md"):
            st.markdown(analysis["memo_md"])


def render_prosper_analysis(analysis: dict, ticker: str = "", ccy: str = "") -> None:
    """The full PROSPER CARD view for the Security (Equity Deep Dive) page."""
    if not analysis:
        return
    if not is_prosper(analysis):
        render_retired(analysis, ticker)
        return

    full, data, r = _parts(analysis)
    spot = analysis.get("price_at_run")
    tier = analysis.get("model_used", "")
    screen_only = tier == "screen" or bool(full.get("screen_only"))

    st.caption(f"**{FRAMEWORK_VERSION}** · {TIER_LABEL.get(tier, tier)} · run {analysis.get('analysis_date', '')}"
               + (f" · valid until {analysis.get('valid_until')}" if analysis.get("valid_until") else "")
               + (f" · {analysis.get('company') or full.get('company')}" if (analysis.get("company") or full.get("company")) else ""))
    if screen_only:
        st.warning("This is a **screen** — no live searches, so no news, IR catalyst dates, litigation "
                   "search or estimate revisions. Treat the call as provisional and run Standard before acting.")
    try:
        if analysis.get("valid_until") and str(analysis["valid_until"]) < __import__("datetime").date.today().isoformat():
            st.warning(f"This card expired on {analysis['valid_until']} (step 13). Re-run it before acting.")
    except Exception:
        pass

    # 1 WHAT THEY DO
    what = full.get("what_it_does") or data.get("what_they_do")
    if what:
        st.markdown(f"**1 · What they do** — {what}")

    # 2 RATING & RECOMMENDATION
    st.markdown(header_html(analysis, ccy), unsafe_allow_html=True)
    for g in r.get("gates") or []:
        st.info(f"**Held back** from {g.get('from')} to {g.get('to')}: {g.get('why')}."
                + (f" Released at {g.get('release')}." if g.get("release") else ""))

    # 3 WHY
    why = data.get("why") or {}
    if why:
        st.markdown("##### 3 · Why")
        st.markdown(f"➕ {why.get('for') or '—'}  \n➖ {why.get('against') or '—'}  \n🟰 {why.get('tips') or '—'}")
    integ = data.get("integrity") or {}
    itype = r.get("integrity_type")
    if itype and itype != "NONE":
        label = {"ACCOUNTS": "Accounting integrity — the reported numbers are in question",
                 "CONDUCT": "Conduct / compliance matter — priced into the cases, no adds until resolved",
                 "REPORTING_CONTROL": "Reporting-control flag — a company-found correction; management score docked"}.get(itype, itype)
        st.warning(f"**{label}.** {integ.get('detail') or ''}"
                   + (f"  \n_Direction source:_ {integ.get('direction_source')}" if integ.get("direction_source") else ""))

    # 4 BEAR · BASE · BULL
    cases = data.get("cases") or {}
    w = r.get("weights") or {}
    rows = []
    if r.get("conduct") and r.get("break") is not None:
        rows.append({"Case": "Break", "Price": _money(r["break"], ccy), "vs today": _vs(r["break"], spot),
                     "Weight": f"{w.get('break', 0)*100:.0f}%", "If": (cases.get("break") or {}).get("why", "")})
    for k in ("bear", "base", "bull"):
        rows.append({"Case": k.title(), "Price": _money(r.get(k), ccy), "vs today": _vs(r.get(k), spot),
                     "Weight": f"{w.get(k, 0)*100:.0f}%" if k in w else "—",
                     "If": (cases.get(k) or {}).get("why", "")})
    st.markdown(f"##### 4 · Bear · Base · Bull (3 years, {data.get('horizon_label') or '—'})")
    st.table(rows)

    # 5 ASYMMETRY
    from core.prosper_engine import ratio_formula
    st.markdown("##### 5 · Asymmetry")
    st.code(f"reward:risk = (bull − spot) ÷ (spot − stressed bear)\n{ratio_formula(r)}", language=None)
    ratio = _f(analysis.get("reward_risk"))
    lines = []
    if ratio is not None and ratio < 999:
        lines.append(f"For every $1 you could lose, you could make **${max(ratio, 0):,.2f}**.")
    pw = _f(analysis.get("prob_weighted_return"))
    if pw is not None:
        lines.append(f"Probability-weighted 3-year return: **{pw*100:+.0f}%**"
                     + (f" (about {r['pw_return_pa']*100:+.1f}% a year)" if _f(r.get("pw_return_pa")) is not None else "") + ".")
    if _f(analysis.get("reentry_price")) is not None:
        lines.append(f"Buy-worthy only at ≥2×; that happens at **{_money(analysis['reentry_price'], ccy)}** = (bull + 2 × bear) ÷ 3.")
    if lines:
        st.markdown("  \n".join(lines))

    # 6 CATALYSTS
    cats = full.get("catalysts") or data.get("catalysts") or []
    st.markdown("##### 6 · Catalysts (dated, next 12 months)")
    if cats:
        for c in cats:
            if isinstance(c, dict):
                st.markdown(f"- **{c.get('event', '')}** — {c.get('date') or 'date not yet announced'} — {c.get('impact', '')}")
    else:
        st.caption("None named.")

    # 7 ACTION PRICES
    ap = data.get("action_prices") or {}
    tps = r.get("take_profit") or []
    st.markdown("##### 7 · Action prices")
    st.markdown("".join([
        _lu.kv("Buy zone", _e(f"{_money(analysis.get('buy_zone_low'), ccy)} – {_money(analysis.get('buy_zone_high'), ccy)}")),
        _lu.kv("Add", _e(ap.get("add") or "—")),
        _lu.kv("Take profits", _e(" · ".join(_money(t, ccy) for t in tps[:3]) or "—"), note="¼ · ½ · most"),
        _lu.kv("Walk away if", _e(analysis.get("walk_away") or ap.get("walk_away") or "—")),
        _lu.kv("Starter size", _e(f"{analysis['starter_pct']:g}% of the book" if _f(analysis.get("starter_pct")) is not None else "—"),
               note=(f"conviction target {r.get('conviction_target_pct'):g}% × regime multiplier — "
                     "shares and funding are BOOK PULSE's job (P1)") if _f(r.get("conviction_target_pct")) is not None else ""),
    ]), unsafe_allow_html=True)

    # 8 WHAT WOULD PROVE US WRONG
    pws = full.get("prove_wrong") or data.get("prove_wrong") or []
    if pws:
        st.markdown("##### 8 · What would prove us wrong")
        for p in pws:
            if isinstance(p, dict):
                st.markdown(f"- **{p.get('fact', '')}** → {p.get('effect', '')}")
            else:
                st.markdown(f"- {p}")

    # 9 WHAT WE COULDN'T VERIFY
    st.markdown("##### 9 · What we couldn't verify")
    st.caption(str(data.get("unverified") or "—"))

    # ── behind a tap ──
    unc = full.get("uncertainties") or []
    if unc:
        with st.expander(f"What the app recalculated or flagged ({len(unc)})", expanded=False):
            for u in unc:
                st.markdown(f"- {u}")

    scores = r.get("scores") or {}
    raw = r.get("scores_raw") or {}
    if scores:
        with st.expander("Scorecard (detail)", expanded=False):
            sc_in = data.get("scores") or {}
            rows = []
            for k in ("d1", "d2", "d3", "d4", "d5", "d6", "d7"):
                if scores.get(k) is None and raw.get(k) is None:
                    continue
                why_k = (sc_in.get(k) or {}).get("why", "") if isinstance(sc_in.get(k), dict) else ""
                rows.append({"Dimension": DIM_NAMES.get(k, k), "Model": raw.get(k), "Used": scores.get(k), "Why": why_k})
            st.table(rows)
            st.caption(f"Lens: {r.get('weights_used', 'CORE').title()} weights · route {analysis.get('archetype_name') or r.get('route')} · "
                       f"AI class {r.get('ai_class', '—')} · re-rating gate {r.get('rr_status', '—')}"
                       + (f" (+{r['rr_bonus']:g})" if r.get("rr_bonus") else "")
                       + (f" · diluted share growth {r['dilution_cagr']*100:.1f}%/yr" if _f(r.get("dilution_cagr")) is not None else ""))
            micro = data.get("microcap") or {}
            if micro.get("pillars"):
                st.caption("Microcap pillars: " + ", ".join(f"{k.upper()} {v}" for k, v in micro["pillars"].items()))
            dist = data.get("distressed") or {}
            if any(dist.get(k) is not None for k in ("s1", "s2", "s3")):
                st.caption("Distressed: " + ", ".join(f"{k.upper()} {dist.get(k)}" for k in ("s1", "s2", "s3")))

    anchors = [a for a in (data.get("anchors") or []) if isinstance(a, dict)]
    change = [c for c in (full.get("change_table") or []) if isinstance(c, dict)]
    entry_line = full.get("entry_line")
    if anchors or change or entry_line:
        with st.expander("Anchor log and change since last run (P9)", expanded=False):
            if entry_line:
                st.markdown(f"Entry line: vs last run **{_money(entry_line.get('old'), ccy)} → {_money(entry_line.get('new'), ccy)}** · "
                            f"driver: **{entry_line.get('driver')}**")
            if change:
                st.table(change)
            elif entry_line:
                st.caption("No input changed.")
            if anchors:
                st.table(anchors)

    reg = data.get("regime") or {}
    if reg.get("inputs"):
        with st.expander(f"Regime of record — {reg.get('state', '—')}", expanded=False):
            st.table([{"Input": k, "Reading": v} for k, v in (reg.get("inputs") or {}).items()])
            if reg.get("unavailable"):
                st.caption("Unavailable: " + ", ".join(str(x) for x in reg["unavailable"]))

    memo = analysis.get("memo_md")
    if memo:
        with st.expander("The model's own card" + (" and memo" if tier == "full" else ""), expanded=False):
            st.markdown(memo)

    card = analysis.get("card_md")
    if card:
        with st.expander("Card as text (copy or save)", expanded=False):
            st.code(card, language=None)
            st.download_button("Download this card (.md)", data=card,
                               file_name=f"{FRAMEWORK_VERSION} CARD {ticker or analysis.get('ticker', '')} "
                                         f"{str(analysis.get('analysis_date', ''))}.md",
                               mime="text/markdown", key=f"dl_card_{ticker}")

    meta = []
    if analysis.get("cost_estimate") is not None:
        meta.append(f"cost USD {float(analysis['cost_estimate']):.3f}")
    if full.get("web_searches"):
        meta.append(f"{full['web_searches']} web searches")
    if full.get("elapsed_seconds"):
        meta.append(f"{full['elapsed_seconds']}s")
    if full.get("model_id"):
        meta.append(str(full["model_id"]))
    if meta:
        st.caption(" · ".join(meta))
