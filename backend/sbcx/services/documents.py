"""Upload, extraction and read use cases for plan documents."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from sbcx.api.schemas import DocumentDetail, DocumentSummary
from sbcx.config import get_settings
from sbcx.domain.benefits import BenefitsDocument
from sbcx.domain.extract.fallback import resolve
from sbcx.domain.extract.run import extract_pdf
from sbcx.domain.parse.layout import sha256_bytes
from sbcx.domain.parse.pdf_guard import check_pdf
from sbcx.errors import AppError, not_found
from sbcx.infra.db import session_scope
from sbcx.infra.llm import get_llm
from sbcx.infra.models import DocumentRow
from sbcx.infra.repos import DocumentRepo
from sbcx.infra.storage import layout_cache_dir, pdf_path, save_pdf
from sbcx.logs import log
from sbcx.versions import PARSER_VERSION

logger = logging.getLogger("sbcx.documents")


def to_summary(row: DocumentRow) -> DocumentSummary:
    warnings = len((row.benefits or {}).get("warnings", []))
    return DocumentSummary(
        id=row.id,
        filename=row.filename,
        source=row.source,
        status=row.status,  # type: ignore[arg-type]
        error_code=row.error_code,
        error_message=row.error_message,
        plan_name=row.plan_name,
        issuer=row.issuer,
        plan_type=row.plan_type,
        npages=row.npages,
        doc_confidence=row.doc_confidence,
        summaries_status=row.summaries_status,  # type: ignore[arg-type]
        warning_count=warnings,  # type: ignore[arg-type]
        catalog_plan_id=row.catalog_plan_id,
        created_at=row.created_at,
    )


def to_detail(row: DocumentRow) -> DocumentDetail:
    b = BenefitsDocument.model_validate(row.benefits) if row.benefits else None
    return DocumentDetail(**to_summary(row).model_dump(), benefits=b)


def upload(filename: str, data: bytes) -> tuple[DocumentRow, bool]:
    """Validate and store an upload. Returns (row, needs_extraction)."""
    s = get_settings()
    npages = check_pdf(data, s.max_upload_mb, s.max_pages)
    sha = sha256_bytes(data)
    with session_scope() as sess:
        repo = DocumentRepo(sess)
        row = repo.by_sha(sha)
        if row is not None:
            stale = row.status == "failed" or (row.status == "ready" and row.parser_version != PARSER_VERSION)
            if row.source == "catalog":
                row.source = "upload"  # the user uploaded a catalog plan: show it in their list
            if not stale:
                return row, False
            row.status, row.error_code, row.error_message = "queued", None, None
            return row, True
        save_pdf(sha, data)
        row = repo.add(
            DocumentRow(sha256=sha, filename=Path(filename or "plan.pdf").name[:255], npages=npages)
        )
        return row, True


def _set(doc_id: str, **fields) -> None:
    with session_scope() as sess:
        row = DocumentRepo(sess).get(doc_id)
        if row is not None:
            for k, v in fields.items():
                setattr(row, k, v)


def extract_document(
    doc_id: str,
    issuer_id: str | None = None,
    issuer_hint: str | None = None,
    run_summaries: bool = True,
    pdf: Path | None = None,
) -> None:
    """Background job: PDF -> BenefitsDocument (+ LLM fallback), then section summaries."""
    s = get_settings()
    with session_scope() as sess:
        row = DocumentRepo(sess).get(doc_id)
        if row is None:
            return
        sha = row.sha256
    _set(doc_id, status="extracting")
    t0 = time.perf_counter()
    try:
        path = pdf or pdf_path(sha)
        doc, _, _ = extract_pdf(
            path,
            layout_cache_dir(),
            sha,
            issuer_id=issuer_id,
            issuer_hint=issuer_hint,
            brands_path=str(s.config_dir / "issuer_brands.json"),
        )
        if s.fallback_enabled:
            resolve(doc, get_llm(), s.model_fallback, s.confidence_threshold)
    except AppError as e:
        _set(doc_id, status="failed", error_code=e.code, error_message=e.message)
        return
    except Exception as e:
        logger.exception("extraction failed")
        _set(
            doc_id,
            status="failed",
            error_code="E_EXTRACTION_FAILED",
            error_message=f"The document could not be parsed ({type(e).__name__}).",
        )
        return
    b = doc.benefits
    _set(
        doc_id,
        status="ready",
        benefits=doc.model_dump(mode="json"),
        plan_name=b.plan_name,
        issuer=b.issuer,
        plan_type=b.plan_type,
        parser_version=PARSER_VERSION,
        doc_confidence=doc.doc_confidence,
        npages=doc.extras.npages,
        summaries_status="pending" if s.summaries_enabled else "skipped",
    )
    log(
        logger,
        "extracted",
        document_id=doc_id,
        ms=round((time.perf_counter() - t0) * 1000),
        fallback_cells=doc.fallback_cells,
        warnings=len(doc.warnings),
    )
    if run_summaries and s.summaries_enabled:
        from sbcx.services.summaries import generate_summaries

        generate_summaries(doc_id)


def get(doc_id: str) -> DocumentRow:
    with session_scope() as sess:
        row = DocumentRepo(sess).get(doc_id)
        if row is None:
            raise not_found("Document", doc_id)
        return row


def list_uploads() -> list[DocumentSummary]:
    with session_scope() as sess:
        return [to_summary(r) for r in DocumentRepo(sess).list_uploads()]


def delete(doc_id: str) -> None:
    with session_scope() as sess:
        repo = DocumentRepo(sess)
        row = repo.get(doc_id)
        if row is None:
            raise not_found("Document", doc_id)
        if row.source == "catalog" or row.catalog_plan_id:
            row.source = "catalog"  # keep catalog documents; just hide them from the upload list
            return
        repo.delete(row)
    p = pdf_path(row.sha256)
    p.unlink(missing_ok=True)


def require_ready(doc_id: str) -> BenefitsDocument:
    row = get(doc_id)
    if row.status != "ready" or not row.benefits:
        raise AppError(
            "E_NOT_READY",
            "The plan hasn't finished processing yet.",
            409,
            {"document_id": doc_id, "status": row.status},
        )
    return BenefitsDocument.model_validate(row.benefits)
