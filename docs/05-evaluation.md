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
- The gold set is LLM-verified against the PDFs (see `data/gold/README.md`), not hand-verified
  by a person.

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

## Re-scored against the PDF-verified gold set (2026-10-17)

After all 10 gold documents were reviewed against their PDFs (63 corrections), the teacher
can be measured for real. Before this, gold *was* the teacher's labels, so the score was circular.

| Model | Field acc. | Halluc. rate | money | percent | deductible_applies | plan_info | excluded F1 |
|---|---|---|---|---|---|---|---|
| Teacher: DeepSeek V4 Flash (v1.1, single pass) | 97.1% | 3.9% | 97.4% | 98.2% | 93.7% | 88.0% | 98.1% |
| Teacher + deductible/OOP repair pass | **97.6%** | 3.9% | **99.1%** | 98.2% | 93.7% | 88.0% | 98.1% |
| Qwen3-4B zero-shot (MLX 8-bit) | 74.7% | 36.5% | 69.8% | 74.1% | 65.7% | 72.0% | 92.5% |

- **The repair pass is worth it:** money accuracy goes from 97.4% to 99.1% for ~$0.0001/doc.
- **The teacher's weak spot is `deductible_applies` (8.8% hallucination rate).** It infers
  "applies" or "doesn't apply" from the page-1 list instead of reading the row. Since the
  student learns from the teacher, the 390 training labels carry this noise too. Options before
  Phase 3: relabel with guideline v1.3 (the rule made explicit; ~$0.27 for 450 docs), or
  accept the noise and measure what the student learns.
- **plan_info (88%)** is mostly naming conventions (issuer prefix, underwriter vs brand), now
  written down as gold conventions for v1.3.
- **Qwen baseline barely moved (75.2% → 74.7%).** Some "hallucinations" became correct
  (LA/NC deductibles), while stricter deductible flags made others wrong. The gap the
  fine-tune has to close is ~23 points to teacher level.
