"""
core/ledger_ui.py — Prosper's design system, v2 ("market ledger").
=================================================================

Replaces the token layer of ``core/ui_components.py``. The component layer
there was never the problem; the *token* layer was — 47 hard-coded hex values
across ``pages/``, 41 distinct font sizes, and no spacing scale at all.

WHAT CHANGED FROM v1, AND WHY
-----------------------------
1. **Light by default, dark on request.** v1 was dark because finance apps are
   dark, which is choosing by category. The owner reads this outdoors in the
   Gulf; under ~10,000 lux a dark ground reflects rather than emits and the
   dimmest token is the first to disappear.

   Both palettes are defined and contrast-verified below. `active_theme()`
   reads the user's choice (Settings -> Appearance, default light) and
   `design_shell()` emits exactly that one, plus `_chrome()` to repaint
   Streamlit's own surfaces — necessary because .streamlit/config.toml is
   static and can only declare one.

   There is deliberately NO `prefers-color-scheme` anywhere. A static config
   cannot follow the OS, so following it in CSS only guarantees the two
   disagree — which is precisely what shipped broken in v7.35: on a phone set
   to dark, `:root:not([data-p-theme="light"])` (0,2,0) outranked the light
   pin (`:root`, 0,1,0) and painted white text onto Streamlit's light chrome.

2. **Rules, not cards.** v1 carried an 18-instance `border-left` severity
   stripe. A ruled list at 1px carries the same grouping, costs no elevation,
   and does not read as a template. Cards survive only where elevation means
   something (the open sheet).

3. **Every pair clears 4.5:1.** Verified, not asserted — see CONTRAST below.
   v1's worst pair was 3.3:1 and its bottom-nav labels were 9.5px.

4. **Drawn icons.** v1 used 190 Unicode glyphs as an icon system while its own
   audit prescribed "one icon set, no emoji in navigation". ``icon()`` is an
   authored 24px set, stroke 1.5, round caps, ``currentColor``.

5. **Nothing below 12px**, and 44px on every tappable thing including pills.

STREAMLIT RULES THIS FILE OBEYS (each cost a real debugging session — see
HANDOFF.md §4):
  * `st.markdown("<div>")` never wraps the widgets that follow. Scope off a
    marker element's following siblings, never by nesting.
  * Never read a Streamlit CSS custom property; `var(--secondary-background-
    color)` is undefined in 1.41 and the light fallback wins on dark ground.
  * `st.columns()` stacks below ~640px with no opt-out. Grids are CSS grids.
  * Widget keys must be unique per render.
  * Anything rendered after `pg.run()` is skipped on the 21 pages that call
    `st.stop()`. Chrome renders before it.

CONTRAST (computed, WCAG 2.1 relative luminance)
  light   paper #F8FAFC   sheet #FFFFFF   sunk #E8ECF1
    ink      19.28  20.17  17.00      up      5.24  5.48  4.62
    ink-2     9.90  10.35   8.73      down    6.18  6.47  5.45
    ink-3     7.24   7.58   6.39      watch   5.38  5.63  4.75
    mark      5.17   5.41   4.56      focus   9.90 10.36  8.73
  dark    paper #0B1120   sheet #111A2B   sunk #0F1626
    ink      17.19  15.89  16.48      up      9.79  9.05  9.39
    ink-2    12.68  11.72  12.16      down    6.81  6.29  6.53
    ink-3     7.34   6.79   7.04      watch  11.28 10.43 10.82
"""

from __future__ import annotations

import html as _html
from typing import Iterable, Mapping, Sequence

# ══════════════════════════════════════════════════════════════════════════
# TOKENS
# ══════════════════════════════════════════════════════════════════════════
# Source: ui-ux-pro-max colours.csv, row "Banking/Traditional Finance" — the
# one verified light-first financial palette in the set. Two deviations, both
# contrast fixes rather than taste: watch #A16207 -> #96590A and mark #64748B
# -> #5D6B80, because the originals measured 4.15:1 and 4.01:1 on --sunk.

TOKENS: dict[str, dict[str, str]] = {
    "light": {
        "paper": "#F8FAFC", "sheet": "#FFFFFF", "sunk": "#E8ECF1",
        "rule": "#E2E8F0", "rule-strong": "#CBD5E1",
        "ink": "#020617", "ink-2": "#334155", "ink-3": "#475569",
        "accent": "#0F172A", "on-accent": "#FFFFFF", "focus": "#1E3A8A",
        "up": "#047857", "down": "#B91C1C", "watch": "#96590A",
        "mark": "#5D6B80",
        "up-wash": "#ECFDF5", "down-wash": "#FEF2F2", "watch-wash": "#FEFCE8",
    },
    "dark": {
        "paper": "#0B1120", "sheet": "#111A2B", "sunk": "#0F1626",
        "rule": "#1E293B", "rule-strong": "#334155",
        "ink": "#F1F5F9", "ink-2": "#CBD5E1", "ink-3": "#94A3B8",
        "accent": "#E2E8F0", "on-accent": "#0B1120", "focus": "#93C5FD",
        "up": "#34D399", "down": "#F87171", "watch": "#FBBF24",
        "mark": "#94A3B8",
        "up-wash": "#062A1E", "down-wash": "#2A1113", "watch-wash": "#2A2008",
    },
}

# 6 steps, real ratios, 12px floor. v1 put four sizes inside 3.5px.
TYPE = {
    "hero": ("32px", "1.05", "600"),
    "xl":   ("21px", "1.15", "600"),
    "lg":   ("17px", "1.25", "600"),
    "md":   ("15px", "1.45", "400"),
    "sm":   ("13px", "1.40", "400"),
    "xs":   ("12px", "1.35", "500"),
}
SPACE = ("4px", "8px", "12px", "16px", "24px", "32px")   # density 8
TAP_MIN = "44px"                                          # HIG / WCAG 2.5.5

_FONT_SANS = ('"IBM Plex Sans", -apple-system, BlinkMacSystemFont, '
              '"Segoe UI", Roboto, sans-serif')
_FONT_MONO = '"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace'

# The one interactive curve. Emil: built-in easings lack the punch that reads
# as intentional; never ease-in on UI, it delays the moment being watched.
_EASE = "cubic-bezier(.23,1,.32,1)"


def _vars(mode: str) -> str:
    return "".join(f"--p-{k}:{v};" for k, v in TOKENS[mode].items())


# ══════════════════════════════════════════════════════════════════════════
# ICONS — authored, 24px box, stroke 1.5, round caps, currentColor.
# ══════════════════════════════════════════════════════════════════════════
_ICONS: dict[str, str] = {
    # A ruled page: what Today is.
    "today": '<rect x="3.75" y="4" width="16.5" height="16" rx="2.25"/>'
             '<path d="M3.75 9.25h16.5M7.75 13.5h8.5M7.75 16.5h5"/>',
    # Ledger rows with right-aligned figures.
    "holdings": '<path d="M4 7h10M17.5 7H20M4 12h11.5M18.5 12H20'
                'M4 17h8M15.5 17H20"/>',
    "ask": '<path d="M20 14.5a2.5 2.5 0 0 1-2.5 2.5H9l-4.5 3.25V6.5'
           'A2.5 2.5 0 0 1 7 4h10.5A2.5 2.5 0 0 1 20 6.5z"/>',
    "activity": '<circle cx="12" cy="12" r="8.25"/><path d="M12 7.25V12l3.1 2"/>',
    "more": '<circle cx="5.5" cy="12" r="1.35" fill="currentColor" stroke="none"/>'
            '<circle cx="12" cy="12" r="1.35" fill="currentColor" stroke="none"/>'
            '<circle cx="18.5" cy="12" r="1.35" fill="currentColor" stroke="none"/>',
    "chevron": '<path d="M9.75 5.5 16.25 12l-6.5 6.5"/>',
    "back": '<path d="M14.25 5.5 7.75 12l6.5 6.5"/>',
    "open": '<path d="M7 17 17 7M9.25 7h7.75v7.75"/>',
    "check": '<path d="M5 12.5 9.75 17.25 19 7"/>',
    "alert": '<path d="M12 4.75 20.75 19.5H3.25z"/><path d="M12 10.25v3.9M12 16.9v.15"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M15.9 15.9 20 20"/>',
    "sort": '<path d="M7 4.5v15M7 19.5l-2.75-2.75M7 19.5l2.75-2.75'
            'M17 19.5v-15M17 4.5l-2.75 2.75M17 4.5l2.75 2.75"/>',
    "star": '<path d="M12 4.6l2.4 4.87 5.37.78-3.885 3.79.917 5.35'
            'L12 16.86l-4.802 2.53.917-5.35L4.23 10.25l5.37-.78z"/>',
}


