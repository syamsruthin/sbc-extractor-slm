# Gold test set (10 SBCs)

The gold labels are teacher labels (v1.1, frozen in `teacher_labels/`) plus **63 corrections,
each verified against the original PDF**. This is the test set for every model in Phase 2+,
so it must never be used for training. **Every plan from these 10 template families is
excluded from training** (see docs/06).

**Status: verified, 2026-10-17.** All 10 documents were reviewed field by field against the
original PDF pages by Claude: plan info, deductible/OOP, all 26 services in and out of
network, drug tiers, and both lists. The review was done by an LLM, not a person. It was
systematic and cites a PDF page for every change, but if you hand-check some documents
yourself, add any further fixes to `corrections.json` the same way.

## Files

- `teacher_labels/<plan_id>.json`: the frozen teacher labels the corrections apply to
- `corrections.json`: every change, with the PDF page, reason and status
- `labels/<plan_id>.json`: the gold labels = teacher labels + accepted corrections
  (`uv run python src/build_gold.py`)
- `review/<plan_id>.md`: side-by-side review sheets (`src/review_sheet.py`)

## What the PDF review found

| Error type | Corrections | Example |
|---|---|---|
| **Inferred `deductible_applies`** | 33 | NE: plain "40% Coinsurance" cells marked "applies" from the page-1 list; FL: "$25 copay / visit" marked "doesn't apply" |
| **Multi-part cells (v1.2 "first listed part")** | 12 | MI: "$30 copay/office visit … 20% for other outpatient" had both fields filled |
| **Missing deductible / OOP amounts** | 5 | LA: deductible and OOP both null; the PDF states $6,000 / $8,900 |
| Plan info consistency | 6 | issuer = header brand ("Ambetter Health", not underwriter "Celtic"); plan_name without the issuer prefix; plan_type "IND POS" → "POS" |
| Prices left in the note only | 2 | TX surgeon fee "No charge" with null prices; TN generic Tier 1A/1B |
| Wrong coverage from limitations text | 1 | TN out-of-network urgent care: price column "Not Covered" |
| Wrong list contents | 1 | LA: 4 "Other Covered Services" listed as exclusions |
| Garbled / misplaced notes | 3 | OR: in-network ER note described the out-of-network rule |

**A first-pass error of mine, caught by the PDF review:** the earlier (Markdown-based) review
"corrected" Arkansas mental health outpatient to 50% coinsurance. The PDF cell is
"$20 copay/visit; and 50% coinsurance for other outpatient services". The review sheet had
matched "outpatient services" inside the *specialist* price cell. The correction is revised,
and `review_sheet.py` now only matches row labels in the first two columns.

## Gold conventions (beyond guideline v1.2)

These were applied consistently in review and written up as guideline v1.3, which was
**tested but not adopted** for the training labels (see docs/04-labeling.md). So the gold set
is stricter than the training labels on `deductible_applies` and issuer naming:

1. `deductible_applies` comes only from **that row**: its price cell, its limitations cell,
   or a legend mark like "†Deductible does not apply". Never infer it from the page-1
   "services covered before the deductible" list or the chart-wide "after your deductible,
   if a deductible applies" note.
2. `issuer` = the brand in the SBC header (not the underwriter in the footer).
3. `plan_name` = the plan name without an `Issuer:` prefix.
4. `plan_type` is one of HMO / PPO / EPO / POS (drop market labels like "IND").
5. `excluded_services` only from "Services Your Plan Generally Does NOT Cover", never
   from "Other Covered Services".
6. Sub-rows (e.g. HMSA "Physician Visit" / "Emergency room") count as parts of one cell:
   the first listed sub-row goes in the structured fields.

## Review status

- [x] 10091OR0780001-01 PacificSource: 3 note fixes
- [x] 11718TX0140020-01 Community Health Choice: 3
- [x] 13262AR0230010-00 Health Advantage: 9 (incl. revised mental-health entry, OOP)
- [x] 13484NE0090009-00 Ambetter: 21 (19 inferred deductible flags, issuer, plan_name)
- [x] 13887FL0010004-00 22 Health: 7 inferred deductible flags
- [x] 15560MI0350004-00 BCBS Michigan: 2 multi-part cells
- [x] 17414NC0010007-01 AmeriHealth Caritas: 4 (deductible, 3 drug-tier flags)
- [x] 18350HI0880013-03 HMSA: 3 (ER, habilitation)
- [x] 19636LA0610013-00 HMO Louisiana: 6 (deductible/OOP, exclusions, plan type/name)
- [x] 23552TN0020036-01 Oscar: 5
