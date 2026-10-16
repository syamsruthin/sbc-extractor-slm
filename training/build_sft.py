"""Phase 3, step 1: build the supervised fine-tuning (SFT) dataset.

One chat example per labeled SBC: system (short student prompt) + user (SBC Markdown)
+ assistant (the teacher label as compact JSON). Written in the "messages" JSONL
format that both MLX-LM and Hugging Face TRL read directly.

Examples longer than --max-seq-length tokens (after the chat template) are dropped,
not truncated: a truncated SBC with a full label would teach the model to invent
the missing part.

    uv run python training/build_sft.py
"""

import argparse
import json
import random
import sys
from pathlib import Path

import pandas as pd
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from schema import SBCExtraction  # noqa: E402
from student import build_messages  # noqa: E402

LABEL_DIR = ROOT / "data/labels/v1.2"
MD_DIR = ROOT / "data/markdown"
OUT_DIR = ROOT / "data/sft"
TOKENIZER_ID = "Qwen/Qwen3-4B-Instruct-2507"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-seq-length", type=int, default=12288)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    tok = AutoTokenizer.from_pretrained(TOKENIZER_ID)
    splits = pd.read_csv(ROOT / "data/splits.csv").set_index("plan_id")
    out = {"train": [], "valid": []}
    dropped = []
    for path in sorted(LABEL_DIR.glob("*.json")):
        label = SBCExtraction.model_validate_json(path.read_text())
        messages = build_messages((MD_DIR / f"{path.stem}.md").read_text(), label.model_dump_json())
        # tokenize=False + explicit tokenize: in transformers v5, tokenize=True returns a
        # dict (len() would count its keys, not tokens).
        text = tok.apply_chat_template(messages, tokenize=False)
        n_tokens = len(tok(text, add_special_tokens=False)["input_ids"])
        if n_tokens > args.max_seq_length:
            dropped.append((path.stem, n_tokens))
            continue
        split = "valid" if splits.loc[path.stem, "split"] == "val" else "train"
        out[split].append({"messages": messages, "_tokens": n_tokens, "_plan_id": path.stem})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    random.Random(args.seed).shuffle(out["train"])
    for split, rows in out.items():
        with (OUT_DIR / f"{split}.jsonl").open("w") as f:
            for r in rows:
                f.write(json.dumps({"messages": r["messages"]}) + "\n")
        toks = [r["_tokens"] for r in rows]
        print(f"{split}: {len(rows)} examples | tokens/example median {sorted(toks)[len(toks) // 2]}, "
              f"max {max(toks)} | total {sum(toks) / 1e6:.2f}M tokens")
    print(f"dropped {len(dropped)} examples over {args.max_seq_length} tokens")
    (OUT_DIR / "manifest.json").write_text(json.dumps({
        "label_dir": str(LABEL_DIR.relative_to(ROOT)), "max_seq_length": args.max_seq_length,
        "train": [r["_plan_id"] for r in out["train"]], "valid": [r["_plan_id"] for r in out["valid"]],
        "dropped": dropped,
    }, indent=1))


if __name__ == "__main__":
    main()