def icon(name: str, size: int = 20, cls: str = "") -> str:
    """One drawn icon. Returns SVG markup; never a Unicode glyph.

    `aria-hidden` because every call site here pairs the icon with a text
    label — an icon that is the only content of a control gets an explicit
    label from the caller instead.
    """
    body = _ICONS.get(name)
    if body is None:
        raise KeyError(f"no icon {name!r}; have {sorted(_ICONS)}")
    return (f'<svg class="{("p-ic " + cls).strip()}" width="{size}" height="{size}" '
            f'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.5" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{body}</svg>')


# ══════════════════════════════════════════════════════════════════════════
# STYLE
# ══════════════════════════════════════════════════════════════════════════
# Every rule below is scoped to `.stMain`, the CLASS, not
# `[data-testid="stMain"]`. Streamlit renames that testid to
# stAppScrollToBottomContainer on any page carrying a chat input — so on Ask,
# and only on Ask, the entire theme silently did not apply: dark text on a dark
# ground, light widget surfaces, no tap-target floor. The class is stable on
# both. Same specificity (0,1,0), so nothing else shifts.
CSS = f"""<style>
:root{{{_vars("light")}
  --p-ease:{_EASE};
  --p-s1:{SPACE[0]};--p-s2:{SPACE[1]};--p-s3:{SPACE[2]};
  --p-s4:{SPACE[3]};--p-s5:{SPACE[4]};--p-s6:{SPACE[5]};
  --p-sans:{_FONT_SANS};--p-mono:{_FONT_MONO};
}}
/* NO prefers-color-scheme here, deliberately. Streamlit's own chrome is set in
   .streamlit/config.toml, which is static and cannot follow the OS — so
   following it in CSS guarantees the two disagree. That is exactly what broke:
   on a phone set to dark, `:root:not([data-p-theme="light"])` (specificity
   0,2,0) beat the light pin (`:root`, 0,1,0), so the dark palette painted onto
   Streamlit's light chrome and every heading went white-on-white.

   The app now declares its own ground, the user chooses it, and design_shell()
   emits exactly one palette. */

/* A stylesheet is not content, but Streamlit still gives it an element
   container, and the vertical block puts its 1rem gap on both sides of it.
   Measured on every page: a 63px band of nothing between two sections, one
   per CSS-only injection. Collapse any container whose whole payload is a
   <style>. Containers that also carry a marker div keep their own rules. */
[data-testid="stElementContainer"]:has(> [data-testid="stHtml"] > style:only-child),
[data-testid="stElementContainer"]:has(> [data-testid="stMarkdownContainer"] > style:only-child){{
  display:none !important;
}}
/* Streamlit's own chrome. Reclaim the block padding and hide the 32-link
   collapsed sidebar, which otherwise counts against every tap-target audit. */
/* Deliberately NOT setting .stApp background or a global font here. While the
   app is part-converted, repainting the ground would leave every unconverted
   page's hard-coded colours sitting on the wrong surface. The components below
   carry their own ground; the sweep flips the app's later. */
.p-scope{{color:var(--p-ink);}}

/* Reclaim the empty band above the page title. Streamlit's header reserves
   ~3.75rem for a toolbar whose only occupant here is the sidebar toggle and
   the overflow menu, and the app view adds its own top padding underneath it.
   Measured on a 393pt phone: ~130pt from the top of the webview to the first
   character of the page title, of which about half is nothing. The toggle and
   menu stay tappable — the band just stops reserving space it does not use. */
@media (max-width:767px){{
  [data-testid="stHeader"]{{height:2.6rem!important;min-height:2.6rem!important;
    background:transparent!important;}}
  .stMain .block-container{{padding-top:0!important;}}
  [data-testid="stAppViewBlockContainer"]{{padding-top:0!important;}}
}}

/* Browser surfaces. These ship with defaults belonging to no design system,
   and theming them is the cheapest signal a page was built, not assembled. */
::selection{{background:var(--p-focus);color:#fff;}}
.stMain{{caret-color:var(--p-focus);
  scrollbar-color:var(--p-rule-strong) transparent;scrollbar-width:thin;}}
.stMain :focus-visible{{outline:2px solid var(--p-focus);
  outline-offset:2px;border-radius:3px;}}

.p-ic{{flex:none;vertical-align:-.15em;}}
.p-num{{font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1;}}
.p-mono{{font-family:var(--p-mono);font-variant-numeric:tabular-nums;}}

/* ── head ──────────────────────────────────────────────────────────── */
.p-head{{display:flex;align-items:flex-start;justify-content:space-between;
  gap:var(--p-s3);padding:var(--p-s1) 0 var(--p-s3);}}
.p-head .t{{font-size:{TYPE['xl'][0]};line-height:{TYPE['xl'][1]};
  font-weight:600;letter-spacing:-.018em;color:var(--p-ink);}}
.p-head .s{{font-size:{TYPE['sm'][0]};color:var(--p-ink-3);margin-top:2px;}}

/* ── hero. No label above the number: an eyebrow is a hard ban, and the
   descriptive line reads better under the figure anyway. ────────────── */
.p-hero{{padding:var(--p-s2) 0 var(--p-s4);}}
.p-hero .v{{font-size:{TYPE['hero'][0]};line-height:{TYPE['hero'][1]};
  font-weight:600;letter-spacing:-.028em;color:var(--p-ink);
  font-variant-numeric:tabular-nums;}}
.p-hero .d{{font-size:{TYPE['lg'][0]};font-weight:600;margin-top:var(--p-s1);
  font-variant-numeric:tabular-nums;}}
.p-hero .s{{font-size:{TYPE['sm'][0]};color:var(--p-ink-3);margin-top:var(--p-s2);}}
.up{{color:var(--p-up);}} .down{{color:var(--p-down);}}
.watch{{color:var(--p-watch);}} .mark{{color:var(--p-mark);}}
.dim{{color:var(--p-ink-3);}}

/* ── provenance ────────────────────────────────────────────────────── */
.p-prov{{display:flex;flex-wrap:wrap;align-items:center;gap:var(--p-s3);
  font-size:{TYPE['xs'][0]};color:var(--p-ink-3);
  padding:var(--p-s2) 0;border-top:1px solid var(--p-rule);
  border-bottom:1px solid var(--p-rule);}}
.p-prov b{{font-weight:600;color:var(--p-ink-2);font-variant-numeric:tabular-nums;}}
.p-dot{{width:7px;height:7px;border-radius:50%;display:inline-block;
  margin-right:6px;vertical-align:0;}}
.p-dot.live{{background:var(--p-up);}} .p-dot.delayed{{background:var(--p-watch);}}
.p-dot.eod{{background:var(--p-ink-3);}} .p-dot.broker_mark{{background:var(--p-mark);}}
.p-dot.stale_cache,.p-dot.none{{background:var(--p-down);}}

/* ── stat row. CSS grid, because st.columns stacks below ~640px. ────── */
.p-stats{{display:grid;gap:1px;background:var(--p-rule);
  border-block:1px solid var(--p-rule);margin:var(--p-s3) 0;}}
.p-stats.c2{{grid-template-columns:repeat(2,1fr);}}
.p-stats.c3{{grid-template-columns:repeat(3,1fr);}}
.p-stat{{background:var(--p-paper);padding:var(--p-s3) var(--p-s2);}}
/* Any cell left alone on the final row spans it, rather than sitting beside
   a hole. Belt-and-braces with the column stepping in stat_row(). */
.p-stats.c2>.p-stat:last-child:nth-child(2n+1){{grid-column:span 2;}}
.p-stats.c3>.p-stat:last-child:nth-child(3n+1){{grid-column:span 3;}}
.p-stat .k{{font-size:{TYPE['xs'][0]};color:var(--p-ink-3);
  letter-spacing:.04em;text-transform:uppercase;font-weight:600;}}
.p-stat .v{{font-size:{TYPE['lg'][0]};font-weight:600;color:var(--p-ink);
  margin-top:3px;font-variant-numeric:tabular-nums;}}
.p-stat .d{{font-size:{TYPE['xs'][0]};margin-top:2px;
  font-variant-numeric:tabular-nums;}}

/* ── section rule ──────────────────────────────────────────────────── */
.p-sec{{display:flex;align-items:baseline;justify-content:space-between;
  gap:var(--p-s3);margin:var(--p-s5) 0 var(--p-s2);
  padding-bottom:var(--p-s2);border-bottom:1px solid var(--p-rule-strong);}}
.p-sec .t{{font-size:{TYPE['xs'][0]};font-weight:600;letter-spacing:.09em;
  text-transform:uppercase;color:var(--p-ink-2);}}
.p-sec .c{{font-size:{TYPE['xs'][0]};color:var(--p-ink-3);
  font-variant-numeric:tabular-nums;}}

/* ── ledger rows. Two lines, identity left, figures hard right. ─────── */
.p-row{{display:flex;align-items:center;justify-content:space-between;
  gap:var(--p-s3);min-height:{TAP_MIN};padding:var(--p-s3) var(--p-s1);
  border-bottom:1px solid var(--p-rule);
  transition:background-color 150ms ease,transform 120ms var(--p-ease);}}
.p-row .tk{{font-size:{TYPE['md'][0]};font-weight:600;color:var(--p-ink);}}
.p-row .nm{{font-size:{TYPE['sm'][0]};color:var(--p-ink-3);margin-top:1px;}}
.p-row .qt{{font-family:var(--p-mono);font-size:{TYPE['xs'][0]};
  color:var(--p-ink-3);margin-top:3px;font-variant-numeric:tabular-nums;}}
.p-row .r{{text-align:right;flex:none;}}
.p-row .v{{font-size:{TYPE['md'][0]};font-weight:600;color:var(--p-ink);
  font-variant-numeric:tabular-nums;}}
.p-row .c{{font-size:{TYPE['sm'][0]};font-weight:500;margin-top:1px;
  font-variant-numeric:tabular-nums;}}
.p-row .p{{font-size:{TYPE['xs'][0]};color:var(--p-mark);margin-top:2px;}}
.p-row{{align-items:flex-start;}}
.p-row .l{{min-width:0;}}
.p-row .nm{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
/* Second right-hand figure line (unrealized). Same size and weight as the
   day change above it, so the two read as one column of figures. */
.p-row .c2{{font-size:{TYPE['sm'][0]};font-weight:500;margin-top:2px;
  font-variant-numeric:tabular-nums;}}
.p-row .in{{font-size:{TYPE['xs'][0]};color:var(--p-mark);margin-top:3px;}}
.p-grp{{display:flex;align-items:baseline;justify-content:space-between;
  padding:var(--p-s4) var(--p-s1) var(--p-s2);
  border-bottom:2px solid var(--p-ink);}}
.p-grp .g{{font-size:{TYPE['sm'][0]};font-weight:600;color:var(--p-ink);
  letter-spacing:.02em;}}
.p-grp .v{{font-size:{TYPE['xs'][0]};color:var(--p-ink-3);
  font-variant-numeric:tabular-nums;}}

/* ── attention. Ruled rows, severity in a dot and a word — not a stripe,
   not a card. v1 shipped "3 warnings, one visual class". ───────────── */
.p-att{{display:flex;gap:var(--p-s3);padding:var(--p-s3) var(--p-s1);
  border-bottom:1px solid var(--p-rule);min-height:{TAP_MIN};
  transition:background-color 150ms ease,transform 120ms var(--p-ease);}}
.p-att .sev{{flex:none;width:var(--p-s2);padding-top:6px;}}
.p-att .sev i{{display:block;width:8px;height:8px;border-radius:50%;}}
.p-att.r .sev i{{background:var(--p-down);}}
.p-att.a .sev i{{background:var(--p-watch);}}
.p-att.n .sev i{{background:var(--p-mark);}}
.p-att .b{{flex:1;min-width:0;}}
.p-att .t{{font-size:{TYPE['md'][0]};font-weight:600;color:var(--p-ink);
  line-height:1.3;}}
.p-att .w{{font-size:{TYPE['sm'][0]};color:var(--p-ink-2);margin-top:3px;}}
.p-att .m{{font-size:{TYPE['xs'][0]};color:var(--p-ink-3);margin-top:var(--p-s2);}}
.p-att .go{{flex:none;align-self:center;color:var(--p-ink-3);}}

/* ── ranked bars. Direct category and value labels on every bar: the
   chart guidance is explicit that colour alone must not encode. ────── */
.p-bar{{padding:var(--p-s3) var(--p-s1);border-bottom:1px solid var(--p-rule);}}
.p-bar .h{{display:flex;align-items:baseline;justify-content:space-between;
  gap:var(--p-s3);margin-bottom:var(--p-s2);}}
.p-bar .n{{font-size:{TYPE['md'][0]};color:var(--p-ink);font-weight:500;}}
.p-bar .p{{font-size:{TYPE['md'][0]};font-weight:600;color:var(--p-ink);
  font-variant-numeric:tabular-nums;}}
.p-bar .tr{{height:8px;background:var(--p-sunk);border-radius:2px;
  overflow:hidden;}}
.p-bar .fl{{height:100%;background:var(--p-ink-2);border-radius:2px;}}
.p-bar.over .fl{{background:var(--p-watch);}}
.p-bar.hold .fl{{background:var(--p-mark);}}
.p-bar .f{{display:flex;justify-content:space-between;gap:var(--p-s3);
  font-size:{TYPE['xs'][0]};color:var(--p-ink-3);margin-top:var(--p-s2);
  font-variant-numeric:tabular-nums;}}

/* ── key/value + ladder ────────────────────────────────────────────── */
.p-kv{{display:flex;align-items:baseline;justify-content:space-between;
  gap:var(--p-s3);padding:var(--p-s3) var(--p-s1);
  border-bottom:1px solid var(--p-rule);font-size:{TYPE['md'][0]};}}
.p-kv .k{{color:var(--p-ink-2);}}
.p-kv .v{{font-weight:600;color:var(--p-ink);text-align:right;
  font-variant-numeric:tabular-nums;}}
.p-kv.here{{background:var(--p-sunk);}}
.p-kv .note{{font-size:{TYPE['xs'][0]};font-weight:500;color:var(--p-ink-3);
  display:block;margin-top:2px;}}

/* ── read: teaching prose, set below data weight so it never competes ─ */
.p-read{{font-size:{TYPE['sm'][0]};line-height:1.55;color:var(--p-ink-2);
  padding:var(--p-s3) 0;}}
.p-read b{{color:var(--p-ink);font-weight:600;}}

/* ── controls. 44px, always. v1 regressed these to 30px. ───────────── */
.p-btn{{display:inline-flex;align-items:center;justify-content:center;
  gap:var(--p-s2);min-height:{TAP_MIN};padding:0 var(--p-s4);border-radius:6px;
  font-size:{TYPE['sm'][0]};font-weight:600;border:1px solid var(--p-rule-strong);
  background:var(--p-sheet);color:var(--p-ink);cursor:pointer;
  transition:background-color 150ms ease,transform 120ms var(--p-ease);}}
.p-btn.primary{{background:var(--p-accent);color:var(--p-on-accent);
  border-color:var(--p-accent);}}
.p-seg{{display:flex;gap:var(--p-s2);overflow-x:auto;padding:var(--p-s1) 0 var(--p-s3);
  scrollbar-width:none;}}
.p-seg::-webkit-scrollbar{{display:none;}}
.p-seg .s{{display:inline-flex;align-items:center;min-height:{TAP_MIN};
  padding:0 var(--p-s3);border-radius:6px;white-space:nowrap;
  font-size:{TYPE['sm'][0]};font-weight:500;color:var(--p-ink-2);
  border:1px solid var(--p-rule);background:var(--p-sheet);
  transition:background-color 150ms ease,transform 120ms var(--p-ease);}}
.p-seg .s.on{{background:var(--p-accent);color:var(--p-on-accent);
  border-color:var(--p-accent);font-weight:600;}}

/* Press feedback. On a free tier that cold-starts 30-60s this is the only
   signal the tap registered before the server answers. */
@media (hover:hover) and (pointer:fine){{
  .p-row:hover,.p-att:hover,.p-list:hover{{background:var(--p-sunk);}}
  .p-btn:hover,.p-seg .s:hover{{background:var(--p-sunk);}}
  .p-btn.primary:hover,.p-seg .s.on:hover{{background:var(--p-ink-2);}}
}}
.p-row:active,.p-att:active,.p-btn:active,.p-seg .s:active,.p-list:active{{
  transform:scale(.98);}}

/* ── bottom bar ────────────────────────────────────────────────────── */
.p-nav{{position:fixed;left:0;right:0;bottom:0;z-index:90;
  display:grid;grid-template-columns:repeat(5,1fr);
  background:var(--p-sheet);border-top:1px solid var(--p-rule-strong);
  padding-bottom:env(safe-area-inset-bottom,0);}}
.p-nav a{{display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:3px;min-height:{TAP_MIN};padding:var(--p-s2) 0;
  font-size:{TYPE['xs'][0]};font-weight:500;color:var(--p-ink-3);
  text-decoration:none;transition:color 150ms ease;}}
.p-nav a.on{{color:var(--p-ink);font-weight:600;}}
.p-nav a.on .p-ic{{color:var(--p-ink);}}
.p-back{{display:inline-flex;align-items:center;gap:var(--p-s2);
  min-height:{TAP_MIN};font-size:{TYPE['sm'][0]};font-weight:600;
  color:var(--p-ink-2);text-decoration:none;}}

/* ── list rows (More) ──────────────────────────────────────────────── */
.p-list{{display:flex;align-items:center;justify-content:space-between;
  gap:var(--p-s3);min-height:{TAP_MIN};padding:var(--p-s3) var(--p-s1);
  border-bottom:1px solid var(--p-rule);
  transition:background-color 150ms ease,transform 120ms var(--p-ease);}}
.p-list .t{{font-size:{TYPE['md'][0]};font-weight:500;color:var(--p-ink);}}
.p-list .s{{font-size:{TYPE['sm'][0]};color:var(--p-ink-3);margin-top:1px;}}
.p-list .r{{display:flex;align-items:center;gap:var(--p-s2);
  font-size:{TYPE['sm'][0]};color:var(--p-ink-3);text-align:right;
  font-variant-numeric:tabular-nums;}}

/* ── skeleton. The most-seen screen on a spun-down free tier. ──────── */
.p-skel{{border-bottom:1px solid var(--p-rule);padding:var(--p-s3) var(--p-s1);
  min-height:{TAP_MIN};display:flex;justify-content:space-between;
  align-items:center;gap:var(--p-s3);}}
.p-sk{{height:11px;border-radius:3px;background:var(--p-sunk);
  background-image:linear-gradient(90deg,transparent 0,
    color-mix(in srgb,var(--p-rule-strong) 55%,transparent) 50%,transparent 100%);
  background-size:220px 100%;background-repeat:no-repeat;
  animation:p-sheen 1.4s linear infinite;}}
.p-sk+.p-sk{{margin-top:7px;}}
@keyframes p-sheen{{from{{background-position:-220px 0;}}
  to{{background-position:calc(100% + 220px) 0;}}}}

/* ── empty ─────────────────────────────────────────────────────────── */
.p-empty{{padding:var(--p-s6) var(--p-s3);text-align:left;
  border-top:1px solid var(--p-rule);border-bottom:1px solid var(--p-rule);}}
.p-empty .t{{font-size:{TYPE['lg'][0]};font-weight:600;color:var(--p-ink);}}
.p-empty .b{{font-size:{TYPE['sm'][0]};color:var(--p-ink-2);
  margin-top:var(--p-s2);max-width:46ch;line-height:1.55;}}
.p-empty .a{{margin-top:var(--p-s4);}}

/* Reduced motion removes movement, not feedback. A global 0.01ms kill
   would destroy the press signal, which is the one thing carrying the
   server's latency. */
@media (prefers-reduced-motion:reduce){{
  .p-row:active,.p-att:active,.p-btn:active,.p-seg .s:active,
  .p-list:active{{transform:none;}}
  .p-sk{{animation:none;background-image:none;}}
}}
</style>"""


