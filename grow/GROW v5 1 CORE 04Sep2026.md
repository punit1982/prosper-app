# GROW v5.1 — CORE
**Signed 04-Sep-2026 · revision 1, 05-Sep-2026 · supersedes v5.0 · the only document read on a standard run**

> **Revision 1 — what the calibration baseline changed, and what it did not.** The 04-Sep baseline could not measure accuracy: median elapsed time was six days against a three-to-five-year horizon. **It changed no weight, no threshold and no rule of judgement**, because six days of price movement is evidence about nothing. What it did find is that **one of the three accuracy commitments was testable immediately, and it failed** — thirteen of the first fifty-three verdicts were issued with no score, and sixty-five more existed only as an aggregate count. Both are permanently outside calibration. Revision 1 therefore adds **rules 20, 21 and 22** — a verdict must be decomposed, a rating list must itemise, and there is one scale — and closes four carried items that needed a decision rather than data: the criteria 5/7 disjointness, the dormancy clock, the archetype-premium falsification test, and the calibration schedule. **Everything else that was open remains open, and §12.3 says when each is answerable.**

> **Read this file every run. Read an annex only when its trigger fires.**
>
> | Annex | Load when |
> |---|---|
> | **A · Companies without history** | Proof stage is S0, S1 or S2, or measurement basis is M6 or M7 |
> | **B · Special measurement bases** | Basis is M2, M3, M4, M5 or M9 |
> | **C · Life sciences** | Gate 1 fires |
> | **D · Evidence and rule register** | Never during a run. Review only |
>
> **What changed from v5.0, in one paragraph.** v5.0 classified a company on one axis — archetype — and scored every company on the same historical inputs. A pre-revenue satellite builder and a mature pipe distributor got the same criteria with the same anchors, and roughly a third of the pre-revenue score was a placeholder rather than a judgement. **Classification is now five axes**, restoring the measurement basis and proof stage that existed in PROSPER v11 and were lost in consolidation. **No criterion is ever scored on a placeholder** — where the evidence does not exist at this stage, the weight is removed and redistributed. And **the single rating is split into two**: a Durability score that contains no price, and an Entry verdict computed from expected return. That split exists because a score containing price was measured falling ten points when a company *rose* 63% on a good result.

---

# §1 · WHAT GROW IS

GROW answers two questions about one company, separately, and never merges them:

**Is this worth owning?** → a **Durability score, 0–100**, containing no price.
**Is it worth buying at today's price?** → an **Entry verdict**, five words plus a price ladder.

It classifies the company on five axes, scores it on the eight things that decide whether a business compounds, prices it against a range rather than a point, and resolves entry by arithmetic rather than by judgement.

**The name:** **G**rowth engine · **R**eal economics · **O**wners and operators · **W**orth.

**Trigger:** `GROW <TICKER>`

| Modifier | Effect |
|---|---|
| `update` / `rebuild` | Force the update or full-rebuild path |
| `screen` | Margin-room screen only, no memo |
| `TICKER, TICKER, …` | Batch — one memo each plus a summary |
| `position` | Add "given what you already own", after both verdicts are set |
| `full` | Print the technical appendix in chat, not just in the file |

**Why two verdicts and not one.** Measured on this project's own names: a score containing price **fell ten points when AXTI rose 63% on a blowout result**, and the same happened on CRDO and PLTR. A number that punishes good news cannot answer "should I stay invested". Separately, **14 of 15 winners never filled a limit 15% below spot** — a framework that requires a discount to spot before it will say anything positive will systematically miss the names it exists to find. The Durability score answers ownership and moves perhaps twice a year. The Entry verdict answers price and moves weekly.

---

# §2 · THE RULES

Nineteen. Break one and the run is defective.

1. **Always produce an answer.** Never "cannot rate". Uncertainty narrows the answer and lowers stated confidence; it never removes it.
2. **Never score with anything un-chased.** Every retrieval item ends as *found* or *the company does not publish it*. The second is a finding. "I didn't look" is not.
3. **Never let a data-provider number fire a mandatory check,** contradict a filing, or be the sole basis of a score. Where the company does not present a line, any check keyed to it is **void**, not failed.
4. **Never change a fixed input** — exit multiple, terminal margin, fade years, probabilities, peer set, classification — **without a ledger note naming the fact, the document and the date.** Same facts, same score.
5. **Never move a score without a row in the change table.** If the total moved and the table is empty, the run is invalid and the prior score stands.
6. **Never carry a price.** Re-pull it and cross-check it against a second source. **If the primary feed will not resolve, use the exchange's own quote page or the company's investor-relations page, and name which was used. A rating is never withheld for want of a price** — but a price older than the last completed session is marked **stale** in the call line, and confidence drops one level.
7. **Never use mid-cycle normalisation on a technology-franchise name.**
8. **Never set a drug-approval probability by hand.** Use Annex C.
9. **If a licence royalty is not disclosed, use 15% of net sales plus 20% of gross milestones and say so in the call.**
10. **Margin level is not quality.** A high margin means you are paying for it and there is less room left. Score the gap, never the level.
11. **One Durability score and one Entry verdict on the page. Never two of either.**
12. **Plain English.** No internal vocabulary reaches the reader — see §10.1. But the reader must be able to reproduce it: arithmetic, weights, the classification path and the change since last run are all printed, in the appendix.
13. **Position-blind by default.** No holding, cost basis or weight is read unless `position` is passed, and then only after both verdicts are fixed. **Enforcement is by check, not by claim** — the file is searched for holding, cost-basis and weight language before it is issued, and the certification line is written after the search passes, never before.
14. **Never invent a rule mid-run.** Log it for the review.
15. **A retrievable fact may never be estimated.** Share count, cash, debt balances, facility sizes, filing dates and any figure printed on the face of a filing come from the filing — never from a data aggregator, and **never by back-solving from market capitalisation or from a per-share figure.** Where the filing has not been opened, the memo says so and **the affected number may not be used to set a price.**
16. **No named comparable, no multiple.** Every terminal or exit multiple names a real company, its multiple, its growth rate and the date measured, **matched on growth within ±5 points of the subject's modelled final-year growth and on business layer.** Where no company trades at a comparable growth rate, **that is the finding**: name the closest, state the growth gap in points, state the adjustment. **Where no comparable can be named at all, the memo says so in the call line, the valuation is built on cash flow rather than on a multiple, and confidence drops one level.**
17. **Stated is not sourced.** Every input to the destination value is classified A, B or C under §6.1 before it is used. **A forecast input that was invented rather than derived is the single most expensive error this project has recorded** — a six-name batch was rebuilt after a destination revenue figure was assigned from nothing, below published consensus, and the run did not know.
18. **The Entry verdict never drives a sale.** A name that has become expensive is a name you stop buying. Sales come from the Durability verdict breaking, or from a break trigger firing — **never from the price having risen, and never from elapsed time.** Measured: a thirty-six-month time stop destroyed six of seven winners; one sat at 1.11× before returning 16.8×.
19. **Every rule in this document carries its provenance.** A rule with no recorded origin cannot be defended at a review and is a candidate for suspension. See §12.
20. **A verdict that is not decomposed is not a verdict.** Every rating printed anywhere — a full memo, a batch summary row, a screen line, a one-line update, a chat reply — carries **the Durability score and the Entry arithmetic that produced it**. A bare word is not permitted at any length. *Measured 04-Sep-2026: thirteen of the first fifty-three verdicts were issued bare. None of the thirteen can be calibrated, because there is no way to ask later whether the score or the price drove the call.*
21. **A rating list itemises every name it rates.** A sweep, screen or batch prints **one row per rated name — ticker, Durability, Entry, price, date** — or states explicitly that the unlisted names were screened and not rated. **An aggregate count of ratings is not a record of them.** *Measured 04-Sep-2026: a 107-name sweep rated 93 names and itemised 28. The other 65 verdicts cannot be reconstructed and are permanently outside calibration.*
22. **One scale, and it is this one.** The only permitted verdict words are **STRONG BUY · BUY · HOLD · SELL · STRONG SELL**. Any verdict issued on a superseded scale — including PROSPER's `BUY / ACCUMULATE / WAIT / REFUSE` — is **not a GROW verdict, is never pooled with GROW verdicts, and is never mapped onto this scale.** A name carrying only a superseded verdict is treated as unrated and re-run. *A mapping invented after the fact is a fabricated verdict.*

---

# §3 · HOW A RUN WORKS — nine steps, in order

**1 · Resolve the ticker, then load the ledger.** **Before anything else, resolve the ticker to one legal entity, one exchange and one listing, and print it.** Where a ticker maps to more than one listing, name every candidate and state which was taken and why. **Where it cannot be resolved to a unique company, the run stops and asks.** A memo on the wrong company is worse than no memo.

