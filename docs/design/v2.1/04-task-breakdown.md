# 04 · Task breakdown

## Definition of done (applies to every task)

1. Code follows the surrounding style (ruff, ruff format, mypy, eslint, tsc clean: `make lint`).
2. The tests named in the task exist and pass, and `make test` is green.
3. If an API model changed: `make gen-api` was run and `make check-api-types` passes.
4. If an engine or prompt output changed: the version in `backend/sbcx/versions.py` is bumped as the task says.
5. Docs touched by the change are updated (`docs/design/v2/05-data-contracts.md`, `06-cost-model.md`,
   README API list) and the task is ticked in [08-backlog.md](08-backlog.md).
6. No unrelated refactors. Anything the task leaves open is written in the backlog as a new item.

Paths below are relative to `backend/` for Python and `frontend/` for TypeScript unless they start with
`docs/`, `eval/` or `data/`.

---

## M0 · Baseline and fixtures

### T0.1 Engine and explanation fixtures
- **Objective:** reproducible inputs for M1 tests that don't need the PDF corpus.
- **Files:** `tests/fixtures/` (new): `f1_moda_bronze.json`, `f1_anthem_catastrophic.json`
  (BenefitsDocument JSON exported from the local DB for `17933TX0010006-00` and `32753MO0990015-01`, plus
  their catalog metal and HSA flag), `f2_explanation.json` (the stored explanation of comparison
  `f8c68687c8aa46229e11129fab76e0c7`); `tests/make_fixtures.py` (new) to regenerate them.
- **Details:** export `documents.benefits` and `catalog_plans.metal/hsa_eligible`; the request uses the
  stored request (premiums 320 and 290, in-network, individual, low/moderate/high).
- **Depends on:** none.
- **Acceptance:** a unit test builds `PlanInput`s from the fixtures, runs `compare()` and reproduces the
  stored scenario totals of `f8c68687…` exactly.
- **Tests:** `tests/unit/test_fixtures.py`.

### T0.2 Labeled explanation-sentence set
- **Objective:** a baseline to measure claim-check precision and recall.
- **Files:** `eval/explanations/sentences.jsonl` (new), `eval/explanations/export.py` (new),
  `eval/explanations/README.md` (new).
- **Details:** export every sentence (headline, key points, scenario texts, watch-out) of every stored
  explanation in `backend/var/sbcx.db` with its comparison id and plan keys. A human labels each
  sentence that states a deductible or coverage fact as `correct` / `incorrect` / `n/a`, with the rule it
  would fall under (C1–C5). At least the F2 sentence must be labeled `incorrect` [C1].
- **Depends on:** none. **Needs a human** for labeling (≈ 46 explanations, a few hundred sentences).
- **Acceptance:** file committed; README states who labeled and when; counts per label recorded in
  `00-discovery-baseline.md`.
- **Tests:** none (data).

### T0.3 Record baseline run
- **Objective:** confirm the discovery numbers on the branch before changes.
- **Details:** run `make test`, `make e2e`, `make score`; record results in the backlog's baseline row.
- **Depends on:** none. **Acceptance:** numbers match `00-discovery-baseline.md` or differences are explained.

---

## M1 · Result accuracy

### T1.1 Engine: before-deductible cost and combined verdict
- **Objective:** R-ACC-1, R-ACC-2.
- **Files:** `sbcx/domain/comparison.py`, `sbcx/domain/compare/engine.py`, `sbcx/versions.py`.
- **Details:**
  1. `CellView.est_cost_before_deductible: Money | None = None`.
  2. `class OverallVerdict(str, Enum)`: `better`, `worse`, `same`, `depends_on_deductible`, `not_comparable`.
  3. `ServiceDiff` and `DrugTierDiff`: `verdicts_before_deductible: dict[str, Verdict] = {}`,
     `overall_verdicts: dict[str, OverallVerdict] = {}`.
  4. `engine.est_before_deductible(cs, key, allowed, hints, ded) -> Money | None` per 02 §2.1, using
     `resolve_applies(..., visit=1)` and `member_pays(..., ded_remaining=ded, bound=b, applies=...)`.
     `ded` = `getattr(plan.deductible, network).individual` (0 if `has_deductible` is false or the value is None).
  5. `view()` takes the extra arguments and fills the field; `_diff()` computes the two new dicts with
     `range_verdict()` and `overall()` per 02 §2.2.
  6. `ENGINE_VERSION = "1.3.0"`.
