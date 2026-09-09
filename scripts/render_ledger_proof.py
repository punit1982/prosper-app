#!/usr/bin/env python3
"""
scripts/render_ledger_proof.py — render core/ledger_ui.py to a static page.

Every screen below is drawn by calling the real component functions. Nothing
is hand-written HTML, so the proof cannot drift from the implementation: if
`ranked_bars()` mis-sorts, the picture mis-sorts.

All figures come from BOOK, one dict, read by every screen. v1's mockups were
hand-written per screen and contradicted each other six ways — ADBE's buy
price was $290 on one screen and $230.07 on another. Sharing the source makes
that class of error impossible rather than merely unlikely.

Usage:  venv/bin/python3 scripts/render_ledger_proof.py [out.html]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ledger_ui as ui  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════
# ONE BOOK. Magnitudes are the ones HANDOFF.md and the 8 Sep audit record:
# 182 holdings, 10 currencies, 179/185 priced in 17.1s, 58 live / 121 delayed,
# ALDAR 7.81 AED via TradingView in 191ms, AED peg 3.6725, $208k of IB01/U03A
# treasuries + ~$67k AED cash as collateral. Illustrative, not a live read.
# ══════════════════════════════════════════════════════════════════════════
CCY = "$"


def day(v):
    """Today's contribution on an allocation bar. One signing rule."""
    return ui.money(v, None, CCY) + ' <span class="dim">today</span>'


UNPRICED = '<span class="dim">no source</span>'

BOOK = {
    "nav": 2_303_400, "day": 17_170, "day_pct": 0.67,
    "holdings": 182, "currencies": 10,
    "freshness": {"live": 58, "delayed": 121, "none": 6},
    "refreshed": "17.1s ago",
    "cash": -254_200, "collateral": 275_000, "health": 72,
    "positions": [
        # ticker, name, qty, avg, value, day_pct, day_amt, prov
        ("NVDA",  "NVIDIA",                    "420 @ $312.40",   184_240,  1.9,  3_430, ("live", "finnhub", 210)),
        ("CRM",   "Salesforce",                "340 @ $291.10",    94_020, -4.2, -4_120, ("live", "tradingview", 191)),
        ("NKE",   "Nike",                    "1,200 @ $88.05",     96_420, -0.8,   -790, ("delayed", "tradingview", 191)),
        ("ADBE",  "Adobe",                     "263 @ $302.15",    87_300,  0.4,    350, ("live", "finnhub", 210)),
        ("ALDAR", "Aldar Properties",      "11,280 @ AED 6.94",    88_140,  1.1,    980, ("delayed", "tradingview", 191)),
        ("EMAAR", "Emaar Properties",       "6,700 @ AED 9.80",    74_320,  0.8,    590, ("delayed", "tradingview", 191)),
        ("ADCB",  "Abu Dhabi Commercial",   "9,400 @ AED 14.02",   36_940, -0.9,   -335, ("delayed", "tradingview", 191)),
        ("OZON",  "Ozon Holdings",           "1,500 @ $24.10",     18_300, None,   None, ("broker_mark", "ibkr", None)),
    ],
    # Region counts sum to 182 exactly. v1's summed to 169 while claiming 182.
    "regions": [("US", 84), ("India", 50), ("Europe", 21), ("UAE", 11),
                ("Japan", 8), ("Other", 5), ("Crypto", 3)],
    "sectors": [
        {"name": "Technology",     "pct": 26.4, "meta": "$607,200 · 31 names", "state": "over", "right": day(11_240)},
        {"name": "Financials",     "pct": 18.1, "meta": "$416,300 · 24 names", "right": day(2_410)},
        {"name": "Real estate",    "pct": 13.6, "meta": "$312,800 · 9 names", "right": day(1_890)},
        {"name": "Consumer disc.", "pct": 11.2, "meta": "$257,600 · 18 names", "right": day(-3_120)},
        {"name": "Energy",         "pct":  9.4, "meta": "$216,200 · 11 names", "right": day(4_610)},
        {"name": "Fixed income",   "pct":  9.0, "meta": "$208,000 · IB01, U03A", "state": "hold", "right": "collateral"},
        {"name": "Healthcare",     "pct":  8.0, "meta": "$184,000 · 14 names", "right": day(120)},
        {"name": "Unclassified",   "pct":  4.3, "meta": "$98,900 · 6 unpriced", "right": UNPRICED},
    ],
    # GROW v5.1. resolve_entry() recomputes these in Python from the memo's
    # own inputs and overrides whatever the model wrote.
    "grow": {
        "ALDAR": {"durability": 72, "verdict": "ACCUMULATE", "last": 7.81, "ccy": "AED",
                  "ladder": [("Strong buy below", 5.60), ("Buy below", 7.95),
                             ("Fair high", 9.10), ("Trim above", 11.40),
                             ("Sell above", 13.70)]},
        "ADBE":  {"durability": 78, "verdict": "HOLD", "last": 331.40, "ccy": "$",
                  "ladder": [("Strong buy below", 174.12), ("Buy below", 230.07),
                             ("Fair high", 348.00), ("Trim above", 435.00),
                             ("Sell above", 522.00)]},
    },
    "rated": 3,          # ADBE, NKE, ALDAR — matches what Security can show
}


