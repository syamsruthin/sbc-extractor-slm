"""Export every sentence of every stored explanation for labeling (v2.1 T0.2).

    cd backend && uv run python ../eval/explanations/export.py [--db var/sbcx.db]

Writes eval/explanations/sentences.jsonl. Existing labels are kept for sentences already in the file.
A reviewer sets "label" to "correct", "incorrect" or "n/a" for each sentence that states a deductible or
coverage fact, and "rule" to the claim rule it falls under (C1-C5)."""

import argparse
import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "sentences.jsonl"
SENT = re.compile(r"(?<=[.!?])\s+")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="var/sbcx.db")
    args = ap.parse_args()
    old = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            r = json.loads(line)
            old[(r["comparison_id"], r["field"], r["sentence"])] = r
    con = sqlite3.connect(args.db)
    rows = con.execute(
        "select id, explanation from comparisons where explanation is not null order by created_at"
    ).fetchall()
    out = []
    for cid, raw in rows:
        c = json.loads(raw)["content"]
        fields = [("headline", c["headline"])] + [("key_points", t) for t in c["key_points"]]
        fields += [("scenarios", s["text"]) for s in c["scenarios"]] + [
            ("watch_out", t) for t in c["watch_out"]
        ]
        for field, text in fields:
            for sent in SENT.split(text):
                key = (cid, field, sent)
                out.append(
                    old.get(key)
                    or {"comparison_id": cid, "field": field, "sentence": sent, "label": None, "rule": None}
                )
    OUT.write_text("".join(json.dumps(r) + "\n" for r in out))
    print(f"{len(out)} sentences from {len(rows)} explanations -> {OUT}")


if __name__ == "__main__":
    main()
