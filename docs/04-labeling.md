# Phase 1: Teacher labeling

```bash
uv run python src/label_sbcs.py --limit 1   # smoke test
uv run python src/label_sbcs.py             # everything not yet labeled
```

- **Teacher:** `deepseek/deepseek-v4-flash` on OpenRouter. Open weights (MIT license), so
  the labels can be published and used for training without license questions.
- **Request settings:** JSON-schema structured outputs (`strict`), `temperature=0`, reasoning
  off, `provider.require_parameters=true` (only route to providers that enforce the schema).
- **Validation:** every response is re-validated with Pydantic, and failures are retried
  (2 retries). Each call is logged with token counts and cost in `data/labels/_log.jsonl`.

## First run: 25 SBCs

| | |
|---|---|
| Valid labels | 25/25 on the first attempt |
| Total cost | **$0.03** (~$0.0013 per doc; ~$2 for 1,500) |
| Latency | ~30–60s per doc; 6 in parallel |
| Label size | ~2.5k Qwen tokens as compact JSON (the target the student learns) |

## What the spot-check found

1. **Runaway outputs.** 3 of 25 calls produced 10–11k output tokens, but their saved labels are
   normal-sized, so the extra tokens were whitespace padding inside the JSON. This is a known
   failure mode of constrained decoding, and those 3 calls cost ~7x more. **Fix:**
   `max_tokens=8000`. A truncated response fails validation and gets retried.
2. **Cells with several components.** Some SBC cells give different prices for parts of one
   service, e.g. mental health outpatient = "office visit $40 copay; other outpatient 40%
   coinsurance". With only one `CostShare` slot, the teacher left `copay` and `coinsurance_pct`
   null and put everything in `note` (10 of 1,300 service cells). That's sensible, but for
   comparison the structured fields should hold the main (office-visit) value.
3. **Notes run long.** The guideline says under 20 words, yet notes reach 40+ words
   (max 268 characters). Long notes make the targets longer and are hard to evaluate.
4. **Accurate in general.** Deductibles, OOP limits, copays, "deductible does not apply"
   flags, and drug tiers all matched the source in the documents checked.

## Guideline v1.1 (applied)

- Cells with several components: put the **office-visit / outpatient** value in the
  structured fields, and the rest in `note`.
- Enforce a note limit with `maxLength` in the schema, not just in the prompt.

Then relabel the 25 (~$0.03) and hand-check ~10 documents to make the gold set.

## Gold review → guideline v1.2

The first-pass gold review (see `data/gold/README.md`) found the teacher ~99% accurate on
service cells, with errors clustered in **multi-part cells**. v1.2 makes the rule unambiguous:

- Fill both copay and coinsurance only for one combined charge ("$250 copay then 20%").
- Different parts of a service: the first listed part goes in the structured fields, the rest in `note`.
- Prices come from the price columns only, never from the limitations column.

The 25 teacher labels are still v1.1. Relabeling with v1.2 happens when the dataset is scaled
up. Gold labels follow v1.2 through tracked corrections.

**Takeaway:** review the labels, find a cluster of errors, sharpen the guideline, and add a
deterministic check if possible. That loop is how label quality improves. Prompt tweaks
alone don't make a teacher consistent.

## Guideline v1.3: tested, not adopted (2026-10-17)

After the PDF review of the gold set (63 corrections), the gold conventions were written up
as guideline v1.3. The main change was a strict rule for `deductible_applies`: decide it from
*that row only* (its price cell, its limitations cell, or a legend mark like "†"), and never
infer it from the page-1 "covered before the deductible" list or the chart-wide note. v1.3 also
added plan-info conventions (issuer = header brand, no `Issuer:` prefix in plan_name,
plan_type ∈ HMO/PPO/EPO/POS) and "exclusions only from the does-NOT-cover box".

**Validated before relabeling.** I labeled the 10 gold docs with v1.3 (~$0.007) and scored them:

| Teacher run (gold set) | Field acc. | deductible_applies | percent | money | plan_info |
|---|---|---|---|---|---|
| v1.1 prompt + repair pass | **97.6%** | **93.7%** | 98.2% | 99.1% | 88.0% |
| v1.3 prompt + repair pass + normalizer | 96.5% | 89.8% | 98.2% | 99.3% | 86.0% |

- The strict rule **fixed** the inferred flags for Ambetter (NE) and 22 Health (FL), but on
  HMO Louisiana the teacher read the "†Deductible does not apply" legend as "every unmarked
  cell = applies" (39 new errors). The teacher keeps inferring; it just picks a different signal.
- Multi-part cells were still filled in both fields despite the explicit rule.
- Caveat: the gold set was built from v1.1 labels, so where v1.1 made an acceptable
  judgment call, gold inherited it. That biases this comparison towards v1.1, but not by
  enough to make v1.3 a clear win.

**Decision: keep the v1.2 labels for training. No relabel, $0.27 saved.** The wins that *were*
reliable came from deterministic code, applied to all 450 v1.2 labels instead of a re-prompt:

- `normalize()` now also drops a 0 next to a real price (`"$40 copay"` must not become
  `coinsurance_pct: 0`; 48 cells in 17 training labels), maps `plan_type` to
  HMO/PPO/EPO/POS, and strips an `Issuer:` prefix from `plan_name`.

v1.3 stays in `src/schema.py` as `ANNOTATION_GUIDELINES_V1_3`, and the run is reproducible with
`label_sbcs.py --guidelines 1.3`.

**Known mismatch carried into Phase 3:** the gold set follows the strict v1.3 conventions,
while the training labels carry the teacher's inferred `deductible_applies` (8.8% hallucination
rate on gold). A student trained on them will lose points on that field by design, so it's
reported separately. Fixing it properly is a product decision about what the field should mean:
**strict** (row-level, mostly null) or **document-level** (use legends and the page-1 list;
more useful for comparison, but the gold set would need re-reviewing).

**Lesson:** validate a guideline change on the gold set before paying to relabel. A prompt
rule that reads clearly to a human doesn't necessarily change model behavior, but a
deterministic normalizer always does.