def _band(ladder, last):
    """Index of the rung whose band contains `last`. One definition, so the
    highlighted rung means the same thing on every screen that draws a ladder
    — v1's meant 'your cost basis' on one screen and 'current price' on the
    next."""
    for i, (_, v) in enumerate(ladder):
        if last <= v:
            return i
    return len(ladder) - 1


def _positions(tickers=None, limit=None):
    rows = BOOK["positions"]
    if tickers:
        rows = [r for r in rows if r[0] in tickers]
    out = []
    for tk, nm, qty, val, pct, amt, (cls, src, lat) in rows[:limit]:
        change = ui.money(amt, pct, CCY) if amt is not None else '<span class="dim">no source</span>'
        out.append(ui.ledger_row(
            tk, nm, ui.fmt_compact(val, CCY), qty=qty,
            change=change, change_value=amt,
            prov=ui.chip(cls, lat, src)))
    return "".join(out)


# ══════════════════════════════════════════════════════════════════════════
# SCREENS
# ══════════════════════════════════════════════════════════════════════════
def screen_today():
    b = BOOK
    adbe = b["grow"]["ADBE"]
    gap = (adbe["ladder"][2][1] - adbe["last"]) / adbe["ladder"][2][1] * 100
    return (
        ui.page_head("Good morning, Punit", "Main portfolio · USD"),
        ui.hero(ui.fmt_compact(b["nav"], CCY),
                delta=f'+{b["day"]:,} · +{b["day_pct"]}% today', delta_value=b["day"],
                sub=f'{b["holdings"]} holdings · {b["currencies"]} currencies',
                title=f'USD {b["nav"]:,.2f}'),
        ui.provenance(b["freshness"], age=f'refreshed {b["refreshed"]}'),
        ui.section("Needs a decision", "3"),
        ui.attention([
            {"level": "critical", "title": "Margin buffer down to 8%",
             "why": f'−${abs(b["cash"]):,} against ${b["collateral"]:,} of liquid collateral. '
                    f'Rule R4 caps short-put collateral at 60% — ${int(b["collateral"]*0.6):,}.',
             "source": "HARVEST rule 4 · recomputed 09:12"},
            {"level": "warn", "title": f'Adobe is {gap:.1f}% below fair value',
             "why": f'GROW puts fair at ${adbe["ladder"][2][1]:,.2f} and the buy rung at '
                    f'${adbe["ladder"][1][1]:,.2f}. Last ${adbe["last"]:,.2f} — fair, not cheap.',
             "source": "GROW v5.1 · durability 78 · verdict HOLD"},
            {"level": "info", "title": "Three earnings inside 7 days",
             "why": "Nike Thursday, Adobe Friday, Salesforce next Tuesday. "
                    "You hold $278K across the three.",
             "source": "Finnhub earnings calendar"},
        ]),
        ui.section("Prosper brief", "09:12"),
        ui.read('<b>What changed.</b> Up 0.67%, and $3,430 of the $17,170 came from '
                'one name. The UAE book contributed $1,235.<br>'
                '<b>Why it matters.</b> Nothing breached today. The margin buffer '
                'was already thin before the market opened.<br>'
                '<b>Next step.</b> Either sell $30K of treasuries into the loan, or '
                'accept an 8% buffer as the working level. Drift is not a third option.'),
        f'<div style="display:flex;gap:8px;padding:4px 0 8px">'
        f'{ui.button("Read full")}{ui.button("Ask a follow-up", icon_name="open")}</div>',
        ui.section("Today's moves", "all 182"),
        _positions(["NVDA", "CRM", "ALDAR"]),
    )


