# PRD: SBC Plan Comparison v2 (deterministic extraction + LLM explanations)

| | |
|---|---|
| Status | Draft for review |
| Branch | `design/v2-hybrid-pipeline` |
| Date | 2026-10-27 |
| Replaces | v1 plan: a fine-tuned SLM generates the full extraction JSON for each document |
| Related | [02-architecture](02-architecture.md) · [03-HLD](03-HLD.md) · [04-LLD](04-LLD.md) · [05-data-contracts](05-data-contracts.md) · [06-cost-model](06-cost-model.md) · [07-evaluation](07-evaluation-and-testing.md) · [08-implementation-plan](08-implementation-plan.md) · [09-decisions](09-decisions.md) |

## 1. Summary

People choosing a health plan get a Summary of Benefits and Coverage (SBC) for each option.
SBCs follow a federally mandated template, but they are long (median 8 pages) and written
so that real dollar differences are hard to see.

v2 changes **who does what**:

| Job | v1 design | v2 design |
|---|---|---|
| Read numbers out of the SBC | Fine-tuned SLM generates ~2.3k tokens of JSON (50–184 s/doc, 74.7–97.6% field accuracy) | **Deterministic Python parser** (template-anchored). A small LLM only re-reads the cells the parser is unsure about |
| Explain each section in plain language | Not designed | **Small LLM** writes a short summary per section, grounded in the extracted JSON and the limitations text |
| Compare plans and compute money differences | Not designed | **Deterministic comparison + cost engine** (no LLM) |
| Explain the comparison to the user | Not designed | **LLM** turns the computed comparison JSON into a readable explanation. A validator rejects any number that isn't in the input |

The principle: **code does the reading and the math; LLMs only write prose about numbers that code already produced.**

## 2. Problem

1. **Generating extraction with an LLM is slow and unreliable for a fixed template.** The
   zero-shot 4B model scored 74.7% with 36.5% hallucination. The teacher (DeepSeek V4 Flash)
   reached 97.6% but takes ~50 s per document. Since every SBC uses the same CMS template,
   most of that work is parsing, which code can do exactly.
2. **The rule-based prototype already works.** `audit_tools/ext.py` + `mk.py` + `excl.py`
   produced base labels for 1,379 new documents in labels v1.4. After sampled PDF review, the
   value error rate fell from 27% to about 4% of docs. It isn't packaged, tested or wired into `src/`.
3. **Comparing plans means arithmetic.** "Plan B saves you $1,140 a year if you have a baby"
   depends on the deductible, coinsurance and OOP-maximum interaction. LLMs get this kind of
   multi-step arithmetic wrong, and the error isn't visible to the user.
4. **People need the "so what".** A table of 26 services × 2 networks doesn't tell anyone
   which plan to pick. A grounded narrative does.

## 3. Goals and non-goals

### Goals

- G1. Extract a standardized benefits JSON from any CMS-template SBC PDF in under 3 s (p95), with no LLM call for at least 90% of documents.
- G2. Field accuracy at least as good as the teacher on the gold set: ≥ 98% field accuracy and ≤ 1% hallucination.
- G3. Add a plain-language summary to each benefit section, written by a small LLM, with every number in it traceable to the JSON.
- G4. Compare a user's plan with one or more other plans: per-service differences, estimated annual cost under usage scenarios, the SBC coverage examples, coverage gaps.
- G5. Generate an explanation from the comparison JSON that is 100% numerically grounded (enforced by a validator, with a templated fallback).
- G6. Every displayed value can be traced to its source page and cell in the PDF.

### Non-goals (v2.0)

- Recommending a plan as advice. We show differences and estimates; we don't act as a licensed broker.
- Non-SBC documents (full policy contracts, EOBs, formularies), scanned PDFs without a text layer (detected and rejected with a clear message; OCR is a later phase).
- Provider-network lookups ("is my doctor in network") and drug formulary lookups.
- Dental-only and Medicare plans.
- Enrollment or any transaction.

## 4. Users and use cases

| Persona | Situation | What they need |
|---|---|---|
| **Employee at open enrollment** (primary) | Employer offers 2–3 plans (e.g. PPO vs HDHP). Has the SBC PDFs. | Upload all options, see which is cheaper for *their* expected usage and why |
| **Marketplace shopper** | Has their current plan's SBC, wants to see if a marketplace plan is better | Upload current plan, compare against catalog plans in their state/metal level |
| **Benefits advisor / broker** (secondary) | Explains options to many clients | Fast side-by-side, exportable explanation, traceability to the source |

