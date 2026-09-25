#!/usr/bin/env python3
"""PROSPER v5.13.1 verifier — the framework text and the resolver must say the same thing.

    python3 prosper_framework/prosper_verify.py

core/prosper_engine.resolve_card() OVERRIDES the model's arithmetic with Python constants. If
someone edits the .md (a weight, a band edge, a regime multiplier, a D5 band) without editing
the engine, the app silently replaces correct numbers with stale ones. This reads the numbers
back out of the framework text and compares them with the engine, and then runs the resolver
over the framework's own worked examples. Expect `RESULT: ALL CHECKS PASS`.
"""
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "_stub"))

from core import prosper_engine as pe  # noqa: E402

T = open(os.path.join(ROOT, "prosper_framework", pe.FRAMEWORK_FILE), encoding="utf-8").read()
FAIL = []


def ok(label, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")
    if not cond:
        FAIL.append(label)


def section(start, end):
    a = T.index(start)
    b = T.index(end, a + len(start))
    return T[a:b]


print("=" * 80)
print(f"{pe.PROSPER_VERSION} VERIFIER · {pe.FRAMEWORK_FILE}")
print("=" * 80)

print("\n[1] VERSION")
ok("framework header names the engine's version", T.lstrip("# ").startswith(pe.PROSPER_VERSION))
ok("status is ADOPTED", "STATUS: ADOPTED" in T)

print("\n[2] CORE WEIGHTS (§B3)")
core = section("## B3. CORE", "## B4.")
w = {f"d{n}": int(p) / 100 for n, p in re.findall(r"\*\*D(\d) [^(*]*\((\d+)%\)", core)}
ok("five Core dimensions with weights", len(w) == 5, str(w))
ok("Core weights match the engine", w == pe.CORE_WEIGHTS, f"md {w} vs engine {pe.CORE_WEIGHTS}")
ok("Core weights sum to 100%", abs(sum(w.values()) - 1) < 1e-9)
formula = re.search(r"Q = \[\(D1×\.(\d+)\)\+\(D2×\.(\d+)\)\+\(D3×\.(\d+)\)\+\(D4×\.(\d+)\)\+\(D5×\.(\d+)\)\] × 10", core)
ok("Q formula present", bool(formula))
if formula:
    fw = {f"d{i+1}": int(x) / 100 for i, x in enumerate(formula.groups())}
    ok("Q formula weights match the engine", fw == pe.CORE_WEIGHTS, str(fw))

print("\n[3] BANDS (§B3)")
bands = re.findall(r"\|\s*(\d+)–(\d+)\s*\|\s*([A-Z/ ]+?)\s*\|", core)
md_edges = sorted(((float(lo), word.split("/")[0].strip()) for lo, hi, word in bands
                   if word.strip() in ("STRONG BUY", "BUY", "HOLD/WATCHLIST", "TRIM", "SELL/AVOID")),
                  reverse=True)
ok("five rating bands", len(md_edges) == 5, str(md_edges))
ok("band edges match the engine", md_edges == [(e, wd) for e, wd in pe.Q_BANDS], f"{md_edges} vs {pe.Q_BANDS}")
ok("64.5 is HOLD, not BUY (the rule's own example)", pe.band_for(64.5) == "HOLD")
ok("65.0 is BUY", pe.band_for(65.0) == "BUY")
ok("79.9 is BUY, 80.0 is STRONG BUY", pe.band_for(79.9) == "BUY" and pe.band_for(80.0) == "STRONG BUY")

print("\n[4] D5 ASYMMETRY BANDS (§B3)")
d5 = core[core.index("**D5 Asymmetric Setup"):]
rows = re.findall(r"\|\s*(\d+)–(\d+)\s*\|\s*([^|]+)\|", d5)
parsed = []
for lo, hi, ratio in rows:
    m = re.search(r"≥(\d+)×|(\d+)–(\d+)×|<(\d+)×", ratio)
    if not m:
        continue
    floor = float(m.group(1) or m.group(2) or 0) if not m.group(4) else -math.inf
    parsed.append((floor, int(lo), int(hi)))
ok("five D5 bands", len(parsed) == 5, str(parsed))
ok("D5 bands match the engine", parsed == pe.D5_BANDS, f"{parsed} vs {pe.D5_BANDS}")
for ratio, band in ((5.0, (9, 10)), (4.99, (7, 8)), (3.0, (7, 8)), (2.0, (5, 6)), (1.99, (3, 4)), (0.99, (0, 2))):
    ok(f"ratio {ratio} scores {band}", pe.d5_range(ratio) == band, str(pe.d5_range(ratio)))

print("\n[5] INCOME, MICROCAP, DISTRESSED WEIGHTS (§B6-§B8)")
inc = section("## B6.", "## B7.")
iw = {f"d{n}": int(p) / 100 for n, p in re.findall(r"\|\s*\**D(\d)[^|]*\|\s*\**(\d+)%", inc)}
ok("Income weights match the engine", iw == pe.INCOME_WEIGHTS, f"{iw} vs {pe.INCOME_WEIGHTS}")
ok("Income weights sum to 100%", abs(sum(iw.values()) - 1) < 1e-9)
mic = section("## B8.", "## B9.")
mw = {k.lower(): int(p) / 100 for k, p in re.findall(r"\|\s*\**([PS]\d)[^|]*\|\s*\**(\d+)%", mic)}
ok("Microcap pillar weights match the engine", mw == pe.MICROCAP_WEIGHTS, f"{mw} vs {pe.MICROCAP_WEIGHTS}")
ok("Microcap weights sum to 100%", abs(sum(mw.values()) - 1) < 1e-9)
dis = section("## B7.", "## B8.")
dw = {k.lower(): int(p) / 100 for k, p in re.findall(r"\|\s*(S\d)[^|]*\|\s*(\d+)%", dis)}
ok("Distressed weights match the engine", dw == pe.DISTRESSED_WEIGHTS, f"{dw} vs {pe.DISTRESSED_WEIGHTS}")

print("\n[6] REGIME MULTIPLIERS (§A)")
reg = section("### REGIME OF RECORD", "**[P8] Sources:**")
rm = {name: int(p) / 100 for name, p in re.findall(r"\|\s*([A-Za-z-]+)\s*\|[^|]*\|\s*(\d+)%", reg)}
ok("five regime states", len(rm) == 5, str(rm))
ok("regime multipliers match the engine", rm == pe.REGIME_MULTIPLIER, f"{rm} vs {pe.REGIME_MULTIPLIER}")

print("\n[7] AI CLASS (§B11)")
ai = section("## B11.", "## B12.")
ok("AI-A floor 8", "floor 8" in ai and pe.AI_D2_FLOOR == {"AI-A": 8})
for cls, cap in (("AI-P", 7), ("AI-V", 5), ("AI-X", 3)):
    ok(f"{cls} ceiling {cap}", re.search(rf"{cls}[^|]*\|\s*ceiling {cap}", ai) is not None and pe.AI_D2_CEILING[cls] == cap)

print("\n[8] FORMULAS (P3, D5-gate, P4, P10)")
ok("P3 formula text present", "(bull − spot) ÷ (spot − stressed bear)" in T)
ok("re-entry formula text present", "(bull + 2 × bear) ÷ 3" in T)
ok("re-entry solves ratio = 2", abs(pe.reward_risk(340, pe.price_for_ratio(340, 180, 2), 180) - 2.0) < 1e-9)
ok("P4 threshold is >10%/yr", ">10%/yr over the last 3 years" in T and pe.DILUTION_CAGR_LIMIT == 0.10)
ok("P10 break weight ≥10%", "weighted ≥10%" in T and pe.CONDUCT_MIN_BREAK_WEIGHT == 0.10)
ok("QoS drawdown >40%", "Down >40%" in T and pe.QOS_MIN_DRAWDOWN_PCT == 40.0)
ok("valid-until +90 / +60 days", "+90 days" in T and "+60 days" in T and
   (pe.VALID_DAYS, pe.VALID_DAYS_SHORT) == (90, 60))
ok("batch budget ≤6 per name", "then ≤6 per name" in T and pe.BATCH_MAX_SEARCHES == 6)
ok("delta budget ≤6", pe.PROSPER_TIERS["delta"]["max_searches"] == 6)
ok("new Core name budget ≤12", pe.PROSPER_TIERS["standard"]["max_searches"] == 12)

print("\n[9] WORKED EXAMPLES")


def card(**over):
    d = {"route": "CORE", "ai_class": "AI-N",
         "scores": {"d1": 8, "d2": 8, "d3": 6, "d4": 7, "d5": 6},
         "cases": {"bear": {"price": 180, "weight": .25}, "base": {"price": 260, "weight": .5},
                   "bull": {"price": 340, "weight": .25}},
         "catalysts": [{"event": "Q3 results", "date": "30-Oct-2026"}],
         "prove_wrong": [{"fact": "x", "effect": "y"}], "integrity": {"type": "NONE"},
         "regime": {"state": "Amber"}, "conviction_target_pct": 3}
    d.update(over)
    return d


r = pe.resolve_card(card(), 231.5)
ok("P3 printed: (340−231.5)÷(231.5−180) = 2.11×", r["ratio_text"] == "2.11×", r["ratio_text"])
ok("Q = 71.5 → BUY at 2.11×", r["q"] == 71.5 and r["call"] == "BUY", f"{r['q']} {r['call']}")
r = pe.resolve_card(card(), 240.0)
ok("same name at 240 (1.67×) → ACCUMULATE ON DIPS, release at 233.33",
   r["call"] == "ACCUMULATE ON DIPS" and abs(r["reentry"] - 233.333) < 0.01, f"{r['call']} {r['reentry']}")
r = pe.resolve_card(card(integrity={"type": "ACCOUNTS"}), 231.5)
ok("F-INT (accounts) caps at SELL", r["call"] == "SELL", r["call"])
r = pe.resolve_card(card(integrity={"type": "CONDUCT"},
                         cases={"break": {"price": 120, "weight": .10}, "bear": {"price": 180, "weight": .2},
                                "base": {"price": 260, "weight": .45}, "bull": {"price": 340, "weight": .25}}), 200)
ok("Conduct: break is the stressed bear; ratio (340−200)÷(200−120)=1.75× → HOLD, no SELL cap",
   r["ratio_text"] == "1.75×" and r["call"] == "HOLD", f"{r['ratio_text']} {r['call']}")
r = pe.resolve_card(card(integrity={"type": "CONDUCT"},
                         cases={"break": {"price": 100, "weight": .10}, "bear": {"price": 180, "weight": .2},
                                "base": {"price": 230, "weight": .45}, "bull": {"price": 250, "weight": .25}}), 200)
ok("Conduct: break-case ratio <1× → SELL", r["call"] == "SELL", f"{r['ratio_text']} {r['call']}")
r = pe.resolve_card(card(integrity={"type": "REPORTING_CONTROL", "restatement_direction": "CONSERVATIVE",
                                    "direction_source": "FY2025 annual report note 2"}), 231.5)
ok("P11 conservative restatement: D4 7 → 6, no SELL cap", r["scores"]["d4"] == 6 and r["call"] != "SELL",
   f"d4={r['scores']['d4']} {r['call']}")
r = pe.resolve_card(card(integrity={"type": "REPORTING_CONTROL", "restatement_direction": "CONSERVATIVE"}), 231.5)
ok("P11 direction without a source → treated as FLATTERING → SELL", r["call"] == "SELL", r["call"])
r = pe.resolve_card(card(dilution={"shares_3y_ago": 100e6, "shares_now": 140e6, "years": 3}), 231.5)
ok("P4: 11.9%/yr dilution caps D4 at 4", r["scores"]["d4"] == 4, str(r["scores"]["d4"]))

print("\n" + "=" * 80)
print("RESULT: ALL CHECKS PASS" if not FAIL else f"RESULT: {len(FAIL)} FAILED — " + "; ".join(FAIL))
sys.exit(1 if FAIL else 0)
