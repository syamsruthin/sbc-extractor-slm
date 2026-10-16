"""Phase 0: hands-on look at the four ideas every fine-tuning run depends on.

  1. Tokenization       - what the model actually sees
  2. Chat templates     - how a conversation becomes one string
  3. Loss masking       - which tokens the model is trained to predict
  4. Memory math        - why QLoRA fits where full fine-tuning doesn't

Only the tokenizer is downloaded (a few MB), not the model weights.

    uv run python training/phase0_foundations.py
"""

import json

from transformers import AutoTokenizer

MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"
IGNORE_INDEX = -100  # PyTorch cross-entropy skips labels with this value

tok = AutoTokenizer.from_pretrained(MODEL_ID)


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# ---------------------------------------------------------------------------
section("1. Tokenization")

line = "Specialist visit: $60 copay/visit; deductible does not apply. Out-of-network: 50% coinsurance"
ids = tok(line, add_special_tokens=False)["input_ids"]
print(f"text   : {line}")
print(f"tokens : {len(ids)} for {len(line)} chars (~{len(line) / len(ids):.1f} chars/token)")
print("pieces :", [tok.decode([i]) for i in ids])

# Numbers matter for us: see how dollar amounts are split.
for amount in ["$1,500", "$9,200", "$18,400"]:
    pieces = [tok.decode([i]) for i in tok(amount, add_special_tokens=False)["input_ids"]]
    print(f"{amount:>8} -> {pieces}")

# ---------------------------------------------------------------------------
section("2. Chat template")

target = {"specialist_visit": {"in_network": {"amount": 60, "type": "copay", "deductible_applies": False}}}
messages = [
    {"role": "system", "content": "Extract SBC fields as JSON."},
    {"role": "user", "content": line},
    {"role": "assistant", "content": json.dumps(target)},
]

full_text = tok.apply_chat_template(messages, tokenize=False)
prompt_text = tok.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
print("The model never sees 'roles' - only this one string with special tokens:\n")
print(full_text)

# ---------------------------------------------------------------------------
section("3. Loss masking (train on the answer, not the prompt)")

assert full_text.startswith(prompt_text), "prompt must be a prefix of the full conversation"
prompt_ids = tok(prompt_text, add_special_tokens=False)["input_ids"]
input_ids = tok(full_text, add_special_tokens=False)["input_ids"]
labels = [IGNORE_INDEX] * len(prompt_ids) + input_ids[len(prompt_ids):]

trained = sum(l != IGNORE_INDEX for l in labels)
print(f"total tokens   : {len(input_ids)}")
print(f"masked (-100)  : {len(prompt_ids)}  <- system + user prompt, no loss")
print(f"trained on     : {trained}  <- assistant JSON + end-of-turn token")
print("\nfirst trained tokens:", [tok.decode([t]) for t in input_ids[len(prompt_ids):][:12]])
print(
    "\nWhy: an SBC prompt is ~6-10k tokens and the JSON answer ~1k. Without masking,"
    "\nmost of the gradient would teach the model to reproduce SBC boilerplate"
    "\ninstead of how to extract from it."
)

# ---------------------------------------------------------------------------
section("4. Memory math for a 4B-parameter model (weights + training state only)")

P = 4e9
GB = 1024**3
lora_params = 33e6  # rough: rank-16 adapters on all attention + MLP projections

rows = [
    # name, weights, grads, optimizer (AdamW: 2 fp32 states + fp32 master copy)
    ("Full FT (bf16 + AdamW)", P * 2, P * 2, P * 12),
    ("LoRA (bf16 base, frozen)", P * 2, lora_params * 2, lora_params * 12),
    ("QLoRA (4-bit NF4 base)", P * 0.55, lora_params * 2, lora_params * 12),
    ("Inference only, bf16", P * 2, 0, 0),
    ("Inference only, 4-bit (AWQ)", P * 0.55, 0, 0),
]
print(f"{'setup':<30}{'weights':>10}{'grads':>10}{'optim':>10}{'total':>10}")
for name, w, g, o in rows:
    print(f"{name:<30}{w / GB:>9.1f}G{g / GB:>9.2f}G{o / GB:>9.2f}G{(w + g + o) / GB:>9.1f}G")
print(
    "\nActivations come on top and grow with sequence length x batch size."
    "\nGradient checkpointing trades ~30% extra compute to shrink them a lot."
    "\nThat's why a 16 GB T4 can QLoRA a 4B model on 8k-token SBCs, but not full-FT it."
)