# ══════════════════════════════════════════════════════════════════════════
# CHART COLOURS
# ══════════════════════════════════════════════════════════════════════════
# Plotly cannot read CSS custom properties — it needs literals baked into the
# figure at render time. These expose the token values so charts and CSS stay
# the same colours instead of drifting apart, which is how the app ended up
# with 11 greens and 16 reds.
#
# ACTIVE_THEME is the single place the app's ground is declared. Flip it and
# .streamlit/config.toml together; see design_shell().
ACTIVE_THEME = "light"


def c(name: str) -> str:
    """One token value, as a literal, for a Plotly figure."""
    return TOKENS[ACTIVE_THEME][name]


# A qualitative sequence for categorical charts, ordered so adjacent entries
# stay distinguishable. Semantic tokens deliberately excluded: green and red
# mean gain and loss everywhere else in the app, and a category that happens
# to land on one would read as a verdict.
# Plotly takes literals, not CSS variables, so these have to be swapped in
# Python when the theme changes — design_shell() rebinds them, the same way it
# rebinds ACTIVE_THEME. The light values were the only set that existed, and on
# the dark ground a #1E7A66 line measured 2.1:1 against #0B1120: a chart drawn
# in ink the same weight as the paper.
CHART_SEQUENCES = {
    "light": ["#1E7A66", "#5D6B80", "#96590A", "#2F6F8F", "#7A5C99",
              "#0F766E", "#8A6D3B", "#4B5563", "#1E3A8A", "#6B7280"],
    "dark":  ["#5EEAD4", "#94A3B8", "#FBBF24", "#7DD3FC", "#C4B5FD",
              "#2DD4BF", "#D6BC8A", "#CBD5E1", "#93C5FD", "#A1A1AA"],
}
CHART_SEQUENCE = CHART_SEQUENCES["light"]


