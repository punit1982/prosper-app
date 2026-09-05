"""
GROW v5.1 — Streamlit rendering of a saved analysis
====================================================
Rule 20: wherever a verdict is shown, the Durability score and the Entry
arithmetic that produced it travel with it. These helpers make that the only
way a verdict can be drawn in the app.
"""

import json
from typing import Optional

import streamlit as st

ENTRY_COLORS = {
    "STRONG BUY": "#00C853",
    "BUY": "#1a9e5c",
    "HOLD": "#f39c12",
    "SELL": "#FF6D00",
    "STRONG SELL": "#DD2C00",
}


def durability_color(score) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "#888"
    if s >= 85: return "#00C853"
    if s >= 70: return "#1a9e5c"
    if s >= 55: return "#f39c12"
    if s >= 40: return "#FF6D00"
    return "#DD2C00"


def durability_band(score) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    if s >= 85: return "Exceptional"
    if s >= 70: return "Strong"
    if s >= 55: return "Conditional"
    if s >= 40: return "Weak"
    return "Not durable"


def _money(v, ccy: str = "") -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if f != f:
        return "—"
    s = f"{f:,.2f}" if abs(f) < 1000 else f"{f:,.0f}"
    return f"{ccy} {s}".strip()


def _pct(v) -> str:
    try:
        f = float(v)
        return f"{f*100:+.1f}%"
    except (TypeError, ValueError):
        return "—"


def _load_json(v, default):
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return default


def is_grow(analysis: dict) -> bool:
    return bool(analysis) and str(analysis.get("framework") or "").startswith("GROW")


def verdict_block_html(analysis: dict, ccy: str = "") -> str:
    """The §10.2 'two answers' block — score, word, ladder, expected return vs bar."""
    dur = analysis.get("durability")
    band = analysis.get("durability_band") or durability_band(dur)
    verdict = str(analysis.get("entry_verdict") or analysis.get("rating") or "—")
    vc = ENTRY_COLORS.get(verdict, "#888")
    dc = durability_color(dur)
    price = analysis.get("price_at_run")
    cagr = analysis.get("cagr_spot")
    req = analysis.get("required_return")
    conf = analysis.get("confidence") or ""
    sb, bb, fh, ra = (analysis.get("strong_buy_below"), analysis.get("buy_below"),
                      analysis.get("fair_high"), analysis.get("reduce_above"))
    dur_txt = f"{float(dur):.0f}" if dur is not None else "—"
    ladder = (
        f"Strong buy below <b>{_money(sb, ccy)}</b> · Buy below <b>{_money(bb, ccy)}</b> · "
        f"Fairly priced <b>{_money(bb, ccy)}–{_money(fh or ra, ccy)}</b> · Reduce above <b>{_money(ra or fh, ccy)}</b>"
    )
    ret_line = ""
    if cagr is not None and req is not None:
        ret_line = (f"Today {_money(price, ccy)}. Expected return about <b>{float(cagr)*100:.1f}% a year</b>, "
                    f"against a bar of <b>{float(req)*100:.1f}%</b>.")
    elif price is not None:
        ret_line = f"Today {_money(price, ccy)}."
    return (
        f'<div style="border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:18px 22px;margin:8px 0 14px 0;'
        f'background:linear-gradient(135deg, rgba(26,158,92,0.07), rgba(0,0,0,0))">'
        f'<div style="display:flex;gap:28px;flex-wrap:wrap;align-items:center">'
        f'<div><div style="font-size:0.75rem;color:#999;letter-spacing:0.5px">DURABILITY · is this worth owning</div>'
        f'<div style="font-size:2.4rem;font-weight:800;color:{dc};line-height:1">{dur_txt}<span style="font-size:1rem;color:#888"> / 100</span> '
        f'<span style="font-size:1rem;font-weight:600;color:{dc}">{band}</span></div></div>'
        f'<div><div style="font-size:0.75rem;color:#999;letter-spacing:0.5px">ENTRY · is it worth buying today</div>'
        f'<div style="display:inline-block;background:{vc};color:white;padding:8px 20px;border-radius:8px;font-weight:800;font-size:1.4rem;margin-top:4px">{verdict}</div></div>'
        f'</div>'
        f'<div style="margin-top:12px;font-size:0.95rem">{ladder}</div>'
        f'<div style="margin-top:6px;font-size:0.95rem;color:#ccc">{ret_line}</div>'
        + (f'<div style="margin-top:6px;font-size:0.9rem;color:#aaa">Confidence: <i>{conf}</i></div>' if conf else "")
        + f'</div>'
    )


