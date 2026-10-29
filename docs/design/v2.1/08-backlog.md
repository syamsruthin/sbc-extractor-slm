# 08 · Implementation backlog

Ordered for execution. A coding agent takes the first item whose state is **ready**, implements it as
specified in [04-task-breakdown.md](04-task-breakdown.md), meets its acceptance criteria and the
definition of done, then sets it to done here. Items marked **blocked** wait for the decision or task
named. Items marked **human** need a person.

Legend: ⬜ ready · ⛔ blocked · 👤 human · 🟡 in progress · ✅ done · ⏸ deferred

## Baseline

| Date | Backend tests | Frontend tests | E2E | Gold acc / halluc | Explanations (llm / retry / template) |
|---|---|---|---|---|---|
| 2026-10-29 (discovery) | 442 | 13 | 2 (per roadmap) | 97.0% / 2.4% | 39 / 3 / 4 of 46 (dev DB) |
| 2026-10-29 (after M0–M4) | 539 | 29 | 2 (fake LLM and LLM off, both green; specs extended) | 97.0% / 2.4% | live, 10 cases: 10 / 0 / 0 |

## Decisions (all decided 2026-10-29, see 01-scope §5)

| ID | Decision | State |
|---|---|---|
| D1 | Combined verdict with "depends on deductible" | ✅ |
| D2 | Household premium rule | ✅ |
| D3 | Rating-area dropdown now, ZIP later | ✅ |
| D4 | Comparison retention default | ✅ |
| D5 | Send free-text health descriptions to OpenRouter (deny data collection, no cache) | ✅ |
| D6 | Quality targets for claim checks and intake | ✅ |
| D7 | Include M5 | ✅ (no, deferred) |
| D8 | Keep stored 1.2.0 results as-is | ✅ |
| D9 | `data_collection: deny` for intake only or all tasks | ✅ |

## Backlog

| # | Task | Title | Milestone | Size | Depends on | State |
|---|---|---|---|---|---|---|
| B-01 | T0.1 | Engine and explanation fixtures from the local DB | M0 | S | — | ✅ |
| B-02 | T0.3 | Record baseline run | M0 | S | — | ✅ |
| B-03 | T0.2 | Labeled explanation-sentence set | M0 | M | — | 🟡 👤 exported, not labeled |
| B-04 | T1.1 | Engine 1.3.0: before-deductible cost, combined verdict | M1 | M | B-01 | ✅ |
| B-05 | T1.2 | Regenerate API types, update data contracts doc | M1 | S | B-04 | ✅ |
| B-06 | T1.4 | Stored 1.2.0 results still load | M1 | S | B-04, D8 | ✅ |
| B-07 | T1.3 | Table shows before/after and combined badge | M1 | M | B-05 | ✅ |
| B-08 | T1.5 | Fact sheet v3 and prompt explanation.v3 | M1 | M | B-04 | ✅ |
| B-09 | T1.6 | Claim checker C1–C5 + eval script | M1 | L | B-08, B-03, D6 | ✅ live gate met; labeled-set precision/recall waits on B-03 |
| B-10 | T1.7 | Explanation badge text | M1 | S | B-09 | ✅ |
| B-11 | T1.8 | Truncate long plan names (SHOULD) | M1 | S | — | ✅ |
| B-12 | T1.9 | Live verification and audit note | M1 | M | B-07, B-09, B-10 | ✅ |
| B-13 | T2.3 | `ComparisonRequest.profile` | M2 | S | — | ✅ |
| B-14 | T2.6 | Reference prices panel and custom-price display | M2 | M | — | ✅ |
| B-15 | T2.1 | Rating areas endpoint | M2 | S | D3 | ✅ |
| B-16 | T2.2 | Household premium quote endpoint | M2 | M | D2 | ✅ |
| B-17 | T2.4 | Builder details card and premium prefill | M2 | L | B-13, B-15, B-16 | ✅ |
| B-18 | T2.5 | Per-member custom events | M2 | M | B-17 | ✅ |
| B-19 | T2.7 | Restore and edit a comparison | M2 | M | B-13, B-14, B-17 | ✅ |
| B-20 | T3.1 | Delete endpoints, list fields | M3 | S | — | ✅ |
| B-21 | T3.2 | Saved comparisons page and notice | M3 | M | B-20 | ✅ |
| B-22 | T3.3 | Retention setting and purge | M3 | S | D4 | ✅ |
| B-23 | T3.4 | Sensitive LLM calls (no cache, deny data collection) | M3 | S | D5, D9 | ✅ |
| B-24 | T3.5 | Log hygiene test | M3 | S | B-23 | ✅ |
| B-25 | T4.1 | Intake eval set | M4 | M | — | 🟡 👤 40 cases drafted by Claude; human review pending |
| B-26 | T4.2 | Intake schema, rules, validator | M4 | M | — | ✅ |
| B-27 | T4.3 | Intake service and prompt | M4 | M | B-26, B-23 | ✅ |
| B-28 | T4.4 | `POST /usage/interpret` | M4 | S | B-27 | ✅ |
| B-29 | T4.5 | Builder: Describe your year | M4 | M | B-28, B-18 | ✅ |
| B-30 | T4.6 | Intake evaluation, enable by default | M4 | M | B-25, B-27 | 🟡 eval run, D6 targets met on the draft set; enabling by default waits on B-25 |
| B-31 | T5.1 | Rank endpoint (optional) | M5 | M | B-16, D7 | ⏸ D7 |
| B-32 | T5.2 | Catalog sort by yearly cost (optional) | M5 | M | B-31, B-17 | ⏸ D7 |

