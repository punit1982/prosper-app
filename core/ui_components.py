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
