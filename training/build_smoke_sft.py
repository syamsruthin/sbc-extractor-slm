"""Phase 3: a tiny, memory-safe dataset for a LOCAL pipeline smoke test (not for real training).

Full examples are ~8k tokens with the answer at the end, so cutting them to a short
max-seq-length would remove the answer entirely. Instead this builds a coherent
mini-task: input = only the "Important Questions" section of each SBC (~1.5k tokens),
target = just its deductible and out-of-pocket amounts (taken from the v1.2 labels).
Every target is fully supported by its input, so nothing here teaches hallucination.

    uv run python training/build_smoke_sft.py
    uv run python training/mlx_smoke.py      # LoRA on Qwen3-0.6B with a memory watchdog
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from repair_amounts import first_section  # noqa: E402

SYSTEM = "Extract the deductible and out-of-pocket limit from this SBC section as minified JSON."
OUT = ROOT / "data/sft_smoke"


def example(plan_id: str) -> dict:
    label = json.loads((ROOT / "data/labels/v1.2" / f"{plan_id}.json").read_text())
    target = {k: label[k] for k in ("deductible", "out_of_pocket_limit")}
    md = first_section((ROOT / "data/markdown" / f"{plan_id}.md").read_text())
    return {"messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": md},
        {"role": "assistant", "content": json.dumps(target, separators=(",", ":"))},
    ]}


def main() -> None:
    manifest = json.loads((ROOT / "data/sft/manifest.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    for split, ids, n in (("train", manifest["train"], 80), ("valid", manifest["valid"], 12)):
        rows = [example(pid) for pid in ids[:n]]
        rows = [r for r in rows if len(r["messages"][1]["content"]) < 9000]  # ~2.5k tokens max
        with (OUT / f"{split}.jsonl").open("w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        print(f"{split}: {len(rows)} examples")


if __name__ == "__main__":
    main()
