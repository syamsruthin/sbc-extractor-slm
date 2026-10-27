"""Build tests/cases/cells.jsonl: real price cells from the reviewed v1.4 docs whose parse matches the
reviewed label (PDF-checked), deduplicated by text. Locks in verified behavior for the cell rules.

    uv run python tests/mine_cells.py   # needs the local corpus and a warm layout cache
"""

import json
import random
import re
from pathlib import Path

from sbcx.cli import BRANDS, LAYOUT_CACHE, PDF_DIR, plan_ids
from sbcx.domain.parse.layout import get_layout
from sbcx.domain.parse.pipeline import parse_layout

V = Path(__file__).resolve().parents[2] / "data/labels/v1.4"
OUT = Path(__file__).resolve().parent / "cases/cells.jsonl"
KEYS = ("covered", "copay", "coinsurance_pct", "deductible_applies")


def main(n: int = 300) -> None:
    random.seed(7)
    seen, cases = set(), []
    for pid in plan_ids("v14"):
        layout = get_layout(PDF_DIR / f"{pid}.pdf", LAYOUT_CACHE)
        raw = parse_layout(layout, PDF_DIR / f"{pid}.pdf", issuer_id=pid[:5], brands_path=BRANDS).raw
        label = json.loads((V / f"{pid}.json").read_text())
        for key, (ins, oos, lim) in raw["_src"].items():
            if key.startswith("t"):
                continue
            for net, text, noteless in (("in_network", ins, False), ("out_of_network", oos, True)):
                exp, got = label["services"][key][net], raw["services"][key][net]
                # "covered as in-network" copies the in-network cell in build(), not in cost()
                if not text or text in seen or exp is None or got is None or re.search(r"(?i)covered as (an )?in-? ?network", text):
                    continue
                if any(exp[k] != got[k] for k in KEYS):
                    continue
                seen.add(text)
                cases.append({"id": f"{pid}:{key}:{net}", "text": text, "lim": lim, "noteless": noteless,
                              "expected": {k: exp[k] for k in KEYS}})
    random.shuffle(cases)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in sorted(cases[:n], key=lambda c: c["id"])) + "\n")
    print(f"{len(cases)} candidate cells, wrote {min(n, len(cases))} to {OUT}")


if __name__ == "__main__":
    main()
