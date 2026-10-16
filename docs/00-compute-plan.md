# Compute plan: what runs where

Local machine: Apple M2 Pro, 16 GB unified memory.

## Mac (free, always available)

- Data pipeline: download SBCs, convert PDF → Markdown, label, build the dataset.
- Eval harness and baselines.
- **MLX-LM LoRA** for learning: fast feedback on small models (e.g. Qwen3-1.7B,
  4-bit). 16 GB caps a 4B model with ~8k-token sequences, so the real runs go on a GPU.
- Plan comparison UI.

The Mac can't serve vLLM properly: vLLM is built for NVIDIA GPUs, and its Mac
support is experimental and CPU/Metal only. Run vLLM on a CUDA GPU.

## Kaggle (free: ~30 GPU-hours/week, T4×2 or P100, 12h sessions)

- Main QLoRA training runs (TRL + PEFT, or Unsloth).
- Can run "Save & Run All" in the background without a browser open.
- T4 limits: no bf16, no FlashAttention-2, no FP8. Use fp16 and it's fine for 3–4B QLoRA.

## Google Colab (free T4, not guaranteed)

- Backup for Kaggle; good for quick experiments.

## Modal (free: monthly starter credits)

- **vLLM serving**: deploy a real HTTPS, OpenAI-compatible endpoint with autoscaling.
- L4 GPUs (Ada) support **FP8**, so the quantization comparisons can be done here.
- Load testing and cost-per-1k-documents numbers.
- Closest to how production inference is run, which is why it's the best place to learn vLLM.

## Other free tools

- **Hugging Face Hub**: host the dataset and model with a model card.
- **Weights & Biases** (free tier): experiment tracking.
- **Teacher model for labels**: Gemini API free tier. Alternatively, the Claude
  Batch API costs a few dollars for ~1–2k documents.
- **CMS Exchange Public Use Files**: the source of SBC URLs.
