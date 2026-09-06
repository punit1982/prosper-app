"""
UI Components
=============
Small shared visual components, so status (fine / needs attention / act now)
has ONE consistent look across the app instead of a different ad hoc emoji
vocabulary per page (see the UI/UX audit, finding #1 — Dividend Dashboard used
🔴/🟡/🟢/⬛, Portfolio Dashboard used the same emoji for a different meaning,
Command Center used yet another set of words for the same three states).

Start small: one chip component, adopted page by page as each is touched,
rather than a one-shot rewrite of every status indicator in the app.
"""

# text color, background — one row per severity level. Deliberately distinct
# from the app's own accent color (used for the floating chat button etc.);
# semantic color is not the same thing as brand color.
_CHIP_COLORS = {
    "critical": ("#d63031", "#fbe4e3"),  # matches core/fortress.py REGIME_COLORS red
    "warn":     ("#a6741a", "#f7eedb"),
    "good":     ("#1a9e5c", "#e6f4ec"),  # matches core/fortress.py REGIME_COLORS green
    "neutral":  ("#666666", "#ececec"),
}


def fmt_age(secs: float) -> str:
    """Human-friendly "how long ago" string, shared so every page's
    data-freshness caption reads the same way (see the UI/UX audit,
    finding on unlabelled cached data reading as a slow/stuck reload)."""
    s = int(secs)
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m {s % 60}s ago"
    if s < 86400:
        return f"{s // 3600}h {(s % 3600) // 60}m ago"
    return f"{s // 86400}d ago"


_RESPONSIVE_TABLE_CSS = """
<style>
/* Colors here are theme-NEUTRAL on purpose. The first version used
   var(--secondary-background-color,#f6f6f6) for the mobile card, but Streamlit
   does not define that custom property in this version, so the fallback won
   and every card rendered a light-grey panel under the app's light-on-dark
   text — unreadable. A translucent grey reads correctly on either ground
   because it tints whatever is behind it instead of replacing it, and
   currentColor-derived borders do the same. */
.ptable-wrap{overflow-x:auto;margin:0 0 0.5rem;}
.ptable{width:100%;border-collapse:collapse;font-size:0.86rem;
  color:inherit;font-variant-numeric:tabular-nums;}
.ptable thead th{text-align:left;padding:8px 10px;border-bottom:2px solid rgba(128,128,128,0.4);
  font-size:0.72rem;letter-spacing:0.03em;text-transform:uppercase;color:inherit;
  opacity:0.6;white-space:nowrap;}
.ptable tbody td{padding:8px 10px;border-bottom:1px solid rgba(128,128,128,0.22);
  color:inherit;white-space:nowrap;}
.ptable tbody td.ptable-title{font-weight:600;}
@media (max-width:767px){
  .ptable-wrap{overflow-x:visible;}
  .ptable, .ptable tbody, .ptable tr, .ptable td{display:block;width:100%;}
  .ptable thead{position:absolute;left:-9999px;}
  .ptable tr{border:1px solid rgba(128,128,128,0.28);border-radius:8px;margin-bottom:10px;
    padding:4px 2px;background:rgba(128,128,128,0.07);}
  .ptable tbody td{border:none;border-bottom:1px dashed rgba(128,128,128,0.18);
    display:flex;justify-content:space-between;gap:12px;white-space:normal;padding:7px 10px;
    min-height:38px;align-items:center;}
  .ptable tbody td:last-child{border-bottom:none;}
  .ptable tbody td.ptable-title{font-size:0.95rem;background:transparent;
    border-bottom:1px solid rgba(128,128,128,0.3);margin-bottom:2px;font-weight:650;}
  .ptable tbody td::before{content:attr(data-label);font-weight:600;opacity:0.55;
    flex:0 0 auto;text-align:left;font-size:0.78rem;}
  .ptable tbody td.ptable-title::before{content:none;}
}
</style>
"""


