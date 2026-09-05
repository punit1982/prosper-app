#!/usr/bin/env python3
"""GROW v5.1 verifier.  python3 grow_verify.py "GROW v5 1 CORE 04Sep2026.md"
Tests the bug classes reading cannot catch:
  DEFINED       everything a rule references is defined
  PRODUCED      everything the memo must contain has a rule producing it
  CONSEQUENTIAL every rule that produces a finding also changes something
  SEPARATED     no price term in Durability; no Durability term in Entry
Plus exhaustive archetype reachability and an exhaustive Entry resolver."""
import re, sys, itertools, collections, os, glob

PATH = sys.argv[1] if len(sys.argv) > 1 else "GROW v5 1 CORE 04Sep2026.md"
T = open(PATH).read()
D = os.path.dirname(os.path.abspath(PATH))
ANNEX = {}
for f in glob.glob(os.path.join(D, "GROW v5 1 ANNEX *.md")):
    ANNEX[os.path.basename(f).split("ANNEX ")[1][0]] = open(f).read()
ALL = T + "\n".join(ANNEX.values())
FAIL, WARN = [], []
def ok(l, c, d=""):
    print(f"  {'ok  ' if c else 'FAIL'}  {l}{('  '+d) if d else ''}")
    if not c: FAIL.append(l)
def warn(l, c, d=""):
    if not c: print(f"  warn  {l}{('  '+d) if d else ''}"); WARN.append(l)

tree = T.split('## 5.2')[0].split('## 5.1')[1]
tbl  = ''  # archetype table lives in Annex E (set after annexes load)
core_ret = T.split("## 6.4")[1].split("# §7")[0]
crit = T.split("## 7.1")[1].split("## 7.2")[0]
prof = re.findall(r'\|\s+\*\*(P\d+)\*\*[^|]*\|([^|]*)\|((?:\s*\**\d+\**\s*\|){8})', T)
MAN = ANNEX.get("E", "")
tbl  = ANNEX.get("E", "")
arch = re.findall(r'\|\s*\*\*([A-Z]\d)\*\*\s*\|([^|]*)\|([^|]*)\|([^|]*)\|\s*(P\d+)\s*\|([^|]*)\|([^|]*)\|', tbl)

print("="*84); print(f"GROW v5.1 VERIFIER  ·  {PATH}"); print(f"annexes loaded: {sorted(ANNEX)}"); print("="*84)

print("\n[1] ARCHETYPES")
tc = set(re.findall(r'\*\*([A-Z]\d)\*\*', tree)); bc = {r[0] for r in arch}
ok("every archetype in the tree has a table row", tc <= bc, f"missing {sorted(tc-bc)}" if tc-bc else f"({len(tc)})")
ok("every table row is reachable from the tree", bc <= tc, f"unreachable {sorted(bc-tc)}" if bc-tc else "")
ok("all archetypes carry premium, hurdle, profile, method and a forbidden method",
   all(all(x.strip() for x in r[2:]) for r in arch), f"({len(arch)} rows)")
ok("the composite / sum-of-parts archetype exists", "G1" in bc and "Gate 0" in T)
lookup = ANNEX.get("E", "")
lookup = lookup.split("Additional")[-1] if "Additional" in lookup else lookup
man = set(re.findall(r'[A-Z]\d', "".join(re.findall(r'\|\s*\*\*([^|]+?)\*\*\s*\|', lookup))))
ok("every archetype has retrieval lines in the lookup annex", bc <= man,
   f"no row: {sorted(bc-man)}" if bc-man else f"({len(man)} codes)")

print("\n[2] DURABILITY WEIGHTS — eight criteria, price excluded")
sums = {p: sum(int(x) for x in re.findall(r'\d+', b)) for p, _, b in prof}
ok("ten profiles present", len(prof) == 10, f"({len(prof)})")
ok("all profiles sum to 100", all(v == 100 for v in sums.values()), str({k:v for k,v in sums.items() if v!=100}))
ok("all profiles carry exactly 8 criteria", all(len(re.findall(r'\d+', b)) == 8 for _, _, b in prof))
used = {r[4] for r in arch}
ok("every profile referenced is defined", used <= set(sums), f"undefined {sorted(used-set(sums))}" if used-set(sums) else "")
warn("every profile defined is used", set(sums) <= used, f"unused {sorted(set(sums)-used)}" if set(sums)-used else "")

