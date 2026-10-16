"""Phase 3: bundle everything the Kaggle run needs into one folder to upload as a Kaggle Dataset.

    uv run python training/package_kaggle.py --kaggle-user <your-kaggle-username>

Creates dist/kaggle-sbc-sft/ with:
  train.jsonl, valid.jsonl   SFT data (data/sft)
  gold/<plan_id>.md          the 10 gold SBC inputs (test only, never trained on)
  schema.json                SBCExtraction JSON schema, for guided decoding
  student_prompt.txt         the exact training/serving system prompt
  train_qlora.py, eval_gold_vllm.py, kaggle_qlora.ipynb
  dataset-metadata.json      for `kaggle datasets create -p dist/kaggle-sbc-sft` (optional)
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from schema import SBCExtraction  # noqa: E402
from student import STUDENT_SYSTEM_PROMPT  # noqa: E402

OUT = ROOT / "dist/kaggle-sbc-sft"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kaggle-user", default="YOUR-KAGGLE-USERNAME")
    args = parser.parse_args()

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "gold").mkdir(parents=True)
    for name in ("train.jsonl", "valid.jsonl"):
        shutil.copy(ROOT / "data/sft" / name, OUT / name)
    for label in sorted((ROOT / "data/gold/labels").glob("*.json")):
        shutil.copy(ROOT / "data/markdown" / f"{label.stem}.md", OUT / "gold" / f"{label.stem}.md")
    (OUT / "schema.json").write_text(json.dumps(SBCExtraction.model_json_schema()))
    (OUT / "student_prompt.txt").write_text(STUDENT_SYSTEM_PROMPT + "\n")
    for f in ("train_qlora.py", "eval_gold_vllm.py", "kaggle_qlora.ipynb"):
        shutil.copy(ROOT / "training" / f, OUT / f)
    (OUT / "dataset-metadata.json").write_text(json.dumps({
        "title": "SBC SFT (Qwen3-4B QLoRA)",
        "id": f"{args.kaggle_user}/sbc-sft",
        "licenses": [{"name": "CC0-1.0"}],
    }, indent=1))

    # Leakage guard: no gold plan may appear in the training data.
    gold = {p.stem for p in (OUT / "gold").glob("*.md")}
    train_ids = set(json.loads((ROOT / "data/sft/manifest.json").read_text())["train"])
    assert not gold & train_ids, f"gold docs in training data: {gold & train_ids}"

    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 2**20
    print(f"{OUT.relative_to(ROOT)}: {len(list(OUT.rglob('*')))} files, {size:.1f} MB")


if __name__ == "__main__":
    main()
