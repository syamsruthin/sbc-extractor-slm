"""One call from PDF to BenefitsDocument (deterministic part). The LLM fallback is applied on top
by services.extraction when enabled."""

from __future__ import annotations

from pathlib import Path

from sbcx.domain.benefits import BenefitsDocument
from sbcx.domain.extract.assemble import assemble
from sbcx.domain.parse.layout import LayoutDoc, get_layout
from sbcx.domain.parse.pipeline import ParseResult, parse_layout


def extract_pdf(
    pdf_path: str | Path,
    cache_dir: Path | None = None,
    sha256: str | None = None,
    issuer_id: str | None = None,
    issuer_hint: str | None = None,
    brands_path: str | None = None,
) -> tuple[BenefitsDocument, LayoutDoc, ParseResult]:
    layout = get_layout(pdf_path, cache_dir, sha256)
    res = parse_layout(
        layout, pdf_path, issuer_id=issuer_id, issuer_hint=issuer_hint, brands_path=brands_path
    )
    return assemble(layout, res, layout.page_texts), layout, res