- **Depends on:** T0.1, D1.
- **Acceptance:** on the F1 fixture, specialist, urgent care, mental health, rehabilitation, habilitation
  and the generic/preferred/non-preferred drug rows have `overall_verdicts["B"] == depends_on_deductible`;
  primary care for the catastrophic plan stays `better` (first visit before deductible); scenario totals
  are identical to engine 1.2.0.
- **Tests:** `tests/unit/test_engine_verdicts.py`: table tests for `range_verdict` and `overall` (every
  combination), `est_before_deductible` for each `deductible_status`, the F1 fixture assertions, a
  hypothesis property (`before.low <= before.high`; before ≥ after for any covered cell with a
  deductible ≥ allowed).

### T1.2 Contract and type regeneration
- **Objective:** keep frontend types in sync.
- **Files:** `frontend/openapi.json`, `frontend/src/api/schema.d.ts`; `docs/design/v2/05-data-contracts.md`.
- **Details:** `make gen-api`; document the new fields and enum.
- **Depends on:** T1.1. **Acceptance:** `make check-api-types` passes. **Tests:** existing.

### T1.3 Side-by-side table: both figures and combined badge
- **Objective:** R-ACC-3, R-ACC-4.
- **Files:** `src/pages/ComparisonPage.tsx` (`DiffTable`, `VERDICT` map), `src/lib/format.ts` if a
  helper is needed, `src/test/fixtures/` (new fixture from T0.1 via `tests/make_frontend_fixture.py`).
- **Details:**
  - Cell: line 1 `display`; line 2 "Before deductible ≈ $X" (or "$X–$Y" when low ≠ high); line 3 "After
    deductible ≈ $Y"; badge from `overall_verdicts[plan]`, falling back to `verdicts[plan]` when
    `overall_verdicts` is empty (old results).
  - New label: `depends_on_deductible → "depends on deductible"` (amber, `bg-amber-50 text-amber-800`),
    `title` = "Before the deductible: A $X vs B $Y. After: A $X' vs B $Y'."
  - "Show only differences" treats `depends_on_deductible` as a difference.
  - Footnote: "Before deductible: what one use costs if you haven't met the deductible. After deductible:
    what it costs once you have. Both use reference prices."
- **Depends on:** T1.2.
- **Acceptance:** with the F1 fixture, no catastrophic-plan row shows "lower cost" where the before
  figure is higher; an old (1.2.0) fixture renders the same text as today.
- **Tests:** `src/pages/pages.test.tsx` cases for new and old fixtures.

### T1.4 Backward compatibility of stored results
- **Objective:** R-ACC-4, D8.
- **Files:** `tests/integration/test_comparisons_api.py`.
- **Details:** insert a stored 1.2.0 result JSON (from T0.1 export) and `GET` it.
- **Depends on:** T1.1. **Acceptance:** 200, fields default, no recomputation. **Tests:** as described.

### T1.5 Fact sheet v3 and prompt v3
- **Objective:** R-ACC-5; give the LLM the facts it lacked in F2.
- **Files:** `sbcx/domain/explain/generate.py` (`factsheet`, `SYSTEM`, `template_explanation`),
  `sbcx/versions.py`, `sbcx/infra/llm/fake_responders.py` if keys changed.
- **Details:** per 02 §2.3. Rename `estimated_cost_per_use` → `cost_per_use_after_deductible`; add
  `cost_per_use_before_deductible` as `{low, high}`; add `overall_verdict`; add per-plan
  `covered_before_deductible` (labels; catastrophic primary care as "Primary care visit (first 3 visits)")
  and `deductible_applies_to_everything_else`. Add the three prompt rules. Template watch-out: when a
  plan has `deductible_applies_to_everything_else`, say so; otherwise list up to 4
  `covered_before_deductible` items. `EXPLANATION_PROMPT_VERSION = "explanation.v3"`.
