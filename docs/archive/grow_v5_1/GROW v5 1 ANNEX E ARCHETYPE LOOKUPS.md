# GROW v5.1 — ANNEX E · ARCHETYPE LOOKUPS
**Read only the rows for the archetype assigned in §5.1 and its runner-up. The other rows are not read.**

## 5.2 · Premiums, profiles and valuation methods

> **Placeholder notice (Revision 2, 05-Sep-2026):** CORE.md's Revision 2 compressed the archetype premium range to +1.0–+7.5 (required return 9.9%–16.4%), but this Annex had not yet been re-calibrated to match. The Premium and Required columns below were produced by a **mechanical linear rescale** of the old (pre-compression) values — `new_premium = 1.0 + (old_premium − 1.0) × 6.5/14.0`, `new_required = 8.93% + new_premium` — solely to keep every number inside the new CORE-mandated range and pass `grow_verify.py`. This preserves the old ranking of archetypes exactly but is **not a calibrated judgment** about where each archetype should sit in the new range. Treat every row here as provisional until it is replaced with real calibration.

| Code | Archetype | Premium | Required | Profile | Primary method | Forbidden here |
|---|---|---|---|---|---|---|
| **A2** | Consumer brand | +1.7 | 10.6% | P1 | Cash-flow model, price and volume split | EV/sales |
| **A3** | Toll-taker | +1.2 | 10.1% | P1 | Volume × take rate × margin | Price to book |
| **T1** | Software / platform | +1.7 | 10.6% | P1 | Forward earnings off retention and Rule of 40, R&D-capitalisation adjusted | Trailing P/E |
| **T2** | Design-in franchise | +2.2 | 11.1% | P3 | Forward earnings on the design-win-backed path, content per unit built | **Mid-cycle normalisation** |
| **T3** | Technology bottleneck | +1.9 | 10.8% | P2 | Qualified capacity × realised price × margin | **Mid-cycle normalisation**; EV/sales alone |
| **T4** | Scaling technology | +3.6 | 12.5% | P6 | EV/gross profit on a cohort path to a stated Rule of 40 | P/E; a terminal margin never earned |
| **B1** | Physical bottleneck | +1.9 | 10.8% | P2 | Forward earnings, pricing power evidenced | EV/sales alone |
| **B2** | Standard-owner | +1.7 | 10.6% | P1 | Cash flow with an extended advantage period | Any five-year fade |
| **B3** | Licence bottleneck | +2.4 | 11.3% | P2 | Cash flow to expiry, then renewal probability | Perpetual growth |
| **C1** | Direct arms dealer | +2.9 | 11.8% | P3 | **Mid-cycle** earnings × exit multiple | Peak-earnings P/E |
| **C2** | Second-derivative supplier | +3.1 | 12.0% | P3 | **Mid-cycle**, content per unit explicit | Trailing P/E at a peak |
| **C3** | Contracted landlord | +2.2 | 11.1% | P4 | Contracted revenue to expiry plus residual, less capital | P/E of any kind |
| **C4** | Merchant operator | +3.6 | 12.5% | P5 | Realised operating income × a cap rate from a **named observed transaction** | Treating an unsigned pipeline as contracted |
| **D1** | Category creator | +4.7 | 13.6% | P6 | Probability the category forms × value if it does | P/E |
| **D2** | Platform-shift pure play | +5.6 | 14.5% | P6 | Win and lose branches, weighted | Any single-point estimate |
| **D3** | Binary unlock | +7.5 | 16.4% | P6 | Probability-weighted value | Every revenue and earnings multiple |
| **E1** | Commodity cyclical | +3.3 | 12.2% | P7 | **Mid-cycle** EBITDA, cost-curve position stated | Spot-price forward earnings |
| **E2** | Policy cyclical | +3.8 | 12.7% | P7 | Subsidised and unsubsidised economics valued **separately** | Assuming current policy to the terminal year |
| **E3** | Capex cyclical | +3.3 | 12.2% | P7 | **Mid-cycle** EBITDA; service revenue valued separately | Peak-cycle multiples |
| **F1** | Margin inflection | +3.3 | 12.2% | P8 | Margin path built from the **named mechanism** | Applying the target as if achieved |
| **F2** | Turnaround | +4.2 | 13.1% | P8 | Works / partly works / fails, weighted by management's record | Forward earnings on management's own plan |
| **F3** | Roll-up | +2.9 | 11.8% | P8 | Organic base; acquisitions at prices actually paid | Consolidated earnings growth |
| **F4** | Broken growth | +2.9 | 11.8% | P8 | Forward earnings at the **matched-growth** comparable | Its own historical multiple |
| **F5** | Traction inflection | +3.6 | 12.5% | P8 | The forward book converted on its **disclosed and evidenced** schedule | **Trailing revenue multiples** |
| **G1** | Composite / sum-of-parts | +2.4 | 11.3% | P4 | **Each segment under its own archetype, summed, less holding cost and a stated discount** | One blended multiple on consolidated figures |
| **H1** | Platform therapeutics | +5.2 | 14.1% | P9 | Risk-adjusted value summed across programmes, platform residual capped at 20% | Any revenue multiple |
| **H2** | Single-asset clinical | +7.0 | 15.9% | P9 | Probability-weighted value via Annex C, less licensor economics | Probabilities not from Annex C |
| **H3** | Commercial biopharma | +3.3 | 12.2% | P10 | Launch curve against a **named analogue**, then decay to loss of exclusivity | Any terminal value ignoring the patent cliff |
| **H4** | Device & diagnostic | +2.9 | 11.8% | P10 | Placements × utilisation × consumable price, tail valued separately | One blended revenue multiple |

