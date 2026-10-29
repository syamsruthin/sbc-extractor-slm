# 01 · Prioritized scope

## 1. Selection

The analysis ranked seven opportunities. This plan takes the top four as milestones (one of them
optional) and leaves the rest out, for the reasons in §3.

| Priority | Opportunity | Findings | Class | In this plan |
|---|---|---|---|---|
| P1 | **Result accuracy:** deductible-aware per-service verdicts and claim checks on explanations | F1, F2, O1 | Essential, conventional + deterministic rules | M1 |
| P2 | **Personal cost inputs:** age, rating area, household, per-member usage, reference-price overrides, editable comparisons | F3, F4, F5 | Essential, conventional | M2 |
| P3 | **Privacy controls and comparison history** | F10, F4 | Essential prerequisite for P4 | M3 |
| P4 | **Natural-language usage intake** | O2 | Targeted AI enhancement | M4 |
| P5 | **Cost-ranked catalog** | F7, O4 | Optional enhancement | M5, only if D7 = yes |

M0 (baseline and fixtures) comes first so every later change is measured against the discovery numbers.

## 2. Opportunity scopes

### P1 · Result accuracy (M1)

- **Problem.** The decision screen shows signals that contradict the computed totals. Per-row badges
  say a $10,600-deductible plan is "lower cost" for specialists and drugs (F1), and an explanation that
  passed every check made a false deductible claim (F2). The product's promise is that numbers and claims
  can be trusted, so these errors are the most damaging ones it can make.
- **Users / workflows.** Everyone who reads a comparison result; worst for HSA, catastrophic and other
  high-deductible plans (104 catalog plans follow federal deductible rules, per the roadmap log).
- **Outcomes and success criteria.**
  - On the F1 fixture, no row whose before-deductible and after-deductible verdicts disagree shows
    "lower cost" or "higher cost"; it shows "depends on deductible" (R-ACC-1..3).
  - The F2 sentence is rejected by the validator; on the labeled sentence set (T0.2) the new checks have
    precision ≥ 0.9 and catch every labeled false deductible or coverage claim (R-ACC-5..8, targets in D6).
  - Template fallback rate on the 9 audit cases stays ≤ 1 / 9 (baseline) after the stricter checks.
- **Approach.** Engine adds a before-deductible cost per use and a combined verdict (engine 1.3.0). The
  fact sheet tells the LLM both figures and which services each plan covers before the deductible
  (prompt explanation.v3). A new deterministic checker validates deductible and coverage claims against
  the `ComparisonResult`. The UI shows both figures and the combined verdict.
- **Excluded.** LLM-as-judge (only considered if the rule checks leave a measured gap); provenance links
  in the comparison table (F9, optional backlog item B-40); any change to scenario totals or extraction.

### P2 · Personal cost inputs (M2)

- **Problem.** Premium is usually the largest part of the annual total, and today it's priced for a
  40-year-old in an arbitrary rating area (F3). Users can't adjust reference prices (F4) and lose their
  inputs when they change anything (F5).
- **Users / workflows.** Marketplace shoppers (catalog plans), families, anyone iterating on a comparison.
- **Outcomes and success criteria.**
  - Catalog premiums prefill from the user's age(s) and chosen rating area, with the source shown.
  - Family comparisons can assign custom events to members; the engine's per-member accumulators are used.
  - A user can change any reference price and see it marked as custom in the result.
  - "Change inputs" reopens the builder with every input restored; re-submitting unchanged inputs
    reproduces the same `result_hash`.
- **Approach.** Two small read endpoints (rating areas, household premium quote), an optional `profile`
  block on `ComparisonRequest` for restoring the form, and builder UI changes. No engine change.
- **Excluded.** Subsidy (APTC) estimation (open question Q8 in discovery); ZIP or county lookup unless D3
  approves a new data source; tobacco rates; employer contribution modeling beyond the existing field.

### P3 · Privacy controls and history (M3)

- **Problem.** Usage profiles can reveal health information. Today they persist forever with no way to
  see or delete them (F10), and comparison history exists only as an unused API (F4). M4 would add
  free-text health descriptions, so these controls come first.