**Then the continuity test, in the same breath.** **Where, inside 24 months, the company has changed its name and its stated primary business, or has acquired the assets that now produce most of its revenue, the entity is continuous but the business is not.** Then: prior financial history is evidence for criterion 8 and for integrity only — **not for the margin-room "own best full year in ten", not for the pre-transition quarters of the guided-versus-delivered table, not for the peer set** · the archetype is decided on the new business alone · the traction ledger starts at the transition date · confidence drops one level · and **the memo names the former business and the date it stopped, in section 1.**

Then find `<TICKER> LEDGER.md` and any prior memo. Ledger → update. Prior memo only → build the ledger from it first. Neither → new build. Then scan this project's chat history for anything on the name that never reached a file.

**2 · Classify on all five axes (§5), and print all five.** The axes decide which annexes load, which inputs are meaningful, and which criteria can be scored at all. **Nothing is modelled before this step.**

**3 · The inflection test.** Six observables, checked before scoring:

| # | Observable | Typical lead on revenue |
|---|---|---|
| 1 | Forward book (backlog, remaining performance obligations, deferred revenue, bookings) growing faster than revenue, two quarters running | 1–8 quarters |
| 2 | Gross profit growing faster than revenue, two quarters running | current |
| 3 | A named customer or design win with a **dated** start of production | 4–12 quarters |
| 4 | A capacity or capability commitment **funded by a customer** — prepayment, reservation fee, tooling contribution | 2–8 quarters |
| 5 | Guidance raised twice within four quarters | 1–4 quarters |
| 6 | Unscheduled open-market buying by an operating executive, or three or more insiders together | varies |

**The same six observables run backwards are a negative inflection**, and are checked in the same pass: the forward book shrinking against revenue · gross profit growing slower than revenue · a design win or programme lost · a customer commitment withdrawn or not renewed · **guidance cut** · insider selling beyond scheduled plans. **Two or more present means the traction criterion is scored on the deterioration, and every break trigger is re-tested in this run rather than at the next one.**

**Forward book means obligated money.** Only amounts a counterparty is contractually obliged to pay count in observable 1, in criterion 7, or anywhere else. **Ceiling value, IDIQ capacity, unexercised options, total programme value, framework agreements, letters of intent and memoranda of understanding are named on their own line, scored zero, and never added to backlog.** *"A $2.9m option exercised under a $10.6m programme" is backlog of $2.9m.*

**And a loan book is not a forward book.** **Where a lending book has grown more than 50% in twelve months it is unseasoned by construction**, its own arrears rate is not evidence, and criterion 7 is scored on the book **net of losses at a seasoned comparable's through-cycle rate, named and sourced.** Deposits funding it are a liability, not traction.

**Two or more present = the test passes.** A dated, disclosed forward number is retrieved evidence, not a company assertion, so it is exempt from the ≤8 cap in §7.3.

**4 · Retrieval sweep — a hard gate.** Work the §6 list to *found* or *not published*, classifying every input A, B or C. **No criterion may be scored while anything is un-chased.** Re-pull always: price and anything whose refresh date passed or whose trigger event occurred. Carry everything else from the ledger.

**5 · Margin room.** The construction below is the one part of this framework with evidence at three separate start dates. **It is scored on the gap, never on the level.**

```
Margin room = Achievable operating margin − Current operating margin   (points)
Achievable  = the LOWEST of: the company's own best full year in ten
                             the peer median at comparable size
                             management's published plan with a stated mechanism
```

**For measurement bases other than M1, the term "margin" is replaced by that basis's own economic measure — see Annex B. For proof stages S0–S2 the anchors do not exist and Annex A governs.**

Then the **mechanism test**. A gap scores above 5 only where the mechanism is **named, dated and structural**: a disclosed mix shift, an announced price rise with an effective date, a cost base permanently removed with the charge taken, fixed-cost absorption on capacity already built and paid for, or a product generation with a disclosed margin profile and a start date.

**Not mechanisms:** "operating leverage", "scale", undelivered acquisition synergies, "the category will mature", or any margin neither the company nor a named peer has earned at this size. **And three consecutive years of margin expansion is not a mechanism** — it is the record of a mechanism that may or may not still be running.

**Score the gap:**

| Margin room, with the mechanism test applied | Score |
|---|---|
| **20 points or more**, mechanism named and dated | **10** |
| **12 up to 20**, mechanism named and dated | **9** |
| **6 up to 12**, mechanism named and dated | **7** |
| Any gap, **mechanism not named** | **5** |
| **Above 0 and below 6**, mechanism named | **3** |
| **0 or below — the company is at or above the best margin it or its peers have earned** | **1** |

**The bands do not overlap. A room of exactly zero scores 1, not 3.**

**The bottom row is the peak detector.** A company earning more than its own history and more than its peers has nowhere left to go, and its return must come entirely from revenue growth or a re-rating. **Say so in those words.**

**One exception to the peak detector, and only one — and it is provisional.** **Where operating margin has expanded in each of the last three years and management has published a plan with a named mechanism, the "own best full year in ten" input is dropped**; achievable becomes the lower of the peer median at scale and the published plan. **The detector still fires whenever the current margin is at or above the peer median.**

> **This exception is capped at 7 and marked PROVISIONAL.** Added 31-Aug-2026 from one company; a two-era backtest has since found no predictive power in prior margin expansion, and a mid-ramp company that lost 41%. Retained because deleting it re-opens the defect it closed. **Where it is used, the memo prints the words "provisional rule applied" and confidence drops one level.** Decision due 28-Feb-2027.

**Three caps:**
- **Where the achievable margin is itself negative, room scores 5 at most.**
- **Where the conversion test cannot be run at all** — half-yearly reporting, no interim operating income — **room scores 8 at most, and no penalty is applied.**
- **Where the company has no revenue, Annex A governs and this criterion is not scored here.**

**And the pass-through rule.** **Revenue the company books gross for hardware, components or services it resells substantially unchanged is not the same revenue as its own product.** Where it exceeds a third of trailing revenue, every number that touches revenue is computed twice and **the own-product figure governs**: the achievable margin and the peer median · the growth-quality table · the forward book · and the multiple. **Criterion 5 is capped at 5 until the pass-through share has been below a third for two consecutive quarters.** The memo prints the pass-through share.

Then the **conversion test**: incremental margin = Δ operating income ÷ Δ revenue, over 4 and 8 quarters. Above 2× the current operating margin, **add 1**. Between 1× and 2×, no adjustment. Between 0 and 1×, **subtract 1**. **Negative while revenue rises, cap room at 3.**

**6 · Three checks, any of which can stop the valuation.**
- **Earnings quality.** Print operating income, net income and operating cash flow side by side. Explain any gap above 15% (income) or 25% (cash). Until both are explained, no earnings multiple may be primary.
- **Margin bridge.** Where margin moved more than 3 points **on the company's own presentation**, bridge it step by step with management's verbatim explanation and a **reversible-or-permanent call on every step.** A mix shift down is permanent and the terminal margin must fall.
- **Growth quality.** **"Absolute profit" means operating profit, and "gross profit" means gross profit. The two are read together and never interchanged.**

| Pattern | Verdict | Effect |
|---|---|---|
| Revenue up, gross profit up faster, absolute profit up | Growth is earned | none |
| Revenue up, gross profit up slower, absolute profit up | Growth is diluted | economic engine capped at 7 |
| Revenue up, absolute profit down | **Growth is being bought** | capped at 5; terminal margin may not exceed the current actual |
| Revenue down, absolute profit down | **The business is shrinking** | capped at 3; terminal margin may not exceed trailing actual |

**And the dilution pre-computation, mandatory before any share-count test runs.** **Split-adjust the entire share-count series, and put shares issued as acquisition consideration on their own line.** Print the reconciliation — raw count, split factor, acquisition shares, organic count. *A six-for-one split was once read as issuance and rejected a name that passed every other test; fifteen names have been wrongly rejected this way. You were not diluted — you bought a company with it.*

**7 · Build the destination.** On the §5 method for the archetype, with the measurement basis governing which numbers are used. **Never use mid-cycle normalisation on a technology-franchise name.**

**The valuation date is a fixed calendar date, not "five years out", and the horizon `n` is the year fraction from today to that date, computed and printed — never asserted.** *A batch once asserted n = 5.00 against a destination explicitly dated 2031, which was 5.396 years away; the 7.9% error in the exponent moved every level and flipped one verdict.*

**Build the four cases: Break · Bear · Base · Bull.** Each states its own revenue, margin, multiple, share count and debt. **Break is the thesis being wrong, not a milder bear — if the bear case still lands above today's price the model is doing no work and a genuine Break case is required.** Where the upside comes from leverage rather than from a mispriced business, say so and discount it.

**The growth path is anchored on a named cohort.** Revenue growth to the valuation date is anchored on a named cohort: companies that crossed this company's current revenue scale and are now five or more years past the crossing. **Print every member, its crossing date, its revenue and growth today, and the cohort median, mean and dispersion.** **If the base case decays slower than the cohort median that is permitted, but it must be justified in writing and the memo must state what the median would have produced.** Generosity is allowed; hidden generosity is not.