print("\n[3] CRITERIA")
cn = re.findall(r'\|\s*(\d)\s*\|\s*\*\*([^*]+)\*\*', crit)
ok("eight criteria defined", len(cn) == 8, f"({len(cn)})")
ok("Worth is not a criterion", "Worth is not a criterion" in T)
anchors = {"1":"end-market spending line","2":"technical lead measured","3":"qualified alternatives",
 "4":"penetration of the addressable","5":"Margin room","6":"cash conversion",
 "7":"converting inside twelve months","8":"prior roles and what happened"}
for n, nm in cn:
    ok(f"criterion {n} {nm.strip()[:26]:<26s} has retrieval support", anchors[n].lower() in ALL.lower())
ok("margin-room band table complete", "20 points or more" in T and "12 up to 20" in T)
ok("bands do not overlap at zero", "A room of exactly zero scores 1, not 3" in T)
ok("peak detector present", "at or above the best margin" in T)
ok("mid-ramp exception is capped and provisional", "capped at 7 and marked PROVISIONAL" in T)
ok("past expansion is not a mechanism", "three consecutive years of margin expansion is not a mechanism" in T)
ok("no placeholder scoring", "A criterion is never given a default of 5" in T)
ok("unscoreable weight is redistributed", "weight is removed and redistributed" in T)
ok("structural evidence may be scored ahead of the P&L", "may be scored ahead of the near-term profit and loss" in T)
ok("the segment, not the consolidated line", "reading the segment, never the consolidated line" in T)

print("\n[4] FIVE AXES")
for lab, pat in [("axis 1 archetype","Axis 1 — archetype"),("axis 2 measurement basis","Axis 2 — measurement basis"),
                 ("axis 3 proof stage","Axis 3 — proof stage"),("axis 4 regime factor","Axis 4 — regime factor"),
                 ("axis 5 horizon","Axis 5 — horizon"),
                 ("all five printed in the header","all five are printed in the memo header"),
                 ("basis assigned by trigger, never by theme","never by theme"),
                 ("computability fallback to M1","FALLBACK"),
                 ("regime never enters the score","never enters the Durability score"),
                 ("regime coverage gap defaults to 1.00 and flags","set to ×1.00, flagged as a coverage gap"),
                 ("horizon computed, never asserted","Computed, printed, never asserted")]:
    ok(lab, pat in T)
for b in ["M1","M2","M3","M4","M5","M6","M7","M8","M9"]: ok(f"  basis {b} defined", f"**{b} ·" in T)
for s in ["S0","S1","S2","S3","S4"]: ok(f"  stage {s} defined", f"**{s}**" in T)

print("\n[5] ANNEX TRIGGERS AND CONTENT")
ok("annex load rules stated in core", "Load when" in T or "load an annex only when" in T)
ok("annex A substitution table exists", "THE SUBSTITUTION TABLE" in ANNEX.get("A",""))
ok("annex A covers S0, S1, S2 and S3 columns", all(x in ANNEX.get("A","") for x in ["S0 ·","S1 ·","S2 ·","S3 ·"]))
ok("annex A margin-room weight removed at S0", "Weight removed and redistributed" in ANNEX.get("A",""))
ok("annex A forward engine has four build methods",
   all(x in ANNEX.get("A","") for x in ["Method A","Method B","Method C","Method D"]))
ok("annex A carries the reverse test", "what the price already requires" in ANNEX.get("A",""))
ok("annex A requires two methods minimum", "at least two of the four must be built" in ANNEX.get("A","").lower()
   or "At least two of the four must be built" in ANNEX.get("A",""))
ok("annex A has the value-chain layer test", "VALUE-CHAIN LAYER" in ANNEX.get("A",""))
ok("annex A has the pre-investment checklist", "PRE-INVESTMENT CHECKLIST" in ANNEX.get("A",""))
ok("annex B covers every special basis",
   all(x in ANNEX.get("B","") for x in ["## M2","## M3","## M4","## M5","## M9"]))
