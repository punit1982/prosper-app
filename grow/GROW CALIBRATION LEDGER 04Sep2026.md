# GROW CALIBRATION LEDGER — BASELINE
**Cut 04-Sep-2026 · covers every verdict issued 14-Aug-2026 to 03-Sep-2026 · this document is the t0 anchor, not a result**

---

## 1 · WHAT THIS IS, AND WHAT IT IS NOT

GROW v5.1 carries three accuracy commitments. This exercise was meant to turn them from targets into measurements.

**It cannot do that yet, and the reason is time, not sample size.** Median elapsed time across the 53 priced US verdicts is **six days**. The maximum is twenty. The framework's own stated horizon is three to five years. Reading a hit rate off six days of price action would be the exact failure GROW was built to stop — printing a number because a number was asked for.

What this document does instead, and what makes it worth the run:

1. **It fixes the baseline.** Every verdict is recorded with the price the memo actually printed, so a real measurement is possible in twelve and thirty-six months. Without this record the calibration could never be run at all — the prices would have to be reconstructed from memory, and they would be reconstructed favourably.
2. **It closes the checks that do not need time** — retrieval integrity, scale consistency, decomposition discipline.
3. **It surfaces five findings in how verdicts were recorded.** Three are defects and are fixable now.

> **Anyone quoting the return columns below as evidence that GROW works, or does not work, has misread this document.**

---

## 2 · THE THREE COMMITMENTS — WHAT EACH READS TODAY

| # | Commitment | Target | Reads today | Status |
|---|---|---|---|---|
| 1 | **Blow-up avoidance** — no name rated HOLD or better falls more than 50% | >=95% | 37/37 = 100% at −50%; 37/37 at −25%; 36/37 at −15% (OM −20.4%) | **Not yet testable.** At six days median, no framework of any quality would show a −50% breach. Re-reads at 12mo |
| 2 | **Interval coverage** — realised outcome lands inside the stated Bear–Bull band | ~80% | Untestable. The bands are three-to-five-year bands | **Not yet testable.** First meaningful read 04-Sep-2029 |
| 3 | **Retrieval integrity** — every figure carries a Class A/B/C tag and a source | 100% | **FAILS.** See F2 and F3 | **Testable now, and it fails** |

**One of the three is testable today, and it is the one that failed.** That is the useful output of this run.

---

## 3 · FINDINGS

### F1 · Two rating scales were in live use in the same three-week window — MATERIAL

The 14-Aug and 15-Aug Swiss and Japanese sweeps, and the 27-Aug TSE update, issue **BUY / ACCUMULATE / WAIT / REFUSE** — the PROSPER vocabulary. Everything from 15-Aug onward issues **STRONG BUY / BUY / HOLD / SELL / STRONG SELL** — the GROW five-point scale.

98 verdicts sit on the PROSPER scale and 53 on the GROW scale. **They cannot be pooled**, and no document says how one maps to the other. A "WAIT" is not a "HOLD": WAIT was a timing statement, HOLD is a rating on the business at the price.

*Consequence:* the Japanese and Swiss names have no GROW-comparable verdict on record. They are excluded from every statistic in section 4.

*Fix:* either re-run the retained Swiss and Japanese names under v5.1, or mark the PROSPER-scale verdicts formally superseded. Do not build a mapping table — a mapping invented after the fact is a fabricated verdict.

### F2 · Thirteen of 53 GROW verdicts were issued with no printed score — MATERIAL

Every verdict in the four 30-Aug LIVE BATCH documents (APP, TTD, IREN, ASTS, RDW, OSS, FLNC, SHLS, ENVX, EOSE) and both 03-Sep names (ONON, LULU) carries a rating with no score and no decomposition.

v5.1 section 7.4 requires the Durability score with its eight criteria, and section 8 requires the Entry arithmetic printed. A bare rating is not reproducible and cannot be calibrated — there is no way to ask later whether the score or the price drove the call.

