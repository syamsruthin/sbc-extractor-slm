# End-to-end comparison quality (2026-10-28)

Live run through the HTTP API with OpenRouter (`deepseek/deepseek-v4-flash`) explanations, parser 2.1.0,
engine 1.0.0 → 1.1.0 (fix below). Nine comparisons built from the catalog with CMS Rate PUF premiums
(age 40, shared rating area), plus the two uploaded plans with a custom usage profile.

## Cases and objective checks

| Case | Plans | Check | Result |
|---|---|---|---|
| CSR ladder, NH WellSense Silver HMO | standard, 73%, 87%, 94%, zero cost sharing (same premium) | better cost sharing never costs more, in every scenario and the worst case | **pass** |
| CSR ladder, WY BCBS Silver PPO | standard, 73%, 87%, 94% | same | **pass** |
| Metal ladder, TX HMO (BSW) | Bronze, Silver, Gold | sensible tier ordering | Bronze cheapest at every level (its OOP limit is below Gold's, and Silver carries the silver-loaded premium): correct math |
| Metal ladder, OR EPO (BridgeSpan) | Bronze, Silver, Gold | Bronze cheapest for low use, Gold for high use | **pass after the engine fix** (before: Bronze looked cheapest for high use at $7,770) |
| Same, family coverage | | | same as individual (single-member usage) |
| TX HMO, having a baby | | | Gold cheapest by $319 |
| Cross-issuer, TX Silver HMO | 4 issuers | | correct; overlapping ranges called "depends" |
| Network types, FL Silver HMO vs EPO | | | correct |
| Uploaded plans, custom usage | Core Gold 1500 vs BCBS Premier PPO Gold | | correct; ranges narrowed by the engine fix |

- Extraction accuracy of the 23 catalog plans used, vs v1.4 labels: **99.87%** (7,452 / 7,462 fields).
- All 9 explanations were written by the LLM and passed numeric grounding on the first try (0 template fallbacks,
  0 policy violations), 7–24 s each.

## Calibration against the SBCs' own coverage examples (1,829 catalog plans)

Rank correlation (Spearman) between the engine's simulated out-of-pocket cost and the totals each SBC prints for
the federal coverage examples (CMS Plan Attributes PUF). The engine scenarios only approximate the federal claim
lists, which aren't published in the PUF.

| Example | Engine 1.0 | Engine 1.1 | Median engine / SBC (1.1) |
|---|---|---|---|
| Having a baby | 0.747 | **0.806** | $4,400 / $4,510 |
| Managing type 2 diabetes | 0.640 | **0.682** | $913 / $1,420 (scenario has fewer drugs/supplies) |
| Simple fracture | 0.606 | **0.679** | $1,920 / $1,950 |

## Engine bug found and fixed (1.1.0)

"No charge" with an unstated deductible was treated as free in both bounds. But SBC charts show costs *after* the
deductible is met, and 738 of 1,812 catalog plans have such cells. Example: BridgeSpan Oregon Bronze (deductible =
OOP limit = $9,200, hospital "No charge") looked $7,800 cheaper than it is for heavy use. Now:

- "No charge" with an unstated deductible is a range like any other cell (low bound: free, high bound: deductible applies);
- in-network preventive care stays free (required by federal law);
- page-1 evidence narrows the range: "only services listed as 'deductible does not apply' are covered first" → the deductible
  applies to unmarked rows (71 plans); services the page-1 list names (e.g. primary care, generic drugs) → covered first.

## Explanation quality: issues found

| # | Issue | Example | Fix |
|---|---|---|---|
| 1 | Wrong comparative claim with correct numbers (1 of 9) | "The Gold plan has the lowest worst-case total of $18,166, while Bronze is $15,539" | Give the fact sheet explicit rankings (lowest premium, deductible, OOP, worst case) and check superlative claims against them |
| 2 | "Not stated" read as "no" | "Connect Silver … does not [require the deductible]"; "Bronze has no charge for ER, hospital stays" | Show the deductible status in every cell sent to the LLM and in the UI ("after deductible (per SBC)" / "deductible not stated") |
| 3 | Plan letters not shown in the UI | explanations say "Plan D"; result cards show names only | Label cards and table columns "A", "B", … |
| 4 | "Numbers verified" badge reads as "claims verified" | sits above the misleading bullet in #2 | Reword to "Numbers checked against the calculation" |
| 5 | Garbled plan name from one issuer header | "Individual and Family ndividual and Fa…" (Harbor Health) | Header cleanup rule |

## Fixes and re-run (engine 1.1.0, parser 2.1.1, prompts v2)

| # | Fix |
|---|---|
| 1 | The fact sheet carries explicit rankings (lowest/highest premium, deductible, OOP limit, no-care and worst case, with plan letters). A claim check rejects "lowest/highest/cheapest" statements that contradict them or a scenario's `lowest_cost`, and any single "lowest" when ranges overlap. Hedged wording ("depends", "overlap") is exempt; each superlative is matched to its nearest metric. Rejected text → one retry with the contradictions listed → template |
| 2 | Every cell carries a deductible status (`applies`, `does_not_apply`, `applies_per_sbc`, `before_per_sbc`, `not_stated`, `none`) and its text says so ("No charge, after deductible (per the SBC's page 1)", "…, deductible not stated"), in the comparison table, the LLM fact sheet and the section summaries. Prompts say "not stated" must never be called free or deductible-free |
| 3 | Result cards, table columns and the chart legend show plan letters ("Plan A", "A · name") |
| 4 | Badge now reads "Numbers checked", with a tooltip saying which checks ran |
| 5 | A plan name is kept when the text after its colon is only coverage-tier words; residue like ": Individual and Family" is stripped ("Harbor Health S1", 5 documents) |

Re-run of the same nine cases with live OpenRouter:

| | Before | After |
|---|---|---|
| Explanations from the LLM | 9 / 9 (one with a wrong comparative claim) | 8 / 9 (6 first try, 2 corrected on retry) |
| Template fallback | 0 | 1: the LLM repeated a wrong claim ("Gold has the highest worst-case total"; Silver's is higher) |
| Wrong superlative claims served | 1 | **0** |
| "Free" / "no deductible" for cells whose deductible is unstated or applies | 2 cases | **0** (OR Bronze now "no charge after deductible") |
| Claim-check false positives on the original nine explanations | — | 0 (it flags exactly the one wrong claim) |

Still open: a row-bleed extraction error in one Oregon SBC gives its hospital surgeon fee the next row's "deductible does
not apply", so its summary calls that fee deductible-free.

Overall: the numbers are trustworthy (dominance checks pass, 99.87% extraction accuracy, strong calibration against
the SBCs' own figures), and the explanations are now readable, grounded in the numbers, and checked for wrong
comparisons and for "free" wording around deductibles.