# A five-step semantic ramp for verdicts and actions — strong-positive through
# strong-negative. Every step clears 4.5:1 on the light ground, which the old
# material-palette values did not: #00C853 measured 1.9:1 and #4CAF50 2.7:1,
# i.e. effectively invisible as text on white.
VERDICT_RAMPS = {
    "light": {
        "strong_positive": "#065F46",
        "positive":        "#047857",
        "neutral":         "#475569",
        "negative":        "#B45309",
        "strong_negative": "#B91C1C",
    },
    "dark": {
        "strong_positive": "#6EE7B7",
        "positive":        "#34D399",
        "neutral":         "#94A3B8",
        "negative":        "#FBBF24",
        "strong_negative": "#F87171",
    },
}
VERDICT_RAMP = VERDICT_RAMPS["light"]

# Diverging scale for heat maps and treemaps: loss through neutral to gain.
# Ends are darker than the material originals so a tile label stays legible.
DIVERGINGS = {
    "light": ["#B91C1C", "#D97706", "#94A3B8", "#059669", "#065F46"],
    "dark":  ["#F87171", "#FBBF24", "#64748B", "#34D399", "#6EE7B7"],
}
DIVERGING = DIVERGINGS["light"]


def verdict(word: str) -> str:
    """Colour for a rating, action or verdict word. One ramp, so BUY on the
    Deep Dive and Add on the Risk page are the same green."""
    w = (word or "").strip().upper()
    if w in ("STRONG BUY", "STRONG_BUY", "ADD", "ACCUMULATE"):
        return VERDICT_RAMP["strong_positive"]
    if w in ("BUY", "HOLD+", "OVERWEIGHT"):
        return VERDICT_RAMP["positive"]
    if w in ("SELL", "TRIM", "REDUCE", "UNDERWEIGHT"):
        return VERDICT_RAMP["negative"]
    if w in ("STRONG SELL", "STRONG_SELL", "EXIT"):
        return VERDICT_RAMP["strong_negative"]
    return VERDICT_RAMP["neutral"]


def chart_theme(fig, *, height: int | None = None, grid: bool = True):
    """Apply the token palette to a Plotly figure, on either ground.

    Replaces `template="plotly_dark"`, which hard-codes a dark background and
    white tick labels and so renders unreadable the moment the app is light.
    Backgrounds stay transparent so the figure sits on whatever surface the
    page provides.
    """
    line = "rgba(128,128,128,0.28)"          # reads on either ground — §4 rule 2
    fig.update_layout(
        template="plotly_white" if ACTIVE_THEME == "light" else "plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=c("ink-2"), size=11),
        legend=dict(font=dict(color=c("ink-2"), size=10)),
        **({"height": height} if height else {}),
    )
    fig.update_xaxes(gridcolor=line, zerolinecolor=line, linecolor=line,
                     showgrid=grid, tickfont=dict(color=c("ink-3")))
    fig.update_yaxes(gridcolor=line, zerolinecolor=line, linecolor=line,
                     showgrid=grid, tickfont=dict(color=c("ink-3")))
    return fig


# ══════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════
def _e(v) -> str:
    return _html.escape(str(v), quote=True)