**Three rules override the table.** Loss-making at the net line → no P/E method may be primary. Mid-cycle normalisation is permitted **only** for E1, E3, C1 and C2. Every terminal multiple obeys rule 16.



**Plus, by archetype:**

| | Additional |
|---|---|
| **T1** | Gross and net retention · Rule of 40 · payback months · contract length · **R&D capitalisation policy and the earnings adjustment** · cohort expansion |
| **T2** | **Design wins by named customer with dated start of production** · **content per unit and its trend by generation** · socket retention through the last transition · backlog and book-to-bill · qualification length |
| **T3 / B1** | Qualified alternatives · qualification months · **price rises held through a downturn** · utilisation and contracted capacity · **customer prepayments** · export-permit status |
| **T4** | **Gross-profit growth versus revenue growth** · Rule of 40 trajectory · retention · **runway and funding plan** · dilution path · **the dated path to breakeven** · share direction versus the two nearest rivals |
| **A2 / A3** | Volume and price growth **separately** · margin through the last cost shock · take rate and its five-year direction · regulatory proceedings on fees |
| **B2 / B3** | Ecosystem investment growth · partner counts · switching cost in money and months · licence expiry, renewal history, whether supply is being expanded |
| **C1 / C2** | **Backlog with named customers and dates** · book-to-bill · content per unit · **concentration from the latest filing** · aftermarket share · **mid-cycle revenue and margin built explicitly** |
| **C3 / C4** | **Average contract length** · counterparty credit · contracted versus uncontracted · capital cost per unit · **asset life against contract life** · **whether debt is ring-fenced or recourse** · for C4, **a named observed transaction anchoring the cap rate** |
| **D1 / D2 / D3** | All three: evidence the category or transition is forming **independently of the company** · runway in months · named design wins. **D2**: which technology the customer has actually funded. **D3**: the event date · **the probability from base rates, with the source** · what the asset is worth if the event fails |
| **E1 / E2 / E3** | All three: **mid-cycle revenue and margin built explicitly** · utilisation · channel inventory · survival through two more bad years. **E1**: position on the cost curve. **E2**: whether support is legislated or discretionary, its expiry, and **unit economics with the subsidy removed**. **E3**: backlog cover and book-to-bill |
| **F1 / F2 / F3 / F4 / F5** | **F1**: the **named** structural mechanism, three periods of evidence, and what happens if revenue falls. **F2**: management's prior record **with numbers**, dated milestones, which are hit, liquidity to finish. **F3**: **organic growth of the acquired base after two years**, multiples paid by deal, debt growth against earnings growth, goodwill share. **F4**: organic growth stabilising or not, cash flow through the de-rating, **insider buying**, the matched-growth comparable. **F5**: the full forward book · its **disclosed** twelve-month conversion share · **the realised conversion rate over four quarters** · what it is worth at half the disclosed conversion |
| **G1** | Segment revenue, segment operating profit, segment assets **for every segment** · the holding-company cost line · any published sum-of-parts from the company or a named analyst · **the discount applied and its basis** |
| **H1 / H2 / H3 / H4** | See Annex C |


---

*Annex E · lookup only · one row per run.*
