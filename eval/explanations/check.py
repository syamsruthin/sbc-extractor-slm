"""Run the deductible/coverage claim checker (sbcx/domain/explain/claims.py) over every stored explanation
and, where sentences.jsonl has labels, report precision and recall (v2.1 T1.6).

    cd backend && uv run python ../eval/explanations/check.py [--db var/sbcx.db]"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

from sbcx.domain.comparison import ComparisonResult
from sbcx.domain.explain.claims import deductible_claims
from sbcx.domain.explain.generate import factsheet
from sbcx.domain.explanation import ExplanationRecord

HERE = Path(__file__).resolve().parent
QUOTE = re.compile(r'^\[(C\d)\] "(.*)" — ')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="var/sbcx.db")
    args = ap.parse_args()
    con = sqlite3.connect(args.db)
    flagged: set[tuple[str, str]] = set()
    n = skipped = 0
    for cid, res, exp in con.execute(
        "select id, result, explanation from comparisons where explanation is not null"
    ):
        result = ComparisonResult.model_validate(json.loads(res))
        if not any(c and c.deductible_status for d in result.services for c in d.cells.values()):
            skipped += 1  # engine 1.0 results carry no deductible status
            continue
        n += 1
        e = ExplanationRecord.model_validate(json.loads(exp)).content
        for v in deductible_claims(e, result, factsheet(result)):
            m = QUOTE.match(v)
            assert m, v
            flagged.add((cid, m.group(2)))
            print(f"{cid[:8]} {v}")
    print(
        f"\nchecked {n} explanations ({skipped} skipped: no deductible status), {len(flagged)} sentences flagged"
    )

    labels = HERE / "sentences.jsonl"
    rows = [json.loads(x) for x in labels.read_text().splitlines()] if labels.exists() else []
    labeled = [r for r in rows if r.get("label") in ("correct", "incorrect")]
    if not labeled:
        print("no labels yet in sentences.jsonl: precision/recall not computed")
        return
    bad = {(r["comparison_id"], r["sentence"].strip()) for r in labeled if r["label"] == "incorrect"}
    good = {(r["comparison_id"], r["sentence"].strip()) for r in labeled if r["label"] == "correct"}
    tp = len(flagged & bad)
    fp = len(flagged & good)
    print(f"labeled: {len(bad)} incorrect, {len(good)} correct")
    print(
        f"precision {tp / max(tp + fp, 1):.2f} ({tp}/{tp + fp}), recall {tp / max(len(bad), 1):.2f} ({tp}/{len(bad)})"
    )


if __name__ == "__main__":
    main()