def _dir(v) -> str:
    """up / down / '' — never colour by sign alone; callers pair with a sign."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return "up" if f > 0 else "down" if f < 0 else ""


_SYMBOL_CCY = {"$", "£", "€", "¥", "₹", "﷼"}


def _ccy(currency: str) -> str:
    """A symbol binds to its number; an ISO code takes a space.
    '$184.2K' and 'AED 7.81' — not '$ 184.2K', which is what v1 emitted."""
    if not currency:
        return ""
    return currency if currency in _SYMBOL_CCY else currency + "\u00a0"


def fmt_compact(value, currency: str = "", *, decimals: int = 1) -> str:
    """2,417,140 -> '2.4M'. Rounding behaviour unchanged from ui_components —
    callers depend on it; only the currency spacing is fixed."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    sign, a, c = ("\u2212" if v < 0 else ""), abs(float(value)), _ccy(currency)
    for cut, sfx in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= cut:
            body = f"{a / cut:,.{decimals}f}".rstrip("0").rstrip(".")
            return f"{sign}{c}{body}{sfx}"
    # Below 1,000 keep two decimals. ui_components' version rounded here, which
    # turned a 7.81 AED share price into "AED 8" — invisible while the helper
    # only ever saw portfolio-scale figures, wrong the moment it sees a price.
    body = f"{a:,.2f}" if a >= 1 else f"{a:,.4f}".rstrip("0")
    return f"{sign}{c}{body}"


def money(amount, pct=None, currency: str = "", *, compact: bool = True) -> str:
    """Amount and percent, always together, correctly signed.

    A percentage without its money is not a decision: '-4.2%' says nothing,
    '-4.2%  -$4,120' says whether to care. ~40 hand-written call sites in
    pages/ emit the percent alone; this is the one that does not.
    """
    if amount is None:
        return '<span class="dim">\u2014</span>'
    a = float(amount)
    sign = "+" if a > 0 else "\u2212" if a < 0 else ""
    # A day change is a decision-grade figure and deserves its digits:
    # "\u2212$4,120" tells you whether to care, "\u2212$4.1K" does not. Abbreviate only
    # once the exact digits stop being actionable.
    exact = not compact or abs(a) < 10_000
    body = (f"{_ccy(currency)}{abs(a):,.0f}" if exact
            else fmt_compact(abs(a), currency))
    out = f'<span class="{_dir(a)} p-num">{sign}{_e(body)}'
    if pct is not None:
        p = float(pct)
        psign = "+" if p > 0 else "\u2212" if p < 0 else ""
        out += f'&nbsp;&nbsp;{psign}{abs(p):.2f}%'
    return out + "</span>"


# ══════════════════════════════════════════════════════════════════════════
# COMPONENTS — every one returns HTML so it is unit-testable without
# Streamlit; the st_* wrappers at the bottom render them.
# ══════════════════════════════════════════════════════════════════════════
def page_head(title: str, sub: str = "", *, back_to: str = "", back_label: str = "") -> str:
    """Title, one line of context, and — new in v2 — a return path.

    Five of v1's eleven destinations were not tabs and none drew a way back;
    the bar lit 'More' while the user stood on Risk.
    """
    out = ""
    if back_to:
        out += (f'<a class="p-back" href="{_e(back_to)}">{icon("back", 18)}'
                f'{_e(back_label or "Back")}</a>')
    out += (f'<div class="p-head"><div><div class="t">{_e(title)}</div>'
            f'{f"<div class=s>{_e(sub)}</div>" if sub else ""}</div>'
            f'<div style="display:flex;gap:12px;color:var(--p-ink-3)">'
            f'{icon("search")}</div></div>')
    return out


def hero(value: str, delta: str = "", delta_value=None, sub: str = "",
         title: str = "") -> str:
    """The one figure the page exists for. No label above it — a kicker over
    a heading is a hard ban, and the descriptive line reads better below."""
    out = (f'<div class="p-hero"><div class="v" title="{_e(title or value)}">'
           f'{_e(value)}</div>')
    if delta:
        out += f'<div class="d {_dir(delta_value)}">{_e(delta)}</div>'
    if sub:
        out += f'<div class="s">{_e(sub)}</div>'
    return out + "</div>"


_PROV_LABEL = {"live": "live", "delayed": "delayed", "eod": "end of day",
               "broker_mark": "broker mark", "stale_cache": "stale", "none": "unpriced"}


def provenance(counts: Mapping[str, int] | str, *, age: str = "") -> str:
    """Data freshness as content, not as an exception.

    Phase 1 put `source` / `latency` / `asof` on every Quote and a class on
    every cache row. Nothing in the app displays any of it. This is the
    cheapest trust win available and it is why the six unpriced lines stop
    being a silent fallback.
    """
    if isinstance(counts, str):
        parts = [f'<span><i class="p-dot {_e(counts)}"></i>'
                 f'{_PROV_LABEL.get(counts, _e(counts))}</span>']
    else:
        parts = [f'<span><i class="p-dot {_e(k)}"></i><b>{v}</b> '
                 f'{_PROV_LABEL.get(k, _e(k))}</span>'
                 for k, v in counts.items() if v]
    if age:
        parts.append(f'<span style="margin-left:auto">{_e(age)}</span>')
    return f'<div class="p-prov">{"".join(parts)}</div>'


def chip(cls: str, latency_ms: int | None = None, source: str = "") -> str:
    """Per-row provenance. `broker_mark` is deliberately colourless: a mark
    is a valuation, not a price, and colouring it would imply otherwise."""
    bits = [_PROV_LABEL.get(cls, cls)]
    if source:
        bits.append(source)
    if latency_ms is not None:
        bits.append(f"{latency_ms}ms")
    return f'<span class="p">{_e(" · ".join(bits))}</span>'


def stat_row(stats: Sequence[tuple], *, columns: int = 3) -> str:
    """A row of KPIs that stays a row at 375px.

    v2 change (§12 P3-2): cells whose value is '—', None or '' are DROPPED
    before layout. A two-cell grid beats a three-cell grid with a hole, and
    fixing it in the component fixes every caller at once.
    """
    live = [s for s in stats if s[1] not in (None, "", "—")]
    if not live:
        return ""
    # Never leave a single cell alone on the last row. 4 items in a 3-column
    # grid renders 3 + 1, and the orphan reads as a rendering fault — which is
    # exactly what "CURRENCIES 9" beside an empty cell looked like on a phone.
    # Step the column count down until the rows divide evenly.
    n = max(2, min(3, min(columns, len(live))))
    while n > 2 and len(live) % n == 1:
        n -= 1
    cells = []
    for s in live:
        label, value = s[0], s[1]
        delta = s[2] if len(s) > 2 else ""
        dval = s[3] if len(s) > 3 else None
        c = (f'<div class="p-stat"><div class="k">{_e(label)}</div>'
             f'<div class="v" title="{_e(value)}">{_e(value)}</div>')
        if delta:
            c += f'<div class="d {_dir(dval)}">{_e(delta)}</div>'
        cells.append(c + "</div>")
    return f'<div class="p-stats c{n}">{"".join(cells)}</div>'


def section(title: str, count: str = "") -> str:
    """A ruled section head. Kept under 20 characters — uppercase past that
    measurably slows reading, and the detector flags it."""
    if len(title) > 20:
        raise ValueError(f"section title {title!r} is {len(title)} chars; "
                         "uppercase past 20 hurts legibility — shorten it")
    return (f'<div class="p-sec"><span class="t">{_e(title)}</span>'
            f'{f"<span class=c>{_e(count)}</span>" if count else ""}</div>')


def group(label: str, value: str = "") -> str:
    return (f'<div class="p-grp"><span class="g">{_e(label)}</span>'
            f'<span class="v">{_e(value)}</span></div>')


