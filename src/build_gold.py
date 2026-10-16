"""Phase 1, step 5: build the gold test set = teacher labels + human corrections.

Corrections live in data/gold/corrections.json (one entry per changed cell, with
a reason), so every gold edit is traceable and the build is re-runnable after
relabeling. Only corrections with status "accepted" are applied.

    uv run python src/build_gold.py
"""

import json
from pathlib import Path

from schema import SBCExtraction

ROOT = Path(__file__).resolve().parent.parent
# Frozen copy of the v1.1 teacher labels the review is based on, so relabeling
# data/labels never shifts the gold set underneath the corrections.
LABEL_DIR = ROOT / "data/gold/teacher_labels"
GOLD_DIR = ROOT / "data/gold"

GOLD_IDS = [
    "10091OR0780001-01",  # PacificSource  EPO  Gold
    "23552TN0020036-01",  # Oscar          EPO  Gold
    "13484NE0090009-00",  # Ambetter       EPO  Silver   (longest doc, 11k tokens)
    "11718TX0140020-01",  # Community HC   HMO  Silver
    "17414NC0010007-01",  # AmeriHealth    HMO  Bronze
    "13887FL0010004-00",  # 22 Health      HMO  Silver   (shortest doc, 5 pages)
    "19636LA0610013-00",  # HMO Louisiana  POS  Silver   (3-tier network)
    "13262AR0230010-00",  # Health Adv.    POS  Platinum
    "18350HI0880013-03",  # HMSA           PPO  Gold     (sub-row layout)
    "15560MI0350004-00",  # BCBS Michigan  PPO  Gold
]


def set_path(obj: dict, path: str, value) -> None:
    *parents, last = path.split(".")
    for key in parents:
        obj = obj[int(key)] if key.isdigit() else obj[key]
    obj[int(last) if last.isdigit() else last] = value


def main() -> None:
    corrections = json.loads((GOLD_DIR / "corrections.json").read_text())
    out_dir = GOLD_DIR / "labels"
    out_dir.mkdir(parents=True, exist_ok=True)
    for plan_id in GOLD_IDS:
        label = json.loads((LABEL_DIR / f"{plan_id}.json").read_text())
        applied = 0
        for c in corrections:
            if c["plan_id"] == plan_id and c["status"] == "accepted":
                set_path(label, c["path"], c["value"])
                applied += 1
        gold = SBCExtraction.model_validate(label)  # corrections must still fit the schema
        (out_dir / f"{plan_id}.json").write_text(gold.model_dump_json(indent=2))
        print(f"{plan_id:<20} {applied} corrections applied")
    pending = [c for c in corrections if c["status"] != "accepted"]
    print(f"\n{len(pending)} corrections not yet accepted")


if __name__ == "__main__":
    main()