def render_grow_analysis(analysis: dict, ticker: str = "", ccy: str = "") -> None:
    """Full GROW result view for the Equity Deep Dive page."""
    if not analysis:
        return

    if not is_grow(analysis):
        # Rule 22: a PROSPER-scale verdict is superseded, not mapped.
        st.warning(
            f"The saved analysis for **{ticker or analysis.get('ticker', '')}** was produced by the retired "
            f"PROSPER engine on **{analysis.get('analysis_date', '?')}**. Under GROW v5.1 rule 22 it is "
            f"superseded and this name counts as **unrated** until it is re-run with GROW."
        )
        return

    full = _load_json(analysis.get("full_response"), {}) or {}
    grow = full.get("grow_json") or {}
    cls = analysis.get("classification") or full.get("classification") or grow.get("classification") or {}
    cases = analysis.get("cases") or full.get("cases") or grow.get("cases") or {}
    stability = analysis.get("stability") or full.get("stability") or (grow.get("entry") or {}).get("stability") or {}
    one_reason = analysis.get("one_reason") or full.get("one_reason") or grow.get("one_reason") or {}
    triggers = analysis.get("break_triggers") or full.get("break_triggers") or grow.get("break_triggers") or []
    driving = analysis.get("driving_inputs") or full.get("driving_inputs") or grow.get("driving_inputs") or []
    failed_peer = analysis.get("failed_peer") or full.get("failed_peer") or grow.get("failed_peer")
    uncertainties = analysis.get("uncertainties") or full.get("uncertainties") or grow.get("uncertainties") or []
    what = analysis.get("what_it_does") or full.get("what_it_does") or grow.get("what_it_does") or ""
    criteria = _load_json(analysis.get("score_breakdown"), {}) or {}
    entry = grow.get("entry") or {}
    dur = grow.get("durability") or {}
    change_table = analysis.get("change_table") or full.get("change_table") or grow.get("change_table") or []
    tier = analysis.get("model_used", "")
    screen_only = bool(analysis.get("screen_only") or full.get("screen_only"))

    # Header line
    date = analysis.get("analysis_date", "")
    st.caption(f"**GROW v5.1** · {'screen only — provisional' if screen_only else GROW_TIER_LABEL.get(tier, tier)} · run {date}"
               + (f" · {analysis.get('company')}" if analysis.get("company") else ""))
    if screen_only:
        st.warning("This is a **screen** (no filings retrieved). Treat both verdicts as provisional and run Standard GROW before acting.")

    if what:
        st.markdown(what)

    st.markdown(verdict_block_html(analysis, ccy), unsafe_allow_html=True)

    # Stability / caps
    if stability:
        words = [str(stability.get(k, "—")) for k in ("minus25", "central", "plus25")]
        unstable = bool(stability.get("unstable")) or len(set(words)) > 1
        line = f"Verdict at −25% / central / +25% on the exit multiple: **{' · '.join(words)}**"
        (st.warning if unstable else st.caption)(("**VERDICT UNSTABLE** — " if unstable else "") + line)
    caps = list(entry.get("caps") or []) + list(entry.get("ceilings") or [])
    if caps:
        st.caption("Caps / ceilings applied: " + ", ".join(str(c) for c in caps))

    # Classification (plain-English row, codes in expander)
    if cls:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Archetype", f"{cls.get('archetype_name') or cls.get('archetype') or '—'}")
        c2.metric("Runner-up would say", f"{cls.get('runner_up_entry') or '—'}", help=f"Runner-up archetype: {cls.get('runner_up', '—')}")
        c3.metric("Horizon", f"{cls.get('horizon_years', '—')} yrs", help=f"Valuation date {cls.get('valuation_date', '—')}")
        c4.metric("Evidence stage", f"{cls.get('stage', '—')} · {cls.get('basis', '—')}",
                  help="Proof stage · measurement basis (see GROW §5)")

    # Driving inputs
    if driving:
        st.markdown("##### Driving inputs")
        rows = []
        for d in driving[:6]:
            if isinstance(d, dict):
                rows.append({"Input": d.get("input", ""), "Value": d.get("value", ""), "Class": d.get("class", ""),
                             "Source": d.get("source", ""), "Moves the answer by": d.get("moves_by", "")})
        if rows:
            st.table(rows)
            n_c = sum(1 for r in rows if str(r["Class"]).strip().upper() == "C")
            if n_c > 2:
                st.warning(f"{n_c} of the driving inputs are forecasts (Class C) — GROW treats the Entry as a range, not a word.")

    # Cases
    if cases:
        st.markdown("##### What you make and what you lose")
        labels = [("break", "If I'm badly wrong"), ("bear", "If I'm mildly wrong"), ("base", "What I actually expect"), ("bull", "If it goes well")]
        rows = []
        for key, label in labels:
            c = cases.get(key) or {}
            if isinstance(c, dict):
                rows.append({"Case": label, "Price": _money(c.get("price"), ccy), "Return / yr": _pct(c.get("return_pa")),
                             "What has to be true": c.get("what_must_be_true", "")})
        if rows:
            st.table(rows)

    # One reason + triggers + failed peer
    if one_reason:
        st.markdown("##### The one reason")
        st.info(f"**{one_reason.get('criterion', '')}**  \n_What would prove it false:_ {one_reason.get('what_would_prove_it_false', '')}")
    if triggers:
        st.markdown("##### What would change my mind")
        for t in triggers:
            if isinstance(t, dict):
                st.markdown(f"- **{t.get('metric', '')}** — {t.get('threshold', '')} → {t.get('effect_on_durability', '')}")
            else:
                st.markdown(f"- {t}")
    if failed_peer:
        fp = failed_peer if isinstance(failed_peer, dict) else {"name": str(failed_peer), "why": ""}
        st.markdown(f"**The failed peer:** {fp.get('name', '')} — {fp.get('why', '')}")

    # Durability breakdown
    if criteria:
        with st.expander("Durability — the eight criteria and weights", expanded=False):
            rows = []
            for k in sorted(criteria, key=lambda x: int(str(x)) if str(x).isdigit() else 99):
                c = criteria[k]
                if isinstance(c, dict):
                    rows.append({"#": c.get("n", k), "Criterion": c.get("name", ""), "Score /10": c.get("score", ""),
                                 "Weight": c.get("weight", ""), "Observable": c.get("observable", "")})
            if rows:
                st.table(rows)
            aw = dur.get("available_weight")
            if aw and float(aw) < 100:
                st.caption(f"Durability scored on {aw} of 100 available weight (unscoreable criteria redistributed).")
            if dur.get("integrity_multiplier") not in (None, 1, 1.0):
                st.caption(f"Integrity level {dur.get('integrity_level')} · multiplier ×{dur.get('integrity_multiplier')}")
            if dur.get("caps_applied"):
                st.caption("Caps: " + ", ".join(str(x) for x in dur["caps_applied"]))

    if change_table:
        with st.expander("Change since last run", expanded=False):
            st.table([c for c in change_table if isinstance(c, dict)])

    if uncertainties:
        with st.expander(f"What I'm not sure about ({len(uncertainties)})", expanded=False):
            for u in uncertainties:
                st.markdown(f"- {u}")

    memo = analysis.get("memo_md")
    if memo:
        with st.expander("Full memo", expanded=False):
            st.markdown(memo)

    meta = []
    if analysis.get("cost_estimate") is not None:
        meta.append(f"cost USD {float(analysis['cost_estimate']):.3f}")
    if full.get("web_searches"):
        meta.append(f"{full['web_searches']} web searches")
    if full.get("elapsed_seconds"):
        meta.append(f"{full['elapsed_seconds']}s")
    if full.get("model_id"):
        meta.append(full["model_id"])
    if meta:
        st.caption(" · ".join(meta))


GROW_TIER_LABEL = {"screen": "Screen", "standard": "Standard GROW", "full": "Full GROW"}