*Fix:* add a check to `grow_verify.py` that fails any memo whose verdict line lacks a score. **This is a verifier gap, not a framework gap** — v5.1 already requires the decomposition; nothing was enforcing it.

### F3 · Sixty-five sweep verdicts exist with no audit trail — MATERIAL

The 14-Aug TSE sweep rates 93 of 107 names but itemises only 28. The remaining 65 verdicts are referenced in aggregate and cannot be reconstructed. The 15-Aug Swiss sweep is cleaner (38 of 113 rated, all itemised).

*Consequence:* retrieval integrity is not 100%. For those 65 it is not measurable at all.

*Fix:* a sweep must itemise every name it rates, or state explicitly that unlisted names were screened and not rated.

### F4 · The Entry arithmetic behaved exactly as designed — CONFIRMING

AXT was rated **HOLD on 21-Aug at $70.18** and **BUY on 30-Aug at $59.32**. The business did not improve in nine days; the price fell 15.5%, EXCESS rose above zero, and the verdict moved one notch. The Durability score barely moved (65.8 to 66.0) while the Entry verdict changed.

This is the v5.1 separation of Durability from Entry working in the open, and it is the clearest live confirmation in the period.

### F5 · The sell side is the weak side, even this early — WATCH, NOT YET EVIDENCE

Four of sixteen SELL or STRONG SELL calls rose more than 5% (EOSE +18.6%, TTD +5.9%, ASPI +5.4%, POET +5.4%). The SELL bucket's mean return of +1.08% sits close to the +1.76% all-name mean; the BUY bucket at +4.04% sits well above it.

At six days this is noise. It is logged because if it is still true at twelve months it points at a specific weakness — the framework identifying poor businesses correctly while mistiming the exit, which is the classic short-side failure and would argue for treating SELL as "do not own" rather than "sell now".

---

## 4 · WHAT THE NUMBERS SAY, WITH THE HEALTH WARNING ATTACHED

**53 GROW-scale verdicts · 45 unique tickers · elapsed 1 to 20 days, median 6 · all prices IBKR live, 04-Sep-2026**

| Verdict | n | Mean | Median | Up | Down |
|---|---|---|---|---|---|
| BUY | 9 | +4.04% | +2.35% | 7 | 2 |
| HOLD | 28 | +1.89% | +0.38% | 15 | 13 |
| SELL | 13 | +1.08% | +1.53% | 8 | 5 |
| STRONG SELL | 3 | −3.24% | −1.62% | 1 | 2 |
| **All rated** | **53** | **+1.76%** | **+1.16%** | | |

**Ordering.** BUY > HOLD > SELL > STRONG SELL, in the right direction at every step. Long-short spread +3.77 points.

**Statistics.** Verdict-vs-return Spearman rho **+0.162, p = 0.247**. Score-vs-return rho **+0.186, p = 0.244** (n=41 with printed scores). Directional hits 14 of 25, **p = 0.345** against a coin flip.

**None of that is significant, and it is not supposed to be.** A true 65% hit rate needs roughly **67 verdicts** to separate from chance at 80% power. There are 53 — but the binding constraint is the horizon, not the count. Fifty-three verdicts measured at six days are fifty-three measurements of market noise.

**Largest moves:** IREN +24.8% (HOLD, 5d) · OM −20.4% (HOLD, 19d) · EOSE +18.6% (SELL, 5d) · SNDK +17.0% (HOLD, 6d) · LULU −16.8% (SELL, 1d) · ALT +16.8% (BUY, 19d).

*LULU is the only call in the set that has already been paid: rated SELL on 03-Sep at $120.58, trading $100.31 one day later. One day proves nothing, and it is recorded here so it cannot quietly be re-told later as a three-year win.*

---

## 5 · THE BASELINE — 53 ANCHORED VERDICTS

Prices are as printed in each memo (t0) against IBKR live 04-Sep-2026.

