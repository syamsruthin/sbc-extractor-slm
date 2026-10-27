# Architecture decision records (ADRs)

Format: context → decision → consequences. Status is "Proposed" until the design is approved.

## ADR-001 Deterministic extraction instead of SLM generation

- **Context.** Every SBC follows the CMS template: the same Important Questions, the same 26
  service rows in the same order, the same exclusions box. Generating ~2.3k tokens of JSON
  with an LLM took 50 s (teacher, 97.6%) to 184 s (4B zero-shot, 74.7%, 36.5% hallucination)
  per document. A regex/table prototype (`audit_tools/ext.py`) already produced the base
  labels for 1,379 documents, with about 4% of docs having a wrong value after
  family sweeps.
- **Decision.** Extract with template-anchored Python rules over pdfplumber tables and
  cleaned markdown. LLMs are not on the main extraction path.
- **Consequences.** Milliseconds of CPU per document, reproducible, no hallucinated values,
  provenance for free. Cost: rules need maintenance for new layouts. That's handled by
  the fallback (ADR-002) and per-family regression tests.

## ADR-002 LLM fallback is cell-scoped

- **Context.** Rules fail on a long tail of cell wordings and layouts, not whole documents.
- **Decision.** Only fields below a confidence threshold go to a small LLM, with the raw
  cell text and its row/column labels, under guided JSON decoding. Accept only results whose
  numbers appear in the raw text; reconcile with the parser guess.
- **Consequences.** ~150 tokens per cell instead of ~6k + 2.3k per document. The LLM can't
  invent values that aren't in the cell. The confidence threshold needs calibration.

## ADR-003 Keep `SBCExtraction` unchanged inside `BenefitsDocument v2`

- **Context.** 1,829 v1.4 labels, the gold set and `eval/score.py` all use v1 paths.
- **Decision.** Wrap v1 as `benefits`; put new data in `extras`, `provenance`, `summaries`.
- **Consequences.** All existing evaluation assets stay valid. Some new facts (limitations,
  deductible type) live outside the core model.

## ADR-004 No LLM arithmetic

- **Context.** Annual-cost comparisons need multi-step math (deductible, coinsurance, OOP cap,
  premiums, contributions). LLM errors here would be invisible and harmful.
- **Decision.** A deterministic engine computes every number the explanation may use,
  including differences between plans. The explanation LLM gets a fact sheet and may only
  restate its numbers. A grounding validator enforces this.
- **Consequences.** The engine must anticipate what the explanation needs (pairwise deltas,
  per-scenario totals). The LLM's job is narrower, so a smaller model can do it.

## ADR-005 Uncertainty becomes ranges, never guesses

- **Context.** `deductible_applies = null` is common (the gold conventions forbid inferring
  it), and family deductible type is often unclear.
- **Decision.** The engine computes low/high bounds and states the assumption. Overlapping
  ranges are reported as "depends".
- **Consequences.** Some answers are less crisp, but they're honest. The same philosophy as
  the three-valued flags in schema v1.

## ADR-006 Reference allowed amounts are configurable estimates

- **Context.** Copay vs coinsurance can't be compared without a price, and SBCs don't give prices.
- **Decision.** A versioned `reference_prices.yaml` with a source and date per value; users can override any price; every estimated comparison is marked.
- **Consequences.** Results depend on the table. The UI must make this visible.

## ADR-007 Summaries at ingestion, cached per document

- **Context.** Section summaries don't depend on the comparison, and the same catalog plan is compared many times.
- **Decision.** Generate summaries once per (hash, parser version, prompt version, model). Comparison doesn't wait for them.
- **Consequences.** Low marginal LLM cost per comparison; summaries go stale when prompts change (lazy recompute).

## ADR-008 Every LLM step has a non-LLM fallback

- **Decision.** Fallback extraction → keep parser guess + `needs_review`. Summaries →
  template sentences from JSON. Explanation → Jinja template from the fact sheet.
- **Consequences.** The product works (less fluently) with no LLM at all, which also makes
  testing and local development simpler.

## ADR-009 Retarget fine-tuning to small, narrow tasks

> **Update 2026-10-27: deferred.** All LLM steps use OpenRouter for now. This ADR describes the path if a self-hosted SLM is revisited.

- **Context.** Phase 3 (QLoRA on Kaggle) targeted full-document extraction, which ADR-001 replaces.
- **Decision.** Reuse the training stack for two narrow LoRA adapters on one small base model:
  1. **Cell fallback:** (raw cell text + row/column labels) → CostShare. Training pairs mined
     from v1.4 labels joined with the parser's raw cell text (~100k pairs).
  2. **Section summarizer:** (section JSON + limitations) → summary. Targets distilled from a
     stronger model, filtered by the grounding validator and judge.
  Serve both from one vLLM instance with multi-LoRA.
- **Consequences.** Training inputs are short (≤ 1k tokens), so the Mac OOM issue from
  full-length MLX training goes away and T4 runs are fast. The doc-level fine-tune can still
  be finished as a learning benchmark. **Open: Q4 in the PRD.**

## ADR-010 Provider-agnostic LLM client

- **Decision.** One `LLMClient` protocol with vLLM, OpenRouter and Anthropic providers; per-task routing in config; every call logged with tokens, latency and cost.
- **Consequences.** We can compare hosted models with the self-hosted SLM on the same eval sets and switch per task.

## ADR-011 Postgres JSONB (SQLite for MVP)

- **Decision.** Store documents and results as versioned JSON in relational tables.
- **Consequences.** Simple operations and queries (e.g. per-issuer quality); no separate document database.