**Management's own guidance is an input only while it has been worth something.** **Where the company has missed a full-year guide by more than 25%, or cut one mid-year by more than 25%, inside the last four quarters, forward guidance is not an input to the central case.** The central case is built on delivered run-rate; the company's number is printed as the Bull case and labelled as management's; and **criterion 8 is capped at 4 for the four quarters that follow.**

**And a guide is only comparable to a guide of the same thing.** **Where the definition of a guided figure changes, restate the record onto the new definition, or mark the comparison broken and say so.**

**And test the shape of any guide that has been reiterated rather than raised.** Where a reiterated full-year figure requires a second half **more than 40% above the first half**, compute the implied step-up, print it, and **score criterion 8 on whether the obligated forward book actually covers it.**

**Count the shares the way the next buyer will.** Every case uses the **fully diluted** count: shares outstanding **read from the filing cover page** under rule 15 **plus pre-funded warrants and anything else exercisable at a nominal price, which are shares already**, plus warrants, convertibles and earnouts in the money at that case's own price. **Where two or more equity raises have closed inside twelve months and the latest was priced below the one before it, criterion 4 is capped at 3.**

**And cash inside a regulated subsidiary is not the group's cash.** **Netted against enterprise value only to the extent the filing states a distributable surplus above the regulatory minimum; where it does not, it is excluded and the exclusion is printed with its amount.**

**Where net debt exceeds 1.5× EBITDA the debt is built, never picked** — constructed from the filing's own repayment table plus a year-by-year cash-flow ladder, with free cash flow allocated on management's stated priority order. **Validation, mandatory: run the same ladder on the current guided year and print the variance against company guidance. A ladder that cannot reproduce this year's guidance cannot forecast the destination.** Refinancing inside the horizon is modelled explicitly, at a higher rate in the downside case.

**Check the arithmetic of growth before using it: growth = reinvestment rate × return on invested capital.** A growth rate the company's own reinvestment and returns cannot produce is arithmetically incompatible, and the memo says so rather than modelling it.

**8 · The joint-conservatism check — three limbs, each tested and printed.** (a) Is base growth below trailing realised? (b) Is the terminal margin below the current actual? (c) Is the terminal multiple below the company's own listed-history low? **If all three fire, the base case is stacking down-bets and must be re-derived.** If two fire, print the flagged limb's sensitivity and state whether the verdict changes when that limb returns to the observed value. **The converse also applies: if the base case contains two or more optimistic inputs, compute and print the variant holding them at conservative values.**

Then the range: 40,000 draws, exit multiple lognormal with sigma from the comp set's coefficient of variation — floor 0.12, or 0.20 with fewer than four matched comps, cap 0.60. Produce expected return, the odds of clearing the required return, the odds of losing money, and the 10th and 90th percentiles.

**Where today's multiple is above the highest in the comp set, the comp set cannot describe its dispersion.** Then sigma comes from **the name's own multiple over the last three years, floored at 0.35**, and the memo says the name is priced outside its comparables. **Either way, split the central case into the part the business delivers and the part that requires today's multiple to hold; where more than half is the multiple, drop confidence one level and write the sentence: "this is a bet on the rating the market gives it, not on the company."**

**9 · Resolve both verdicts by §8, then write three to six break triggers** — each citing a number the company actually publishes, each stating what it would do to Durability. **A trigger citing a metric the company does not publish is not a trigger.** Mark every trigger from the prior run *happened · did not happen · not yet testable*; one that fired is examined on its facts and, if judged not to be a break, **re-set with its new threshold stated, never quietly dropped.** Then write two files.

---

# §4 · COST OF CAPITAL

```
Required return = risk-free rate + equity risk premium + archetype premium
```

| Input | Value | Source |
|---|---|---|
| US 10-year Treasury | **4.70%** | Trading Economics, 14-Aug-2026 |
| Implied equity risk premium | **4.23%** | Damodaran, 01-Jan-2026 |
| **Base cost of equity** | **8.93%** | |

Restated on the first business day of each quarter, or on a 50bp move in the ten-year. **This is maintenance, not amendment.** Print the build, never a bare number.

**Standing caution, printed in every memo.** The archetype premiums have no derivation. The archetype choice has been observed to move an answer more than a full quarter of company news. **Every memo prints what the Entry verdict would be under the runner-up archetype.** This is the framework's deepest unresolved problem and it is mitigated, not fixed.

**What would refute the premiums, stated so the claim is falsifiable.** The premium ladder asserts one thing and only one: **that outcome dispersion rises monotonically down the ladder** — a binary-unlock name is wider than a category creator, which is wider than a cyclical, which is wider than a toll-taker. **That ordering is testable and is dated to the 12-month calibration (04-Sep-2027):** rank the realised 12-month dispersion of the rated names by archetype and compare the ranking to the premium ranking. **A rank correlation below +0.5 refutes the ladder and the premiums are re-ordered to the observed ranking.** Until that date the premiums remain what they are — reasoned constants, mitigated by the runner-up print — but they are no longer unfalsifiable, which was the substance of the objection.

---

# §5 · CLASSIFICATION — FIVE AXES

**All five are set before any number is modelled, and all five are printed in the memo header.** Archetype says what kind of business it is. Measurement basis says which numbers are meaningful. Proof stage says which criteria can be scored at all. The regime factor says which way the multiple is drifting. The horizon says over what period.

## 5.1 · Axis 1 — archetype: the tree, first match wins

> **Every number a gate reads is taken before disclosed one-off items, and the adjustment is named.** **An archetype decided by a one-off is an archetype decided by noise.**

> **And separate the money that came from the state before any gate reads a number.** **Government production credits, subsidies, grants and transferable tax attributes recognised inside revenue or gross profit are stripped out first, and every gate is decided on what remains.** **Where the classification changes once the credit is removed, take the branch without it, print both, and drop confidence one level.** The expiry year of every credit relied on goes in the memo.
>
> **Where a gate's input cannot be determined at all** — **take the branch the retrievable evidence best supports, name the input that could not be determined, print the score under both branches, and drop confidence one level.** Never guess a gate silently.
>
> **And within a gate, the branches are read in the order printed and the first that matches wins.**

**Gate 0 · Composite.** No single segment is more than 60% of value **and** the segments would classify under different archetypes → **G1**. *Value each segment under its own archetype, sum, subtract holding-company cost and a stated discount. See Annex B.*

**Gate 1 · Life sciences.** Value primarily a therapeutic, device or diagnostic needing regulatory approval?
→ Approved product worth >30% of value: **H3** (drug) or **H4** (device/diagnostic) · A technology with ≥3 independent programmes: **H1** · One molecule, ≤3 indications: **H2**

**Gate 2 · Sub-scale option.** Revenue under $25m or gross profit negative, value gated on something that hasn't happened?
→ A dated discrete event: **D3** · One technology transition: **D2** · A market that doesn't exist yet at scale: **D1**

**Gate 3 · Scaling technology.** Revenue growth ≥40%, operating margin below zero, **and gross margin ≥35% or expanding ≥3pp a year** → **T4**

**Gate 4 · Cycle.** Selling price set by a market the company doesn't control → **E1** · More than 30% of demand created by subsidy, tariff or mandate → **E2** · More than half of revenue is customers' capex **and the end market is not in secular expansion** → **E3**

> **The secular-expansion test, binding.** A market is in secular expansion where a named third party has it compounding above 15% for three years or more **and** the company's forward book is growing faster than its revenue. Where both hold, the company is **not** a cyclical, **mid-cycle normalisation is forbidden**, and the tree continues.

**Gate 5 · Inflection.** The §3 test passed on two or more while the reported P&L is flat or falling → **F5**

**Gate 6 · Repair.** Three consecutive periods of margin expansion on flat revenue → **F1** · New management, dated plan, business recently better → **F2** · Over 30% of three-year growth acquired → **F3** · **Revenue growth has at least halved against its three-year average or turned negative, AND the multiple has de-rated more than 40%** → **F4**

> **F4's test is stated in numbers because the words were ambiguous. The multiple breaking and the business breaking are different events, and only the growth test separates them.**

**Gate 7 · Infrastructure.** Owns capacity rented to others? ≥70% contracted, average contract ≥5 years, investment-grade tenants → **C3**; otherwise → **C4**

**Gate 8 · Bottleneck.** Fewer than three qualified alternatives, qualification measured in years, and a price rise held through a downturn? → **T3** if the end market is in secular technology-driven expansion, else **B1** · Owns the standard or protocol → **B2** · Holds a scarce permission → **B3**

**Gate 9 · Recurring.** Contracted or repeat revenue with disclosed retention? Software or platform → **T1** · Consumer repeat purchase with pricing power → **A2** · A fee on volume it doesn't control → **A3**

