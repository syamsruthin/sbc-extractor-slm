# Phase 2: Evaluation harness

```bash
uv run python eval/run_mlx.py --run <name> [--model mlx-community/...]   # predictions on the 10 gold docs
uv run python eval/score.py eval/predictions/<name>                      # field-level report + score.json
```

Every model in this project (baselines, fine-tunes, quantized variants, the vLLM endpoint)
writes `eval/predictions/<run>/<plan_id>.json` and goes through the **same scorer**. That's
what makes the numbers comparable.

## How scoring works

Each label is flattened into ~260 leaf paths per document
(`services.specialist_visit.in_network.copay`, ...). Each gold/pred pair gets one outcome:

| Outcome | Meaning | Why it's tracked separately |
|---|---|---|
| correct / correct_null | match (numbers ±0.01, text normalized) | |
| wrong | both present, different | misread value |
| omission | gold has a value, pred is null | missed information |
| **hallucination** | gold is null, pred has a value | **invented information, the worst error for a benefits tool** |

Results are grouped by field type (money, percent, covered, deductible_applies, plan_info,
drug tier category), so a strong overall number can't hide weakness in, say, deductible flags.

Other metrics:
- **Lists** (`services_before_deductible`, `excluded_services`): precision/recall/F1 with fuzzy
  name matching, since "Cosmetic surgery" and "Cosmetic Surgery procedures" are the same item.
- **Notes**: free text, so only presence is scored (did the model add a note where gold has one?).
- **Drug tiers**: aligned by position. A missing tier scores all its fields as omissions.
- **Format**: JSON parse rate and strict schema-valid rate, reported separately from field accuracy.

### Design decisions

- **Schema-invalid but parseable JSON is still scored field by field.** One note over 150
  characters shouldn't zero out 250 correct fields. Format compliance is its own metric, and
  in serving, vLLM guided decoding enforces the schema anyway.
- **Unparseable output scores as all omissions** in `all_docs`; `parsed_docs` shows accuracy
  when the model produces JSON at all.
- **A null CostShare means "no benefit"**, the same as `covered=false`. The teacher uses both
  forms (47 vs. 367 times for out-of-network), so neither is penalized.
- **Sanity checks:** gold vs. gold = 100%. Teacher vs. gold flags exactly the 3 accepted corrections.
  Hand-made broken predictions (invalid JSON, missing service, fewer tiers, one wrong number)
  each produce the expected outcome.

## Caveats

- 10 documents means ~2,600 field comparisons. That's enough to see big gaps between models,
  not to separate models within ~1 percentage point.
- Until the PDF review is done, gold = teacher + corrections, so the **teacher's score is
  circular** and serves only as a ceiling reference.

## Baseline 1: Qwen3-4B-Instruct-2507, zero-shot (MLX 8-bit, M2 Pro)

Prompt = teacher instructions + the full JSON schema. Greedy decoding, no constrained decoding.

| Metric | Value |
|---|---|
| **Field accuracy (all fields)** | **75.2%** |
| Hallucination rate (gold null → model invents a value) | **35.7%** |
| money / percent / covered / deductible_applies | 68.4% / 74.5% / 91.0% / 68.5% |
| drug tier category | 60.3% |
| services_before_deductible F1 / excluded_services F1 | 65.8% / 94.5% |
| JSON parse rate / strict schema-valid rate | 100% / **20%** |
| Latency per doc (M2 Pro, MLX 8-bit) | ~184 s (prefill ~310 tok/s, decode ~26 tok/s, peak 7.2 GB) |

Per-document accuracy ranges from 58% (AmeriHealth NC, Health Advantage AR, HMSA HI) to 91% (Ambetter NE).

### Error analysis

1. **Zeros instead of nulls (265 of 475 hallucinations).** "20% coinsurance" comes out as
   `copay: 0, coinsurance_pct: 20`. The model knows the price but not the convention that
   "not applicable" is null. Counting these as correct would put the baseline at ~85%.
2. **Guessed deductible flags (120 hallucinations).** It says true or false where the SBC is
   silent. This is exactly the "never infer" rule a fine-tune has to learn.
3. **Drug tier segmentation.** BCBS Michigan came back with 17 tiers instead of 4 (it split
   retail and mail order and repeated rows); HMSA with 8 instead of 5. Each extra tier counts
   as a block of hallucinations.
4. **Format.** Every output parsed as JSON, but only 2 of 10 passed the schema, almost entirely
   due to notes over 150 characters.
5. **Genuinely invented numbers are rare** (~8 cells). The 4B model *reads* SBCs reasonably
   well; it mostly doesn't follow our conventions.

**Implications for Phase 3:** these are convention and structure errors, which SFT on teacher
labels targets directly. The fine-tune should also drop the ~1.7k-token schema from the
prompt (the model learns the shape) and shorten generation, which is the latency bottleneck
(~26 tok/s × ~3.8k tokens). Target: >95% field accuracy with <3% hallucination rate.
