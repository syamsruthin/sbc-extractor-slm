# 03 · Implementation specification

Requirements are testable statements. "MUST" items are required for the milestone exit; "SHOULD" items
may slip to the backlog with a note. Each requirement names the tasks that implement it.

## 1. Result accuracy (M1)

### Functional

| ID | Requirement | Tasks |
|---|---|---|
| R-ACC-1 | For every service and drug-tier cell, the comparison result MUST include `est_cost_before_deductible` as a `{low, high}` range, computed as in [02 §2.1](02-solution-design.md#21-before-deductible-cost-per-use). Not-covered cells get the full reference price (as `est_cost_per_use` does), so coverage gaps keep their verdict; unknown cells are `null`. *(Changed during implementation: `null` for not-covered cells turned their existing "lower cost" verdict into "not comparable".)* | T1.1 |
| R-ACC-2 | For every non-base plan, each service and drug diff MUST include `verdicts_before_deductible` and `overall_verdicts`, computed as in [02 §2.2](02-solution-design.md#22-combined-verdict). | T1.1 |
| R-ACC-3 | The side-by-side table MUST show, per cell, the before-deductible and after-deductible cost per use, and a badge from `overall_verdicts`. `depends_on_deductible` MUST render as an amber "depends on deductible" badge with a tooltip naming both figures. | T1.3 |
| R-ACC-4 | Comparisons stored before engine 1.3.0 (no new fields) MUST render exactly as today. | T1.3, T1.4 |
| R-ACC-5 | The fact sheet MUST include before- and after-deductible cost per use for top differences, `overall_verdict`, and per plan `covered_before_deductible` and `deductible_applies_to_everything_else` ([02 §2.3](02-solution-design.md#23-explanation-inputs-fact-sheet-v3-prompt-explanationv3)). | T1.5 |
| R-ACC-6 | The explanation validator MUST reject sentences that break rules C1–C5 ([02 §2.4](02-solution-design.md#24-claim-checker-domainexplainclaimspy)) and feed them into the existing retry message. | T1.6 |
| R-ACC-7 | The template explanation MUST pass C1–C5 for every fixture comparison. | T1.6 |
| R-ACC-8 | The explanation badge tooltip MUST list the checks that ran: amounts and percentages, lowest/highest claims, deductible and coverage claims. | T1.7 |
| R-ACC-9 | SHOULD: long plan names in table headers truncate to one line with the full name in a tooltip. | T1.8 |

### Technical

- `ENGINE_VERSION` → `1.3.0`; `EXPLANATION_PROMPT_VERSION` → `explanation.v3`.
- New fields default to `None` / `{}` in Pydantic so old JSON validates (`ComparisonResult.model_validate`
  on stored rows).
- Regenerate `frontend/openapi.json` and `frontend/src/api/schema.d.ts` (`make gen-api`); `make
  check-api-types` must pass.
- No change to scenario totals: `result_hash` changes only because of the added fields; scenario totals
  for every fixture MUST be byte-identical to engine 1.2.0 (tested).

## 2. Personal cost inputs (M2)

### Functional

| ID | Requirement | Tasks |
|---|---|---|
| R-PER-1 | `GET /catalog/rating-areas?state=XX` MUST return the distinct rating areas with premium rows in that state, sorted by number (`Rating Area 2` before `Rating Area 10`), each with the count of distinct plans priced. | T2.1 |
| R-PER-2 | `GET /catalog/plans/{plan_id}/premium-quote?rating_area=..&ages=a,b,c` MUST return per-member band, rate and `counted` flag, `monthly_total`, and `missing_ages`, applying the child rule in [02 §3.2](02-solution-design.md#32-rules) (D2). | T2.2 |
| R-PER-3 | When at least one catalog plan is selected and premiums are loaded, the builder MUST show a "Your details" card: one age per household member (1 for individual, up to 10 for family) and one rating-area select per state among the selected catalog plans. | T2.4 |
| R-PER-4 | Catalog premium fields MUST prefill from the household quote and show "CMS 2026 rate, before subsidy" under the field; user edits MUST mark the field as user-entered and stop prefill for it. | T2.4 |
| R-PER-5 | With family coverage, each custom event row MUST have a "Who" select listing the household members; the request MUST carry the member index. | T2.5 |
| R-PER-6 | The builder MUST have a collapsible "Prices used for estimates" panel listing every reference price with its label; changed values (≥ 0, ≤ 1,000,000) MUST be sent as `reference_price_overrides`; a "Reset" button restores defaults. | T2.6 |
| R-PER-7 | The result page MUST show which prices were custom ("2 custom prices") and the premium source when `profile` is present. | T2.6, T2.7 |
| R-PER-8 | "Change inputs" MUST open `/compare?from=<id>` with plans, base plan, premiums, contributions, coverage, network, scenarios, custom events (with members), overrides and profile restored. | T2.7 |
| R-PER-9 | Re-submitting a restored comparison without edits MUST produce the same `result.result_hash`. | T2.7 |

### Technical

- `ComparisonRequest.profile: ComparisonProfile | None = None` with `ages: list[int]` (0..120, ≤ 10) and
  `rating_areas: dict[str, str]` (state → rating area). The engine ignores it; it isn't part of the result
  hash because the hash is computed over the result only.
- `selection` hook gets `replace(items: SelectedPlan[])`.
- Uploaded plans keep manual premium entry only (no change).

## 3. Privacy controls and history (M3)

| ID | Requirement | Tasks |
|---|---|---|
| R-PRV-1 | `DELETE /comparisons/{id}` MUST return 204 and remove the row; unknown id → 404 `E_NOT_FOUND`. | T3.1 |
| R-PRV-2 | `DELETE /comparisons` MUST remove all comparisons and return 204. | T3.1 |
| R-PRV-3 | A "Saved comparisons" page MUST list comparisons (date, plan names, scenario labels) newest first, open each, delete each, and delete all after an in-page confirmation step. | T3.2 |
| R-PRV-4 | When `SBCX_COMPARISON_RETENTION_DAYS` is set, comparisons older than N days MUST be deleted at startup and by `sbcx purge-comparisons`. | T3.3 |
| R-PRV-5 | `complete_json(..., sensitive=True)` MUST skip the response cache (read and write) and send the provider data-collection-deny setting. | T3.4 |
| R-PRV-6 | No log line (app or `llm_calls`) MUST contain request bodies, prompt text or model output. | T3.5 |
| R-PRV-7 | The builder MUST show a short notice on what is saved and how to delete it. | T3.2 |
| R-PRV-8 | `ComparisonListItem` MUST add `scenario_labels: list[str]` (backward compatible). | T3.1 |

## 4. Natural-language usage intake (M4)

| ID | Requirement | Tasks |
|---|---|---|
| R-INT-1 | `POST /usage/interpret` MUST implement the contract in [02 §5.2](02-solution-design.md#52-contract). | T4.4 |
| R-INT-2 | Every returned event MUST satisfy validator rules 1–4 ([02 §5.3](02-solution-design.md#53-processing)); one retry with listed violations, then 422. | T4.2, T4.3 |
| R-INT-3 | The call MUST use `task="usage_intake"`, `sensitive=True`, model `SBCX_MODEL_INTAKE`. | T4.3 |
| R-INT-4 | The text MUST NOT be stored in the database, the LLM cache or logs. | T4.3, T4.6 |
| R-INT-5 | In the builder, "Describe your year" MUST show only when `/health` reports `intake_available` (new field: `intake_enabled` and `llm_configured`). Interpreted events MUST be appended as editable custom-event rows marked "from your description" with the quote as a tooltip, and `unmodeled` items listed as "Not included". Nothing is submitted until the user presses Compare. | T4.5 |
| R-INT-6 | Before the first Interpret in a session, the user MUST confirm a notice that the text is sent to an AI service and not stored. | T4.5 |
| R-INT-7 | On the intake eval set, the metrics in [01 §2 P4](01-scope.md#p4--natural-language-usage-intake-m4) MUST meet the D6 targets before the feature is enabled by default (`SBCX_INTAKE_ENABLED`, default false until then). | T4.1, T4.6 |

## 5. Cost-ranked catalog (M5, optional, D7)

| ID | Requirement | Tasks |
|---|---|---|
| R-RNK-1 | `POST /catalog/rank` takes state, rating area, ages, coverage tier, network, one scenario (preset id or custom), optional metal and plan type, limit ≤ 50; returns plans sorted by `total.high` then `total.low`, each with total range and premium. | T5.1 |
| R-RNK-2 | Plans without a premium for the given ages and rating area are excluded and counted in `excluded_no_premium`. | T5.1 |
| R-RNK-3 | Ranking 240 plans (TX) MUST take < 2 s on the dev machine. | T5.1 |
| R-RNK-4 | The catalog page MUST offer "Sort by estimated yearly cost" when details are set, reusing the M2 details. | T5.2 |

## 6. Non-functional

| Area | Requirement |
|---|---|
| Compatibility | All 442 existing backend tests, 13 frontend tests and 2 E2E tests stay green, except tests updated for the intended changes listed in the task |
| Performance | Comparison create stays < 200 ms server time for 5 plans (engine target); rating areas < 50 ms; premium quote < 50 ms |
| Degraded mode | With `SBCX_LLM_MODE=off`, M1–M3 work fully; M4 is hidden |
| Determinism | Engine 1.3.0: same inputs → same `result_hash` |
| Accessibility | New controls have labels; badges convey state with text, not only color |