- **Depends on:** T1.1.
- **Acceptance:** for the F1 fixture, Moda's `covered_before_deductible` includes primary care,
  specialist, urgent care and generic drugs; Anthem's has preventive care and "Primary care visit (first
  3 visits)" and `deductible_applies_to_everything_else = true`.
- **Tests:** `tests/unit/test_engine_explain.py` additions; numeric grounding still passes for the
  template on all fixtures.

### T1.6 Claim checker C1–C5
- **Objective:** R-ACC-6, R-ACC-7.
- **Files:** `sbcx/domain/explain/claims.py` (new), `sbcx/domain/explain/generate.py` (`_validate`,
  `explain`, `_HEDGE` reuse), `eval/explanations/check.py` (new).
- **Details:** per 02 §2.4 and §2.5. Signature `deductible_claims(e: Explanation, result: ComparisonResult,
  facts: dict) -> list[str]`; `facts` gives plan names for `_mentions`. Called from `_validate`, which now
  needs `result` (thread it from `explain`). Retry message gets a line "deductible or coverage claims that
  contradict the plan data: …". `eval/explanations/check.py` runs the checker over `sentences.jsonl`
  (needs each comparison's stored result) and prints precision / recall per rule.
- **Depends on:** T1.5, T0.2.
- **Acceptance:** the F2 sentence is flagged [C1]; on `sentences.jsonl`, precision ≥ 0.9 and recall = 1.0
  on labeled `incorrect` sentences (D6); the template explanation for all fixtures passes.
- **Tests:** `tests/unit/test_claims.py`: one positive and one negative case per rule, hedge skip,
  multi-plan sentence, unknown alias skipped, F2 regression.

### T1.7 Explanation badge text
- **Objective:** R-ACC-8.
- **Files:** `src/components/ExplanationPanel.tsx`.
- **Details:** tooltip: "Checked against the calculation: N amounts and percentages, lowest/highest claims,
  and statements about deductibles and coverage. Other wording isn't machine-checked."
- **Depends on:** T1.6. **Acceptance / tests:** text present in `pages.test.tsx`.

### T1.8 Plan-name truncation in headers (SHOULD)
- **Objective:** R-ACC-9.
- **Files:** `src/pages/ComparisonPage.tsx` table headers and scenario table.
- **Details:** `max-w-[14rem] truncate` with `title`. **Depends on:** none. **Tests:** visual check (T1.9).

### T1.9 Live verification
- **Objective:** confirm M1 against the real model.
- **Details:** with OpenRouter on, re-create the 9 audit cases (2026-10-28 audit) plus the F1 pair;
  record explanation source, claim violations and any wrong claims read by a human, and screenshots of the
  F1 table. Write `eval/audits/<date>-m1-result-accuracy.md`.
- **Depends on:** T1.3, T1.6, T1.7. **Acceptance:** template fallbacks ≤ 1 of 10; zero wrong deductible or
  coverage claims served; F1 rows as in T1.1.

---

## M2 · Personal cost inputs

### T2.1 Rating areas endpoint
- **Objective:** R-PER-1.
- **Files:** `sbcx/infra/repos.py` (`PremiumRepo.rating_areas(state)`), `sbcx/services/catalog.py`,
  `sbcx/api/routes/catalog.py`, `sbcx/api/schemas.py` (`RatingArea{rating_area, plans_priced}`,
  `RatingAreas{items}`).
- **Details:** `SELECT rating_area, COUNT(DISTINCT plan_key) … WHERE state = ? GROUP BY rating_area`;
  natural sort by the trailing number. Measure latency on the real DB; if > 50 ms add
  `Index("ix_premium_state_area", "state", "rating_area")` in `models.py` (created by `create_all` for new
  DBs; for existing DBs add a `CREATE INDEX IF NOT EXISTS` in `init_db`).
- **Depends on:** D3. **Acceptance:** TX returns its rating areas in numeric order.
- **Tests:** `tests/integration/test_catalog_api.py` with a seeded premiums table; empty state → `[]`.

### T2.2 Household premium quote
- **Objective:** R-PER-2.
- **Files:** `sbcx/services/catalog.py` (`age_band(age)`, `household_quote(plan_id, rating_area, ages)`),
  `sbcx/api/routes/catalog.py`, `sbcx/api/schemas.py` (`PremiumQuoteMember{age, band, monthly_premium,
  counted}`, `HouseholdQuote{plan_id, rating_area, members, monthly_total, missing_ages}`).
- **Details:** `ages` query is a comma list of 1–10 integers 0..120; rule per 02 §3.2; `monthly_total`
  is `None` when `missing_ages` is non-empty; rounding to cents.
- **Depends on:** D2, A3. **Acceptance:** 2 adults + 4 children under 21 → the youngest child is
  `counted: false`; ages 14 and 64 map to `0-14` and `64 and over`.
- **Tests:** unit tests for `age_band` and the child rule; integration test of the endpoint.

### T2.3 Request profile
- **Objective:** carry details for restore and display (R-PER-7, R-PER-8).
- **Files:** `sbcx/domain/comparison.py` (`ComparisonProfile`, `ComparisonRequest.profile`), regenerate types.
- **Depends on:** none. **Acceptance:** old stored requests validate; profile round-trips through
  `POST`/`GET`. **Tests:** `test_comparisons_api.py`.

### T2.4 Builder: Your details card and prefill
- **Objective:** R-PER-3, R-PER-4.
- **Files:** `src/pages/CompareBuilderPage.tsx`, `src/lib/compareForm.ts` (schema: `ages`, `ratingAreas`,
  per-plan `premiumSource`), `src/api/client.ts`, `src/hooks/api.ts` (`useRatingAreas(state)`,
  household quote fetch).
- **Details:** card appears when any selected plan has `catalogPlanId` and `/catalog/facets`
  `premiums_loaded` is true. State per catalog plan comes from `GET /catalog/plans/{id}` (`state`).
  Individual coverage shows one age field; family shows a list with Add / Remove (1..10). Default age 40
  (today's behavior) until the user changes it, shown as a placeholder hint "used for premiums". Prefill
  replaces the current age-40 effect; it runs when ages or areas change and only touches fields with
  `premiumSource === "cms"`. Under prefilled fields: "CMS 2026 rate, before subsidy". `toRequest` adds
  `profile`.
- **Depends on:** T2.1, T2.2, T2.3.
- **Acceptance:** changing age from 40 to 60 changes catalog premiums; a typed premium is kept.
- **Tests:** vitest for `toRequest` (profile), prefill logic as a pure function (`nextPremiums(prev,
  quotes)`) in `compareForm.ts` with unit tests.

### T2.5 Per-member custom events
- **Objective:** R-PER-5.
- **Files:** `src/pages/CompareBuilderPage.tsx`, `src/lib/compareForm.ts`.
- **Details:** when coverage is family, each custom row shows "Who" with member labels ("You (40)",
  "Member 2 (38)", …); default 0; removing a member resets rows pointing to it to 0. Individual coverage
  hides the select and sends 0.
- **Depends on:** T2.4 (member list). **Acceptance:** a family comparison with two members' events
  shows a different total than the same events on one member when each member has their own deductible
  (embedded) — verified on a fixture in a backend test.
- **Tests:** `toRequest` unit test; backend `test_cost_model.py` case for two members (if not already covered).

### T2.6 Reference prices panel
- **Objective:** R-PER-6, R-PER-7 (prices part).
- **Files:** `src/pages/CompareBuilderPage.tsx` (new section or `src/components/PricesPanel.tsx`),
  `src/lib/compareForm.ts` (`overrides` field, only changed values), `src/pages/ComparisonPage.tsx`
  (assumptions card: "Custom prices: MRI $1,800 (default $1,200)").
- **Details:** uses `useReferencePrices()`; collapsed by default; inputs per key with the label and the
  source/version line; "Reset to defaults".
- **Depends on:** none. **Acceptance:** overriding the MRI price changes the moderate and high scenario
  totals for plans where MRI cost-sharing is coinsurance.
- **Tests:** vitest for overrides diffing; existing backend tests cover `with_overrides`.

### T2.7 Restore and edit a comparison
- **Objective:** R-PER-8, R-PER-9.
- **Files:** `src/hooks/selection.tsx` (`replace`), `src/pages/CompareBuilderPage.tsx` (read
  `?from=`, `useComparison`), `src/lib/compareForm.ts` (`fromRequest(resp) -> FormInput`),
  `src/pages/ComparisonPage.tsx` (link `to={`/compare?from=${id}`}`, details line).
- **Details:** `fromRequest` is the inverse of `toRequest`; selection items built from
  `result.plans` (`label` = plan name, `source` = catalog when `catalog_plan_id`).
- **Depends on:** T2.3, T2.4, T2.6.
- **Acceptance:** round trip `toRequest(fromRequest(x))` equals `x.request` for fixtures; E2E: edit then
  compare gives the same hash when nothing changed.
- **Tests:** vitest round-trip; Playwright step added to `e2e/compare.spec.ts`.

---

## M3 · Privacy controls and history

### T3.1 Delete endpoints and list fields
- **Objective:** R-PRV-1, R-PRV-2, R-PRV-8.
- **Files:** `sbcx/infra/repos.py` (`ComparisonRepo.delete`, `delete_all`), `sbcx/services/comparison.py`,
  `sbcx/api/routes/comparisons.py`, `sbcx/api/schemas.py`.
- **Details:** a background explanation for a deleted comparison must not recreate it:
  `set_explanation` already returns when the row is missing (verified).
- **Depends on:** none. **Tests:** integration tests for both endpoints and the 404.

### T3.2 Saved comparisons page and notice
- **Objective:** R-PRV-3, R-PRV-7.
- **Files:** `src/pages/HistoryPage.tsx` (new), `src/App.tsx` (route `comparisons`), `src/components/Layout.tsx`
  (nav item "Saved"), `src/hooks/api.ts` (`useComparisons`, `useDeleteComparison`), builder notice text.
- **Details:** delete-all uses an inline confirm row (no `window.confirm`).
- **Depends on:** T3.1. **Tests:** vitest render + delete flow with mocked API.

### T3.3 Retention setting and purge
- **Objective:** R-PRV-4.
- **Files:** `sbcx/config.py`, `sbcx/main.py` (startup), `sbcx/cli.py` (`purge-comparisons`),
  `backend/.env.example`.
- **Depends on:** D4. **Tests:** unit test with frozen time.

### T3.4 Sensitive LLM calls
- **Objective:** R-PRV-5.
- **Files:** `sbcx/infra/llm/base.py` (protocol), `openrouter.py`, `fake.py`.
- **Details:** `complete_json(..., cache: bool = True, sensitive: bool = False)`. When `sensitive`, skip
  `self.cache.get/put` and set `payload["provider"]["data_collection"] = "deny"`. Verify the parameter
  name and value in the OpenRouter provider-routing docs before merging (A5); if the account has no
  provider that satisfies `require_parameters` + deny for the configured model, the call fails with
  `LLMError` and the feature degrades (tested with a mocked 404/400).
- **Depends on:** D5, D9. **Tests:** `tests/unit/test_llm_client.py` with `httpx.MockTransport`: payload
  contains the setting; cache file unchanged after a sensitive call.

### T3.5 Log hygiene test
- **Objective:** R-PRV-6.
- **Files:** `tests/integration/test_privacy_logs.py` (new).
- **Details:** capture logs (caplog) during a comparison with custom events and (after M4) an intake call;
  assert no event names from the request body, no intake text, no model output appear.
- **Depends on:** T3.4 (and re-run after T4.4). **Tests:** as described.

---

## M4 · Natural-language usage intake

### T4.1 Intake evaluation set
- **Objective:** a measurable target before shipping (R-INT-7).
- **Files:** `eval/intake/cases.jsonl` (new), `eval/intake/README.md`.
- **Details:** ≥ 40 descriptions written by a human, covering: single person / family; numbers vs
  frequency words; pregnancy; chronic conditions with and without stated visits; drug fills; ER and
  hospital; things not modeled (dental cleanings for adults, glasses, a named drug's price); typos; a
  prompt-injection attempt. Each case lists expected events (event, count, member) and expected
  `unmodeled` quotes.
- **Depends on:** none. **Needs a human.**

### T4.2 Intake domain: schema, rules, validator
- **Objective:** R-INT-2.
- **Files:** `sbcx/domain/intake/__init__.py`, `schema.py` (`UsageDraft`, `DraftEvent`, `Unmodeled`),
  `rules.py` (frequency table, `allowed_counts(quote)`), `validate.py`.
- **Details:** per 02 §5.3; pure functions; no LLM import.
- **Depends on:** none. **Tests:** `tests/unit/test_intake_validate.py`: each rule, frequency table,
  merging duplicates, quotes with extra whitespace or different case.

### T4.3 Intake service and prompt
- **Objective:** R-INT-2..4.
- **Files:** `sbcx/domain/intake/prompt.py` (system prompt built from `ScenarioConfig.event_types`),
  `sbcx/services/usage.py` (new), `sbcx/config.py` (`model_intake`, `intake_enabled`),
  `sbcx/versions.py` (`INTAKE_PROMPT_VERSION = "intake.v1"`), `sbcx/infra/llm/fake_responders.py`
  (deterministic responder for tests).
- **Details:** user text inside `<description>` … `</description>`; prompt says to ignore instructions
  in it. One retry with violations. `sensitive=True`.
- **Depends on:** T4.2, T3.4. **Tests:** service tests with the fake client: valid, invalid-then-valid,
  invalid twice → error, LLM error → unavailable.

### T4.4 Intake API
- **Objective:** R-INT-1.
- **Files:** `sbcx/api/routes/usage.py` (new), `sbcx/main.py` (router), `sbcx/api/schemas.py`,
  `sbcx/api/routes/health.py` (`intake_available`), regenerate types.
- **Details:** returns 404 when `intake_enabled` is false (feature off), 503 when no LLM or the budget is
  spent. `/health` reports `intake_available = intake_enabled and llm_available`.
- **Depends on:** T4.3. **Tests:** `tests/integration/test_usage_api.py`; re-run T3.5.

### T4.5 Builder: Describe your year
- **Objective:** R-INT-5, R-INT-6.
- **Files:** `src/components/UsageDescribe.tsx` (new), `src/pages/CompareBuilderPage.tsx`,
  `src/hooks/api.ts` (`useInterpretUsage`), `src/api/client.ts`.
- **Details:** text area (1,000-char counter), notice with an "I understand" checkbox kept in
  `sessionStorage` (try/catch), Interpret button, result appended to custom rows with a "from your
  description" tag; `unmodeled` listed; errors as toasts with "Add events manually instead".
- **Depends on:** T4.4, T2.5. **Tests:** vitest with mocked API; Playwright case with fake LLM.

### T4.6 Intake evaluation and cost
- **Objective:** R-INT-7 gate.
- **Files:** `eval/intake/run.py` (new), `eval/audits/<date>-m4-intake.md`.
- **Details:** run the eval set against the configured model; report precision, recall, count
  exact-match, unmodeled recall, validator rejection rate, mean cost and latency per call.
- **Depends on:** T4.1, T4.3. **Acceptance:** D6 targets met → set `intake_enabled` default true (separate
  commit).

---

## M5 · Cost-ranked catalog (optional, D7)

### T5.1 Rank endpoint
- **Objective:** R-RNK-1..3.
- **Files:** `sbcx/services/ranking.py` (new), `sbcx/api/routes/catalog.py`, schemas.
- **Details:** load ready catalog plans for state (and optional filters), household quote per plan (T2.2),
  `simulate()` once per plan with `deductible_hints(metal, hsa)`; sort; cap at `limit`. Load BenefitsDocuments
  in one query.
- **Depends on:** T2.2. **Tests:** integration with 3 seeded plans; timing test on the real DB (skipped
  without data).

### T5.2 Catalog sort option
- **Objective:** R-RNK-4.
- **Files:** `src/pages/CatalogPage.tsx`, details state shared with the builder (lift to a small context
  or `localStorage`, try/catch).
- **Depends on:** T5.1, T2.4. **Tests:** vitest.