def ledger_row(ticker: str, name: str, value: str = "", *, qty: str = "",
               change: str = "", change_value=None, prov: str = "",
               unrealized: str = "", unrealized_value=None,
               income: str = "", value_html: str = "") -> str:
    """One position, up to four lines, everything a decision needs.

        LITE                                    USD 9.8K
        LUMENTUM HOLDINGS INC          +USD 973  +11.04%
        135 @ 65.20                  +USD 1,240  +14.62%
        Div 2.1% · ex 12 Sep              live · 191ms

    Figures are right-aligned in one column so the eye scans straight down the
    list instead of hunting across each row — the reason a broker statement is
    set this way, and the reason IBKR's positions table stays readable at this
    density. Lines are omitted when their inputs are absent, so a fund line
    with no cost basis collapses to two rather than showing empty scaffolding.

    `qty` is quantity @ average cost, `unrealized` the open P&L in money and
    percent, `income` the yield and ex-date. All four were asked for and none
    is in _build_stock_table / _build_fund_table today.
    """
    # `value` is ESCAPED — pass plain text. For a pre-rendered figure (money()
    # returns markup) use `value_html`. Passing markup as `value` printed the
    # raw <span> on the Command Center's attribution rows in v7.36; making the
    # two paths explicit is what stops that recurring.
    left = [f'<div class="tk">{_e(ticker)}</div>']
    right = [f'<div class="v">{value_html or _e(value)}</div>']
    if name:
        left.append(f'<div class="nm">{_e(name)}</div>')
    if change:
        right.append(f'<div class="c {_dir(change_value)}">{change}</div>')
    if qty:
        left.append(f'<div class="qt">{_e(qty)}</div>')
    if unrealized:
        right.append(f'<div class="c2 {_dir(unrealized_value)}">{unrealized}</div>')
    if income:
        left.append(f'<div class="in">{_e(income)}</div>')
    if prov:
        right.append(prov)
    return (f'<div class="p-row" role="link" tabindex="0">'
            f'<div class="l">{"".join(left)}</div>'
            f'<div class="r">{"".join(right)}</div></div>')


def attention(items: Sequence[Mapping], *, limit: int = 3) -> str:
    """The decision queue. Ruled rows; severity is a dot plus the reason.

    v1 drew these as cards with a 3px coloured border-left — the single most
    recognisable AI tell, and a device it used 18 times. The information is
    identical; what changes is that this reads as a ledger rather than a
    template, and it costs no elevation.
    """
    sev = {"critical": "r", "warn": "a", "info": "n"}
    out = []
    for it in items[:limit]:                   # a queue longer than 3 is a list
        level = sev.get(it.get("level", "info"), "n")
        out.append(
            f'<div class="p-att {level}" role="link" tabindex="0">'
            f'<div class="sev"><i></i></div><div class="b">'
            f'<div class="t">{_e(it["title"])}</div>'
            + (f'<div class="w">{_e(it["why"])}</div>' if it.get("why") else "")
            + (f'<div class="m">{_e(it["source"])}</div>' if it.get("source") else "")
            + '</div>'
            f'<div class="go">{icon("chevron", 18)}</div></div>')
    # Never silently drop an alert: say how many are not shown.
    if len(items) > limit:
        n = len(items) - limit
        out.append(f'<div class="p-att n"><div class="sev"></div><div class="b">'
                   f'<div class="w">{n} more, lower priority</div></div></div>')
    return "".join(out)


def ranked_bars(items: Sequence[Mapping], *, limit: int = 8) -> str:
    """Ordered horizontal bars — the replacement for all 8 Plotly donuts.

    Sorted here, in the component, rather than trusting the caller: v1 shipped
    its flagship example mis-sorted (26.4, 18.1, 13.6, 11.2, 9.4, 8.0, 9.0,
    4.3) while selling the component on 'sorts correctly'.

    Chart guidance is explicit that category must not be encoded by colour
    alone, so every bar carries its own name, percent, money and count.
    """
    rows = sorted(items, key=lambda r: float(r["pct"]), reverse=True)[:limit]
    if not rows:
        return ""
    top = float(rows[0]["pct"]) or 1.0
    out = []
    for r in rows:
        pct = float(r["pct"])
        cls = r.get("state", "")
        out.append(
            f'<div class="p-bar {cls}"><div class="h">'
            f'<span class="n">{_e(r["name"])}</span>'
            f'<span class="p">{pct:.1f}%</span></div>'
            f'<div class="tr"><div class="fl" style="width:{pct / top * 100:.1f}%"></div></div>'
            f'<div class="f"><span>{_e(r.get("meta", ""))}</span>'
            + (f'<span>{r["right"]}</span>' if r.get("right") else "")
            + '</div></div>')
    return "".join(out)


def kv(key: str, value: str, *, here: bool = False, note: str = "") -> str:
    v = f'{value}{f"<span class=note>{_e(note)}</span>" if note else ""}'
    return (f'<div class="p-kv{" here" if here else ""}">'
            f'<span class="k">{_e(key)}</span><span class="v">{v}</span></div>')


def read(body_html: str) -> str:
    """Teaching prose, set below data weight so it never competes with figures."""
    return f'<div class="p-read">{body_html}</div>'


def list_row(title: str, sub: str = "", right: str = "") -> str:
    return (f'<div class="p-list" role="link" tabindex="0"><div>'
            f'<div class="t">{_e(title)}</div>'
            f'{f"<div class=s>{_e(sub)}</div>" if sub else ""}</div>'
            f'<div class="r">{right}{icon("chevron", 18)}</div></div>')


def skeleton(rows: int = 5) -> str:
    """The loading state. On a free-tier instance that spins down, this is
    genuinely the most-seen screen in the product — and it did not exist."""
    out = []
    for i in range(rows):
        w1, w2 = 54 - (i % 3) * 9, 30 - (i % 2) * 6
        out.append(
            f'<div class="p-skel"><div style="flex:1">'
            f'<div class="p-sk" style="width:{w1}%"></div>'
            f'<div class="p-sk" style="width:{w2}%"></div></div>'
            f'<div style="width:76px"><div class="p-sk"></div>'
            f'<div class="p-sk" style="width:60%;margin-left:auto"></div></div></div>')
    return "".join(out)


def empty(title: str, body: str, action: str = "") -> str:
    """The healthy state, designed. On ~340 days a year nothing needs a
    decision, which makes this Today's modal state, not its edge case."""
    return (f'<div class="p-empty"><div class="t">{_e(title)}</div>'
            f'<div class="b">{_e(body)}</div>'
            f'{f"<div class=a>{action}</div>" if action else ""}</div>')


def button(label: str, *, primary: bool = False, icon_name: str = "") -> str:
    return (f'<button class="p-btn{" primary" if primary else ""}" type="button">'
            f'{_e(label)}{icon(icon_name, 18) if icon_name else ""}</button>')


def segment(options: Sequence[str], active: str) -> str:
    return ('<div class="p-seg" role="tablist">' + "".join(
        f'<span class="s{" on" if o == active else ""}" role="tab" '
        f'tabindex="0" aria-selected="{"true" if o == active else "false"}">'
        f'{_e(o)}</span>' for o in options) + "</div>")


NAV = (("today", "Today", "views/00_Command_Center.py"),
       ("holdings", "Holdings", "views/2_Portfolio_Dashboard.py"),
       ("ask", "Ask", "views/24_AI_Chat.py"),
       ("activity", "Activity", "views/9_Activity.py"),
       ("more", "More", "views/0_Settings.py"))


def nav(active: str = "today") -> str:
    """Five slots, drawn icons, 12px labels, 44px targets, real active state.

    v1's bar used Unicode glyphs at 9.5px and lit the wrong slot on five of
    eleven screens.
    """
    return '<nav class="p-nav" aria-label="Primary">' + "".join(
        f'<a class="{"on" if k == active else ""}" href="#{k}"'
        f'{" aria-current=page" if k == active else ""}>'
        f'{icon(k, 22)}<span>{lbl}</span></a>' for k, lbl, _ in NAV) + "</nav>"


# ══════════════════════════════════════════════════════════════════════════
# STREAMLIT WRAPPERS
# ══════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════
# THEME
# ══════════════════════════════════════════════════════════════════════════
# The app declares its own ground and the user chooses it. .streamlit/config.toml
# is static and sets Streamlit's chrome to the LIGHT palette; when the user picks
# dark, _chrome() repaints that chrome from the tokens so the two agree. This is
# why there is no prefers-color-scheme anywhere: a static config cannot follow
# the OS, so following it in CSS only guarantees a mismatch.
THEMES = ("light", "dark")


def active_theme() -> str:
    """The user's choice, defaulting to light. Read fresh each run so the
    toggle takes effect on the very next rerun."""
    try:
        from core.settings import SETTINGS
        t = str(SETTINGS.get("pref_theme", "light")).lower()
        return t if t in THEMES else "light"
    except Exception:
        return "light"