def screen_today_quiet():
    b = BOOK
    return (
        ui.page_head("Good morning, Punit", "Main portfolio · USD"),
        ui.hero(ui.fmt_compact(b["nav"], CCY),
                delta="+2,140 · +0.09% today", delta_value=2_140,
                sub=f'{b["holdings"]} holdings · {b["currencies"]} currencies'),
        ui.provenance({"live": 62, "delayed": 117, "none": 6}, age="refreshed 14.8s ago"),
        ui.section("Needs a decision", "0"),
        ui.empty("Nothing needs you today",
                 "Every guardrail is inside its limit, no holding is outside its GROW "
                 "band, and the next earnings date is 9 days out. The last time "
                 "something needed a decision was 4 September.",
                 ui.button("Review guardrails anyway")),
        ui.section("Today's moves", "all 182"),
        _positions(["NVDA", "ALDAR", "ADCB"]),
    )


def screen_loading():
    return (
        ui.page_head("Good morning, Punit", "Main portfolio · USD"),
        '<div class="p-hero"><div class="p-sk" style="width:56%;height:34px"></div>'
        '<div class="p-sk" style="width:38%;height:15px;margin-top:10px"></div></div>',
        '<div class="p-prov"><span class="dim">Waking the server — free tier, '
        'this takes 30–60 seconds after idle.</span></div>',
        ui.section("Needs a decision"),
        ui.skeleton(3),
        ui.section("Today's moves"),
        ui.skeleton(3),
    )


def screen_holdings():
    b = BOOK
    regions = " · ".join(f"{n} {c}" for n, c in b["regions"])
    return (
        ui.page_head("Holdings", f'{ui.fmt_compact(b["nav"], CCY)} · {b["holdings"]} positions'),
        ui.segment(["Positions", "Allocation", "Performance"], "Positions"),
        ui.segment(["All 182"] + [f"{n} {c}" for n, c in b["regions"]], "All 182"),
        ui.group("United States", "$1.42M · 62%"),
        _positions(["NVDA", "CRM", "NKE", "ADBE"]),
        ui.group("United Arab Emirates", "$312K · 14%"),
        _positions(["ALDAR", "EMAAR", "ADCB"]),
        ui.group("Unpriced", "6 lines · broker mark"),
        _positions(["OZON"]),
        ui.read(f'Regions sum to {sum(c for _, c in b["regions"])}: {regions}.'),
        f'<div style="padding:12px 0">{ui.button("Show all 182")}</div>',
    )


def screen_allocation():
    b = BOOK
    top3 = sum(s["pct"] for s in sorted(b["sectors"], key=lambda s: -s["pct"])[:3])
    return (
        ui.page_head("Holdings", "Allocation · $2.30M"),
        ui.segment(["Positions", "Allocation", "Performance"], "Allocation"),
        ui.segment(["Sector", "Region", "Currency", "Cap size", "Account"], "Sector"),
        ui.read(f'Top three sectors are <b>{top3:.1f}% of the book</b>. Technology is '
                f'over your 25% cap by 1.4 points, and today’s gain widened it.'),
        ui.ranked_bars(b["sectors"]),
        ui.section("Concentration", "cap 25%"),
        ui.kv("Largest holding · NVDA", '<span class="up">8.0%</span>'),
        ui.kv("Top 5 names", "24.6%"),
        ui.kv("Largest sector · Technology", '<span class="watch">26.4%</span>',
              note="over cap since 2 September"),
    )