**Gate 10 · Supplier.** Revenue is the customer's capex or bill of materials? Designed in, with named customers, dated start of production and disclosed content per unit → **T2** · Sells the primary equipment → **C1** · Supplies those who do → **C2**

**The tie-break, in this order and no other.**
1. **Resolve on the fact: where does the gross profit actually sit?** That identifies which business this is, and it is an observation rather than a policy.
2. **If the fact does not resolve it, take the archetype with the higher required return.** A lower required return discounts less and produces a higher entry price; taking the lower one flatters the call. *This rule shipped stated backwards once and moved one name's level from $419 to $479 — two sell rungs on a name trading at $895.*
3. **Print the runner-up and the Entry verdict it would have produced, always.**

**And the forward limb: the trailing test proposes, guidance disposes.** Every assignment test above reads backwards. **Where company guidance for the next reported period contradicts the trailing direction on that archetype's own defining term, the archetype is reassigned and the contradiction is printed.** *A company was routed to Margin Inflection on a trailing margin moving +11.1pp a year, on the same day it guided that margin flat.* **This limb can flatter; where it moves a verdict up, that is recorded and reviewed.**

## 5.2 · Premiums, profiles and valuation methods

**Read the two rows for the assigned archetype and its runner-up from `GROW v5 1 ANNEX E ARCHETYPE LOOKUPS.md`** — premium, required return, weight profile, primary valuation method and the method forbidden for that archetype. The other twenty-eight rows are not read.

**Three rules override the table and are read every run.** Loss-making at the net line -> no P/E method may be primary. Mid-cycle normalisation is permitted **only** for E1, E3, C1 and C2. Every terminal multiple obeys rule 16.

## 5.3 · Axis 2 — measurement basis

**Assigned by its stated trigger and by nothing else — never by theme, never by sector, never by which cluster the name sits in.** *Two optics companies were once assigned the capacity basis because they were AI-infrastructure names; both failed its trigger, and the one company in that complex that does publish capacity in units was not on the list at all.*

| | Trigger | Margin room runs on | Growth runs on | Cash test | Annex |
|---|---|---|---|---|---|
| **M1 · Standard** | Normal P&L, revenue >$50m | Gross and operating margin room + named mechanism | Revenue | OCF ≥ NI | core |
| **M2 · Lender** | Lending assets >25% of total assets | Return on tangible common equity vs own range and stated target; mechanism = efficiency ratio | Revenue, **cycle-base guard almost always applies** | Pre-provision profit vs net income, **and charge-offs vs provision** | B |
| **M3 · Capacity** | Fixed assets >40% of total assets, or the business sells capacity | **Unit economics at full utilisation versus today** — cost per MW, per wafer, per rig-day | Revenue **and volume, both printed** | OCF ≥ NI **plus the maintenance-versus-growth capex split** | B |
| **M4 · Real estate / NAV** | Development or investment property >50% of assets | Development margin and yield-on-cost vs own range; mechanism = mix shift recurring versus trading | **Recurring income, not total revenue** | Collections vs recognised revenue; backlog conversion | B |
| **M5 · Resource** | Sells a quoted commodity at spot | **Unit cash cost against the industry cost curve**; mechanism = grade, strip ratio, recovery | **Volume, never revenue** — revenue is a price artefact | OCF ≥ NI at mid-cycle price, **not spot** | B |
| **M6 · Pre-revenue** | Revenue <$10m | **Not scored. Weight removed and redistributed** | Two of three contracted, funded or dated milestones met in twelve months | Runway ≥18 months **and the dilution schedule printed** | A |
| **M7 · Early commercial** | Revenue $10–50m | **Gross-margin direction over four quarters. The level is ignored** | Revenue ≥1.6× over three years | **Burn per incremental revenue dollar falling** | A |
| **M8 · Mature** | Revenue >$1bn and growth <5% | Margin and return on capital vs own ten-year range | Revenue, cycle-base guard | OCF ≥ NI | core |
| **M9 · Composite** | Gate 0 fired | **By segment, each on its own basis** | By segment | By segment | B |

**The computability limb, and it binds.** **A basis whose mandated checks the company does not disclose is not eligible for that company. Fall back to M1, and print `FALLBACK to M1 - mandated checks not disclosed`, naming the missing disclosure.** *A rule that cannot be computed cannot govern.*

**Entry ceilings by basis: M6 caps at BUY. M7 caps at STRONG BUY only where the forward engine is evidenced under Annex A; otherwise BUY.**

## 5.4 · Axis 3 — proof stage

**What evidence exists yet. This decides which criteria can be scored at all.**

| | Test | Effect |
|---|---|---|
| **S0** | No revenue, or revenue not from the business being valued | Annex A governs criteria 5, 6, 8 and 9 |
| **S1** | Revenue exists; gross profit negative or immaterial | Annex A governs criteria 5 and 6 |
| **S2** | Gross profit positive; operating loss | Annex A governs criterion 5 |
| **S3** | Operating profit positive for fewer than three years, or listed under three years | Own-history anchors unavailable; peer anchors only |
| **S4** | Three or more years of positive operating margin **and** three or more years listed | Full historical machinery valid |

**The five-year scale test, stated pass or fail in every S0–S2 memo:** *will this be a real business at the valuation date, or is this a venture bet?*

## 5.5 · Axis 4 — regime factor

**A multiplier on the terminal multiple only. It never enters the Durability score.** Capped at ±15%, never outside the comp range, and it sits inside the mandatory ±25% multiple stress, so it can never on its own make or break a verdict.

**Why it may never score.** Membership of a correct megatrend was tested and found worthless as a predictor: **eleven cases carried a completely correct theme and lost between 78% and 97%.** Solar scaled, telehealth became normal, remote work became permanent, and the equities were destroyed anyway. The regime factor adjusts what a buyer will pay for a given stream of profits. It says nothing about whether this company will earn them.

**If the theme has no assigned row, the factor is not invented and not defaulted to a neighbouring row** — it is set to ×1.00, flagged as a coverage gap, and queued for the next review. *Applying an adjacent row by default once moved one name's price by 13.6%, enough to flip fair into rich. Five coverage gaps were found in three days; the gap is the normal case.*

## 5.6 · Axis 5 — horizon

**`n` = the year fraction from the run date to the destination's own target date. Computed, printed, never asserted.** The archetype's horizon band is a constraint on which target year is legitimate, not a source of `n`. A destination dated outside the band is rebuilt, not discounted anyway. **For D3 and H2, `n` runs to the dated event, floored at one year; a name with no dated event is not a binary unlock.**

---

# §6 · RETRIEVAL

## 6.1 · Classify every input before deciding anything

| Class | Definition | Treatment |
|---|---|---|
| **A · DISCLOSED** | Exists today in a document — share counts, debt balances and maturities, cash, covenants, strikes, contract terms, segment splits, guidance as issued | **Retrieve it. Estimation prohibited. Back-solving from market value prohibited** |
| **B · DERIVABLE** | Not a single printed figure, but constructible from Class A items plus a schedule, a published algorithm or a stated policy | **Build it and show the build.** A round number in place of a build is a defect |
| **C · FORECAST** | Genuinely future, with no schedule and no company algorithm behind it — terminal multiple, final-year end-market growth, competitive outcome | **Judgement permitted.** Bounded, sensitivity printed, comp-evidenced where it is a multiple |

**Only Class C rows count as judgement anywhere in this framework. A Class A or B input appearing as judgement makes the memo defective — it is withdrawn and re-run, not downgraded.**

## 6.2 · The source ladder — run in order, stop when found

| Tier | Source | Mandatory targets |
|---|---|---|
| 1 | **Primary filings** | Cover-page share count · balance sheet · **debt note including the year-by-year repayment table** · covenants · dilution note · segment note · subsequent events |
| 2 | **The company on the record** — transcripts, deck, IR releases | Long-term targets **and the algorithm behind them** · capital-allocation priority order |
| 3 | **Exchange, regulator or registry** for non-SEC filers | Local equivalent of Tier 1 |
| 4 | **Computed from Tiers 1–3** | **Recomputed every run. Never carried** |
| 5 | **Aggregators and press** | **Confirmation only. Never the sole source for a number that sets a price** |

## 6.3 · The exhaustion test and the negative-retrieval log

A Class A or B input may be downgraded to C **only** after the applicable tiers are searched and this line is printed:

> `NOT FOUND — [input]. Searched: [documents, by name]. [What is and isn't disclosed]. Downgraded to Class C. Omission is conservative because [reason].`

**An unlogged "judgement" is a defect. A logged negative is a finding and is fully acceptable.** The standard is not omniscience; it is that the search happened and its result is on the record.

**Depth is never budgeted.** Search ceilings govern breadth — how many names, how many angles — never depth on a load-bearing input. **If a run must be truncated, drop names. Never estimate a retrievable figure.**

