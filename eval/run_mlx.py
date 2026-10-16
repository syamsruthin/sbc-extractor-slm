"""Phase 2: run a local model with MLX on the gold docs and save its predictions.

Zero-shot baseline: the base model gets the same instructions as the teacher plus the
JSON schema in the prompt, since it hasn't learned the output shape. There's no
constrained decoding here, so JSON validity is measured as part of the baseline.

    uv run python eval/run_mlx.py --model mlx-community/Qwen3-4B-Instruct-2507-8bit --run qwen3-4b-zeroshot-8bit
    uv run python eval/score.py eval/predictions/qwen3-4b-zeroshot-8bit

    # a LoRA adapter trained with the short student prompt (training/build_sft.py):
    uv run python eval/run_mlx.py --model mlx-community/Qwen3-4B-Instruct-2507-4bit \
        --adapter-path training/runs/mlx-smoke --prompt student --run qwen3-4b-mlx-smoke
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from mlx_lm import load, stream_generate
from mlx_lm.sample_utils import make_sampler

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from label_sbcs import SYSTEM_PROMPT  # noqa: E402
from schema import SBCExtraction  # noqa: E402
from student import build_messages  # noqa: E402

GOLD_DIR = ROOT / "data/gold/labels"
MD_DIR = ROOT / "data/markdown"

ZERO_SHOT_PROMPT = (
    SYSTEM_PROMPT
    + "\n\nReturn ONLY a JSON object that matches this JSON Schema. Include every key. No prose, no code fences.\n"
    + json.dumps(SBCExtraction.model_json_schema(), separators=(",", ":"))
)


def extract_json(text: str) -> str:
    """Strip code fences / prose around the outermost JSON object, if any."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="mlx-community/Qwen3-4B-Instruct-2507-8bit")
    parser.add_argument("--run", required=True, help="name of eval/predictions/<run>")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--adapter-path", default=None, help="LoRA adapter dir from mlx_lm.lora")
    parser.add_argument("--prompt", choices=["zeroshot", "student"], default="zeroshot",
                        help="zeroshot = teacher rules + schema; student = the short fine-tuning prompt")
    args = parser.parse_args()

    run_dir = ROOT / "eval/predictions" / args.run
    (run_dir / "raw").mkdir(parents=True, exist_ok=True)
    model, tokenizer = load(args.model, adapter_path=args.adapter_path)
    sampler = make_sampler(temp=0.0)  # greedy: deterministic, standard for extraction evals

    plan_ids = [p.stem for p in sorted(GOLD_DIR.glob("*.json"))][: args.limit]
    for plan_id in plan_ids:
        if (run_dir / f"{plan_id}.json").exists():
            continue
        markdown = (MD_DIR / f"{plan_id}.md").read_text()
        messages = (build_messages(markdown) if args.prompt == "student" else
                    [{"role": "system", "content": ZERO_SHOT_PROMPT}, {"role": "user", "content": markdown}])
        prompt = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        start, text, last = time.time(), "", None
        for last in stream_generate(model, tokenizer, prompt, max_tokens=args.max_tokens, sampler=sampler):
            text += last.text
        stats = {
            "plan_id": plan_id,
            "model": args.model,
            "adapter": args.adapter_path,
            "prompt": args.prompt,
            "seconds": round(time.time() - start, 1),
            "prompt_tokens": last.prompt_tokens,
            "prompt_tps": round(last.prompt_tps, 1),
            "generation_tokens": last.generation_tokens,
            "generation_tps": round(last.generation_tps, 1),
            "peak_memory_gb": round(last.peak_memory, 2),
            "hit_max_tokens": last.generation_tokens >= args.max_tokens,
        }
        (run_dir / "raw" / f"{plan_id}.txt").write_text(text)
        (run_dir / f"{plan_id}.json").write_text(extract_json(text))
        with (run_dir / "_stats.jsonl").open("a") as f:
            f.write(json.dumps(stats) + "\n")
        print(json.dumps(stats), flush=True)


if __name__ == "__main__":
    main()
