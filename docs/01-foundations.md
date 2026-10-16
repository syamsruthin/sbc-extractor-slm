# Phase 0: Foundations

Run it yourself: `uv run python training/phase0_foundations.py`

## 1. Tokenization

A model sees integer token IDs, not text. Qwen3 averages ~3.4 characters per token
on SBC text.

**Qwen splits numbers into single digits**: `$18,400` → `$ 1 8 , 4 0 0`. This
matters for us because every dollar amount is generated one digit at a time, and a
wrong digit is a wrong answer. Numeric fields need their own accuracy metric in Phase 2.

**Budget rule:** an 8-page SBC is ~6–10k tokens. Your context length (`max_seq_length`)
has to fit prompt + answer, and activation memory grows with it.

## 2. Chat templates

Roles (`system`, `user`, `assistant`) are flattened into a single string with special
tokens (`<|im_start|>`, `<|im_end|>` for Qwen). Every model family has its own template.

**Rule:** train and serve with the **same** template. If training formats data one way
and vLLM formats requests another way, accuracy silently drops. Always use
`tokenizer.apply_chat_template`; never hand-build the string.

## 3. Loss masking

Fine-tuning is next-token prediction with cross-entropy loss. Labels are the input
IDs, except that prompt positions are set to `-100`, which the loss ignores.

- We only want the model to learn **prompt → JSON**, not to memorize SBC boilerplate.
- In our data, the prompt is ~90% of the tokens, so without masking most of the
  learning signal would be wasted.
- The `<|im_end|>` token **is** trained, so the model learns when to stop.
- In TRL this is `assistant_only_loss=True` (or `completion_only_loss` for
  prompt/completion datasets).

## 4. Memory math

Training memory = weights + gradients + optimizer state + activations.

| Setup (4B model) | Approx. memory before activations |
|---|---|
| Full fine-tune, bf16 + AdamW (~16 bytes/param) | ~60 GB |
| LoRA, frozen bf16 base | ~8 GB |
| QLoRA, frozen 4-bit base | ~2.5 GB |

- **LoRA** freezes the base model and learns small low-rank matrices: `W' = W + (α/r)·B·A`.
  Only ~1% of parameters get gradients and optimizer state.
- **QLoRA** also stores the frozen base in 4-bit NF4, then dequantizes it on the fly
  for each forward pass. The adapters themselves stay in 16-bit.
- **Activations** scale with batch × sequence length. Gradient checkpointing recomputes
  them in the backward pass instead of storing them (~30% slower, much less memory).

## Glossary

- **SFT**: supervised fine-tuning on (input, desired output) pairs.
- **PEFT**: parameter-efficient fine-tuning; LoRA is the most common method.
- **Distillation**: training a small "student" model on outputs from a big "teacher" model.
- **Epoch**: one full pass over the training data.