## 6.4 · Universal core, 40 items

*Every scored criterion must have a line here. A criterion with no retrieval rule is a criterion scored on nothing.*

**The business itself (criteria 1, 2, 4)** · what it sells, in two sentences for someone outside the sector · **revenue by segment and by geography, with percentages** — if one line is over 60%, say so, that line is the company · **where it sits in the chain: who supplies it, who buys from it, and who could go around it** · **at least three named competitors with their revenue or share** · **the specific end-market spending line its revenue depends on, its size and growth rate, with a named third-party source** · **the share of revenue exposed to that line, and the share sitting in a shrinking legacy line** · patents that matter with expiry dates · technical lead measured in something — benchmark, yield, cycle time, approvals held · what replication would cost a well-funded competitor, in money and years · penetration of the addressable pool and the growth achievable at this size.

**Durability (criterion 3)** · gross and net revenue retention where disclosed · switching cost in money and months · market share and its three-year direction · **number of qualified alternatives and the customer qualification time** · **whether a price rise was achieved and held through a demand downturn**.

**The forward book (criterion 7)** · **backlog, remaining performance obligations, deferred revenue, contract liabilities or bookings — the figure, its year-on-year change, and the share converting inside twelve months** · book-to-bill and its four-quarter trend · **design wins by named counterparty with a dated start of production** · **customer prepayments and capacity reservation fees** · qualification passes · announced price rises not yet in reported revenue.

**What people say (criterion 2)** · customer review platforms — rating, trend, count, and the content of the worst reviews · employee platforms — overall, leadership approval, trend, attrition or reorganisation mentions. **Where no consumer platform exists, the business-to-business substitute is used and the line is marked, never left blank.**

**The people (criterion 8)** · **the chief executive's and finance director's prior roles and what happened to those businesses, with numbers** · tenure and executive turnover over three years · whether the founder is still involved · **what management is actually paid to achieve, and whether that matches what shareholders need**.

**The numbers and the register (criteria 5, 6, 8), 28 items.** Legal entity and filer type · shares outstanding **from the filing cover page** · price with timestamp, source and contract id · **price cross-check from a second source** · market cap and enterprise value · average daily traded value · short interest and trend · revenue 3–5 years · **organic** revenue · gross margin by year and last four quarters · operating and net margin, GAAP · operating cash flow · free cash flow · **net income to operating income bridge** · **net income to operating cash flow bridge** · return on capital against cost of capital and the direction of the spread · share count 3–5 years, **split-adjusted, with acquisition consideration on its own line** · **debt with the year-by-year maturity schedule**, covenants and fixed/floating · cash, committed undrawn facilities, months of runway · **dilution: convertibles, warrants, earnouts with count, strike, expiry** · current and next-year guidance as issued · **the eight-quarter guided-versus-delivered table** · analyst distribution with count and date — **and two to four analysts with a demonstrated prior record on this name or sector, named and weighted above the mean** · **customer concentration from the latest filing** · insider transactions **split open-market versus scheduled** · institutional ownership and direction · **the peer set with each member's multiple, growth rate and measurement date** · the integrity search and what was checked.

**Mandatory triggers — conditions that force a document open.** **If a trigger fires and the document is not opened, the memo says so in the call line and confidence drops to "this is a close call".**

| If this is true… | Open this before concluding anything |
|---|---|
| Net debt above **1.5× EBITDA** | The **full maturity schedule by year**, covenants, fixed/floating split, weighted average rate, **and the mandatory-prepayment terms** |
| Free cash flow negative, **or** capital spending above 50% of revenue | The **funding plan**: cash reconciled to the filing, committed facilities, customer prepayments, expected issuance |
| Net income differs from operating income by more than **15%** | The reconciliation — tax, interest, one-offs, minority interests |
| Net income differs from operating cash flow by more than **25%** | The cash-flow bridge |
| Gross or operating margin moved more than **3 points** either way | **Management's own explanation, verbatim, with its date** |
| The forward multiple is **above** the trailing multiple | The consensus earnings path, and what is expected to fall |
| Revenue growth above 25% **while gross margin falls** | Segment and mix disclosure, and unit economics if published |
| An acquisition contributed more than **10%** of revenue growth | **The organic growth figure, separately stated** |
| Convertibles, warrants or earnouts outstanding | The dilution note: count, strike, expiry, in or out of the money |
| A regulator, court or exchange action exists | **The primary filing or docket entry**, never press coverage |
| Customer concentration above **25%** of revenue | The concentration note **from the latest filing** |
| Cash plus committed undrawn facilities below **one quarter of operating costs** | The liquidity note, the covenant tests, and **the date by which the money must be found** |
| Debt classified as **current above 50% of total debt** | The refinancing plan and the lender's stated position, **from the filing** |
| Recently listed or sponsor-controlled | Lock-up terms, registration rights, sponsor holdings, the prospectus |

**The chronic-gap rule.** A trigger that fires and whose document is not opened costs one level of confidence, once. **Where the same document has gone un-opened in three consecutive runs of the same company, that is a standing condition of the analysis.** It is named in the call section as a risk in its own words, confidence is capped at *"this is a close call and I could be wrong"* regardless of the odds, and the ledger records the run numbers. *A company carrying $7.59bn of debt had its maturity schedule un-retrieved in three consecutive memos, and no run told the reader it had happened before.*

**Plus, by archetype: read the one row for the assigned archetype from `GROW v5 1 ANNEX E ARCHETYPE LOOKUPS.md`.** The other twenty-nine rows are not read.

---

# §7 · THE DURABILITY SCORE

## 7.1 · Eight criteria. Price is not one of them.

| # | Criterion | Scored on |
|---|---|---|
| 1 | **Market pull** | Is the end market growing structurally, what share of revenue is exposed, is it third-party evidenced |
| 2 | **Product and customer evidence** | What it owns technically, independent assessment, customer scores and their direction, churn |
| 3 | **Moat and bottleneck** | Retention, switching costs in money and time, share direction, qualified alternatives, **price rises held through a downturn**, **whether the moat appears in a disclosed number or only in narrative** |
| 4 | **Runway and optionality** | Penetration, growth achievable at this size, adjacent vectors with evidence not slideware. **The current growth rate earns nothing — it is anti-predictive** |
| 5 | **Margin room** | §3 step 5. The gap, the mechanism, the incremental margin. **"Conversion" here means revenue converting into profit and nothing else** |
| 6 | **Economic engine (realised)** | Organic growth, **cash conversion**, return on capital against cost of capital and the spread's direction, survival through a bad outcome, dilution. *Margin level is not scored here* |
| 7 | **Traction** | Forward book size, growth and the disclosed share converting inside twelve months; **realised book conversion over four quarters**; book-to-bill; dated design wins; customer prepayments; qualification passes; cohort expansion. **"Book conversion" means order book converting into revenue and nothing else** |

> **Criteria 5 and 7 are disjoint by construction, and this was checked.** Criterion 5 reads margin — the gap to achievable, the named mechanism, incremental margin. Criterion 7 reads the order book — backlog, design wins, prepayments. **No observable appears in both.** The word *conversion* formerly appeared in both with two different meanings and has been disambiguated above; that ambiguity, not shared evidence, was the double-count risk. **What remains open is a weighting question, not a double-count**: whether margin room deserves 22 points in the repair profile P8 when past margin change has shown no predictive power. That is a calibration question and is dated in §12.3.
| 8 | **Operator credibility** | Guided-versus-delivered over eight quarters, executive record with numbers, capital allocation evidenced by transactions, **control environment — auditor findings, material weaknesses, restatements**, employee sentiment, insider and institutional behaviour |

**Worth is not a criterion.** Price lives entirely in the Entry verdict in §8. *A score containing price was measured falling ten points when a company rose 63% on a good result.*

## 7.2 · No placeholders. Evidence-weighted scoring.

**Where a criterion has no evidence at this company's measurement basis and proof stage, its weight is removed and redistributed pro-rata across the criteria that can be scored, and the memo prints "Durability scored on X of 100 available weight."**

**A criterion is never given a default of 5.** A placeholder is a Hold-shaped number that carries no information, and on a pre-revenue company it was consuming roughly a third of the score.

**Where a criterion has partial evidence** — the observable exists but is company-asserted or indirect — **it is scored, capped at 8, and the cap is printed.**

**Annex A supplies the substitute input for criteria 5, 6, 8 at stages S0–S2. Where Annex A supplies a substitute, the weight stays and the substitute is scored. Where it supplies none, the weight is removed.**

## 7.3 · Discipline