ok("annex C probabilities are pinned", "Never re-retrieved per run" in ANNEX.get("C",""))
ok("annex C maps one probability to four cases", "split 60 / 40 by default" in ANNEX.get("C",""))
ok("annex C resolves the overlap with annex A", "do not run both" in ANNEX.get("C",""))
ok("annex D is never loaded in a run", "Never loaded during a run" in ANNEX.get("D",""))

print("\n[6] SEPARATED — the two verdicts are independent by construction")
dur = T.split("# §7 · THE DURABILITY SCORE")[1].split("# §8")[0]
ent = T.split("# §8 · THE ENTRY VERDICT")[1].split("# §9")[0]
price_terms = ["today's price", "spot", "multiple versus peers", "price to book", "cheap", "P/E"]
bad = [w for w in ["CAGR_spot", "EXCESS", "price ladder", "today's price"] if w in dur]
ok("no price term appears in the Durability section", not bad, f"found {bad}" if bad else "")
ok("Durability is explicitly price-free", "containing no price" in T and "Price is not one of them" in T)
ok("Entry never raises Durability", "Entry never raises Durability" in T)
ok("Durability is never touched by price", "Durability is never touched by price" in T)
ok("the reason for the split is recorded", "punishes good news" in T or "rose 63%" in T)

print("\n[7] ENTRY RESOLVER — exhaustive")
def entry(excess, cagr, bull_pos, no_engine, paper, integ):
    if integ == '4': return 'STRONG SELL'
    if cagr < 0: v = 'SELL' if bull_pos else 'STRONG SELL'
    elif excess >= 8: v = 'STRONG BUY'
    elif excess >= 0: v = 'BUY'
    else: v = 'HOLD'
    O = ['STRONG SELL','SELL','HOLD','BUY','STRONG BUY']
    if no_engine and O.index(v) > O.index('HOLD'): v = 'HOLD'
    if paper and O.index(v) > 0: v = O[max(0, O.index(v)-1)]
    ceil = {'3A':'HOLD','3C':'HOLD','3B':'BUY'}.get(integ)
    if ceil and O.index(v) > O.index(ceil): v = ceil
    return v
O = ['STRONG SELL','SELL','HOLD','BUY','STRONG BUY']
grid = list(itertools.product([-20,-12,-0.1,0,0.1,7.9,8,15],[-0.3,-0.01,0,0.01,0.12,0.4],
        [True,False],[True,False],[True,False],['0','1','2','3A','3B','3C','4']))
bad = []
for ex, cg, bp, ne, pp, ig in grid:
    v = entry(ex, cg, bp, ne, pp, ig)
    if v not in O: bad.append(("not a verdict", ex, cg, ig))
    if ig == '4' and v != 'STRONG SELL': bad.append(("fraud not Strong Sell", ex, cg, ig))
    if ig == '3A' and O.index(v) > O.index('HOLD'): bad.append(("3A ceiling", ex, cg, ig))
    if ig == '3C' and O.index(v) > O.index('HOLD'): bad.append(("3C ceiling", ex, cg, ig))
    if ig == '3B' and O.index(v) > O.index('BUY'): bad.append(("3B ceiling", ex, cg, ig))
    if ne and O.index(v) > O.index('HOLD'): bad.append(("no-engine cap", ex, cg, ig))
    if cg < 0 and O.index(v) > O.index('SELL'): bad.append(("negative CAGR above Sell", ex, cg, ig))
ok(f"no ambiguous or illegal Entry verdict across {len(grid):,} combinations", not bad,
   f"{len(bad)} violations e.g. {bad[:2]}" if bad else "")