- **Outcomes and success criteria.** Users can list and delete saved comparisons; an optional retention
  period purges old ones; LLM calls for sensitive tasks bypass the response cache and request providers
  that don't collect data; logs contain no prompt or usage text (verified by test).
- **Excluded.** Authentication and multi-user tenancy (deferred in v2; still single-user local);
  encryption at rest.

### P4 · Natural-language usage intake (M4)

- **Problem.** The engine is only as good as the usage profile, and converting a life situation into
  event codes and counts is the hardest step for users.
- **Outcomes and success criteria.** A user can describe their year in up to 1,000 characters and get
  editable event rows; nothing is computed until they confirm; anything not modeled is listed rather than
  guessed. On the intake evaluation set: event precision ≥ 0.90, recall ≥ 0.80, count exact-match ≥ 0.80
  (approved, D6). With the LLM off the feature is hidden and everything else works.
- **Approach.** One structured-output LLM call constrained to the event catalog in `scenarios.yaml`, a
  deterministic validator (event in catalog, quoted phrase present in the text, count bounds), and the
  existing custom-event rows as the review UI. Not an agent.
- **Excluded.** Drug-name or provider-specific pricing, condition-to-utilization inference beyond what the
  user states ("diabetes" alone doesn't invent visits; it's listed as not modeled), storing the free text.

### P5 · Cost-ranked catalog (M5, optional)

- **Problem.** Shoppers can't find which plans cost least for them (F7).
- **Approach.** Rank all plans in one state and rating area by simulated annual total for one scenario,
  reusing `simulate()` and the M2 household quote. No AI.
- **Gate.** Only if D7 approves it for this release; depends on M2.

## 3. Explicitly out of scope

| Item | Why not now |
|---|---|
| Grounded Q&A panel (O3) | Demand unproven (discovery Q4); most of its value appears after P1–P4 |
| Agentic RAG, multi-agent systems, autonomous agents (O7) | No data source requires them; formulary and provider data are PRD non-goals |
| Operator audit workflow (O5), fallback recalibration (O6) | Matter mostly for a new plan year; no user-visible gain now |
| Export, share, print | Broker persona; not top-ranked; needs privacy decisions first |
| Provenance in the comparison table (F9) | Low priority; listed as optional backlog item B-40 |
| Subsidy (APTC), ZIP/county lookup | Need decisions and new data (Q8, D3) |
| Auth, Postgres, job queue | Deferred by the v2 roadmap |

## 4. Essential vs optional

- **Essential:** M0, M1, M2, M3.
- **Essential, AI feature approved (D5):** M4.
- **Deferred:** M5 (D7). Optional backlog items in [08-backlog.md](08-backlog.md) stay unscheduled.

## 5. Decisions

All nine were decided by the project owner on 2026-10-29; each took the recommended option.

| ID | Decision | Outcome (2026-10-29) | Affects |
|---|---|---|---|
| D1 | Per-row verdict semantics | **Approved:** show before- and after-deductible cost per use and a combined verdict with a "depends on deductible" state | T1.1–T1.3, T1.7 |
| D2 | Household premium rule | **Approved:** sum of each member's age rate, counting at most the 3 oldest children under 21. T2.2 still confirms the rule against CMS rating rules (A3) before merging | T2.2, T2.5 |
| D3 | Location input | **Approved:** rating-area dropdown from existing PUF data; ZIP/county lookup stays parked (B-41) | T2.1 |
| D4 | Comparison retention | **Approved:** keep until deleted; `SBCX_COMPARISON_RETENTION_DAYS` exists but is unset by default | T3.3 |
| D5 | Send free-text health descriptions to OpenRouter | **Approved:** opt-in per use with a notice, no caching, no storage, data collection denied | M4 |
| D6 | Quality targets | **Approved as proposed** (§2 and [06-testing-strategy §3](06-testing-strategy.md#3-ai-quality-evaluation)) | M1, M4 exit criteria |
| D7 | Include M5 | **Not in this release;** revisit after M2 | M5 (deferred) |
| D8 | Stored engine 1.2 comparisons | **Approved:** keep the stored result, no recompute; render in the old style | T1.4 |
| D9 | Scope of `data_collection: deny` | **Approved:** intake task only | T3.4 |