- **Every score names the observable that produced it.** "Strong moat" is not a score. "99% gross retention, 105% net, disclosed quarterly" is.
- **Where the company doesn't publish something, score on what remains and name the absence.**
- **No criterion above 8 on company assertion alone** — except a filed forward-book figure, a dated design win with a named counterparty, a customer prepayment in contract liabilities, or an on-the-record guidance raise.
- **Where a company will not disclose the metric its own model turns on** — retention in a retention business, concentration in an outsourced manufacturer, utilisation in a placement business — **that refusal scores negatively on criterion 3**, not neutrally.
- **The structural-evidence rule.** **Criterion 3 may be scored ahead of the near-term profit and loss where the structural position is independently evidenced** — a sole qualified supplier of a mandatory input, a decade-deep software lock-in, a named customer list with no second source. *This rule is why a lithography monopoly scored well in 2015 before its product shipped, why a chip company scored well at a cyclical trough in 2019 on a software moat, and why a company whose headline revenue was flat scored well in 2016 when the segment underneath was compounding.* **It requires reading the segment, never the consolidated line.**

## 7.4 · Durability weights — one table, verified to 100

| Profile | Used by | 1 Pull | 2 Prod | **3 Moat** | 4 Run | **5 Room** | 6 Engine | 7 Tract | 8 Oper |
|---|---|---|---|---|---|---|---|---|---|
| **P1** Franchise | A2 A3 T1 B2 | 6 | 14 | **28** | 10 | **12** | 10 | 6 | 14 |
| **P2** Bottleneck | B1 B3 T3 | 8 | 10 | **30** | 8 | **12** | 12 | 8 | 12 |
| **P3** Design-in & supplier | T2 C1 C2 | 12 | 10 | 18 | 6 | **14** | 10 | **18** | 12 |
| **P4** Contracted infrastructure | C3 G1 | 8 | 4 | 14 | 6 | **12** | 16 | **22** | 18 |
| **P5** Merchant operator | C4 | 10 | 6 | 14 | 8 | **14** | 20 | 12 | 16 |
| **P6** Option | D1 D2 D3 T4 | 10 | 20 | 14 | 16 | **10** | 8 | 12 | 10 |
| **P7** Cycle | E1 E2 E3 | 14 | 6 | 14 | 4 | **16** | 22 | 12 | 12 |
| **P8** Repair | F1–F5 | 6 | 8 | 14 | 6 | **22** | 14 | 14 | 16 |
| **P9** Clinical life science | H1 H2 | 10 | 24 | 12 | 16 | **4** | 10 | 12 | 12 |
| **P10** Commercial life science | H3 H4 | 10 | 18 | 14 | 8 | **14** | 12 | 12 | 12 |

```
Durability = Σ (criterion × weight) ÷ available weight × 100, then × the integrity multiplier
```

> **Why traction fell and moat rose.** Contracted backlog, remaining performance obligations and deferred revenue were tested across 265 companies and nine start years and returned **null as general predictors**. They are retained at full weight only where the book is contractually obligated and the archetype's value converts directly out of it — design-in supply (P3) and contracted infrastructure (P4) — and cut everywhere else. The weight moved to moat because, on a panel of five companies that each lost more than 80% from a peak, **all five failed on the moat question first**, and each would have been capped on that question alone before any valuation argument was needed.
>
> **Why market pull is capped low in every profile.** Every one of those five losers sat inside a genuinely correct structural theme. Being right about the trend was worth nothing.
>
> **Why operator credibility is weighted at 12–18 everywhere.** This project's own recorded failures have been governance and sourcing failures, not analytical ones.

## 7.5 · Durability bands

| Score | Reading | Meaning |
|---|---|---|
| **85–100** | **Exceptional** | Large room, named mechanism, evidence it is already starting |
| **70–84** | **Strong** | Real room and a credible path |
| **55–69** | **Conditional** | One named thing must go right — and the memo names it |
| **40–54** | **Weak** | Room exists but nothing is closing it |
| **below 40** | **Not durable** | Either no room left, or no mechanism |

**There is no entry floor and there never will be.** The lowest-scoring quintile of a 173-company ten-year study produced **25.7% five-baggers against 11.4%** for the highest. A floor would have excluded a 121×, a 93× and a 15×, all loss-making at the start.

**Score caps, applied after the integrity multiplier — both cap Durability at 55:**
- The company cannot survive a bad outcome without raising money: *(cash + committed undrawn facilities + non-refundable customer prepayments) < 18 months of trailing burn*, **and** no funded plan disclosed, **and** no raise completed in the last two quarters above the prior raise price.
- Debt above 3.5× EBITDA **on filing figures** with more than half due inside the horizon.

**And one cap on quality itself: where more than two criteria are scored on partial evidence, Durability caps at 70 and is marked low-evidence.**

---

# §8 · THE ENTRY VERDICT — arithmetic, not judgement

## 8.1 · The computation

```
CAGR_spot = (central-case value at the valuation date ÷ today's price)^(1/n) − 1
EXCESS    = CAGR_spot − required return
```

`n` is the computed horizon from §5.6. The central case is **the third of the four — what I actually expect, not an average.**

| EXCESS | Verdict |
|---|---|
| **≥ +8 points** | **STRONG BUY** |
| **0 to +8 points** | **BUY** |
| **CAGR_spot positive but below the required return** | **HOLD** |
| **CAGR_spot below zero** | **SELL** |
| **CAGR_spot below zero AND the Bull case also loses money** | **STRONG SELL** |

**This replaces the score-to-band mapping and the 20% price ceiling used to v5.0.** Both are **suspended in writing under §12**, for the reason the framework's own change control requires: the score-band produced ratings that moved when nothing about the business had changed, and the 20% ceiling had no calibration and, on the evidence that **fourteen of fifteen winners never traded 15% below the price at which they were first identified**, was systematically excluding the names this framework exists to find. **Entry verdicts issued under v5.0 and earlier are not convertible to this scale. A name has no v5.1 Entry verdict until it is re-run.**

## 8.2 · The price ladder — printed on every memo

Four prices, each the level at which the verdict changes. Solve the CAGR equation for price.

| Line | Solve for | Printed as |
|---|---|---|
| **Strong buy below** | CAGR_spot = required + 8 | `$X` |
| **Buy below** | CAGR_spot = required | `$Y` |
| **Fairly priced** | CAGR_spot = 0 | `$Y to $Z` |
| **Reduce above** | CAGR_spot < 0 | `above $Z` |

**Print all four in every memo, even when three of them are far from the current price.** They are the answer to "at what price does this change", and they are why the Entry verdict is a range rather than a word.

## 8.3 · The stability test — the word, not just the level

**Recompute the Entry verdict at −25%, central and +25% on the terminal multiple.** Where it is not the same word at all three:

> **Print `VERDICT UNSTABLE`, name the two or three words, and print the price ladder at each end of the band. Confidence drops to "this is a close call and I could be wrong."**

*On the batch that found this, three of four names had an unstable verdict and it was invisible. This is not a reason to distrust the calls — it is the honest width of them.*

## 8.4 · The two caps on the Entry verdict

| Cap | Test | Effect |
|---|---|---|
| **NO FORWARD ENGINE** | Criteria 5 and 7 together score below 9 of their combined available weight ÷ 2. **D3 and H2 exempt** | **Caps at HOLD.** Cannot print BUY or STRONG BUY |
| **PAPER PROFITS** | The earnings-quality check in §3 step 6 fails on either limb | **One rung down** — STRONG BUY→BUY, BUY→HOLD, HOLD→HOLD |

**Both are printed whenever they bind, and whenever they would bind at the +25% multiple.**

## 8.5 · The ceilings, which override everything

| Ceiling | Fires when | Effect |
|---|---|---|
| **STRONG SELL, fixed** | Court finding of fraud, indictment, delisting, or an admitted misstatement of results | Entry = STRONG SELL. Durability = not scored |
| **HOLD** | Accounting seriously in question — unremediated material weakness, restatement, auditor dispute, regulator enforcement, unrebutted misstatement allegation | Entry capped at HOLD |
| **BUY** | Conduct case — consumer-protection or deceptive-practices action | Entry capped at BUY |
| **HOLD** | **Licence case** — a regulator has found the activity behind a material share of revenue was unlicensed, or has confiscated income as unlawfully earned | Entry capped at HOLD |

**The lowest ceiling wins. A verdict may always sit below a ceiling. No ceiling ever raises a verdict.**

## 8.6 · Integrity — the multiplier on Durability

| Level | Trigger | Multiplier | Entry ceiling |
|---|---|---|---|
| **0 · Clean** | Nothing material found | **1.00** | none |
| **1 · Noise** | Routine shareholder-suit solicitations with no upstream cause; a single departure with a normal explanation | **1.00** | none |
| **2 · Watch** | Disclosed control deficiency; unexplained or badly-timed executive departure; aggressive but legal accounting; related-party transactions; a short report the company has rebutted with evidence | **0.92** | none |
| **3A · Accounting** | See §8.5 | **0.75** | Hold |
| **3B · Conduct** | See §8.5 | **0.88** | Buy |
| **3C · Licence** | A regulator has found that activity producing more than **20% of revenue** was carried on **without the required licence**, or has **confiscated income as unlawfully earned** | **0.80** | Hold |
| **4 · Disqualifying** | Fraud finding, indictment, delisting, admitted misstatement | **not scored** | Strong Sell |