### User stories

| ID | Story | Priority |
|---|---|---|
| US-1 | As a user, I upload an SBC PDF and see its benefits in a clean, standardized layout with a short summary per section. | P0 |
| US-2 | As a user, I upload two or more SBCs and see a side-by-side comparison with the differences highlighted. | P0 |
| US-3 | As a user, I enter my monthly premium for each plan (and optional employer HSA/HRA contribution) so annual costs are real. | P0 |
| US-4 | As a user, I pick a usage profile (low / moderate / high, or a custom list such as "6 specialist visits, 1 MRI, monthly brand drug") and see estimated annual cost per plan. | P0 |
| US-5 | As a user, I read a plain-language explanation of which plan costs less in which situations, and why. | P0 |
| US-6 | As a user, I click any number and see the PDF page and the original cell text it came from. | P1 |
| US-7 | As a user, I compare my uploaded plan against marketplace plans from the catalog (same state, plan year, filters). | P1 |
| US-8 | As a user, I see warnings when a value was uncertain or inferred ("deductible may apply; the SBC doesn't say"). | P0 |
| US-9 | As a user, I see the plans' own coverage examples (having a baby, managing diabetes, simple fracture) side by side. | P1 |
| US-10 | As an operator, I batch-ingest the CMS PUF SBC catalog and monitor extraction quality per insurer. | P1 |
| US-11 | As an operator, I see per-request LLM cost, latency and grounding-failure rates. | P1 |

## 5. Functional requirements

### FR-A Ingestion and extraction

