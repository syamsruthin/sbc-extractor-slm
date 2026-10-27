"""PDF -> LayoutDoc: the two views the parser reads, built once per document and cached by sha256.

- markdown view: pymupdf4llm markdown (same version that produced data/markdown), repaired the way
  audit_tools/mdclean.py did it: strike/mark tags removed, run-together tokens ("deductibledoes")
  split using word bigrams from the PDF text layer.
- table view: pdfplumber tables (first 12 pages) as pipe rows after the markdown header, the way
  audit_tools/ext.py load() did with EXTSRC=pdf.
Plus the exclusions-box words and the page-1 layout text (issuer footer).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pdfplumber
import pymupdf

LAYOUT_VERSION = "1"
_SEP = re.compile(r"(\s+|<br>|\*\*|\||<u>|</u>|<sup>|</sup>)")


@dataclass
class LayoutDoc:
    sha256: str
    npages: int
    md: str  # cleaned markdown view
    pdf_rows: str  # table view: markdown header + pdfplumber table rows as pipe rows
    page1_text: str
    excl: dict | None  # exclusions box (see exclusions.excl_box)
    md_fixes: int = 0
    version: str = LAYOUT_VERSION
    page_texts: list[str] = field(default_factory=list)  # plain text per page, for provenance

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str) -> LayoutDoc:
        return cls(**json.loads(s))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def layout_text(pdf_path: str | Path, first: int | None = None, last: int | None = None) -> str:
    """`pdftotext -layout` when poppler is installed (what the prototype used); pdfplumber otherwise."""
    if shutil.which("pdftotext"):
        cmd = ["pdftotext", "-layout"]
        if first:
            cmd += ["-f", str(first)]
        if last:
            cmd += ["-l", str(last)]
        return subprocess.run([*cmd, str(pdf_path), "-"], capture_output=True, text=True, timeout=60).stdout
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages[(first or 1) - 1 : last or len(pdf.pages)]
        return "\f".join((p.extract_text(layout=True) or "") for p in pages)


def raw_text(pdf_path: str | Path) -> str:
    """Plain text layer used for the token-split repair (`pdftotext` default mode, as the prototype)."""
    if shutil.which("pdftotext"):
        return subprocess.run(
            ["pdftotext", str(pdf_path), "-"], capture_output=True, text=True, timeout=60
        ).stdout
    with pymupdf.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc)


def page_texts(pdf_path: str | Path) -> list[str]:
    with pymupdf.open(pdf_path) as doc:
        return [page.get_text() for page in doc]


def clean_markdown(md: str, raw: str) -> tuple[str, int]:
    """Port of audit_tools/mdclean.py."""
    pw = raw.split()
    words = set(pw)
    big = set(zip(pw, pw[1:], strict=False))
    md = md.replace("~~", "")
    md = re.sub(r"</?mark>", "", md)

    def fix(core: str) -> str:
        if core in words:
            return core
        for i in range(1, len(core)):
            if (core[:i], core[i:]) in big:
                return core[:i] + " " + core[i:]
        for i in range(1, len(core) - 1):
            for j in range(i + 1, len(core)):
                a, b, c = core[:i], core[i:j], core[j:]
                if (a, b) in big and (b, c) in big:
                    return a + " " + b + " " + c
        return core

    out, fixes = [], 0
    for t in _SEP.split(md):
        if t and not _SEP.fullmatch(t):
            r = fix(t)
            fixes += r != t
            out.append(r)
        else:
            out.append(t)
    return "".join(out), fixes


def table_rows(md: str, tables_by_page: list[list[list[list[str | None]]]]) -> str:
    head = md.split("\n|", 1)[0]
    out = [head]
    for tabs in tables_by_page:
        for t in tabs:
            for r in t:
                out.append("|" + "|".join((c or "").replace("|", "/").replace("\n", "<br>") for c in r) + "|")
    return "\n".join(out)


def build_layout(pdf_path: str | Path, sha256: str | None = None) -> LayoutDoc:
    import pymupdf4llm

    from sbcx.domain.parse.exclusions import excl_box

    pdf_path = Path(pdf_path)
    sha = sha256 or sha256_bytes(pdf_path.read_bytes())
    md_raw = pymupdf4llm.to_markdown(str(pdf_path), show_progress=False)
    md, fixes = clean_markdown(md_raw, raw_text(pdf_path))
    tables: list = []
    with pdfplumber.open(pdf_path) as pdf:
        npages = len(pdf.pages)
        for pg in pdf.pages[:12]:
            tables.append(pg.extract_tables())
    return LayoutDoc(
        sha256=sha,
        npages=npages,
        md=md,
        pdf_rows=table_rows(md, tables),
        page1_text=layout_text(pdf_path, 1, 1),
        excl=excl_box(pdf_path),
        md_fixes=fixes,
        page_texts=page_texts(pdf_path),
    )


def get_layout(pdf_path: str | Path, cache_dir: Path | None, sha256: str | None = None) -> LayoutDoc:
    sha = sha256 or sha256_bytes(Path(pdf_path).read_bytes())
    if cache_dir is not None:
        f = cache_dir / f"{sha}.json"
        if f.exists():
            doc = LayoutDoc.from_json(f.read_text())
            if doc.version == LAYOUT_VERSION:
                if not doc.page_texts:  # caches written before page_texts existed
                    doc.page_texts = page_texts(pdf_path)
                    f.write_text(doc.to_json())
                return doc
    doc = build_layout(pdf_path, sha)
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{sha}.json").write_text(doc.to_json())
    return doc