**Any level of 3A or above needs the primary document.** Where it was not obtained, assign the highest level the retrieved evidence supports **and print Durability at both that level and the one above it.**

**At level 3C the revenue at issue comes out of every forward case** until a licence or permitted structure is evidenced and dated.

**Where the integrity multiplier moves Durability across a band boundary, say so and print both scores.**

**Mandatory upstream search:** any law-firm "investigating" headline is traced to its cause before classification. The test is whether a specific, unrebutted allegation of misstatement exists — not whether a press release was published.

## 8.7 · Order of operations — fixed

```
DURABILITY:  raw score → ÷ available weight → × integrity multiplier → caps → band
ENTRY:       central case → CAGR at spot → excess vs required → band
             → §8.4 caps → §8.5 ceilings → §8.3 stability test
```

**Durability is never touched by price. Entry never raises Durability. Neither is derived from the other.**

## 8.8 · Confidence — computed, not felt

| Say | When |
|---|---|
| *"I'm confident"* | The odds of clearing the required return sit 0.25 or more from a coin flip, **and** the gap between the good and bad outcomes is 22 points of annual return or less, **and** nothing the company publishes is missing |
| *"reasonably confident"* | The odds sit at least 0.12 from a coin flip |
| *"this is a close call and I could be wrong"* | Anything else · three or more retrieval items the company publishes were not obtained · **the verdict is unstable across the ±25% band** · **more than two rows of the driving-inputs table are Class C** · **a mandatory-trigger document has gone un-opened in three consecutive runs** · **the provisional mid-ramp rule was applied** |

## 8.9 · What accuracy means here, and the three things measured

**The commitment is not to be right about the future.** Directional accuracy on individual equities over three to five years lands near 60% for good practitioners, and pursuing more than that is itself the error: the highest-quality quintile of the ten-year study produced **the fewest** five-baggers.

**The arithmetic that matters.** On a fifteen-name sleeve, one winner at 10× with losers at −70% **loses money**. Two winners at 3.6× with losses capped at −40% works. **The target is two in fifteen, not eighty percent.** Three levers, all multiplicative, together worth **+17.8 percentage points**: raising the hit rate (the room-and-mechanism screen delivered 25.0% against 7.7%), cutting loss size (rule 18), and **never applying a time stop** — a thirty-six-month stop destroyed six of seven winners.

**Three commitments, all testable, all logged in the calibration ledger:**

| Measure | Target | Test |
|---|---|---|
| **Blow-up avoidance** | **≥95%** | No name at Entry BUY or better falls more than 50% within 24 months |
| **Interval coverage** | **≈80%** | The realised outcome lands inside the printed 10th–90th percentile band |
| **Retrieval integrity** | **100%** | No Class A or B input estimated. Every downgrade carries its negative-retrieval log |

**Directional accuracy is recorded but is not a target.** It is reported at each review with no threshold attached, because setting one would push the framework toward exactly the high-quality, low-return names the evidence says to avoid.

---

# §9 · LIFE SCIENCES

**Where Gate 1 fires, load Annex C.** It carries the pinned probability engine, the modifier table, the mapping from one probability to the four cases, and the retrieval set for H1–H4. **Never set a drug-approval probability by hand, and never re-retrieve the base rates per run — that was the source of the variance.**

---

# §10 · WHAT YOU WRITE

## 10.1 · Banned. Use the right column.

| Never | Instead |
|---|---|
| Panel A / harness / profile P2 / archetype T3 / basis M3 / stage S1 | "I'm valuing this as a bottleneck business" |
| Capped at Hold / uncapped Buy | **One verdict, then a sentence on what's holding it back** |
| Required return 11.93% | "you need about 12% a year to be paid for this risk" |
| EXCESS +6.4pp | "it should return about six points a year more than the risk demands" |
| P(beat) 0.58 · p10 −2.1% · p90 +33.4% | "it clears that bar about 6 times in 10; badly wrong loses 2% a year, well right makes 33%" |
| Durability 74 = Σ(criterion × weight) | *(appendix only — but the score itself is printed)* |
| Reward-to-risk 1.53× | "for every £1 of downside there's £1.50 of upside" |
| Say-do ratio 6/8 | "management hit its own guidance six times in eight quarters" |
| Net revenue retention 118% | "existing customers spent 18% more than last year" |
| Integrity Level 3A, ×0.75 | "there's an accounting problem serious enough that I don't fully trust the numbers" |
| [FACT] [CALC] [EST] in the prose | "per the Q2 filing" / "my estimate" *(tags stay in the detail sections)* |

**Voice:** short sentences, one idea each · every number gets a comparison · bold the one number that decides it · one caveat then move on, the rest collect at the end · written to be read aloud to someone who doesn't follow the company.

## 10.2 · The memo — this order

**1 · What this company does.** Three to five plain sentences, before anything else. What they sell, who buys it, how they make money, who supplies them, who could go around them. If one segment is over 60% of revenue, say so — that segment is the company. **If a twelve-year-old could not repeat it back, it is not written well enough yet.**

**2 · The two answers, together.**

```
DURABILITY   74 / 100 · STRONG        (is this worth owning)
ENTRY        BUY                       (is it worth buying today)

Strong buy below $X · Buy below $Y · Fairly priced $Y–$Z · Reduce above $Z
Today $P.  Expected return about C% a year to <date>, against a bar of R%.
```

Then confidence in words. **Durability first, always** — it is the question that decides whether the name belongs in the book at all.

**This block travels with the verdict wherever the verdict goes.** A summary table, a screen row, a chat answer or a one-line update carries at minimum **the Durability score, the Entry word, and the buy-below price**. Rule 20 has no short form and no exception for brevity: *if there is not room for the score, there is not room for the verdict.*

**3 · The driving inputs — immediately under the two answers, before any argument.** Five rows at most.

| Input | Value | Class | Source | Moves the answer by |
|---|---|---|---|---|

**A Class C row is permitted and honest. What is not permitted is burying it.** **Where more than two rows are Class C, the Entry output is a range rather than a word, and confidence is "this is a close call and I could be wrong."**

**4 · Why.** Three to six short paragraphs. Strongest fact first, then the case against, then what tips it.

**5 · What you make and what you lose.** Four rows — *If I'm badly wrong · If I'm mildly wrong · What I actually expect · If it goes well* — each with a price, a return per year, and one line on what has to be true. **Then the stability line: the verdict at −25%, central and +25% on the exit multiple.**

**6 · The one reason.** **The single criterion carrying the thesis, and one sentence describing what would prove it false.** Written before any position exists. Checked quarterly. **This is the entire sell discipline: sell when it breaks, never for time, never for price.**

**7 · What would change my mind.** Three to six things, each a number the company publishes, each with its effect on Durability.

**8 · The failed peer.** **One named company, same archetype, same tailwind, that died anyway — and why.** Every memo. The absence of one is itself a finding.

**9 · What I'm not sure about.** Every Class C input, everything undisclosed, everything stale, every negative-retrieval log. All of it here, stacked, never dispersed. **Anything un-retrieved for three consecutive runs is named with its count.**

**10 · The detail.** The full working. Tags allowed.

**11 · Appendix — the machinery.** All five classification axes and the gate that set each · the eight scores and weights · available weight and what was redistributed · the arithmetic · the range outputs · retrieval status · the change table versus last run · cost-of-capital build · **the runner-up archetype and the Entry verdict it would have produced** · **every provisional rule applied in this run, named.**

**For a batch:** one summary table first — **ticker · what it does in five words · Durability · Entry · buy-below price** — ranked by Durability, highest first. Then one full memo per name in that order. **Names where the model does not apply go in their own block at the bottom with the reason, never mixed into the ranking.**

**For a sweep or screen — rule 21, stated operationally.** The output carries **two counts and one table**: how many names were examined, how many were rated, and **one row for every rated name** — ticker · Durability · Entry · price · date. **The two counts must reconcile to the table.** Where a name was examined but not rated, it appears in a separate *screened, not rated* list with a one-line reason, or the output states the count and that no verdict was formed. **A sweep that says "93 of 107 rated" and then names 28 of them has issued 65 verdicts it cannot account for, and is not a valid output.**

**And the shared-risk test, which is not optional.** **Name the variables the batch has in common — a policy, a customer, an input price, an end market — and for each, say what every name in the batch is worth if it goes the wrong way.** Where two or more names share a variable, **their Break cases are not independent and the memo says so in those words.** A batch of five names on one policy is one position with five tickers.

**And where the batch shares no variable, say that too.** **Independence is a result, not the absence of one. Never manufacture a shared variable to fill the section.**

---

# §11 · CONTINUITY

