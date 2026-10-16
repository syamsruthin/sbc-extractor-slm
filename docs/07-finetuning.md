# Phase 3: Fine-tuning (LoRA / QLoRA)

```bash
uv run python training/build_sft.py               # labels -> data/sft/{train,valid}.jsonl
# local smoke test (Mac, MLX):
uv run mlx_lm.lora --model mlx-community/Qwen3-4B-Instruct-2507-4bit --train --data data/sft \
  --iters 30 --batch-size 1 --max-seq-length 12288 --grad-checkpoint --mask-prompt \
  --adapter-path training/runs/mlx-smoke
# real run (Kaggle T4, CUDA): training/train_qlora.py, see "Running on Kaggle" below
```

## The dataset

| | Examples | Median tokens | Total tokens |
|---|---|---|---|
| train | 376 | 8.2k | 3.23M |
| valid | 48 | 9.1k | 0.44M |

- One chat example per SBC: **system** (one-line student prompt, `src/student.py`) +
  **user** (SBC Markdown) + **assistant** (teacher label, compact JSON, ~2.5k tokens).
- The student prompt has **no guidelines and no schema**. The model learns the shape from
  examples, which saves ~2.5k prompt tokens on every request.
- 26 docs over 12,288 tokens were **dropped, not truncated**: a truncated SBC with a full
  label teaches the model to invent the missing rows.
- The validation docs come from 5 held-out template families, so validation loss measures
  generalization to unseen layouts.

## LoRA in one picture

A frozen weight matrix `W` (d × k) gets a trainable low-rank update:

```
W' = W + (alpha / r) · B · A        A: r × k (random init),  B: d × r (zero init)
```

- Because `B` starts at zero, training starts exactly at the base model.
- For a 2560 × 2560 projection at r = 16: 2 × 2560 × 16 = **82k** trainable parameters
  instead of 6.6M. Over all 7 projections in 36 layers that's ~33M parameters (~0.8% of 4B).
- `alpha / r` scales the update. Common practice is alpha = 2r, so the effective learning
  rate doesn't change when you change r.
- **Target modules:** all linear layers (`q,k,v,o` in attention + `gate,up,down` in the MLP).
  For format-heavy tasks like extraction, adapting the MLP matters, not just attention.
- After training, `B·A` can be **merged** into `W` (one model, no adapter overhead), or kept
  separate so one base model can serve several adapters (vLLM multi-LoRA, Phase 6).

## QLoRA: LoRA on a 4-bit base

- The frozen base model is stored in **4-bit NF4** ("normal float": quantization levels
  placed for normally distributed weights) with **double quantization** (the
  quantization constants are quantized too). 4B params → ~2.5 GB instead of 8 GB.
- For each forward pass, a layer's 4-bit weights are **dequantized on the fly** to the
  compute dtype (fp16 on a T4, bf16 on newer GPUs). LoRA `A`/`B` stay in 16/32-bit and are
  the only things with gradients.
- **Paged optimizers** move optimizer state to CPU RAM when GPU memory spikes.
- On the Mac, MLX does the same thing: `mlx_lm.lora` on a 4-bit model *is* QLoRA.

## Hyperparameters (first run) and why

| | Value | Why |
|---|---|---|
| Base model | Qwen3-4B-Instruct-2507 | Same as the zero-shot baseline (74.7%), so the gain is measurable |
| LoRA r / alpha / dropout | 16 / 32 / 0.05 | Standard starting point; extraction isn't a "new knowledge" task |
| Targets | all 7 linear projections | Format and convention learning lives in the MLP too |
| Learning rate | 2e-4, cosine, 5% warmup | Typical for LoRA (≈10x full fine-tuning) |
| Effective batch | 8 (1 × 8 grad accumulation) | 12k-token sequences only fit one at a time |
| Epochs | 2 (~94 optimizer steps) | Small dataset; watch validation loss for overfitting |
| Max sequence length | 12,288 | Covers 94% of docs (see docs/06) |
| Loss | assistant tokens only | ~70% of each sequence is SBC text we don't want to learn to write (docs/01) |
| Gradient checkpointing | on | Trades ~30% speed for a large cut in activation memory |

## The memory trap: logits

Weights (2.5 GB) and LoRA state (<1 GB) are easy. The surprise is the **output logits**:

```
12,288 tokens × 151,936 vocab × 4 bytes (fp32) ≈ 7.5 GB  — for ONE sequence
```

That alone nearly fills a 16 GB T4. The fix is a **fused linear + cross-entropy kernel**
(Liger kernel, `use_liger_kernel=True` in TRL; Unsloth has its own). It computes the loss in
chunks without ever materializing the full logits tensor.

## What to watch while training

- **Train loss** should fall fast in the first ~20 steps as the model learns the JSON shape,
  then flatten. A loss near 0 = memorizing.
- **Validation loss** on held-out families: if it rises while train loss falls, stop. That
  epoch is overfitting to the training layouts.
- **The real metric is the gold set**, not loss. Run `eval/` on the 10 gold docs: field
  accuracy, hallucination rate, schema-valid rate. Loss can improve while the
  `deductible_applies` habits (docs/04) stay the same.

## What happened on the Mac (16 GB): don't train full-length locally

The MLX smoke run (Qwen3-4B 4-bit, LoRA, 12,288-token sequences) loaded fine and computed
an initial **validation loss of 0.275**. The base model already finds much of the JSON
predictable, since the keys and structure repeat. Then the **first training step ran the
Mac out of memory and the machine restarted.** It's the logits trap above: MLX has no fused
cross-entropy kernel, so the backward pass needs the full 12k × 152k logits (and their
gradients) on top of the model, activations and optimizer state. 16 GB of unified memory
can't hold that.

Rule of thumb: on a 16 GB Mac, use MLX for **inference and evaluation** (the baseline used
7.2 GB peak), and run **training on a CUDA GPU** with a fused-loss kernel. A local training
run is only safe at a much shorter `--max-seq-length` (e.g. ≤ 4k) with a small model, which
can test the pipeline but tells you nothing about this task.

## Running on Kaggle (free T4)

1. **Bundle:** `uv run python training/package_kaggle.py --kaggle-user <you>` creates
   `dist/kaggle-sbc-sft/` (~13 MB): SFT data, the 10 gold inputs (test only; a leakage
   check asserts none are in train), `schema.json`, `student_prompt.txt`, both scripts and
   the notebook.
2. **Upload:** kaggle.com → *Datasets → New Dataset* → drag in the folder's contents → name
   it `sbc-sft` (keep it private).
3. **Notebook:** *Code → New Notebook → File → Import Notebook* → `kaggle_qlora.ipynb`.
   Settings: Accelerator **GPU T4**, Internet **on**, *Add Input* → your `sbc-sft` dataset.
4. Run the **dry run** cell first (5 steps: checks memory, and that the loss isn't `nan`).
   Then *Save Version → Save & Run All* for the full run, which keeps running with the tab closed.
5. Download `results.zip`, put `predictions/*` into `eval/predictions/`, and score with
   `eval/score.py`.

Things that may need adjusting on the first CUDA run (the scripts were written on a Mac):
- **fp16 overflow** (`loss: nan`): T4s have no bf16. Try `--lr 1e-4`. If it persists, load
  the base model with fp32 compute (slower).
- **Out of memory:** lower `--max-length` to 10240 (drops ~8% more docs), or reduce
  `--rank` to 8.
- **Library API drift:** TRL renames arguments between releases (e.g. `max_seq_length` →
  `max_length`). Read the error, and pin the version that works in the notebook.
