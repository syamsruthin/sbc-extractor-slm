# Phase 1: Data collection

```bash
uv run python src/collect_sbcs.py --n 30     # PUF → manifest → sample PDFs
uv run python src/pdf_to_markdown.py         # PDFs → Markdown + token stats
```

## Source: CMS Plan Attributes PUF (plan year 2026)

- `https://download.cms.gov/marketplace-puf/2026/plan-attributes-puf.zip` (1 MB zip, 32 MB CSV)
- 22,059 plan rows, 151 columns. The `URLForSummaryofBenefitsCoverage` column holds the SBC link.
- After removing dental-only plans and duplicate URLs: **14,476 unique medical SBCs from
  184 issuers in 30 states**. That's far more than the ~1–2k we need.
- Coverage is limited to HealthCare.gov states; state-run exchanges such as CA and NY aren't in it.

## Sampling

Round-robin across issuers: one plan per issuer first, then a second per issuer, and so
on. Diversity of layouts across insurers matters more than the number of documents. When we
build the train/test split, we'll **split by issuer** so the test set measures generalization
to layouts the model has never seen.

## First sample (30 plans)

- Downloaded 25/30. The rest were 4 HTTP errors and 1 HTML landing page instead of a PDF.
  Expect ~15% loss at scale.
- Every download is checked for the `%PDF` magic bytes and capped at 10 MB.

| | min | median | max |
|---|---|---|---|
| pages | 5 | 8 | 12 |
| tokens (Qwen3) | 4.2k | 5.7k | 11.2k |

**Context length decision:** `max_seq_length = 12288` covers every document plus a ~1k-token
JSON answer. On a T4 with QLoRA, that means batch size 1 with gradient accumulation and
gradient checkpointing.

## Markdown quality (pymupdf4llm)

- ✅ The main cost-sharing tables survive as pipe tables in all 25 docs: deductible,
  out-of-pocket (OOP) limit, copays, coinsurance and drug tiers.
- ⚠️ Spaces get lost at styling boundaries, e.g. `theout-of-pocket`, `deductibledoes not apply`.
  It's readable, and since the model trains on this exact input, it learns this quirk.
- ❌ The **coverage examples** page (Peg / Joe / Mia, laid out in 3 columns) comes out garbled
  and duplicated. Options: (a) leave those fields out of v1, (b) parse that page separately
  with a column-aware extractor, or (c) try Docling for that page. **Decision for v1: (a).**

## Next

1. Design the JSON schema (v1: plan basics, deductibles, OOP limits, ~15 common services,
   4 drug tiers, excluded services).
2. Label with a teacher model, and validate every label against the schema.
3. Hand-verify a gold test set of ~50 documents.
4. Scale up to ~1,500 documents.