def _chrome(mode: str) -> str:
    """Repaint Streamlit's own surfaces from the token set.

    config.toml can only declare one palette, so everything Streamlit draws
    itself — the app background, headers, inputs, expanders, tables — has to be
    re-coloured here when the user picks the other one. Scoped to the widgets
    that actually carry a background, rather than a blanket `* {color:...}`,
    which would also repaint the semantic up/down figures.
    """
    t = TOKENS[mode]
    # `:root:root` is specificity (0,2,0); the base sheet declares the light
    # tokens at `:root` (0,1,0). Winning on SPECIFICITY rather than on source
    # order makes this immune to the sheet being emitted again later — which
    # is what a loading skeleton, a fragment or a future caller will eventually
    # do, and what turned the bottom bar white and the page title invisible in
    # dark mode. Do not lower this to a single :root.
    return f"""<style>
:root:root{{{_vars(mode)}}}
.stApp,[data-testid="stAppViewContainer"],[data-testid="stHeader"]{{
  background:{t['paper']}!important;}}
[data-testid="stSidebar"]{{background:{t['sheet']}!important;}}
/* The sidebar carried ONLY a background override, so its text kept
   Streamlit's static config colour — measured 30 elements at 1.1:1 in dark
   mode, i.e. the whole navigation was invisible. Links, labels, headings and
   the collapse control all need the token set. */
[data-testid="stSidebar"],
[data-testid="stSidebar"] *:not(svg):not(path){{color:{t['ink-2']}!important;}}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] *{{color:{t['ink-2']}!important;}}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"][aria-current] *{{
  color:{t['ink']}!important;}}
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,[data-testid="stSidebar"] summary{{color:{t['ink']}!important;}}
[data-testid="stSidebar"] hr{{border-color:{t['rule']}!important;}}
[data-testid="stSidebarNav"] li a{{color:{t['ink-2']}!important;}}
/* The sidebar's WIDGETS still painted themselves from the static config
   palette: the text input, the select and the secondary buttons all sat at
   #F8FAFC — white boxes carrying dark-mode text, on a dark ground. Colour
   alone was never enough; the surfaces have to move too. */
[data-testid="stSidebar"] [data-testid="stTextInputRootElement"],
[data-testid="stSidebar"] [data-baseweb="input"],
[data-testid="stSidebar"] [data-baseweb="base-input"],
[data-testid="stSidebar"] [data-baseweb="select"]>div,
[data-testid="stSidebar"] [data-baseweb="popover"] li,
[data-testid="stSidebar"] [role="listbox"],
[data-testid="stSidebar"] input,[data-testid="stSidebar"] textarea{{
  background:{t['sunk']}!important;color:{t['ink']}!important;
  border-color:{t['rule-strong']}!important;}}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] .stButton button,
[data-testid="stSidebar"] [data-testid="stButton"] button{{
  background:{t['sheet']}!important;border:1px solid {t['rule-strong']}!important;}}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] div,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] p{{
  color:{t['ink']}!important;}}
[data-testid="stSidebar"] input::placeholder,
[data-testid="stSidebar"] textarea::placeholder{{color:{t['ink-3']}!important;opacity:1;}}
.stMain [data-testid="stTextInputRootElement"],
.stMain [data-baseweb="base-input"]{{
  background:{t['sheet']}!important;border-color:{t['rule-strong']}!important;}}
.stMain,.stMain p,.stMain li,
.stMain h1,.stMain h2,.stMain h3,
.stMain h4,.stMain label,
.stMain [data-testid="stMarkdownContainer"]{{color:{t['ink']};}}
.stMain .stTextInput input,.stMain .stNumberInput input,
.stMain .stTextArea textarea,.stMain [data-baseweb="select"]>div{{
  background:{t['sheet']}!important;color:{t['ink']}!important;
  border-color:{t['rule-strong']}!important;}}
.stMain [data-testid="stExpander"],
.stMain [data-testid="stExpander"] details{{
  background:{t['sheet']}!important;border-color:{t['rule']}!important;}}
.stMain [data-testid="stDataFrame"]{{background:{t['sheet']}!important;}}
.stMain hr{{border-color:{t['rule']}!important;}}
.stMain code{{background:{t['sunk']}!important;color:{t['ink']}!important;}}

/* ── Streamlit's own controls ────────────────────────────────────────────
   These carry their own backgrounds from the static config.toml palette, so
   under the other theme they stay the wrong colour. The segmented controls
   used across Holdings, Risk, Income, Security and Activity rendered as WHITE
   pills with white labels in dark mode — the control was unreadable, not just
   off-brand. Placeholders were invisible for the same reason. */
.stMain [data-baseweb="segmented-control"],
.stMain [data-testid="stButtonGroup"]{{background:transparent!important;}}
.stMain [data-testid="stButtonGroup"] button,
.stMain [data-baseweb="segmented-control"] button{{
  background:{t['sheet']}!important;color:{t['ink-2']}!important;
  border:1px solid {t['rule-strong']}!important;}}
.stMain [data-testid="stButtonGroup"] button[aria-checked="true"],
.stMain [data-testid="stButtonGroup"] button[aria-selected="true"],
.stMain [data-testid="stButtonGroup"] button[kind="segmented_controlActive"]{{
  background:{t['accent']}!important;color:{t['on-accent']}!important;
  border-color:{t['accent']}!important;}}
.stMain .stButton button,
.stMain [data-testid="stButton"] button,
.stMain .stButton button *,
.stMain [data-testid="stButton"] button *{{color:{t['ink']}!important;}}
.stMain .stButton button,
.stMain [data-testid="stButton"] button{{
  background:{t['sheet']}!important;border:1px solid {t['rule-strong']}!important;}}
.stMain .stButton button[kind="primary"],
.stMain [data-testid="stButton"] button[kind="primary"]{{
  background:{t['accent']}!important;border-color:{t['accent']}!important;}}
.stMain .stButton button[kind="primary"],
.stMain [data-testid="stButton"] button[kind="primary"],
.stMain .stButton button[kind="primary"] *,
.stMain [data-testid="stButton"] button[kind="primary"] *{{
  color:{t['on-accent']}!important;}}
/* Streamlit names its own buttons stBaseButton-<kind>. The rules above match
   on .stButton / kind=, which the segmented control and the primary button do
   not carry — both kept painting themselves #E2E8F0 from the static config
   palette, so the SELECTED currency pill was a light box holding light text at
   1.13:1. Match the testid prefix and there is nothing left to miss. */
/* st.link_button is an <a data-testid="stBaseLinkButton-secondary">, not a
   <button>, so none of the button rules reached it: Activity drew 30 "Read →"
   links at 1.1:1. Link buttons and buttons are the same control to a reader. */
.stMain [data-testid^="stBaseLinkButton-"],
.stMain [data-testid^="stBaseButton-"]{{
  background:{t['sheet']}!important;border:1px solid {t['rule-strong']}!important;
  color:{t['ink']}!important;}}
.stMain [data-testid="stBaseButton-primary"],
.stMain [data-testid="stBaseButton-segmented_controlActive"]{{
  background:{t['accent']}!important;border-color:{t['accent']}!important;}}
.stMain [data-testid="stBaseButton-primary"],
.stMain [data-testid="stBaseButton-primary"] p,
.stMain [data-testid="stBaseButton-primary"] div,
.stMain [data-testid="stBaseButton-segmented_controlActive"],
.stMain [data-testid="stBaseButton-segmented_controlActive"] p,
.stMain [data-testid="stBaseButton-segmented_controlActive"] div{{
  color:{t['on-accent']}!important;}}
.stMain [data-testid^="stBaseLinkButton-"],
.stMain [data-testid^="stBaseLinkButton-"] p,
.stMain [data-testid^="stBaseLinkButton-"] div{{color:{t['ink']}!important;}}
/* The remaining widgets Streamlit paints from the static config palette. Each
   was found by walking the live DOM for a light surface or a dark glyph on the
   dark ground, not by reading the source. */
.stMain [data-testid="stSliderThumbValue"],
.stMain [data-testid="stTickBarMin"],
.stMain [data-testid="stTickBarMax"]{{color:{t['ink-2']}!important;}}
.stMain [data-testid="stSliderTickBar"]{{background:transparent!important;}}
.stMain pre,.stMain [data-testid="stCode"],.stMain .stCode pre{{
  background:{t['sunk']}!important;color:{t['ink']}!important;}}
.stMain [data-baseweb="tag"]{{
  background:{t['sunk']}!important;color:{t['ink']}!important;}}
.stMain [data-testid="stFileUploaderDropzone"],
.stMain [data-testid="stFileUploaderFile"]{{
  background:{t['sunk']}!important;border-color:{t['rule-strong']}!important;}}
/* The dropzone's own copy ("Drag and drop file here", the size limit) keeps
   Streamlit's static textColor — measured 1.12:1 on Connections. */
.stMain [data-testid="stFileUploaderDropzone"] span,
.stMain [data-testid="stFileUploaderDropzone"] div,
.stMain [data-testid="stFileUploaderDropzoneInstructions"] span,
.stMain [data-testid="stFileUploaderDropzoneInstructions"] small,
.stMain [data-testid="stFileUploaderFile"] span,
.stMain [data-testid="stFileUploaderFile"] div{{color:{t['ink-2']}!important;}}
.stMain [data-testid="stAlertContainer"],
.stMain [data-testid="stAlertContentInfo"],
.stMain [data-testid="stAlertContentSuccess"],
.stMain [data-testid="stAlertContentWarning"],
.stMain [data-testid="stAlertContentError"]{{color:{t['ink']}!important;}}
.stMain [data-testid="stNotification"],
.stMain [data-testid="stAlert"] > div{{
  background:{t['sunk']}!important;color:{t['ink']}!important;}}
/* A button narrower than its label must not break the word. Streamlit's own
   rules allow an intra-word break, which turned "Refresh" in a 1/8 column into
   a 190px vertical tower of single letters. Wrap between words, never inside
   one — the button gets taller by a line instead of by seven. */
.stMain button p,.stMain button div,.stMain a[data-testid^="stBaseLinkButton"] p{{
  overflow-wrap:normal!important;word-break:normal!important;}}
/* The dataframe hover toolbar floats a white 79x44 panel over a dark table. */
.stMain [data-testid="stElementToolbar"],
.stMain [data-testid="stElementToolbar"] > div,
.stMain [data-testid="stElementToolbarButton"]{{
  background:{t['sheet']}!important;color:{t['ink-2']}!important;
  border-color:{t['rule']}!important;}}
/* An unchecked box or radio is a pure-white 16px square on a dark page. Only
   the UNCHECKED state is repainted — the checked one carries the accent fill
   and its tick, and must keep them. */
.stMain label[data-baseweb="checkbox"]:has(input:not(:checked))>span:first-child,
.stMain label[data-baseweb="radio"]:has(input:not(:checked))>div,
.stMain label[data-baseweb="radio"]:has(input:not(:checked))>div>div{{
  background:{t['sunk']}!important;border-color:{t['rule-strong']}!important;}}
.stMain input::placeholder,
.stMain textarea::placeholder{{color:{t['ink-3']}!important;opacity:1;}}
.stMain [data-baseweb="popover"] li,
.stMain [role="listbox"]{{
  background:{t['sheet']}!important;color:{t['ink']}!important;}}
.stMain [data-testid="stCheckbox"] label,
.stMain [data-testid="stRadio"] label,
.stMain [data-testid="stCaptionContainer"]{{color:{t['ink-2']}!important;}}
.stMain [data-baseweb="tab"]{{color:{t['ink-2']}!important;}}
.stMain [data-testid="stMetricValue"]{{color:{t['ink']}!important;}}
.stMain [data-testid="stMetricLabel"]{{color:{t['ink-3']}!important;}}
/* Streamlit paints its OWN text colour from config.toml, which is static and
   therefore the light value. Anything the selectors above do not name keeps it
   — which in dark mode meant the bottom bar's links and Material icon glyphs
   rendered in near-black on the dark ground. Page links and icons are the two
   that carry text and were missed. */
/* Streamlit ships Source Sans Pro and applies it to containers this sheet
   does not name, so two faces rendered side by side. One family, everywhere. */
.stMain,[data-testid="stSidebar"],
.stMain *:not([class*="material"]):not([data-testid="stIconMaterial"]),
[data-testid="stSidebar"] *:not([class*="material"]):not([data-testid="stIconMaterial"]){{
  font-family:{_FONT_SANS};}}
.stMain a[data-testid="stPageLink-NavLink"],
.stMain a[data-testid="stPageLink-NavLink"] *,
.stMain span[data-testid="stIconMaterial"],
.stMain [data-testid="stMarkdownContainer"] a{{
  color:{t['ink-2']}!important;}}
.stMain a[data-testid="stPageLink-NavLink"][aria-current],
.stMain a[data-testid="stPageLink-NavLink"][aria-current] *{{
  color:{t['ink']}!important;}}
/* Charts inherit the page ground, so the plot area must not stay white. */
.stMain .js-plotly-plot .plotly .main-svg{{background:transparent!important;}}
</style>"""