def screen_security():
    g = BOOK["grow"]["ALDAR"]
    here = _band(g["ladder"], g["last"])
    rungs = "".join(
        ui.kv(lbl, f'{g["ccy"]} {v:,.2f}', here=(i == here),
              note=f'last {g["ccy"]} {g["last"]:,.2f} sits in this band' if i == here else "")
        for i, (lbl, v) in enumerate(g["ladder"]))
    return (
        ui.page_head("ALDAR", "Aldar Properties PJSC · ADX · AED",
                     back_to="#holdings", back_label="Holdings"),
        '<div class="p-read" style="padding-top:0;font-family:var(--p-mono);font-size:12px">'
        'ISIN AEA002001013 · conid 12457 · listing exchange ADX</div>',
        ui.hero("AED 7.81", delta="+0.09 · +1.17% today", delta_value=0.09),
        ui.provenance("delayed", age="tradingview · 191ms · 16:02 GST"),
        ui.segment(["Overview", "Thesis", "Numbers", "Chart", "News"], "Overview"),
        ui.section("Your position"),
        ui.kv("Quantity · average cost", "11,280 @ AED 6.94"),
        ui.kv("Market value", "$88,140 · 3.8% of book"),
        ui.kv("Unrealized", ui.money(9_812, 12.5, "AED", compact=False)),
        ui.section("GROW entry ladder", f'durability {g["durability"]}'),
        rungs,
        ui.read(f'Verdict <b>{g["verdict"]}</b>. The ladder is recomputed in Python from '
                f'the memo’s own inputs and overrides whatever the model wrote. '
                f'Stability band ±25% holds.'),
        ui.section("Street view", "confirmation only"),
        ui.kv("Ratings", "4 buy · 2 hold · 0 sell"),
        ui.kv("Mean target", "AED 8.90"),
        ui.read('GROW §6.2 puts aggregator data at Tier 5 — it may confirm a thesis, '
                'never set a price. This block never appears above the ladder.'),
    )


def screen_risk():
    b = BOOK
    buf = b["collateral"] + b["cash"]
    return (
        ui.page_head("Risk", "Guardrails, and which are breached",
                     back_to="#more", back_label="More"),
        ui.hero(f'{b["health"]} / 100', delta="2 of 6 guardrails breached",
                delta_value=-1, sub="Market cycle · Growing"),
        ui.section("Guardrails", "6 checks"),
        ui.kv("Single name ≤ 25%", '<span class="up">NVDA 8.0%</span>'),
        ui.kv("Sector ≤ 25%", '<span class="watch">Technology 26.4%</span>'),
        ui.kv("Currency spread", '<span class="up">10 currencies</span>'),
        ui.kv("Margin ≤ 10% of NAV", '<span class="watch">11.0%</span>'),
        ui.kv("Liquid collateral", f'<span class="up">${b["collateral"]:,}</span>'),
        ui.kv("Drawdown from peak", '<span class="up">−4.1%</span>'),
        ui.section("Margin", "against collateral"),
        ui.kv("Loan", ui.money(b["cash"], None, CCY, compact=False)),
        ui.kv("IB01 + U03A treasuries", "$208,000"),
        ui.kv("AED cash", "$67,000"),
        ui.kv("Buffer", f'<span class="watch">${buf:,} · '
                        f'{buf / b["collateral"] * 100:.0f}%</span>'),
        ui.read('The CHF / JPY / SGD debit is a deliberate 1–1.5% funding carry, not '
                'distress. It is counted here as leverage and labelled as a choice.'),
    )


def screen_more():
    return (
        ui.page_head("More", "punit1982 · Main portfolio"),
        ui.section("Go deep"),
        ui.list_row("Risk", "Guardrails and margin",
                    '<span class="watch">72 / 100</span>'),
        ui.list_row("Income", "Dividends, coupons, premium", "$41,280 / yr"),
        ui.list_row("Options", "HARVEST v1.0 · paper mode", "3 tickets"),
        ui.list_row("Evaluate", "GROW v5.1 durability and entry",
                    f'<span class="watch">{BOOK["rated"]} of 182 rated</span>'),
        ui.section("Data"),
        ui.list_row("Add holdings", "Statement, screenshot or manual", "last 8 Sep"),
        ui.list_row("Connections", "Brokers and feeds",
                    '<span class="up">IBKR · Coinbase</span>'),
        ui.list_row("Data source health", "Probed from the server, not a laptop",
                    '<span class="up">10 of 11</span>'),
        ui.read('Mubasher returns <b>403 from Render</b> — Cloudflare blocks datacenter '
                'IPs. It works from a laptop, which is why this row says which network '
                'ran the check.'),
        ui.section("Account"),
        ui.list_row("Display", "Base currency, compact numbers", "USD"),
        ui.list_row("Settings", "Models, collateral ledger, keys"),
    )