- A1. Accept PDF up to 10 MB / 20 pages. Validate magic bytes; reject encrypted or textless PDFs with a specific message.
- A2. Deduplicate by SHA-256. A re-upload of a known document returns the cached extraction.
- A3. Detect whether the document is a CMS-template SBC (header phrases, "Important Questions" table, "Common Medical Event" table). Non-SBC → reject.
- A4. Extract into **BenefitsDocument v2** ([05-data-contracts](05-data-contracts.md)): every v1 `SBCExtraction` field, plus per-field provenance (page, raw cell text), confidence, limitations text per service, deductible type (embedded/aggregate), coverage examples, other covered services.
- A5. Fields below the confidence threshold go to a **cell-level LLM fallback**. Fallback results are validated and marked `source="llm_fallback"`.
- A6. Apply the existing deterministic `normalize()` rules plus the v1.4 labeling conventions (row-only deductible flags, first-listed part, later-charge rule, IHCP column handling).
- A7. Run business-rule validation (e.g. family ≥ individual, OOP limit ≥ deductible, OOP limit ≤ the plan year's legal maximum). Violations become warnings, not silent fixes.

### FR-B Section summaries

- B1. Produce one summary (≤ 60 words) for each of 13 sections (plan overview, deductible & OOP, office visits, tests, drugs, outpatient surgery, emergency, hospital stay, mental health, pregnancy, recovery & special needs, children's eye & dental, exclusions & other covered).
- B2. Input to the summarizer = that section's JSON + its limitations text. No other context.
- B3. Every number in a summary must appear in the section input (grounding check). On failure: one retry with feedback, then fall back to a template sentence.
- B4. Summaries are cached by (document hash, parser version, prompt version, model).

### FR-C Comparison and cost engine

- C1. Compare 2–5 plans. One is the "base" (the user's current/first plan).
- C2. Align services across plans by the fixed schema keys. Align drug tiers by `category`, not position.
- C3. For each service and network, compute: the cost-share difference, an estimated cost per use (using reference allowed amounts), and a verdict (`better` / `worse` / `same` / `not_comparable`).
- C4. Compute annual cost per plan for each usage scenario = premiums − employer contributions + simulated out-of-pocket cost, walking events through deductible → copay/coinsurance → OOP limit ([06-cost-model](06-cost-model.md)).
- C5. Report best case (premium only) and worst case (premium + in-network OOP limit) for every plan.
- C6. When a needed input is unknown (e.g. `deductible_applies = null`), compute low and high bounds and report a range plus the assumption.
- C7. Show the SBC coverage examples (Peg / Joe / Mia) as the plan states them, without recomputation.
- C8. Rank the differences by estimated dollar impact so the explanation focuses on what matters.
- C9. The engine is deterministic and versioned: same inputs + same engine version → identical output.

### FR-D Explanation

- D1. Input = the ComparisonResult JSON (top-ranked differences, scenario table, warnings, section summaries) + the user's profile. The LLM never sees the PDF.
- D2. Output = a structured explanation: headline, 3–5 key points, per-scenario paragraph, "watch out for" list, assumptions and disclaimer.
- D3. **Numeric grounding validator**: every currency amount, percentage and count in the output must match a value in the input (after formatting normalization). Fail → retry once with the offending numbers listed → fall back to the deterministic template explanation.
- D4. Must not recommend a plan as advice. Uses phrasing like "costs less under the moderate-use scenario". A disclaimer is always present.
- D5. Streams to the UI (server-sent events) once validated paragraph-by-paragraph, or after full validation (configurable).

### FR-E Catalog (P1)

- E1. Batch job ingests SBCs listed in the CMS Plan Attributes PUF (14,476 unique URLs) with the same pipeline.
- E2. Catalog search by state, plan year, metal level, plan type, issuer.
- E3. Optional premium lookup from the CMS Rate PUF by rating area and age.

## 6. Non-functional requirements

| Area | Requirement |
|---|---|
| Latency | Extraction p95 ≤ 3 s (no fallback), ≤ 8 s (with fallback). Summaries ≤ 10 s for all sections (parallel). Comparison engine ≤ 200 ms. Explanation ≤ 15 s p95. |
| Accuracy | Field accuracy ≥ 98%, hallucination ≤ 1% on the 10-doc gold set. ≥ 97% on the 105 cell-reviewed v1.4 val docs. |
| Grounding | 100% of displayed numbers trace to the extraction or the computed comparison. |
| Cost | ≤ $0.01 LLM cost per comparison of 3 plans (summaries cached per document). |
| Determinism | Parser and cost engine are pure functions of input + version. |
| Traceability | Every field stores page number and raw cell text. |
| Privacy | SBCs are plan documents, not personal data. Usage profiles can reveal health information. Since v2.1 (decision D4) comparisons, with their premiums, ages and usage, are kept on the local machine until the user deletes them on the Saved page, with an optional retention period (`SBCX_COMPARISON_RETENTION_DAYS`); the builder says so. No profile data in logs. Free-text usage descriptions are sent to the LLM only on request, never cached or stored, and only to providers that don't collect data (D5, D9). |
| Availability | Extraction and comparison work with the LLM provider down (degraded: no summaries, template explanation). |
| Observability | Per-stage latency, fallback rate, grounding failure rate, LLM tokens/cost, per-insurer extraction quality. |

## 7. Success metrics

| Metric | Target at launch |
|---|---|
| Gold-set field accuracy (parser + fallback) | ≥ 98% |
| Documents needing no LLM fallback | ≥ 90% |
| Explanation grounding pass rate on first try | ≥ 95% (100% after retry/fallback) |
| Template-fallback explanations served | ≤ 2% |
| Median time from upload of 2 plans to explanation | ≤ 20 s |
| User-reported "number is wrong" per 100 comparisons | ≤ 1 |

## 8. Assumptions

- Uploaded SBCs use the CMS SBC template (true for marketplace and employer group plans; the template is required by regulation).
- Premiums aren't in the SBC. The user enters them, or (catalog) they come from the Rate PUF.
- Reference allowed amounts are estimates. They are labeled as such, and the user can override them.

## 9. Open questions

| # | Question | Default if not decided |
|---|---|---|
| Q1 | Primary comparison target: user's uploads only, or uploads + marketplace catalog? | **Decided: both** (catalog moves into v2.0) |
| Q2 | Explanation model: hosted or self-hosted SLM? | **Decided: OpenRouter** |
| Q3 | Summarizer model | **Decided: capable OpenRouter model**, configurable per task |
| Q4 | Keep the doc-level fine-tuned extractor? | **Decided: fine-tuning deferred**; OpenRouter handles fallback and summaries |
| Q5 | Source for reference allowed amounts | Configurable YAML with illustrative national medians, user-overridable |
| Q6 | Include HSA tax savings in annual cost? | No for v2.0; show employer HSA/HRA contribution only |

## 10. Release scope

| Release | Scope |
|---|---|
| v2.0 (MVP) | US-1–5, US-8. Uploads only. Hosted LLM. Simple web UI |
| v2.1 | US-6 (PDF provenance viewer), US-9 (coverage examples), US-11 |
| v2.2 | US-7, US-10 (catalog + Rate PUF), self-hosted SLM for summaries/fallback |