def keep_row() -> None:
    """Keep the NEXT st.columns() horizontal on a phone.

    HANDOFF §4 rule 4 records that st.columns stacks below ~640px "with no
    per-row opt-out". There is no Python opt-out, but there is a CSS one, and
    without it a `st.columns([7, 1])` header spends two full-height rows on a
    caption and a single icon button. Scoped off a marker's next sibling, the
    same way every other row-level rule in this app is.
    """
    _emit(
        "<style>@media (max-width:767px){"
        '[data-testid="stElementContainer"]:has(.p-keeprow){display:none;}'
        '[data-testid="stElementContainer"]:has(.p-keeprow)+[data-testid="stHorizontalBlock"]{'
        "flex-wrap:nowrap!important;align-items:center!important;gap:8px!important;}"
        '[data-testid="stElementContainer"]:has(.p-keeprow)+[data-testid="stHorizontalBlock"]'
        '>[data-testid="stColumn"]{min-width:0!important;}'
        "}</style><div class='p-keeprow'></div>"
    )


def _emit(html: str) -> None:
    """Emit raw HTML/CSS WITHOUT Streamlit's Markdown pipeline.

    st.markdown parses its argument as Markdown *before* the HTML reaches the
    browser, and that parser has now mangled this stylesheet twice:

      1. it truncated the block at the first CSS comment (fixed by _min), and
      2. it ate `*` as emphasis — `*:not([class*="material"])` arrived in the
         DOM as ` :not([class`, cutting the sheet dead at that point and
         silently dropping every rule after it, including the bottom-nav icon
         colour that dark mode needs.

    st.html skips the parser entirely and hands the string straight to the same
    DOMPurify sanitiser st.markdown ends at. Anything that is markup, not
    prose, goes through here.
    """
    import streamlit as st
    st.html(html)


def _min(css: str) -> str:
    """Strip CSS comments and leading indentation before emitting.

    st.markdown runs the string through a Markdown pipeline before it reaches
    the DOM, and that pipeline mangles a multi-line <style> containing comment
    blocks — the sheet arrived TRUNCATED at the first comment, silently losing
    every rule after it. Measured in the harness: _chrome() returned 4,605
    bytes and the DOM held 1,457, cut exactly at a `/* ... */`.

    The comments belong in the source, not in the payload, so they are removed
    on the way out. This also stops re-sending several KB of prose on every
    rerun.
    """
    import re as _re
    css = _re.sub(r"/\*.*?\*/", "", css, flags=_re.S)
    return "\n".join(ln.strip() for ln in css.splitlines() if ln.strip())


def shell_css() -> str:
    """The complete stylesheet for the ACTIVE theme: tokens, components and the
    Streamlit chrome repaint, in that order.

    Anything that needs the sheet must use this rather than CSS alone. CSS
    declares the LIGHT tokens on :root — emitting it again after design_shell()
    silently reverts the palette for everything below it, which is what turned
    the bottom bar white and the section labels unreadable in dark mode. Found
    in the preview harness by counting --p-ink-2 declarations in the DOM.
    """
    return _min(CSS) + _min(_chrome(active_theme()))


def design_shell() -> None:
    """Inject the token + component sheet, globally, from app.py — BEFORE
    pg.run(), because 21 of the 24 pages call st.stop() and anything after
    pg.run() never renders on exactly those pages.

    Injected UNCONDITIONALLY. Streamlit rebuilds the DOM from scratch on every
    rerun, so there is no previous run to "already have" the stylesheet from;
    a session-scoped guard skips the injection on every rerun after the first
    and leaves the components rendering as unstyled divs. This function had
    exactly that bug in v7.25 — mobile_shell's own docstring warns about it,
    and it shipped anyway. Do not add a guard here.
    """
    import streamlit as st
    mode = active_theme()
    # ACTIVE_THEME is what the Plotly literals read; keep it in step with the
    # CSS on every run, since both are regenerated per rerun anyway.
    global ACTIVE_THEME, CHART_SEQUENCE, DIVERGING, VERDICT_RAMP
    ACTIVE_THEME = mode
    CHART_SEQUENCE = CHART_SEQUENCES[mode]
    DIVERGING = DIVERGINGS[mode]
    VERDICT_RAMP = VERDICT_RAMPS[mode]
    _emit(_min(CSS) + _min(_chrome(mode)))


def write(*html: str) -> None:
    """Render component output. One call per logical block."""
    _emit("".join(html))
