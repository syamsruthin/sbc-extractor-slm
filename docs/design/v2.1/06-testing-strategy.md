# 06 · Testing strategy and quality gates

Existing layers stay as they are (`docs/design/v2/07-evaluation-and-testing.md`): pytest unit, property
(hypothesis) and integration tests with the fake LLM; vitest; Playwright E2E with an isolated backend and
the fake LLM; `make score` for the parser; CI runs lint, types, backend tests, frontend tests and build.
This plan adds tests to those layers and two offline evaluations.

## 1. Test matrix

| Layer | M1 | M2 | M3 | M4 | M5 |
|---|---|---|---|---|---|
| Unit | `range_verdict`, `overall`, `est_before_deductible` per status; claim rules C1–C5; fact sheet fields | `age_band`, child rule, `nextPremiums`, `toRequest`/`fromRequest` round trip, overrides diff | LLM payload (`data_collection`), cache bypass, purge with frozen time | validator rules, frequency table, prompt builder | rank ordering |
| Property | before ≤ high, before ≥ after when deductible ≥ allowed; totals unchanged vs 1.2.0 | household total = sum of counted members | — | validator never accepts a quote absent from the text (hypothesis strings) | — |
| Integration (API) | stored 1.2.0 result loads; new fields present on create | rating areas, premium quote, profile round trip | delete one / all / 404, list fields, log capture | interpret: ok, retry, 422, 503, 404 when disabled | rank endpoint with seeded plans |
| Frontend (vitest) | new and old comparison fixtures render; badge text | details card, member select, prices panel | history list and delete | describe component states | sort option |
| E2E (Playwright) | existing 2 specs green | edit → recompare same hash | delete from Saved | interpret with fake LLM, confirm, compare | — |
| AI evaluation | claim-check precision/recall on `sentences.jsonl`; live 10-case audit | — | — | intake eval set metrics | — |
| Performance | comparison create < 200 ms (5 plans) | rating areas, quote < 50 ms | — | intake latency reported | TX < 2 s |
| Security / privacy | — | input bounds (ages, members) | logs contain no bodies/prompts; sensitive calls uncached | prompt-injection cases in eval set; text not stored | — |

## 2. Regression protection

- **Scenario totals:** a golden test computes every fixture comparison with engine 1.3.0 and asserts
  each `ScenarioResult.total` and `out_of_pocket` equals the 1.2.0 values stored in the fixture. Any
  difference fails M1.
- **Parser:** M1–M5 don't touch `domain/parse`; `make score` must still report gold 97.0% / 2.4% before
  each milestone merge.
- **Calibration:** rank agreement with coverage examples (baby 0.837, diabetes 0.706, fracture 0.738)
  must not change, since scenario math doesn't change. The calibration script from the 2026-10-28 audit
  isn't in the repo; it only needs re-creating if a totals test fails.
- **API types:** `make check-api-types` in every PR that changes a model.
- **Degraded mode:** the existing E2E variant with LLM off must pass after each milestone.

## 3. AI quality evaluation

### Explanation claims (M1)

| Metric | Definition | Gate (D6) |
|---|---|---|
| Claim-check precision | flagged sentences labeled `incorrect` / all flagged | ≥ 0.9 |
| Claim-check recall | labeled `incorrect` deductible/coverage sentences flagged / all such sentences | 1.0 on the labeled set |
| Template fallback rate | template explanations / live cases (9 audit cases + F1) | ≤ 1 / 10 |
| Wrong claims served | human review of the 10 live explanations | 0 deductible/coverage errors |

### Usage intake (M4)

| Metric | Definition | Gate (D6, approved) |
|---|---|---|
| Event precision | correct (event, member) pairs / returned pairs | ≥ 0.90 |
| Event recall | correct pairs / expected pairs | ≥ 0.80 |
| Count exact-match | correct counts / correct pairs | ≥ 0.80 |
| Unmodeled recall | expected unmodeled quotes returned as unmodeled | ≥ 0.80 |
| Injection cases | cases where output contains events not in the text | 0 |
| Validator rejection rate | calls ending in 422 | reported, no gate |

Both evaluations are offline scripts (`eval/explanations/check.py`, `eval/intake/run.py`) and write a
dated note under `eval/audits/`, as the existing audits do.

## 4. UX validation

- M1: screenshot review of the F1 comparison table at desktop and phone width; check that a reader can
  tell "depends on deductible" from the badge and tooltip alone.
- M2: walk through a family comparison with two members' events and catalog premiums from a non-default
  age and rating area.
- M4: three people unfamiliar with the app describe their own year (or a written persona) and say whether
  the events matched; note mismatches as eval cases.

These are manual checks recorded in the milestone's audit note; they don't block CI.

## 5. Quality gates per PR and milestone

| Gate | When | Command / evidence |
|---|---|---|
| Lint and types | every PR | `make lint` |
| Tests | every PR | `make test` |
| API types | PRs that change models | `make check-api-types` |
| E2E | milestone merge | `make e2e` (fake LLM) and LLM-off variant |
| Parser score | milestone merge | `make score` unchanged |
| AI eval | M1, M4 exit | eval scripts + audit note |
| Review | every PR | reviewer checks the task's acceptance criteria and DoD |
