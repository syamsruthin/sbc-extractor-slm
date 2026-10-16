"""Phase 3: local LoRA pipeline smoke test (MLX) with a memory watchdog.

The first full-length MLX run took the whole Mac down (docs/07-finetuning.md). This one
uses a 0.6B model on the short smoke dataset (training/build_smoke_sft.py), and a watchdog
kills training if system free memory drops below --min-free-pct or the process grows past
--max-gb, so a mistake ends the run instead of the machine.

    uv run python training/mlx_smoke.py            # train
    uv run python training/mlx_smoke.py --eval     # base vs adapter on the smoke valid set
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_pct() -> int:
    out = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout
    m = re.search(r"free percentage:\s*(\d+)%", out)
    return int(m.group(1)) if m else 100


def rss_gb(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return int(out) / 2**20 if out else 0.0


def evaluate(model_id: str, adapter_path: str, data: str) -> None:
    """Exact match of the 8 deductible/OOP amounts: base model vs base + adapter."""
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    rows = [json.loads(line) for line in (ROOT / data / "valid.jsonl").open()]
    for name, adapter in (("base", None), ("base + LoRA", adapter_path)):
        model, tok = load(model_id, adapter_path=str(ROOT / adapter) if adapter else None)
        exact = parsed = 0
        for r in rows:
            prompt = tok.apply_chat_template(r["messages"][:-1], add_generation_prompt=True,
                                             tokenize=False, enable_thinking=False)
            text = generate(model, tok, prompt, max_tokens=200, sampler=make_sampler(temp=0.0))
            try:
                pred = json.loads(text[text.find("{"): text.rfind("}") + 1])
                parsed += 1
                exact += pred == json.loads(r["messages"][-1]["content"])
            except ValueError:
                pass
        print(f"{name:<12} valid JSON {parsed}/{len(rows)} | all 8 amounts exact {exact}/{len(rows)}")
        print(f"   last output: {text.strip()[:160]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="mlx-community/Qwen3-0.6B-4bit")
    parser.add_argument("--data", default="data/sft_smoke")
    parser.add_argument("--iters", type=int, default=40)
    parser.add_argument("--adapter-path", default="training/runs/smoke-0.6b")
    parser.add_argument("--min-free-pct", type=int, default=15)
    parser.add_argument("--max-gb", type=float, default=6.0)
    parser.add_argument("--eval", action="store_true", help="evaluate instead of training")
    args = parser.parse_args()
    if args.eval:
        return evaluate(args.model, args.adapter_path, args.data)

    cmd = [sys.executable, "-m", "mlx_lm", "lora", "--model", args.model, "--train", "--data", args.data,
           "--fine-tune-type", "lora", "--num-layers", "8", "--batch-size", "1", "--iters", str(args.iters),
           "--learning-rate", "2e-4", "--max-seq-length", "4096", "--grad-checkpoint", "--mask-prompt",
           "--steps-per-report", "5", "--steps-per-eval", "20", "--val-batches", "6",
           "--save-every", str(args.iters), "--adapter-path", args.adapter_path]
    log_path = ROOT / "training/runs/smoke-0.6b.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        peak_rss, min_free = 0.0, 100
        while proc.poll() is None:
            free, rss = free_pct(), rss_gb(proc.pid)
            peak_rss, min_free = max(peak_rss, rss), min(min_free, free)
            if free < args.min_free_pct or rss > args.max_gb:
                proc.kill()
                print(f"WATCHDOG: killed training (free {free}%, process {rss:.1f} GB)", flush=True)
                break
            time.sleep(2)
    print(f"exit {proc.wait()} | peak process RSS {peak_rss:.2f} GB | lowest system free {min_free}%")
    print(f"log: {log_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