**There are no rebuilds.** Every run after the first is an update against the ledger. Refresh: price · anything stale or triggered · news and filings since the last memo · a reported quarter in full · **the prior memo's change-my-mind list, each marked happened / didn't / not yet testable** · **the one reason, marked intact or broken** · both verdicts.

**Durability changes only where a change table names the input that moved, on what document, on what date.** Criteria with no new evidence are carried with their original date. **If Durability moved and the table is empty, the run is invalid and the prior score stands.**

**Entry may change with no change table at all** — it is a function of price, and price moves. That is the point of separating them.

**A verdict may also move because the framework changed rather than because the company did.** Record it as a rule change, name the rule, and leave Durability untouched.

**Fixed inputs** — exit multiple, terminal margin, fade years, probabilities, peer set, all five classification axes — change only against a named dated fact, recorded in the ledger.

**The ledger — one row per retrieval item, these eight columns, no others:**

| item | value | **class** | status | source document | date | refresh rule | run that retrieved it |

**Status is one of three words: `RETRIEVED` · `NOT DISCLOSED` · `NOT REACHED`.** A published memo may contain no `NOT REACHED`. **Where an item has been `NOT REACHED` in three consecutive runs, the ledger records the consecutive count and the chronic-gap rule fires.** The ledger also carries, in named sections: the frozen judgement inputs with justification · all five axes and the gate that set each · the manifest count · the one reason, dated · an append log, one line per change with the fact and document behind it.

**Files:** `<TICKER> LEDGER.md` (append-only) and `<TICKER> <Company> <DDMMMYYYY> GROW.md`. Both saved to the project and delivered. **An undelivered file does not exist.**

---

# §12 · CHANGE CONTROL

**Frozen to 30-Aug-2027, reviewed 28-Feb-2027.**

**Frozen:** the five Entry words · the Durability 0–100 scale · the §8.7 order of operations · the output contract in §10.
**May be extended at a review, additively:** the criteria, the retrieval list, the archetype metric sets, the measurement bases.
**Not frozen, and not amendment:** the cost-of-capital inputs and the regime table.

**Suspensions made in this version, in writing, under the clause that permits suspending a rule actively producing wrong answers:**
1. **The score-to-band mapping for Entry** — replaced by §8.1. It produced verdicts that moved when the business had not.
2. **The 20% price ceiling** — replaced by §8.1. Uncalibrated, and excluding the names the framework exists to find.
3. **The margin-room floor** — no longer needed. A high-headroom business priced below its destination now produces positive excess return on its own arithmetic.
4. **The PROSPER verdict scale** (`BUY / ACCUMULATE / WAIT / REFUSE`) — **superseded, not translated.** 98 verdicts issued on it between 14-Aug and 27-Aug-2026 stand as a historical record and are excluded from every GROW statistic. No mapping table to the five-point scale exists or may be built. Names carrying only a PROSPER verdict — the Swiss and Japanese coverage — are **unrated** until re-run under v5.1. See rule 22.

**Propose before changing. No rule is altered inside the run that discovered the problem. No run mints a rule.**

## 12.1 · Provenance

**Every rule is recorded with four things: the company that produced it, the date, the number of independent observations behind it, and whether it has changed a verdict since.** The register is `GROW FEEDBACK REGISTER 04Sep2026.md`.

Between 29-Aug and 31-Aug-2026 this framework gained thirty-one rules, **twenty-nine of them from a single company each.** Each was defensible alone; together they are a model fitted to twenty-nine observations one at a time. **A rule with n=1 is a hypothesis.** The first of the twenty-nine to be tested — the mid-ramp exception — failed.

## 12.2 · Retirement

| State | Test | Consequence |
|---|---|---|
| **Evidenced** | Backed by a study, a panel, or three or more independent observations | Kept |
| **Confirmed by use** | n=1 at adoption, but has since fired on a second, unrelated company | Promoted; the second company is recorded |
| **Provisional** | n=1, fired only on the company that produced it, and has changed at least one verdict | Kept, marked PROVISIONAL, **the memo prints "provisional rule applied" and drops confidence one level whenever it is used** |
| **Dormant** | n=1 and **has not fired across ten runs in which its trigger condition was present** | **Suspended by default at the review** unless re-argued in writing |

**The dormancy clock, defined — because without it the test is unrunnable.** Dormancy counts **opportunities, not calendar time**: a rule is Dormant once ten runs have presented its trigger condition and it did not fire. A rule that has had fewer than ten such opportunities is **Untested**, not Dormant, and is neither suspended nor promoted. *As of 04-Sep-2026 all twenty-nine of the n=1 rules added between 29-Aug and 31-Aug are **Untested** — v5.1 has not yet been run. Suspending them at the February review on elapsed time alone would retire rules that were never given a chance to fire, which is the opposite of what the retirement rule is for.*

**A rule that fails a direct empirical test is demoted, not deleted** — deleting it re-opens whatever defect it was written to close.

## 12.3 · Calibration that consumes its own output

**Every verdict is logged with Durability, Entry, the price ladder, the odds, the confidence, the date and the price.** At each review:

| Question | If the answer is wrong |
|---|---|
| **Blow-up rate: did any BUY-or-better fall more than 50% inside 24 months?** Target ≤5% | The moat and survival criteria are re-weighted, and the failure is added to the loser panel |
| **Interval coverage: what share of outcomes landed inside the printed 10th–90th band?** Target ≈80% | Below 70% the dispersion floor rises; above 90% it falls |
| **Retrieval integrity: how many Class A or B inputs were estimated?** Target zero | Any occurrence is a defect, and the memo is re-run |
| Did roughly 6 in 10 Strong Buys and 5.5 in 10 Buys clear their required return? | The dispersion floor rises |
| Did names passing the inflection test outperform names failing it? | Gate 5's weight is reconsidered |
| **How many re-runs moved Durability with no change-table row?** Target zero | Any occurrence is a protocol failure |
| **How many rules are Dormant or Provisional, and is the count rising?** | A rising count means the framework is accreting faster than it is learning |

**The baseline exists.** `GROW CALIBRATION LEDGER 04Sep2026.md` anchors **53 verdicts to the price each memo printed**, verified live. Nothing in it is a hit rate — median elapsed at the cut was six days — and it says so. Its purpose is that the twelve-month read has something honest to measure against, which it would not have had.

| Read | Date | What becomes measurable |
|---|---|---|
| Baseline | 04-Sep-2026 | Anchors only. Retrieval integrity **failed** and produced rules 20–22 |
| 6-month | 04-Mar-2027 | Direction of the long-short spread; whether the sell side stays weak |
| **12-month** | **04-Sep-2027** | **Blow-up rate · directional hit rate · the archetype-premium dispersion ranking (§5.2) · whether margin room at 22 in P8 is carrying its weight** |
| 36-month | 04-Sep-2029 | Interval coverage, at the framework's own horizon |

**Next review: 28-Feb-2027.** Agenda: the mid-ramp exception's decision · **the Untested list — how many of the twenty-nine n=1 rules have had ten trigger opportunities yet** · the regime-table coverage map · the six-month calibration direction. *The archetype premium and the P8 weighting are no longer February items: both are now dated tests at the twelve-month read, and neither can be answered earlier.*

---

# §13 · HOW TO KNOW THIS IS CORRECT

```
python3 grow_verify.py "GROW v5 1 CORE 04Sep2026.md"
```

The verifier tests the failure modes that reading cannot catch, because a thing that was never written contradicts nothing:

- **DEFINED** — every term a formula uses, every multiplier, every band, every archetype's premium, hurdle, profile, method and retrieval lines.
- **PRODUCED** — every element the memo must contain traces back to a rule that generates it.
- **NOT LOST** — the accuracy rules that were each silently dropped in a past consolidation and had to be restored.
- **CONSEQUENTIAL** — every rule that produces a finding also changes something. The failure mode this framework exists to prevent is a finding printed and then ignored.
- **SEPARATED** — new in v5.1. **No price term appears in any Durability input, and no Durability term appears in the Entry arithmetic.** The two verdicts are proved independent by construction.
- Plus: all ten profiles sum to 100 · every archetype reachable and fully specified · **the Entry resolver exhaustively over its full input grid** · no dangling references, dead vocabulary or duplicated rules.

**On size.** The core is about 14,000 words. **Annexes are loaded only when their trigger fires**, so a standard mature company costs the core alone, and a pre-revenue company costs the core plus Annex A. This is how the framework grew in coverage while falling in cost per run.

**A change to this framework is not finished until the verifier passes.** If it fails, the framework is wrong — not the verifier — unless the failing assertion is itself demonstrably mis-specified, in which case fix the assertion and say so.

---

*GROW v5.1 CORE · 04-Sep-2026 · supersedes v5.0 · five classification axes · two verdicts, one of which contains no price · annexes A–D carry what does not apply to every company · position-blind · sizing and funding out of scope · not investment advice.*
