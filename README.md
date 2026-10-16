# SBC Extractor — Fine-tuned SLM served with vLLM

Fine-tune a small language model (3–4B) to extract structured data from
ACA **Summary of Benefits and Coverage (SBC)** documents, quantize it, and serve
it with **vLLM**. The extracted JSON powers a side-by-side health plan comparison.

**Goal:** match frontier-model extraction accuracy at a fraction of the cost and
latency, on hardware you control.

## Pipeline

```
SBC PDFs ──► Markdown (pymupdf4llm) ──► teacher-labeled JSON (DeepSeek V4 Flash) ──► LoRA/QLoRA SFT
   ──► eval vs baselines ──► merge + quantize (AWQ/GPTQ/FP8) ──► vLLM (structured outputs)
   ──► plan comparison app
```

## Roadmap

| Phase | Learn | Build | Where | Status |
|---|---|---|---|---|
| 0 | Tokenization, chat templates, loss masking, memory math | Notes in `docs/` | Mac | ✅ |
| 1 | Data sourcing, schema design, distillation labeling | SBC download → Markdown → labeled dataset | Mac | 🔄 gold review |
| 2 | Evaluation design | Eval harness + baselines (base SLM, frontier model) | Mac | ⏳ |
| 3 | LoRA, QLoRA, PEFT, TRL/Unsloth | Training runs (MLX on Mac to learn; CUDA for real runs) | Mac + Kaggle | ⏳ |
| 4 | Error analysis, sweeps, (optional) DPO | Improved model | Kaggle | ⏳ |
| 5 | Quantization: AWQ, GPTQ, FP8, GGUF | Accuracy / size / latency comparison table | Modal | ⏳ |
| 6 | vLLM internals: PagedAttention, continuous batching, guided decoding | OpenAI-compatible endpoint + load test | Modal | ⏳ |
| 7 | Productizing | Plan comparison UI, HF model card, write-up | Mac + HF | ⏳ |

See [docs/00-compute-plan.md](docs/00-compute-plan.md) for what runs where.

## Repo layout

```
data/        raw PDFs, markdown, labels (large files gitignored)
docs/        learning notes, one per phase
src/         pipeline code (parsing, labeling, schema)
eval/        evaluation harness and results
training/    training scripts and Kaggle notebooks
serving/     vLLM deployment (Modal)
app/         plan comparison UI
```

## Quickstart

```bash
uv sync
uv run python training/phase0_foundations.py   # tokenization, chat templates, loss masking, memory math
uv run python src/collect_sbcs.py --n 30       # CMS PUF -> issuer-diverse SBC PDF sample
uv run python src/pdf_to_markdown.py           # PDF -> Markdown + token stats
echo "OPENROUTER_API_KEY=..." > .env
uv run python src/label_sbcs.py                # teacher labels, schema-validated
uv run python src/review_sheet.py <plan_id>... # gold-set review sheets
uv run python src/build_gold.py                # gold labels = teacher labels + tracked corrections
```

## Progress so far

- **Data:** 14,476 unique medical SBC URLs from 184 issuers (CMS 2026 Plan Attributes PUF).
  Median SBC is 8 pages, ~5.7k tokens.
- **Schema:** [Pydantic](src/schema.py) covering deductibles, OOP limits, all 26 SBC template
  services, variable drug tiers and exclusions. One schema drives teacher labeling, training
  targets and vLLM guided decoding.
- **Teacher labeling:** DeepSeek V4 Flash via OpenRouter, using structured outputs, Pydantic
  validation and error-feedback retries. Cost: **~$0.0015 per document** (~$2 for 1,500).
- **Label quality:** first-pass gold review shows ~99% service-cell accuracy. Errors cluster in
  multi-part cells, which led to [annotation guideline v1.2](docs/04-labeling.md) plus a
  deterministic normalizer.

Learning notes for each step are in [docs/](docs/).

## Results

_Filled in as phases complete._
