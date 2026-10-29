# 00 · Discovery baseline

The discovery and feasibility analysis (2026-10-29, `main @ fd4b31a`) is the source for this plan. This
page lists the parts of it the plan relies on, one correction found while planning, and the measured
baseline that success is compared against.

## Findings used

| ID | Finding | Evidence | Used by |
|---|---|---|---|
| F1 | Per-service verdict ("lower cost") is computed after the deductible is met, so high-deductible plans look cheaper on almost every row | `backend/sbcx/domain/compare/engine.py:64` (`est_per_use`), live comparison `f8c68687…` (Moda TX Bronze 8700 `17933TX0010006-00` vs Anthem Catastrophic `32753MO0990015-01`) | M1 |
| F2 | Explanation grounding checks numbers and superlatives only; a served explanation said Moda Bronze makes you "pay full cost until the deductible is met" although its visits and drugs have copays with the deductible not applying | `domain/explain/generate.py` (`_validate`, `claim_check`), same live comparison | M1 |
| F3 | Catalog premiums prefill for age 40 and the first rating area; no age, location, household input; family usage modeled as one member | `frontend/src/pages/CompareBuilderPage.tsx` (prefill effect), `frontend/src/lib/compareForm.ts` (`member: 0`) | M2 |
| F4 | Reference-price overrides, comparison history and LLM usage have APIs but no UI | `ComparisonRequest.reference_price_overrides`, `useReferencePrices()` unused, `api.listComparisons` unused | M2, M3 |
| F5 | "Change inputs" rebuilds the builder from the selection tray, losing premiums and usage | `ComparisonPage.tsx` link to `/compare`, builder `defaultValues` | M2 |
| F6 | Explanation template fallback 4 / 46 (8.7%) in the local DB vs PRD target ≤ 2% (includes dev runs) | `comparisons.explanation.source` | M1 (measure only) |
| F7 | Catalog search is substring-only; no ranking by cost for the user | `CatalogRepo.search` | M5 (optional) |
| F10 | Comparisons (including custom usage) are stored indefinitely without consent or delete; PRD says session by default | `ComparisonRow`, PRD §6 Privacy | M3 |
| O1 | Claim-level verification, deterministic first | analysis §4 | M1 |
| O2 | Natural-language usage intake with user confirmation | analysis §4 | M4 |
| O4 | Cost-ranked catalog | analysis §4 | M5 |

## Correction found while planning

The analysis said the per-use figure appears "with no caveat". That's not accurate: `DiffTable` in
`ComparisonPage.tsx` ends with the footnote *"Per use" assumes the deductible is already met and uses
reference prices*. The finding stands, because the per-row badges ("lower cost", green) carry the
after-deductible verdict on every row and the footnote is below a long table. The fix in M1 is the same.

## Verified facts the plan depends on

- The engine already supports per-member claims and family accumulators: `Event.member` (0–9),
  `Claim.member`, `_Acc.ded_remaining(m)` / `oop_remaining(m)` in `cost_model.py`. Only the UI sends
  `member: 0` for everything.
- A before-deductible cost per use can be computed from existing functions:
  `member_pays(cs, allowed, ded_remaining=<deductible>, bound, applies=resolve_applies(cs, key, bound, hints, visit=1))`.
- `deductible_status()` already classifies every cell (`applies`, `does_not_apply`, `applies_per_sbc`,
  `applies_hsa_rules`, `applies_catastrophic_rules`, `first_visits_before`, `before_per_sbc`, `not_stated`, `none`).
- The Rate PUF rows loaded cover ages `0-14`, `15` … `63`, `64 and over`, keyed by `RatingAreaId`
  (e.g. `Rating Area 1`) and state. No ZIP or county mapping is in the repo.
- Catalog states hold up to 240 plans (TX), then 188 (WI), 125 (OK).
- `PremiumRepo.lookup(plan_key, age, rating_area)` and `GET /catalog/plans/{id}/premiums?age=&rating_area=` exist.
- The OpenRouter client has a response cache (`var/llm_cache.sqlite`) keyed on the full payload and stores
  the output; `llm_call` log records contain no prompt text.
- `ComparisonRow` stores `request` (incl. `custom_scenario`) and `result` as JSON; `init_db()` adds new
  columns through `_ADDED_COLUMNS`.

## Baseline (measured 2026-10-29 unless noted)

| Metric | Baseline | Source |
|---|---|---|
| Backend tests | 442 passed | `make backend-test` |
| Frontend unit tests | 13 passed | `make frontend-test` |
| E2E tests | 2 (green per roadmap M20) | `frontend/e2e/compare.spec.ts`; not re-run during discovery |
| Gold field accuracy / hallucination | 97.0% / 2.4% | `sbcx score --set gold` |
| Reviewed v1.4 agreement | 99.5% | audit 2026-10-27 (parser 2.1.0) |
| Coverage-example rank agreement (engine 1.2) | baby 0.837, diabetes 0.706, fracture 0.738 | roadmap deviation log |
| Explanation source, local DB | 39 llm, 3 llm_retry, 4 template (of 46) | `comparisons` table |
| Explanation source, 9 audit cases (live, prompts v2) | 8 LLM (2 after retry), 1 template | audit 2026-10-28 |
| Wrong qualitative claims served | ≥ 1 known (F2) | live comparison `f8c68687…` |
| Per-row verdicts contradicting before-deductible reality | at least 8 rows in the F1 comparison (specialist, urgent care, mental health, rehab, habilitation, 3 drug tiers; specialty was cut off in the capture) | live page |
| LLM cost | explanation ≈ $0.00045/call, summary ≈ $0.00008/call | `llm_calls` |
| Premium personalization | age 40 + first rating area only | code |

Baselines that don't exist yet and are created in M0: a labeled set of explanation sentences for claim
checking (T0.2), and an intake evaluation set (T4.1). Their targets were approved on 2026-10-29 (D6).
