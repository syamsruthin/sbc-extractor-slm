"""Phase 1, step 2: convert SBC PDFs to Markdown and measure token lengths.

The model is trained on Markdown, not raw PDF: table structure survives as
pipe tables, which is what makes the cost-sharing rows readable.
Incremental (skips PDFs already converted) and parallel across CPU cores.

    uv run python src/pdf_to_markdown.py
"""

import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
import pymupdf
import pymupdf4llm
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "data/raw/sbc_pdfs"
MD_DIR = ROOT / "data/markdown"
STATS = ROOT / "data/markdown_stats.csv"
TOKENIZER_ID = "Qwen/Qwen3-4B-Instruct-2507"


def convert(pdf: Path) -> dict:
    try:
        with pymupdf.open(pdf) as doc:
            pages = doc.page_count
        md = pymupdf4llm.to_markdown(str(pdf), show_progress=False)
    except Exception as e:  # corrupt or encrypted PDFs: record and move on
        return {"plan_id": pdf.stem, "error": f"{type(e).__name__}: {e}"[:200]}
    (MD_DIR / f"{pdf.stem}.md").write_text(md)
    return {"plan_id": pdf.stem, "pages": pages}


def main() -> None:
    MD_DIR.mkdir(parents=True, exist_ok=True)
    todo = [p for p in sorted(PDF_DIR.glob("*.pdf")) if not (MD_DIR / f"{p.stem}.md").exists()]
    print(f"converting {len(todo)} PDFs on {os.cpu_count()} cores")
    with ProcessPoolExecutor() as pool:
        converted = list(pool.map(convert, todo, chunksize=4))
    errors = [c for c in converted if "error" in c]
    for e in errors:
        print("  failed:", e["plan_id"], e["error"])

    # Stats over every Markdown file (cheap to recompute; tokenizing is fast).
    tok = AutoTokenizer.from_pretrained(TOKENIZER_ID)
    rows = []
    for md_path in sorted(MD_DIR.glob("*.md")):
        md = md_path.read_text()
        rows.append({
            "plan_id": md_path.stem,
            "chars": len(md),
            "tokens": len(tok(md, add_special_tokens=False)["input_ids"]),
            "pipe_table_rows": md.count("\n|"),
            "has_coverage_examples": "peg is having a baby" in md.lower(),
        })
    stats = pd.DataFrame(rows)
    stats.to_csv(STATS, index=False)
    print(stats.describe(percentiles=[0.5, 0.9, 0.99]).round(0).to_string())
    print(f"\nno pipe tables (layout lost?): {(stats.pipe_table_rows == 0).sum()}/{len(stats)}")
    print(f"over 12k tokens: {(stats.tokens > 12000).sum()}/{len(stats)} | conversion failures: {len(errors)}")


if __name__ == "__main__":
    main()
