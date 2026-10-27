"""Reject files the parser shouldn't try: not a PDF, too big, encrypted, scanned, or not an SBC."""

import re

import pymupdf

from sbcx.errors import AppError

SBC_SIGNALS = [
    (re.compile(r"summary\s+of\s+benefits\s+and\s+coverage", re.I), 0.30),
    (re.compile(r"important\s+questions", re.I), 0.25),
    (re.compile(r"common\s+medical\s+event|services\s+you\s+may\s+need", re.I), 0.25),
    (re.compile(r"specialist|primary\s+care|emergency\s+room", re.I), 0.20),
]


def check_pdf(data: bytes, max_mb: int = 10, max_pages: int = 20) -> int:
    """Validate an upload; returns the page count or raises AppError."""
    if not data.startswith(b"%PDF"):
        raise AppError("E_NOT_PDF", "The file is not a PDF.", 422)
    if len(data) > max_mb * 1024 * 1024:
        raise AppError("E_TOO_LARGE", f"The file is larger than {max_mb} MB.", 413, {"bytes": len(data)})
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:
        raise AppError("E_NOT_PDF", "The PDF could not be opened.", 422) from e
    with doc:
        if doc.needs_pass or doc.is_encrypted:
            raise AppError("E_ENCRYPTED", "The PDF is password-protected.", 422)
        n = doc.page_count
        if n > max_pages:
            raise AppError("E_TOO_LARGE", f"The PDF has more than {max_pages} pages.", 413, {"pages": n})
        text = "\n".join(doc[i].get_text() for i in range(min(n, 3)))
    if len(text.strip()) < 200:
        raise AppError(
            "E_NO_TEXT_LAYER", "The PDF has no text layer (scanned documents aren't supported yet).", 422
        )
    score = sum(w for rx, w in SBC_SIGNALS if rx.search(text))
    if score < 0.6:
        raise AppError(
            "E_NOT_SBC",
            "This doesn't look like a Summary of Benefits and Coverage (SBC) document.",
            422,
            {"score": round(score, 2)},
        )
    return n