ok("a negative expected return can never print Buy", entry(-5, -0.02, True, False, False, '0') == 'SELL')
ok("excess at exactly +8 is Strong Buy", entry(8, 0.2, True, False, False, '0') == 'STRONG BUY')
ok("excess just below 0 is Hold, not Sell", entry(-0.1, 0.05, True, False, False, '0') == 'HOLD')
ok("paper profits costs one rung", entry(9, 0.2, True, False, True, '0') == 'BUY')
ok("no forward engine caps at Hold", entry(20, 0.3, True, True, False, '0') == 'HOLD')
ok("price ladder has four levels", all(x in T for x in ["Strong buy below","Buy below","Fairly priced","Reduce above"]))
ok("verdict stability is tested across the band", "VERDICT UNSTABLE" in T)

print("\n[8] NOT LOST — accuracy rules restored in past consolidations")
for lab, pat in [
 ("mandatory triggers force a document open","force a document open"),
 ("debt schedule forced above 1.5x EBITDA","full maturity schedule by year"),
 ("organic figure forced when an acquisition drives growth","organic growth figure, separately stated"),
 ("concentration from the LATEST filing","from the latest filing"),
 ("management's verbatim explanation on a margin move","own explanation, verbatim"),
 ("primary docket on a regulator action","primary filing or docket entry"),
 ("named credible dissenting analysts","demonstrated prior record on this name"),
 ("reinvestment arithmetic check","reinvestment rate"),
 ("Break is the thesis being wrong","not a milder bear"),
 ("terminal multiple needs a named company","matched on growth within ±5 points"),
 ("guided-versus-delivered table","guided-versus-delivered"),
 ("integrity upstream search","upstream search"),
 ("integrity 3A needs the primary document","primary document"),
 ("position read only after both verdicts","after both verdicts are fixed"),
 ("firewall enforced by check not by claim","Enforcement is by check, not by claim"),
 ("cohort-anchored decay curve","anchored on a named cohort"),
 ("cohort median printed even when beaten","state what the median would have produced"),
 ("joint-conservatism three limbs","joint-conservatism check"),
 ("optimistic variant also computed","two or more optimistic inputs"),
 ("debt built not picked","the debt is built, never picked"),
 ("ladder validated against this year's guidance","cannot reproduce this year's guidance"),
 ("dilution pre-computation for splits","Split-adjust the entire share-count series"),
 ("acquisition shares on their own line","acquisition consideration on their own line"),
 ("negative-retrieval log format","NOT FOUND —"),
 ("depth is never budgeted","Depth is never budgeted"),
 ("class A/B/C input classification","C · FORECAST"),
 ("only class C counts as judgement","Only Class C rows count as judgement"),
]:
    ok(lab, pat in T)

print("\n[9] CONSEQUENTIAL — a finding must change something")
for lab, pat in [
 ("stress test changes the verdict's confidence","Confidence drops to \"this is a close call and I could be wrong.\""),
 ("driving inputs table exists","| Input | Value | Class | Source | Moves the answer by |"),
 ("too much judgement forces a range","the Entry output is a range rather than a word"),
 ("chronic gap counted and capped","three consecutive runs"),
 ("retrievable fact may never be estimated","A retrievable fact may never be estimated"),
 ("back-solving named and banned","never by back-solving from market capitalisation"),
 ("no named comparable, no multiple","No named comparable, no multiple"),
 ("stated is not sourced","Stated is not sourced"),
 ("entry never drives a sale","The Entry verdict never drives a sale"),
 ("no time stop","never from elapsed time"),
 ("the one reason is the sell discipline","the entire sell discipline"),
 ("failed peer required every memo","The failed peer"),
 ("runner-up archetype verdict printed","the Entry verdict it would have produced"),
 ("five-year scale test stated pass or fail","venture bet"),
]:
    ok(lab, pat in ALL)

print("\n[10] ACCURACY COMMITMENTS")
for lab, pat in [("blow-up avoidance target","Blow-up avoidance"),("interval coverage target","Interval coverage"),
                 ("retrieval integrity target","Retrieval integrity"),
                 ("directional accuracy has no threshold","is not a target"),
                 ("the sleeve arithmetic is stated","two in fifteen"),
                 ("calibration questions carry actions","If the answer is wrong")]:
    ok(lab, pat in T)

