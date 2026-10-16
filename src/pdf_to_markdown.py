"""Phase 1, step 2: convert SBC PDFs to Markdown and measure token lengths.

The model is trained on Markdown, not raw PDF: table structure survives as
pipe tables, which is what makes the cost-sharing rows readable.

    uv run python src/pdf_to_markdown.py
"""

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


def main() -> None:
    MD_DIR.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(TOKENIZER_ID)

    rows = []
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        with pymupdf.open(pdf) as doc:
            pages = doc.page_count
        md = pymupdf4llm.to_markdown(str(pdf), show_progress=False)
        (MD_DIR / f"{pdf.stem}.md").write_text(md)
        rows.append({
            "plan_id": pdf.stem,
            "pages": pages,
            "chars": len(md),
            "tokens": len(tok(md, add_special_tokens=False)["input_ids"]),
            "pipe_table_rows": md.count("\n|"),
            "has_coverage_examples": "Peg is Having a Baby".lower() in md.lower(),
        })

    stats = pd.DataFrame(rows)
    stats.to_csv(STATS, index=False)
    print(stats.describe().round(0).to_string())
    print(f"\nwith coverage examples found: {stats.has_coverage_examples.sum()}/{len(stats)}")
    print(f"no pipe tables (layout lost?): {(stats.pipe_table_rows == 0).sum()}/{len(stats)}")


if __name__ == "__main__":
    main()
