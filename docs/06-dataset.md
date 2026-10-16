# Phase 1: Scaling the dataset

```bash
uv run python src/build_splits.py --target 2000            # template families → train/val manifest
uv run python src/download_split.py --workers 12           # parallel, resumable, dedup by sha256
uv run python src/build_splits.py --topup 400              # replace docs lost to blocked hosts
uv run python src/download_split.py
uv run python src/pdf_to_markdown.py                       # parallel, incremental
uv run python src/label_sbcs.py --split train,val --budget 0.90 --workers 8
```

## Splitting by template family

Test-set leakage in document extraction usually comes from **layouts**, not from duplicate
plans. Many SBCs from one insurer come from one template, and some insurers publish under
several issuer IDs or brand names.

- **Family = registered domain of the SBC URL.** This catches links that names miss:
  HMO Louisiana and Blue Cross Blue Shield of Louisiana both publish on `lablue.com`; all
  Ambetter subsidiaries publish on `centene.com`.
- **Generic CDNs** (`cloudfront.net`, `windows.net`, `widen.net`, ...) host unrelated
  insurers, so for those the family is domain + brand.
- 77 families in total. **The 10 gold families are excluded entirely** (4,408 docs, including
  all Ambetter and Oscar plans). **6 random families are held out as validation.**
- Sampling is round-robin across families (≤30 docs/family), so UnitedHealthcare's 1,440
  plans don't swamp the 10-plan insurers.
- Possible leak: Health Advantage (gold) is an Arkansas Blue Cross subsidiary; Arkansas Blue
  Cross families on other domains may share its template.

## Download

| | Attempted | OK |
|---|---|---|
| train (initial) | 1,800 | 1,237 |
| train (top-up from reliable families) | 400 | 391 |
| val | 200 | 165 |
| **total** | 2,400 | **1,793** |

The ~30% loss isn't random. About **17 families block scripted downloads completely**
(HTTP 403, timeouts, HTML landing pages), so retrying is pointless. The top-up only draws
from families with ≥80% download success. 15 byte-identical PDFs were dropped as duplicates.

## Labeling under a hard budget ($0.95)

The OpenRouter key had $1.98 left and $1 had to stay on it.

1. **Provider pinning.** The same DeepSeek V4 Flash fp8 weights cost ~10x more on some
   providers. Routing to StreamLake/Baidu with a `max_price` cap cut cost from ~$0.0014 to
   **~$0.00076 per doc**.
2. **Minified JSON output** for the teacher (pretty-printing is pure output-token cost).
3. **Budget guard.** Spend is tracked from each response's `usage.cost`, because the key's
   usage endpoint lagged by 10+ minutes. New docs stop once spend + an in-flight reserve
   reaches the cap.
4. **Priority order.** 60 val docs first, then train round-robin across families. If the
   budget runs out, the labeled subset is still as diverse as possible.

## Result

Labeling was stopped at **450 docs** (decided mid-run: enough for a first fine-tune).

| | Docs | Families | Max docs/family |
|---|---|---|---|
| train | 390 | 44 | 10 |
| val | 60 | 5 | 12 |

- 450/450 labels valid, 0 failed calls. 427 of 433 logged calls went to StreamLake.
- **Total spend for this phase: ~$0.34** (labels ~$0.27, two repair passes ~$0.07),
  against the $0.95 cap. The key keeps ~$1.6.
- A kill mid-run lost the log's write buffer for 17 docs (their labels are fine, since a
  label is only written after validation). The log now flushes after every line.

## QA: the deductible / out-of-pocket problem

`src/dataset_qa.py` re-validates every label, checks coverage and sequence lengths, and runs
the same rule-based checks as the gold review sheets.

**Biggest finding:** the full-document teacher call returned **null for the deductible or OOP
limit in 366 places** (~40% of docs), even though every SBC states them on page 1. The same
failure was in the v1.1 labels (8/25) and therefore **in the gold set**. The gold review had
only checked flagged service rows, so it missed this. On HMO Louisiana, the "hallucinated"
deductible from the Qwen baseline was actually correct and the gold label was wrong.

**Fix: a targeted second pass** (`src/repair_amounts.py`):
- input = only the "Important Questions" section (~1.5k tokens), schema = only these two fields
- ~$0.00008 per doc, i.e. 1/8 of a full label
- fills nulls only; where both passes have a value, they agreed in all but 2 cases
  (left unchanged and listed)

Result: **778 amounts filled**. Of the 74 nulls left, 70 are genuine: the SBC says
"Not Applicable", almost all `-02` plan variants (zero cost-sharing plans for American
Indian / Alaska Native enrollees).

A bug in the repair pass, caught during QA: the section cut at the first "common medical"
text, but some SBCs say "See the Common Medical Events chart below" inside the deductible
row. It now cuts at the header row whose first cell is "Common Medical Event".

**Lessons:**
- A single huge structured-output call can silently drop fields. Field-level null-rate checks
  catch this; "valid JSON" doesn't.
- Two-pass extraction (full doc + targeted re-ask for critical fields) is cheap insurance.
- Gold review needs a checklist covering *every* field group, not just flagged rows.

## Other QA numbers

| | |
|---|---|
| Sequence length (prompt + SBC + compact JSON), median / p95 / max | 8.5k / 12.8k / 18.1k tokens |
| Fits in `max_seq_length` 8k / 12k / 16k | 42% / 94% / 98% |
| Drug tiers per plan | 4 (60%), 5 (22%), 6–8 (16%) |
| Rule-based flags on service rows | 17.3% (vs. ~7% on gold) |

The flag rate is mostly the checker, not the labels. Zero-cost-sharing variants make "No charge"
rows common, and the row matcher misfires on unfamiliar layouts (e.g. Wyoming BCBS:
the label was right, the matched source row was wrong). The worst families (Anthem/Wellpoint,
Cigna) are worth hand-checking before Phase 3.

**Phase 3 implications:** use `max_seq_length = 12288` and drop the 6% of longer docs (or
truncate the coverage-examples pages, which aren't in the schema). Also, CSR variants
(`-00`…`-06`) of one plan are near-duplicates, so sample weighting by base plan may help.