def render_responsive_table(df, *, title_col: str | None = None) -> None:
    """
    Render a small dataframe as a table that becomes a stack of cards on
    phones (< 768px) instead of a sideways-scrolling wall — see the UI/UX
    audit finding *"Wide tables have one mobile strategy: scroll sideways"*.

    ``df`` should already hold display-ready strings (this does no
    formatting). ``title_col`` (default: the first column) is promoted to
    the card header on mobile and gets no "label:" prefix.

    Desktop loses interactive column-sort vs. ``st.dataframe`` — an
    acceptable trade for the 5–15 row comparison tables this is used on.
    """
    import html as _html
    import streamlit as st

    cols = list(df.columns)
    if not cols:
        return
    tcol = title_col if title_col in cols else cols[0]

    head = "".join(f"<th>{_html.escape(str(c))}</th>" for c in cols)
    body_rows = []
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            val = _html.escape("" if row[c] is None else str(row[c]))
            if c == tcol:
                cells.append(f"<td class='ptable-title' data-label=''>{val}</td>")
            else:
                cells.append(f"<td data-label=\"{_html.escape(str(c))}\">{val}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    st.markdown(
        _RESPONSIVE_TABLE_CSS
        + f"<div class='ptable-wrap'><table class='ptable'>"
        + f"<thead><tr>{head}</tr></thead>"
        + f"<tbody>{''.join(body_rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def status_chip(label: str, level: str = "neutral") -> str:
    """
    Return inline HTML for a small status chip: a colored dot + label.

    level: "critical" | "warn" | "good" | "neutral" — pick by what the
    situation actually calls for (e.g. days-until-ex-dividend, margin debt,
    regime state), not by which page you're on. Use with
    st.markdown(..., unsafe_allow_html=True).
    """
    color, bg = _CHIP_COLORS.get(level, _CHIP_COLORS["neutral"])
    return (
        "<span style='display:inline-flex;align-items:center;gap:5px;"
        "font-size:11px;font-weight:600;letter-spacing:0.02em;text-transform:uppercase;"
        f"padding:2px 8px;border-radius:4px;background:{bg};color:{color};white-space:nowrap;'>"
        f"<span style='width:6px;height:6px;border-radius:50%;background:{color};"
        "display:inline-block;flex:0 0 auto'></span>"
        f"{label}</span>"
    )


# ═══════════════════════════════════════════════════════════════════════════
# MOBILE DESIGN SYSTEM  (v7.14)
# ═══════════════════════════════════════════════════════════════════════════
# Measured on a real 375×812 viewport against the owner's actual 182-holding
# portfolio, before any of this existed:
#   Command Center      3,677px = 4.5 screens; first number 526px down
#   Portfolio Dashboard 1,977px, 39 metrics, 12 st.dataframe scroll-boxes
#   Portfolio Summary   1,534px, 5 charts, 28 tap targets under 44px
#
# The root cause is not styling, it is layout arithmetic: st.columns() stacks
# below ~640px, so every "row of 3 KPIs" becomes three full-width rows ~70px
# tall. Streamlit gives no way to opt out per-row, so the fix is a CSS grid
# applied to the specific containers that must stay side by side.
#
# The density target is the IBKR mobile app: one hero figure, a dense
# supporting grid, and everything else as a scannable row list — not a
# spreadsheet in a scroll-box. Concretely:
#   · numbers are tabular-nums so columns align without a table
#   · the value and its change sit on ONE line, change right-aligned
#   · a row is a whole tap target, minimum 44px (Apple HIG / WCAG 2.5.5)
#   · nothing scrolls sideways; wide data becomes rows, not columns

# Semantic tokens. Deliberately few: two greys, one accent, two directional
# colors, one radius scale. Every value below is used somewhere in this file —
# if a token stops being referenced, delete it rather than leaving it to rot.
MOBILE_TOKENS = {
    "up":        "#1a9e5c",
    "down":      "#d63031",
    "flat":      "#8a8f98",
    "accent":    "#0984e3",
    "radius":    "10px",
    "row_min_h": "44px",   # minimum tap target
}

_MOBILE_CSS = """
<style>
:root{
  --p-up:#1a9e5c; --p-down:#d63031; --p-flat:#8a8f98; --p-accent:#0984e3;
  --p-line:rgba(128,128,128,0.22);
  --p-surface:rgba(128,128,128,0.06);
}

/* ── Reclaim the top of the screen ───────────────────────────────────────
   Streamlit's default block padding costs ~100px before the first pixel of
   content. On an 812px phone that is an eighth of the viewport spent on
   nothing, every page, every load. */
@media (max-width:767px){
  [data-testid="stMain"] .block-container{
    padding-top:0.75rem !important; padding-bottom:4.5rem !important;
    padding-left:0.85rem !important; padding-right:0.85rem !important;
  }
  [data-testid="stMain"] h1{font-size:1.35rem !important;margin-bottom:0.1rem !important;}
  [data-testid="stMain"] h2{font-size:1.15rem !important;}
  [data-testid="stMain"] h3,[data-testid="stMain"] h4{
    font-size:0.95rem !important;margin:0.9rem 0 0.35rem !important;}
  /* st.divider() costs 49px each and there are five on Command Center */
  [data-testid="stMain"] hr{margin:0.7rem 0 !important;}

  /* Tap targets. Nav links, buttons and tabs all render at 32px by default. */
  [data-testid="stMain"] .stButton button,
  [data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"],
  [data-testid="stMain"] button[data-baseweb="tab"]{
    min-height:44px !important;
  }
  /* Tab strips scroll sideways with no sign that more exist — fade the edge. */
  [data-testid="stMain"] [data-baseweb="tab-list"]{
    -webkit-overflow-scrolling:touch;
    mask-image:linear-gradient(to right,#000 88%,transparent 100%);
  }

  /* Plotly's modebar is 8 controls the user never wants, drawn ON TOP of the
     data on a 375px canvas. */
  [data-testid="stMain"] .modebar{display:none !important;}

  /* The floating chat button sits over the bottom-right of every table and
     chart; give the page enough tail to scroll clear of it, and lift it above
     the bottom navigation bar. */
  [data-testid="stMain"] .block-container > div:last-child{margin-bottom:2rem;}
  [data-testid="stMain"] [data-testid="stPopover"],
  div[class*="chat-fab"], div[class*="floating"]{
    bottom:calc(60px + env(safe-area-inset-bottom,0px)) !important;
  }
}

/* ── Hero: the one number the page exists to show ───────────────────────── */
.p-hero{margin:0.15rem 0 0.6rem;}
.p-hero .p-hero-label{font-size:0.7rem;letter-spacing:0.06em;text-transform:uppercase;
  opacity:0.55;font-weight:600;}
.p-hero .p-hero-value{font-size:clamp(1.9rem,8vw,2.6rem);font-weight:650;line-height:1.1;
  font-variant-numeric:tabular-nums;letter-spacing:-0.02em;margin:0.1rem 0 0.15rem;}
.p-hero .p-hero-delta{font-size:0.95rem;font-weight:600;font-variant-numeric:tabular-nums;}
.p-hero .p-hero-sub{font-size:0.75rem;opacity:0.55;margin-top:0.15rem;}

/* ── Stat grid: stays a grid at 375px, where st.columns() would not ─────── */
.p-stats{display:grid;gap:1px;background:var(--p-line);border:1px solid var(--p-line);
  border-radius:10px;overflow:hidden;margin:0.5rem 0 0.75rem;}
.p-stats.c2{grid-template-columns:repeat(2,1fr);}
.p-stats.c3{grid-template-columns:repeat(3,1fr);}
.p-stats.c4{grid-template-columns:repeat(4,1fr);}
.p-stat{background:var(--p-surface);padding:9px 10px;min-width:0;}
.p-stat .k{font-size:0.63rem;letter-spacing:0.04em;text-transform:uppercase;opacity:0.55;
  font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.p-stat .v{font-size:0.98rem;font-weight:650;font-variant-numeric:tabular-nums;
  line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.p-stat .d{font-size:0.72rem;font-weight:600;font-variant-numeric:tabular-nums;}
@media (max-width:359px){ .p-stats.c4{grid-template-columns:repeat(2,1fr);} }

/* ── Row list: replaces st.dataframe on phones ──────────────────────────── */
.p-rows{border:1px solid var(--p-line);border-radius:10px;overflow:hidden;margin:0.35rem 0 0.9rem;}
.p-row{display:flex;align-items:center;gap:10px;padding:8px 11px;min-height:44px;
  border-bottom:1px solid var(--p-line);}
.p-row:last-child{border-bottom:none;}
.p-row .p-id{min-width:0;flex:1 1 auto;}
.p-row .p-sym{font-weight:650;font-size:0.9rem;line-height:1.25;}
.p-row .p-name{font-size:0.72rem;opacity:0.55;line-height:1.3;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.p-row .p-num{text-align:right;flex:0 0 auto;font-variant-numeric:tabular-nums;}
.p-row .p-val{font-weight:650;font-size:0.9rem;line-height:1.25;}
.p-row .p-chg{font-size:0.75rem;font-weight:600;line-height:1.3;}
.p-up{color:var(--p-up);} .p-down{color:var(--p-down);} .p-flat{color:var(--p-flat);}

/* Sticky group header inside a long row list — IBKR keeps the section label
   visible while you scroll its rows. */
.p-group{position:sticky;top:0;z-index:2;padding:6px 11px;font-size:0.68rem;
  letter-spacing:0.05em;text-transform:uppercase;font-weight:700;opacity:0.75;
  background:var(--p-surface);backdrop-filter:blur(6px);
  border-bottom:1px solid var(--p-line);}
</style>
"""

def mobile_shell() -> None:
    """Inject the mobile design-system stylesheet.

    Call at the top of any page that uses hero_metric / stat_grid / row_list.
    Injected unconditionally: Streamlit re-runs the whole script on every
    interaction and rebuilds the DOM from scratch, so there is no run to
    "already have" the stylesheet from, and a session-scoped guard would skip
    the injection on every rerun after the first. One <style> block is a few
    hundred bytes and duplicate rules are idempotent."""
    import streamlit as st
    st.markdown(_MOBILE_CSS, unsafe_allow_html=True)


def fmt_compact(value, currency: str = "", *, decimals: int = 1) -> str:
    """2,417,140 -> "2.4M". Phones have ~20 characters of comfortable width on
    one line; a nine-digit portfolio value spends half of it on zeros. The
    exact figure stays available in the element's title attribute."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if v < 0 else ""
    a = abs(v)
    for cutoff, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= cutoff:
            body = f"{a / cutoff:,.{decimals}f}".rstrip("0").rstrip(".")
            return f"{currency + ' ' if currency else ''}{sign}{body}{suffix}"
    body = f"{a:,.0f}" if a >= 1 else f"{a:,.2f}"
    return f"{currency + ' ' if currency else ''}{sign}{body}"


def _dir_class(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "p-flat"
    return "p-up" if v > 0 else ("p-down" if v < 0 else "p-flat")


def hero_metric(label: str, value: str, *, delta: str = "", delta_value=None,
                sub: str = "", title: str = "") -> None:
    """The single figure a page exists to show, at display size.

    `delta_value` (a number) decides the delta's color; `delta` is the text.
    `title` is the unabbreviated value, surfaced on long-press/hover."""
    import html as _html
    import streamlit as st
    cls = _dir_class(delta_value)
    parts = [
        "<div class='p-hero'>",
        f"<div class='p-hero-label'>{_html.escape(label)}</div>",
        f"<div class='p-hero-value' title='{_html.escape(title or value)}'>{_html.escape(value)}</div>",
    ]
    if delta:
        parts.append(f"<div class='p-hero-delta {cls}'>{_html.escape(delta)}</div>")
    if sub:
        parts.append(f"<div class='p-hero-sub'>{_html.escape(sub)}</div>")
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def stat_grid(stats, *, columns: int = 3) -> None:
    """A row of compact KPIs that stays a row on a 375px phone.

    `stats`: iterable of (label, value) or (label, value, delta_text, delta_value).
    st.columns() cannot do this — it stacks below ~640px with no opt-out, which
    is what turned every 3-KPI row into three 70px rows."""
    import html as _html
    import streamlit as st
    cells = []
    for s in stats:
        label, value = s[0], s[1]
        delta = s[2] if len(s) > 2 else ""
        dval = s[3] if len(s) > 3 else None
        cell = [f"<div class='p-stat'><div class='k'>{_html.escape(str(label))}</div>",
                f"<div class='v' title='{_html.escape(str(value))}'>{_html.escape(str(value))}</div>"]
        if delta:
            cell.append(f"<div class='d {_dir_class(dval)}'>{_html.escape(str(delta))}</div>")
        cell.append("</div>")
        cells.append("".join(cell))
    n = max(2, min(4, columns))
    st.markdown(f"<div class='p-stats c{n}'>{''.join(cells)}</div>", unsafe_allow_html=True)


def row_list(rows, *, group: str = "") -> None:
    """A scannable list of instruments — the mobile replacement for
    st.dataframe, which renders as a fixed-height box with its own horizontal
    AND vertical scrollbars (a scroll trap inside a scrolling page, and the
    reason the holdings table showed 3 of its 12 columns on a phone).

    `rows`: iterable of dicts with keys
        symbol, name (optional), value, change (optional text),
        change_value (optional number, drives color)."""
    import html as _html
    import streamlit as st
    out = []
    if group:
        out.append(f"<div class='p-group'>{_html.escape(group)}</div>")
    for r in rows:
        chg = r.get("change") or ""
        chg_html = (f"<div class='p-chg {_dir_class(r.get('change_value'))}'>"
                    f"{_html.escape(str(chg))}</div>") if chg else ""
        name = r.get("name") or ""
        name_html = f"<div class='p-name'>{_html.escape(str(name))}</div>" if name else ""
        out.append(
            "<div class='p-row'>"
            f"<div class='p-id'><div class='p-sym'>{_html.escape(str(r.get('symbol','')))}</div>"
            f"{name_html}</div>"
            f"<div class='p-num'><div class='p-val'>{_html.escape(str(r.get('value','')))}</div>"
            f"{chg_html}</div>"
            "</div>"
        )
    st.markdown(f"<div class='p-rows'>{''.join(out)}</div>", unsafe_allow_html=True)


_PAGE_HEADER_CSS = """
<style>
.p-head{margin:0 0 0.5rem;}
.p-head .t{font-size:1.25rem;font-weight:700;letter-spacing:-0.02em;line-height:1.2;}
.p-head .m{font-size:0.72rem;opacity:0.55;margin-top:2px;}
@media (min-width:768px){ .p-head .t{font-size:1.75rem;} .p-head .m{font-size:0.8rem;} }
</style>
"""


def page_header(title: str, meta: str = "") -> None:
    """One compact page header replacing the app-name <h1> + subtitle +
    freshness caption stack.

    On Command Center that stack was ~211px before the first portfolio
    number — an <h1> reading "Prosper" (which the browser tab, the sidebar
    and the nav already say), a 1.05rem date line, and a separate
    "Data as of…" caption. Same information, one block, ~55px."""
    import html as _html
    import streamlit as st
    meta_html = f"<div class='m'>{_html.escape(meta)}</div>" if meta else ""
    st.markdown(
        _PAGE_HEADER_CSS
        + f"<div class='p-head'><div class='t'>{_html.escape(title)}</div>{meta_html}</div>",
        unsafe_allow_html=True,
    )


_RESPONSIVE_SWAP_CSS = """
<style>
/* The card list is for phones only; the desktop table stays authoritative
   (sortable, full column set) at tablet width and above. */
.p-mobile-only{display:none;}
@media (max-width:767px){
  .p-mobile-only{display:block;}
  /* Hide the st.dataframe that immediately follows the marker element.
     st.dataframe renders as a fixed-height widget with its OWN horizontal and
     vertical scrollbars — a scroll trap inside a scrolling page. Measured on
     a 375px viewport it showed 3 of the holdings table's 12 columns, with the
     4th clipped mid-character. :has() is used because Streamlit gives no way
     to put a class on a widget's own container in 1.41. */
  [data-testid="stElementContainer"]:has(.p-df-marker) + [data-testid="stElementContainer"]{
    display:none !important;
  }
}
</style>
"""


def responsive_holdings(rows, *, group: str = "", limit: int = 25) -> int:
    """Render a holdings list that is a card list on phones and leaves the
    following ``st.dataframe`` visible on larger screens.

    Call immediately BEFORE the ``st.dataframe`` it replaces::

        responsive_holdings(rows, group="Stocks — 120")
        st.dataframe(styled, use_container_width=True, hide_index=True)

    ``rows`` uses the same shape as :func:`row_list`. Returns the number of
    rows NOT rendered, so the caller can offer a way to see the rest.

    ``limit`` exists because an unbounded list is its own failure mode: the
    first version of this rendered all 182 positions and made the Dashboard
    12.8 phone screens tall — worse than the scroll-box it replaced. Rows
    should arrive pre-sorted by market value, so the cap keeps what matters.
    """
    import html as _html
    import streamlit as st

    rows = list(rows)
    hidden = max(0, len(rows) - limit) if limit else 0
    shown = rows[:limit] if limit else rows

    out = []
    if group:
        label = group if not hidden else f"{group} · top {len(shown)} by value"
        out.append(f"<div class='p-group'>{_html.escape(label)}</div>")
    for r in shown:
        chg = r.get("change") or ""
        chg_html = (f"<div class='p-chg {_dir_class(r.get('change_value'))}'>"
                    f"{_html.escape(str(chg))}</div>") if chg else ""
        name = r.get("name") or ""
        name_html = f"<div class='p-name'>{_html.escape(str(name))}</div>" if name else ""
        out.append(
            "<div class='p-row'>"
            f"<div class='p-id'><div class='p-sym'>{_html.escape(str(r.get('symbol','')))}</div>"
            f"{name_html}</div>"
            f"<div class='p-num'><div class='p-val'>{_html.escape(str(r.get('value','')))}</div>"
            f"{chg_html}</div>"
            "</div>"
        )
    st.markdown(
        _RESPONSIVE_SWAP_CSS
        + f"<div class='p-mobile-only'><div class='p-rows'>{''.join(out)}</div></div>"
        + "<div class='p-df-marker'></div>",
        unsafe_allow_html=True,
    )
    return hidden


def holdings_rows(sub_df, symbol: str, *, name_col: str = "name"):
    """Turn an enriched holdings slice into :func:`responsive_holdings` rows.

    Shows what a phone actually needs per position — what it is, what it is
    worth, how it moved today — and leaves quantity, average cost, analyst
    target and the rest to the desktop table."""
    import pandas as pd
    # Biggest positions first — a phone shows a couple of dozen rows before the
    # user gives up scrolling, so they should be the ones that move the total.
    if "market_value" in sub_df.columns:
        sub_df = sub_df.assign(
            _mv=pd.to_numeric(sub_df["market_value"], errors="coerce")
        ).sort_values("_mv", ascending=False, na_position="last")
    rows = []
    for _, r in sub_df.iterrows():
        mv = r.get("market_value")
        pct = r.get("change_pct")
        try:
            pct_f = float(pct)
            pct_txt = f"{pct_f:+.2f}%"
        except (TypeError, ValueError):
            pct_f, pct_txt = None, ""
        rows.append({
            "symbol": str(r.get("ticker", "")),
            "name": str(r.get(name_col, "") or "")[:34],
            "value": fmt_compact(mv, symbol) if pd.notna(mv) else "—",
            "change": pct_txt,
            "change_value": pct_f,
        })
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# CHARTS ON A 375px CANVAS  (v7.16)
# ═══════════════════════════════════════════════════════════════════════════
# Measured failures on the real Command Center at 375px, before this existed:
#   · P&L attribution — y-axis tick labels clipped to "00 (-4.7%)", and the
#     value annotations overlapped the bars they belonged to
#   · sector treemap — leaf labels rendered at 4-6px, pure noise
#   · allocation bars — ~40% of the width spent on the category column and
#     ~5% on the bars themselves
#   · every chart — Plotly's 8-control modebar drawn ON TOP of the data
#
# Streamlit cannot read the viewport, so a figure has to work at 375px AND at
# 1280px from one definition. Everything below is width-independent rather
# than a phone special case:
#   automargin lets the axis claim exactly the room its labels need at any
#   width instead of being clipped by a fixed margin; uniformtext HIDES text
#   that would render below the legibility floor rather than drawing it at
#   4px; a horizontal legend below the plot costs height (cheap, we scroll)
#   instead of width (scarce). The modebar is hidden via config here and via
#   CSS in mobile_shell, because Streamlit's own toolbar can re-add it.

_CHART_FONT = ('"IBM Plex Sans", -apple-system, BlinkMacSystemFont, '
               '"Segoe UI", sans-serif')


def mobile_chart(fig, *, height: int | None = None, legend: bool = True,
                 min_text: int = 9, tick_chars: int = 0):
    """Make a Plotly figure legible at 375px without breaking it at 1280px.

    ``height``     explicit pixel height; defaults to Plotly's own.
    ``legend``     False hides it entirely — prefer this when the marks are
                   already labelled, since a legend on a phone is pure cost.
    ``min_text``   text below this many px is hidden rather than drawn (the
                   treemap fix). 0 disables.
    ``tick_chars`` truncate categorical tick labels to this many characters
                   (adds an ellipsis). 0 leaves them alone — automargin will
                   make room, which is right until the labels are so long the
                   plot area collapses.

    Returns the same figure, mutated, so it can be used inline.
    """
    layout = {
        "margin": dict(l=8, r=8, t=28, b=8),
        "font": dict(family=_CHART_FONT, size=11),
        "hoverlabel": dict(font=dict(family=_CHART_FONT, size=12)),
        "xaxis": dict(automargin=True, title=None),
        "yaxis": dict(automargin=True, title=None),
        "dragmode": False,
    }
    if height:
        layout["height"] = height
    if legend:
        layout["legend"] = dict(orientation="h", yanchor="bottom", y=1.02,
                                xanchor="left", x=0, font=dict(size=10),
                                title=None)
    else:
        layout["showlegend"] = False
    if min_text:
        layout["uniformtext"] = dict(minsize=min_text, mode="hide")

    try:
        fig.update_layout(**layout)
    except Exception:
        # Treemaps/pies have no cartesian axes; retry without them.
        layout.pop("xaxis", None)
        layout.pop("yaxis", None)
        try:
            fig.update_layout(**layout)
        except Exception:
            return fig

    # Pie/donut slice labels default to following the slice angle, so on a
    # narrow canvas the thin slices print their labels sideways and run them
    # over the chart edge (measured on Portfolio Summary: "Energy 4.53%" set
    # vertically and clipped). Horizontal is always readable; uniformtext above
    # then hides the ones that no longer fit rather than shrinking them.
    try:
        for tr in fig.data:
            if getattr(tr, "type", "") == "pie":
                tr.insidetextorientation = "horizontal"
    except Exception:
        pass

    if tick_chars:
        def _clip(v):
            t = str(v)
            return t if len(t) <= tick_chars else t[: tick_chars - 1] + "…"
        try:
            for axis in ("xaxis", "yaxis"):
                vals = getattr(fig.layout, axis).ticktext
                if vals:
                    fig.update_layout(**{axis: dict(
                        ticktext=[_clip(v) for v in vals])})
        except Exception:
            pass
        # Category axes usually carry their labels on the traces instead.
        try:
            for tr in fig.data:
                for attr in ("y", "x", "labels"):
                    vals = getattr(tr, attr, None)
                    if vals is not None and len(vals) and isinstance(vals[0], str):
                        setattr(tr, attr, [_clip(v) for v in vals])
                        break
        except Exception:
            pass
    return fig


_CHART_CONFIG = {
    "displayModeBar": False,
    "scrollZoom": False,
    "responsive": True,
    "doubleClick": False,
}


def show_chart(fig, *, key: str | None = None, height: int | None = None,
               legend: bool = True, min_text: int = 9, tick_chars: int = 0):
    """``mobile_chart`` + ``st.plotly_chart`` with the modebar off.

    One call so no page has to remember the config dict — the modebar
    reappearing over the data was the single most common chart complaint."""
    import streamlit as st
    fig = mobile_chart(fig, height=height, legend=legend,
                       min_text=min_text, tick_chars=tick_chars)
    st.plotly_chart(fig, use_container_width=True, key=key,
                    config=_CHART_CONFIG)


# ═══════════════════════════════════════════════════════════════════════════
# BOTTOM NAVIGATION  (v7.16)
# ═══════════════════════════════════════════════════════════════════════════
# The sidebar lists 24 pages in five groups. On a phone that is a drawer you
# must open, scroll and read before you can go anywhere, so the four screens
# actually used day to day cost the same effort as the twenty that are not.
# This is the standard phone answer: a fixed bar with the few real
# destinations, always one tap away. Everything else stays in the sidebar,
# which Streamlit's own header button still opens.
#
# Plain anchors rather than st.page_link because a fixed bar has to be ONE
# element — Streamlit wraps every widget in its own container, so a row of
# page_links cannot be positioned as a unit. The hrefs are the same URLs
# st.navigation registers, so they resolve identically.

_NAV_ITEMS = [
    ("Home",      "/",                   "M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"),
    ("Portfolio", "/Portfolio_Dashboard", "M4 19V9h4v10zm6 0V5h4v14zm6 0v-7h4v7z"),
    ("Research",  "/Research_Hub",       "M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14m9 16-4.5-4.5"),
    ("Risk",      "/Risk_Strategy",      "M12 3 4 6.5v5c0 4.5 3.4 8.7 8 9.5 4.6-.8 8-5 8-9.5v-5z"),
    ("Ask",       "/AI_Chat",            "M4 5h16v10H8l-4 4z"),
]

_BOTTOM_NAV_CSS = """
<style>
.p-nav{display:none;}
@media (max-width:767px){
  .p-nav{
    display:grid;grid-template-columns:repeat(5,1fr);
    position:fixed;left:0;right:0;bottom:0;z-index:999;
    background:var(--background-color,#0e1117);
    border-top:1px solid rgba(128,128,128,0.28);
    padding-bottom:env(safe-area-inset-bottom,0);
    backdrop-filter:blur(10px);
  }
  .p-nav a{
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    gap:2px;min-height:52px;text-decoration:none;color:inherit;opacity:0.62;
    font-size:0.63rem;font-weight:600;letter-spacing:0.02em;padding:6px 2px;
  }
  .p-nav a:hover,.p-nav a:focus-visible{opacity:1;}
  .p-nav a:focus-visible{outline:2px solid var(--p-accent,#0984e3);outline-offset:-2px;}
  .p-nav svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.9;
    stroke-linecap:round;stroke-linejoin:round;}
}
</style>
"""


def bottom_nav() -> None:
    """Fixed bottom navigation bar, phones only.

    Call once per run, after the page body — ``mobile_shell`` already reserves
    the matching bottom padding so the bar never covers the last row."""
    import streamlit as st
    links = "".join(
        f'<a href="{href}" target="_self" aria-label="{label}">'
        f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="{path}"/></svg>'
        f'<span>{label}</span></a>'
        for label, href, path in _NAV_ITEMS
    )
    st.markdown(_BOTTOM_NAV_CSS + f'<nav class="p-nav">{links}</nav>',
                unsafe_allow_html=True)