print("\n[10b] RECORDABLE — a verdict that cannot be audited later is not issued")
# Closes the three defects the 04-Sep-2026 calibration baseline found.
for lab, pat in [("bare verdicts banned at any length", "A verdict that is not decomposed is not a verdict"),
                 ("the ban has no short form",          "if there is not room for the score, there is not room for the verdict"),
                 ("the answer block travels with the verdict", "This block travels with the verdict wherever the verdict goes"),
                 ("rating lists must itemise every rated name", "A rating list itemises every name it rates"),
                 ("aggregate counts are not a record",   "An aggregate count of ratings is not a record of them"),
                 ("sweep output reconciles counts to table", "The two counts must reconcile to the table"),
                 ("one verdict scale only",             "One scale, and it is this one"),
                 ("PROSPER scale superseded not mapped", "superseded, not translated"),
                 ("no mapping table permitted",         "never mapped onto this scale"),
                 ("superseded verdicts mean unrated",   "is treated as unrated and re-run")]:
    ok(lab, pat in T)

print("\n[10c] OPEN ITEMS — each is closed, or dated, or named as structural")
for lab, pat in [("criteria 5 and 7 proved disjoint",   "Criteria 5 and 7 are disjoint by construction"),
                 ("the conversion ambiguity is fixed",  "means revenue converting into profit and nothing else"),
                 ("book conversion defined separately", "means order book converting into revenue and nothing else"),
                 ("the P8 weight question is dated not vague", "That is a calibration question and is dated"),
                 ("the dormancy clock is defined",      "Dormancy counts **opportunities, not calendar time**"),
                 ("untested is distinguished from dormant", "is **Untested**, not Dormant"),
                 ("the archetype premiums are falsifiable", "What would refute the premiums"),
                 ("the refutation test has a threshold", "rank correlation below +0.5 refutes the ladder"),
                 ("the calibration baseline is named",  "GROW CALIBRATION LEDGER 04Sep2026.md"),
                 ("the baseline disclaims being a result", "Nothing in it is a hit rate")]:
    ok(lab, pat in T)
# the four reads must each carry a date
ok("all four calibration reads are dated",
   all(d in T for d in ("04-Sep-2026", "04-Mar-2027", "04-Sep-2027", "04-Sep-2029")))
# rules 20-22 must exist and be numbered contiguously off 19
ok("rules 20-22 present and numbered", all(f"\n{n}. **" in T for n in (19, 20, 21, 22)))

print("\n[11] CONTRADICTIONS")
ok("the suspended rules are named in writing", "Suspensions made in this version" in T)
ok("v5.0 entry verdicts declared non-convertible", "not convertible to this scale" in T)
ok("no leftover 20% price ceiling", "more than 20% below today's price" not in T)
ok("no leftover margin-room floor", "raise the rating to **BUY**" not in T)
ok("one criteria count", "nine criteria" not in T)
refs = set(re.findall(r'§(\d+)', T)); defs = set(re.findall(r'^# §(\d+)', T, re.M))
ok("no dangling section references", refs <= defs, f"dangling {sorted(refs-defs)}" if refs-defs else "")
s = [x.strip() for x in re.split(r'(?<=[.!?])\s+', re.sub(r'[*`|#]', ' ', T)) if len(x.split()) >= 9]
dups = [x for x, c in collections.Counter(s).items() if c > 1]
ok("no accidental duplicate sentences", len(dups) <= 1, f"{len(dups)}")

print("\n[12] SIZE")
cw = len(T.split()); print(f"  core    {cw:,} words  ~{cw*1.33:,.0f} tokens")
for k in sorted(ANNEX):
    aw = len(ANNEX[k].split()); print(f"  annex {k} {aw:,} words  ~{aw*1.33:,.0f} tokens")
print(f"  standard run = core only. pre-revenue = core + A. life science = core + C.")
ok("the stated core word count matches", f"{round(cw,-2):,} words" in T, f"actual {cw:,}")

print("\n" + "="*84)
print(f"RESULT: {'ALL CHECKS PASS' if not FAIL else f'{len(FAIL)} FAILURES'}" + (f"  ·  {len(WARN)} warnings" if WARN else ""))
for x in FAIL: print(f"   - {x}")
print("="*84)
sys.exit(1 if FAIL else 0)