| Ticker | Date | Verdict | Score | t0 price | 04-Sep | Delta |
|---|---|---|---|---|---|---|
| APP | 15-Aug | BUY | 66 | 316.75 | 320.43 | +1.2% |
| PODD | 16-Aug | BUY | 71 | 144.03 | 147.41 | +2.3% |
| VOR | 16-Aug | BUY | 69 | 23.03 | 25.09 | +8.9% |
| ALT | 16-Aug | BUY | 68 | 2.9201 | 3.41 | +16.8% |
| CATX | 16-Aug | HOLD | 61 | 3.20 | 3.14 | −1.9% |
| OM | 16-Aug | HOLD | 59 | 4.51 | 3.59 | −20.4% |
| IBRX | 16-Aug | HOLD | 50 | 7.5409 | 8.075 | +7.1% |
| STXS | 16-Aug | SELL | 44 | 1.3789 | 1.40 | +1.5% |
| CIFR | 21-Aug | HOLD | 68 | 15.78 | 17.74 | +12.4% |
| ORCL | 21-Aug | HOLD | 68 | 146.51 | 159.20 | +8.7% |
| NBIS | 21-Aug | HOLD | 59 | 219.50 | 225.47 | +2.7% |
| CRWV | 21-Aug | HOLD | 50 | 87.65 | 89.11 | +1.7% |
| IREN | 21-Aug | HOLD | 50 | 41.84 | 44.43 | +6.2% |
| COHR | 21-Aug | HOLD | 76.4 | 289.00 | 281.05 | −2.8% |
| LITE | 21-Aug | HOLD | 70.2 | 866.02 | 880.93 | +1.7% |
| AXTI | 21-Aug | HOLD | 65.8 | 70.18 | 62.35 | −11.2% |
| AAOI | 21-Aug | SELL | 44.8 | 112.25 | 105.58 | −5.9% |
| ASPI | 21-Aug | SELL | 42.9 | 3.985 | 4.20 | +5.4% |
| POET | 21-Aug | SELL | 35.3 | 8.23 | 7.93 | −3.6% |
| ORCL | 27-Aug | HOLD | 72 | 151.36 | 159.20 | +5.2% |
| CIFR | 27-Aug | HOLD | 70 | 16.47 | 17.74 | +7.7% |
| HLIT | 28-Aug | BUY | 70 | 12.08 | 11.78 | −2.5% |
| FSLR | 28-Aug | HOLD | 59 | 203.27 | 204.53 | +0.6% |
| AMPG | 28-Aug | SELL | 31 | 3.385 | 3.45 | +1.9% |
| MU | 29-Aug | HOLD | 66.4 | 930.80 | 1018.00 | +9.4% |
| SNDK | 29-Aug | HOLD | 61.0 | 1483.42 | 1735.30 | +17.0% |
| AMKR | 29-Aug | HOLD | 57.6 | 48.15 | 47.78 | −0.8% |
| ASX | 29-Aug | HOLD | 56.6 | 37.78 | 37.37 | −1.1% |
| AXTI | 30-Aug | BUY | 66.0 | 59.32 | 62.35 | +5.1% |
| AAOI | 30-Aug | SELL | 44.6 | 106.75 | 105.58 | −1.1% |
| AMPG | 30-Aug | SELL | 32.5 | 3.38 | 3.45 | +2.1% |
| POET | 30-Aug | SELL | 32.1 | 7.5258 | 7.93 | +5.4% |
| APP | 30-Aug | BUY | — | 318.50 | 320.43 | +0.6% |
| TTD | 30-Aug | SELL | — | 13.60 | 14.40 | +5.9% |
| IREN | 30-Aug | HOLD | — | 35.60 | 44.43 | +24.8% |
| ASTS | 30-Aug | BUY | — | 58.09 | 62.16 | +7.0% |
| RDW | 30-Aug | HOLD | — | 10.88 | 10.53 | −3.2% |
| OSS | 30-Aug | HOLD | — | 10.30 | 9.97 | −3.2% |
| FLNC | 30-Aug | HOLD | — | 10.92 | 10.33 | −5.4% |
| SHLS | 30-Aug | HOLD | — | 7.25 | 7.12 | −1.8% |
| ENVX | 30-Aug | HOLD | — | 3.38 | 3.31 | −2.1% |
| EOSE | 30-Aug | SELL | — | 3.28 | 3.89 | +18.6% |
| PLTR | 30-Aug | HOLD | 70.6 | 185.50 | 174.40 | −6.0% |
| PDYN | 30-Aug | HOLD | 57.0 | 5.77 | 5.715 | −1.0% |
| BZAI | 30-Aug | STRONG SELL | 27.4 | 0.5194 | 0.4728 | −9.0% |
| QTEX | 30-Aug | STRONG SELL | 22.4 | 0.8228 | 0.8299 | +0.9% |
| GRAB | 31-Aug | BUY | 69.0 | 3.54 | 3.43 | −3.1% |
| TMDX | 31-Aug | HOLD | 61.6 | 83.23 | 90.08 | +8.2% |
| TIGR | 31-Aug | SELL | 41.9 | 5.12 | 5.08 | −0.8% |
| SKYX | 31-Aug | SELL | 37.4 | 1.34 | 1.36 | +1.5% |
| AMTX | 31-Aug | STRONG SELL | 26.1 | 1.85 | 1.82 | −1.6% |
| ONON | 03-Sep | HOLD | — | 27.94 | 27.98 | +0.1% |
| LULU | 03-Sep | SELL | — | 120.58 | 100.31 | −16.8% |

