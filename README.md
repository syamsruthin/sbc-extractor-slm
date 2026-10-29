# SBC Plan Compare (v2)

Upload health plan **Summary of Benefits and Coverage (SBC)** PDFs, or pick 2026 marketplace plans,
and see what each plan really costs you. Python reads the SBC and does all the money math; an LLM
(via OpenRouter) only writes plain-language summaries and the final explanation, and a validator
rejects any number it wasn't given.

```
SBC PDF ─► deterministic parser (template-anchored) ─► BenefitsDocument (+ provenance, confidence)
              └─ low-confidence cells ─► LLM fallback (grounded)
BenefitsDocument ─► section summaries (LLM, grounded) ─► comparison + cost engine (no LLM)
               ─► fact sheet ─► explanation (LLM, numeric grounding, template fallback) ─► React UI
```

- Design: [docs/design/v2](docs/design/v2/README.md) (PRD, architecture, HLD, LLD, cost model, ADRs)
- Plan and status: [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)

## Run the app locally

Requirements: Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node 20+, and optionally poppler
(`brew install poppler`) for `pdftotext`, which the parser uses when present.

```bash
make setup                       # backend (uv sync) + frontend (npm install)
cp backend/.env.example backend/.env   # optional: add OPENROUTER_API_KEY (or keep it in the repo-root .env)
make dev                         # API on http://localhost:8000, UI on http://localhost:5173
```

Open http://localhost:5173, drop SBC PDFs on **My plans**, select two or more, and press **Compare**.
API docs: http://localhost:8000/docs.

Without an OpenRouter key the app still works: summaries and explanations fall back to templates
built from the computed numbers (`SBCX_LLM_MODE=off`). `SBCX_LLM_MODE=fake` gives deterministic
output for tests.

Optional: `SBCX_INTAKE_ENABLED=true` turns on "Describe your year" in the comparison builder (needs an
OpenRouter key; the description is never cached or stored). Saved comparisons can be deleted on the
**Saved** page, or purged by age with `SBCX_COMPARISON_RETENTION_DAYS` / `uv run sbcx purge-comparisons --days N`.

### Marketplace catalog (optional)

Needs the local SBC corpus in `data/raw/sbc_pdfs` and the CMS Plan Attributes PUF in `data/raw/puf/`
(see `src/collect_sbcs.py`).

```bash
make ingest-catalog              # extract every local SBC into the catalog (no LLM calls; ~10 min cold, ~2 min with a warm layout cache)
make load-premiums               # download the CMS 2026 Rate PUF (16 MB) and load premiums
```

### Tests and checks

```bash
make test                        # backend pytest (unit, property, integration; fake LLM) + frontend vitest
make lint                        # ruff, mypy, eslint, tsc
make e2e                         # Playwright: upload -> compare -> explanation (isolated backend, fake LLM)
make score                       # parser accuracy on the gold set and the reviewed v1.4 labels (eval/score.py)
# live LLM checks (spend a few cents of OpenRouter credit), run from backend/:
#   uv run python ../eval/explanations/check.py        claim checks over stored explanations
#   uv run python ../eval/intake/run.py                usage intake evaluation
make check-api-types             # frontend types match the backend OpenAPI spec
```

Tests that need SBC PDFs skip automatically when `data/raw` isn't present.

### Docker

```bash
docker compose up --build        # UI on http://localhost:8080
```

### Layout

```
backend/   FastAPI app (sbcx/): api/ -> services/ -> domain/ (parser, engine, explanation) <- infra/ (db, llm)
frontend/  React + TypeScript + Vite UI, API types generated from OpenAPI
config     backend/config/*.yaml: reference prices, scenarios, issuer brands
docs/      design docs (v2) and the learning notes from the fine-tuning phases
src/ eval/ training/   data collection, labeling, evaluation and the earlier SLM fine-tuning work
```

## Results (v2 parser)

| | Field acc. | Hallucination | Latency / doc |
|---|---|---|---|
| Teacher LLM (DeepSeek V4 Flash + repair) | 97.6% | 3.9% | ~50 s |
| Qwen3-4B zero-shot | 74.7% | 36.5% | ~184 s |
| **v2 deterministic parser** (gold, 10 docs) | **96.9%** | **2.4%** | ~3–8 s cold (PDF layout), < 0.1 s parse |
| v2 parser vs reviewed v1.4 labels (450 docs) | 98.7% agreement | 1.6% | 0 crashes on 1,829 PDFs |

---

# History: SBC Extractor — Fine-tuned SLM served with vLLM


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
| 1 | Data sourcing, schema design, distillation labeling | SBC download → Markdown → labeled dataset | Mac | ✅ 450 labeled + verified gold |
| 2 | Evaluation design | Eval harness + baselines (base SLM, frontier model) | Mac | ✅ harness, teacher + zero-shot baselines |
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
- **Dataset:** 450 labeled SBCs (390 train / 60 val) from 49 template families. Splits are by
  SBC-URL domain so no layout crosses train/val/test; the 10 gold families are excluded entirely.
  [Details](docs/06-dataset.md). Total labeling spend for the scale-up: **~$0.34**.
- **Two-pass extraction:** QA found the teacher dropping deductible/OOP amounts in ~40% of docs.
  A targeted re-ask of just those fields (~$0.00008/doc) fixed 778 values.
- **Label quality:** against the PDF-verified gold set, the teacher scores 97.6% field accuracy; its weak spot is inferring `deductible_applies` (8.8% hallucination).
- **Guideline v1.3, tested then rejected:** a stricter deductible rule scored *lower* on the gold
  set (96.5% vs 97.6%), so the labels stayed v1.2. The reliable fixes went into a deterministic
  normalizer instead. [Write-up](docs/04-labeling.md). Errors cluster in
  multi-part cells, which led to [annotation guideline v1.2](docs/04-labeling.md) plus a
  deterministic normalizer.

Learning notes for each step are in [docs/](docs/).

## Results

Field-level accuracy on the 10-document gold set (~2,700 fields). Details in [docs/05-evaluation.md](docs/05-evaluation.md).

| Model | Field acc. | Hallucination rate | Schema-valid | Latency / doc |
|---|---|---|---|---|
| Teacher: DeepSeek V4 Flash + repair pass (API) | 97.6% | 3.9% | 100% | ~50 s |
| Qwen3-4B-Instruct-2507, zero-shot (MLX 8-bit, M2 Pro) | 74.7% | 36.5% | 20% | ~184 s |
| Fine-tuned Qwen3-4B | _Phase 3_ | | | |

Gold set: 10 SBCs from 10 held-out template families, ~2,600 fields, every field verified
against the source PDF ([review notes](data/gold/README.md)).
