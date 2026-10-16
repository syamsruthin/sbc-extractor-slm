"""Phase 1, step 9: targeted second pass for deductible and out-of-pocket limit.

QA found the full-document teacher call often returns null for these two fields
(~40% of labels) even though every SBC states them on page 1. They're the most
important fields for plan comparison, so we re-extract them with a focused call:
input = only the "Important Questions" section (~1.5k tokens), schema = only these
two fields. It costs ~1/10 of a full label.

Results go to data/labels/repairs/<label_set>.jsonl; --apply then fills null
amounts in the labels. Where both passes give a value and they disagree, nothing
is changed and the case is listed for review.

    uv run python src/repair_amounts.py --labels data/labels/v1.2 --workers 8
    uv run python src/repair_amounts.py --labels data/labels/v1.2 --apply
"""

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from label_sbcs import BUDGET, DEFAULT_MODEL, MINIFIED, call_teacher, strict_schema
from schema import NetworkAmounts

ROOT = Path(__file__).resolve().parent.parent
MD_DIR = ROOT / "data/markdown"
REPAIR_DIR = ROOT / "data/labels/repairs"


class Amounts2(BaseModel):
    deductible: NetworkAmounts
    out_of_pocket_limit: NetworkAmounts


PROMPT = """From this section of a US health plan Summary of Benefits and Coverage (SBC),
extract the overall deductible and the out-of-pocket limit, for in-network and
out-of-network providers, individual and family amounts, as numbers in dollars.

- "Single", "self-only", "per person", "individual" -> individual.
- Plans with several in-network tiers: in_network = the first (lowest-cost) tier.
- Embedded amounts like "$3,000 individual / $6,000 family" -> 3000 and 6000.
- out_of_network is null if it says not applicable, unlimited, or not covered.
- Only use null when the amount is genuinely not stated.""" + MINIFIED

RESPONSE_FORMAT = {"type": "json_schema", "json_schema": {
    "name": "sbc_amounts", "strict": True, "schema": strict_schema(Amounts2.model_json_schema())}}


def first_section(md: str) -> str:
    """The 'Important Questions' table: everything before the services table.

    Cut at the services table's header row, whose FIRST cell is "Common Medical Event"
    (possibly with bold/<br> markup). The phrase also appears in intro text and inside
    the deductible row ("See the Common Medical Events chart below").
    """
    m = re.search(r"^\|[\s*_]*common(?:\s|\*|_|<br>)*medical", md, re.I | re.M)
    return md[: m.start() if m else 8000]


def repair_one(plan_id: str, api_key: str) -> dict:
    record = {"plan_id": plan_id}
    try:
        content, usage, provider = call_teacher(
            [{"role": "system", "content": PROMPT},
             {"role": "user", "content": first_section((MD_DIR / f"{plan_id}.md").read_text())}],
            DEFAULT_MODEL, api_key, response_format=RESPONSE_FORMAT)
        BUDGET.add(usage.get("cost", 0.0))
        record.update(Amounts2.model_validate_json(content).model_dump(mode="json"),
                      cost=usage.get("cost", 0.0), provider=provider)
    except (ValidationError, Exception) as e:  # noqa: BLE001 - log and continue
        record["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return record


def apply(label_dir: Path, repairs: dict[str, dict]) -> None:
    filled = conflicts = 0
    conflict_rows = []
    for plan_id, rep in repairs.items():
        path = label_dir / f"{plan_id}.json"
        if "error" in rep or not path.exists():
            continue
        label = json.loads(path.read_text())
        changed = False
        for field in ("deductible", "out_of_pocket_limit"):
            for net in ("in_network", "out_of_network"):
                old, new = label[field][net] or {}, rep[field][net] or {}
                for k in ("individual", "family"):
                    o, n = old.get(k), new.get(k)
                    if o is None and n is not None:
                        label[field][net] = {**dict.fromkeys(("individual", "family")), **old, k: n}
                        old = label[field][net]
                        filled += 1
                        changed = True
                    elif o is not None and n is not None and abs(o - n) > 0.01:
                        conflicts += 1
                        conflict_rows.append((plan_id, f"{field}.{net}.{k}", o, n))
        if changed:
            path.write_text(json.dumps(label, indent=2))
    print(f"filled {filled} null amounts; {conflicts} conflicts left unchanged")
    for row in conflict_rows[:20]:
        print("  conflict:", row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True, help="label dir, e.g. data/labels/v1.2")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--budget", type=float, default=0.10)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    label_dir = (ROOT / args.labels).resolve()
    REPAIR_DIR.mkdir(parents=True, exist_ok=True)
    out = REPAIR_DIR / f"{label_dir.name}.jsonl"
    done = {json.loads(line)["plan_id"]: json.loads(line) for line in out.open()} if out.exists() else {}

    if args.apply:
        return apply(label_dir, done)

    load_dotenv(ROOT / ".env")
    api_key = os.environ["OPENROUTER_API_KEY"]
    BUDGET.cap, BUDGET.reserve = args.budget, args.workers * 0.001
    todo = [p.stem for p in sorted(label_dir.glob("*.json"))
            if p.stem not in done or "error" in done[p.stem]]
    print(f"repairing {len(todo)} docs (budget ${args.budget})")

    def guarded(pid: str) -> dict | None:
        return None if BUDGET.exhausted() else repair_one(pid, api_key)

    with ThreadPoolExecutor(args.workers) as pool, out.open("a") as f:
        for rec in pool.map(guarded, todo):
            if rec:
                f.write(json.dumps(rec) + "\n")
                f.flush()
    recs = [json.loads(line) for line in out.open()]
    print(f"done: {sum('error' not in r for r in recs)} ok, {sum('error' in r for r in recs)} errors, "
          f"spent ${BUDGET.spent:.4f}")


if __name__ == "__main__":
    main()