Sizes: S ≤ half a day, M ≈ 1–2 days, L ≈ 3+ days for one developer or agent session, including tests.
They are rough planning aids, not commitments.

## Optional, not scheduled (from discovery, outside the selected scope)

| # | Item | Finding | Why parked |
|---|---|---|---|
| B-40 | Provenance links in the comparison table | F9 | Low priority; easy follow-up after M1 |
| B-41 | ZIP/county → rating area lookup | F3, D3 | Needs a new CMS data source |
| B-42 | Subsidy (APTC) estimate | F3, discovery Q8 | Needs a scope decision |
| B-43 | LLM usage view for operators (`/meta/usage`) | F4 | Operator-only |
| B-44 | Export / share a comparison | F12 | Broker persona; after M3 privacy work |
| B-45 | Grounded Q&A panel | O3 | Demand unproven (discovery Q4) |
| B-46 | Benefit-attribute catalog filters | F7 | Revisit with M5 |
| B-47 | Investigate the two uploads stuck at `summaries_status = pending` | F8, discovery Q10 | Unconfirmed; may be dev state |

## Progress log

| Date | Milestone | Outcome |
|---|---|---|
| 2026-10-29 | M0 | Fixture `backend/tests/fixtures/f1_comparison.json` + `tests/make_fixtures.py`; stored totals reproduced. Baseline confirmed (lint, 442 backend, 13 frontend, 2 E2E). Sentences exported to `eval/explanations/sentences.jsonl`, labeling pending (B-03). |
| 2026-10-29 | M1 | Engine 1.3.0, prompt explanation.v3, `claims.py` (C1–C5), table and badge. Live: 10/10 explanations on the first try after fixes ([audit](../../../eval/audits/2026-10-29-m1-result-accuracy.md)). Deviations: not-covered cells get a full-price before-deductible estimate (keeps the existing "lower cost" verdict for coverage gaps); C3 also rejects deductible claims the SBC doesn't state; fact sheet names the plans in each coverage gap. |
| 2026-10-29 | M2 | Rating areas and household quote endpoints, `ComparisonRequest.profile`, builder details card, per-member events, prices panel, restore from a result. Browser check found restored premiums overwritten by CMS rates when arriving from the result page; fixed and covered by a StrictMode test. |
| 2026-10-29 | M3 | Delete endpoints, Saved page, retention purge (startup + `sbcx purge-comparisons`), `sensitive` LLM calls (no cache, `data_collection: deny`, accepted by OpenRouter live), log-hygiene tests. |
| 2026-10-29 | M4 | `domain/intake/`, `POST /usage/interpret`, "Describe your year". Draft eval: precision 1.00, recall 0.98, counts 1.00, unmodeled 1.00, 0 leaks ([audit](../../../eval/audits/2026-10-29-m4-intake.md)). `SBCX_INTAKE_ENABLED` stays false until a human-reviewed set passes. |
