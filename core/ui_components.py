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
.ptable-wrap{overflow-x:auto;margin:0 0 0.5rem;}
.ptable{width:100%;border-collapse:collapse;font-size:0.86rem;
  font-variant-numeric:tabular-nums;}
.ptable thead th{text-align:left;padding:8px 10px;border-bottom:2px solid var(--line,#d8dee6);
  font-size:0.72rem;letter-spacing:0.03em;text-transform:uppercase;color:var(--text-color,#31333f);
  opacity:0.65;white-space:nowrap;}
.ptable tbody td{padding:8px 10px;border-bottom:1px solid var(--line,#e6e6e6);white-space:nowrap;}
.ptable tbody td.ptable-title{font-weight:600;}
@media (max-width:767px){
  .ptable-wrap{overflow-x:visible;}
  .ptable, .ptable tbody, .ptable tr, .ptable td{display:block;width:100%;}
  .ptable thead{position:absolute;left:-9999px;}
  .ptable tr{border:1px solid var(--line,#d8dee6);border-radius:8px;margin-bottom:10px;
    padding:6px 4px;background:var(--secondary-background-color,#f6f6f6);}
  .ptable tbody td{border:none;border-bottom:1px dashed var(--line,#e0e0e0);
    display:flex;justify-content:space-between;gap:12px;white-space:normal;padding:7px 10px;}
  .ptable tbody td:last-child{border-bottom:none;}
  .ptable tbody td.ptable-title{font-size:1rem;background:transparent;
    border-bottom:1px solid var(--line,#d0d0d0);margin-bottom:2px;}
  .ptable tbody td::before{content:attr(data-label);font-weight:600;opacity:0.6;
    flex:0 0 auto;text-align:left;}
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