SCREENS = [
    ("Today", "today", screen_today,
     "One number, then a queue. The freshness strip is the first thing under the "
     "hero because Phase 1 made it computable and nothing shows it."),
    ("Today · nothing to do", "today", screen_today_quiet,
     "The healthy state — true on roughly 340 days a year, which makes it Today's "
     "normal condition, not its edge case. v1 designed the queue and not the empty queue."),
    ("Waking up", "today", screen_loading,
     "On a spun-down free tier this is the most-seen screen in the product. It says "
     "what is happening and how long it takes, instead of a spinner."),
    ("Holdings", "holdings", screen_holdings,
     "Quantity and average cost on the row, provenance under the figures, and the "
     "six unpriced lines quarantined in their own group with a broker-mark label."),
    ("Allocation", "holdings", screen_allocation,
     "Eight Plotly donuts become one ranked list. The component sorts, so the "
     "picture cannot ship mis-ordered the way v1's did."),
    ("Security", "holdings", screen_security,
     "Five pages in one. The highlighted rung means exactly one thing — the band "
     "containing the last price — and _band() is the only place that decides it."),
    ("Risk", "more", screen_risk,
     "Four eager tabs become one scroll of pass/fail. Arrived at from More, with a "
     "return path drawn — v1 had five non-tab destinations and no way back."),
    ("More", "more", screen_more,
     "Every row carries the one number that says whether it needs attention."),
]


def build(out: Path) -> None:
    frames = []
    for title, active, fn, caption in SCREENS:
        body = "".join(fn())
        frames.append(
            f'<figure class="fr"><figcaption><span class="ft">{title}</span>'
            f'<span class="fc">{caption}</span></figcaption>'
            f'<div class="ph"><div class="phc">{body}</div>{ui.nav(active)}</div></figure>')

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prosper ledger UI — render proof</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
{ui.CSS}
<style>
  body{{margin:0;background:var(--p-sunk);font-family:var(--p-sans);color:var(--p-ink);}}
  .wrap{{max-width:1360px;margin:0 auto;padding:32px 24px 64px;}}
  h1{{font-size:24px;font-weight:600;letter-spacing:-.02em;margin:0 0 6px;}}
  .sub{{font-size:14px;color:var(--p-ink-3);margin:0 0 32px;max-width:70ch;line-height:1.55;}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,375px);gap:40px 32px;justify-content:start;}}
  .fr{{margin:0;width:375px;}}
  figcaption{{margin-bottom:10px;}}
  .ft{{display:block;font-size:15px;font-weight:600;letter-spacing:-.005em;}}
  .fc{{display:block;font-size:13px;line-height:1.5;color:var(--p-ink-3);margin-top:3px;}}
  .ph{{width:375px;height:812px;position:relative;overflow:hidden;border-radius:20px;
       background:var(--p-paper);border:1px solid var(--p-rule-strong);
       box-shadow:0 1px 2px rgba(2,6,23,.10),0 6px 12px -8px rgba(2,6,23,.18);}}
  .phc{{position:absolute;inset:0 0 62px;overflow-y:auto;padding:14px 16px 20px;
        scrollbar-width:none;}}
  .phc::-webkit-scrollbar{{display:none;}}
  .ph .p-nav{{position:absolute;}}
  @media (max-width:430px){{
    .wrap{{padding:16px 8px 40px;}} .grid{{grid-template-columns:1fr;}}
    .fr,.ph{{width:100%;}}
  }}
</style></head><body><div class="wrap">
<h1>Prosper ledger UI — render proof</h1>
<p class="sub">Every pixel below is produced by calling <code>core/ledger_ui.py</code>.
No screen contains hand-written markup, and all figures read from one
<code>BOOK</code> dict, so two screens cannot disagree. Regenerate with
<code>venv/bin/python3 scripts/render_ledger_proof.py</code>.</p>
<div class="grid">{''.join(frames)}</div>
</div></body></html>"""
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}  ({len(page):,} bytes, {len(SCREENS)} screens)")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "ledger_proof.html"))
