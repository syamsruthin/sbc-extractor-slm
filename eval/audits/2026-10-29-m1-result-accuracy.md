# M1 result accuracy (2026-10-29)

Plan v2.1, milestone M1 (`docs/design/v2.1/`): engine 1.3.0 (cost per use before and after the
deductible, combined verdict), fact sheet and prompt `explanation.v3`, deductible and coverage claim
checks C1–C5 (`backend/sbcx/domain/explain/claims.py`).

## F1: deductible-blind per-row verdicts

Fixture `backend/tests/fixtures/f1_comparison.json` (Moda TX Bronze 8700 vs Anthem Catastrophic, exported
from comparison `f8c68687…`). Engine 1.2.0 marked the catastrophic plan "lower cost" on every row. Engine
1.3.0:

| Row | Before deductible A / B | After A / B | Verdict for B |
|---|---|---|---|
| Specialist visit | $120 / $250 | $120 / $0 | depends on deductible |
| Urgent care | $120 / $200 | $120 / $0 | depends on deductible |
| Mental health outpatient, rehab, habilitation | copay / full price | copay / $0 | depends on deductible |
| Generic, preferred, non-preferred, specialty drugs | copay / full price | copay / $0 | depends on deductible |
| Primary care visit | $85 / $0 | $85 / $0 | lower cost (first 3 visits are before the deductible) |
| Hospital facility, childbirth facility, MH inpatient | $8,700 / up to $10,600 | $0 / $0 | higher cost |

Scenario totals and headline numbers are identical to the stored engine 1.2.0 result
(`tests/unit/test_fixtures.py`).

## F2: claim checks on stored explanations

`eval/explanations/check.py` over the 27 stored explanations that carry deductible statuses (19 older
ones have none and are skipped):

| Comparison | Rule | Sentence | Verdict on review |
|---|---|---|---|
| f8c68687 | C1 | "Moda Bronze's out-of-pocket limit equals its deductible ($8,700), so you pay full cost until the deductible is met." | **Wrong claim** (the discovery F2 sentence): Moda covers visits and drugs with copays before the deductible |
| 757b261d | C4 | "Regence Silver 6500 does not cover children's dental check-up, while the other two plans do." | **Wrong claim** not found by the 2026-10-28 audit: Regence is the only one of the three that covers it |

`eval/explanations/sentences.jsonl` (707 sentences from 46 explanations) is exported but **not labeled
yet** (T0.2 needs a person), so the formal precision/recall gate (D6: precision ≥ 0.9, recall 1.0) is not
measured. The two flags above were both confirmed by reading the plan data.

## Live runs (OpenRouter `deepseek/deepseek-v4-flash`, 10 stored comparisons re-created on a database copy)

Script: `eval/explanations/live_check.py`. Cases: the F1 comparison and the nine most recent stored
comparisons with explanations (the 2026-10-28 audit set).

| Run | Change before the run | LLM first try | After retry | Template | Rejections reviewed |
|---|---|---|---|---|---|
| 1 | first version of C1–C5 | 5 | 4 | 1 | 3 true, 2 false positives (deductible phrase attached to the wrong service; "doesn't cover X before the deductible" read as a coverage claim) |
| 2 | phrase-to-service linking, timing wording | 8 | 2 | 0 | 2 true (Regence dental) |
| 3 | C3 also rejects "after/before the deductible" claims where the SBC doesn't say | 6 | 4 | 0 | 1 false positive ("do not state whether the deductible applies") |
| 4 | hedge wording for "not state whether" | 7 | 2 | 1 | 4 true (Regence dental ×2, "doesn't cover" a covered service, unstated deductible) |
| 5 | prompt: never assert a deductible the SBC doesn't state | 8 | 0 | 2 | 4 true (Regence dental, twice per case) |
| 6 | fact sheet names the plans in each coverage gap; plan names masked before service matching | 10 | 0 | 0 | — |
| 7 | "deductible applies to everything else" only when no deductible is unstated | **10** | **0** | **0** | — |

Human-style review of runs 6 and 7 (every sentence mentioning a deductible or coverage, read against the
computed cells) found one wrong statement in run 6, caused by the fact sheet itself ("Plan C's deductible
applies to everything else" for a plan whose SBC leaves most deductibles unstated). Fixed for run 7; run 7
describes that plan as "for some services the SBC does not state whether the deductible applies".

Gate (D6): template fallbacks ≤ 1 of 10 — **met** (0 of 10); wrong deductible or coverage claims served —
**0 found** in run 7 on review. Cost: 55 explanation calls over the runs, $0.0237 in total, mean latency 13 s.

## Known limits

- Sentences that name no plan ("Both plans cover …") aren't attributed to a plan, so C2–C5 skip them.
- Services without an unambiguous alias (e.g. "hospital stays") aren't checked.
- The checks are rule-based; new phrasings will appear. Each new false positive or miss should become a
  case in `backend/tests/unit/test_claims.py`, as the ones above did.
