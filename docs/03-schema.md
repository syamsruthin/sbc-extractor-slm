# Phase 1: Schema design (v1)

Code: [src/schema.py](../src/schema.py) (Pydantic). One definition serves three uses:

| Use | How |
|---|---|
| Teacher labeling | Gemini `response_schema` |
| Training targets | the student learns to emit this JSON |
| Serving | vLLM guided decoding with `SBCExtraction.model_json_schema()` |

## What the real data looks like

The same fact is written many different ways across insurers:

```
$80copay; deductible does not apply
$100copayment/visit, Deductible does not apply
$70.00 copayafter deductible
25%coinsurance
No charge
Not covered
```

Drug tiers range from 4 to 6 per plan, with names like "Value drug tier", "Tier 1b" and
"Specialty drugs and Oral Chemotherapy".

## Decisions

1. **Structured cost-sharing plus a short `note`.** Plans become numerically comparable.
   The `note` field captures only what the structured fields can't (per-day copays, visit limits).
   We chose this over also storing the raw cell text, which would have added ~1.5k output tokens.
2. **All 26 rows of the CMS SBC template.** The task is complete and well defined.
3. **Drug tiers as a variable-length list with a standard `category`.** This stays faithful to
   the document and is still comparable.
4. **Three-valued flags (`true`/`false`/`null`).** `null` means "the document doesn't say."
   If the teacher is forced to pick true or false, it guesses, and the student learns to
   hallucinate. Labels should reflect real uncertainty.
5. **A fixed shape.** Every key is always present, so evaluation compares the same
   field paths across every document.
6. **Out of scope for v1:** coverage examples (they parse badly, see 02), special network
   tiers (e.g. Indian Health Care Providers), and mail-order drug pricing.

## Cost of the schema

| | tokens |
|---|---|
| Output, compact JSON | ~2,300 |
| Output, indented JSON | ~3,500 |
| JSON schema itself | ~1,660 |

**Lesson: output tokens set latency.** Prefill (reading the 6k-token SBC) runs in parallel
and is fast. Decoding (writing the JSON) produces one token at a time. So we:
- train on **compact** JSON (~35% fewer tokens than indented),
- **don't** put the JSON schema in the student's prompt. The fine-tuned model learns the
  shape, and at serving time vLLM guided decoding enforces it. That saves ~1.7k prompt tokens.
  The teacher does get the schema, since it hasn't been trained on it.

## Evaluation implications (Phase 2)

- Score field by field over the flattened paths (e.g. `services.specialist_visit.in_network.copay`).
- Numbers: exact match after normalization. `note` and names: fuzzy match, reported separately.
- Drug tiers: align predicted and gold tiers by order before comparing.
- Track `null` correctness separately. Predicting a value where the gold label is `null`
  is a hallucination, and that's the error that matters most.
