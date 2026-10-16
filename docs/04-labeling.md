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

## Proposed guideline v1.1

- Cells with several components: put the **office-visit / outpatient** value in the
  structured fields, and the rest in `note`.
- Enforce a note limit with `maxLength` in the schema, not just in the prompt.

Then relabel the 25 (~$0.03) and hand-check ~10 documents to make the gold set.
