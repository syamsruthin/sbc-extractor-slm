# SBC Extractor — Fine-tuned SLM served with vLLM

Fine-tune a small language model (3–4B) to extract structured data from
ACA **Summary of Benefits and Coverage (SBC)** documents, quantize it, and serve
it with **vLLM**. The extracted JSON powers a side-by-side health plan comparison.

**Goal:** match frontier-model extraction accuracy at a fraction of the cost and
latency, on hardware you control.

## Pipeline

```
SBC PDFs ──► Markdown (Docling/PyMuPDF) ──► teacher-labeled JSON ──► LoRA/QLoRA SFT
   ──► eval vs baselines ──► merge + quantize (AWQ/GPTQ/FP8) ──► vLLM (structured outputs)
   ──► plan comparison app
```

## Roadmap

| Phase | Learn | Build | Where |
|---|---|---|---|
| 0 | Tokenization, chat templates, loss masking, memory math | Notes in `docs/` | Mac |
| 1 | Data sourcing, schema design, distillation labeling | SBC download → Markdown → labeled dataset | Mac |
| 2 | Evaluation design | Eval harness + baselines (base SLM, frontier model) | Mac |
| 3 | LoRA, QLoRA, PEFT, TRL/Unsloth | Training runs (MLX on Mac to learn; CUDA for real runs) | Mac + Kaggle |
| 4 | Error analysis, sweeps, (optional) DPO | Improved model | Kaggle |
| 5 | Quantization: AWQ, GPTQ, FP8, GGUF | Accuracy / size / latency comparison table | Modal |
| 6 | vLLM internals: PagedAttention, continuous batching, guided decoding | OpenAI-compatible endpoint + load test | Modal |
| 7 | Productizing | Plan comparison UI, HF model card, write-up | Mac + HF |

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

## Results

_Filled in as phases complete._
