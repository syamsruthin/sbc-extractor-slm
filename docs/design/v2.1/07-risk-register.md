# 07 · Risk register

Likelihood and impact: L (low), M (medium), H (high).

## Risks

| ID | Risk | L | I | Mitigation | Owner / trigger |
|---|---|---|---|---|---|
| RK1 | Stricter claim checks raise the template-fallback rate (already 4/46 in the dev DB vs a ≤ 2% PRD target) | M | M | Fact sheet v3 gives the model the facts it lacked; C1–C5 measured on the labeled set before enabling; gate ≤ 1/10 live; if missed, tune aliases and patterns, not the threshold | T1.9 |
| RK2 | Claim-check false positives on paraphrases (e.g. "copays apply right away") or false negatives on phrasing not in the patterns | M | M | Labeled sentence set; skip ambiguous aliases rather than guess; new misses become test cases | T1.6 |
| RK3 | Users find two cost figures per cell harder to read | M | M | Combined badge carries the message; UX check in M1; tooltip wording reviewed | T1.3 |
| RK4 | Household child rule is wrong or incomplete (tobacco, age-on-effective-date) | M | H | D2 confirms the rule against CMS rating rules first (A3); show "before subsidy, non-tobacco" with every prefilled premium | T2.2 |
| RK5 | Rating area names mean little to users ("Rating Area 3") | H | M | Show the count of plans priced; D3 records ZIP/county lookup as the follow-up; users can still type their own premium | T2.4 |
| RK6 | OpenRouter `data_collection: deny` unsupported for the configured model, or name differs | M | M | Verify in T3.4 (A5); on failure the intake feature reports unavailable instead of falling back to an allow-provider | T3.4 |
| RK7 | Delete endpoints and stored ages/usage are unprotected because there is no auth | M | H if hosted | Acceptable only for the local single-user app; any hosting decision must add auth first (recorded in README) | Hosting decision |
| RK8 | Intake maps conditions to invented utilization ("diabetes" → visits) | M | H | Prompt requires `unmodeled`; validator requires quotes; eval has condition-only cases; user confirmation | T4.6 |
| RK9 | Prompt injection in the description | L | L | Delimited block, schema-constrained output, quote rule, user review; injection cases in eval | T4.1 |
| RK10 | Engine field additions break old stored results or the frontend | L | M | Optional fields with defaults; integration test with a stored 1.2.0 row; old-fixture vitest | T1.4 |
| RK11 | M1 and M2 both edit `domain/comparison.py` and generated types | M | L | Merge one, regenerate types, rebase the other | Sequencing |
| RK12 | Labeling (T0.2) and eval writing (T4.1) depend on human time | H | M | Start them first; M1 can merge engine and UI parts (T1.1–T1.4) before T1.6's gate | M0, M4 |
| RK13 | Intake cost or latency higher than estimated | L | L | Measured in T4.6; budget cap already enforced per process | T4.6 |

## Assumptions to validate

| ID | Assumption | How to validate | Task |
|---|---|---|---|
| A1 | Users read the per-row badge more than the footnote, so the badge must carry the deductible caveat | M1 UX check | T1.9 |
| A2 | Using the individual deductible for "one use before deductible" is right for family coverage too | Review with the cost-model doc §family rules | T1.1 |
| A3 | Family premium = sum of member age rates with at most 3 children under 21 counted (CMS rating rule) | Check 45 CFR 147.102 and CMS rate guidance | T2.2 |
| A4 | Rate PUF rows for a plan exist only in rating areas where it's sold, so an empty quote means "not sold here" | Spot-check 5 plans | T2.1 |
| A5 | OpenRouter provider routing accepts `data_collection: "deny"` together with `require_parameters: true` | OpenRouter docs + one live call | T3.4 |
| A6 | 1,000 characters is enough to describe a year of care | Eval cases and UX check | T4.1 |
| A7 | The local DB's 46 explanations are representative enough to label for C1–C5 | Compare with the 9 audit cases | T0.2 |

## Dependencies

| Dependency | Needed by | Status |
|---|---|---|
| Local DB with catalog, premiums and comparison `f8c68687…` | T0.1 | Present on the dev machine |
| CMS Rate PUF loaded | M2 | Loaded (226,950 rows) |
| OpenRouter key and credit | T1.9, T4.6 | Present (used in discovery); budget cap $2/process |
| Human reviewer | T0.2, T4.1, D1–D9, live checks | Needed |
