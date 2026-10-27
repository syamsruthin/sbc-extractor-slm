"""Local file storage for uploaded PDFs, addressed by sha256."""

from pathlib import Path

from sbcx.config import get_settings


def pdf_dir() -> Path:
    d = get_settings().var_dir / "pdfs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pdf_path(sha256: str) -> Path:
    return pdf_dir() / f"{sha256}.pdf"


def save_pdf(sha256: str, data: bytes) -> Path:
    p = pdf_path(sha256)
    if not p.exists():
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    return p


def layout_cache_dir() -> Path:
    return get_settings().var_dir / "cache" / "layout"