**Not priced and therefore not anchored:** IQE (LSE, 48.20p, 29-Aug HOLD and 30-Aug BUY), SIVE (SEK 27.32, 30-Aug HOLD), VNP (C$25.55, 28-Aug HOLD), 000660 SK hynix (KRW 1,658,000, 29-Aug HOLD), and the ten 16-Aug TSE names. These need a non-US price source before the 12-month check; anchoring them is the first task of the next calibration.

---

## 6 · RE-CHECK SCHEDULE

| Date | Elapsed | What becomes readable |
|---|---|---|
| **04-Dec-2026** | 3 months | Nothing statistical. The blow-up check becomes marginally informative. Confirm no verdict has been quietly abandoned |
| **04-Mar-2027** | 6 months | Direction of the long-short spread; whether the sell-side weakness in F5 persists |
| **04-Sep-2027** | 12 months | **First read with any power.** Blow-up avoidance becomes a real number. Directional hit rate becomes worth computing |
| **04-Sep-2029** | 36 months | **First read at the framework's own horizon.** Interval coverage testable for the first time |

The 12-month check is the one that matters for whether v5.1 is doing its job. Everything before it is housekeeping.

---

## 7 · WHAT CHANGES IN v5.1 AS A RESULT

Three changes, all enforcement rather than doctrine. **No weight, rule or threshold changes** — nothing in this run is evidence about the framework's substance, and changing substance on six days of price data would be exactly the n=1 error the mid-ramp exception was demoted for.

| # | Change | Where |
|---|---|---|
| 1 | Verifier fails any memo whose verdict line lacks a Durability score and printed Entry arithmetic | `grow_verify.py` — new check |
| 2 | A sweep must itemise every name it rates, or state that unlisted names were screened and not rated | CORE section 9, output rules |
| 3 | PROSPER-scale verdicts (BUY/ACCUMULATE/WAIT/REFUSE) are formally superseded. No mapping to the GROW five-point scale is permitted | CORE section 2, change control |

---

*GROW Calibration Ledger · baseline cut 04-Sep-2026 · 53 GROW-scale verdicts anchored, 98 PROSPER-scale verdicts excluded per F1 · prices IBKR live, four independently re-verified (LULU, TTD, AXTI, MU) · this document contains no hit rate and no accuracy percentage, by design · not investment advice.*
