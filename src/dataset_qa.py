"""Phase 1, step 8: QA the labeled training set before fine-tuning.

  - every label re-validates against the current schema
  - split / family coverage
  - rule-based flag rate (same checks as the gold review sheets), to compare
    against the gold set where flagged rows were reviewed by hand
  - training sequence lengths (prompt + SBC + compact JSON answer) in Qwen tokens,
    which decide max_seq_length for Phase 3

    uv run python src/dataset_qa.py
"""

import json
from collections import Counter
from pathlib import Path

import pandas as pd
from transformers import AutoTokenizer

from label_sbcs import LABEL_DIR
from review_sheet import SERVICE_ROWS, check, find_row, table_rows
from schema import SBCExtraction

ROOT = Path(__file__).resolve().parent.parent
MD_DIR = ROOT / "data/markdown"
TOKENIZER_ID = "Qwen/Qwen3-4B-Instruct-2507"
PROMPT_OVERHEAD = 120  # short student instruction + chat template tokens (no schema, see docs/03)


def main() -> None:
    tok = AutoTokenizer.from_pretrained(TOKENIZER_ID)
    splits = pd.read_csv(ROOT / "data/splits.csv").set_index("plan_id")
    rows, invalid = [], []
    for path in sorted(LABEL_DIR.glob("*.json")):
        try:
            label = SBCExtraction.model_validate_json(path.read_text())
        except ValueError as e:
            invalid.append((path.stem, str(e)[:120]))
            continue
        d = label.model_dump(mode="json")
        md = (MD_DIR / f"{path.stem}.md").read_text()
        md_rows = table_rows(md)
        flagged = found = 0
        for field, (pattern, nth) in SERVICE_ROWS.items():
            src = find_row(md_rows, pattern, nth)
            if not src:
                continue
            found += 1
            src_out = src[-2] if len(src) >= 3 else (src[1] if len(src) > 1 else "")
            flagged += bool(check(d["services"][field]["in_network"], src[0]) +
                            check(d["services"][field]["out_of_network"], src_out))
        cells = [c for s in d["services"].values() for c in s.values() if c]
        compact = label.model_dump_json()
        rows.append({
            "plan_id": path.stem,
            "split": splits.loc[path.stem, "split"],
            "family": splits.loc[path.stem, "family"],
            "input_tokens": len(tok(md, add_special_tokens=False)["input_ids"]),
            "output_tokens": len(tok(compact, add_special_tokens=False)["input_ids"]),
            "drug_tiers": len(d["drug_tiers"]),
            "notes": sum(c["note"] is not None for c in cells),
            "rows_found": found,
            "rows_flagged": flagged,
        })

    df = pd.DataFrame(rows)
    df["seq_tokens"] = df.input_tokens + df.output_tokens + PROMPT_OVERHEAD
    df.to_csv(ROOT / "data/dataset_qa.csv", index=False)

    print(f"labels: {len(df)} valid, {len(invalid)} invalid {invalid[:3]}")
    for split, part in df.groupby("split"):
        print(f"  {split}: {len(part)} docs, {part.family.nunique()} families, "
              f"max {part.family.value_counts().iloc[0]} docs/family")
    print("\ntoken lengths (Qwen):")
    print(df[["input_tokens", "output_tokens", "seq_tokens"]].describe(percentiles=[.5, .9, .95, .99]).round(0).to_string())
    for limit in (8192, 12288, 16384):
        print(f"  fit in max_seq_length={limit}: {(df.seq_tokens <= limit).mean():.1%}")
    print(f"\ndrug tiers per plan: {dict(sorted(Counter(df.drug_tiers).items()))}")
    print(f"notes per plan (median): {df.notes.median():.0f}")
    rate = df.rows_flagged.sum() / df.rows_found.sum()
    print(f"rule-based flags: {df.rows_flagged.sum()} of {df.rows_found.sum()} service rows ({rate:.1%}); "
          f"source rows found for {df.rows_found.sum() / (len(df) * len(SERVICE_ROWS)):.0%} of fields")
    print("most-flagged families:",
          df.groupby("family").apply(lambda g: g.rows_flagged.sum() / max(g.rows_found.sum(), 1))
            .sort_values(ascending=False).head(5).round(3).to_dict())


if __name__ == "__main__":
    main()
